import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { getDocuments, uploadDocument, removeDocument, processDocument, getVerificationStatus } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import DocumentCard from "../../components/DocumentCard";
import DocumentVerificationPanel from "../../components/DocumentVerificationPanel";
import Modal from "../../components/Modal";
import ConfirmDialog from "../../components/ConfirmDialog";
import PrototypeNotice from "../../components/PrototypeNotice";
import { ErrorState, LoadingState } from "../../components/AsyncState";
import "./Documents.css";

export default function Documents() {
  const { session } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [viewingDoc, setViewingDoc] = useState(null);
  const [removingDoc, setRemovingDoc] = useState(null);
  const [processingDocId, setProcessingDocId] = useState(null);

  useEffect(() => {
    let mounted = true;
    setError("");
    getDocuments(session?.applicantId, session?.token)
      .then((docs) => {
        if (mounted) setDocuments(docs);
      })
      .catch((loadError) => {
        if (mounted) setError(loadError.message || "Unable to load documents.");
      })
      .finally(() => {
        if (mounted) setIsLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [session]);

  const refreshDoc = (updatedDoc) => {
    setDocuments((prev) => prev.map((d) => (d.id === updatedDoc.id ? updatedDoc : d)));
  };

  const handleUpload = async (documentId, file, variant) => {
    setFeedback("");
    try {
      const updated = await uploadDocument(session?.applicantId, documentId, file, variant, session?.token);
      refreshDoc(updated);
      setFeedback(`${updated.name} uploaded. Application state has been recalculated.`);
    } catch (uploadError) {
      setFeedback(`Upload failed: ${uploadError.message}`);
    }
  };

  const handleProcess = async (doc) => {
    if (!doc || processingDocId === doc.id) return;
    setProcessingDocId(doc.id);
    setFeedback("");
    try {
      const result = await processDocument(
        session?.applicantId,
        doc.id,
        session?.token,
        doc.documentId
      );

      // Build extraction summary for Layer 1 panel view
      const extractionDetails = {};
      if (result.fields) {
        if (result.fields.candidateName?.normalizedValue) {
          extractionDetails["Candidate Name"] = result.fields.candidateName.normalizedValue;
        }
        if (result.fields.dob?.normalizedValue) {
          extractionDetails["Date of Birth"] = result.fields.dob.normalizedValue;
        }
        if (result.fields.registrationNumber?.normalizedValue) {
          extractionDetails["Roll / Registration No"] = result.fields.registrationNumber.normalizedValue;
        }
        if (result.fields.marksObtained?.normalizedValue) {
          extractionDetails["Marks Obtained"] = String(result.fields.marksObtained.normalizedValue);
        }
        if (result.fields.maxMarks?.normalizedValue) {
          extractionDetails["Max Marks"] = String(result.fields.maxMarks.normalizedValue);
        }
        if (result.fields.percentage?.normalizedValue) {
          extractionDetails["Percentage"] = `${result.fields.percentage.normalizedValue}%`;
        }
        if (result.fields.cgpa?.normalizedValue) {
          extractionDetails["CGPA"] = String(result.fields.cgpa.normalizedValue);
        }
        if (result.fields.institution?.normalizedValue) {
          extractionDetails["Institution / Board"] = result.fields.institution.normalizedValue;
        }
      }
      extractionDetails["Extraction Confidence"] = `${Math.round((result.overallConfidence ?? 0) * 100)}%`;
      if (result.classification?.predictedType) {
        extractionDetails["Predicted Type"] = result.classification.predictedType;
      }

      let validationDetails = {};
      let authDetails = { status: "UNAVAILABLE" };

      if (session?.token && session.token !== "mock-jwt-token") {
        if (doc.documentId) {
          try {
            const verifRes = await getVerificationStatus(
              session?.applicantId,
              doc.id,
              session?.token,
              doc.documentId
            );
            if (verifRes?.validationResult) {
              const vRes = verifRes.validationResult;
              const fr = vRes.fieldResults || {};
              for (const [k, v] of Object.entries(fr)) {
                validationDetails[k] = `${v.status}: ${v.message || ""}`;
              }
              if (vRes.reasons && vRes.reasons.length > 0) {
                validationDetails["Validation Notes"] = vRes.reasons.join("; ");
              }
              if (Object.keys(validationDetails).length === 0) {
                validationDetails["Validation Outcome"] = vRes.validationStatus;
              }
            } else {
              validationDetails["Validation Outcome"] = "Validation pending or record unavailable";
            }
            if (verifRes?.authoritativeVerification) {
              authDetails = {
                status: verifRes.authoritativeVerification.status,
                source: verifRes.authoritativeVerification.provider,
                recordId: verifRes.authoritativeVerification.lookupIdentifier,
              };
            }
          } catch {
            // Surface a safe error/unavailable state, never display mock data when real token is active
            validationDetails = {
              "Validation Status": "Verification details unavailable (network or service error)",
            };
            authDetails = {
              status: "UNAVAILABLE",
            };
          }
        } else {
          validationDetails = {
            "Validation Status": "Document identifier not yet assigned",
          };
          authDetails = {
            status: "UNAVAILABLE",
          };
        }
      } else {
        // Intentional mock mode fallback
        validationDetails = doc.details?.validation || { "Structure": "Format matches requirements" };
        authDetails = doc.details?.authoritative || { status: "PENDING" };
      }

      const updated = {
        ...doc,
        processingStatus: result.processingState || "COMPLETED",
        processingConfidence: result.overallConfidence,
        details: {
          ...(doc.details || {}),
          extraction: Object.keys(extractionDetails).length > 0 ? extractionDetails : { "OCR Extraction": "Text parsed successfully." },
          validation: validationDetails,
          authoritative: authDetails,
        },
      };
      refreshDoc(updated);
      setFeedback(
        `OCR processing complete for "${doc.name}" (${Math.round((result.overallConfidence ?? 0) * 100)}% confidence). Extraction confirms document content, not authenticity.`
      );
    } catch (procErr) {
      const updated = {
        ...doc,
        processingStatus: "FAILED",
      };
      refreshDoc(updated);
      setFeedback(`Processing failed for "${doc.name}": ${procErr.message}`);
    } finally {
      setProcessingDocId(null);
    }
  };

  const handleRemoveConfirmed = async () => {
    if (!removingDoc) return;
    setFeedback("");
    try {
      const updated = await removeDocument(
        session?.applicantId,
        removingDoc.id,
        session?.token,
        removingDoc.documentId,
        removingDoc
      );
      refreshDoc(updated);
      setFeedback(`${updated.name || removingDoc.name} removed. Application state has been recalculated.`);
    } catch (removeError) {
      setFeedback(`Remove failed: ${removeError.message}`);
    } finally {
      setRemovingDoc(null);
    }
  };

  const submittedCount = documents.filter((d) => d.status !== "NOT_UPLOADED").length;

  if (isLoading) return <LoadingState message="Loading your documents…" />;
  if (error) return <ErrorState message={error} />;

  return (
    <div>
      <PageHeader
        title="Documents"
        subtitle={`${submittedCount} of ${documents.length} required documents submitted.`}
      />

      <PrototypeNotice>
        OCR extraction, content validation and authoritative verification are shown as separate
        layers. Their results are simulated in this frontend until the backend integrations are connected.
      </PrototypeNotice>

      {feedback && (
        <div className="document-feedback" role="status" aria-live="polite">
          {feedback}
        </div>
      )}

      <div className="document-grid">
        {documents.map((doc) => (
          <DocumentCard
            key={doc.id}
            doc={doc}
            onUpload={(file, variant) => handleUpload(doc.id, file, variant)}
            onView={() => setViewingDoc(doc)}
            onRemove={() => setRemovingDoc(doc)}
            onProcess={() => handleProcess(doc)}
            isProcessing={processingDocId === doc.id}
          />
        ))}
      </div>

      {viewingDoc && (
        <Modal title="Document Verification" onClose={() => setViewingDoc(null)}>
          <DocumentVerificationPanel documentName={viewingDoc.name} details={viewingDoc.details} />
        </Modal>
      )}

      {removingDoc && (
        <ConfirmDialog
          title="Remove document"
          message={`Remove "${removingDoc.name}"? You'll need to upload it again before processing can continue.`}
          confirmLabel="Remove"
          onConfirm={handleRemoveConfirmed}
          onCancel={() => setRemovingDoc(null)}
        />
      )}
    </div>
  );
}
