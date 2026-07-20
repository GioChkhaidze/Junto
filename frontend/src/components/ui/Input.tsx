import { forwardRef, type InputHTMLAttributes } from "react";
import { useFieldControl } from "./Field";
import styles from "./Field.module.css";

type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { "aria-describedby": describedBy, "aria-invalid": invalid, className, id, required, ...props },
  ref,
) {
  const field = useFieldControl({ id, describedBy, invalid, required });

  return (
    <input
      {...props}
      ref={ref}
      id={field.id}
      required={field.required}
      aria-describedby={field.describedBy}
      aria-invalid={field.invalid}
      className={[styles.control, field.isInvalid && styles.controlInvalid, className].filter(Boolean).join(" ")}
    />
  );
});
