import type { HTMLAttributes } from "react";

type CardVariant = "default" | "soft" | "accent" | "warm";

const VARIANT: Record<CardVariant, string> = {
  default: "card",
  soft: "card-soft",
  accent: "card-accent",
  warm: "card-warm",
};

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
}

export function Card({ variant = "default", className, ...rest }: CardProps) {
  return <div className={[VARIANT[variant], className].filter(Boolean).join(" ")} {...rest} />;
}
