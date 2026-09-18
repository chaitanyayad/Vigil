import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/client";
import { ErrorNote } from "../components/ui";

export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      navigate("/fleet");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-full grid place-items-center px-4">
      <form onSubmit={submit} className="card p-8 w-full max-w-sm">
        <div className="text-xl font-semibold tracking-[0.3em] text-center">VIGIL</div>
        <p className="text-muted text-xs text-center mt-1 mb-6">
          AI-assisted monitoring · tamper-evident incident ledger
        </p>
        {error != null && <ErrorNote error={error} />}
        <label className="microlabel block mb-1">Username</label>
        <input
          className="field w-full mb-4"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />
        <label className="microlabel block mb-1">Password</label>
        <input
          className="field w-full mb-6"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
        <button className="btn btn-primary w-full" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
