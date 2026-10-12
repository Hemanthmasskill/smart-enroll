import { useRef, useState } from "react";
import StatusBadge from "./StatusBadge";
import "./DocumentCard.css";

const SUPPORTED_FORMATS = "PDF, JPG, PNG";

const DEGREE_VARIANTS = [
  { value: "ORIGINAL_DEGREE_CERTIFICATE", label: "Original Degree Certificate" },
  { value: "PROVISIONAL_DEGREE_CERTIFICATE", label: "Provisional Degree Certificate" },
  { value: "COURSE_COMPLETION_CERTIFICATE", label: "Course Completion Certificate" },
];

/**
 * Renders one required document: either an upload dropzone (nothing
 * uploaded yet) or a summary row with the uploaded file, its
 * verification status, and View/Replace/Remove actions.
 */
export default function DocumentCard({ doc, onUpload, onView, onRemove }) {
  const inputRef = useRef(null);
  const isUploaded = doc.status !== "NOT_UPLOADED";
  const isDegreeCertificate =
    doc.id === "doc-degree" ||
    doc.documentType === "DEGREE_CERTIFICATE" ||
    doc.name?.toLowerCase().includes("degree");

  const [selectedVariant, setSelectedVariant] = useState(
    doc.documentVariant || doc.variant || "PROVISIONAL_DEGREE_CERTIFICATE"
  );

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];
    if (file) onUpload(file, isDegreeCertificate ? selectedVariant : undefined);
    event.target.value = "";
  };

  const handleDrop = (event) => {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) onUpload(file, isDegreeCertificate ? selectedVariant : undefined);
  };

  const getVariantLabel = (val) => {
    const match = DEGREE_VARIANTS.find((v) => v.value === val);
    return match ? match.label : val;
  };

  const activeVariant = doc.documentVariant || doc.variant || (isUploaded && isDegreeCertificate ? selectedVariant : null);

  return (
    <div className="document-card card">
      <div className="document-card-top">
        <div>
          <h3 className="document-card-name">{doc.name}</h3>
          <span className="document-card-required">
            {doc.required ? "Required" : "Optional"}
          </span>
        </div>
        <StatusBadge code={doc.status} />
      </div>

      {isDegreeCertificate && !isUploaded && (
        <div className="document-variant-container" onClick={(e) => e.stopPropagation()}>
          <label htmlFor={`variant-select-${doc.id}`} className="document-variant-label">
            Degree Variant:
          </label>
          <select
            id={`variant-select-${doc.id}`}
            value={selectedVariant}
            onChange={(e) => setSelectedVariant(e.target.value)}
            className="document-variant-select"
          >
            {DEGREE_VARIANTS.map((v) => (
              <option key={v.value} value={v.value}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {isUploaded ? (
        <div className="document-card-file">
          <div className="document-card-file-info">
            <span className="document-card-filename">{doc.fileName}</span>
            {activeVariant && (
              <span className="document-card-variant-badge">
                {getVariantLabel(activeVariant)}
              </span>
            )}
            <span className="document-card-uploaded-at">Uploaded {doc.uploadedAt}</span>
          </div>
          <div className="document-card-actions">
            <button className="btn btn-secondary btn-sm" onClick={onView}>
              View
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => inputRef.current?.click()}>
              Replace
            </button>
            <button className="btn btn-danger-ghost btn-sm" onClick={onRemove}>
              Remove
            </button>
          </div>
        </div>
      ) : (
        <div
          className="document-dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
          }}
        >
          <span className="document-dropzone-icon" aria-hidden="true">
            &#8593;
          </span>
          <span className="document-dropzone-text">Drag and drop, or click to upload</span>
          <span className="document-dropzone-formats">Supported formats: {SUPPORTED_FORMATS}</span>
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.jpg,.jpeg,.png"
        className="visually-hidden"
        onChange={handleFileChange}
      />
    </div>
  );
}
