import { type ButtonHTMLAttributes, forwardRef } from "react";

export const IconButton = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement>>(
  function IconButton({ type = "button", className, ...rest }, ref) {
    return (
      <button
        ref={ref}
        type={type}
        className={["icon-btn", className].filter(Boolean).join(" ")}
        {...rest}
      />
    );
  },
);
