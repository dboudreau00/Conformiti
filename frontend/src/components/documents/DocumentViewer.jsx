/**
 * Open a stored document in the browser without leaving the app.
 *
 * Nothing here is rendered as HTML from the file. PDFs and images are fetched
 * through the API client (so the credential travels the same way as every
 * other request, in header or cookie mode). Images are shown from a blob URL
 * in an <img>; PDFs are drawn onto canvases by pdf.js, in a worker that is
 * part of this bundle, with scripting off — no frame, no plugin, and no PDF
 * JavaScript ever runs. Word and Excel
 * files arrive from the server already parsed into a small structured
 * vocabulary (headings, runs, list items, tables, sheets) and are rendered
 * from that. A file whose bytes do not match its extension is refused by the
 * server and shown here as "download instead".
 *
 * The frame around the file is the point of the component: version, status,
 * folder, the controls it satisfies, and a SHA-256 computed in the browser
 * from the bytes on screen — the same digest a sealed package manifest
 * records, so a reviewer can compare the two without downloading anything.
 */
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { DownloadIcon, FingerprintIcon, PanelRightIcon, XIcon, ZoomInIcon, ZoomOutIcon } from "lucide-react";
import * as pdfjs from "pdfjs-dist";
import api, { downloadFile } from "../../api/client.js";

// pdf.js renders the pages onto canvases in our own page. No frame, no
// plugin, and nothing in the PDF ever executes: the library's scripting
// support is off, the worker is a same-origin asset of this bundle, and the
// bytes never leave the browser. (Chromium's built-in viewer was the
// alternative; it is a plugin that cannot be sandboxed and runs PDF
// JavaScript, and the headless browser the test suite drives has no viewer at
// all.)
pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
const PDF_PAGE_BATCH = 20;
import { EASE } from "../layout/PanelTransition.jsx";
import { Badge } from "../ui/Badge.jsx";
import { Button } from "../ui/Button.jsx";
import { Label, Loading } from "../ui/Panel.jsx";
import { errorText } from "../../utils/a11y.js";
import { cn } from "../../utils/cn.js";
import { DOC_STATUS } from "../../utils/tone.js";

const KIND_LABEL = { pdf: "PDF", image: "Image", docx: "Word document", xlsx: "Spreadsheet", text: "Text" };

/** Viewer props for a row from /documents/. Shared by every page that lists them. */
export function documentViewerProps(doc) {
  const status = DOC_STATUS[doc.status] || { label: doc.status, tone: "muted" };
  return {
    title: doc.name,
    subtitle: [doc.folder_path, doc.control_id].filter(Boolean).join(" · "),
    previewUrl: `/documents/${doc.id}/preview/`,
    downloadUrl: doc.download_url || `/documents/${doc.id}/download/`,
    filename: doc.name,
    badge: status,
    facts: [
      { label: "Version", value: `v${doc.version ?? 1}` },
      { label: "Owner", value: doc.owner_name || "—" },
      { label: "Folder", value: doc.folder_path || "—" },
      { label: "Next review", value: doc.next_review_date || "—" },
      { label: "Updated", value: (doc.updated_at || "").slice(0, 10) || "—" },
    ],
    chips: (doc.satisfies || []).map((s) => ({ label: s.label, title: s.title })),
  };
}

async function sha256Hex(blob) {
  if (!window.crypto?.subtle) return null;
  const digest = await window.crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function detailFromError(e, fallback) {
  const data = e?.response?.data;
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text());
      if (parsed?.detail) return String(parsed.detail);
    } catch { /* not JSON */ }
  }
  return errorText(e, fallback);
}

// --- Structured renderers ---------------------------------------------------------

function Runs({ runs }) {
  return runs.map((r, i) => {
    let node = r.t;
    if (r.b) node = <strong key={`b${i}`}>{node}</strong>;
    if (r.i) node = <em key={`i${i}`}>{node}</em>;
    return <span key={i}>{node}</span>;
  });
}

function DocxBody({ blocks }) {
  const H = ["h2", "h3", "h4", "h5"];
  return (
    <article className="mx-auto my-6 max-w-3xl rounded-xl border border-line bg-surface px-8 py-10 shadow-sm sm:px-12">
      {blocks.map((b, i) => {
        if (b.type === "heading") {
          const Tag = H[Math.min(b.level, 4) - 1] || "h4";
          return <Tag key={i} className={cn("font-semibold text-ink", b.level === 1 ? "mt-6 text-xl" : b.level === 2 ? "mt-5 text-lg" : "mt-4 text-base")}>{b.text}</Tag>;
        }
        if (b.type === "list_item") {
          return (
            <p key={i} className="my-1 flex gap-2 text-[13.5px] leading-relaxed text-ink" style={{ paddingLeft: `${b.level * 1.25}rem` }}>
              <span className="text-faint" aria-hidden="true">•</span>
              <span><Runs runs={b.runs} /></span>
            </p>
          );
        }
        if (b.type === "table") {
          return (
            <div key={i} className="my-4 overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <tbody>
                  {b.rows.map((row, r) => (
                    <tr key={r} className={r === 0 ? "bg-surface-2" : undefined}>
                      {row.map((cell, c) => (
                        <td key={c} className="whitespace-pre-line border border-line px-2.5 py-1.5 align-top text-ink">{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {b.truncated ? <Label className="mt-1 block">Table truncated in preview.</Label> : null}
            </div>
          );
        }
        if (b.type === "notice") return <p key={i} className="notice notice-warn my-4">{b.text}</p>;
        return <p key={i} className="my-2.5 whitespace-pre-line text-[13.5px] leading-relaxed text-ink"><Runs runs={b.runs} /></p>;
      })}
      {blocks.length === 0 ? <p className="text-sm text-muted">This document has no readable text.</p> : null}
    </article>
  );
}

function colName(i) {
  let s = "";
  for (let n = i; n >= 0; n = Math.floor(n / 26) - 1) s = String.fromCharCode(65 + (n % 26)) + s;
  return s;
}

function SheetBody({ sheets }) {
  const [active, setActive] = useState(0);
  const sheet = sheets[active] || sheets[0];
  if (!sheet) return <p className="p-8 text-sm text-muted">This workbook has no sheets.</p>;
  const width = sheet.rows.reduce((m, r) => Math.max(m, r.length), 0);
  return (
    <div className="flex h-full min-h-0 flex-col">
      {sheets.length > 1 ? (
        <div className="flex flex-wrap gap-1 border-b border-line bg-surface px-3 py-2" role="tablist" aria-label="Sheets">
          {sheets.map((s, i) => (
            <button key={s.name + i} type="button" role="tab" aria-selected={i === active} onClick={() => setActive(i)}
                    className={cn("rounded-md px-2.5 py-1 text-xs font-medium transition-colors duration-150",
                      i === active ? "bg-accent/10 text-accent" : "text-muted hover:bg-surface-2 hover:text-ink")}>
              {s.name}
            </button>
          ))}
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="min-w-full border-collapse font-mono text-xs">
          <thead className="sticky top-0 z-10 bg-surface-2">
            <tr>
              <th className="w-10 border border-line px-2 py-1 text-right font-normal text-faint" scope="col">#</th>
              {Array.from({ length: width }, (_, i) => (
                <th key={i} className="border border-line px-2 py-1 text-left font-normal text-faint" scope="col">{colName(i)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sheet.rows.map((row, r) => (
              <tr key={r} className={r === 0 ? "bg-accent/[0.04] font-medium" : undefined}>
                <td className="border border-line px-2 py-1 text-right text-faint">{r + 1}</td>
                {Array.from({ length: width }, (_, c) => (
                  <td key={c} className="max-w-[360px] truncate border border-line px-2 py-1 text-ink" title={row[c]}>{row[c] ?? ""}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {sheet.truncated ? <p className="notice notice-warn m-3">Only the first rows are shown. Download for the whole sheet.</p> : null}
      </div>
    </div>
  );
}

/** Tear a pdf.js document down without letting anything it throws reach
 *  React: cancel the render tasks first, and destroy on the next tick, so an
 *  effect cleanup never raises mid-commit (an error there takes the whole
 *  page to the error boundary). */
function disposePdf(doc, tasks) {
  for (const task of tasks.values()) {
    try { task.cancel(); } catch { /* already finished */ }
  }
  tasks.clear();
  if (!doc) return;
  setTimeout(() => {
    try {
      const done = doc.destroy();
      if (done && typeof done.catch === "function") done.catch(() => {});
    } catch { /* the worker is gone; nothing to release */ }
  }, 0);
}

function PdfBody({ bytes, title }) {
  const [state, setState] = useState({ status: "loading", pages: 0, shown: 0, error: "" });
  const [zoom, setZoom] = useState(1);
  const docRef = useRef(null);
  const hostRef = useRef(null);
  const tasksRef = useRef(new Map());   // page number -> in-flight RenderTask

  useEffect(() => {
    let live = true;
    let loading = null;
    setState({ status: "loading", pages: 0, shown: 0, error: "" });
    (async () => {
      try {
        const data = new Uint8Array(await bytes.arrayBuffer());
        loading = pdfjs.getDocument({ data, isEvalSupported: false, disableAutoFetch: true, enableXfa: false });
        const doc = await loading.promise;
        if (!live) { disposePdf(doc, new Map()); return; }
        docRef.current = doc;
        setState({ status: "ready", pages: doc.numPages, shown: Math.min(doc.numPages, PDF_PAGE_BATCH), error: "" });
      } catch (e) {
        if (live) setState({ status: "error", pages: 0, shown: 0, error: e?.message || "This PDF could not be rendered." });
      }
    })();
    return () => {
      live = false;
      const doc = docRef.current;
      docRef.current = null;
      if (doc) disposePdf(doc, tasksRef.current);
      else if (loading) setTimeout(() => { try { loading.destroy(); } catch { /* not started */ } }, 0);
    };
  }, [bytes]);

  // Draw every visible page whenever the count or the zoom changes. A newer
  // pass cancels the tasks of the one before it.
  useEffect(() => {
    const doc = docRef.current;
    const host = hostRef.current;
    if (state.status !== "ready" || !doc || !host) return undefined;
    let cancelled = false;
    const tasks = tasksRef.current;
    (async () => {
      const width = Math.max(320, host.clientWidth - 48);
      for (let n = 1; n <= state.shown && !cancelled; n++) {
        const canvas = host.querySelector(`canvas[data-page="${n}"]`);
        if (!canvas || canvas.dataset.zoom === String(zoom)) continue;
        const page = await doc.getPage(n);
        if (cancelled) return;
        const base = page.getViewport({ scale: 1 });
        const scale = (width / base.width) * zoom;
        const dpr = window.devicePixelRatio || 1;
        const viewport = page.getViewport({ scale: scale * dpr });
        canvas.width = Math.floor(viewport.width);
        canvas.height = Math.floor(viewport.height);
        canvas.style.width = `${Math.floor(viewport.width / dpr)}px`;
        canvas.style.height = `${Math.floor(viewport.height / dpr)}px`;
        const task = page.render({ canvasContext: canvas.getContext("2d"), viewport });
        tasks.set(n, task);
        try {
          await task.promise;
          if (!cancelled) canvas.dataset.zoom = String(zoom);
        } finally {
          if (tasks.get(n) === task) tasks.delete(n);
        }
      }
    })().catch(() => { /* cancelled, or the document was torn down */ });
    return () => {
      cancelled = true;
      for (const task of tasks.values()) {
        try { task.cancel(); } catch { /* finished */ }
      }
      tasks.clear();
    };
  }, [state, zoom]);

  if (state.status === "loading") return <Loading className="py-24">Rendering…</Loading>;
  if (state.status === "error") {
    return <p className="p-8 text-center text-sm text-danger" role="alert">{state.error}</p>;
  }
  return (
    <div ref={hostRef} className="min-h-full px-6 py-4" data-pdf-pages={state.pages}>
      <div className="mb-3 flex items-center justify-center gap-2">
        <Button size="sm" variant="ghost" aria-label="Zoom out" disabled={zoom <= 0.5} onClick={() => setZoom((z) => Math.max(0.5, +(z - 0.25).toFixed(2)))}>
          <ZoomOutIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        </Button>
        <Label>{state.pages} page{state.pages === 1 ? "" : "s"} · {Math.round(zoom * 100)}%</Label>
        <Button size="sm" variant="ghost" aria-label="Zoom in" disabled={zoom >= 3} onClick={() => setZoom((z) => Math.min(3, +(z + 0.25).toFixed(2)))}>
          <ZoomInIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        </Button>
      </div>
      <div className="flex flex-col items-center gap-4">
        {Array.from({ length: state.shown }, (_, i) => (
          <canvas key={i + 1} data-page={i + 1} className="max-w-full rounded-sm bg-white shadow-md" aria-label={`${title}, page ${i + 1}`} role="img" />
        ))}
      </div>
      {state.shown < state.pages ? (
        <div className="mt-4 flex justify-center">
          <Button size="sm" onClick={() => setState((s) => ({ ...s, shown: Math.min(s.pages, s.shown + PDF_PAGE_BATCH) }))}>
            Show {Math.min(PDF_PAGE_BATCH, state.pages - state.shown)} more page(s)
          </Button>
        </div>
      ) : null}
    </div>
  );
}

// --- The wrapper ------------------------------------------------------------------

export default function DocumentViewer({
  open, title, subtitle, previewUrl, downloadUrl, filename, badge, facts = [], chips = [], onClose,
}) {
  const [state, setState] = useState({ status: "loading" });
  const [digest, setDigest] = useState(null);
  const [zoom, setZoom] = useState("fit");
  const [aside, setAside] = useState(true);
  const closeRef = useRef(null);

  // Fetch through the API client, never by pointing a frame at the URL: the
  // media location behind nginx forces download and denies framing on
  // purpose, and a bare <iframe src> would carry no credential in header mode.
  useEffect(() => {
    if (!open || !previewUrl) return undefined;
    let live = true;
    let url = null;
    setState({ status: "loading" });
    setDigest(null);
    setZoom("fit");
    (async () => {
      try {
        const r = await api.get(previewUrl, { responseType: "blob" });
        const type = String(r.headers?.["content-type"] || "");
        if (type.includes("application/json")) {
          const data = JSON.parse(await r.data.text());
          if (live) setState({ status: "ready", kind: data.kind, data });
          return;
        }
        url = URL.createObjectURL(r.data);
        if (live) setState({ status: "ready", kind: type === "application/pdf" ? "pdf" : "image", blobUrl: url, bytes: r.data });
      } catch (e) {
        const detail = await detailFromError(e, "Couldn't open this file.");
        if (live) setState({ status: e?.response?.status === 415 ? "unavailable" : "error", detail });
      }
    })();
    return () => {
      live = false;
      // The PDF viewer inside the frame may still be reading the blob as the
      // dialog unmounts; revoking a moment later avoids an aborted fetch.
      if (url) {
        const stale = url;
        setTimeout(() => URL.revokeObjectURL(stale), 1500);
      }
    };
  }, [open, previewUrl]);

  // The digest is free when the bytes are already here (PDF, image).
  useEffect(() => {
    if (state.status !== "ready" || !state.bytes) return undefined;
    let live = true;
    sha256Hex(state.bytes).then((hex) => { if (live) setDigest(hex || "unavailable"); }).catch(() => { if (live) setDigest("unavailable"); });
    return () => { live = false; };
  }, [state]);

  useEffect(() => {
    if (!open) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    document.addEventListener("keydown", onKey);
    const t = setTimeout(() => closeRef.current?.focus(), 30);
    return () => {
      document.body.style.overflow = prev;
      document.removeEventListener("keydown", onKey);
      clearTimeout(t);
    };
  }, [open, onClose]);

  async function computeDigest() {
    setDigest("computing");
    try {
      const r = await api.get(downloadUrl, { responseType: "blob" });
      setDigest((await sha256Hex(r.data)) || "unavailable");
    } catch {
      setDigest("unavailable");
    }
  }

  const kindLabel = state.kind ? KIND_LABEL[state.kind] || state.kind : null;

  let body;
  if (state.status === "loading") {
    body = <Loading className="py-24">Opening…</Loading>;
  } else if (state.status === "unavailable" || state.status === "error") {
    body = (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
        <p className={cn("max-w-md text-sm", state.status === "error" ? "text-danger" : "text-muted")} role={state.status === "error" ? "alert" : "status"}>
          {state.detail}
        </p>
        {downloadUrl ? (
          <Button size="sm" variant="primary" icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                  onClick={() => downloadFile(downloadUrl, filename || title)}>
            Download
          </Button>
        ) : null}
      </div>
    );
  } else if (state.kind === "pdf") {
    body = <PdfBody bytes={state.bytes} title={title} />;
  } else if (state.kind === "image") {
    body = (
      <div className={cn("min-h-full p-6", zoom === "fit" && "flex items-center justify-center")}>
        <img src={state.blobUrl} alt={title}
             className={cn("rounded-md shadow-md", zoom === "fit" ? "max-h-[calc(100vh-200px)] max-w-full object-contain" : "max-w-none")} />
      </div>
    );
  } else if (state.kind === "docx") {
    body = <DocxBody blocks={state.data.blocks || []} />;
  } else if (state.kind === "xlsx") {
    body = <SheetBody sheets={state.data.sheets || []} />;
  } else if (state.kind === "text") {
    body = (
      <pre className="whitespace-pre-wrap break-words p-6 font-mono text-xs leading-relaxed text-ink">
        {state.data.text}{state.data.truncated ? "\n\n[Preview truncated. Download for the whole file.]" : ""}
      </pre>
    );
  }

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          key="viewer"
          role="dialog"
          aria-modal="true"
          aria-label={`Viewing ${title}`}
          className="fixed inset-0 z-50 flex flex-col bg-black/70 p-2 backdrop-blur-sm sm:p-5"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18, ease: EASE }}
          onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
        >
          <motion.div
            className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-pop"
            initial={{ y: 14, scale: 0.985 }}
            animate={{ y: 0, scale: 1 }}
            exit={{ y: 8, scale: 0.985 }}
            transition={{ duration: 0.22, ease: EASE }}
          >
            <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <h2 className="truncate text-[15px] font-semibold text-ink">{title}</h2>
                  {badge ? <Badge tone={badge.tone} dot>{badge.label}</Badge> : null}
                  {kindLabel ? <Badge tone="faint" mono>{kindLabel}</Badge> : null}
                </div>
                {subtitle ? <Label className="mt-0.5 block truncate">{subtitle}</Label> : null}
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                {state.kind === "image" ? (
                  <Button size="sm" variant="ghost" aria-pressed={zoom === "actual"} onClick={() => setZoom((z) => (z === "fit" ? "actual" : "fit"))}
                          icon={zoom === "fit" ? <ZoomInIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" /> : <ZoomOutIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                    {zoom === "fit" ? "Actual size" : "Fit"}
                  </Button>
                ) : null}
                {downloadUrl ? (
                  <Button size="sm" onClick={() => downloadFile(downloadUrl, filename || title)}
                          icon={<DownloadIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                    Download
                  </Button>
                ) : null}
                <Button size="sm" variant="ghost" aria-pressed={aside} onClick={() => setAside((a) => !a)}
                        icon={<PanelRightIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                  Details
                </Button>
                <Button ref={closeRef} size="sm" variant="ghost" aria-label="Close viewer" onClick={onClose}>
                  <XIcon className="h-4 w-4" strokeWidth={2} aria-hidden="true" />
                </Button>
              </div>
            </header>

            <div className="flex min-h-0 flex-1">
              <div className="relative min-h-0 min-w-0 flex-1 overflow-auto bg-surface-2">{body}</div>
              {aside ? (
                <aside className="hidden w-72 shrink-0 overflow-y-auto border-l border-line bg-surface px-4 py-4 md:block" aria-label="Document details">
                  <dl className="space-y-3">
                    {facts.map((f) => (
                      <div key={f.label}>
                        <Label as="dt">{f.label}</Label>
                        <dd className={cn("mt-0.5 break-words text-[13px] text-ink", f.mono && "break-all font-mono text-2xs")}>{f.value || "—"}</dd>
                      </div>
                    ))}
                    {chips.length ? (
                      <div>
                        <Label as="dt">Satisfies controls</Label>
                        <dd className="mt-1 flex flex-wrap gap-1">
                          {chips.map((c) => <Badge key={c.label} tone="accent" mono title={c.title}>{c.label}</Badge>)}
                        </dd>
                      </div>
                    ) : null}
                    <div>
                      <Label as="dt">SHA-256 of the bytes shown</Label>
                      <dd className="mt-1">
                        {digest && digest !== "computing" && digest !== "unavailable" ? (
                          <p className="break-all font-mono text-2xs text-ink">{digest}</p>
                        ) : digest === "computing" ? (
                          <Label>Computing…</Label>
                        ) : digest === "unavailable" ? (
                          <Label>Not available in this browser context.</Label>
                        ) : (
                          <Button size="sm" variant="ghost" onClick={computeDigest}
                                  icon={<FingerprintIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}>
                            Compute digest
                          </Button>
                        )}
                        <p className="mt-1.5 text-2xs leading-snug text-faint">
                          Computed in your browser. Compare it with the digest recorded in a sealed audit package to prove this is the same file.
                        </p>
                      </dd>
                    </div>
                  </dl>
                </aside>
              ) : null}
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
