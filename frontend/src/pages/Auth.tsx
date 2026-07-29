import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ApiError } from "../lib/api";
import { ProviderButtons } from "../components/ProviderButtons";
import clsx from "clsx";

type Mode = "login" | "register";
type Step = "details" | "code";

const VALUE_PROPS = [
  "One shared pool of companies and portals for the whole squad.",
  "Everyone tracks their own applications, statuses, and notes.",
  "See each other's progress live, from applied to offer.",
];

const CODE_LENGTH = 6;

export default function Auth() {
  const { login, register, otpRequired, providers, startRegistration, verifyRegistration } =
    useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [mode, setMode] = useState<Mode>("login");
  const [identifier, setIdentifier] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  // An OAuth failure lands back here with a message in router state.
  const initialError = (location.state as { authError?: string } | null)?.authError ?? null;
  const [error, setError] = useState<string | null>(initialError);

  // OTP signup state
  const [step, setStep] = useState<Step>("details");
  const [code, setCode] = useState("");
  const [pendingEmail, setPendingEmail] = useState("");
  const [resendIn, setResendIn] = useState(0);
  /** True when the pending signup is gone (expired or attempts used up). */
  const [needsNewCode, setNeedsNewCode] = useState(false);
  const autoSubmitted = useRef(false);

  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname;
  const target = from && from !== "/auth" ? from : "/";
  const landAfterAuth = useCallback(() => {
    navigate(target, { replace: true });
  }, [navigate, target]);

  // Resend cooldown ticker.
  useEffect(() => {
    if (resendIn <= 0) return;
    const t = window.setInterval(() => {
      setResendIn((s) => (s <= 1 ? 0 : s - 1));
    }, 1000);
    return () => window.clearInterval(t);
  }, [resendIn]);

  const validateDetails = (): string | null => {
    if (mode === "login") {
      if (identifier.trim().length === 0) return "Enter your email or username.";
      if (password.length === 0) return "Enter your password.";
      return null;
    }
    if (displayName.trim().length === 0) return "Display name is required.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return "Enter a valid email address.";
    if (password.length < 8) return "Password must be at least 8 characters.";
    return null;
  };

  const failMessage = (err: unknown, fallback: string): string =>
    err instanceof ApiError ? err.message : fallback;

  /** Sends (or resends) the code for the current form values. */
  const sendCode = async (): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      const res = await startRegistration({
        display_name: displayName.trim(),
        email: email.trim(),
        password,
      });
      setPendingEmail(email.trim());
      setResendIn(res.resend_after_seconds);
      setNeedsNewCode(false);
      setCode("");
      autoSubmitted.current = false;
      return true;
    } catch (err) {
      setError(failMessage(err, "Couldn't send the verification code. Retry."));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const submitDetails = async (e: FormEvent) => {
    e.preventDefault();
    const v = validateDetails();
    if (v) {
      setError(v);
      return;
    }
    setError(null);

    if (mode === "register" && otpRequired) {
      if (await sendCode()) setStep("code");
      return;
    }

    setBusy(true);
    try {
      if (mode === "login") {
        await login({ identifier: identifier.trim(), password });
      } else {
        await register({
          display_name: displayName.trim(),
          email: email.trim(),
          password,
        });
      }
      landAfterAuth();
    } catch (err) {
      setError(failMessage(err, "Couldn't reach the server. Check it is running and retry."));
    } finally {
      setBusy(false);
    }
  };

  const submitCode = useCallback(
    async (value: string) => {
      if (value.length !== CODE_LENGTH || busy) return;
      setBusy(true);
      setError(null);
      try {
        await verifyRegistration(pendingEmail, value);
        landAfterAuth();
      } catch (err) {
        setError(failMessage(err, "Couldn't verify the code. Retry."));
        // 410 expired, 429 attempts used up, 404 no pending signup: the server
        // dropped the pending row, so a fresh code is the only way forward.
        if (err instanceof ApiError && [404, 410, 429].includes(err.status)) {
          setNeedsNewCode(true);
        }
        setCode("");
        autoSubmitted.current = false;
      } finally {
        setBusy(false);
      }
    },
    [busy, landAfterAuth, pendingEmail, verifyRegistration],
  );

  const onCodeChange = (raw: string) => {
    const digits = raw.replace(/\D/g, "").slice(0, CODE_LENGTH);
    setCode(digits);
    if (digits.length === CODE_LENGTH && !autoSubmitted.current && !needsNewCode) {
      autoSubmitted.current = true;
      void submitCode(digits);
    }
  };

  const switchMode = (m: Mode) => {
    setMode(m);
    setError(null);
    setStep("details");
    setCode("");
    setNeedsNewCode(false);
  };

  const backToDetails = () => {
    setStep("details");
    setError(null);
    setCode("");
    setNeedsNewCode(false);
    autoSubmitted.current = false;
  };

  const onCodeScreen = mode === "register" && otpRequired && step === "code";

  const errorBlock = error && (
    <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">
      {error}
    </p>
  );

  return (
    <div className="flex min-h-screen">
      {/* Brand panel */}
      <div className="hidden w-1/2 flex-col justify-center border-r border-line bg-paper p-12 lg:flex">
        <div className="max-w-md">
          <p className="text-2xl font-semibold tracking-tight text-ink">JobSquad</p>
          <p className="mt-2 text-base text-muted">The multiplayer job hunt.</p>
          <ul className="mt-10 space-y-4">
            {VALUE_PROPS.map((p) => (
              <li key={p} className="flex items-baseline gap-3 text-sm text-muted">
                <span
                  className="h-1.5 w-1.5 shrink-0 translate-y-[-1px] rounded-full bg-muted/70"
                  aria-hidden
                />
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
                  mode === m ? "bg-raised text-ink" : "text-muted hover:text-ink",
                )}
              >
                {m === "login" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>

          {onCodeScreen ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void submitCode(code);
              }}
              className="card space-y-4 p-6"
              noValidate
            >
              <div>
                <h2 className="text-sm font-semibold text-ink">Check your email</h2>
                <p className="mt-1 text-sm text-muted">We sent a 6-digit code to {pendingEmail}.</p>
              </div>
              <div>
                <label htmlFor="auth-code" className="label">
                  Verification code
                </label>
                <input
                  id="auth-code"
                  className="input text-center font-mono text-lg tracking-[0.5em]"
                  value={code}
                  onChange={(e) => onCodeChange(e.target.value)}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={CODE_LENGTH}
                  placeholder="000000"
                  aria-label="6-digit verification code"
                  autoFocus
                />
              </div>
              {errorBlock}
              <button
                type="submit"
                className="btn-primary w-full"
                disabled={busy || code.length !== CODE_LENGTH || needsNewCode}
              >
                {busy ? "Verifying..." : "Verify and create account"}
              </button>
              <div className="flex items-center justify-between gap-3 text-xs">
                <button type="button" className="link font-medium" onClick={backToDetails}>
                  Back
                </button>
                {needsNewCode ? (
                  <button
                    type="button"
                    className="link font-medium"
                    onClick={() => {
                      if (resendIn > 0) {
                        backToDetails();
                        return;
                      }
                      void sendCode();
                    }}
                    disabled={busy}
                  >
                    Request a new code
                  </button>
                ) : (
                  <button
                    type="button"
                    className={clsx(
                      "font-medium",
                      resendIn > 0 || busy ? "cursor-not-allowed text-muted" : "link",
                    )}
                    onClick={() => void sendCode()}
                    disabled={resendIn > 0 || busy}
                  >
                    {resendIn > 0 ? `Resend in ${resendIn}s` : "Resend code"}
                  </button>
                )}
              </div>
            </form>
          ) : (
            <>
              <ProviderButtons providers={providers} redirectTo={target} />
              <form onSubmit={submitDetails} className="card space-y-4 p-6" noValidate>
                {mode === "login" ? (
                  <div>
                    <label htmlFor="auth-identifier" className="label">
                      Email or username
                    </label>
                    <input
                      id="auth-identifier"
                      className="input"
                      value={identifier}
                      onChange={(e) => setIdentifier(e.target.value)}
                      placeholder="you@example.com"
                      autoComplete="username"
                      autoFocus
                    />
                  </div>
                ) : (
                  <>
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
                        autoFocus
                      />
                    </div>
                    <div>
                      <label htmlFor="auth-email" className="label">
                        Email
                      </label>
                      <input
                        id="auth-email"
                        type="email"
                        className="input"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="you@example.com"
                        autoComplete="email"
                        required
                      />
                      {otpRequired && (
                        <p className="mt-1 text-[11px] text-muted/90">
                          This server verifies new accounts by email.
                        </p>
                      )}
                    </div>
                  </>
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
                {errorBlock}
                <button type="submit" className="btn-primary w-full" disabled={busy}>
                  {busy
                    ? mode === "login"
                      ? "Signing in..."
                      : "Working..."
                    : mode === "login"
                      ? "Sign in"
                      : otpRequired
                        ? "Send verification code"
                        : "Create account"}
                </button>
              </form>
            </>
          )}

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
