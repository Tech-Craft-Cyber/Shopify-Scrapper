import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { RunsData, Schedule, api, duration, fmtDateTime } from "../api";
import { useApp } from "../App";
import { Icon } from "../icons";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const LOG_CLASS: Record<string, string> = { roles_found: "ok", careers_page_no_openings: "no", no_careers_page: "no", rate_limited: "w", timeout: "w", warning: "w", error: "w" };

export default function RunsPage() {
  const { user, refreshSummary } = useApp();
  const [data, setData] = useState<RunsData | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();

  const load = useCallback(() => api.runs().then(setData).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  const running = !!data?.current;
  useEffect(() => {
    const t = setInterval(load, running ? 4000 : 30000);
    return () => clearInterval(t);
  }, [load, running]);

  const runNow = async () => {
    setBusy(true); setError("");
    try { await api.runNow(); await load(); refreshSummary(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const stop = async () => {
    if (!confirm("Stop the current run? Agencies already checked keep their results.")) return;
    setBusy(true);
    try { await api.stopRun(); await load(); refreshSummary(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const t = data?.tiles;
  return (
    <main className="page">
      <div className="page-head">
        <div><h1>Scrape runs</h1><div className="sub">Checks every agency in the Shopify partner directory for open roles.</div></div>
        {user.is_admin && (
          <div style={{ display: "flex", gap: 8 }}>
            {running && <button className="btn" disabled={busy} onClick={stop}><Icon name="stop" />Stop current run</button>}
            <button className="btn primary" disabled={busy || running} onClick={runNow}><Icon name="play" />Run now</button>
          </div>)}
      </div>
      {error && <div className="error-banner" style={{ marginBottom: 12 }}>{error}</div>}

      <div className="grid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1.25fr", gap: 16, marginBottom: 16, alignItems: "start" }}>
        <ScheduleCard admin={user.is_admin} />
        <CurrentRun data={data} />
      </div>

      <div className="tiles" style={{ gridTemplateColumns: "repeat(4,1fr)", marginBottom: 16 }}>
        <div className="tile"><div className="label">Open roles</div><div className="v">{t?.open_roles ?? "—"}</div>
          <div className="d">{t?.open_roles_delta != null ? <><b style={{ color: t.open_roles_delta >= 0 ? "var(--good-ink)" : "var(--crit-ink)" }}>{t.open_roles_delta >= 0 ? "+" : ""}{t.open_roles_delta}</b> vs. previous run</> : "after the latest run"}</div></div>
        <div className="tile"><div className="label">Agencies hiring</div><div className="v">{t?.agencies_hiring ?? "—"}</div><div className="d">of {t?.agencies_total ?? "—"} in the directory</div></div>
        <div className="tile"><div className="label">New roles, last run</div><div className="v">{t?.new_last_run ?? "—"}</div>
          <div className="d">{t?.new_last_run == null ? "first run is the baseline" : `${t?.removed_last_run ?? 0} roles were removed`}</div></div>
        <div className="tile"><div className="label">Verified roles</div><div className="v">{t?.verified_pct != null ? `${t.verified_pct}%` : "—"}</div><div className="d">read from job-board feeds or JSON-LD</div></div>
      </div>

      <div className="grid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        <Breakdown data={data} />
        <NewPerRun data={data} />
      </div>

      <div className="card table-wrap">
        <div className="card-head"><h2>Run history</h2><span className="faint">Click a run to see what it changed</span></div>
        <table className="table">
          <thead><tr><th>Started</th><th>Trigger</th><th>Duration</th><th style={{ textAlign: "right" }}>Agencies</th><th style={{ textAlign: "right" }}>Open roles</th><th style={{ textAlign: "right" }}>New</th><th style={{ textAlign: "right" }}>Removed</th><th>Result</th></tr></thead>
          <tbody className="tnum">
            {!data ? <tr><td colSpan={8}><div className="empty"><span className="spinner" /></div></td></tr>
              : data.history.length === 0 ? <tr><td colSpan={8}><div className="empty">No runs yet.</div></td></tr>
              : data.history.map((r) => (
                <tr key={r.id} className="click" onClick={() => nav(`/runs/${r.id}`)} title={`Open run #${r.id}`}>
                  <td>{fmtDateTime(r.started_at)}</td>
                  <td>{r.trigger === "manual" ? (r.user_name ?? "Manual") : r.trigger === "import" ? "Import" : "Schedule"}</td>
                  <td>{["running", "retrying"].includes(r.status) ? "running" : duration(r.started_at, r.finished_at)}</td>
                  <td style={{ textAlign: "right" }}>{r.processed < r.total ? `${r.processed} / ${r.total}` : r.total}</td>
                  <td style={{ textAlign: "right" }}>{r.status === "completed" ? r.roles_found : "—"}</td>
                  <td style={{ textAlign: "right" }}>{r.baseline ? <span className="faint" title="First run: everything is a baseline, not 'new'">baseline</span> : r.status === "completed" ? r.new_roles : "—"}</td>
                  <td style={{ textAlign: "right" }}>{r.status === "completed" ? r.removed_roles : "—"}</td>
                  <td><RunChip status={r.status} error={r.error} /></td>
                </tr>))}
          </tbody>
        </table>
      </div>
    </main>
  );
}

export function RunChip({ status, error }: { status: string; error: string | null }) {
  if (status === "completed") return <span className="chip good"><Icon name="checkc" />Completed</span>;
  if (status === "running") return <span className="chip new"><Icon name="refresh" />In progress</span>;
  if (status === "retrying") return <span className="chip new"><Icon name="clock" />Retrying rate-limited</span>;
  return <span className="chip crit" title={error ?? ""}><Icon name="xc" />{status === "stopped" ? `Stopped${error ? `: ${error.toLowerCase()}` : ""}` : `Failed${error ? `: ${error.slice(0, 40)}` : ""}`}</span>;
}

function CurrentRun({ data }: { data: RunsData | null }) {
  const cur = data?.current;
  const [lines, setLines] = useState<{ id: number; status: string; line: string }[]>([]);
  const lastId = useRef(0);
  const runId = cur?.id ?? data?.history[0]?.id;
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => { setLines([]); lastId.current = 0; }, [runId]);
  useEffect(() => {
    if (!runId) return;
    let stop = false;
    const tick = async () => {
      const more = await api.runLog(runId, lastId.current).catch(() => []);
      if (stop || !more.length) return;
      lastId.current = more[more.length - 1].id;
      setLines((l) => [...l, ...more].slice(-200));
    };
    tick();
    const t = setInterval(tick, cur ? 3000 : 60000);
    return () => { stop = true; clearInterval(t); };
  }, [runId, cur]);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [lines]);

  const pct = cur && cur.total ? (100 * cur.processed) / cur.total : 0;
  const etaMin = cur && cur.processed > 5 && cur.total ? Math.round(((Date.now() - new Date(cur.started_at).getTime()) / cur.processed) * (cur.total - cur.processed) / 60000) : null;
  return (
    <div className="card">
      <div className="card-head">
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span className={`dot ${cur ? "live" : ""}`} style={cur ? undefined : { background: "#bbb", boxShadow: "none" }} />
          <h2>{cur ? "Current run" : "Latest run log"}</h2>
          {cur && <span className="faint">started {fmtDateTime(cur.started_at)} {cur.trigger === "schedule" ? "by schedule" : cur.user_name ? `by ${cur.user_name}` : ""}</span>}
        </div>
        {cur && <span className="muted tnum">{cur.processed} / {cur.total || "…"}{etaMin != null && cur.status === "running" ? ` · about ${etaMin} min left` : ""}</span>}
      </div>
      {cur && (
        <div style={{ padding: "14px 16px" }}>
          <div className="progress"><div style={{ width: `${pct}%` }} /></div>
          <div style={{ display: "flex", gap: 18, marginTop: 10, fontSize: 12.5, color: "var(--ink-2)", flexWrap: "wrap" }}>
            <span><b style={{ color: "var(--ink)" }}>{cur.live_hiring}</b> hiring</span>
            <span><b style={{ color: "var(--ink)" }}>{cur.live_roles}</b> roles so far</span>
            <span><b style={{ color: "var(--ink)" }}>{cur.live_new}</b> new roles</span>
            <span><b style={{ color: "var(--ink)" }}>{cur.live_rate_limited}</b> rate-limited (retried later)</span>
          </div>
        </div>)}
      <div className="log" ref={box} style={cur ? undefined : { borderRadius: "0 0 var(--radius) var(--radius)" }}>
        {lines.length === 0 ? <div className="no">{runId ? "No log lines yet." : "No runs yet. Press Run now or turn on the schedule."}</div>
          : lines.map((l) => (
            <div key={l.id} className="line"><span className={LOG_CLASS[l.status] ?? "no"}>{l.status.padEnd(13, " ")}</span> {l.line}</div>))}
      </div>
    </div>
  );
}

function ScheduleCard({ admin }: { admin: boolean }) {
  const [s, setS] = useState<Schedule | null>(null);
  const [saved, setSaved] = useState<Schedule | null>(null);
  const [preview, setPreview] = useState<{ next_runs: string[]; description: string } | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const zones = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone") ?? ["UTC"];

  useEffect(() => { api.schedule().then((x) => { setS(x); setSaved(x); }).catch((e) => setMsg({ ok: false, text: e.message })); }, []);
  const dirty = JSON.stringify(s) !== JSON.stringify(saved);
  useEffect(() => {
    if (!s || !s.enabled) { setPreview(null); return; }
    const t = setTimeout(() => api.previewSchedule(s).then(setPreview).catch((e) => setPreview({ next_runs: [], description: e.message })), 300);
    return () => clearTimeout(t);
  }, [s]);

  if (!s) return <div className="card"><div className="empty"><span className="spinner" /></div></div>;
  const up = (p: Partial<Schedule>) => { setMsg(null); setS({ ...s, ...p }); };
  const days = s.days.split(",").filter(Boolean);
  const dis = !admin;
  const save = async () => {
    try { const x = await api.saveSchedule(s); setS(x); setSaved(x); setMsg({ ok: true, text: x.enabled ? "Schedule saved." : "Saved. Scheduled runs are off." }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };
  const nextList = preview?.next_runs ?? s.next_runs;

  return (
    <div className="card" style={{ order: -1 }}>
      <div className="card-head">
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}><Icon name="cal" /><h2>Schedule</h2></div>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, cursor: dis ? "default" : "pointer" }}>
          Scheduled runs {s.enabled ? "on" : "off"}
          <button className={`toggle pill-btn ${s.enabled ? "on" : ""}`} disabled={dis} onClick={() => up({ enabled: !s.enabled })} aria-label="Scheduled runs" />
        </label>
      </div>
      <fieldset disabled={dis} style={{ border: 0, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 14, opacity: s.enabled ? 1 : 0.6 }}>
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Repeat</div>
          <div className="seg" style={{ width: "100%" }}>
            {([["interval", "Every few hours"], ["daily", "Daily"], ["cron", "Cron"]] as const).map(([k, l]) => (
              <span key={k} className={s.mode === k ? "on" : ""} style={{ flex: 1, justifyContent: "center" }} onClick={() => !dis && up({ mode: k })}>{l}</span>))}
          </div>
        </div>
        {s.mode === "cron" ? (
          <label><div className="label" style={{ marginBottom: 6 }}>Cron expression</div>
            <input className="field-input" value={s.cron} onChange={(e) => up({ cron: e.target.value })} placeholder="0 6 * * 1-5" style={{ fontFamily: "ui-monospace, Consolas, monospace" }} />
            <div className="faint" style={{ fontSize: 12, marginTop: 4 }}>minute hour day month weekday, e.g. <code>0 6 * * 1-5</code> = 06:00 on weekdays</div></label>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: s.mode === "interval" ? "100px 140px 1fr" : "140px 1fr", gap: 10 }}>
            {s.mode === "interval" && <label><div className="label" style={{ marginBottom: 6 }}>Every</div>
              <select className="field-input" value={s.interval_hours} onChange={(e) => up({ interval_hours: Number(e.target.value) })}>
                {[1, 2, 3, 4, 6, 8, 12, 24].map((h) => <option key={h} value={h}>{h} h</option>)}</select></label>}
            <label><div className="label" style={{ marginBottom: 6 }}>{s.mode === "interval" ? "Starting" : "At"}</div>
              <input className="field-input" type="time" value={s.time} onChange={(e) => up({ time: e.target.value })} /></label>
            <label><div className="label" style={{ marginBottom: 6 }}>Time zone</div>
              <select className="field-input" value={s.timezone} onChange={(e) => up({ timezone: e.target.value })}>
                {!zones.includes(s.timezone) && <option>{s.timezone}</option>}{zones.map((z) => <option key={z}>{z}</option>)}</select></label>
          </div>)}
        {s.mode === "cron" && <label><div className="label" style={{ marginBottom: 6 }}>Time zone</div>
          <select className="field-input" value={s.timezone} onChange={(e) => up({ timezone: e.target.value })}>
            {!zones.includes(s.timezone) && <option>{s.timezone}</option>}{zones.map((z) => <option key={z}>{z}</option>)}</select></label>}
        {s.mode === "daily" && (
          <div><div className="label" style={{ marginBottom: 6 }}>On these days</div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {DAYS.map((d) => (
                <button type="button" key={d} className={`day ${days.includes(d) ? "on" : ""}`}
                  onClick={() => up({ days: DAYS.filter((x) => (x === d ? !days.includes(d) : days.includes(x))).join(",") })}>
                  {d[0].toUpperCase() + d.slice(1)}</button>))}
            </div></div>)}
        <div style={{ display: "flex", flexDirection: "column", gap: 7, fontSize: 13 }}>
          {([["use_browser", "Use the headless browser for JS-heavy or blocked sites"],
             ["retry_rate_limited", "Retry rate-limited sites 1 hour after the run"],
             ["email_team", s.email_available ? "Email the team new roles and watched-agency alerts" : "Email the team new roles (set SMTP_* in .env first)"],
             ["skip_if_running", "Skip a run if the previous one is still going"]] as const).map(([k, l]) => (
            <label key={k} style={{ display: "flex", gap: 9, alignItems: "center", cursor: dis ? "default" : "pointer" }}
              onClick={(e) => { e.preventDefault(); if (!dis && (k !== "email_team" || s.email_available)) up({ [k]: !s[k] } as Partial<Schedule>); }}>
              <span className={`check ${s[k] ? "on" : ""}`}>{s[k] ? <Icon name="check" /> : null}</span>
              <span style={{ opacity: k === "email_team" && !s.email_available ? 0.6 : 1 }}>{l}</span></label>))}
        </div>
        <details>
          <summary className="faint" style={{ fontSize: 12.5, cursor: "pointer" }}>Directory &amp; speed</summary>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 80px 90px", gap: 10, marginTop: 10 }}>
            <label><div className="label" style={{ marginBottom: 6 }}>Service</div><input className="field-input" value={s.service} onChange={(e) => up({ service: e.target.value })} /></label>
            <label><div className="label" style={{ marginBottom: 6 }}>Country</div><input className="field-input" value={s.location} maxLength={2} onChange={(e) => up({ location: e.target.value.toUpperCase() })} /></label>
            <label><div className="label" style={{ marginBottom: 6 }}>Parallel</div><input className="field-input" type="number" min={1} max={16} value={s.concurrency} onChange={(e) => up({ concurrency: Number(e.target.value) })} /></label>
          </div>
        </details>
        <div style={{ background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: 8, padding: "9px 12px", fontSize: 12.5, color: "var(--ink-2)" }}>
          {s.enabled ? (<><b style={{ color: "var(--ink)" }}>Next runs:</b> {nextList.length ? nextList.map((x) => fmtDateTime(x, s.timezone)).join(" · ") : preview?.description}
            <span className="faint"> ({s.timezone})</span></>) : "Scheduled runs are off. Turn them on to run automatically."}
        </div>
        {msg && <div className={msg.ok ? "ok-banner" : "error-banner"}>{msg.text}</div>}
        {admin ? (
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="btn sm" disabled={!dirty} onClick={() => { setS(saved); setMsg(null); }}>Cancel</button>
            <button type="button" className="btn sm primary" disabled={!dirty} onClick={save}>Save schedule</button>
          </div>) : <div className="faint" style={{ fontSize: 12.5 }}>Only admins can change the schedule.</div>}
      </fieldset>
    </div>
  );
}

function Breakdown({ data }: { data: RunsData | null }) {
  const [table, setTable] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const rows = data?.breakdown ?? [];
  const total = rows.reduce((a, r) => a + r.count, 0);
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div className="card">
      <div className="card-head"><div><h2>What each agency site gave us</h2><div className="faint" style={{ fontSize: 12.5 }}>Latest completed run · {total} agencies</div></div>
        <button className="btn sm ghost" onClick={() => setTable(!table)}>{table ? "Chart view" : "Table view"}</button></div>
      <div style={{ padding: "12px 16px 16px" }}>
        {rows.length === 0 ? <div className="empty">No completed run yet.</div> : table ? (
          <table className="table"><thead><tr><th>Result</th><th style={{ textAlign: "right" }}>Agencies</th><th style={{ textAlign: "right" }}>Share</th></tr></thead>
            <tbody className="tnum">{rows.map((r) => <tr key={r.label}><td>{r.label}</td><td style={{ textAlign: "right" }}>{r.count}</td><td style={{ textAlign: "right" }}>{Math.round(100 * r.count / total)}%</td></tr>)}</tbody></table>
        ) : rows.map((r, i) => (
          <div className="hbar" key={r.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <span>{r.label}</span>
            <div className="track">
              <div className="fill" style={{ width: `${(100 * r.count) / max}%` }} />
              {hover === i && <span className="tip" style={{ left: `${(50 * r.count) / max}%` }}>{r.label}: {r.count} ({Math.round(100 * r.count / total)}%)</span>}
            </div>
            <span className="val">{r.count}</span>
          </div>))}
      </div>
    </div>
  );
}

function niceMax(v: number) {
  for (const m of [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000]) if (v <= m) return m;
  return Math.ceil(v / 1000) * 1000;
}

function NewPerRun({ data }: { data: RunsData | null }) {
  const [table, setTable] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const pts = (data?.new_per_run ?? []).filter((p) => !p.baseline);
  const max = niceMax(Math.max(1, ...pts.map((p) => p.new_roles)));
  const H = 120;
  return (
    <div className="card">
      <div className="card-head"><div><h2>New roles per scrape</h2><div className="faint" style={{ fontSize: 12.5 }}>Last {pts.length || 14} completed runs</div></div>
        <button className="btn sm ghost" onClick={() => setTable(!table)}>{table ? "Chart view" : "Table view"}</button></div>
      {pts.length === 0 ? <div className="empty">Shows up after the second completed run (the first run is the baseline).</div> : table ? (
        <div style={{ padding: "12px 16px 16px" }}><table className="table"><thead><tr><th>Run</th><th style={{ textAlign: "right" }}>New roles</th></tr></thead>
          <tbody className="tnum">{pts.map((p) => <tr key={p.id}><td>{fmtDateTime(p.started_at)}</td><td style={{ textAlign: "right" }}>{p.new_roles}</td></tr>)}</tbody></table></div>
      ) : (
        <div style={{ padding: "22px 16px 14px 46px" }}>
          <div className="cols" style={{ height: H }}>
            {[0, max / 2, max].map((g) => <div key={g} className="gridline" style={{ bottom: (g / max) * H }}><span>{g}</span></div>)}
            {pts.map((p, i) => (
              <div key={p.id} className={`c ${i === pts.length - 1 ? "hi" : ""}`} style={{ height: Math.max(2, (p.new_roles / max) * H) }}
                onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                {hover === i && <span className="tip">{fmtDateTime(p.started_at)}: {p.new_roles} new</span>}
              </div>))}
          </div>
          <div className="xaxis">{pts.map((p, i) => <span key={p.id} style={i === pts.length - 1 ? { color: "var(--ink)", fontWeight: 600 } : undefined}>{new Date(p.started_at).getDate()}</span>)}</div>
          <div className="faint" style={{ fontSize: 12, marginTop: 8 }}>Latest: <b style={{ color: "var(--ink)" }}>{pts[pts.length - 1].new_roles} new</b> · hover a bar for the date</div>
        </div>)}
    </div>
  );
}
