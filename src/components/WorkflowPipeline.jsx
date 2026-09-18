import StatusBadge from "./StatusBadge";
import { WORKFLOW_STATE_META } from "../utils/workflowUtils";
import "./WorkflowPipeline.css";

export default function WorkflowPipeline({ workflow, compact = false }) {
  if (!workflow) return null;

  return (
    <section
      className={`card workflow-pipeline ${compact ? "workflow-pipeline-compact" : ""}`}
      aria-labelledby="workflow-pipeline-heading"
    >
      <div className="workflow-pipeline-head">
        <div>
          <span className="workflow-eyebrow">Integrated autonomous workflow</span>
          <h2 id="workflow-pipeline-heading">Admission Processing Workflow</h2>
        </div>
        <span className="workflow-model" aria-label="Observable agent execution model">
          OBSERVE → PLAN → ACT → VERIFY → RE-PLAN
        </span>
      </div>

      <ol className="workflow-stage-list">
        {workflow.stages.map((stage, index) => {
          const meta = WORKFLOW_STATE_META[stage.state] ?? WORKFLOW_STATE_META.WAITING;
          return (
            <li className={`workflow-stage workflow-state-${stage.state}`} key={stage.id}>
              <div className="workflow-stage-index" aria-hidden="true">
                {stage.state === "COMPLETED" ? "✓" : index + 1}
              </div>
              <div className="workflow-stage-body">
                <div className="workflow-stage-title-row">
                  <h3>{stage.label}</h3>
                  <StatusBadge label={meta.label} tone={meta.tone} />
                </div>
                <p>{stage.detail}</p>
                {!compact && (
                  <span className="workflow-observable-action">
                    Observable action: {stage.observableAction}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      <p className="workflow-disclaimer">
        This prototype displays observable workflow state, tool-level actions and deterministic
        results only. It does not expose private model reasoning or chain-of-thought.
      </p>
    </section>
  );
}
