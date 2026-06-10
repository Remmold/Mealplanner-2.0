import { useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import { ArrowRight, Check, Hand, Menu, Sparkles, TriangleAlert, X } from "lucide-react";
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
import { Button, Empty, ErrorBanner, IconButton, Modal, Textarea } from "./ui";
import { MarkdownMessage } from "../lib/markdown";

interface ProgressItem {
  id: string;
  status: "running" | "done" | "failed";
  icon: ReactNode;
  text: string;
}

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
  const { t } = useTranslation();

  // Friendly category tag for a proposal card, from the kind's domain prefix
  // (e.g. "profile.field" -> "Preference"). Literal keys keep t() type-safe.
  const kindLabel = (kind: string): string => {
    switch (kind.split(".")[0]) {
      case "recipe": return t("chat.pending.kinds.recipe");
      case "calendar": return t("chat.pending.kinds.calendar");
      case "profile": return t("chat.pending.kinds.profile");
      case "pantry": return t("chat.pending.kinds.pantry");
      case "plan": return t("chat.pending.kinds.plan");
      default: return kind.split(".")[0];
    }
  };
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [showSessions, setShowSessions] = useState(false);
  const [progressItems, setProgressItems] = useState<ProgressItem[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const progressOpen = progressItems.length > 0;
  const progressDone = progressOpen && progressItems.every((p) => p.status !== "running");

  function pushProgress(item: ProgressItem) {
    setProgressItems((prev) => [...prev, item]);
  }
  function updateProgress(id: string, patch: Partial<ProgressItem>) {
    setProgressItems((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }

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
    pushProgress({
      id: card.id,
      status: "running",
      icon: <Sparkles size={14} />,
      text: card.summary,
    });
    try {
      const res = await acceptPending(card.id);
      patchCard(card.id, { status: res.status, result: res.result, created: res.created });
      updateProgress(card.id, {
        status: res.status === "accepted" ? "done" : "failed",
        icon: res.status === "accepted" ? <Check size={14} /> : <TriangleAlert size={14} />,
        text: res.result || (res.status === "accepted" ? card.summary : t("chat.failed")),
      });
      if (res.status === "accepted") dataChanged("*");

      // When an entry just landed on the meal plan, jump the calendar to the
      // week that contains it so the user sees the addition live.
      const planDate = res.created?.plan_date;
      if (res.status === "accepted" && planDate) {
        navigateTo({ tab: "plan", week_start: planDate });
      }

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
      updateProgress(card.id, {
        status: "failed",
        icon: <TriangleAlert size={14} />,
        text: String(e),
      });
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

  // Dismiss on Escape (pairs with the click-outside backdrop below).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div className="chat-backdrop" onClick={onClose} aria-hidden />
      <div className="chat-drawer">
      <div className="chat-header">
        <div className="row gap-2 flex-1">
          <IconButton onClick={() => setShowSessions(!showSessions)} title={t("chat.header.sessions")}>
            <Menu size={16} />
          </IconButton>
          <strong className="chat-title">{t("chat.header.title")}</strong>
        </div>
        <Button onClick={startNewSession} variant="ghost" size="sm">{t("chat.header.newChat")}</Button>
        <IconButton onClick={onClose} title={t("common.close")}>
          <X size={16} />
        </IconButton>
      </div>

      {showSessions && (
        <div className="chat-sessions">
          {sessions.length === 0 && <Empty className="small">{t("chat.sessions.empty")}</Empty>}
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`chat-session-row ${s.id === activeId ? "active" : ""}`}
              onClick={() => loadSession(s.id)}
            >
              <div className="flex-1">
                <div className="chat-session-title">{s.title}</div>
                <div className="tiny muted">{t("chat.sessions.messageCount", { count: s.message_count })}</div>
              </div>
              <IconButton
                onClick={(e) => { e.stopPropagation(); removeSession(s.id); }}
                className="icon-btn-sm"
                aria-label={t("chat.sessions.deleteChat")}
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
            <p className="chat-greeting"><Trans i18nKey="chat.welcome.greeting" /> <Hand size={18} /></p>
            <p className="muted small">
              {t("chat.welcome.intro")}
            </p>
            <ul className="chat-suggestions">
              <li onClick={() => setInput(t("chat.welcome.suggestions.vegetarianWeekPrompt"))}>
                {t("chat.welcome.suggestions.vegetarianWeekLabel")}
              </li>
              <li onClick={() => setInput(t("chat.welcome.suggestions.addCurryPrompt"))}>
                {t("chat.welcome.suggestions.addCurryLabel")}
              </li>
              <li onClick={() => setInput(t("chat.welcome.suggestions.quickPastaPrompt"))}>
                {t("chat.welcome.suggestions.quickPastaLabel")}
              </li>
              <li onClick={() => setInput(t("chat.welcome.suggestions.savedRecipesPrompt"))}>
                {t("chat.welcome.suggestions.savedRecipesLabel")}
              </li>
            </ul>
          </div>
        )}

        {messages.map((m, i) => {
          const stillPending = m.pending?.filter((c) => c.status === "pending") ?? [];
          return (
            <div key={i} className={`chat-msg chat-msg-${m.role}`}>
              {m.content && (
                <div className="chat-msg-content">
                  {m.role === "assistant"
                    ? <MarkdownMessage content={m.content} />
                    : m.content}
                </div>
              )}
              {m.pending && m.pending.length > 0 && (
                <div className="chat-pending">
                  <div className="chat-pending-header">
                    <span>{t("chat.pending.header", { count: m.pending.length })}</span>
                    {stillPending.length > 1 && (
                      <Button onClick={() => acceptAll(stillPending)} size="xs" variant="primary">
                        {t("chat.pending.acceptAll")}
                      </Button>
                    )}
                  </div>
                  {m.pending.map((c) => (
                    <div key={c.id} className={`pending-card pending-${c.status}`}>
                      <div className="pending-card-summary">
                        <span className="pending-kind">{kindLabel(c.kind)}</span>
                        <span className="pending-text">{c.summary}</span>
                      </div>
                      {c.status === "pending" && (
                        <div className="pending-actions">
                          <Button onClick={() => handleReject(c)} size="xs">{t("chat.pending.reject")}</Button>
                          <Button onClick={() => handleAccept(c)} size="xs" variant="primary">{t("chat.pending.accept")}</Button>
                        </div>
                      )}
                      {c.status === "accepting" && <span className="pending-status muted">{t("chat.pending.applying")}</span>}
                      {c.status === "rejecting" && <span className="pending-status muted">{t("chat.pending.rejecting")}</span>}
                      {c.status === "accepted" && !c.preview && (
                        <span className="pending-status accepted"><Check size={14} /> {c.result || t("common.done")}</span>
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
                            <div className="pending-preview-img placeholder" title={t("chat.pending.imageGenerating")} />
                          )}
                          <div className="pending-preview-body">
                            <div className="pending-preview-name">{c.preview.name}</div>
                            <div className="tiny muted">
                              {t("chat.pending.previewMeta", {
                                servings: c.preview.servings,
                                toBuy: c.preview.ingredients.length,
                                steps: c.preview.instructions.length,
                                count: c.preview.instructions.length,
                              })}
                            </div>
                          </div>
                          <Button
                            onClick={() => navigateTo({ tab: "recipe", recipe_id: c.preview!.id })}
                            size="xs"
                            variant="primary"
                          >
                            {t("chat.pending.view")} <ArrowRight size={12} />
                          </Button>
                        </div>
                      )}
                      {c.status === "rejected" && (
                        <span className="pending-status rejected"><X size={14} /> {t("chat.pending.rejected")}</span>
                      )}
                      {c.status === "failed" && (
                        <span className="pending-status failed"><TriangleAlert size={14} /> {c.result || t("chat.failed")}</span>
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

      <Modal
        open={progressOpen}
        onClose={() => { if (progressDone) setProgressItems([]); }}
      >
        <h3 className="m-0">{t("chat.progress.heading")}</h3>
        <p className="muted small mt-1">
          {progressDone
            ? t("chat.progress.allDone")
            : t("chat.progress.working")}
        </p>
        <ul className="gen-feed-list mt-3">
          {progressItems.map((item) => (
            <li key={item.id} className={`gen-feed-item gen-feed-${item.status === "running" ? "pending" : item.status}`}>
              <span className="gen-feed-icon">{item.icon}</span>
              <span className="gen-feed-text">{item.text}</span>
            </li>
          ))}
        </ul>
        {progressDone && (
          <Button onClick={() => setProgressItems([])} variant="primary" className="mt-3">
            {t("common.done")}
          </Button>
        )}
      </Modal>

      <div className="chat-input-row">
        <Textarea
          placeholder={t("chat.input.placeholder")}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
          }}
          rows={2}
          disabled={sending}
        />
        <Button onClick={send} disabled={sending || !input.trim()} variant="primary">
          {t("chat.input.send")}
        </Button>
      </div>
      </div>
    </>
  );
}
