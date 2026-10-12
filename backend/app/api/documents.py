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
from app.services.document import (
    delete_document,
    get_document_file,
    get_document_metadata,
    list_documents,
    upload_document,
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
