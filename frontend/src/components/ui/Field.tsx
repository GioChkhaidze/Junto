import { createContext, useContext, useId, type AriaAttributes, type ReactNode } from "react";
import styles from "./Field.module.css";

interface FieldContextValue {
  controlId: string;
  describedBy?: string;
  invalid: boolean;
  required: boolean;
}

const FieldContext = createContext<FieldContextValue | null>(null);

interface FieldProps {
  children: ReactNode;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  controlId?: string;
  className?: string;
}

interface FieldControlOptions {
  id?: string;
  describedBy?: string;
  invalid?: AriaAttributes["aria-invalid"];
  required?: boolean;
}

interface ResolvedFieldControl {
  id?: string;
  describedBy?: string;
  invalid?: AriaAttributes["aria-invalid"];
  isInvalid: boolean;
  required?: boolean;
}

function joinIds(...values: Array<string | undefined>): string | undefined {
  const ids = values.flatMap((value) => value?.split(/\s+/).filter(Boolean) ?? []);
  const uniqueIds = [...new Set(ids)];
  return uniqueIds.length > 0 ? uniqueIds.join(" ") : undefined;
}

export function useFieldControl(options: FieldControlOptions): ResolvedFieldControl {
  const field = useContext(FieldContext);
  const invalid = field?.invalid ? true : options.invalid;

  return {
    id: field?.controlId ?? options.id,
    describedBy: joinIds(options.describedBy, field?.describedBy),
    invalid,
    isInvalid: invalid === true || (typeof invalid === "string" && invalid !== "false"),
    required: field?.required || options.required || undefined,
  };
}

export function Field({ children, className, controlId, error, hint, label, required = false }: FieldProps) {
  const generatedId = useId();
  const resolvedControlId = controlId ?? `field-${generatedId}`;
  const hintId = hint ? `${resolvedControlId}-hint` : undefined;
  const errorId = error ? `${resolvedControlId}-error` : undefined;
  const describedBy = joinIds(hintId, errorId);

  return (
    <FieldContext.Provider value={{ controlId: resolvedControlId, describedBy, invalid: Boolean(error), required }}>
      <div className={[styles.field, className].filter(Boolean).join(" ")}>
        <label className={styles.label} htmlFor={resolvedControlId}>
          <span>{label}</span>
          {required ? (
            <span className={styles.required} aria-hidden="true">
              *
            </span>
          ) : null}
        </label>
        {children}
        {hint ? (
          <p className={styles.hint} id={hintId}>
            {hint}
          </p>
        ) : null}
        {error ? (
          <p className={styles.error} id={errorId} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </FieldContext.Provider>
  );
}
