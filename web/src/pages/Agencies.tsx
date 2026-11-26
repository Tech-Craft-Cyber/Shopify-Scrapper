import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Agency, AgencyStatus, ago, api, host, shortUrl } from "../api";
import { useApp } from "../App";
import { Icon } from "../icons";
import { Avatar, Logo, Tier } from "../components/bits";
import AgencyDrawer from "../components/AgencyDrawer";

const TABS: [AgencyStatus | "all", string, string?][] = [
  ["all", "All"], ["hiring", "Hiring", "checkc"], ["no_openings", "No openings", "minus"],
  ["needs_review", "Needs review", "alert"], ["no_careers", "No careers page", "xc"], ["other", "Other"],
];
const STATUS_CHIP: Record<AgencyStatus, [string, string, string]> = {
  hiring: ["good", "checkc", "Hiring"], no_openings: ["", "minus", "No openings"], needs_review: ["warn", "alert", "Needs review"],
  no_careers: ["", "xc", "No careers page"], other: ["", "info", "Other"],
};
const OTHER_LABEL: Record<string, string> = {
  site_unreachable: "Site unreachable", rate_limited: "Rate limited", timeout: "Timed out", error: "Error",
  no_website: "No website listed", non_company_site: "Social/booking link only", profile_error: "Profile error",
};
const PAGE = 50;

export default function AgenciesPage() {
  const { refreshSummary } = useApp();
  const [params, setParams] = useSearchParams();
  const [list, setList] = useState<Agency[] | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [tier, setTier] = useState("");
  const [sort, setSort] = useState<"name" | "roles" | "checked">("name");
  const [shown, setShown] = useState(PAGE);
  const [showReviewed, setShowReviewed] = useState(false);
  const tab = (params.get("tab") as AgencyStatus | "all") || "all";
  const watching = params.get("watching") === "1";
  const openId = Number(params.get("agency")) || null;

  const load = useCallback(() => { api.agencies().then(setList).catch((e) => setError(e.message)); }, []);
  useEffect(load, [load]);
  useEffect(() => setShown(PAGE), [tab, watching, q, tier, sort]);

  const setParam = (k: string, v: string | null) => { const p = new URLSearchParams(params); if (v) p.set(k, v); else p.delete(k); setParams(p); };
  const patch = (id: number, x: Partial<Agency>) => setList((l) => l && l.map((a) => (a.id === id ? { ...a, ...x } : a)));

  const reviewed = useMemo(() => (list ?? []).filter((a) => a.review_state && a.raw_status === "careers_page_roles_unclear"), [list]);
  const filtered = useMemo(() => {
    if (!list) return [];
    const s = q.trim().toLowerCase();
    let out = list.filter((a) =>
      (tab === "all" || a.status === tab) && (!watching || a.watching) && (!tier || a.tier === tier) &&
      (!s || `${a.name} ${a.website} ${a.location}`.toLowerCase().includes(s)));
    if (tab === "needs_review" && showReviewed) out = reviewed.filter((a) => (!s || a.name.toLowerCase().includes(s)));
    if (sort === "roles") out = [...out].sort((a, b) => b.open_roles - a.open_roles || a.name.localeCompare(b.name));
    if (sort === "checked") out = [...out].sort((a, b) => (b.last_checked_at ?? "").localeCompare(a.last_checked_at ?? ""));
    return out;
  }, [list, tab, watching, tier, q, sort, showReviewed, reviewed]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: list?.length ?? 0 };
    for (const a of list ?? []) c[a.status] = (c[a.status] ?? 0) + 1;
    return c;
  }, [list]);

  const toggleWatch = async (a: Agency) => {
    patch(a.id, { watching: !a.watching });
    await api.watch(a.id, !a.watching).catch((e) => { setError(e.message); load(); });
  };

  return (
    <main className="page">
      <div className="page-head">
        <div><h1>Agencies</h1><div className="sub">All {counts.all || "…"} partners from the directory and what the scraper found on each site. Watch an agency to get an alert when it posts a new role.</div></div>
        <div className="input" style={{ width: 280, maxWidth: "100%" }}><Icon name="search" />
          <input placeholder="Search agencies…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search agencies" /></div>
      </div>
      {error && <div className="error-banner" style={{ marginBottom: 12 }}>{error}</div>}

      <div style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
        <div className="seg" role="tablist">
          {TABS.map(([k, label, icon]) => (
            <span key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setParam("tab", k === "all" ? null : k)}>
              {icon && <Icon name={icon} size="sm" style={{ color: k === "hiring" ? "var(--good)" : k === "needs_review" ? "var(--warn-ink)" : undefined }} />}
              {label} {k === "needs_review" && counts[k] ? <span className="count alert">{counts[k]}</span> : <span className="faint">{counts[k] ?? 0}</span>}
            </span>))}
        </div>
        <button className={`chip ${watching ? "new" : "outline"}`} style={{ height: 32, padding: "0 12px", fontSize: 13 }} onClick={() => setParam("watching", watching ? null : "1")}>
          <Icon name="bell" />Watching · {list?.filter((a) => a.watching).length ?? 0}</button>
        <select className="select" style={{ marginLeft: "auto" }} value={tier} onChange={(e) => setTier(e.target.value)} aria-label="Tier">
          <option value="">Tier: Any</option>{["Platinum", "Premier", "Plus", "Select"].map((t) => <option key={t}>{t}</option>)}
        </select>
        {tab !== "needs_review" && (
          <select className="select" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} aria-label="Sort">
            <option value="name">Name A–Z</option><option value="roles">Most open roles</option><option value="checked">Recently checked</option>
          </select>)}
      </div>

      {tab === "needs_review" ? (
        <>
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12, fontSize: 13, color: "var(--ink-2)", flexWrap: "wrap" }}>
            <Icon name="info" />
            <span style={{ flex: 1, minWidth: 260 }}>The scraper found a careers page on these sites but couldn't read the roles. Open the page and record what you see. Each answer is kept on later scrapes, and the agency comes back here only if its careers page changes.</span>
            <div className="seg"><span className={!showReviewed ? "on" : ""} onClick={() => setShowReviewed(false)}>To review</span>
              <span className={showReviewed ? "on" : ""} onClick={() => setShowReviewed(true)}>Reviewed by team <span className="faint">{reviewed.length}</span></span></div>
          </div>
          <div className="card">
            {list === null ? <div className="empty"><span className="spinner" /></div>
              : filtered.length === 0 ? <div className="empty">{showReviewed ? "Nothing reviewed yet." : "Nothing to review. Nice."}</div>
              : filtered.slice(0, shown).map((a) => (
                <ReviewItem key={a.id} a={a} onWatch={() => toggleWatch(a)} onDone={() => { load(); refreshSummary(); }} setError={setError} />))}
          </div>
        </>
      ) : (
        <div className="card table-wrap">
          <table className="table">
            <thead><tr><th>Agency</th><th>Status</th><th style={{ textAlign: "right" }}>Open roles</th><th>Source</th><th>HQ</th><th>Team size</th><th>Team</th><th>Last checked</th><th style={{ textAlign: "right" }}>Alerts</th></tr></thead>
            <tbody>
              {list === null ? <tr><td colSpan={9}><div className="empty"><span className="spinner" /></div></td></tr>
                : filtered.length === 0 ? <tr><td colSpan={9}><div className="empty">No agencies match.</div></td></tr>
                : filtered.slice(0, shown).map((a) => {
                  const [cls, icon, label] = STATUS_CHIP[a.status];
                  return (
                    <tr key={a.id} className="click" onClick={() => setParam("agency", String(a.id))}>
                      <td><div style={{ display: "flex", gap: 10, alignItems: "center" }}><Logo name={a.name} />
                        <div><b>{a.name}</b> <Tier tier={a.tier} /><div className="faint" style={{ fontSize: 12.5 }}>{a.website ? host(a.website) : "no website"}</div></div></div></td>
                      <td><span className={`chip ${cls}`}><Icon name={icon} />{a.status === "other" ? OTHER_LABEL[a.raw_status] ?? "Not checked yet" : label}</span></td>
                      <td className="tnum" style={{ textAlign: "right", fontWeight: a.open_roles ? 600 : 400 }}>
                        {a.open_roles || <span className="faint">{a.status === "no_openings" ? 0 : "—"}</span>}
                        {a.new_roles > 0 && <> <span className="chip new" style={{ height: 18, fontSize: 11 }}>+{a.new_roles}</span></>}</td>
                      <td>{a.ats ? <span className="chip outline">{a.ats[0].toUpperCase() + a.ats.slice(1)}</span> : a.careers_url ? <span className="chip outline">Careers page</span> : <span className="faint">—</span>}</td>
                      <td>{a.location.replace(/, United States$/, "") || <span className="faint">—</span>}</td>
                      <td>{a.team_size.replace(/ people$/, "") || <span className="faint">—</span>}</td>
                      <td>{a.team.length ? <span className="stack" title={a.team.map((t) => t.name).join(", ")}>{a.team.slice(0, 3).map((t) => <Avatar key={t.name} initials={t.initials} name={t.name} sm />)}</span> : <span className="faint">—</span>}</td>
                      <td className="faint">{ago(a.last_checked_at)}</td>
                      <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                        <button className={`watch ${a.watching ? "on" : ""}`} onClick={() => toggleWatch(a)}><Icon name="bell" size="sm" />{a.watching ? "Watching" : "Watch"}</button></td>
                    </tr>);
                })}
            </tbody>
          </table>
        </div>
      )}
      {filtered.length > shown && (
        <div style={{ display: "flex", justifyContent: "center", marginTop: 12 }}>
          <button className="btn" onClick={() => setShown(shown + PAGE)}>Show more ({filtered.length - shown} left)</button></div>)}

      {openId && <AgencyDrawer id={openId} onClose={() => setParam("agency", null)} onWatch={(on) => patch(openId, { watching: on })} />}
    </main>
  );
}

function ReviewItem({ a, onWatch, onDone, setError }: { a: Agency; onWatch: () => void; onDone: () => void; setError: (s: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [loc, setLoc] = useState("");
  const [url, setUrl] = useState(a.careers_url);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try { await fn(); onDone(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    act(async () => { await api.addRole(a.id, { title, location: loc, url }); setTitle(""); setLoc(""); setAdding(false); });
  };
  const stateLabel = { no_openings: "Marked no openings", roles_added: "Roles added by hand", ignored: "Marked not relevant" }[a.review_state ?? ""];

  return (
    <div className="q" style={adding ? { background: "#fbfcfe" } : undefined}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><b>{a.name}</b><Tier tier={a.tier} />
          {stateLabel ? <span className="chip good"><Icon name="checkc" />{stateLabel}</span>
            : <span className={`chip ${a.review_reason === "Page failed to load" ? "crit" : "warn"}`}><Icon name="alert" />{a.review_reason}</span>}</div>
        {a.careers_url && <a className="link" style={{ fontSize: 13, display: "inline-flex", gap: 5, alignItems: "center", marginTop: 4 }} href={a.careers_url} target="_blank" rel="noreferrer noopener">{shortUrl(a.careers_url)}<Icon name="ext" size="sm" /></a>}
        {a.notes && <div className="why"><Icon name="info" size="sm" />{a.notes}</div>}
        {a.careers_email && <div className="why"><Icon name="mail" size="sm" />{a.careers_email}</div>}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {a.careers_url && <a className="btn sm" href={a.careers_url} target="_blank" rel="noreferrer noopener"><Icon name="ext" />Open page</a>}
        {a.review_state ? <button className="btn sm" disabled={busy} onClick={() => act(() => api.review(a.id, "reopen"))}><Icon name="refresh" />Review again</button> : (<>
          <button className="btn sm" disabled={busy} onClick={() => act(() => api.review(a.id, "no_openings"))}>No openings</button>
          <button className={`btn sm ${adding ? "primary" : ""}`} onClick={() => setAdding(!adding)}>Add role</button>
          <button className="btn sm" disabled={busy} onClick={() => act(() => api.review(a.id, "ignored"))} title="Not a real careers page / not relevant">Not relevant</button>
        </>)}
        <button className={`btn sm ${a.watching ? "on" : ""}`} onClick={onWatch}><Icon name="bell" />{a.watching ? "Watching" : "Watch"}</button>
      </div>
      {adding && (
        <form className="add" onSubmit={submit}>
          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr auto", gap: 8, alignItems: "end" }} className="grid-2">
            <label><div className="label" style={{ marginBottom: 6 }}>Role title</div><input className="field-input" required minLength={2} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus /></label>
            <label><div className="label" style={{ marginBottom: 6 }}>Location</div><input className="field-input" placeholder="e.g. Remote (US)" value={loc} onChange={(e) => setLoc(e.target.value)} /></label>
            <label><div className="label" style={{ marginBottom: 6 }}>Apply URL</div><input className="field-input" type="url" value={url} onChange={(e) => setUrl(e.target.value)} /></label>
            <div style={{ display: "flex", gap: 6 }}><button type="button" className="btn sm" onClick={() => setAdding(false)}>Cancel</button><button className="btn sm primary" disabled={busy}>Add</button></div>
          </div>
          <div className="faint" style={{ fontSize: 12.5, marginTop: 8 }}>Roles added by hand show an “Added by hand” tag and are flagged for a re-check if this careers page changes. Add as many as the page lists.</div>
        </form>)}
    </div>
  );
}
