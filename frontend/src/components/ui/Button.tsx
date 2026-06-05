import { type ButtonHTMLAttributes, forwardRef } from "react";

type ButtonVariant = "default" | "primary" | "accent" | "ghost" | "danger";
type ButtonSize = "md" | "sm" | "xs";

const VARIANT: Record<ButtonVariant, string> = {
  default: "",
  primary: "btn-primary",
  accent: "btn-accent",
  ghost: "btn-ghost",
  danger: "btn-danger",
};

const SIZE: Record<ButtonSize, string> = {
  md: "",
  sm: "btn-sm",
  xs: "btn-xs",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", block = false, type = "button", className, ...rest },
  ref,
) {
  const cls = ["btn", VARIANT[variant], SIZE[size], block && "btn-block", className]
    .filter(Boolean)
    .join(" ");
  return <button ref={ref} type={type} className={cls} {...rest} />;
});
