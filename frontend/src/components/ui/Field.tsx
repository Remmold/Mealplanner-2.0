import type { LabelHTMLAttributes } from "react";

export function Field({ className, ...rest }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={["field", className].filter(Boolean).join(" ")} {...rest} />;
}
