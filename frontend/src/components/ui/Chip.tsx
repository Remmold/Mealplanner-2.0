import type { ReactNode } from "react";
import { X } from "lucide-react";

export interface ChipProps {
  active?: boolean;
  onClick?: () => void;
  onRemove?: () => void;
  className?: string;
  children: ReactNode;
}

export function Chip({ active = false, onClick, onRemove, className, children }: ChipProps) {
  return (
    <span className={["chip", active && "chip-active", className].filter(Boolean).join(" ")}>
      <span onClick={onClick}>{children}</span>
      {onRemove && (
        <span
          className="chip-x"
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
        >
          <X size={14} />
        </span>
      )}
    </span>
  );
}
