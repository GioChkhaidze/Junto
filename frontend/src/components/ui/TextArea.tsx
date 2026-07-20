import { forwardRef, type TextareaHTMLAttributes } from "react";
import { useFieldControl } from "./Field";
import styles from "./Field.module.css";

type TextAreaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { "aria-describedby": describedBy, "aria-invalid": invalid, className, id, required, rows = 5, ...props },
  ref,
) {
  const field = useFieldControl({ id, describedBy, invalid, required });

  return (
    <textarea
      {...props}
      ref={ref}
      id={field.id}
      rows={rows}
      required={field.required}
      aria-describedby={field.describedBy}
      aria-invalid={field.invalid}
      className={[styles.control, styles.textarea, field.isInvalid && styles.controlInvalid, className]
        .filter(Boolean)
        .join(" ")}
    />
  );
});
