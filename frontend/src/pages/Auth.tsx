import { useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ApiError } from "../lib/api";
import clsx from "clsx";

type Mode = "login" | "register";

const VALUE_PROPS = [
  "One shared pool of companies and portals for the whole squad.",
  "Everyone tracks their own applications, statuses, and notes.",
  "See each other's progress live, from applied to offer.",
];

export default function Auth() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname;

  const validate = (): string | null => {
    const uname = username.trim().toLowerCase();
    if (!/^[a-z0-9_]{3,30}$/.test(uname)) {
      return "Username must be 3-30 characters: lowercase letters, digits, underscore.";
    }
    if (mode === "register" && displayName.trim().length === 0) {
      return "Display name is required.";
    }
    if (password.length < 8) {
      return "Password must be at least 8 characters.";
    }
    return null;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const uname = username.trim().toLowerCase();
      if (mode === "login") {
        await login({ username: uname, password });
      } else {
        await register({ username: uname, display_name: displayName.trim(), password });
      }
      navigate(from && from !== "/auth" ? from : "/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Couldn't reach the server. Check it is running and retry.",
      );
    } finally {
      setBusy(false);
    }
  };

  const switchMode = (m: Mode) => {
    setMode(m);
    setError(null);
  };

  return (
    <div className="flex min-h-screen">
      {/* Brand panel */}
      <div className="hidden w-1/2 flex-col justify-center border-r border-line bg-canvas p-12 lg:flex">
        <div className="max-w-md">
          <p className="text-2xl font-semibold tracking-tight text-ink">JobSquad</p>
          <p className="mt-2 text-base text-muted">The multiplayer job hunt.</p>
          <ul className="mt-10 space-y-4">
            {VALUE_PROPS.map((p) => (
              <li key={p} className="flex items-baseline gap-3 text-sm text-muted">
                <span className="h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full bg-ink/60" aria-hidden />
                {p}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Form panel */}
      <div className="flex w-full flex-col items-center justify-center p-6 lg:w-1/2">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <p className="text-xl font-semibold tracking-tight text-ink">JobSquad</p>
            <p className="mt-1 text-sm text-muted">The multiplayer job hunt.</p>
          </div>

          <div className="mb-5 grid grid-cols-2 rounded-lg border border-line bg-paper p-1">
            {(["login", "register"] as const).map((m) => (
              <button
                key={m}
                onClick={() => switchMode(m)}
                className={clsx(
                  "rounded-md py-1.5 text-sm font-medium transition-colors duration-150 ease-out",
                  mode === m ? "bg-pill text-ink" : "text-muted hover:text-ink",
                )}
              >
                {m === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          <form onSubmit={submit} className="card space-y-4 p-6" noValidate>
            <div>
              <label htmlFor="auth-username" className="label">
                Username
              </label>
              <input
                id="auth-username"
                className="input font-mono"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="e.g. haris"
                autoComplete="username"
                autoFocus
              />
            </div>
            {mode === "register" && (
              <div>
                <label htmlFor="auth-display" className="label">
                  Display name
                </label>
                <input
                  id="auth-display"
                  className="input"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="How your squad sees you"
                  autoComplete="name"
                />
              </div>
            )}
            <div>
              <label htmlFor="auth-password" className="label">
                Password
              </label>
              <input
                id="auth-password"
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "register" ? "At least 8 characters" : "Your password"}
                autoComplete={mode === "register" ? "new-password" : "current-password"}
              />
            </div>
            {error && (
              <p role="alert" className="rounded-md bg-[#FEF2F2] px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? "Signing in..." : mode === "login" ? "Sign in" : "Create account"}
            </button>
          </form>

          <p className="mt-4 text-center text-xs text-muted">
            {mode === "login" ? "New here?" : "Already have an account?"}{" "}
            <button
              className="link font-medium"
              onClick={() => switchMode(mode === "login" ? "register" : "login")}
            >
              {mode === "login" ? "Create an account" : "Sign in instead"}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
