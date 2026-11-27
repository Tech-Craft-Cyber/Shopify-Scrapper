import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Alert, Summary, User, ago, api } from "./api";
import { Icon } from "./icons";
import Login from "./pages/Login";
import RolesPage from "./pages/Roles";
import AgenciesPage from "./pages/Agencies";
import RunsPage from "./pages/Runs";
import RunDetailPage from "./pages/RunDetail";
import TeamPage from "./pages/Team";

type Ctx = { user: User; summary: Summary | null; refreshSummary: () => void };
const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => { api.me().then(setUser).catch(() => setUser(null)); }, []);
  useEffect(() => {
    const onExpired = () => setUser(null);
    window.addEventListener("auth:expired", onExpired);
    return () => window.removeEventListener("auth:expired", onExpired);
  }, []);

  const refreshSummary = useCallback(() => { api.summary().then(setSummary).catch(() => {}); }, []);
  useEffect(() => {
    if (!user) return;
    refreshSummary();
    const t = setInterval(refreshSummary, 20000);
    return () => clearInterval(t);
  }, [user, refreshSummary]);

  if (user === undefined) return <div className="login-wrap"><span className="spinner" /></div>;
  if (user === null) return <Login onLogin={(u) => setUser(u)} />;

  return (
    <AppCtx.Provider value={{ user, summary, refreshSummary }}>
      <Topbar onLogout={() => api.logout().finally(() => setUser(null))} />
      <Routes>
        <Route path="/" element={<Navigate to="/roles" replace />} />
        <Route path="/roles" element={<RolesPage />} />
        <Route path="/agencies" element={<AgenciesPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:id" element={<RunDetailPage />} />
        <Route path="/team" element={<TeamPage />} />
        <Route path="*" element={<Navigate to="/roles" replace />} />
      </Routes>
      <TabBar />
    </AppCtx.Provider>
  );
}

function useOutsideClose(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) close(); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open, close]);
  return ref;
}

function Topbar({ onLogout }: { onLogout: () => void }) {
  const { user, summary, refreshSummary } = useApp();
  const [menu, setMenu] = useState(false);
  const [bell, setBell] = useState(false);
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const menuRef = useOutsideClose(menu, useCallback(() => setMenu(false), []));
  const bellRef = useOutsideClose(bell, useCallback(() => setBell(false), []));
  const nav = useNavigate();

  const openBell = async () => {
    setBell((b) => !b);
    if (!bell) {
      const a = await api.alerts();
      setAlerts(a);
      if (a.some((x) => !x.read_at)) { await api.readAlerts(); refreshSummary(); }
    }
  };

  const cur = summary?.current_run;
  return (
    <header className="topbar">
      <Link to="/roles" className="brand"><div className="brand-mark"><Icon name="briefcase" size="sm" /></div>Agency Roles</Link>
      <nav className="nav">
        <NavLink to="/roles" className={({ isActive }) => (isActive ? "on" : "")}><Icon name="briefcase" />Roles
          {summary && <span className="count">{summary.open_roles}</span>}</NavLink>
        <NavLink to="/agencies" className={({ isActive }) => (isActive ? "on" : "")}><Icon name="building" />Agencies
          {!!summary?.needs_review && <span className="count alert" title="Careers pages that need a human check">{summary.needs_review}</span>}</NavLink>
        <NavLink to="/runs" className={({ isActive }) => (isActive ? "on" : "")}><Icon name="activity" />Runs</NavLink>
      </nav>
      <div className="right">
        <button className="run-pill pill-btn" onClick={() => nav("/runs")} style={{ padding: "5px 12px 5px 10px", border: "1px solid var(--line)" }}>
          {cur ? (<><span className="dot live" />{cur.status === "retrying" ? "Retrying rate-limited sites" : `Scraping · ${cur.processed} / ${cur.total || "…"}`}</>)
            : summary?.last_run ? (<><span className="dot" />Last scrape {ago(summary.last_run.finished_at)} · <b style={{ color: "var(--ink)" }}>{summary.new_roles} new</b></>)
            : (<><span className="dot" style={{ background: "#bbb", boxShadow: "none" }} />No scrapes yet</>)}
        </button>
        <div ref={bellRef} style={{ position: "relative" }}>
          <button className="pill-btn" onClick={openBell} aria-label="Alerts" style={{ position: "relative", display: "flex", color: "var(--ink-2)" }}>
            <Icon name="bell" size="lg" />{!!summary?.unread_alerts && <span className="bell-dot" />}
          </button>
          {bell && (
            <div className="menu alerts-pop">
              <div style={{ padding: "12px 14px", borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between" }}>
                <b>Alerts</b><Link to="/agencies?watching=1" onClick={() => setBell(false)} className="link" style={{ fontSize: 13 }}>Watched agencies</Link>
              </div>
              {alerts === null ? <div className="empty"><span className="spinner" /></div>
                : alerts.length === 0 ? <div className="empty" style={{ fontSize: 13 }}>No alerts yet. Watch an agency to hear when it posts a new role.</div>
                : alerts.map((a) => (
                  <div key={a.id} className={`alert-item ${a.read_at ? "" : "unread"}`}>
                    <div>{a.message}</div><div className="faint" style={{ fontSize: 12, marginTop: 3 }}>{ago(a.created_at)}</div>
                  </div>))}
            </div>
          )}
        </div>
        <div ref={menuRef} style={{ position: "relative" }}>
          <button className="avatar a1 pill-btn" style={{ color: "#fff" }} onClick={() => setMenu(!menu)} aria-label="Account">{user.initials}</button>
          {menu && (
            <div className="menu">
              <div style={{ padding: "8px 10px 10px", borderBottom: "1px solid var(--line)", marginBottom: 4 }}>
                <b>{user.name}</b><div className="faint" style={{ fontSize: 12.5 }}>{user.email}</div>
              </div>
              <Link to="/team" onClick={() => setMenu(false)}><Icon name="users" />{user.is_admin ? "Team & account" : "My account"}</Link>
              <a href="/api/roles.csv"><Icon name="download" />Export roles (CSV)</a>
              <button onClick={onLogout}><Icon name="logout" />Sign out</button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function TabBar() {
  const loc = useLocation();
  const saved = new URLSearchParams(loc.search).get("saved") === "1";
  const is = (p: string) => loc.pathname.startsWith(p);
  return (
    <nav className="tabbar">
      <Link to="/roles" className={is("/roles") && !saved ? "on" : ""}><Icon name="briefcase" size="lg" />Roles</Link>
      <Link to="/roles?saved=1" className={is("/roles") && saved ? "on" : ""}><Icon name="bookmark" size="lg" />Saved</Link>
      <Link to="/agencies" className={is("/agencies") ? "on" : ""}><Icon name="building" size="lg" />Agencies</Link>
      <Link to="/runs" className={is("/runs") ? "on" : ""}><Icon name="activity" size="lg" />Runs</Link>
    </nav>
  );
}
