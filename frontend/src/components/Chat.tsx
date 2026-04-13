import { useEffect, useRef, useState } from "react";
import {
  listChatSessions,
  createChatSession,
  getChatSession,
  deleteChatSession,
  sendChatMessage,
  dataChanged,
  type ChatMessage,
  type ChatSessionSummary,
  type ChatAuditEvent,
} from "../api";

interface DisplayMessage {
  role: "user" | "assistant" | "system";
  content: string;
  audit?: ChatAuditEvent[];
}

export default function Chat({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [showSessions, setShowSessions] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => { if (open) refreshSessions(); }, [open]);
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  async function refreshSessions() {
    try {
      const list = await listChatSessions();
      setSessions(list);
      if (!activeId && list.length > 0) {
        await loadSession(list[0].id);
      } else if (!activeId) {
        await startNewSession();
      }
    } catch (e) { setError(String(e)); }
  }

  async function startNewSession() {
    try {
      const s = await createChatSession();
      setSessions((prev) => [{ id: s.id, title: s.title, created_at: s.created_at, updated_at: s.updated_at, message_count: 0 }, ...prev]);
      setActiveId(s.id);
      setMessages([]);
      setShowSessions(false);
    } catch (e) { setError(String(e)); }
  }

  async function loadSession(id: string) {
    try {
      const detail = await getChatSession(id);
      setActiveId(detail.id);
      setMessages(detail.messages.map((m: ChatMessage) => ({ role: m.role, content: m.content })));
      setShowSessions(false);
    } catch (e) { setError(String(e)); }
  }

  async function removeSession(id: string) {
    try {
      await deleteChatSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
    } catch (e) { setError(String(e)); }
  }

  async function send() {
    const text = input.trim();
    if (!text || sending) return;

    let sid = activeId;
    if (!sid) {
      try {
        const s = await createChatSession();
        sid = s.id;
        setActiveId(sid);
        setSessions((prev) => [{ id: s.id, title: s.title, created_at: s.created_at, updated_at: s.updated_at, message_count: 0 }, ...prev]);
      } catch (e) { setError(String(e)); return; }
    }

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setSending(true);
    setError("");

    try {
      const res = await sendChatMessage(sid, text);
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply, audit: res.audit }]);
      // If the agent mutated anything, tell the rest of the app to refresh
      if (res.audit.length > 0) dataChanged("*");
      // refresh session list (titles update on first message)
      listChatSessions().then(setSessions).catch(() => {});
    } catch (e) {
      setError(String(e));
    } finally {
      setSending(false);
    }
  }

  if (!open) return null;

  return (
    <div className="chat-drawer">
      <div className="chat-header">
        <div className="row gap-2" style={{ flex: 1, alignItems: "center" }}>
          <button onClick={() => setShowSessions(!showSessions)} className="icon-btn" title="Sessions">≡</button>
          <strong style={{ fontFamily: "var(--font-serif)", fontSize: 17 }}>Hearth assistant</strong>
        </div>
        <button onClick={startNewSession} className="btn btn-ghost btn-sm">New</button>
        <button onClick={onClose} className="icon-btn" title="Close">×</button>
      </div>

      {showSessions && (
        <div className="chat-sessions">
          {sessions.length === 0 && <div className="empty small">No previous chats.</div>}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`chat-session-row ${s.id === activeId ? "active" : ""}`}
              onClick={() => loadSession(s.id)}
            >
              <div className="flex-1" style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {s.title}
                </div>
                <div className="tiny muted">{s.message_count} messages</div>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); removeSession(s.id); }}
                className="icon-btn"
                style={{ width: 22, height: 22, fontSize: 12 }}
              >×</button>
            </div>
          ))}
        </div>
      )}

      <div className="chat-body" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-welcome">
            <p style={{ fontFamily: "var(--font-serif)", fontSize: 18, marginBottom: 8 }}>Hi there 👋</p>
            <p className="muted small">
              I can manage your recipes, plans and pantry. Try:
            </p>
            <ul className="chat-suggestions">
              <li onClick={() => setInput("Create a vegetarian week starting next Monday for 4 people")}>
                "Create a vegetarian week starting next Monday for 4 people"
              </li>
              <li onClick={() => setInput("Add Thai red curry to Wednesday dinner in my current plan")}>
                "Add Thai red curry to Wednesday dinner"
              </li>
              <li onClick={() => setInput("Generate a quick weeknight pasta and save it")}>
                "Generate a quick weeknight pasta and save it"
              </li>
              <li onClick={() => setInput("Show me my saved recipes")}>
                "Show me my saved recipes"
              </li>
            </ul>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`chat-msg chat-msg-${m.role}`}>
            <div className="chat-msg-content">{m.content}</div>
            {m.audit && m.audit.length > 0 && (
              <div className="chat-audit">
                {m.audit.map((a, j) => (
                  <div key={j} className="chat-audit-item">
                    <span className="chat-audit-dot" />
                    <span>{a.summary}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}

        {sending && (
          <div className="chat-msg chat-msg-assistant">
            <div className="chat-typing">
              <span></span><span></span><span></span>
            </div>
          </div>
        )}

        {error && <div className="error">{error}</div>}
      </div>

      <div className="chat-input-row">
        <textarea
          className="textarea"
          placeholder="Ask the assistant…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
          }}
          rows={2}
          disabled={sending}
        />
        <button onClick={send} disabled={sending || !input.trim()} className="btn btn-primary">
          Send
        </button>
      </div>
    </div>
  );
}
