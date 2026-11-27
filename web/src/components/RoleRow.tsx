import { MyStatus, Role } from "../api";
import { Icon } from "../icons";
import { Logo, SourceChip, TeamCell, Tier, WorkModeIcon } from "./bits";

/** One row in a role list (Roles page, run detail). `badge` goes after the title, e.g. "Removed". */
export default function RoleRow({ role: r, selected, onOpen, onSetMine, badge, hideState }: {
  role: Role; selected: boolean; onOpen: () => void; onSetMine: (s: MyStatus) => void; badge?: React.ReactNode; hideState?: boolean;
}) {
  const closed = r.state === "closed";
  return (
    <div className={`role ${selected ? "sel" : ""}`} onClick={onOpen}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
        <Logo name={r.agency.name} />
        <div style={{ minWidth: 0 }}>
          <div className="t" style={closed ? { color: "var(--ink-2)" } : undefined}>{r.title}{badge}
            {!badge && r.is_new && <span className="chip new">New</span>}
            {r.state === "missing" && !hideState && <span className="chip warn" title="Not listed in the last successful check; removed if it's missing again"><Icon name="alert" />May be closed</span>}
            {closed && !badge && <span className="chip">Closed</span>}
            {r.needs_recheck && <span className="chip warn"><Icon name="alert" />Re-check</span>}</div>
          <div className="meta">{r.agency.name} <Tier tier={r.agency.tier} /><span className="sep">·</span>{r.category}<span className="sep">·</span><SourceChip source={r.source} /></div>
        </div>
      </div>
      <div className="who"><WorkModeIcon mode={r.work_mode} />{r.location || r.work_mode}</div>
      <div><TeamCell team={r.team} /></div>
      <div className="acts" onClick={(e) => e.stopPropagation()}>
        <button className={`btn sm ${r.my.status === "saved" ? "on" : ""}`} onClick={() => onSetMine(r.my.status === "saved" ? null : "saved")}>
          <Icon name={r.my.status === "saved" ? "bookmarkf" : "bookmark"} />{r.my.status === "saved" ? "Saved" : r.my.status === "applied" ? "Applied" : "Save"}</button>
        {r.url && !closed && <a className="btn sm primary" href={r.url} target="_blank" rel="noreferrer noopener"
          title={r.url_kind === "job" ? "Open the job posting" : "This role has no page of its own; opens the careers page"}>Apply<Icon name="ext" /></a>}
      </div>
    </div>
  );
}
