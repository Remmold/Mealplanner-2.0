import type { HTMLAttributes } from "react";

export function ErrorBanner({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  if (!children) return null;
  return (
    <div className={["error", className].filter(Boolean).join(" ")} {...rest}>
      {children}
    </div>
  );
}

export function Empty({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={["empty", className].filter(Boolean).join(" ")} {...rest} />;
}

export function Divider({ className }: { className?: string }) {
  return <div className={["divider", className].filter(Boolean).join(" ")} />;
}
