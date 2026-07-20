import { forwardRef, type SelectHTMLAttributes } from "react";
import { useFieldControl } from "./Field";
import { Icon } from "./Icon";
import styles from "./Field.module.css";

type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { "aria-describedby": describedBy, "aria-invalid": invalid, className, id, required, ...props },
  ref,
) {
  const field = useFieldControl({ id, describedBy, invalid, required });

  return (
    <span className={styles.selectWrap}>
      <select
        {...props}
        ref={ref}
        id={field.id}
        required={field.required}
        aria-describedby={field.describedBy}
        aria-invalid={field.invalid}
        className={[styles.control, styles.select, field.isInvalid && styles.controlInvalid, className]
          .filter(Boolean)
          .join(" ")}
      />
      <Icon className={styles.selectIcon} name="chevron-down" size={18} />
    </span>
  );
});
