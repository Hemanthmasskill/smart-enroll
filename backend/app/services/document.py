from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from typing import Any
import uuid
from fastapi import HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

from bson import ObjectId
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
from app.schemas.document_processing import DocumentProcessingResult
from app.schemas.verification import (
    AuthoritativeVerificationRecord,
    DocumentValidationResult,
    DocumentVerificationDetailsResponse,
)
from app.services.ocr import OCREngine, run_document_processing_pipeline
from app.services.verification import (
    SyntheticAuthoritativeVerificationProvider,
    validate_document_content,
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
            validationStatus=None,
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
        processingStatus=doc.get("processingStatus"),
        processingConfidence=doc.get("processingConfidence"),
        validationStatus=doc.get("validationStatus", "NOT_RUN"),
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


def process_document(
    db: Database,
    current_user: dict,
    document_id: str,
    engine: OCREngine | None = None,
    run_id: str | None = None,
) -> DocumentProcessingResult:
    """
    Run bounded OCR, classification, and field extraction for an uploaded document.
    Enforces ownership (applicant owns document, or admin allowed).
    Concurrency: rejects if document is already in PROCESSING state.
    Updates MongoDB document record with processingResult and processingStatus without changing document status to VERIFIED.
    Preserves original uploaded physical file intact.
    """
    doc = db["documents"].find_one({"documentId": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    # 1. Enforce applicant role and document ownership
    if current_user.get("role") != "applicant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only applicants are permitted to process documents.",
        )

    user_id = str(current_user["_id"])
    if doc.get("userId") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to process this document.",
        )

    # 2. Fast in-memory check for early, user-friendly conflict response
    if doc.get("processingStatus") == "PROCESSING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document processing is currently in progress. Please retry after it completes.",
        )

    storage_dir = get_storage_dir()
    stored_filename = doc.get("storedFileName")
    if not stored_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document file is missing or has not been uploaded yet.",
        )

    file_path = storage_dir / stored_filename
    if not is_path_safe(storage_dir, file_path) or not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored physical document not found for processing.",
        )

    # Read binary bytes for processing (original file is strictly read-only and preserved)
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read document from storage.",
        )

    # 3. Atomic conditional claim in MongoDB before starting OCR pipeline
    now = datetime.now(timezone.utc).isoformat()
    claim_filter: dict[str, Any] = {
        "_id": doc["_id"],
        "processingStatus": {"$ne": "PROCESSING"},
    }
    claim_set: dict[str, Any] = {
        "processingStatus": "PROCESSING",
        "updatedAt": now,
    }
    if run_id:
        app_id = doc.get("applicationId")
        if app_id:
            app = db["applications"].find_one({"applicationId": app_id})
            if not app or app.get("activeRunId") != run_id or run_id in app.get("supersededRunIds", []):
                current_active = app.get("activeRunId") if app else None
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Execution ownership lost for run '{run_id}'. Application active run is '{current_active}'.",
                )
        claim_filter["supersededRunIds"] = {"$ne": run_id}
        claim_filter["$or"] = [
            {"activeRunId": {"$exists": False}},
            {"activeRunId": None},
            {"activeRunId": run_id},
            {"activeRunId": {"$regex": "^superseded-", "$ne": f"superseded-{run_id}"}},
        ]
        claim_set["activeRunId"] = run_id

    try:
        claim_result = db["documents"].update_one(
            claim_filter,
            {"$set": claim_set},
        )
    except Exception as e:
        logger.error(
            "Database error while claiming document %s for processing: %s",
            document_id,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to initiate document processing due to a server error. Please try again later.",
        )

    if claim_result.matched_count == 0:
        # Check if the document was deleted concurrently
        current_doc = db["documents"].find_one({"_id": doc["_id"]})
        if not current_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found.",
            )
        if run_id and (
            current_doc.get("activeRunId") == f"superseded-{run_id}"
            or (
                current_doc.get("activeRunId")
                and not str(current_doc.get("activeRunId", "")).startswith("superseded-")
                and current_doc.get("activeRunId") != run_id
            )
            or run_id in current_doc.get("supersededRunIds", [])
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Execution ownership lost for run '{run_id}'. Document ownership token is '{current_doc.get('activeRunId')}'.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document processing is currently in progress. Please retry after it completes.",
        )

    content_type = doc.get("contentType", "application/pdf")
    doc_type = doc.get("documentType", "10TH_MARKSHEET")
    app_id = doc.get("applicationId")

    try:
        result = run_document_processing_pipeline(
            file_bytes=file_bytes,
            content_type=content_type,
            document_id=document_id,
            document_type=doc_type,
            application_id=app_id,
            engine=engine,
        )
    except Exception as e:
        logger.error(
            "Fatal error during document processing pipeline for document %s: %s",
            document_id,
            str(e),
            exc_info=True,
        )
        now_err = datetime.now(timezone.utc).isoformat()
        err_filter: dict[str, Any] = {"_id": doc["_id"]}
        if run_id:
            err_filter["activeRunId"] = run_id
            err_filter["supersededRunIds"] = {"$ne": run_id}

        try:
            err_update_res = db["documents"].update_one(
                err_filter,
                {
                    "$set": {
                        "processingStatus": "FAILED",
                        "updatedAt": now_err,
                    }
                },
            )
            if run_id and err_update_res.matched_count == 0:
                logger.warning(
                    "Execution ownership lost for run %s on document %s during fatal pipeline error handling; document status untouched.",
                    run_id,
                    document_id,
                )
        except Exception as db_err:
            logger.error(
                "Failed to update document %s status to FAILED: %s",
                document_id,
                str(db_err),
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while processing the document. Please try again later.",
        )

    # Persist structured processing result
    # Crucial rule: original document's 'status' (e.g. UPLOADED) MUST NOT be changed to VERIFIED!
    now_done = datetime.now(timezone.utc).isoformat()
    result_dict = result.model_dump()
    doc_filter: dict[str, Any] = {"_id": doc["_id"]}
    if run_id:
        doc_filter["activeRunId"] = run_id
        doc_filter["supersededRunIds"] = {"$ne": run_id}

    doc_update_res = db["documents"].update_one(
        doc_filter,
        {
            "$set": {
                "processingResult": result_dict,
                "processingStatus": result.processingState,
                "processingConfidence": result.overallConfidence,
                "updatedAt": now_done,
            }
        },
    )
    if run_id and doc_update_res.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Execution ownership lost for run '{run_id}' during document processing persistence.",
        )

    # Increment 14: Synchronously run deterministic content validation when processing succeeds
    # If processing failed (e.g. engine error), leave document in UPLOADED state and do not validate.
    # If validation fails unexpectedly, preserve processingStatus = COMPLETED and original processingResult!
    if result.processingState == "COMPLETED":
        try:
            app_record = db["applications"].find_one({"applicationId": app_id}) if app_id else None
            user_record = None
            user_id_str = doc.get("userId")
            if user_id_str:
                try:
                    user_record = db["users"].find_one({"_id": ObjectId(user_id_str)})
                except Exception:
                    user_record = db["users"].find_one({"_id": user_id_str})

            sibling_docs = []
            if app_id:
                sibling_docs = list(
                    db["documents"].find({"applicationId": app_id, "documentId": {"$ne": document_id}})
                )

            updated_doc = dict(doc)
            updated_doc["processingResult"] = result_dict
            updated_doc["processingStatus"] = result.processingState
            updated_doc["processingConfidence"] = result.overallConfidence

            val_result = validate_document_content(
                db=db,
                document=updated_doc,
                application=app_record,
                user=user_record,
                sibling_documents=sibling_docs,
            )

            new_status = (
                "VALIDATED" if val_result.validationStatus == "VALIDATED"
                else "MISMATCH" if val_result.validationStatus == "MISMATCH"
                else "MANUAL_REVIEW"
            )

            val_filter: dict[str, Any] = {"_id": doc["_id"]}
            if run_id:
                val_filter["activeRunId"] = run_id
                val_filter["supersededRunIds"] = {"$ne": run_id}

            val_res = db["documents"].update_one(
                val_filter,
                {
                    "$set": {
                        "validationResult": val_result.model_dump(),
                        "validationStatus": val_result.validationStatus,
                        "status": new_status,
                        "updatedAt": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
            if run_id and val_res.matched_count == 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Execution ownership lost for run '{run_id}' during validation persistence.",
                )
        except HTTPException:
            raise
        except Exception as val_err:
            logger.error(
                "Unexpected error during content validation for document %s: %s",
                document_id,
                str(val_err),
                exc_info=True,
            )
            now_err = datetime.now(timezone.utc).isoformat()
            val_err_filter: dict[str, Any] = {"_id": doc["_id"]}
            if run_id:
                val_err_filter["activeRunId"] = run_id
                val_err_filter["supersededRunIds"] = {"$ne": run_id}
            db["documents"].update_one(
                val_err_filter,
                {
                    "$set": {
                        "validationStatus": "ERROR",
                        "status": "MANUAL_REVIEW",
                        "validationResult": {
                            "documentId": document_id,
                            "documentType": doc_type,
                            "validationStatus": "ERROR",
                            "fieldResults": {},
                            "crossDocumentResults": [],
                            "missingMandatoryFields": [],
                            "reasons": ["Unexpected error during content validation execution."],
                            "validatedAt": now_err,
                            "errorSummary": "Internal error occurred during validation execution.",
                        },
                        "updatedAt": now_err,
                    }
                },
            )

    return result


def get_document_processing_result(
    db: Database,
    current_user: dict,
    document_id: str,
) -> DocumentProcessingResult:
    """
    Retrieve persisted processing result for an authorized document.
    Enforces ownership (applicant owns document, or admin allowed).
    """
    doc = db["documents"].find_one({"documentId": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    user_role = current_user.get("role")
    user_id = str(current_user["_id"])
    if user_role == "applicant":
        if doc.get("userId") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access processing results for this document.",
            )
    elif user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role.",
        )

    res_data = doc.get("processingResult")
    if not res_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No processing result found for this document.",
        )

    return DocumentProcessingResult.model_validate(res_data)


def verify_document(
    db: Database,
    current_user: dict,
    document_id: str,
    run_id: str | None = None,
) -> DocumentValidationResult:
    """
    Rerun deterministic content validation against canonical application and sibling documents.
    Applicant owner only.
    Requires completed OCR processing.
    """
    if current_user.get("role") != "applicant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only applicants are permitted to verify documents.",
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
            detail="Not authorized to verify this document.",
        )

    if doc.get("processingStatus") != "COMPLETED" or not doc.get("processingResult"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document must complete OCR processing before content validation can be performed.",
        )

    app_id = doc.get("applicationId")
    app_record = db["applications"].find_one({"applicationId": app_id}) if app_id else None
    if run_id and (
        not app_record
        or app_record.get("activeRunId") != run_id
        or run_id in app_record.get("supersededRunIds", [])
    ):
        current_active = app_record.get("activeRunId") if app_record else None
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Execution ownership lost for run '{run_id}'. Active run is '{current_active}'.",
        )

    user_record = None
    try:
        user_record = db["users"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        user_record = db["users"].find_one({"_id": user_id})

    sibling_docs = []
    if app_id:
        sibling_docs = list(
            db["documents"].find({"applicationId": app_id, "documentId": {"$ne": document_id}})
        )

    val_result = validate_document_content(
        db=db,
        document=doc,
        application=app_record,
        user=user_record,
        sibling_documents=sibling_docs,
    )

    new_status = (
        "VALIDATED" if val_result.validationStatus == "VALIDATED"
        else "MISMATCH" if val_result.validationStatus == "MISMATCH"
        else "MANUAL_REVIEW"
    )

    now_done = datetime.now(timezone.utc).isoformat()
    val_filter: dict[str, Any] = {"_id": doc["_id"]}
    if run_id:
        val_filter["activeRunId"] = run_id
        val_filter["supersededRunIds"] = {"$ne": run_id}

    val_res = db["documents"].update_one(
        val_filter,
        {
            "$set": {
                "validationResult": val_result.model_dump(),
                "validationStatus": val_result.validationStatus,
                "status": new_status,
                "updatedAt": now_done,
            }
        },
    )
    if run_id and val_res.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Execution ownership lost for run '{run_id}' during verification persistence.",
        )

    return val_result


def get_document_verification(
    db: Database,
    current_user: dict,
    document_id: str,
) -> DocumentVerificationDetailsResponse:
    """
    Retrieve validation result and authoritative verification details for an authorized document.
    Enforces ownership (applicant owns document, or admin allowed).
    """
    doc = db["documents"].find_one({"documentId": document_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    user_role = current_user.get("role")
    user_id = str(current_user["_id"])
    if user_role == "applicant":
        if doc.get("userId") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access verification details for this document.",
            )
    elif user_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted for this role.",
        )

    proc_res = doc.get("processingResult") or {}
    fields = proc_res.get("fields") or {}
    extraction_summary = {}
    for k, v in fields.items():
        if isinstance(v, dict) and v.get("normalizedValue") is not None:
            extraction_summary[k] = v.get("normalizedValue")

    val_data = doc.get("validationResult")
    auth_data = doc.get("authoritativeVerification")

    return DocumentVerificationDetailsResponse(
        documentId=document_id,
        documentType=doc.get("documentType", "10TH_MARKSHEET"),
        lifecycleStatus=doc.get("status", "UPLOADED"),
        processingStatus=doc.get("processingStatus"),
        processingConfidence=doc.get("processingConfidence"),
        validationStatus=doc.get("validationStatus", "NOT_RUN"),
        validationResult=DocumentValidationResult.model_validate(val_data) if val_data else None,
        authoritativeVerification=AuthoritativeVerificationRecord.model_validate(auth_data) if auth_data else None,
        extractionSummary=extraction_summary if extraction_summary else None,
    )


def authoritative_verify_document(
    db: Database,
    current_user: dict,
    document_id: str,
) -> AuthoritativeVerificationRecord:
    """
    Run simulated authoritative verification against synthetic fixtures.
    Applicant owner only.
    Stores authoritativeVerification separately. Never sets lifecycle status to VERIFIED.
    """
    if current_user.get("role") != "applicant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only applicants are permitted to run authoritative verification.",
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
            detail="Not authorized to run authoritative verification on this document.",
        )

    if doc.get("processingStatus") != "COMPLETED" or not doc.get("processingResult"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document must complete OCR processing before authoritative verification.",
        )

    proc_res = doc.get("processingResult") or {}
    extracted_fields = proc_res.get("fields") or {}
    doc_type = doc.get("documentType", "10TH_MARKSHEET")

    cand_name = (extracted_fields.get("candidateName") or {}).get("normalizedValue")

    provider = SyntheticAuthoritativeVerificationProvider()
    auth_record = provider.verify_document_credential(
        document_type=doc_type,
        extracted_fields=extracted_fields,
        candidate_name=cand_name,
    )

    now_done = datetime.now(timezone.utc).isoformat()
    db["documents"].update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "authoritativeVerification": auth_record.model_dump(),
                "updatedAt": now_done,
            }
        },
    )

    return auth_record
