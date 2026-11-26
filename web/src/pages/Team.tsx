import { FormEvent, useEffect, useState } from "react";
import { User, api, fmtDateTime } from "../api";
import { useApp } from "../App";
import { Icon } from "../icons";
import { Avatar } from "../components/bits";

export default function TeamPage() {
  const { user } = useApp();
  return (
    <main className="page" style={{ maxWidth: 900, margin: "0 auto" }}>
      <div className="page-head"><div><h1>{user.is_admin ? "Team & account" : "My account"}</h1></div></div>
      <PasswordCard />
      {user.is_admin && <TeamCard me={user} />}
    </main>
  );
}

function PasswordCard() {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.changePassword(cur, next); setMsg({ ok: true, text: "Password changed." }); setCur(""); setNext(""); }
    catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
  };
  return (
    <form className="card" style={{ marginBottom: 16 }} onSubmit={submit}>
      <div className="card-head"><h2>Change password</h2></div>
      <div style={{ padding: 16, display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 10, alignItems: "end" }} className="grid-2">
        <label><div className="label" style={{ marginBottom: 6 }}>Current password</div><input className="field-input" type="password" autoComplete="current-password" required value={cur} onChange={(e) => setCur(e.target.value)} /></label>
        <label><div className="label" style={{ marginBottom: 6 }}>New password (10+ characters)</div><input className="field-input" type="password" autoComplete="new-password" minLength={10} required value={next} onChange={(e) => setNext(e.target.value)} /></label>
        <button className="btn primary">Update</button>
        {msg && <div className={msg.ok ? "ok-banner" : "error-banner"} style={{ gridColumn: "1 / -1" }}>{msg.text}</div>}
      </div>
    </form>
  );
}

function TeamCard({ me }: { me: User }) {
  const [users, setUsers] = useState<(User & { created_at: string })[]>([]);
  const [form, setForm] = useState({ email: "", name: "", password: "", is_admin: false });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = () => api.users().then(setUsers).catch((e) => setMsg({ ok: false, text: e.message }));
  useEffect(() => { load(); }, []);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.addUser(form); setMsg({ ok: true, text: `Added ${form.email}. Share the password with them; they can change it under My account.` }); setForm({ email: "", name: "", password: "", is_admin: false }); load(); }
    catch (err) { setMsg({ ok: false, text: (err as Error).message }); }
  };
  const remove = async (u: User) => {
    if (!confirm(`Remove ${u.name}? Their saved roles and notes are deleted.`)) return;
    await api.deleteUser(u.id).catch((e) => setMsg({ ok: false, text: e.message }));
    load();
  };

  return (
    <div className="card">
      <div className="card-head"><h2>Team</h2><span className="faint" style={{ fontSize: 12.5 }}>{users.length} people</span></div>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Added</th><th /></tr></thead>
        <tbody>{users.map((u) => (
          <tr key={u.id}><td><span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}><Avatar initials={u.name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase()} name={u.name} sm />{u.name}</span></td>
            <td>{u.email}</td><td>{u.is_admin ? <span className="chip new">Admin</span> : <span className="chip">Member</span>}</td>
            <td className="faint">{fmtDateTime(u.created_at)}</td>
            <td style={{ textAlign: "right" }}>{u.id !== me.id && <button className="btn sm ghost" onClick={() => remove(u)} aria-label={`Remove ${u.name}`}><Icon name="trash" /></button>}</td></tr>))}</tbody>
      </table></div>
      <form onSubmit={add} style={{ padding: 16, borderTop: "1px solid var(--line)", display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto auto", gap: 10, alignItems: "end" }} className="grid-2">
        <label><div className="label" style={{ marginBottom: 6 }}>Name</div><input className="field-input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label><div className="label" style={{ marginBottom: 6 }}>Email</div><input className="field-input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
        <label><div className="label" style={{ marginBottom: 6 }}>Temporary password</div><input className="field-input" type="text" minLength={10} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></label>
        <label style={{ display: "flex", gap: 8, alignItems: "center", height: 36, fontSize: 13 }}><input type="checkbox" checked={form.is_admin} onChange={(e) => setForm({ ...form, is_admin: e.target.checked })} />Admin</label>
        <button className="btn primary"><Icon name="plus" />Add</button>
        {msg && <div className={msg.ok ? "ok-banner" : "error-banner"} style={{ gridColumn: "1 / -1" }}>{msg.text}</div>}
      </form>
    </div>
  );
}
