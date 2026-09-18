import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { getDocuments, uploadDocument, removeDocument } from "../../services/api";
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

  useEffect(() => {
    let mounted = true;
    setError("");
    getDocuments(session?.applicantId)
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

  const handleUpload = async (documentId, file) => {
    setFeedback("");
    try {
      const updated = await uploadDocument(session?.applicantId, documentId, file);
      refreshDoc(updated);
      setFeedback(`${updated.name} uploaded. Application state has been recalculated.`);
    } catch (uploadError) {
      setFeedback(`Upload failed: ${uploadError.message}`);
    }
  };

  const handleRemoveConfirmed = async () => {
    if (!removingDoc) return;
    setFeedback("");
    try {
      const updated = await removeDocument(session?.applicantId, removingDoc.id);
      refreshDoc(updated);
      setFeedback(`${updated.name} removed. Application state has been recalculated.`);
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
            onUpload={(file) => handleUpload(doc.id, file)}
            onView={() => setViewingDoc(doc)}
            onRemove={() => setRemovingDoc(doc)}
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
