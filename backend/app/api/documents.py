from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pymongo.database import Database

from app.api.deps import RequireRole, get_current_user
from app.core.database import get_db
from app.schemas.document import DocumentDeleteResponse, DocumentResponse
from app.schemas.document_processing import DocumentProcessingResult
from app.core.concurrency import acquire_ocr_worker
from app.core.rate_limit import enforce_rate_limit
from app.schemas.verification import (
    AuthoritativeVerificationRecord,
    DocumentValidationResult,
    DocumentVerificationDetailsResponse,
)
from app.services.document import (
    authoritative_verify_document,
    delete_document,
    get_document_file,
    get_document_metadata,
    get_document_processing_result,
    get_document_verification,
    list_documents,
    process_document,
    upload_document,
    verify_document,
)

router = APIRouter()


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Documents"],
)
async def upload_document_endpoint(
    file: UploadFile = File(...),
    documentType: str = Form(..., description="Logical document type or frontend identifier"),
    documentVariant: str | None = Form(
        None, description="Required variant if documentType is DEGREE_CERTIFICATE"
    ),
    applicationId: str | None = Form(
        None, description="Optional application ID to verify against applicant ownership"
    ),
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Upload or replace a logical document file.
    Only authenticated applicants can upload against their own application.
    Enforces format validation (PDF/JPG/PNG <= 10MB) and degree certificate variant rules.
    """
    user_id = str(current_user.get("_id") or current_user.get("id"))
    enforce_rate_limit(f"doc_upload:{user_id}", max_requests=10, window_seconds=60, action_description="document uploads")
    return await upload_document(
        db=db,
        current_user=current_user,
        file=file,
        document_type_raw=documentType,
        document_variant_raw=documentVariant,
        requested_app_id=applicationId,
    )


@router.get(
    "",
    response_model=list[DocumentResponse],
    tags=["Documents"],
)
def list_documents_endpoint(
    applicationId: str | None = Query(
        None, description="Optional application filter (required for admin specific lookup)"
    ),
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    List the six logical document slots for the authenticated applicant's application.
    Admins can query document slots for an application or list all uploaded documents.
    """
    return list_documents(
        db=db,
        current_user=current_user,
        requested_app_id=applicationId,
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    tags=["Documents"],
)
def get_document_metadata_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve document metadata.
    Does not expose internal server storage path.
    Enforces applicant ownership checks.
    """
    return get_document_metadata(
        db=db,
        current_user=current_user,
        document_id=document_id,
    )


@router.get(
    "/{document_id}/download",
    tags=["Documents"],
)
def download_document_file_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Safely stream the stored binary file for viewing or downloading.
    Enforces applicant ownership checks and storage boundary containment.
    """
    return get_document_file(
        db=db,
        current_user=current_user,
        document_id=document_id,
    )


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    tags=["Documents"],
)
def delete_document_endpoint(
    document_id: str,
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Delete a document and its stored physical file.
    Only the owning applicant may delete their document.
    """
    return delete_document(
        db=db,
        current_user=current_user,
        document_id=document_id,
    )


@router.post(
    "/{document_id}/process",
    response_model=DocumentProcessingResult,
    tags=["Documents"],
)
def process_document_endpoint(
    document_id: str,
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Run bounded OCR, classification, and field extraction for the uploaded document.
    Enforces ownership (only owning applicant permitted to initiate processing).
    Stores processing result in document metadata without marking document as VERIFIED.
    """
    user_id = str(current_user.get("_id") or current_user.get("id"))
    enforce_rate_limit(f"doc_proc:{user_id}", max_requests=10, window_seconds=60, action_description="document processing requests")
    with acquire_ocr_worker():
        return process_document(
            db=db,
            current_user=current_user,
            document_id=document_id,
        )


@router.get(
    "/{document_id}/processing-result",
    response_model=DocumentProcessingResult,
    tags=["Documents"],
)
def get_document_processing_result_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve persisted OCR extraction, classification, and field results.
    Enforces ownership (applicant owns document, or admin allowed).
    """
    return get_document_processing_result(
        db=db,
        current_user=current_user,
        document_id=document_id,
    )


@router.post(
    "/{document_id}/verify",
    response_model=DocumentValidationResult,
    tags=["Documents"],
)
def verify_document_endpoint(
    document_id: str,
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Rerun deterministic content validation against canonical application and sibling documents.
    Enforces ownership (only owning applicant permitted to initiate validation).
    """
    user_id = str(current_user.get("_id") or current_user.get("id"))
    enforce_rate_limit(f"doc_verify:{user_id}", max_requests=10, window_seconds=60, action_description="document verification requests")
    return verify_document(
        db=db,
        current_user=current_user,
        document_id=document_id,
    )


@router.get(
    "/{document_id}/verification",
    response_model=DocumentVerificationDetailsResponse,
    tags=["Documents"],
)
def get_document_verification_endpoint(
    document_id: str,
    current_user: dict = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """
    Retrieve structured verification details including field comparisons, cross-checks, and authoritative simulation.
    Enforces ownership (applicant owns document, or admin allowed).
    """
    return get_document_verification(
        db=db,
        current_user=current_user,
        document_id=document_id,
    )


@router.post(
    "/{document_id}/authoritative-verify",
    response_model=AuthoritativeVerificationRecord,
    tags=["Documents"],
)
def authoritative_verify_document_endpoint(
    document_id: str,
    current_user: dict = Depends(RequireRole(["applicant"])),
    db: Database = Depends(get_db),
):
    """
    Run simulated authoritative verification against synthetic fixtures.
    Enforces ownership (only owning applicant permitted).
    Results are strictly simulated and cannot establish authentic government verification.
    """
    user_id = str(current_user.get("_id") or current_user.get("id"))
    enforce_rate_limit(
        f"doc_auth_verify:{user_id}",
        max_requests=10,
        window_seconds=60,
        action_description="authoritative verification requests",
    )
    return authoritative_verify_document(
        db=db,
        current_user=current_user,
        document_id=document_id,
    )
