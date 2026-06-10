import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";

export interface SelectOption {
  value: string;
  label: ReactNode;
}

export interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
}

// Custom listbox replacing the native <select> so dropdowns match the app
// theme. Keyboard: Enter/Space/Arrows open; Up/Down/Home/End move; Enter picks;
// Escape/Tab/outside-click close. Stores/sends the option's string value.
export function Select({
  value,
  onChange,
  options,
  className,
  disabled,
  "aria-label": ariaLabel,
}: SelectProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  const selectedIndex = options.findIndex((o) => o.value === value);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : undefined;

  useEffect(() => {
    if (!open) return;
    function onDocDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocDown);
    return () => document.removeEventListener("mousedown", onDocDown);
  }, [open]);

  function openMenu() {
    if (disabled) return;
    setActive(selectedIndex >= 0 ? selectedIndex : 0);
    setOpen(true);
  }

  function choose(i: number) {
    const opt = options[i];
    if (opt) onChange(opt.value);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (disabled) return;
    if (!open) {
      if (["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        openMenu();
      }
      return;
    }
    switch (e.key) {
      case "Escape": e.preventDefault(); setOpen(false); break;
      case "ArrowDown": e.preventDefault(); setActive((i) => Math.min(options.length - 1, i + 1)); break;
      case "ArrowUp": e.preventDefault(); setActive((i) => Math.max(0, i - 1)); break;
      case "Home": e.preventDefault(); setActive(0); break;
      case "End": e.preventDefault(); setActive(options.length - 1); break;
      case "Enter": case " ": e.preventDefault(); choose(active); break;
      case "Tab": setOpen(false); break;
    }
  }

  return (
    // stopPropagation: when this Select sits inside a <Field> (a <label>),
    // option clicks would otherwise bubble to the label and get forwarded back
    // to the trigger button, re-opening the menu right after a pick.
    <div
      ref={rootRef}
      className={["select-wrap", className].filter(Boolean).join(" ")}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        className="select"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={onKeyDown}
      >
        <span className="select-value">{selected ? selected.label : ""}</span>
        <ChevronDown size={16} className="select-caret" />
      </button>
      {open && (
        <ul className="select-menu" role="listbox">
          {options.map((o, i) => (
            <li
              key={o.value}
              role="option"
              aria-selected={o.value === value}
              className={
                "select-option" +
                (i === active ? " active" : "") +
                (o.value === value ? " selected" : "")
              }
              onMouseEnter={() => setActive(i)}
              onClick={() => choose(i)}
            >
              <span className="flex-1">{o.label}</span>
              {o.value === value && <Check size={14} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
