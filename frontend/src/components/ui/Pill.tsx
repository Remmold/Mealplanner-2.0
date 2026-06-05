import type { HTMLAttributes } from "react";

type PillVariant = "default" | "active" | "warm";

const VARIANT: Record<PillVariant, string> = {
  default: "",
  active: "pill-active",
  warm: "pill-warm",
};

export interface PillProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: PillVariant;
}

export function Pill({ variant = "default", className, ...rest }: PillProps) {
  return <span className={["pill", VARIANT[variant], className].filter(Boolean).join(" ")} {...rest} />;
}
