import { type InputHTMLAttributes, forwardRef } from "react";

type InputVariant = "default" | "title" | "inline";

// `title`/`inline` swap the base look entirely, so they replace `.input` rather than stacking on it.
const BASE: Record<InputVariant, string> = {
  default: "input",
  title: "input-title",
  inline: "input input-inline",
};

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  variant?: InputVariant;
  numeric?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { variant = "default", numeric = false, className, ...rest },
  ref,
) {
  const cls = [BASE[variant], numeric && "input-num", className].filter(Boolean).join(" ");
  return <input ref={ref} className={cls} {...rest} />;
});
