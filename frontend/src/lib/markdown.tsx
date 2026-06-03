// Minimal markdown renderer for the chat assistant. Builds React elements
// directly (never dangerouslySetInnerHTML, so there is no XSS surface) and
// covers exactly what the agent emits: **bold**/__bold__, *italic*/_italic_,
// `code`, # headings, "- " and "1." lists, paragraphs with soft line breaks,
// and the app's own [label](nav:<target>) links rendered as jump buttons.
import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { navigateTo, type NavIntent } from "../api";

// Targets the chat agent can embed via [label](nav:<target>).
const NAV_TARGETS: Record<string, NavIntent> = {
  plan:             { tab: "plan" },
  "plan/generate":  { tab: "plan", openGenerator: true },
  recipes:          { tab: "recipe" },
  shopping:         { tab: "shopping" },
  profile:          { tab: "profile" },
};

// One pass over inline spans. At each position the alternatives are tried
// left-to-right, so `**` is matched as bold before `*` is tried as italic.
// Groups: 1/2 link label/target · 3|4 bold · 5 code · 6|7 italic.
const INLINE_RE =
  /\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|__([^_]+)__|`([^`]+)`|\*([^*]+)\*|_([^_]+)_/g;

function parseInline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  for (const m of text.matchAll(INLINE_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push(text.slice(last, idx));
    const key = `${keyBase}-${k++}`;
    if (m[1] !== undefined) {
      const label = m[1];
      const target = m[2];
      if (target.startsWith("nav:")) {
        const intent = NAV_TARGETS[target.slice(4)];
        if (intent) {
          out.push(
            <button key={key} type="button" className="chat-nav-link" onClick={() => navigateTo(intent)}>
              {label} <ChevronRight size={12} />
            </button>,
          );
        } else {
          out.push(label);   // unknown target — show the label as plain text
        }
      } else if (/^https?:\/\//.test(target)) {
        out.push(<a key={key} href={target} target="_blank" rel="noopener noreferrer">{label}</a>);
      } else {
        out.push(label);
      }
    } else if (m[3] !== undefined || m[4] !== undefined) {
      out.push(<strong key={key}>{parseInline((m[3] ?? m[4]) as string, key)}</strong>);
    } else if (m[5] !== undefined) {
      out.push(<code key={key}>{m[5]}</code>);
    } else if (m[6] !== undefined || m[7] !== undefined) {
      out.push(<em key={key}>{parseInline((m[6] ?? m[7]) as string, key)}</em>);
    }
    last = idx + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const UL_RE = /^\s*[-*+]\s+/;
const OL_RE = /^\s*\d+\.\s+/;
const H_RE = /^(#{1,6})\s+(.*)$/;

export function MarkdownMessage({ content }: { content: string }): ReactNode {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let bk = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") { i++; continue; }

    const h = H_RE.exec(line);
    if (h) {
      const lvl = Math.min(h[1].length, 3);
      blocks.push(<div key={`b${bk}`} className={`md-h md-h${lvl}`}>{parseInline(h[2], `h${bk}`)}</div>);
      bk++; i++;
      continue;
    }

    if (UL_RE.test(line)) {
      const items: ReactNode[] = [];
      while (i < lines.length && UL_RE.test(lines[i])) {
        items.push(<li key={`li${i}`}>{parseInline(lines[i].replace(UL_RE, ""), `ul${i}`)}</li>);
        i++;
      }
      blocks.push(<ul key={`b${bk++}`} className="md-list">{items}</ul>);
      continue;
    }

    if (OL_RE.test(line)) {
      const items: ReactNode[] = [];
      while (i < lines.length && OL_RE.test(lines[i])) {
        items.push(<li key={`li${i}`}>{parseInline(lines[i].replace(OL_RE, ""), `ol${i}`)}</li>);
        i++;
      }
      blocks.push(<ol key={`b${bk++}`} className="md-list">{items}</ol>);
      continue;
    }

    // Paragraph: consecutive lines that aren't a blank, list, or heading.
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !UL_RE.test(lines[i]) &&
      !OL_RE.test(lines[i]) &&
      !H_RE.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    const inner: ReactNode[] = [];
    para.forEach((p, idx) => {
      if (idx > 0) inner.push(<br key={`br${bk}-${idx}`} />);
      inner.push(...parseInline(p, `p${bk}-${idx}`));
    });
    blocks.push(<p key={`b${bk++}`} className="md-p">{inner}</p>);
  }
  return <div className="md">{blocks}</div>;
}
