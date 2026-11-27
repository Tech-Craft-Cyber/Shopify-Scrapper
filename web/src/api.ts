// Typed client for the FastAPI backend.

export type User = { id: number; email: string; name: string; is_admin: boolean; initials: string };
export type MyStatus = "saved" | "applied" | "not_interested" | null;
export type TeamMark = { user_id: number; name: string; initials: string; status: "saved" | "applied"; at: string };
export type Source = { kind: "verified" | "parsed" | "check" | "manual"; label: string };
export type AgencyRef = { id: number; name: string; handle: string; tier: string; location: string; team_size: string; website: string };

export type Role = {
  id: number; title: string; location: string; department: string; url: string; url_kind: "job" | "careers";
  category: string; work_mode: string; state: "open" | "missing" | "closed";
  first_seen_at: string; last_seen_at: string; first_seen_run: number | null; is_new: boolean; manual: boolean; needs_recheck: boolean;
  added_by: string | null; source: Source; agency: AgencyRef;
  my: { status: MyStatus; note: string }; team: TeamMark[];
};

export type RoleDetail = Role & {
  agency: AgencyRef & { careers_url: string; linkedin: string; profile_url: string; partner_since: string; watching: boolean };
  more_roles: { id: number; title: string; location: string }[];
  activity: { name: string; initials: string; status: string; at: string; title: string; role_id: number }[];
  history: { type: string; detail: string; at: string }[];
};

export type AgencyStatus = "hiring" | "no_openings" | "needs_review" | "no_careers" | "other";
export type Agency = {
  id: number; handle: string; name: string; tier: string; location: string; team_size: string; website: string;
  careers_url: string; careers_email: string; ats: string; ats_board: string; raw_status: string;
  status: AgencyStatus; open_roles: number; new_roles: number; watching: boolean;
  team: { name: string; initials: string }[]; last_checked_at: string | null; notes: string;
  review_reason: string; review_state: string | null; linkedin: string; profile_url: string;
};

export type Run = {
  id: number; trigger: string; status: string; baseline: number; started_at: string; finished_at: string | null;
  total: number; processed: number; hiring: number; roles_found: number; new_roles: number; removed_roles: number;
  rate_limited: number; error: string | null; user_name: string | null;
  live_hiring?: number; live_roles?: number; live_new?: number; live_rate_limited?: number;
};
export type RunsData = {
  current: Run | null; history: Run[];
  tiles: { open_roles: number; open_roles_delta: number | null; agencies_hiring: number; agencies_total: number;
    new_last_run: number | null; removed_last_run: number | null; verified_pct: number | null };
  breakdown: { label: string; count: number }[];
  new_per_run: { id: number; started_at: string; new_roles: number; baseline: boolean }[];
};
export type ChangeType = "added" | "reopened" | "reposted" | "missing" | "removed";
export type RunOutcome = {
  agency_id: number; name: string; tier: string; website: string; careers_url: string;
  status: string; label: string; group: "hiring" | "no_openings" | "needs_review" | "no_careers" | "failed" | "other";
  role_count: number; notes: string; at: string;
};
export type RunDetail = {
  run: Run; counts: Record<ChangeType, number>;
  changes: { type: ChangeType; detail: string; at: string; role: Role }[];
  outcomes: RunOutcome[]; prev_id: number | null; next_id: number | null;
};
export type Schedule = {
  enabled: number | boolean; mode: "interval" | "daily" | "cron"; interval_hours: number; time: string; timezone: string;
  days: string; cron: string; service: string; location: string; use_browser: number | boolean;
  retry_rate_limited: number | boolean; email_team: number | boolean; skip_if_running: number | boolean;
  concurrency: number; next_runs: string[]; description: string; email_available: boolean;
};
export type Summary = {
  open_roles: number; new_roles: number; needs_review: number; unread_alerts: number;
  last_run: { id: number; finished_at: string; new_roles: number } | null;
  current_run: { id: number; status: string; total: number; processed: number } | null;
};
export type Alert = { id: number; agency_id: number | null; message: string; created_at: string; read_at: string | null };

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: { "X-Requested-With": "fetch", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && path !== "/auth/login" && path !== "/me") {
    window.dispatchEvent(new Event("auth:expired"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const d = await res.json();
      msg = typeof d.detail === "string" ? d.detail : Array.isArray(d.detail) ? d.detail.map((x: { msg: string }) => x.msg).join("; ") : msg;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  me: () => call<User>("GET", "/me"),
  login: (email: string, password: string) => call<User>("POST", "/auth/login", { email, password }),
  logout: () => call("POST", "/auth/logout"),
  changePassword: (current: string, next: string) => call("POST", "/me/password", { current, new: next }),
  summary: () => call<Summary>("GET", "/summary"),
  roles: () => call<Role[]>("GET", "/roles"),
  role: (id: number) => call<RoleDetail>("GET", `/roles/${id}`),
  setRole: (id: number, status: MyStatus, note?: string) => call<{ status: MyStatus; note: string }>("PUT", `/roles/${id}/me`, { status, note }),
  closeManualRole: (id: number) => call("DELETE", `/roles/${id}`),
  agencies: () => call<Agency[]>("GET", "/agencies"),
  watch: (id: number, on: boolean) => call<{ watching: boolean }>(on ? "PUT" : "DELETE", `/agencies/${id}/watch`),
  review: (id: number, action: "no_openings" | "ignored" | "reopen") => call("POST", `/agencies/${id}/review`, { action }),
  addRole: (id: number, r: { title: string; location: string; url: string }) => call<{ id: number }>("POST", `/agencies/${id}/roles`, r),
  runs: () => call<RunsData>("GET", "/runs"),
  run: (id: number) => call<RunDetail>("GET", `/runs/${id}`),
  runLog: (id: number, after: number) => call<{ id: number; at: string; status: string; line: string }[]>("GET", `/runs/${id}/log?after=${after}`),
  runNow: () => call<{ id: number }>("POST", "/runs"),
  stopRun: () => call("POST", "/runs/stop"),
  schedule: () => call<Schedule>("GET", "/schedule"),
  saveSchedule: (s: Partial<Schedule>) => call<Schedule>("PUT", "/schedule", s),
  previewSchedule: (s: Partial<Schedule>) => call<{ next_runs: string[]; description: string }>("POST", "/schedule/preview", s),
  alerts: () => call<Alert[]>("GET", "/alerts"),
  readAlerts: () => call("POST", "/alerts/read"),
  users: () => call<(User & { created_at: string })[]>("GET", "/users"),
  addUser: (u: { email: string; name: string; password: string; is_admin: boolean }) => call("POST", "/users", u),
  deleteUser: (id: number) => call("DELETE", `/users/${id}`),
};

// ---- formatting helpers
export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : d < 14 ? `${d} days ago` : new Date(iso).toLocaleDateString();
}

export function fmtDateTime(iso: string | null | undefined, tz?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: tz });
}

export function duration(a: string, b: string | null): string {
  const m = Math.round(((b ? new Date(b).getTime() : Date.now()) - new Date(a).getTime()) / 60000);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function host(url: string): string {
  try { return new URL(url).host.replace(/^www\./, ""); } catch { return url; }
}

export function shortUrl(url: string): string {
  try { const u = new URL(url); return (u.host.replace(/^www\./, "") + u.pathname).replace(/\/$/, ""); } catch { return url; }
}
