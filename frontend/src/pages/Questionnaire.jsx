/**
 * The vendor's side of the security questionnaire: a public page reached from
 * the emailed link, outside the signed-in shell. It shows the questions, keeps
 * a draft, and submits once. Nothing else of the product is reachable from
 * here -- the token is the only credential and it opens exactly this.
 */
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { ConformitiMark } from "../components/brand/ConformitiMark.jsx";
import { PanelTransition } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Meter } from "../components/ui/Meter.jsx";
import { Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { Chip } from "../components/ui/SegmentedControl.jsx";

const ANSWERS = [["yes", "Yes"], ["partial", "Partial"], ["no", "No"], ["n/a", "N/A"]];
const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "long", year: "numeric" });
const fmt = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso).slice(0, 10) : DATE_FMT.format(d);
};

function Header({ vendor, organisation }) {
  return (
    <div className="flex items-center gap-3">
      <ConformitiMark size={36} title="Conformiti" />
      <div className="min-w-0">
        <p className="text-[15px] font-semibold tracking-[-0.01em] text-ink">{organisation || "Conformiti"}</p>
        <Label>Security questionnaire{vendor ? ` · ${vendor}` : ""}</Label>
      </div>
    </div>
  );
}

const CLOSED = {
  unknown: ["This link is not valid", "Check the address from the email, or ask your contact to send it again."],
  expired: ["This link has expired", "Ask your contact to send a new one."],
  revoked: ["This link was withdrawn", "Your contact has sent a newer link, or no longer needs the questionnaire."],
  submitted: ["Already submitted — thank you", "Your answers were received and are being reviewed."],
  error: ["Something went wrong", "Try again in a moment."],
};

export default function Questionnaire() {
  const { token } = useParams();
  const [state, setState] = useState({ status: "loading" });
  const [answers, setAnswers] = useState({});
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const url = `/api/questionnaire/${encodeURIComponent(token || "")}/`;

  useEffect(() => {
    let live = true;
    axios.get(url)
      .then((r) => {
        if (!live) return;
        setState({ status: r.data.status === "open" ? "ready" : r.data.status, data: r.data });
        setAnswers(r.data.answers || {});
      })
      .catch((e) => live && setState({ status: e?.response?.status === 404 ? "unknown" : "error" }));
    return () => { live = false; };
  }, [url]);

  const data = state.data;
  const questions = data?.questions || [];
  const areas = useMemo(() => {
    const out = [];
    for (const q of questions) {
      let a = out.find((x) => x.area === q.area);
      if (!a) { a = { area: q.area, items: [] }; out.push(a); }
      a.items.push(q);
    }
    return out;
  }, [questions]);
  const answered = questions.filter((q) => answers[q.id]?.answer).length;
  const setAnswer = (id, patch) => setAnswers((cur) => ({ ...cur, [id]: { ...(cur[id] || {}), ...patch } }));

  async function saveDraft() {
    setMsg(null);
    setBusy(true);
    try {
      await axios.put(url, { answers });
      setMsg({ ok: true, text: "Draft saved. You can come back to this link until it expires." });
    } catch (e) {
      setMsg({ ok: false, text: e?.response?.data?.detail || "The draft could not be saved." });
    } finally {
      setBusy(false);
    }
  }

  async function submit(e) {
    e.preventDefault();
    setMsg(null);
    setBusy(true);
    try {
      await axios.post(`${url}submit/`, { answers, respondent_name: name.trim(), respondent_title: title.trim() });
      setState({ status: "done", data });
    } catch (err) {
      setMsg({ ok: false, text: err?.response?.data?.detail || "The questionnaire could not be submitted." });
    } finally {
      setBusy(false);
    }
  }

  let body;
  if (state.status === "loading") {
    body = <Panel><Loading /></Panel>;
  } else if (state.status === "done") {
    body = (
      <Panel className="p-6">
        <Header vendor={data?.vendor} organisation={data?.organisation} />
        <h1 className="mt-6 text-[20px] font-semibold tracking-[-0.02em] text-ink">Thank you</h1>
        <p className="mt-2 text-[13px] leading-snug text-muted">
          Your answers for {data?.vendor} were received{answered ? ` (${answered} of ${questions.length} questions)` : ""} and will be reviewed by {data?.sender || "your contact"}. This link is now closed.
        </p>
      </Panel>
    );
  } else if (state.status !== "ready") {
    const [heading, detail] = CLOSED[state.status] || CLOSED.error;
    body = (
      <Panel className="p-6">
        <Header vendor={data?.vendor} organisation={data?.organisation} />
        <h1 className="mt-6 text-[20px] font-semibold tracking-[-0.02em] text-ink">{heading}</h1>
        <p className="mt-2 text-[13px] leading-snug text-muted">{detail}</p>
      </Panel>
    );
  } else {
    body = (
      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Panel className="p-6">
          <Header vendor={data.vendor} organisation={data.organisation} />
          <h1 className="mt-6 text-[20px] font-semibold tracking-[-0.02em] text-ink">Security questionnaire for {data.vendor}</h1>
          <p className="mt-2 text-[13px] leading-snug text-muted">
            {data.sender}{data.organisation ? ` at ${data.organisation}` : ""} has asked you to answer {questions.length} questions about {data.vendor}'s security practices.
            Save a draft as often as you like; submit once when you are done. This link works until <span className="text-ink">{fmt(data.expires_at)}</span>.
          </p>
          {data.message ? (
            <blockquote className="mt-3 border-l-2 border-line pl-3 text-[13px] leading-snug text-muted">{data.message}</blockquote>
          ) : null}
          <div className="mt-4 flex items-center gap-3">
            <Meter value={answered} total={questions.length || 1} className="w-40" ariaLabel="Questions answered" />
            <Label>{answered}/{questions.length} answered</Label>
            {data.saved_at ? <Label>· draft saved {fmt(data.saved_at)}</Label> : null}
          </div>
        </Panel>

        <Panel className="overflow-hidden">
          <PanelHeader title="Questions" meta="Yes · Partial · No · N/A, with a note where it helps" />
          <div className="divide-y divide-line">
            {areas.map((a) => (
              <fieldset key={a.area} className="px-5 py-4">
                <legend className="mb-2 font-mono text-2xs uppercase tracking-label text-faint">{a.area}</legend>
                <ul className="space-y-3">
                  {a.items.map((q) => (
                    <li key={q.id} className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_auto]">
                      <p className="text-[13px] text-ink">{q.text}</p>
                      <div className="flex flex-wrap items-center gap-1.5">
                        {ANSWERS.map(([k, l]) => (
                          <Chip key={k} active={answers[q.id]?.answer === k} onClick={() => setAnswer(q.id, { answer: k })}>{l}</Chip>
                        ))}
                        <input className="input input-sm w-48" placeholder="Note" aria-label={`Note for: ${q.text}`} maxLength={1000}
                               value={answers[q.id]?.note || ""} onChange={(e) => setAnswer(q.id, { note: e.target.value })} />
                      </div>
                    </li>
                  ))}
                </ul>
              </fieldset>
            ))}
          </div>
        </Panel>

        <Panel className="p-5">
          {msg ? <div className={msg.ok ? "notice notice-ok mb-4" : "notice notice-err mb-4"} role={msg.ok ? "status" : "alert"}>{msg.text}</div> : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="q-name" className="field-label">Your name</label>
              <input id="q-name" className="input" required maxLength={160} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </div>
            <div>
              <label htmlFor="q-title" className="field-label">Your role (optional)</label>
              <input id="q-title" className="input" maxLength={160} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="CISO" autoComplete="organization-title" />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" disabled={busy || !name.trim() || answered === 0}>
              {busy ? "Sending…" : "Submit questionnaire"}
            </Button>
            <Button type="button" onClick={saveDraft} disabled={busy}>Save draft</Button>
            <Badge tone="muted">Submits once; the link closes afterwards</Badge>
          </div>
        </Panel>
      </form>
    );
  }

  return (
    <PanelTransition>
      <div className="min-h-screen bg-bg px-4 py-10">
        <div className="mx-auto w-full max-w-[760px]">
          {body}
          <p className="mt-4 text-center font-mono text-2xs uppercase tracking-label text-faint">Powered by Conformiti</p>
        </div>
      </div>
    </PanelTransition>
  );
}
