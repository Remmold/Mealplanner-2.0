import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { Check, ChefHat, Clock, Eye, Heart, Rewind, Sparkles, Utensils, X } from "lucide-react";
import {
  fetchExploreDeck,
  fetchExploreRecipeDetail,
  fetchExploreStats,
  swipeRecipe,
  undoLastSwipe,
  dataChanged,
  navigateTo,
  type ExploreCard,
  type ExploreRecipeDetail,
  type ExploreStats,
  type SlotFilter,
} from "../api";
import { Button, Card, Empty, ErrorBanner, Modal, Pill } from "./ui";

// How far the user has to drag (px) for a swipe to fire on release.
const SWIPE_THRESHOLD_PX = 110;
// Below this card count we prefetch the next batch in the background.
const PREFETCH_BELOW = 5;

// Dinner-only world — the filter chips collapse to "All / Dinner" so
// breakfast/lunch recipes (if any seep in from the pool) can still be
// discovered but they're no longer surfaced by default.
const SLOT_OPTIONS: { id: SlotFilter; label: string }[] = [
  { id: "dinner", label: "Dinner" },
  { id: "any",    label: "All" },
];

interface BannerState {
  recipeId: string;
  recipeName: string;
  addedCuisines: string[];
}

export default function Explore() {
  const [slot, setSlot] = useState<SlotFilter>("dinner");
  const [deck, setDeck] = useState<ExploreCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [stats, setStats] = useState<ExploreStats | null>(null);
  const [banner, setBanner] = useState<BannerState | null>(null);

  // Drag state lives in refs so re-render doesn't churn the gesture; we mirror
  // the displacement into React state for the transform that drives animation.
  const dragStart = useRef<{ x: number; y: number; pointerId: number } | null>(null);
  const [drag, setDrag] = useState({ dx: 0, dy: 0, swiping: false });
  // The card flying off after a swipe. Rendered SEPARATELY from the deck so
  // that the next card (previously the visible peek[0]) keeps its DOM
  // identity and smoothly transitions from peek-position to top-position —
  // no more "the underneath card got replaced" visual glitch.
  const [exiting, setExiting] = useState<{ card: ExploreCard; direction: "left" | "right" } | null>(null);
  // Inspect modal: opening it pauses gestures so the user can read.
  const [inspecting, setInspecting] = useState<ExploreRecipeDetail | null>(null);
  const [inspectLoading, setInspectLoading] = useState(false);

  async function openInspect(cardId: string) {
    setInspectLoading(true);
    try {
      const detail = await fetchExploreRecipeDetail(cardId);
      setInspecting(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setInspectLoading(false);
    }
  }

  const refreshStats = useCallback(() => {
    fetchExploreStats().then(setStats).catch(() => {});
  }, []);

  const loadDeck = useCallback(async (s: SlotFilter) => {
    setLoading(true);
    setError("");
    // Clear in-memory cards immediately so a stale deck never lingers during
    // refetch — important because the pool can be edited server-side between
    // mounts.
    setDeck([]);
    try {
      const cards = await fetchExploreDeck(s, 20);
      setDeck(cards);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadDeck(slot); refreshStats(); }, [slot, loadDeck, refreshStats]);

  // Refetch when the user returns to the tab (other tab updates the pool,
  // so coming back should pick up changes without a hard refresh).
  useEffect(() => {
    function onFocus() { loadDeck(slot); refreshStats(); }
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [slot, loadDeck, refreshStats]);

  const top = deck[0] ?? null;

  async function applySwipe(direction: "like" | "skip") {
    if (!top || exiting) return;   // ignore re-triggers mid-exit
    const card = top;

    // Pop the deck IMMEDIATELY so what was peek[0] becomes the new top in the
    // same render. With a stable key its DOM is reused and the CSS transition
    // smoothly animates its transform from peek-position to (0,0). Meanwhile
    // `exiting` renders the swiped card separately, flying off-screen.
    setExiting({ card, direction: direction === "like" ? "right" : "left" });
    setDeck((prev) => prev.slice(1));
    setDrag({ dx: 0, dy: 0, swiping: false });

    const apiPromise = swipeRecipe(card.id, direction);

    // Wait slightly longer than the .28s transition before unmounting.
    await new Promise((resolve) => setTimeout(resolve, 320));
    setExiting(null);

    try {
      const res = await apiPromise;
      if (direction === "like") {
        dataChanged("recipes");
        if (res.saved_recipe_id) {
          setBanner({
            recipeId: res.saved_recipe_id,
            recipeName: res.saved_recipe_name ?? card.name,
            addedCuisines: res.profile_added_cuisines,
          });
        }
      }
      refreshStats();
    } catch (e) {
      // Card has already flown out; surface the error rather than rewinding.
      setError(e instanceof Error ? e.message : String(e));
    }
    if (deck.length - 1 <= PREFETCH_BELOW) loadDeck(slot);
  }

  async function applyUndo() {
    try {
      await undoLastSwipe();
      await loadDeck(slot);
      refreshStats();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function onPointerDown(e: ReactPointerEvent<HTMLDivElement>) {
    if (!top) return;
    dragStart.current = { x: e.clientX, y: e.clientY, pointerId: e.pointerId };
    (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
    setDrag({ dx: 0, dy: 0, swiping: true });
  }

  function onPointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    if (!dragStart.current || dragStart.current.pointerId !== e.pointerId) return;
    setDrag({
      dx: e.clientX - dragStart.current.x,
      dy: e.clientY - dragStart.current.y,
      swiping: true,
    });
  }

  function onPointerUp(e: ReactPointerEvent<HTMLDivElement>) {
    if (!dragStart.current || dragStart.current.pointerId !== e.pointerId) return;
    const { dx } = drag;
    dragStart.current = null;
    if (dx > SWIPE_THRESHOLD_PX) applySwipe("like");
    else if (dx < -SWIPE_THRESHOLD_PX) applySwipe("skip");
    else setDrag({ dx: 0, dy: 0, swiping: false });
  }

  // Keyboard shortcuts. ← skip · → like · ↑ save+plan · ↓ undo.
  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if (!top || e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "ArrowLeft") { e.preventDefault(); applySwipe("skip"); }
      else if (e.key === "ArrowRight") { e.preventDefault(); applySwipe("like"); }
      else if (e.key === "ArrowDown") { e.preventDefault(); applyUndo(); }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [top, deck, slot]);

  // Cards behind the top one — visible as a "deck" hint.
  return (
    <div className="col gap-4">
      <div className="hero">
        <h1>Explore</h1>
        <p>
          Swipe through recipes from the starter library, fresh AI generations, and
          other households. Right to save, left to skip. Three likes in a cuisine
          and we&apos;ll quietly add it to your profile.
        </p>
      </div>

      <ErrorBanner>{error}</ErrorBanner>

      <div className="row gap-2 wrap items-center">
        <span className="overline muted">Filter</span>
        {SLOT_OPTIONS.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setSlot(s.id)}
            className={"chip" + (slot === s.id ? " chip-active" : "")}
          >
            {s.label}
          </button>
        ))}
        {stats && (
          <span className="ml-auto small muted">
            ♥ {stats.likes} · ✕ {stats.skips} · pool: {stats.pool_size}
          </span>
        )}
      </div>

      {banner && (
        <Card variant="soft" className="explore-banner">
          <div className="row gap-3 items-center">
            <Check size={18} className="explore-banner-icon" />
            <div className="flex-1">
              <div className="fw-600">Saved &lsquo;{banner.recipeName}&rsquo;</div>
              {banner.addedCuisines.length > 0 && (
                <div className="tiny muted">
                  Added {banner.addedCuisines.join(", ")} to your cuisine preferences.
                </div>
              )}
            </div>
            <Button size="sm" variant="primary" onClick={() => {
              navigateTo({ tab: "plan" });
              setBanner(null);
            }}>
              Add to plan
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setBanner(null)}>
              Dismiss
            </Button>
          </div>
        </Card>
      )}

      {loading && deck.length === 0 && <div className="muted">Loading deck…</div>}

      {!loading && !top && (
        <Empty>
          The deck is empty for this filter. Try a different slot, or come back
          after a meal-plan generation fills the pool with fresh recipes.
        </Empty>
      )}

      {(top || exiting) && (
        <div className="explore-stage">
          {/* Unified deck render: stable keys per recipe so the previously
              peek[0] card keeps its DOM when it bubbles up to top. Top card
              (index 0) gets the drag handlers, peek cards are inert. */}
          {deck.slice(0, 3).map((card, i) => {
            const isTop = i === 0;
            return (
              <div
                key={card.id}
                className={
                  "explore-card " +
                  (isTop ? "explore-card-top" : "explore-card-peek") +
                  (isTop && drag.swiping ? " is-dragging" : "")
                }
                style={{
                  transform: isTop
                    ? `translate(${drag.dx}px, ${drag.dy * 0.4}px) rotate(${drag.dx * 0.05}deg)`
                    : `translateY(${i * 10}px) scale(${1 - i * 0.04})`,
                  zIndex: 10 - i,
                }}
                onPointerDown={isTop ? onPointerDown : undefined}
                onPointerMove={isTop ? onPointerMove : undefined}
                onPointerUp={isTop ? onPointerUp : undefined}
                onPointerCancel={isTop ? onPointerUp : undefined}
                aria-hidden={!isTop}
              >
                <CardBody card={card} muted={!isTop} onInspect={isTop ? () => openInspect(card.id) : undefined} />
                {isTop && (
                  <>
                    <div
                      className="explore-decision explore-decision-like"
                      style={{ opacity: Math.max(0, Math.min(1, drag.dx / SWIPE_THRESHOLD_PX)) }}
                      aria-hidden
                    >
                      SAVE
                    </div>
                    <div
                      className="explore-decision explore-decision-skip"
                      style={{ opacity: Math.max(0, Math.min(1, -drag.dx / SWIPE_THRESHOLD_PX)) }}
                      aria-hidden
                    >
                      SKIP
                    </div>
                  </>
                )}
              </div>
            );
          })}

          {/* The flying-off card. Lives outside the deck map; once setExiting
              clears it after the 320ms wait, React unmounts it cleanly. */}
          {exiting && (
            <div
              key={exiting.card.id}
              className="explore-card explore-card-top"
              style={{
                transform: `translate(${exiting.direction === "right" ? 1500 : -1500}px, -120px) rotate(${exiting.direction === "right" ? 30 : -30}deg)`,
                zIndex: 20,
                pointerEvents: "none",
              }}
              aria-hidden
            >
              <CardBody card={exiting.card} />
              <div
                className="explore-decision explore-decision-like"
                style={{ opacity: exiting.direction === "right" ? 1 : 0 }}
                aria-hidden
              >
                SAVE
              </div>
              <div
                className="explore-decision explore-decision-skip"
                style={{ opacity: exiting.direction === "left" ? 1 : 0 }}
                aria-hidden
              >
                SKIP
              </div>
            </div>
          )}
        </div>
      )}

      {inspectLoading && (
        <div className="modal-backdrop" aria-hidden>
          <div className="modal">
            <div className="muted">Loading recipe…</div>
          </div>
        </div>
      )}

      <Modal
        open={!!inspecting}
        onClose={() => setInspecting(null)}
        title={inspecting?.name}
      >
        {inspecting && (
          <div className="col gap-3">
            <div className="row gap-2 wrap">
              {inspecting.meal_type && <Pill className="pill-match">{inspecting.meal_type}</Pill>}
              {inspecting.cuisine.map((c) => <Pill key={c}>{c}</Pill>)}
              {inspecting.time_min != null && (
                <span className="explore-card-meta"><Clock size={12} /> {inspecting.time_min} min</span>
              )}
              <span className="explore-card-meta">
                <Utensils size={12} /> {inspecting.ingredients.length} ingredients
              </span>
            </div>
            <div>
              <h4 className="mt-2">Ingredients</h4>
              <ul className="explore-inspect-ingredients">
                {inspecting.ingredients.map((ing, i) => {
                  const useDisplay =
                    ing.display_quantity != null &&
                    ing.display_unit != null &&
                    ing.display_unit !== "g";
                  const qtyText = useDisplay
                    ? `${ing.display_quantity} ${ing.display_unit}`
                    : `${Math.round(ing.quantity_g)}g`;
                  return (
                    <li key={`${ing.fdc_id}-${i}`}>
                      <span className="small muted">{qtyText}</span>{" "}
                      {ing.name ?? `fdc ${ing.fdc_id}`}
                    </li>
                  );
                })}
              </ul>
            </div>
            <div>
              <h4 className="mt-2">Instructions</h4>
              <ol className="explore-inspect-instructions">
                {inspecting.instructions.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
            </div>
            <div className="row gap-2 justify-end mt-3">
              <Button variant="ghost" onClick={() => { setInspecting(null); applySwipe("skip"); }}>
                Skip
              </Button>
              <Button variant="primary" onClick={() => { setInspecting(null); applySwipe("like"); }}>
                <Heart size={14} /> Save
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {top && (
        <div className="row gap-3 justify-center">
          <button
            type="button"
            onClick={() => applySwipe("skip")}
            className="explore-action explore-action-skip"
            title="Skip (←)"
            aria-label="Skip"
          >
            <X size={22} />
          </button>
          <button
            type="button"
            onClick={applyUndo}
            className="explore-action explore-action-undo"
            title="Undo last (↓)"
            aria-label="Undo last swipe"
          >
            <Rewind size={18} />
          </button>
          <button
            type="button"
            onClick={() => applySwipe("like")}
            className="explore-action explore-action-like"
            title="Save (→)"
            aria-label="Save"
          >
            <Heart size={22} />
          </button>
        </div>
      )}
    </div>
  );
}


function CardBody({ card, muted = false, onInspect }: { card: ExploreCard; muted?: boolean; onInspect?: () => void }) {
  const slot = card.meal_type;
  const sourceLabel =
    card.source === "starter_corpus" ? "starter" :
    card.source === "llm" ? "community AI" : "shared";

  return (
    <div className={"explore-card-body" + (muted ? " explore-card-body-muted" : "")}>
      <div className="explore-card-image">
        {card.image_path ? (
          <img
            src={`/api/recipe-images/${card.image_path}`}
            alt=""
            draggable={false}
            onDragStart={(e) => e.preventDefault()}
          />
        ) : (
          <div className="explore-card-placeholder">
            <ChefHat size={48} />
          </div>
        )}
        <span className="explore-card-source">
          <Sparkles size={11} /> {sourceLabel}
        </span>
        {onInspect && (
          <button
            type="button"
            className="explore-card-inspect"
            onClick={(e) => { e.stopPropagation(); onInspect(); }}
            onPointerDown={(e) => e.stopPropagation()}
            aria-label="Inspect recipe"
            title="View full recipe"
          >
            <Eye size={16} />
          </button>
        )}
      </div>
      <div className="explore-card-content">
        <h2 className="explore-card-name">{card.name}</h2>
        <div className="row gap-2 wrap">
          {slot && <Pill className="pill-match">{slot}</Pill>}
          {card.cuisine.slice(0, 2).map((c) => (
            <Pill key={c}>{c}</Pill>
          ))}
          {card.time_min != null && (
            <span className="explore-card-meta"><Clock size={12} /> {card.time_min} min</span>
          )}
          <span className="explore-card-meta">
            <Utensils size={12} /> {card.ingredient_count} ingredients · {card.step_count} steps
          </span>
        </div>
        {card.ingredients_preview.length > 0 && (
          <p className="explore-card-ingredients">
            {card.ingredients_preview.join(" · ")}
            {card.ingredient_count > card.ingredients_preview.length &&
              ` …+${card.ingredient_count - card.ingredients_preview.length}`}
          </p>
        )}
        {card.match_reasons.length > 0 && (
          <p className="explore-card-reasons">
            <span className="overline muted">Why this</span>{" "}
            {card.match_reasons.join(" · ")}
          </p>
        )}
      </div>
    </div>
  );
}
