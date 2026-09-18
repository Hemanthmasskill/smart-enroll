import { Fragment, useEffect, useState } from "react";
import PageHeader from "../../components/PageHeader";
import { getProgrammeRules, updateProgrammeRules } from "../../services/api";
import "./Admin.css";

const FIELD_DEFS = [
  { key: "minimumQualification", label: "Required Qualifying Degree" },
  { key: "minimumPercentage", label: "Minimum Bachelor's Percentage" },
  { key: "mathematicsRequirement", label: "Mathematics Requirement" },
  { key: "requiredDocuments", label: "Required Documents" },
  { key: "entranceRequirement", label: "Entrance Examination Requirement" },
];

export default function ProgrammeRules() {
  const [items, setItems] = useState([]);
  const [editingId, setEditingId] = useState(null);
  const [formValues, setFormValues] = useState({});
  const [feedback, setFeedback] = useState("");

  useEffect(() => {
    getProgrammeRules().then(setItems);
  }, []);

  const startEdit = (programmeId, rules) => {
    setFeedback("");
    setEditingId(programmeId);
    setFormValues(rules ?? {});
  };

  const cancelEdit = () => {
    setEditingId(null);
    setFormValues({});
  };

  const saveEdit = async (programmeId) => {
    try {
      const updated = await updateProgrammeRules(programmeId, formValues);
      setItems((prev) =>
        prev.map((item) => (item.programme.id === programmeId ? { ...item, rules: updated } : item))
      );
      setEditingId(null);
      setFeedback("Programme rules saved in the frontend simulation. Applicant eligibility now reads the updated configuration.");
    } catch (error) {
      setFeedback(`Unable to save programme rules: ${error.message}`);
    }
  };

  return (
    <div>
      <PageHeader
        title="Programme Rules"
        subtitle="Deterministic, system-owned eligibility configuration for each programme."
      />

      {feedback && (
        <div className="admin-feedback" role="status" aria-live="polite">{feedback}</div>
      )}

      <div className="card admin-panel" style={{ marginBottom: "var(--space-5)" }}>
        <p className="admin-muted">
          These criteria are configured by the institution and are not generated, inferred, or
          modified by the Smart Enroll agent. The applicant-facing Eligibility page evaluates
          every application against exactly these rules — editing a value here changes what
          applicants are evaluated against.
        </p>
      </div>

      <div className="programme-rules-list">
        {items.map(({ programme, rules }) => {
          const isEditing = editingId === programme.id;
          return (
            <section className="card admin-section" key={programme.id}>
              <div className="admin-panel-head">
                <div>
                  <span className="admin-panel-title">{programme.name}</span>
                  <p className="admin-muted" style={{ marginTop: "2px" }}>
                    {programme.fullName}
                  </p>
                </div>
                {!isEditing && (
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => startEdit(programme.id, rules)}
                  >
                    Edit
                  </button>
                )}
              </div>

              {rules ? (
                isEditing ? (
                  <div>
                    <div className="programme-rules-edit-grid">
                      {FIELD_DEFS.map((field) => (
                        <div className="field" key={field.key}>
                          <label htmlFor={`${programme.id}-${field.key}`}>{field.label}</label>
                          <input
                            id={`${programme.id}-${field.key}`}
                            value={formValues[field.key] ?? ""}
                            onChange={(e) =>
                              setFormValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                            }
                          />
                        </div>
                      ))}
                    </div>
                    <div className="application-actions" style={{ justifyContent: "flex-end" }}>
                      <button className="btn btn-secondary" onClick={cancelEdit}>
                        Cancel
                      </button>
                      <button className="btn btn-accent" onClick={() => saveEdit(programme.id)}>
                        Save Changes
                      </button>
                    </div>
                  </div>
                ) : (
                  <dl className="admin-kv">
                    {FIELD_DEFS.map((field) => (
                      <Fragment key={field.key}>
                        <dt>{field.label}</dt>
                        <dd>{rules[field.key]}</dd>
                      </Fragment>
                    ))}
                  </dl>
                )
              ) : (
                <p className="admin-muted">No configured rules found for this programme.</p>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
