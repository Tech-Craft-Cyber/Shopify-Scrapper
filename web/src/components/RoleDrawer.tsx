import { useEffect, useState } from "react";
import { MyStatus, Role, RoleDetail, ago, api, host, shortUrl } from "../api";
import { Icon } from "../icons";
import { Avatar, Logo, SourceChip, Tier } from "./bits";

const STAGES: [Exclude<MyStatus, null>, string, string][] = [
  ["saved", "Saved", "bookmarkf"], ["applied", "Applied", "send"], ["not_interested", "Not interested", "minus"],
];

export default function RoleDrawer({ id, userId, list, onOpen, onClose, onChange }: {
  id: number; userId: number; list: number[]; onOpen: (id: number) => void; onClose: () => void;
  onChange: (patch: Partial<Role>) => void;
}) {
  const [d, setD] = useState<RoleDetail | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [copied, setCopied] = useState(false);
  void userId;

  useEffect(() => {
    setD(null);
    setError("");
    api.role(id).then((x) => { setD(x); setNote(x.my.note); }).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "TEXTAREA") return;
      if (e.key === "Escape") onClose();
      const i = list.indexOf(id);
      if (e.key === "ArrowDown" && i >= 0 && i < list.length - 1) onOpen(list[i + 1]);
      if (e.key === "ArrowUp" && i > 0) onOpen(list[i - 1]);
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [id, list, onOpen, onClose]);

  const setStatus = async (s: MyStatus) => {
    if (!d) return;
    const next = d.my.status === s ? null : s;
    setD({ ...d, my: { ...d.my, status: next } });
    onChange({ my: { status: next, note } });
    await api.setRole(id, next, note).catch((e) => setError(e.message));
  };
  const saveNote = async () => {
    if (!d || note === d.my.note) return;
    setD({ ...d, my: { ...d.my, note } });
    await api.setRole(id, d.my.status, note).catch((e) => setError(e.message));
  };
  const toggleWatch = async () => {
    if (!d) return;
    const on = !d.agency.watching;
    setD({ ...d, agency: { ...d.agency, watching: on } });
    await api.watch(d.agency.id, on).catch((e) => setError(e.message));
  };
  const idx = list.indexOf(id);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Role details">
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 16px", borderBottom: "1px solid var(--line)" }}>
          <button className="btn sm ghost" style={{ padding: "0 6px" }} disabled={idx <= 0} onClick={() => onOpen(list[idx - 1])} aria-label="Previous role"><Icon name="chevup" /></button>
          <button className="btn sm ghost" style={{ padding: "0 6px" }} disabled={idx < 0 || idx >= list.length - 1} onClick={() => onOpen(list[idx + 1])} aria-label="Next role"><Icon name="chev" /></button>
          {idx >= 0 && <span className="faint" style={{ fontSize: 12.5 }}>{idx + 1} of {list.length}</span>}
          <button className="btn sm ghost" style={{ marginLeft: "auto" }} onClick={() => { navigator.clipboard?.writeText(location.href).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); }}>
            <Icon name="link" />{copied ? "Copied" : "Copy link"}</button>
          <button className="btn sm ghost" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        <div className="drawer-body">
          {error && <div className="error-banner" style={{ marginBottom: 12 }}>{error}</div>}
          {!d ? <div className="empty"><span className="spinner" /></div> : (<>
            <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
              <Logo name={d.agency.name} big />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  {d.is_new && <span className="chip new">New · first seen {ago(d.first_seen_at)}</span>}
                  <SourceChip source={d.source} />
                  {d.state === "missing" && <span className="chip warn"><Icon name="alert" />Not listed in the last check</span>}
                </div>
                <h1 style={{ fontSize: 21, marginTop: 8 }}>{d.title}</h1>
                <div className="muted" style={{ marginTop: 2 }}>{d.agency.name} · {d.category}{d.department ? ` · ${d.department}` : ""}</div>
                <div style={{ display: "flex", gap: 6, marginTop: 8, color: "var(--ink-2)", fontSize: 13, alignItems: "center" }}>
                  <Icon name={d.work_mode === "Remote" ? "wifi" : "pin"} size="sm" />{d.location || d.work_mode}
                </div>
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
              {d.url && <a className="btn primary" style={{ flex: 1, justifyContent: "center" }} href={d.url} target="_blank" rel="noreferrer noopener">
                {d.url_kind === "job" ? "Apply on agency site" : "Open careers page to apply"}<Icon name="ext" /></a>}
            </div>
            {d.manual && <div className="faint" style={{ fontSize: 12.5, marginTop: 8 }}>Added by hand by {d.added_by ?? "a teammate"}. It isn't updated by the scraper.</div>}

            <div className="section" style={{ marginTop: 18 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <h2>My status</h2><span className="faint" style={{ fontSize: 12.5 }}>Teammates see your status, not your notes</span></div>
              <div className="stage">
                {STAGES.map(([k, label, icon]) => (
                  <button key={k} className={d.my.status === k ? "on" : ""} onClick={() => setStatus(k)}><Icon name={icon} size="sm" />{label}</button>))}
              </div>
              <textarea className="note" style={{ marginTop: 10 }} rows={3} placeholder="Private notes (saved when you click away)"
                value={note} onChange={(e) => setNote(e.target.value)} onBlur={saveNote} />
            </div>

            <div className="section">
              <h2 style={{ marginBottom: 10 }}>Team activity at this agency</h2>
              {d.activity.length === 0 ? <div className="faint" style={{ fontSize: 13 }}>No teammate has saved or applied to roles here.</div> : (
                <div className="timeline">{d.activity.map((a, i) => (
                  <div className="tl" key={i}><Avatar initials={a.initials} name={a.name} sm />
                    <div><b>{a.name.split(" ")[0]}</b> {a.status} {a.role_id === d.id ? "this role" : <>to <b>{a.title}</b></>}</div>
                    <span className="when">{ago(a.at)}</span></div>))}</div>)}
            </div>

            <div className="section">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <h2>About the agency</h2>
                <button className={`btn sm ${d.agency.watching ? "on" : ""}`} onClick={toggleWatch}><Icon name="bell" />{d.agency.watching ? "Watching agency" : "Watch agency"}</button>
              </div>
              <dl className="kv">
                {d.agency.tier && <><dt>Partner tier</dt><dd><Tier tier={d.agency.tier} /></dd></>}
                {d.agency.location && <><dt>Headquarters</dt><dd>{d.agency.location}</dd></>}
                {d.agency.team_size && <><dt>Team size</dt><dd>{d.agency.team_size}</dd></>}
                {d.agency.partner_since && <><dt>Partner since</dt><dd>{d.agency.partner_since}</dd></>}
                {d.agency.careers_url && <><dt>Careers page</dt><dd><a className="link" href={d.agency.careers_url} target="_blank" rel="noreferrer noopener">{shortUrl(d.agency.careers_url)}</a></dd></>}
                <dt>Links</dt><dd style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  {d.agency.website && <a className="link" href={d.agency.website} target="_blank" rel="noreferrer noopener">{host(d.agency.website)}</a>}
                  {d.agency.linkedin && <a className="link" href={d.agency.linkedin} target="_blank" rel="noreferrer noopener">LinkedIn</a>}
                  {d.agency.profile_url && <a className="link" href={d.agency.profile_url} target="_blank" rel="noreferrer noopener">Shopify profile</a>}
                </dd>
              </dl>
            </div>

            {d.more_roles.length > 0 && (
              <div className="section">
                <h2 style={{ marginBottom: 4 }}>More roles here</h2>
                {d.more_roles.map((m) => (
                  <button key={m.id} className="pill-btn" onClick={() => onOpen(m.id)}
                    style={{ display: "flex", justifyContent: "space-between", width: "100%", padding: "8px 0", borderBottom: "1px solid var(--line)", fontSize: 13.5, textAlign: "left" }}>
                    <span>{m.title}</span><span className="faint">{m.location}</span></button>))}
              </div>)}

            {d.history.length > 0 && (
              <div className="section">
                <h2 style={{ marginBottom: 8 }}>History</h2>
                {d.history.map((h, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, color: "var(--ink-2)", padding: "3px 0" }}>
                    <span>{{ added: "First seen", reposted: "Reposted with a new link", updated: "Title or location changed", missing: "Not listed in a check", removed: "Removed", reopened: "Listed again" }[h.type] ?? h.type}</span>
                    <span className="faint">{ago(h.at)}</span></div>))}
              </div>)}
          </>)}
        </div>
      </aside>
    </>
  );
}
