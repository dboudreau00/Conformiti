import { memo, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRightIcon } from "lucide-react";
import { cn } from "../../utils/cn.js";
import { CONTROL_STATUS, READINESS_BAND, TONE_FILL, TONE_TEXT } from "../../utils/tone.js";
import { Badge } from "../ui/Badge.jsx";
import { Empty, Label, LoadError, Loading, Panel } from "../ui/Panel.jsx";
import { joinSome } from "../ui/ShowMore.jsx";
import { STATUS_FILL, StatusGlyph } from "./StatusGlyph.jsx";

/** Above this many controls the field offers framework chips, and draws only
 * the largest few until the reader chooses more: a thousand squares of nine
 * pixels cannot be read as a map. */
const CHIP_FROM = 600;
const DEFAULT_DRAWN = 4;
/** Past this many squares a change of light is not animated: thousands of
 * simultaneous fades are work for the browser and no help to the reader. */
const BIG_FROM = 800;
/** Partners named in the place card before "and N more". */
const LISTED = 6;
const NONE = new Set();
/** The legend reads in the schedule's order, not the vocabulary's. */
const LEGEND = ["implemented", "in_progress", "not_started", "not_applicable"];

/** The edge of a square shrinks as the field grows, down to a floor. */
function cellFor(count) {
  const step = Math.floor(Math.sqrt(220000 / Math.max(count, 1)));
  return Math.max(9, Math.min(20, step - 3));
}

/** A territory is drawn roughly square-ish, wider than tall. */
const columnsFor = (n) => Math.max(4, Math.ceil(Math.sqrt(n * 1.5)));

/** Everything the interaction needs, built once per response: territories in
 * the schedule's order holding their controls in register order, and the
 * crosswalk turned into an index from a control to the themes it sits in. */
function buildModel(data) {
  const territories = data.frameworks.map((fw) => ({ fw, controls: [], by: {} }));
  const place = new Map();
  territories.forEach((t, ti) => t.fw.categories.forEach((cat) => place.set(cat.id, ti)));
  const byId = new Map();
  for (const c of data.controls) {
    const ti = place.get(c.category);
    if (ti === undefined) continue;
    const t = territories[ti];
    const item = { ...c, fw: t.fw, ti, i: t.controls.length };
    t.controls.push(item);
    t.by[c.status] = (t.by[c.status] || 0) + 1;
    byId.set(c.id, item);
  }
  const themesOf = new Map();
  data.themes.forEach((theme, ti) => {
    for (const id of theme.controls) {
      if (!byId.has(id)) continue;
      const list = themesOf.get(id);
      if (list) list.push(ti);
      else themesOf.set(id, [ti]);
    }
  });
  return { territories: territories.filter((t) => t.controls.length), byId, themes: data.themes, themesOf, total: byId.size };
}

/** Every control that shares a theme with `id`: its crosswalk partners. */
function partnersOf(model, id) {
  const out = new Set();
  for (const ti of model.themesOf.get(id) || []) {
    for (const member of model.themes[ti].controls) if (member !== id) out.add(member);
  }
  return out;
}

/** The place card's view of the partners: strongest first (most themes in
 * common), then the territories' order, and how many sit in each framework. */
function partnerDetail(model, id) {
  const shared = new Map();
  const themes = model.themesOf.get(id) || [];
  for (const ti of themes) {
    for (const member of model.themes[ti].controls) {
      if (member !== id) shared.set(member, (shared.get(member) || 0) + 1);
    }
  }
  const list = [...shared.keys()]
    .map((pid) => model.byId.get(pid))
    .filter(Boolean)
    .sort((a, b) => shared.get(b.id) - shared.get(a.id) || a.ti - b.ti || a.i - b.i);
  const tally = new Map();
  for (const p of list) tally.set(p.fw.id, { fw: p.fw, n: (tally.get(p.fw.id)?.n || 0) + 1, ti: p.ti });
  return {
    list,
    tally: [...tally.values()].sort((a, b) => a.ti - b.ti),
    themes: themes.map((ti) => model.themes[ti].theme),
  };
}

function defaultDrawn(model) {
  const size = (t) => t.controls.length - (t.by.not_applicable || 0);
  const largest = [...model.territories]
    .sort((a, b) => size(b) - size(a) || a.controls[0].ti - b.controls[0].ti)
    .slice(0, DEFAULT_DRAWN);
  return new Set(largest.map((t) => t.fw.id));
}

const SQUARE =
  "relative block h-[var(--cell)] w-[var(--cell)] rounded-[3px] border p-0 transition-opacity duration-150 ease-out " +
  "group-data-[big=true]/field:transition-none " +
  "group-data-[light=true]/field:[&:not([data-lit=true])]:opacity-[0.38] " +
  "data-[lit=true]:shadow-[0_0_0_1.5px_rgb(var(--accent)),0_0_8px_1px_rgb(var(--accent)/0.55)]";
// Important, so they win over the global :focus-visible ring on the one
// square the keyboard is on: that square is the probe, and this is its focus.
const HOT = "!opacity-100 z-10 !outline !outline-2 !outline-offset-1 !outline-ink";
const PINNED = "!opacity-100 z-10 !outline !outline-[length:3px] !outline-offset-1 !outline-ink";

/** One control. Memoised, and fed only primitives besides the control itself,
 * so moving the pointer re-renders the few squares whose state changed and
 * not the thousand beside them. */
const Square = memo(function Square({ c, tab, lit, hot, pinned }) {
  const label = `${c.ref}, ${c.title}, ${CONTROL_STATUS[c.status]?.label || c.status}`;
  // Not through cn(): tailwind-merge reads `outline` as a width, as in Tailwind
  // 4, and would drop the style these classes need.
  const className = pinned ? `${SQUARE} ${PINNED}` : hot ? `${SQUARE} ${HOT}` : SQUARE;
  return (
    <button
      type="button"
      data-cid={c.id}
      data-status={c.status}
      data-lit={lit ? "true" : undefined}
      tabIndex={tab ? 0 : -1}
      aria-label={label}
      aria-pressed={pinned}
      title={label}
      style={STATUS_FILL[c.status] || STATUS_FILL.not_started}
      className={className}
    />
  );
});

const cidOf = (e) => {
  const el = e.target.closest ? e.target.closest("[data-cid]") : null;
  return el ? Number(el.dataset.cid) : null;
};

/** What the coverage atlas draws, and what it does with it.
 *
 * Every control is one small square, grouped into a territory per framework in
 * the schedule's order. Hovering or focusing a square lights the controls that
 * answer the same theme in any territory (its crosswalk partners) and dims
 * the rest; a click or Enter pins it and opens its place card. There are no
 * lines between squares: with a few hundred partners they would be a hairball,
 * and a lit square is something a keyboard can reach and a screen reader can
 * be told about. The field is one tab stop with arrow keys inside it. */
export function CoverageAtlas({ data, loading, error, onRetry }) {
  const uid = useId();
  const fieldRef = useRef(null);
  const sideRef = useRef(null);
  const [chosen, setChosen] = useState(null);
  const [hoverId, setHoverId] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const [pinnedId, setPinnedId] = useState(null);
  const [rovingId, setRovingId] = useState(null);
  // Escape puts the lights out even while a square still has focus.
  const [quiet, setQuiet] = useState(false);

  const model = useMemo(() => (data ? buildModel(data) : null), [data]);

  // A refreshed response can drop a control the reader had pinned.
  useEffect(() => {
    if (model && pinnedId !== null && !model.byId.has(pinnedId)) setPinnedId(null);
  }, [model, pinnedId]);

  // On a narrow page the selected-control card sits under the field, which can
  // put it below the fold when a square is chosen: bring it into view, and only
  // that far. Beside the field it is already where the reader is looking.
  useEffect(() => {
    const side = sideRef.current;
    const field = fieldRef.current;
    if (pinnedId === null || !side || !field) return;
    if (side.getBoundingClientRect().top < field.getBoundingClientRect().bottom - 1) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    side.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
  }, [pinnedId]);

  const chips = !!model && model.total > CHIP_FROM;
  const drawnIds = useMemo(() => {
    if (!model) return NONE;
    if (!chips) return new Set(model.territories.map((t) => t.fw.id));
    return chosen ? new Set([...chosen].filter((id) => model.territories.some((t) => t.fw.id === id))) : defaultDrawn(model);
  }, [model, chips, chosen]);
  const shown = useMemo(() => (model ? model.territories.filter((t) => drawnIds.has(t.fw.id)) : []), [model, drawnIds]);

  // Where each drawn control sits, for the arrow keys: its territory, its
  // place inside it, and its place in the whole field.
  const { flat, where, counts } = useMemo(() => {
    const list = [];
    const at = new Map();
    const tally = { implemented: 0, in_progress: 0, not_started: 0, not_applicable: 0 };
    shown.forEach((t, ti) => {
      t.controls.forEach((c, i) => {
        at.set(c.id, { ti, i, f: list.length });
        list.push(c);
      });
      for (const [status, n] of Object.entries(t.by)) tally[status] = (tally[status] || 0) + n;
    });
    return { flat: list, where: at, counts: tally };
  }, [shown]);

  const cell = cellFor(flat.length);
  const gap = cell < 12 ? 2 : 3;
  const step = cell + gap;

  const probeId = quiet ? null : hoverId ?? focusId;
  const lightId = quiet ? null : hoverId ?? focusId ?? pinnedId;
  const partners = useMemo(() => (model && lightId !== null ? partnersOf(model, lightId) : NONE), [model, lightId]);
  const pinned = model && pinnedId !== null ? model.byId.get(pinnedId) : null;
  const detail = useMemo(() => (pinned ? partnerDetail(model, pinned.id) : null), [model, pinned]);
  const probe = model && probeId !== null && probeId !== pinnedId ? model.byId.get(probeId) : null;
  // Of the pinned control's partners, the ones in a territory that is drawn.
  const litDrawn = useMemo(() => (detail ? detail.list.reduce((n, p) => n + (where.has(p.id) ? 1 : 0), 0) : 0), [detail, where]);
  const tabId = rovingId !== null && where.has(rovingId) ? rovingId : flat[0]?.id;

  function move(next) {
    if (!next) return;
    const el = fieldRef.current?.querySelector(`[data-cid="${next.id}"]`);
    if (el) el.focus();
  }

  function onKeyDown(e) {
    if (e.key === "Escape" && (pinnedId !== null || lightId !== null)) {
      setPinnedId(null);
      setQuiet(true);
      e.stopPropagation();
      return;
    }
    const id = cidOf(e);
    const here = id === null ? null : where.get(id);
    if (!here || e.altKey || e.metaKey) return;
    const terr = shown[here.ti];
    let next;
    switch (e.key) {
      case "ArrowRight": next = flat[here.f + 1]; break;
      case "ArrowLeft": next = flat[here.f - 1]; break;
      case "ArrowDown":
      case "ArrowUp": {
        // As many columns as the territory is drawn with right now, which
        // depends on the width of the page and not on anything stored.
        const columns = getComputedStyle(e.target.parentElement).gridTemplateColumns.split(" ").length || 1;
        next = terr.controls[here.i + (e.key === "ArrowDown" ? columns : -columns)];
        break;
      }
      case "Home": next = e.ctrlKey ? flat[0] : terr.controls[0]; break;
      case "End": next = e.ctrlKey ? flat[flat.length - 1] : terr.controls[terr.controls.length - 1]; break;
      case "PageDown": next = shown[here.ti + 1]?.controls[0]; break;
      case "PageUp": next = shown[here.ti - 1]?.controls[0]; break;
      default: return;
    }
    e.preventDefault();
    move(next);
  }

  function pin(id) {
    setQuiet(false);
    setPinnedId((cur) => (cur === id ? null : id));
  }

  if (loading && !model) {
    return (
      <Panel className="min-w-0">
        <AtlasHeader />
        <Loading>Loading the atlas…</Loading>
      </Panel>
    );
  }
  if (error || !model) {
    return (
      <Panel className="min-w-0">
        <AtlasHeader />
        <LoadError what="The coverage atlas" reason={error} onRetry={onRetry} />
      </Panel>
    );
  }
  if (model.total === 0) {
    return (
      <Panel className="min-w-0">
        <AtlasHeader />
        <Empty title="No controls to draw">Load a control library and every control appears here as one square.</Empty>
      </Panel>
    );
  }

  const announce = pinned
    ? `${pinned.ref} selected. ${detail.list.length === 0 ? "No other control answers the same theme." : `${detail.list.length.toLocaleString()} other ${detail.list.length === 1 ? "control answers" : "controls answer"} the same themes.`}`
    : "";

  return (
    <Panel className="min-w-0">
      <AtlasHeader
        legend={
          <ul aria-label="Legend with counts" className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {LEGEND.map((status) => (
              <li key={status} className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-muted">
                <StatusGlyph status={status} />
                {CONTROL_STATUS[status].label}
                <b className="tabular font-mono text-2xs font-medium text-ink">{(counts[status] || 0).toLocaleString()}</b>
              </li>
            ))}
            <li className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-muted">
              <i
                aria-hidden="true"
                className="inline-block h-[11px] w-[11px] shrink-0 rounded-[3px] border border-line-strong bg-surface-2 shadow-[0_0_0_1.5px_rgb(var(--accent)),0_0_6px_1px_rgb(var(--accent)/0.5)]"
              />
              Answers the same theme
            </li>
          </ul>
        }
      />

      {chips ? (
        <div role="group" aria-label="Frameworks to draw" className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
          <Label className="mr-1">Draw</Label>
          {model.territories.map((t) => {
            const on = drawnIds.has(t.fw.id);
            return (
              <button
                key={t.fw.id}
                type="button"
                aria-pressed={on}
                onClick={() => {
                  const next = new Set(drawnIds);
                  if (on) next.delete(t.fw.id);
                  else next.add(t.fw.id);
                  setChosen(next);
                }}
                className={cn(
                  "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-[background-color,border-color,color] duration-150 ease-out",
                  on ? "border-transparent bg-accent/10 text-accent" : "border-line text-muted hover:border-line-strong hover:text-ink"
                )}
              >
                {t.fw.name}
                <span className="tabular font-mono text-2xs opacity-80">{t.controls.length.toLocaleString()}</span>
              </button>
            );
          })}
          <button type="button" className="link ml-1" onClick={() => setChosen(drawnIds.size === model.territories.length ? defaultDrawn(model) : new Set(model.territories.map((t) => t.fw.id)))}>
            {drawnIds.size === model.territories.length ? `Draw the largest ${DEFAULT_DRAWN}` : "Draw all"}
          </button>
        </div>
      ) : null}

      <div className="dash-atlas p-4 sm:p-5">
        <div className="min-w-0">
          {shown.length === 0 ? (
            <Empty title="Nothing is drawn" className="py-8">Choose a framework above to draw its controls.</Empty>
          ) : (
            <div
              ref={fieldRef}
              role="group"
              aria-label={`${flat.length.toLocaleString()} controls grouped by framework`}
              aria-describedby={`${uid}-help`}
              data-light={partners.size > 0 ? "true" : "false"}
              data-big={flat.length > BIG_FROM ? "true" : "false"}
              data-focus={lightId !== null ? lightId : undefined}
              data-pinned={pinnedId !== null ? pinnedId : undefined}
              className="group/field flex flex-wrap items-start gap-x-6 gap-y-5"
              style={{ "--cell": `${cell}px`, "--gap": `${gap}px` }}
              onPointerOver={(e) => {
                if (e.pointerType === "touch") return;
                const id = cidOf(e);
                if (id !== null && id !== hoverId) {
                  setQuiet(false);
                  setHoverId(id);
                }
              }}
              onPointerLeave={() => setHoverId(null)}
              onFocus={(e) => {
                const id = cidOf(e);
                if (id === null) return;
                setQuiet(false);
                setFocusId(id);
                setRovingId(id);
              }}
              onBlur={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget)) setFocusId(null);
              }}
              onClick={(e) => {
                const id = cidOf(e);
                if (id !== null) pin(id);
              }}
              onKeyDown={onKeyDown}
            >
              <p id={`${uid}-help`} className="sr-only">
                Use the arrow keys to move between controls. Enter selects one and lights the controls that answer the same themes. Escape clears.
              </p>
              {shown.map((t) => {
                const cols = columnsFor(t.controls.length);
                const applicable = t.controls.length - (t.by.not_applicable || 0);
                return (
                  <div key={t.fw.id} className="max-w-full">
                    <div
                      role="group"
                      aria-labelledby={`${uid}-fw-${t.fw.id}`}
                      className="w-fit max-w-full rounded-[10px] border border-dashed border-line-strong bg-grid/55 p-2"
                    >
                      <div
                        className="grid max-w-full"
                        style={{ gridTemplateColumns: "repeat(auto-fill, var(--cell))", gap: "var(--gap)", width: cols * step - gap }}
                      >
                        {t.controls.map((c) => (
                          <Square
                            key={c.id}
                            c={c}
                            tab={c.id === tabId}
                            lit={partners.has(c.id)}
                            hot={c.id === probeId}
                            pinned={c.id === pinnedId}
                          />
                        ))}
                      </div>
                    </div>
                    <p id={`${uid}-fw-${t.fw.id}`} className="mt-2 px-1">
                      <span className="block text-[13px] font-semibold leading-[18px] tracking-[-0.005em] text-ink">
                        {t.fw.name}
                        {t.fw.version ? <span className="ml-1.5 font-mono text-2xs font-normal text-faint">{t.fw.version}</span> : null}
                      </span>
                      <span className="block text-xs leading-4 text-muted">
                        {t.controls.length.toLocaleString()} controls, {(t.by.implemented || 0).toLocaleString()} implemented
                        {applicable !== t.controls.length ? `, ${(t.by.not_applicable || 0).toLocaleString()} not applicable` : ""}
                      </span>
                    </p>
                  </div>
                );
              })}
            </div>
          )}
          <p className="sr-only" role="status" aria-live="polite">{announce}</p>
        </div>

        <div ref={sideRef} role="group" aria-label="Selected control" className="dash-atlas-side flex min-w-0 flex-col gap-3">
          {pinned ? (
            <PlaceCard control={pinned} detail={detail} litDrawn={litDrawn} onPick={pin} onClear={() => { setPinnedId(null); setQuiet(true); }} />
          ) : (
            <div className="rounded-xl border border-line border-t-2 border-t-accent bg-surface-2 p-4">
              <Label>Crosswalk</Label>
              {probe ? (
                <>
                  <p className="mt-2 flex items-baseline gap-2">
                    <span className="font-mono text-[15px] font-medium text-ink">{probe.ref}</span>
                    <span className="min-w-0 truncate text-[13px] font-semibold text-ink">{probe.title}</span>
                  </p>
                  <p className="mt-1 text-xs text-muted">
                    {probe.fw.name}, {CONTROL_STATUS[probe.status]?.label.toLowerCase()}.{" "}
                    {partners.size === 0 ? "No other control answers the same theme." : `${partners.size.toLocaleString()} ${partners.size === 1 ? "control answers" : "controls answer"} the same themes.`}
                  </p>
                  <p className="mt-2 text-xs text-faint">Select it to pin the crosswalk.</p>
                </>
              ) : (
                <p className="mt-2 text-xs leading-snug text-muted">
                  Point at a square, or move to it with the arrow keys, to light every control that answers the same theme in any framework. Select one to pin it and see what it answers.
                </p>
              )}
            </div>
          )}
          <p className="px-0.5 text-xs leading-snug text-muted">
            <b className="font-semibold text-ink">{flat.length.toLocaleString()} controls</b>, one square each, grouped by framework.
            {chips && shown.length < model.territories.length ? ` ${model.total.toLocaleString()} in all.` : ""} Arrow keys move through them.
          </p>
        </div>
      </div>
    </Panel>
  );
}

function AtlasHeader({ legend }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-line px-5 py-3.5">
      <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">Coverage atlas</h2>
      {legend}
    </header>
  );
}

function PlaceCard({ control, detail, litDrawn, onPick, onClear }) {
  const status = CONTROL_STATUS[control.status] || { label: control.status, tone: "muted" };
  const band = READINESS_BAND[control.band] || READINESS_BAND.not_applicable;
  const more = detail.list.length - LISTED;
  return (
    <div className="rounded-xl border border-line border-t-2 border-t-accent bg-surface-2 p-4" data-testid="atlas-place">
      <div className="flex items-center justify-between gap-2">
        <Label className="truncate">{control.fw.name}</Label>
        <Badge tone={status.tone} dot mono className="shrink-0">{status.label}</Badge>
      </div>
      <p className="mt-2.5 flex items-baseline gap-2">
        <span className="shrink-0 font-mono text-base font-medium tracking-[-0.01em] text-ink">{control.ref}</span>
        <span className="min-w-0 text-[15px] font-semibold leading-snug tracking-[-0.01em] text-ink">{control.title}</span>
      </p>
      <p className="mt-1.5 flex items-center gap-2 text-xs text-muted">
        {control.score === null || control.score === undefined ? (
          "Not scored: marked not applicable."
        ) : (
          <>
            <span className={cn("h-2 w-2 rounded-[3px]", TONE_FILL[band.tone])} aria-hidden="true" />
            <span>
              Readiness <b className="tabular font-semibold text-ink">{control.score}</b>
            </span>
            <span className={TONE_TEXT[band.tone]}>{band.label}</span>
          </>
        )}
      </p>

      <div className="mt-3 border-t border-line pt-3">
        <Label>Also answers</Label>
        {detail.list.length === 0 ? (
          <p className="mt-1.5 text-xs text-muted">No other control answers the same theme.</p>
        ) : (
          <>
            <p className="mt-1.5 text-xs text-muted">
              {detail.list.length.toLocaleString()} {detail.list.length === 1 ? "control" : "controls"}
              {litDrawn !== detail.list.length ? `, ${litDrawn.toLocaleString()} in the territories drawn` : ""}. Themes: {joinSome(detail.themes, 2)}.
            </p>
            <ul className="mt-2 flex flex-col gap-0.5">
              {detail.list.slice(0, LISTED).map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => onPick(p.id)}
                    title={`${p.ref}, ${p.title}. Select it.`}
                    className="flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-xs transition-colors duration-150 ease-out hover:bg-ink/[0.05]"
                  >
                    <StatusGlyph status={p.status} />
                    <span className="min-w-0 truncate">
                      <span className="font-medium text-ink">{p.ref}</span>
                      <span className="ml-1.5 text-muted">{p.fw.name}</span>
                    </span>
                    <span className="ml-auto shrink-0 text-muted">{CONTROL_STATUS[p.status]?.label}</span>
                  </button>
                </li>
              ))}
            </ul>
            {more > 0 ? (
              <p className="mt-1.5 px-1 text-xs text-muted">
                and {more.toLocaleString()} more
                {detail.tally.length > 1 ? `, in ${joinSome(detail.tally.map((t) => `${t.fw.name} (${t.n.toLocaleString()})`), 3)}` : ""}.
              </p>
            ) : null}
          </>
        )}
      </div>

      <div className="mt-3 flex items-center justify-between gap-3">
        <Link to={`/controls?framework=${encodeURIComponent(control.fw.key)}&search=${encodeURIComponent(control.ref)}`} className="link">
          Open control
          <ArrowUpRightIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
        </Link>
        <button type="button" onClick={onClear} className="text-xs text-muted transition-colors duration-150 ease-out hover:text-ink">
          Clear <span className="font-mono text-2xs text-faint">Esc</span>
        </button>
      </div>
    </div>
  );
}
