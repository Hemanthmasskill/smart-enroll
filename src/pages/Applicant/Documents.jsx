import { useEffect, useState } from "react";
import { useAuth } from "../../context/AuthContext";
import { getDocuments, uploadDocument, removeDocument } from "../../services/api";
import PageHeader from "../../components/PageHeader";
import DocumentCard from "../../components/DocumentCard";
import DocumentVerificationPanel from "../../components/DocumentVerificationPanel";
import Modal from "../../components/Modal";
import ConfirmDialog from "../../components/ConfirmDialog";
import "./Documents.css";

export default function Documents() {
  const { session } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [viewingDoc, setViewingDoc] = useState(null);
  const [removingDoc, setRemovingDoc] = useState(null);

  useEffect(() => {
    getDocuments(session?.applicantId).then((docs) => {
      setDocuments(docs);
      setIsLoading(false);
    });
  }, [session]);

  const refreshDoc = (updatedDoc) => {
    setDocuments((prev) => prev.map((d) => (d.id === updatedDoc.id ? updatedDoc : d)));
  };

  const handleUpload = async (documentId, file) => {
    const updated = await uploadDocument(session?.applicantId, documentId, file);
    refreshDoc(updated);
  };

  const handleRemoveConfirmed = async () => {
    const updated = await removeDocument(session?.applicantId, removingDoc.id);
    refreshDoc(updated);
    setRemovingDoc(null);
  };

  const submittedCount = documents.filter((d) => d.status !== "NOT_UPLOADED").length;

  if (isLoading) return <p>Loading your documents...</p>;

  return (
    <div>
      <PageHeader
        title="Documents"
        subtitle={`${submittedCount} of ${documents.length} required documents submitted.`}
      />

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
