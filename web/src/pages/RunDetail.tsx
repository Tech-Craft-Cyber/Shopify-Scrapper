import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChangeType, MyStatus, Role, RunDetail, RunOutcome, api, duration, fmtDateTime, shortUrl } from "../api";
import { useApp } from "../App";
import { Icon } from "../icons";
import { Tier } from "../components/bits";
import RoleRow from "../components/RoleRow";
import RoleDrawer from "../components/RoleDrawer";
import { LOG_CLASS, RunChip } from "./Runs";

type Tab = "changes" | "outcomes" | "log";

const CHANGE: Record<ChangeType, { label: string; chip: string; icon?: string; help: string }> = {
  added: { label: "New", chip: "new", help: "Roles this run found for the first time" },
  reopened: { label: "Back", chip: "good", icon: "refresh", help: "Removed earlier, listed again in this run" },
  reposted: { label: "New link", chip: "violet", icon: "link", help: "Same title at the same agency, posted under a new link" },
  missing: { label: "May be closed", chip: "warn", icon: "alert", help: "Not listed in this run; removed if it's missing again" },
  removed: { label: "Removed", chip: "crit", icon: "xc", help: "Missing from two successful checks in a row" },
};
const ORDER: ChangeType[] = ["added", "reopened", "reposted", "missing", "removed"];

const GROUPS: [RunOutcome["group"] | "all", string][] = [
  ["all", "All"], ["hiring", "Hiring"], ["no_openings", "No openings"], ["needs_review", "Needs review"],
  ["no_careers", "No careers page"], ["failed", "Failed checks"], ["other", "Other"],
];
const GROUP_CHIP: Record<string, string> = { hiring: "good", needs_review: "warn", failed: "crit" };

export default function RunDetailPage() {
  const { user, refreshSummary } = useApp();
  const id = Number(useParams().id);
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<RunDetail | null>(null);
  const [error, setError] = useState("");
  const tab = (params.get("tab") as Tab) || "changes";
  const openId = Number(params.get("role")) || null;
  const setParam = (k: string, v: string | null) => { const p = new URLSearchParams(params); if (v) p.set(k, v); else p.delete(k); setParams(p, { replace: k !== "role" }); };

  const load = useCallback(() => { api.run(id).then((d) => { setData(d); setError(""); }).catch((e) => setError(e.message)); }, [id]);
  useEffect(() => { setData(null); load(); }, [load]);
  const running = !!data && ["running", "retrying"].includes(data.run.status);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [running, load]);

  const r = data?.run;
  const baseline = !!r?.baseline;
  const total = data ? ORDER.reduce((n, k) => n + data.counts[k], 0) : 0;

  return (
    <main className="page">
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10, fontSize: 13 }}>
        <Link to="/runs" className="muted" style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
          <Icon name="chevr" size="sm" style={{ transform: "rotate(180deg)" }} />All runs</Link>
        <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          <button className="btn sm" disabled={!data?.prev_id} onClick={() => data?.prev_id && nav(`/runs/${data.prev_id}`)}>
            <Icon name="chevr" size="sm" style={{ transform: "rotate(180deg)" }} />Older</button>
          <button className="btn sm" disabled={!data?.next_id} onClick={() => data?.next_id && nav(`/runs/${data.next_id}`)}>
            Newer<Icon name="chevr" size="sm" /></button>
        </span>
      </div>

      <div className="page-head">
        <div>
          <h1 style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>Run #{id} {r && <RunChip status={r.status} error={r.error} />}</h1>
          <div className="sub">{r ? <>
            {r.trigger === "manual" ? `Started by ${r.user_name ?? "a teammate"}` : r.trigger === "import" ? "Imported from the command-line scraper" : "Scheduled"}
            {" · "}{fmtDateTime(r.started_at)}{r.finished_at ? ` → ${fmtDateTime(r.finished_at)}` : ""}
            {" · "}{running ? "running" : duration(r.started_at, r.finished_at)}
            {" · "}{r.processed < r.total ? `${r.processed} of ${r.total}` : r.total} agencies checked
          </> : error ? "" : "Loading…"}</div>
        </div>
        {data && data.counts.added > 0 && (
          <Link className="btn" to={`/roles?run=${id}`}><Icon name="briefcase" />Open roles from this run</Link>)}
      </div>
      {error && <div className="error-banner" style={{ marginBottom: 12 }}>{error}</div>}
      {baseline && (
        <div className="card" style={{ padding: "10px 14px", marginBottom: 14, fontSize: 13, color: "var(--ink-2)", display: "flex", gap: 8, alignItems: "center" }}>
          <Icon name="info" />This is the baseline run: the first time every role was seen, so they're listed as found rather than flagged New on the Roles page.
        </div>)}

      <div className="tiles run-tiles" style={{ gridTemplateColumns: "repeat(5,1fr)", marginBottom: 16 }}>
        {ORDER.map((k) => (
          <button key={k} className={`tile ${tab === "changes" && params.get("type") === k ? "on" : ""}`} title={CHANGE[k].help}
            aria-pressed={tab === "changes" && params.get("type") === k}
            onClick={() => { const p = new URLSearchParams(params); p.delete("tab"); if (p.get("type") === k) p.delete("type"); else p.set("type", k); setParams(p, { replace: true }); }}>
            <div className="label">{k === "added" && baseline ? "Found" : CHANGE[k].label}</div>
            <div className="v tnum">{data ? data.counts[k] : "—"}</div>
            <div className="d">{CHANGE[k].help}</div>
          </button>))}
      </div>

      <div className="seg" role="tablist" style={{ marginBottom: 14 }}>
        {([["changes", "Changes", total], ["outcomes", "Agency outcomes", data?.outcomes.length], ["log", "Log", null]] as [Tab, string, number | null | undefined][]).map(([k, label, n]) => (
          <span key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setParam("tab", k === "changes" ? null : k)}>
            {label}{n != null && <span className="faint">{n}</span>}</span>))}
      </div>

      {tab === "changes" && <Changes data={data} baseline={baseline} type={(params.get("type") as ChangeType) || null}
        setType={(t) => setParam("type", t)} openId={openId} openRole={(rid) => setParam("role", rid ? String(rid) : null)}
        onMine={(rid, patch) => setData((d) => d && { ...d, changes: d.changes.map((c) => c.role.id === rid ? { ...c, role: { ...c.role, ...patch } } : c) })}
        onError={setError} />}
      {tab === "outcomes" && <Outcomes data={data} />}
      {tab === "log" && <FullLog runId={id} live={running} />}

      {openId && tab === "changes" && (
        <RoleDrawer id={openId} userId={user.id} list={(data?.changes ?? []).map((c) => c.role.id)}
          onOpen={(rid) => setParam("role", rid ? String(rid) : null)} onClose={() => setParam("role", null)}
          onChange={(patch) => { setData((d) => d && { ...d, changes: d.changes.map((c) => c.role.id === openId ? { ...c, role: { ...c.role, ...patch } } : c) }); refreshSummary(); }} />)}
    </main>
  );
}

function Changes({ data, baseline, type, setType, openId, openRole, onMine, onError }: {
  data: RunDetail | null; baseline: boolean; type: ChangeType | null; setType: (t: string | null) => void;
  openId: number | null; openRole: (id: number | null) => void; onMine: (id: number, patch: Partial<Role>) => void; onError: (m: string) => void;
}) {
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(100);
  useEffect(() => setShown(100), [type, q]);
  const list = useMemo(() => {
    if (!data) return [];
    const s = q.trim().toLowerCase();
    return data.changes
      .filter((c) => (!type || c.type === type) && (!s || `${c.role.title} ${c.role.agency.name} ${c.role.location}`.toLowerCase().includes(s)))
      .sort((a, b) => ORDER.indexOf(a.type) - ORDER.indexOf(b.type));
  }, [data, type, q]);

  const setMine = async (role: Role, status: MyStatus) => {
    onMine(role.id, { my: { ...role.my, status } });
    try { await api.setRole(role.id, status); } catch (e) { onError((e as Error).message); onMine(role.id, { my: role.my }); }
  };

  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div className="input" style={{ width: 260, maxWidth: "100%" }}><Icon name="search" />
          <input placeholder="Role, agency, location…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search changes" /></div>
        {type && <button className="chip" onClick={() => setType(null)} style={{ background: "var(--surface)", border: "1px solid var(--line-strong)", color: "var(--ink)" }}>
          {type === "added" && baseline ? "Found" : CHANGE[type].label} <Icon name="x" /></button>}
        <span className="muted">{list.length} change{list.length === 1 ? "" : "s"}</span>
      </div>
      <div className="card">
        {!data ? <div className="empty"><span className="spinner" /></div>
          : list.length === 0 ? <div className="empty">{data.changes.length === 0
            ? (["running", "retrying"].includes(data.run.status) ? "Nothing has changed yet. This page updates while the run is going." : "This run didn't change any roles. Everything it found was already on the board.")
            : "No changes match."}</div>
          : list.slice(0, shown).map((c) => (
            <RoleRow key={`${c.type}-${c.role.id}`} role={c.role} selected={openId === c.role.id} onOpen={() => openRole(c.role.id)}
              onSetMine={(st) => setMine(c.role, st)} hideState={c.type === "missing"}
              badge={<span className={`chip ${CHANGE[c.type].chip}`} title={c.type === "reposted" ? c.detail : CHANGE[c.type].help}>
                {CHANGE[c.type].icon && <Icon name={CHANGE[c.type].icon!} />}{c.type === "added" && baseline ? "Found" : CHANGE[c.type].label}</span>} />))}
        {list.length > shown && (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", borderTop: "1px solid var(--line)", color: "var(--ink-2)", fontSize: 13 }}>
            <span>Showing {shown} of {list.length}</span>
            <button className="btn sm" onClick={() => setShown(shown + 100)}>Load more</button>
          </div>)}
      </div>
    </>
  );
}

function Outcomes({ data }: { data: RunDetail | null }) {
  const nav = useNavigate();
  const [group, setGroup] = useState<RunOutcome["group"] | "all">("all");
  const [q, setQ] = useState("");
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: data?.outcomes.length ?? 0 };
    for (const o of data?.outcomes ?? []) c[o.group] = (c[o.group] ?? 0) + 1;
    return c;
  }, [data]);
  const list = (data?.outcomes ?? []).filter((o) => (group === "all" || o.group === group)
    && (!q.trim() || o.name.toLowerCase().includes(q.trim().toLowerCase())));
  return (
    <>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div className="input" style={{ width: 240, maxWidth: "100%" }}><Icon name="search" />
          <input placeholder="Search agencies…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search agencies" /></div>
        <select className="select" value={group} onChange={(e) => setGroup(e.target.value as typeof group)} aria-label="Result">
          {GROUPS.filter(([k]) => k === "all" || counts[k]).map(([k, label]) => <option key={k} value={k}>{label} ({counts[k] ?? 0})</option>)}
        </select>
        <span className="muted">{list.length} agenc{list.length === 1 ? "y" : "ies"}</span>
      </div>
      <div className="card table-wrap">
        <table className="table">
          <thead><tr><th>Agency</th><th>Result in this run</th><th style={{ textAlign: "right" }}>Roles</th><th>Details</th></tr></thead>
          <tbody>
            {!data ? <tr><td colSpan={4}><div className="empty"><span className="spinner" /></div></td></tr>
              : list.length === 0 ? <tr><td colSpan={4}><div className="empty">No agencies match.</div></td></tr>
              : list.slice(0, 300).map((o) => (
                <tr key={o.agency_id} className="click" onClick={() => nav(`/agencies?agency=${o.agency_id}`)}>
                  <td><div style={{ fontWeight: 600 }}>{o.name} <Tier tier={o.tier} /></div>
                    {o.website && <div className="faint" style={{ fontSize: 12 }}>{shortUrl(o.website)}</div>}</td>
                  <td><span className={`chip ${GROUP_CHIP[o.group] ?? ""}`}>{o.label}</span></td>
                  <td className="tnum" style={{ textAlign: "right" }}>{o.role_count || "—"}</td>
                  <td className="muted" style={{ fontSize: 12.5, maxWidth: 420 }}>{o.notes || (o.careers_url ? shortUrl(o.careers_url) : "")}</td>
                </tr>))}
          </tbody>
        </table>
        {list.length > 300 && <div className="faint" style={{ padding: "10px 16px", fontSize: 12.5 }}>Showing the first 300. Search or filter to narrow it down.</div>}
      </div>
    </>
  );
}

function FullLog({ runId, live }: { runId: number; live: boolean }) {
  const [lines, setLines] = useState<{ id: number; at: string; status: string; line: string }[] | null>(null);
  useEffect(() => {
    let stop = false;
    let last = 0;
    let acc: NonNullable<typeof lines> = [];
    const pull = async () => {
      for (;;) {
        const more = await api.runLog(runId, last).catch(() => []);
        if (stop) return;
        if (more.length) { last = more[more.length - 1].id; acc = [...acc, ...more]; }
        if (more.length < 500) break;
      }
      setLines(acc);
    };
    pull();
    const t = live ? setInterval(pull, 4000) : undefined;
    return () => { stop = true; if (t) clearInterval(t); };
  }, [runId, live]);
  return (
    <div className="card">
      <div className="card-head"><h2>Log</h2><span className="faint">{lines ? `${lines.length} lines` : ""}</span></div>
      <div className="log full-log">
        {lines === null ? <div className="no">Loading…</div> : lines.length === 0 ? <div className="no">No log lines for this run.</div>
          : lines.map((l) => (
            <div key={l.id} className="line"><span className="no">{new Date(l.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>{" "}
              <span className={LOG_CLASS[l.status] ?? "no"}>{l.status.padEnd(13, " ")}</span> {l.line}</div>))}
      </div>
    </div>
  );
}
