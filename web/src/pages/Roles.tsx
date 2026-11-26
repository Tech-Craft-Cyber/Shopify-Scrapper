import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { MyStatus, Role, api } from "../api";
import { useApp } from "../App";
import { Icon } from "../icons";
import { Check, Logo, SourceChip, TeamCell, Tier, Toggle, WorkModeIcon, persist, store } from "../components/bits";
import RoleDrawer from "../components/RoleDrawer";

const CATEGORIES = ["Engineering", "Design", "Marketing & growth", "Project & account", "Sales", "Data & analytics", "Internship", "Other"];
const MODES = ["Remote", "Hybrid", "On-site", "Not stated"];
const SOURCES: [string, string][] = [["verified", "Verified"], ["parsed", "Parsed"], ["check", "Check"], ["manual", "Added by hand"]];
const TIERS = ["Platinum", "Premier", "Plus", "Select"];
const SIZES = ["1–10", "11–50", "51–200", "201–500", "500+"];

type Filters = {
  q: string; newOnly: boolean; hideApplied: boolean; hideTeam: boolean;
  cats: string[]; modes: string[]; sources: string[]; tiers: string[]; size: string; sort: "newest" | "agency" | "title";
};
const EMPTY: Filters = { q: "", newOnly: false, hideApplied: true, hideTeam: false, cats: [], modes: [], sources: [], tiers: [], size: "", sort: "newest" };
const PAGE = 50;

const toggleIn = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);

export default function RolesPage() {
  const { user, summary, refreshSummary } = useApp();
  const [params, setParams] = useSearchParams();
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [error, setError] = useState("");
  const [f, setF] = useState<Filters>(() => ({ ...EMPTY, ...store<Partial<Filters>>("roles.filters", {}), q: "" }));
  const [shown, setShown] = useState(PAGE);
  const [showFilters, setShowFilters] = useState(false);
  const savedOnly = params.get("saved") === "1";
  const openId = Number(params.get("role")) || null;

  const load = useCallback(() => { api.roles().then(setRoles).catch((e) => setError(e.message)); }, []);
  useEffect(load, [load]);
  useEffect(() => { const { q: _q, ...rest } = f; void _q; persist("roles.filters", rest); setShown(PAGE); }, [f]);

  const set = (patch: Partial<Filters>) => setF((x) => ({ ...x, ...patch }));
  const setSavedOnly = (on: boolean) => { const p = new URLSearchParams(params); if (on) p.set("saved", "1"); else p.delete("saved"); setParams(p); };
  const openRole = (id: number | null) => { const p = new URLSearchParams(params); if (id) p.set("role", String(id)); else p.delete("role"); setParams(p); };

  const filtered = useMemo(() => {
    if (!roles) return [];
    const q = f.q.trim().toLowerCase();
    let out = roles.filter((r) => {
      if (savedOnly && r.my.status !== "saved") return false;
      if (!savedOnly && f.hideApplied && (r.my.status === "applied" || r.my.status === "not_interested")) return false;
      if (f.hideTeam && r.team.some((t) => t.status === "applied")) return false;
      if (f.newOnly && !r.is_new) return false;
      if (f.cats.length && !f.cats.includes(r.category)) return false;
      if (f.modes.length && !f.modes.includes(r.work_mode)) return false;
      if (f.sources.length && !f.sources.includes(r.source.kind)) return false;
      if (f.tiers.length && !f.tiers.includes(r.agency.tier)) return false;
      if (f.size && !r.agency.team_size.startsWith(f.size)) return false;
      if (q && !`${r.title} ${r.agency.name} ${r.location} ${r.category} ${r.department}`.toLowerCase().includes(q)) return false;
      return true;
    });
    if (f.sort === "agency") out = [...out].sort((a, b) => a.agency.name.localeCompare(b.agency.name) || a.title.localeCompare(b.title));
    if (f.sort === "title") out = [...out].sort((a, b) => a.title.localeCompare(b.title));
    if (f.sort === "newest") out = [...out].sort((a, b) => Number(b.is_new) - Number(a.is_new) || b.first_seen_at.localeCompare(a.first_seen_at));
    return out;
  }, [roles, f, savedOnly]);

  const count = (pred: (r: Role) => boolean) => (roles ? roles.filter(pred).length : 0);
  const setMine = async (role: Role, status: MyStatus) => {
    setRoles((rs) => rs && rs.map((r) => (r.id === role.id ? { ...r, my: { ...r.my, status } } : r)));
    try { await api.setRole(role.id, status); } catch (e) { setError((e as Error).message); load(); }
  };
  const onDrawerChange = (id: number, patch: Partial<Role>) =>
    setRoles((rs) => rs && rs.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const activeChips: [string, () => void][] = [
    ...f.cats.map((c) => [c, () => set({ cats: toggleIn(f.cats, c) })] as [string, () => void]),
    ...f.modes.map((c) => [c, () => set({ modes: toggleIn(f.modes, c) })] as [string, () => void]),
    ...f.sources.map((c) => [SOURCES.find((s) => s[0] === c)?.[1] ?? c, () => set({ sources: toggleIn(f.sources, c) })] as [string, () => void]),
    ...f.tiers.map((c) => [c, () => set({ tiers: toggleIn(f.tiers, c) })] as [string, () => void]),
    ...(f.size ? [[`Team ${f.size}`, () => set({ size: "" })] as [string, () => void]] : []),
    ...(f.newOnly ? [["New since last scrape", () => set({ newOnly: false })] as [string, () => void]] : []),
  ];
  const nFilters = activeChips.length + (savedOnly ? 1 : 0);

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <h1>{savedOnly ? "Saved roles" : "Open roles"}</h1>
          <div className="sub">{roles ? `${roles.length} roles at ${new Set(roles.map((r) => r.agency.id)).size} Shopify partner agencies` : "Loading…"}
            {summary?.last_run && !savedOnly ? ` · ${summary.new_roles} new since the last scrape` : ""}</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn mobile-only" onClick={() => setShowFilters(!showFilters)}><Icon name="filter" />Filters{nFilters ? ` · ${nFilters}` : ""}</button>
          <a className="btn" href="/api/roles.csv"><Icon name="download" />Export CSV</a>
        </div>
      </div>
      {error && <div className="error-banner" style={{ marginBottom: 12 }}>{error}</div>}

      <div className="layout">
        <aside className={`filters ${showFilters ? "open" : ""}`}>
          <div className="input" style={{ marginBottom: 14 }}><Icon name="search" />
            <input placeholder="Title, agency, skill…" value={f.q} onChange={(e) => set({ q: e.target.value })} aria-label="Search roles" /></div>
          <div className="fgroup">
            <Toggle on={savedOnly} onClick={() => setSavedOnly(!savedOnly)} n={count((r) => r.my.status === "saved")}>Only roles I saved</Toggle>
            <Toggle on={f.newOnly} onClick={() => set({ newOnly: !f.newOnly })} n={summary?.new_roles ?? count((r) => r.is_new)}>New since last scrape</Toggle>
            <Toggle on={f.hideApplied} onClick={() => set({ hideApplied: !f.hideApplied })} n={count((r) => r.my.status === "applied" || r.my.status === "not_interested")}>Hide applied / not interested</Toggle>
            <Toggle on={f.hideTeam} onClick={() => set({ hideTeam: !f.hideTeam })} n={count((r) => r.team.some((t) => t.status === "applied"))}>Hide if a teammate applied</Toggle>
          </div>
          <div className="fgroup">
            <div className="label">Role type {f.cats.length > 0 && <button className="pill-btn" style={{ color: "var(--accent)", textTransform: "none", letterSpacing: 0, fontWeight: 550 }} onClick={() => set({ cats: [] })}>Clear</button>}</div>
            {CATEGORIES.map((c) => <Check key={c} on={f.cats.includes(c)} onClick={() => set({ cats: toggleIn(f.cats, c) })} n={count((r) => r.category === c)}>{c}</Check>)}
          </div>
          <div className="fgroup">
            <div className="label">Work mode</div>
            {MODES.map((m) => <Check key={m} on={f.modes.includes(m)} onClick={() => set({ modes: toggleIn(f.modes, m) })} n={count((r) => r.work_mode === m)}>{m}</Check>)}
          </div>
          <div className="fgroup">
            <div className="label">Source</div>
            {SOURCES.map(([k, label]) => (
              <Check key={k} on={f.sources.includes(k)} onClick={() => set({ sources: toggleIn(f.sources, k) })} n={count((r) => r.source.kind === k)}>
                <span className={`chip ${k === "verified" ? "good" : k === "check" ? "warn" : k === "manual" ? "violet" : ""}`}>
                  <Icon name={k === "verified" ? "checkc" : k === "check" ? "alert" : k === "manual" ? "users" : "info"} />{label}</span>
              </Check>))}
          </div>
          <div className="fgroup" style={{ border: 0 }}>
            <div className="label">Agency</div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
              {TIERS.map((t) => <button key={t} className={`chip ${f.tiers.includes(t) ? "new" : "outline"}`} onClick={() => set({ tiers: toggleIn(f.tiers, t) })}>{t}</button>)}
            </div>
            <select className="field-input" value={f.size} onChange={(e) => set({ size: e.target.value })} aria-label="Team size">
              <option value="">Team size: Any</option>
              {SIZES.map((s) => <option key={s} value={s}>{s} people</option>)}
            </select>
          </div>
        </aside>

        <section>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            {activeChips.map(([label, rm]) => (
              <button key={label} className="chip" onClick={rm} style={{ background: "var(--surface)", border: "1px solid var(--line-strong)", color: "var(--ink)" }}>{label} <Icon name="x" /></button>))}
            <span className="muted" style={{ marginLeft: 6 }}>{filtered.length} role{filtered.length === 1 ? "" : "s"}</span>
            <select className="select" style={{ marginLeft: "auto" }} value={f.sort} onChange={(e) => set({ sort: e.target.value as Filters["sort"] })} aria-label="Sort">
              <option value="newest">Newest first</option><option value="agency">Agency A–Z</option><option value="title">Title A–Z</option>
            </select>
          </div>

          <div className="card">
            <div className="role head" style={{ padding: "9px 16px", background: "var(--surface-2)", borderRadius: "var(--radius) var(--radius) 0 0", cursor: "default" }}>
              <span className="label">Role</span><span className="label">Location</span><span className="label">Team</span><span />
            </div>
            {roles === null ? <div className="empty"><span className="spinner" /></div>
              : filtered.length === 0 ? <div className="empty">{savedOnly ? "You haven't saved any roles yet." : roles.length === 0 ? "No roles yet. Run a scrape from the Runs page." : "No roles match these filters."}</div>
              : filtered.slice(0, shown).map((r) => (
                <div key={r.id} className={`role ${openId === r.id ? "sel" : ""}`} onClick={() => openRole(r.id)}>
                  <div style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
                    <Logo name={r.agency.name} />
                    <div style={{ minWidth: 0 }}>
                      <div className="t">{r.title}{r.is_new && <span className="chip new">New</span>}
                        {r.state === "missing" && <span className="chip warn" title="Not listed in the last successful check; removed if it's missing again"><Icon name="alert" />May be closed</span>}
                        {r.needs_recheck && <span className="chip warn"><Icon name="alert" />Re-check</span>}</div>
                      <div className="meta">{r.agency.name} <Tier tier={r.agency.tier} /><span className="sep">·</span>{r.category}<span className="sep">·</span><SourceChip source={r.source} /></div>
                    </div>
                  </div>
                  <div className="who"><WorkModeIcon mode={r.work_mode} />{r.location || r.work_mode}</div>
                  <div><TeamCell team={r.team} /></div>
                  <div className="acts" onClick={(e) => e.stopPropagation()}>
                    <button className={`btn sm ${r.my.status === "saved" ? "on" : ""}`} onClick={() => setMine(r, r.my.status === "saved" ? null : "saved")}>
                      <Icon name={r.my.status === "saved" ? "bookmarkf" : "bookmark"} />{r.my.status === "saved" ? "Saved" : r.my.status === "applied" ? "Applied" : "Save"}</button>
                    {r.url && <a className="btn sm primary" href={r.url} target="_blank" rel="noreferrer noopener"
                      title={r.url_kind === "job" ? "Open the job posting" : "This role has no page of its own; opens the careers page"}>Apply<Icon name="ext" /></a>}
                  </div>
                </div>))}
            {filtered.length > shown && (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 16px", borderTop: "1px solid var(--line)", color: "var(--ink-2)", fontSize: 13 }}>
                <span>Showing {shown} of {filtered.length}</span>
                <button className="btn sm" onClick={() => setShown(shown + PAGE)}>Load more</button>
              </div>)}
          </div>
        </section>
      </div>

      {openId && (
        <RoleDrawer id={openId} userId={user.id} list={filtered.map((r) => r.id)} onOpen={openRole} onClose={() => openRole(null)}
          onChange={(patch) => { onDrawerChange(openId, patch); refreshSummary(); }} />
      )}
    </main>
  );
}
