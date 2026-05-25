import { useEffect, useRef, useState } from "react";
import { ArrowRight, Check, Hand, Menu, TriangleAlert, X } from "lucide-react";
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
import { Button, Empty, ErrorBanner, IconButton, Textarea } from "./ui";

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
        <div className="row gap-2 flex-1">
          <IconButton onClick={() => setShowSessions(!showSessions)} title="Sessions">
            <Menu size={16} />
          </IconButton>
          <strong className="chat-title">Hearth assistant</strong>
        </div>
        <Button onClick={startNewSession} variant="ghost" size="sm">New</Button>
        <IconButton onClick={onClose} title="Close">
          <X size={16} />
        </IconButton>
      </div>

      {showSessions && (
        <div className="chat-sessions">
          {sessions.length === 0 && <Empty className="small">No previous chats.</Empty>}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`chat-session-row ${s.id === activeId ? "active" : ""}`}
              onClick={() => loadSession(s.id)}
            >
              <div className="flex-1">
                <div className="chat-session-title">{s.title}</div>
                <div className="tiny muted">{s.message_count} messages</div>
              </div>
              <IconButton
                onClick={(e) => { e.stopPropagation(); removeSession(s.id); }}
                className="icon-btn-sm"
                aria-label="Delete chat"
              >
                <X size={12} />
              </IconButton>
            </div>
          ))}
        </div>
      )}

      <div className="chat-body" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="chat-welcome">
            <p className="chat-greeting">Hi there <Hand size={18} /></p>
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
                      <Button onClick={() => acceptAll(stillPending)} size="xs" variant="primary">
                        Accept all
                      </Button>
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
                          <Button onClick={() => handleReject(c)} size="xs">Reject</Button>
                          <Button onClick={() => handleAccept(c)} size="xs" variant="primary">Accept</Button>
                        </div>
                      )}
                      {c.status === "accepting" && <span className="pending-status muted">Applying…</span>}
                      {c.status === "rejecting" && <span className="pending-status muted">Rejecting…</span>}
                      {c.status === "accepted" && !c.preview && (
                        <span className="pending-status accepted"><Check size={14} /> {c.result || "Done"}</span>
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
                          <Button
                            onClick={() => navigateTo({ tab: "recipe", recipe_id: c.preview!.id })}
                            size="xs"
                            variant="primary"
                          >
                            View <ArrowRight size={12} />
                          </Button>
                        </div>
                      )}
                      {c.status === "rejected" && (
                        <span className="pending-status rejected"><X size={14} /> Rejected</span>
                      )}
                      {c.status === "failed" && (
                        <span className="pending-status failed"><TriangleAlert size={14} /> {c.result || "Failed"}</span>
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

        <ErrorBanner>{error}</ErrorBanner>
      </div>

      <div className="chat-input-row">
        <Textarea
          placeholder="Ask the assistant…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
          }}
          rows={2}
          disabled={sending}
        />
        <Button onClick={send} disabled={sending || !input.trim()} variant="primary">
          Send
        </Button>
      </div>
    </div>
  );
}
