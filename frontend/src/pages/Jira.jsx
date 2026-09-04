import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { DiamondIcon, Loader2Icon, PlusIcon, RefreshCwIcon, XIcon } from "lucide-react";
import api, { fetchAll } from "../api/client.js";
import { EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { errorText } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";

const EMPTY_FORM = { base_url: "", email: "", api_token: "", enabled: false };
const CELL = "px-2.5 py-3 align-middle first:pl-5 last:pr-5";
const HEAD = "table-head px-2.5 py-2 text-left font-normal first:pl-5 last:pr-5";

/** Jira statuses are workspace-defined, so the tone is inferred from the name. */
function statusTone(status) {
  const s = (status || "").toLowerCase();
  if (/(done|closed|resolved|complete|released)/.test(s)) return "success";
  if (/(block|reject|cancel)/.test(s)) return "danger";
  if (/(progress|review|testing|doing|qa|develop)/.test(s)) return "info";
  if (/(to do|todo|backlog|open|new|selected)/.test(s)) return "faint";
  return "muted";
}

function Notice({ msg }) {
  if (!msg) return null;
  return (
    <div className={cn("notice", msg.ok ? "notice-ok" : "notice-err")} role={msg.ok ? "status" : "alert"}>
      {msg.text}
    </div>
  );
}

export default function Jira({ me }) {
  const isManager = !!me?.capabilities?.manage_users;
  const [config, setConfig] = useState(null);
  const [configErr, setConfigErr] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [boards, setBoards] = useState(null); // null = loading
  const [boardsErr, setBoardsErr] = useState(null);
  const [active, setActive] = useState(null);
  const [issues, setIssues] = useState(null);
  const [issueErr, setIssueErr] = useState(null);
  const [msg, setMsg] = useState(null); // connection panel feedback
  const [boardMsg, setBoardMsg] = useState(null); // tracked boards feedback
  const [busy, setBusy] = useState(null); // "save" | "test" | "add" | "remove"
  const [newBoard, setNewBoard] = useState({ board_id: "", name: "" });
  const issueReq = useRef(0);

  useEffect(() => {
    loadBoards();
  }, []);

  useEffect(() => {
    if (!isManager) return undefined;
    let cancelled = false;
    setConfigErr(null);
    api
      .get("/integrations/jira/config/")
      .then((r) => {
        if (cancelled) return;
        setConfig(r.data);
        setForm({ base_url: r.data.base_url || "", email: r.data.email || "", api_token: "", enabled: !!r.data.enabled });
      })
      .catch((e) => {
        if (!cancelled) setConfigErr(errorText(e, "Couldn't load the Jira configuration."));
      });
    return () => {
      cancelled = true;
    };
  }, [isManager]);

  function loadBoards(selectId) {
    setBoardsErr(null);
    // Paginated at 50 — follow `next` so every tracked board is listed.
    return fetchAll("/integrations/jira/boards/")
      .then((list) => {
        setBoards(list);
        const pick = selectId ? list.find((b) => b.id === selectId) : list[0];
        if (pick) openBoard(pick);
        else {
          setActive(null);
          setIssues(null);
          setIssueErr(null);
        }
      })
      .catch((e) => {
        setBoards([]);
        setBoardsErr(errorText(e, "Couldn't load the tracked boards."));
      });
  }

  function openBoard(b) {
    const seq = ++issueReq.current;
    setActive(b);
    setIssues(null);
    setIssueErr(null);
    api
      .get(`/integrations/jira/boards/${b.id}/issues/`)
      .then((r) => {
        if (issueReq.current === seq) setIssues(r.data);
      })
      .catch((e) => {
        if (issueReq.current === seq) setIssueErr(errorText(e, "Couldn't load issues from Jira."));
      });
  }

  async function saveConfig(e) {
    e.preventDefault();
    setBusy("save");
    setMsg(null);
    try {
      const payload = { base_url: form.base_url, email: form.email, enabled: form.enabled };
      if (form.api_token) payload.api_token = form.api_token;
      const { data } = await api.patch("/integrations/jira/config/", payload);
      setConfig(data);
      setForm((f) => ({ ...f, api_token: "" }));
      setMsg({ ok: true, text: "Configuration saved." });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "Couldn't save — check the base URL format.") });
    } finally {
      setBusy(null);
    }
  }

  async function testConnection() {
    setBusy("test");
    setMsg(null);
    try {
      const { data } = await api.post("/integrations/jira/test/");
      setMsg({ ok: true, text: data.detail });
    } catch (err) {
      setMsg({ ok: false, text: errorText(err, "Connection test failed.") });
    } finally {
      setBusy(null);
    }
  }

  async function addBoard(e) {
    e.preventDefault();
    setBusy("add");
    setBoardMsg(null);
    try {
      const { data } = await api.post("/integrations/jira/boards/", {
        board_id: Number(newBoard.board_id),
        name: newBoard.name.trim(),
      });
      setNewBoard({ board_id: "", name: "" });
      setBoardMsg({ ok: true, text: `Now tracking ${data.name}.` });
      await loadBoards(data.id);
    } catch (err) {
      setBoardMsg({ ok: false, text: errorText(err, "Couldn't track that board.") });
    } finally {
      setBusy(null);
    }
  }

  async function removeBoard(b) {
    setBusy("remove");
    setBoardMsg(null);
    try {
      await api.delete(`/integrations/jira/boards/${b.id}/`);
      setActive(null);
      setIssues(null);
      setIssueErr(null);
      await loadBoards();
    } catch (err) {
      setBoardMsg({ ok: false, text: errorText(err, "Couldn't remove that board.") });
    } finally {
      setBusy(null);
    }
  }

  const configured = config ? !!(config.enabled && config.base_url && config.has_token) : (boards?.length || 0) > 0;
  const dirty =
    !!config &&
    (form.base_url !== (config.base_url || "") ||
      form.email !== (config.email || "") ||
      !!form.api_token ||
      form.enabled !== !!config.enabled);
  const issuesLoading = !!active && !issues && !issueErr;
  const canAdd = !busy && Number(newBoard.board_id) > 0 && !!newBoard.name.trim();

  return (
    <PanelTransition>
      <Stack className="grid grid-cols-12 gap-4">
        <StackItem className="col-span-12 space-y-4 lg:col-span-4">
          {isManager ? (
            <Panel className="overflow-hidden">
              <PanelHeader title="Connection">
                <Badge tone={config?.enabled ? "success" : "muted"} dot>
                  {config?.enabled ? "enabled" : "disabled"}
                </Badge>
              </PanelHeader>
              {configErr ? (
                <div className="p-5">
                  <div className="notice notice-err" role="alert">
                    {configErr}
                  </div>
                </div>
              ) : !config ? (
                <Loading>Loading configuration…</Loading>
              ) : (
                <form onSubmit={saveConfig} noValidate className="space-y-3 p-5">
                  <div>
                    <label htmlFor="jira-base-url" className="field-label">
                      Base URL
                    </label>
                    <input
                      id="jira-base-url"
                      className="input"
                      inputMode="url"
                      autoComplete="off"
                      placeholder="https://your-team.atlassian.net"
                      value={form.base_url}
                      onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                    />
                  </div>
                  <div>
                    <label htmlFor="jira-email" className="field-label">
                      Account email
                    </label>
                    <input
                      id="jira-email"
                      type="email"
                      className="input"
                      autoComplete="off"
                      placeholder="you@company.com"
                      value={form.email}
                      onChange={(e) => setForm({ ...form, email: e.target.value })}
                    />
                  </div>
                  <div>
                    <label htmlFor="jira-token" className="field-label">
                      API token
                    </label>
                    <input
                      id="jira-token"
                      type="password"
                      className="input font-mono"
                      autoComplete="new-password"
                      placeholder={config.has_token ? "•••••• (saved — leave blank to keep)" : "Paste an Atlassian API token"}
                      value={form.api_token}
                      onChange={(e) => setForm({ ...form, api_token: e.target.value })}
                    />
                    <p className="mt-1.5 text-2xs leading-snug text-faint">
                      Create a scoped token at id.atlassian.com → Security → API tokens. It is stored server-side and never sent to the
                      browser.
                    </p>
                  </div>
                  <label htmlFor="jira-enabled" className="flex cursor-pointer items-center gap-2.5 pt-1 text-[13px] text-ink">
                    <input
                      id="jira-enabled"
                      type="checkbox"
                      className="h-4 w-4 shrink-0 accent-accent"
                      checked={form.enabled}
                      onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                    />
                    Integration enabled
                  </label>
                  <Notice msg={msg} />
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button type="submit" variant="primary" size="sm" disabled={!!busy}>
                      {busy === "save" ? "Saving…" : "Save configuration"}
                    </Button>
                    <Button size="sm" onClick={testConnection} disabled={!!busy}>
                      {busy === "test" ? "Testing…" : "Test connection"}
                    </Button>
                    <AnimatePresence>
                      {busy === "test" ? (
                        <motion.span
                          initial={{ opacity: 0, x: -6 }}
                          animate={{ opacity: 1, x: 0 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.18, ease: EASE }}
                          className="flex items-center gap-1.5 text-xs text-muted"
                          role="status"
                        >
                          <Loader2Icon className="h-3.5 w-3.5 animate-spin" strokeWidth={2} aria-hidden="true" />
                          Reaching Jira…
                        </motion.span>
                      ) : null}
                    </AnimatePresence>
                  </div>
                  {dirty ? (
                    <p className="text-2xs leading-snug text-faint">Test connection checks the saved configuration — save first to test these changes.</p>
                  ) : null}
                </form>
              )}
            </Panel>
          ) : null}

          <Panel className="overflow-hidden">
            <PanelHeader title="Tracked boards" meta={boards ? `${boards.length} board${boards.length === 1 ? "" : "s"}` : undefined} />
            {boards === null ? (
              <Loading>Loading boards…</Loading>
            ) : boardsErr ? (
              <div className="p-5">
                <div className="notice notice-err" role="alert">
                  {boardsErr}
                </div>
              </div>
            ) : boards.length === 0 ? (
              <Empty title="No boards tracked yet">
                {isManager ? "Track a board below to bring its issues in." : "An administrator can track a Jira board from this page."}
              </Empty>
            ) : (
              <ul className="p-2">
                <AnimatePresence initial={false}>
                  {boards.map((b) => {
                    const on = active?.id === b.id;
                    return (
                      <motion.li
                        key={b.id}
                        layout
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, x: 20, height: 0 }}
                        transition={{ duration: 0.2, ease: EASE }}
                        className={cn("relative flex items-center gap-1 rounded-lg", on ? "text-accent" : "text-muted")}
                      >
                        {on ? (
                          <motion.span
                            layoutId="jira-board-active"
                            className="absolute inset-0 rounded-lg bg-accent/10"
                            transition={{ type: "spring", stiffness: 520, damping: 38 }}
                            aria-hidden="true"
                          />
                        ) : null}
                        <button
                          type="button"
                          onClick={() => openBoard(b)}
                          aria-current={on ? "true" : undefined}
                          className={cn(
                            "relative flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2.5 py-2 text-left",
                            "transition-colors duration-150 ease-out",
                            !on && "hover:bg-surface-2 hover:text-ink"
                          )}
                        >
                          <DiamondIcon className="h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
                          <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{b.name}</span>
                          <span className="tabular font-mono text-2xs text-faint">#{b.board_id}</span>
                        </button>
                        {isManager ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="relative mr-1 shrink-0"
                            onClick={() => removeBoard(b)}
                            disabled={!!busy}
                            aria-label={`Remove ${b.name}`}
                            icon={<XIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                          >
                            Remove
                          </Button>
                        ) : null}
                      </motion.li>
                    );
                  })}
                </AnimatePresence>
              </ul>
            )}
            {isManager ? (
              <form onSubmit={addBoard} noValidate className="space-y-2.5 border-t border-line bg-surface-2 p-3">
                <Label>Track board</Label>
                <div className="grid grid-cols-[96px_1fr] gap-2">
                  <div>
                    <label htmlFor="jira-board-id" className="field-label">
                      Board ID
                    </label>
                    <input
                      id="jira-board-id"
                      type="number"
                      min="1"
                      required
                      className="input input-sm font-mono"
                      placeholder="12"
                      value={newBoard.board_id}
                      onChange={(e) => setNewBoard({ ...newBoard, board_id: e.target.value })}
                    />
                  </div>
                  <div>
                    <label htmlFor="jira-board-name" className="field-label">
                      Name
                    </label>
                    <input
                      id="jira-board-name"
                      required
                      className="input input-sm"
                      placeholder="Security backlog"
                      value={newBoard.name}
                      onChange={(e) => setNewBoard({ ...newBoard, name: e.target.value })}
                    />
                  </div>
                </div>
                <Notice msg={boardMsg} />
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  className="w-full"
                  disabled={!canAdd}
                  icon={<PlusIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                >
                  {busy === "add" ? "Tracking…" : "Track board"}
                </Button>
                <p className="text-2xs leading-snug text-faint">The board ID is the number in the Jira board URL (…/boards/12).</p>
              </form>
            ) : null}
          </Panel>
        </StackItem>

        <StackItem className="col-span-12 lg:col-span-8">
          <Panel className="overflow-hidden">
            <PanelHeader title={active ? active.name : "Board issues"}>
              {active ? (
                <div className="flex items-center gap-3">
                  <Label>
                    {issues ? `#${active.board_id} · ${issues.total} issue${issues.total === 1 ? "" : "s"}` : `#${active.board_id}`}
                  </Label>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => openBoard(active)}
                    disabled={issuesLoading}
                    icon={<RefreshCwIcon className={cn("h-3.5 w-3.5", issuesLoading && "animate-spin")} strokeWidth={2} aria-hidden="true" />}
                  >
                    Refresh
                  </Button>
                </div>
              ) : null}
            </PanelHeader>

            {boards === null ? (
              <Loading>Loading boards…</Loading>
            ) : !active ? (
              configured ? (
                <Empty title="No board selected">
                  {isManager ? "Track a board on the left to see its issues here." : "An administrator can track a Jira board from this page."}
                </Empty>
              ) : (
                <Empty title="Jira isn't connected yet">
                  {isManager
                    ? "Enter the workspace URL, account email and API token on the left, then enable the integration."
                    : "An administrator can connect Jira from this page."}
                </Empty>
              )
            ) : issueErr ? (
              <div className="p-5">
                <div className="notice notice-err" role="alert">
                  {issueErr}
                </div>
              </div>
            ) : !issues ? (
              <Loading>Fetching issues from Jira…</Loading>
            ) : issues.issues.length === 0 ? (
              <Empty title="No issues on this board">Jira returned nothing for board #{active.board_id}.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] table-fixed border-collapse">
                  <colgroup>
                    <col className="w-[104px]" />
                    <col />
                    <col className="w-[150px]" />
                    <col className="w-[150px]" />
                    <col className="w-[110px]" />
                  </colgroup>
                  <thead>
                    <tr className="border-b border-line bg-surface-2">
                      {["Key", "Summary", "Status", "Assignee", "Updated"].map((h) => (
                        <th key={h} scope="col" className={HEAD}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {issues.issues.map((i, idx) => (
                      <motion.tr
                        key={i.key}
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.22, ease: EASE, delay: Math.min(idx, 12) * 0.03 }}
                        className="transition-colors duration-150 ease-out hover:bg-surface-2"
                      >
                        <td className={CELL}>
                          <span className="font-mono text-xs text-accent">{i.key}</span>
                        </td>
                        <td className={cn(CELL, "min-w-0")} title={i.summary}>
                          <span className="block truncate text-[13px] text-ink">{i.summary}</span>
                          <span className="block truncate text-2xs text-faint">
                            {i.type}
                            {i.priority ? ` · ${i.priority}` : ""}
                          </span>
                        </td>
                        <td className={CELL}>
                          <Badge tone={statusTone(i.status)} dot>
                            {i.status || "—"}
                          </Badge>
                        </td>
                        <td className={cn(CELL, "truncate text-xs text-muted")} title={i.assignee || undefined}>
                          {i.assignee || <span className="text-faint">Unassigned</span>}
                        </td>
                        <td className={cn(CELL, "tabular font-mono text-xs text-muted")}>{(i.updated || "").slice(0, 10)}</td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}
