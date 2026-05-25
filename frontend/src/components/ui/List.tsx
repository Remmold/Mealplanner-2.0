import type { HTMLAttributes } from "react";

export function List({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={["list", className].filter(Boolean).join(" ")} {...rest} />;
}

export interface ListRowProps extends HTMLAttributes<HTMLDivElement> {
  disabled?: boolean;
}

export function ListRow({ disabled = false, className, ...rest }: ListRowProps) {
  return (
    <div className={["list-row", disabled && "disabled", className].filter(Boolean).join(" ")} {...rest} />
  );
}
