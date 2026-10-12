from datetime import datetime, timezone
from pathlib import Path
import re
import uuid
from fastapi import HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.schemas.document import (
    DEGREE_VARIANTS,
    DOCUMENT_DISPLAY_NAMES,
    DOCUMENT_TYPES,
    FRONTEND_ID_TO_TYPE,
    TYPE_TO_FRONTEND_ID,
    DocumentResponse,
    normalize_degree_variant,
    normalize_document_type,
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB limit
READ_CHUNK_SIZE = 64 * 1024  # 64 KiB bounded reading chunk


def get_storage_dir() -> Path:
    """Return absolute path to configured storage root and ensure it exists."""
    storage_dir = settings.storage_path
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def is_path_safe(base_dir: Path, target_path: Path) -> bool:
    """Ensure target_path does not escape base_dir (path traversal protection)."""
    try:
        resolved_base = base_dir.resolve()
        resolved_target = target_path.resolve()
        return resolved_target.is_relative_to(resolved_base)
    except Exception:
        return False


def sanitize_filename(name: str) -> str:
    """Sanitize original filename for safe metadata storage and display."""
    base = Path(name).name
    # Strip dangerous characters, control characters and limit length
    cleaned = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "_", base).strip()
    return cleaned[:120] if cleaned else "document"


def detect_file_signature(data: bytes) -> str | None:
    """
    Inspect magic bytes:
    - PDF: starts with b"%PDF-"
    - PNG: starts with standard PNG signature b"\\x89PNG\\r\\n\\x1a\\n"
    - JPEG: starts with b"\\xff\\xd8\\xff"
    """
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


async def read_and_validate_file(file: UploadFile) -> tuple[bytes, str, str]:
    """
    Read file stream with strict 10 MiB bounds.
    Validate signatures, extensions, and content types consistently.
    Returns: (file_bytes, detected_mime_type, normalized_extension)
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename",
        )

    ext = Path(file.filename).suffix.lower()
    allowed_exts = {".pdf", ".png", ".jpg", ".jpeg"}
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{ext}'. Only PDF, JPG, and PNG files are allowed.",
        )

    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = await file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size exceeds maximum allowable limit of 10MB.",
            )
        chunks.append(chunk)

    if total_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File cannot be empty.",
        )

    file_bytes = b"".join(chunks)
    detected_mime = detect_file_signature(file_bytes)
    if not detected_mime:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File signature does not match any allowed format (PDF, JPG, PNG) or content is malformed.",
        )

    # Cross-check detected signature with file extension
    ext_to_mimes = {
        ".pdf": {"application/pdf"},
        ".png": {"image/png"},
        ".jpg": {"image/jpeg", "image/jpg"},
        ".jpeg": {"image/jpeg", "image/jpg"},
    }
    if detected_mime not in ext_to_mimes.get(ext, set()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File extension '{ext}' does not match detected content signature ({detected_mime}).",
        )

    # Cross-check declared MIME if client provided one
    declared_mime = (file.content_type or "").lower().split(";")[0].strip()
    if declared_mime and declared_mime != "application/octet-stream":
        if declared_mime not in ext_to_mimes.get(ext, set()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Declared Content-Type '{declared_mime}' does not match file extension '{ext}'.",
            )

    return file_bytes, detected_mime, ext


def resolve_applicant_application(
    db: Database, current_user: dict, requested_app_id: str | None = None
) -> dict:
    """Resolve applicant's application server-side and enforce ownership."""
    user_id = str(current_user["_id"])
    applicant_id = current_user.get("applicant_id")

    query = {"$or": [{"userId": user_id}]}
    if applicant_id:
        query["$or"].append({"applicantId": applicant_id})

    app = db["applications"].find_one(query)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No application found for current applicant.",
        )

    if requested_app_id:
        if requested_app_id not in (app.get("applicationId"), app.get("applicantId")):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access documents for this application.",
            )

    return app


def to_document_response(doc: dict | None, application_id: str, doc_type: str) -> DocumentResponse:
    """Format MongoDB document record or empty logical slot into DocumentResponse."""
    name = DOCUMENT_DISPLAY_NAMES.get(doc_type, doc_type)
    frontend_id = TYPE_TO_FRONTEND_ID.get(doc_type, doc_type.lower())

    if doc is None:
        return DocumentResponse(
            documentId=None,
            id=frontend_id,
            applicationId=application_id,
            userId=None,
            applicantId=None,
            documentType=doc_type,
            documentVariant=None,
            name=name,
            originalFileName=None,
            fileName=None,
            contentType=None,
            fileSize=None,
            status="NOT_UPLOADED",
            required=True,
            uploadedAt=None,
            updatedAt=None,
        )

    return DocumentResponse(
        documentId=doc.get("documentId"),
        id=frontend_id,
        applicationId=doc.get("applicationId", application_id),
        userId=doc.get("userId"),
        applicantId=doc.get("applicantId"),
        documentType=doc.get("documentType", doc_type),
        documentVariant=doc.get("documentVariant"),
        name=name,
        originalFileName=doc.get("originalFileName"),
        fileName=doc.get("originalFileName"),
        contentType=doc.get("contentType"),
        fileSize=doc.get("fileSize"),
        status=doc.get("status", "UPLOADED"),
        required=True,
        uploadedAt=doc.get("uploadedAt"),
        updatedAt=doc.get("updatedAt"),
    )


async def upload_document(
    db: Database,
    current_user: dict,
    file: UploadFile,
    document_type_raw: str,
    document_variant_raw: str | None = None,
    requested_app_id: str | None = None,
) -> DocumentResponse:
    """
    Handle document upload or replacement.
    Enforces ownership, validation, degree variants, safe storage and rollback on failure.
    """
    if current_user.get("role") != "applicant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only applicants are permitted to upload documents.",
        )

    # Normalize and validate documentType
    try:
        doc_type = normalize_document_type(document_type_raw)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Validate degreeVariant
    if doc_type == "DEGREE_CERTIFICATE":
        if not document_variant_raw:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A valid documentVariant is required for DEGREE_CERTIFICATE: "
                + ", ".join(DEGREE_VARIANTS),
            )
        try:
            doc_variant = normalize_degree_variant(document_variant_raw)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    else:
        if document_variant_raw and document_variant_raw.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"documentVariant is not allowed for document type {doc_type}.",
            )
        doc_variant = None

    # Resolve applicant's application server-side
    app = resolve_applicant_application(db, current_user, requested_app_id)
    application_id = app["applicationId"]
    user_id = str(current_user["_id"])
    applicant_id = current_user.get("applicant_id")

    # Read and validate upload content
    try:
        file_bytes, detected_mime, ext = await read_and_validate_file(file)
    finally:
        await file.close()

    storage_dir = get_storage_dir()
    document_id = f"doc_{uuid.uuid4().hex[:12]}"
    stored_filename = f"{document_id}_{uuid.uuid4().hex[:8]}{ext}"
    target_path = storage_dir / stored_filename

    if not is_path_safe(storage_dir, target_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Storage path security validation failed.",
        )

    # Safe write to disk
    try:
        with open(target_path, "wb") as f:
            f.write(file_bytes)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to write file to storage.",
        )

    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "documentId": document_id,
        "applicationId": application_id,
        "userId": user_id,
        "applicantId": applicant_id,
        "documentType": doc_type,
        "documentVariant": doc_variant,
        "originalFileName": sanitize_filename(file.filename),
        "storedFileName": stored_filename,
        "contentType": detected_mime,
        "fileSize": len(file_bytes),
        "status": "UPLOADED",
        "uploadedAt": now,
        "updatedAt": now,
        "storagePath": str(target_path.resolve()),
    }

    # Atomic single active slot handling
    existing = db["documents"].find_one(
        {"applicationId": application_id, "documentType": doc_type}
    )

    if existing:
        old_stored_filename = existing.get("storedFileName")
        metadata["uploadedAt"] = existing.get("uploadedAt", now)
        try:
            # Compare-and-swap: condition on matching record ID and expected storedFileName
            cas_query = {"_id": existing["_id"]}
            if old_stored_filename:
                cas_query["storedFileName"] = old_stored_filename

            result = db["documents"].replace_one(cas_query, metadata)
            if result.matched_count == 0:
                # Concurrent modification/replacement conflict
                target_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Document replacement conflict: document was modified or replaced concurrently. Please retry.",
                )
        except HTTPException:
            raise
        except Exception:
            # Compensating rollback: remove newly written file so storage remains clean
            target_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while replacing document metadata.",
            )

        # Clean up old file only after successful database replacement
        if old_stored_filename:
            old_path = storage_dir / old_stored_filename
            if is_path_safe(storage_dir, old_path) and old_path.exists():
                try:
                    old_path.unlink()
                except Exception:
                    pass
    else:
        try:
            db["documents"].insert_one(metadata)
        except DuplicateKeyError:
            # Concurrent upload into same slot
            target_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A document is already being uploaded for this slot.",
            )
        except Exception:
            target_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while persisting document metadata.",
            )

    return to_document_response(metadata, application_id, doc_type)


def list_documents(
    db: Database, current_user: dict, requested_app_id: str | None = None
) -> list[DocumentResponse]:
    """
    List the six logical slots for an authorized application.
    Admins can query an application by ID.
    Applicants query their own application.
    """
    user_role = current_user.get("role")

    if user_role == "applicant":
        app = resolve_applicant_application(db, current_user, requested_app_id)
        application_id = app["applicationId"]
    elif user_role == "admin":
        if requested_app_id:
            app = db["applications"].find_one(
                {"$or": [{"applicationId": requested_app_id}, {"applicantId": requested_app_id}]}
            )
            if not app:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Application not found.",
                )
            application_id = app["applicationId"]
        else:
            # Admin general listing: return all uploaded document metadata across applications
            docs = list(db["documents"].find({}, {"storagePath": 0, "storedFileName": 0}))
            results = []
            for d in docs:
                dtype = d.get("documentType", "")
                results.append(to_document_response(d, d.get("applicationId", ""), dtype))
            return results
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role.",
        )

    existing_docs = {
        d["documentType"]: d
        for d in db["documents"].find({"applicationId": application_id})
    }

    results: list[DocumentResponse] = []
    for dtype in DOCUMENT_TYPES:
        doc = existing_docs.get(dtype)
        results.append(to_document_response(doc, application_id, dtype))

    return results


def get_document_metadata(
    db: Database, current_user: dict, document_id: str
) -> DocumentResponse:
    """Retrieve metadata for a single document, verifying ownership."""
    doc = db["documents"].find_one({"documentId": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    user_role = current_user.get("role")
    if user_role == "applicant":
        user_id = str(current_user["_id"])
        if doc.get("userId") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this document.",
            )
    elif user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role.",
        )

    return to_document_response(doc, doc.get("applicationId", ""), doc.get("documentType", ""))


def get_document_file(
    db: Database, current_user: dict, document_id: str
) -> FileResponse:
    """Safely stream stored document binary file, verifying ownership."""
    doc = db["documents"].find_one({"documentId": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    user_role = current_user.get("role")
    if user_role == "applicant":
        user_id = str(current_user["_id"])
        if doc.get("userId") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this document.",
            )
    elif user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role.",
        )

    storage_dir = get_storage_dir()
    stored_filename = doc.get("storedFileName")
    if not stored_filename:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File record is missing storage filename.",
        )

    file_path = storage_dir / stored_filename
    if not is_path_safe(storage_dir, file_path) or not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored physical document not found.",
        )

    return FileResponse(
        path=file_path,
        media_type=doc.get("contentType", "application/octet-stream"),
        filename=doc.get("originalFileName", "document"),
    )


def delete_document(
    db: Database, current_user: dict, document_id: str
) -> dict:
    """
    Remove logical document and physical file.
    Only applicant can delete their own documents. Admins are prohibited.
    """
    user_role = current_user.get("role")
    if user_role != "applicant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin deletion of documents is not permitted.",
        )

    doc = db["documents"].find_one({"documentId": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    user_id = str(current_user["_id"])
    if doc.get("userId") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this document.",
        )

    # Remove from MongoDB
    db["documents"].delete_one({"_id": doc["_id"]})

    # Remove physical file from storage
    storage_dir = get_storage_dir()
    stored_filename = doc.get("storedFileName")
    if stored_filename:
        file_path = storage_dir / stored_filename
        if is_path_safe(storage_dir, file_path) and file_path.exists():
            try:
                file_path.unlink()
            except Exception:
                pass

    return {
        "detail": "Document deleted successfully.",
        "documentId": document_id,
    }
