import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Role, ago, api, host, shortUrl } from "../api";
import { Icon } from "../icons";
import { Logo, SourceChip, Tier } from "./bits";

type Detail = { agency: Record<string, string | number | null>; roles: Role[]; history: { type: string; detail: string; at: string }[]; watching: boolean };

export default function AgencyDrawer({ id, onClose, onWatch }: { id: number; onClose: () => void; onWatch: (on: boolean) => void }) {
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setD(null);
    fetch(`/api/agencies/${id}`, { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText)))).then(setD).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);

  const toggleWatch = async () => {
    if (!d) return;
    const on = !d.watching;
    setD({ ...d, watching: on });
    onWatch(on);
    await api.watch(id, on).catch((e) => setError(e.message));
  };
  const a = d?.agency ?? {};
  const s = (k: string) => (a[k] == null ? "" : String(a[k]));

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Agency details">
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
          <span className="faint" style={{ fontSize: 12.5 }}>Agency</span>
          <button className="btn sm ghost" style={{ marginLeft: "auto" }} onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="drawer-body">
          {error && <div className="error-banner">{error}</div>}
          {!d ? <div className="empty"><span className="spinner" /></div> : (<>
            <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
              <Logo name={s("name")} big />
              <div style={{ flex: 1 }}><h1 style={{ fontSize: 21 }}>{s("name")} <Tier tier={s("tier")} /></h1>
                <div className="muted">{[s("location"), s("team_size")].filter(Boolean).join(" · ")}</div></div>
              <button className={`btn sm ${d.watching ? "on" : ""}`} onClick={toggleWatch}><Icon name="bell" />{d.watching ? "Watching" : "Watch"}</button>
            </div>
            <div className="section" style={{ marginTop: 18 }}>
              <dl className="kv">
                {s("website") && <><dt>Website</dt><dd><a className="link" href={s("website")} target="_blank" rel="noreferrer noopener">{host(s("website"))}</a></dd></>}
                {s("careers_url") && <><dt>Careers page</dt><dd><a className="link" href={s("careers_url")} target="_blank" rel="noreferrer noopener">{shortUrl(s("careers_url"))}</a></dd></>}
                {s("ats_board") && <><dt>Job board</dt><dd><a className="link" href={s("ats_board")} target="_blank" rel="noreferrer noopener">{s("ats")}</a></dd></>}
                {s("careers_email") && <><dt>Careers email</dt><dd><a className="link" href={`mailto:${s("careers_email")}`}>{s("careers_email")}</a></dd></>}
                {s("linkedin") && <><dt>LinkedIn</dt><dd><a className="link" href={s("linkedin")} target="_blank" rel="noreferrer noopener">Company page</a></dd></>}
                {s("profile_url") && <><dt>Shopify profile</dt><dd><a className="link" href={s("profile_url")} target="_blank" rel="noreferrer noopener">Partner directory</a></dd></>}
                {s("partner_since") && <><dt>Partner since</dt><dd>{s("partner_since")}</dd></>}
                <dt>Last checked</dt><dd>{ago(s("last_checked_at"))}{s("notes") ? <div className="faint" style={{ fontSize: 12.5 }}>{s("notes")}</div> : null}</dd>
              </dl>
            </div>
            <div className="section">
              <h2 style={{ marginBottom: 6 }}>Open roles ({d.roles.length})</h2>
              {d.roles.length === 0 ? <div className="faint" style={{ fontSize: 13 }}>No open roles right now. Watch this agency to get an alert when it posts one.</div>
                : d.roles.map((r) => (
                  <Link key={r.id} to={`/roles?role=${r.id}`} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "9px 0", borderBottom: "1px solid var(--line)", alignItems: "center" }}>
                    <span><b style={{ fontWeight: 550 }}>{r.title}</b> {r.is_new && <span className="chip new">New</span>}<div className="faint" style={{ fontSize: 12.5 }}>{r.location || r.work_mode}</div></span>
                    <SourceChip source={r.source} /></Link>))}
            </div>
            {d.history.length > 0 && (
              <div className="section">
                <h2 style={{ marginBottom: 8 }}>History</h2>
                {d.history.map((h, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12.5, color: "var(--ink-2)", padding: "3px 0" }}>
                    <span>{{ added: "Posted", removed: "Removed", reopened: "Listed again", reposted: "Reposted" }[h.type] ?? h.type}: {h.detail.split(" -> ")[0].replace(/^added by hand: /, "")}</span>
                    <span className="faint" style={{ whiteSpace: "nowrap" }}>{ago(h.at)}</span></div>))}
              </div>)}
          </>)}
        </div>
      </aside>
    </>
  );
}
