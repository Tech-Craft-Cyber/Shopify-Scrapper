import { Role, Source } from "../api";
import { Icon } from "../icons";

export function Tier({ tier }: { tier: string }) {
  if (!tier) return null;
  const cls = tier.toLowerCase() === "platinum" ? "platinum" : tier.toLowerCase() === "premier" ? "premier" : "";
  return <span className={`tier ${cls}`}>{tier}</span>;
}

export function SourceChip({ source }: { source: Source }) {
  if (source.kind === "verified") return <span className="chip good" title="Read from the agency's job board feed"><Icon name="checkc" />Verified · {source.label}</span>;
  if (source.kind === "check") return <span className="chip warn" title="Found as a heading on the careers page — double-check it's a real opening"><Icon name="alert" />Check</span>;
  if (source.kind === "manual") return <span className="chip violet"><Icon name="users" />Added by hand</span>;
  return <span className="chip" title="Parsed from the careers page"><Icon name="info" />Parsed</span>;
}

export function Logo({ name, big }: { name: string; big?: boolean }) {
  return <div className="logo" style={big ? { width: 44, height: 44, fontSize: 16 } : undefined}>{(name.trim()[0] || "?").toUpperCase()}</div>;
}

const AV = ["a1", "a2", "a3", "a4"];
/** Same person, same colour everywhere: the colour comes from the name, not the list position. */
export function colorFor(seed: string) {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return AV[h % AV.length];
}
export function Avatar({ initials, name, sm }: { initials: string; name: string; sm?: boolean }) {
  return <span className={`avatar ${sm ? "sm" : ""} ${colorFor(name)}`} title={name}>{initials}</span>;
}

export function TeamCell({ team }: { team: Role["team"] }) {
  if (!team.length) return <span className="faint team-empty">—</span>;
  const applied = team.filter((t) => t.status === "applied");
  const label = team.length === 1 ? `${team[0].name.split(" ")[0]} ${team[0].status}`
    : applied.length ? `${applied.length} applied${team.length > applied.length ? `, ${team.length - applied.length} saved` : ""}`
    : `${team.length} saved`;
  return (
    <span className="who" title={team.map((t) => `${t.name}: ${t.status}`).join("\n")}>
      <span className="stack">{team.slice(0, 3).map((t) => <Avatar key={t.user_id} initials={t.initials} name={t.name} sm />)}</span>{label}
    </span>
  );
}

export function WorkModeIcon({ mode }: { mode: string }) {
  return <Icon name={mode === "Remote" ? "wifi" : "pin"} size="sm" />;
}

export function Check({ on, onClick, children, n }: { on: boolean; onClick: () => void; children: React.ReactNode; n?: number }) {
  return (
    <div className="frow" onClick={onClick} role="checkbox" aria-checked={on} tabIndex={0}
      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); onClick(); } }}>
      <span className={`check ${on ? "on" : ""}`}>{on && <Icon name="check" />}</span>{children}
      {n !== undefined && <span className="n">{n}</span>}
    </div>
  );
}

export function Toggle({ on, onClick, children, n }: { on: boolean; onClick: () => void; children: React.ReactNode; n?: number }) {
  return (
    <div className="frow" onClick={onClick} role="switch" aria-checked={on} tabIndex={0}
      onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); onClick(); } }}>
      <span className={`toggle ${on ? "on" : ""}`} />{children}{n !== undefined && <span className="n">{n}</span>}
    </div>
  );
}

export function store<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
export function persist(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode etc. */ }
}
