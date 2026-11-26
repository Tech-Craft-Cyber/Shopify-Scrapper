import { FormEvent, useState } from "react";
import { User, api } from "../api";
import { Icon } from "../icons";

export default function Login({ onLogin }: { onLogin: (u: User) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.login(email, password);
      onLogin(await api.me());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form style={{ width: "100%", maxWidth: 380 }} onSubmit={submit}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "center", marginBottom: 22 }}>
          <div className="brand-mark" style={{ width: 36, height: 36 }}><Icon name="briefcase" /></div>
          <b style={{ fontSize: 19 }}>Agency Roles</b>
        </div>
        <div className="card" style={{ padding: 26 }}>
          <h1 style={{ fontSize: 19 }}>Sign in</h1>
          <div className="sub" style={{ marginBottom: 18 }}>Team access only. Ask an admin for an account.</div>
          {error && <div className="error-banner" style={{ marginBottom: 14 }}>{error}</div>}
          <label className="label" htmlFor="email">Email</label>
          <input id="email" className="field-input" style={{ marginTop: 6 }} type="email" autoComplete="username" required
            value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          <label className="label" htmlFor="pw" style={{ display: "block", marginTop: 14 }}>Password</label>
          <input id="pw" className="field-input" style={{ marginTop: 6 }} type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <button className="btn primary" type="submit" disabled={busy} style={{ width: "100%", justifyContent: "center", height: 40, marginTop: 18 }}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
