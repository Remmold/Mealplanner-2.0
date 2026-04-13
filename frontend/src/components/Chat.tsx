import { useEffect, useRef, useState } from "react";
import {
  listChatSessions,
  createChatSession,
  getChatSession,
  deleteChatSession,
  sendChatMessage,
  acceptPending,
  rejectPending,
  fetchRecipe,
  dataChanged,
  navigateTo,
  type ChatMessage,
  type ChatSessionSummary,
  type ProposedAction,
  type Recipe,
} from "../api";

type PendingStatus = "pending" | "accepting" | "rejecting" | "accepted" | "rejected" | "failed";

interface PendingCard extends ProposedAction {
  status: PendingStatus;
  result?: string | null;
  created?: Record<string, string> | null;
  preview?: Recipe | null;   // fetched after accept for recipe.create
}

interface DisplayMessage {
  role: "user" | "assistant" | "system";
  content: string;
  pending?: PendingCard[];
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
      const cards: PendingCard[] = res.pending.map((p) => ({ ...p, status: "pending" }));
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply, pending: cards }]);
      // refresh session list (titles update on first message)
      listChatSessions().then(setSessions).catch(() => {});
    } catch (e) {
      setError(String(e));
    } finally {
      setSending(false);
    }
  }

  function patchCard(id: string, patch: Partial<PendingCard>) {
    setMessages((prev) =>
      prev.map((m) =>
        m.pending
          ? { ...m, pending: m.pending.map((c) => (c.id === id ? { ...c, ...patch } : c)) }
          : m
      )
    );
  }

  async function handleAccept(card: PendingCard) {
    patchCard(card.id, { status: "accepting" });
    try {
      const res = await acceptPending(card.id);
      patchCard(card.id, { status: res.status, result: res.result, created: res.created });
      if (res.status === "accepted") dataChanged("*");

      // For recipe.create we fetch the saved recipe so the user sees proof —
      // thumbnail, ingredient count, jump button. Poll every 5s for up to
      // 60s to pick up the background-generated image.
      const recipeId = res.created?.recipe_id;
      if (res.status === "accepted" && recipeId) {
        const tryFetch = async (attempt: number) => {
          try {
            const recipe = await fetchRecipe(recipeId);
            patchCard(card.id, { preview: recipe });
            if (!recipe.image_path && attempt < 12) {
              setTimeout(() => tryFetch(attempt + 1), 5000);
            }
          } catch {
            if (attempt < 3) setTimeout(() => tryFetch(attempt + 1), 2000);
          }
        };
        tryFetch(0);
      }
    } catch (e) {
      patchCard(card.id, { status: "failed", result: String(e) });
    }
  }

  async function handleReject(card: PendingCard) {
    patchCard(card.id, { status: "rejecting" });
    try {
      const res = await rejectPending(card.id);
      patchCard(card.id, { status: res.status });
    } catch (e) {
      patchCard(card.id, { status: "failed", result: String(e) });
    }
  }

  async function acceptAll(cards: PendingCard[]) {
    for (const c of cards) {
      if (c.status === "pending") await handleAccept(c);
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

        {messages.map((m, i) => {
          const stillPending = m.pending?.filter((c) => c.status === "pending") ?? [];
          return (
            <div key={i} className={`chat-msg chat-msg-${m.role}`}>
              {m.content && <div className="chat-msg-content">{m.content}</div>}
              {m.pending && m.pending.length > 0 && (
                <div className="chat-pending">
                  <div className="chat-pending-header">
                    <span>{m.pending.length} proposed action{m.pending.length === 1 ? "" : "s"}</span>
                    {stillPending.length > 1 && (
                      <button onClick={() => acceptAll(stillPending)} className="btn btn-xs btn-primary">
                        Accept all
                      </button>
                    )}
                  </div>
                  {m.pending.map((c) => (
                    <div key={c.id} className={`pending-card pending-${c.status}`}>
                      <div className="pending-card-summary">
                        <span className="pending-kind">{c.kind}</span>
                        <span className="pending-text">{c.summary}</span>
                      </div>
                      {c.status === "pending" && (
                        <div className="pending-actions">
                          <button onClick={() => handleReject(c)} className="btn btn-xs">Reject</button>
                          <button onClick={() => handleAccept(c)} className="btn btn-xs btn-primary">Accept</button>
                        </div>
                      )}
                      {c.status === "accepting" && <span className="pending-status muted">Applying…</span>}
                      {c.status === "rejecting" && <span className="pending-status muted">Rejecting…</span>}
                      {c.status === "accepted" && !c.preview && (
                        <span className="pending-status accepted">✓ {c.result || "Done"}</span>
                      )}
                      {c.status === "accepted" && c.preview && (
                        <div className="pending-preview">
                          {c.preview.image_path ? (
                            <img
                              src={`/api/recipe-images/${c.preview.image_path}`}
                              alt=""
                              className="pending-preview-img"
                            />
                          ) : (
                            <div className="pending-preview-img placeholder" title="Image is generating…" />
                          )}
                          <div className="pending-preview-body">
                            <div className="pending-preview-name">{c.preview.name}</div>
                            <div className="tiny muted">
                              {c.preview.servings} servings · {c.preview.ingredients.length} ingredients · {c.preview.instructions.length} steps
                            </div>
                          </div>
                          <button
                            onClick={() => navigateTo({ tab: "recipe", recipe_id: c.preview!.id })}
                            className="btn btn-xs btn-primary"
                          >
                            View →
                          </button>
                        </div>
                      )}
                      {c.status === "rejected" && (
                        <span className="pending-status rejected">× Rejected</span>
                      )}
                      {c.status === "failed" && (
                        <span className="pending-status failed">⚠ {c.result || "Failed"}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}

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
