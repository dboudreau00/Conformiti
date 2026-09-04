import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { FlagIcon, PlusIcon, UserIcon, UserPlusIcon, XIcon } from "lucide-react";
import api, { fetchAll } from "../api/client.js";
import { Badge } from "../components/ui/Badge.jsx";
import { Button } from "../components/ui/Button.jsx";
import { Empty, Label, Loading, Panel, PanelHeader } from "../components/ui/Panel.jsx";
import { EASE, PanelTransition, Stack, StackItem } from "../components/layout/PanelTransition.jsx";
import { errorText } from "../utils/a11y.js";
import { cn } from "../utils/cn.js";

function Notice({ notice }) {
  if (!notice) return null;
  return (
    <div className={cn("notice", notice.kind === "ok" ? "notice-ok" : "notice-err")} role={notice.kind === "ok" ? "status" : "alert"}>
      {notice.text}
    </div>
  );
}

/** Membership is unique per (group, user); DRF phrases that as a "unique set" error. */
function memberErrorText(e) {
  const msg = errorText(e);
  return /unique/i.test(msg) ? "That person is already a champion in this group." : msg;
}

const displayName = (u) => u?.full_name || u?.username || "";

export default function Groups({ me }) {
  const canEdit = !!me?.capabilities?.manage_users;

  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState("");
  const [active, setActive] = useState(null);
  const [members, setMembers] = useState([]);
  const [membersLoading, setMembersLoading] = useState(false);
  const [membersErr, setMembersErr] = useState("");
  const [users, setUsers] = useState([]);

  // Guards against a slow members response landing after the user switched groups.
  const membersReq = useRef(0);
  const activeIdRef = useRef(null);

  // New-group form (left column)
  const [gName, setGName] = useState("");
  const [gPurpose, setGPurpose] = useState("");
  const [gOwner, setGOwner] = useState("");
  const [gBusy, setGBusy] = useState(false);
  const [gNotice, setGNotice] = useState(null);

  // Add-champion form (right column)
  const [mUser, setMUser] = useState("");
  const [mDept, setMDept] = useState("");
  const [mNote, setMNote] = useState("");
  const [mBusy, setMBusy] = useState(false);
  const [mNotice, setMNotice] = useState(null);
  const [removingId, setRemovingId] = useState(null);

  function open(g) {
    const switching = g.id !== activeIdRef.current;
    activeIdRef.current = g.id;
    setActive(g);
    if (switching) {
      setMembers([]);
      setMembersLoading(true);
      setMNotice(null);
      setMUser("");
    }
    setMembersErr("");
    const req = ++membersReq.current;
    fetchAll(`/group-members/?group=${g.id}`)
      .then((list) => {
        if (membersReq.current !== req) return;
        setMembers(list);
      })
      .catch((e) => {
        if (membersReq.current !== req) return;
        setMembers([]);
        setMembersErr(errorText(e));
      })
      .finally(() => {
        if (membersReq.current === req) setMembersLoading(false);
      });
  }

  function loadGroups(selectId) {
    setLoadErr("");
    return fetchAll("/champion-groups/")
      .then((list) => {
        setGroups(list);
        const pick = selectId ? list.find((g) => g.id === selectId) : list[0];
        if (pick) open(pick);
        else {
          activeIdRef.current = null;
          setActive(null);
          setMembers([]);
        }
      })
      .catch((e) => setLoadErr(errorText(e)))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadGroups();
  }, []);

  // /users/ is manage_users-only and only feeds the editor pickers, so only editors fetch it.
  useEffect(() => {
    if (!canEdit) return;
    fetchAll("/users/").then(setUsers).catch(() => setUsers([]));
  }, [canEdit]);

  async function addGroup(e) {
    e.preventDefault();
    if (!canEdit || gBusy || !gName.trim()) return;
    setGBusy(true);
    setGNotice(null);
    const payload = { name: gName.trim(), purpose: gPurpose.trim() };
    if (gOwner) payload.owner = Number(gOwner);
    try {
      const { data } = await api.post("/champion-groups/", payload);
      setGName("");
      setGPurpose("");
      setGOwner("");
      setGNotice({ kind: "ok", text: `Created “${data.name}”.` });
      await loadGroups(data.id);
    } catch (ex) {
      setGNotice({ kind: "err", text: errorText(ex) });
    } finally {
      setGBusy(false);
    }
  }

  async function addMember(e) {
    e.preventDefault();
    if (!canEdit || !active || mBusy || !mUser || !mDept.trim()) return;
    setMBusy(true);
    setMNotice(null);
    const picked = users.find((u) => String(u.id) === mUser);
    try {
      await api.post("/group-members/", {
        group: active.id,
        user: Number(mUser),
        department: mDept.trim(),
        note: mNote.trim(),
      });
      setMUser("");
      setMDept("");
      setMNote("");
      setMNotice({ kind: "ok", text: `Added ${displayName(picked) || "champion"} to ${active.name}.` });
      await loadGroups(active.id);
    } catch (ex) {
      setMNotice({ kind: "err", text: memberErrorText(ex) });
    } finally {
      setMBusy(false);
    }
  }

  async function removeMember(m) {
    if (!canEdit || !active || removingId) return;
    setRemovingId(m.id);
    setMNotice(null);
    try {
      await api.delete(`/group-members/${m.id}/`);
      setMNotice({ kind: "ok", text: `Removed ${m.user_name || m.username} from ${active.name}.` });
      await loadGroups(active.id);
    } catch (ex) {
      setMNotice({ kind: "err", text: errorText(ex) });
    } finally {
      setRemovingId(null);
    }
  }

  const memberIds = new Set(members.map((m) => m.user));
  const addable = users.filter((u) => !memberIds.has(u.id));
  const memberLabel = (n) => `${n} ${n === 1 ? "member" : "members"}`;

  return (
    <PanelTransition>
      <Stack className="grid grid-cols-12 gap-4">
        {/* ---- Group list + new-group form ---- */}
        <StackItem className="col-span-12 lg:col-span-4">
          <Panel className="overflow-hidden">
            <PanelHeader title="Champion groups" meta={!loading ? `${groups.length} ${groups.length === 1 ? "group" : "groups"}` : "Inter-departmental"} />

            {loadErr ? <div className="px-4 pt-3"><div className="notice notice-err" role="alert">{loadErr}</div></div> : null}

            {loading ? (
              <Loading />
            ) : groups.length === 0 ? (
              <Empty title="No champion groups yet">
                {canEdit ? "Create the first group below." : "Nothing has been set up yet."}
              </Empty>
            ) : (
              <ul className="p-2" aria-label="Champion groups">
                {groups.map((g) => {
                  const on = active?.id === g.id;
                  return (
                    <li key={g.id}>
                      <button
                        type="button"
                        onClick={() => open(g)}
                        aria-current={on ? "true" : undefined}
                        className={cn(
                          "relative flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors duration-150 ease-out",
                          on ? "text-accent" : "text-muted hover:bg-surface-2 hover:text-ink"
                        )}
                      >
                        {on ? (
                          <motion.span
                            layoutId="group-active"
                            className="absolute inset-0 rounded-lg bg-accent/10"
                            transition={{ type: "spring", stiffness: 520, damping: 38 }}
                            aria-hidden="true"
                          />
                        ) : null}
                        <FlagIcon className={cn("relative h-3.5 w-3.5 shrink-0", on ? "text-accent" : "text-faint")} strokeWidth={2} aria-hidden="true" />
                        <span className="relative min-w-0 flex-1 truncate text-[13px] font-medium">{g.name}</span>
                        <Badge tone={on ? "accent" : "muted"} className="tabular relative shrink-0">
                          {memberLabel(g.member_count ?? 0)}
                        </Badge>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}

            {canEdit ? (
              <form onSubmit={addGroup} className="space-y-2 border-t border-line p-3" aria-labelledby="new-group-label">
                <Label id="new-group-label" as="p">New group</Label>
                <div>
                  <label htmlFor="cg-name" className="sr-only">Group name</label>
                  <input
                    id="cg-name"
                    className="input input-sm"
                    value={gName}
                    onChange={(e) => setGName(e.target.value)}
                    placeholder="Group name, e.g. Privacy Champions"
                    required
                    maxLength={160}
                    disabled={gBusy}
                  />
                </div>
                <div>
                  <label htmlFor="cg-purpose" className="sr-only">Purpose</label>
                  <input
                    id="cg-purpose"
                    className="input input-sm"
                    value={gPurpose}
                    onChange={(e) => setGPurpose(e.target.value)}
                    placeholder="Purpose — what this group is accountable for"
                    disabled={gBusy}
                  />
                </div>
                {users.length > 0 ? (
                  <div>
                    <label htmlFor="cg-owner" className="sr-only">Accountable owner</label>
                    <select id="cg-owner" className="input input-sm" value={gOwner} onChange={(e) => setGOwner(e.target.value)} disabled={gBusy}>
                      <option value="">Accountable owner — unassigned</option>
                      {users.map((u) => (
                        <option key={u.id} value={u.id}>{displayName(u)}</option>
                      ))}
                    </select>
                  </div>
                ) : null}
                <Button
                  type="submit"
                  size="sm"
                  variant="primary"
                  className="w-full"
                  disabled={gBusy || !gName.trim()}
                  icon={<PlusIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                >
                  {gBusy ? "Creating…" : "Create group"}
                </Button>
                <Notice notice={gNotice} />
              </form>
            ) : null}

            <p className="border-t border-line px-5 py-3 text-xs leading-snug text-faint">
              Each group has one accountable owner; members are champions who carry security practices into the department
              they are tagged with.
            </p>
          </Panel>
        </StackItem>

        {/* ---- Selected group + add-champion form ---- */}
        <StackItem className="col-span-12 space-y-4 lg:col-span-8">
          {loading ? (
            <Panel>
              <Loading />
            </Panel>
          ) : !active ? (
            <Panel>
              <Empty title="No group selected">
                {groups.length === 0
                  ? canEdit
                    ? "Create a champion group to start assigning departmental champions."
                    : "No champion groups have been defined yet."
                  : "Pick a group to see its champions."}
              </Empty>
            </Panel>
          ) : (
            <AnimatePresence mode="wait">
              <motion.div
                key={active.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.22, ease: EASE }}
              >
                <Panel className="overflow-hidden">
                  <PanelHeader title={active.name}>
                    <Label className="flex items-center gap-1">
                      <UserIcon className="h-3 w-3" strokeWidth={2} aria-hidden="true" />
                      Owner: {active.owner_name || "unassigned"}
                    </Label>
                  </PanelHeader>
                  <p className={cn("border-b border-line px-5 py-3 text-[13px] leading-snug", active.purpose ? "text-muted" : "italic text-faint")}>
                    {active.purpose || "No stated purpose yet."}
                  </p>

                  {mNotice ? <div className="px-5 pt-3"><Notice notice={mNotice} /></div> : null}

                  {membersErr ? (
                    <div className="px-5 py-3"><div className="notice notice-err" role="alert">{membersErr}</div></div>
                  ) : membersLoading ? (
                    <Loading />
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-left">
                        <thead>
                          <tr className="border-b border-line bg-surface-2">
                            <th scope="col" className="table-head px-5 py-2 font-normal">Champion</th>
                            <th scope="col" className="table-head px-5 py-2 font-normal">Department</th>
                            <th scope="col" className="table-head px-5 py-2 font-normal">Note</th>
                            {canEdit ? <th scope="col" className="table-head w-[90px] px-5 py-2 text-right font-normal"><span className="sr-only">Actions</span></th> : null}
                          </tr>
                        </thead>
                        <tbody>
                          <AnimatePresence initial={false}>
                            {members.map((m) => (
                              <motion.tr
                                key={m.id}
                                initial={{ opacity: 0, y: 6 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, x: 20 }}
                                transition={{ duration: 0.2, ease: EASE }}
                                className="border-b border-line last:border-0"
                              >
                                <td className="px-5 py-3 align-top">
                                  <p className="text-[13px] font-medium leading-snug text-ink">{m.user_name || m.username}</p>
                                  <p className="font-mono text-2xs text-faint">{m.username}</p>
                                </td>
                                <td className="px-5 py-3 align-top">
                                  <Badge>{m.department}</Badge>
                                </td>
                                <td className="max-w-[320px] px-5 py-3 align-top text-xs leading-snug text-muted">
                                  {m.note ? <span className="line-clamp-2">{m.note}</span> : <span className="text-faint">—</span>}
                                </td>
                                {canEdit ? (
                                  <td className="px-5 py-2 text-right align-top">
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => removeMember(m)}
                                      disabled={removingId !== null}
                                      aria-label={`Remove ${m.user_name || m.username} from ${active.name}`}
                                      icon={<XIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                                    >
                                      {removingId === m.id ? "Removing…" : "Remove"}
                                    </Button>
                                  </td>
                                ) : null}
                              </motion.tr>
                            ))}
                          </AnimatePresence>
                        </tbody>
                      </table>
                      {members.length === 0 ? (
                        <Empty title="No champions in this group yet">
                          {canEdit ? "Add the first champion below." : "Nobody has been assigned to this group."}
                        </Empty>
                      ) : null}
                    </div>
                  )}

                  <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-2.5">
                    <Label>{membersLoading ? "Loading…" : memberLabel(members.length)}</Label>
                    {active.owner_name ? <Label>Accountable: {active.owner_name}</Label> : null}
                  </div>
                </Panel>
              </motion.div>
            </AnimatePresence>
          )}

          {active && canEdit ? (
            <Panel className="overflow-hidden">
              <PanelHeader title="Add a champion" meta={active.name} />
              <form onSubmit={addMember} className="bg-surface-2 p-4">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_200px_minmax(0,1fr)_auto] md:items-end">
                  <div>
                    <label htmlFor="cm-user" className="field-label">User</label>
                    <select id="cm-user" className="input input-sm" value={mUser} onChange={(e) => setMUser(e.target.value)} required disabled={mBusy}>
                      <option value="">Select a person…</option>
                      {addable.map((u) => (
                        <option key={u.id} value={u.id}>
                          {displayName(u)}{u.role_detail?.name ? ` · ${u.role_detail.name}` : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="cm-dept" className="field-label">Department they champion</label>
                    <input
                      id="cm-dept"
                      className="input input-sm"
                      value={mDept}
                      onChange={(e) => setMDept(e.target.value)}
                      placeholder="Engineering"
                      required
                      maxLength={120}
                      disabled={mBusy}
                    />
                  </div>
                  <div>
                    <label htmlFor="cm-note" className="field-label">Note (optional)</label>
                    <input
                      id="cm-note"
                      className="input input-sm"
                      value={mNote}
                      onChange={(e) => setMNote(e.target.value)}
                      placeholder="e.g. leads secure-code training"
                      maxLength={200}
                      disabled={mBusy}
                    />
                  </div>
                  <Button
                    type="submit"
                    size="sm"
                    variant="primary"
                    className="md:h-8"
                    disabled={mBusy || !mUser || !mDept.trim()}
                    icon={<UserPlusIcon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />}
                  >
                    {mBusy ? "Adding…" : "Add champion"}
                  </Button>
                </div>
                {addable.length === 0 && users.length > 0 && !membersLoading ? (
                  <p className="mt-3 text-xs text-faint">Everyone is already a champion in this group.</p>
                ) : null}
              </form>
            </Panel>
          ) : null}
        </StackItem>
      </Stack>
    </PanelTransition>
  );
}
