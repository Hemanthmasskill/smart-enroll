import "./ProgressStepper.css";

/**
 * Horizontal step indicator. `steps` is an array of labels,
 * `currentStep` is the zero-based index of the active step.
 * Steps before currentStep are marked complete.
 */
export default function ProgressStepper({ steps, currentStep }) {
  return (
    <ol className="stepper">
      {steps.map((label, index) => {
        const state =
          index < currentStep ? "complete" : index === currentStep ? "current" : "pending";
        return (
          <li key={label} className={`stepper-item state-${state}`}>
            <span className="stepper-marker">{state === "complete" ? "\u2713" : index + 1}</span>
            <span className="stepper-label">{label}</span>
            {index < steps.length - 1 && <span className="stepper-connector" />}
          </li>
        );
      })}
    </ol>
  );
}
