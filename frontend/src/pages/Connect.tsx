import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowLeft, CheckCircle2, Puzzle, ShieldCheck, Trash2 } from "lucide-react";
import {
  revokeSupersededToken,
  useCreateExtensionToken,
  useExtensionTokens,
  useRevokeExtensionToken,
} from "../hooks/useExtension";
import { useToast } from "../components/ui/Toast";
import { ConfirmDialog } from "../components/ui/Dialog";
import { EmptyState, ErrorState } from "../components/ui/EmptyState";
import { Skeleton, Spinner } from "../components/ui/Spinner";
import { ApiError } from "../lib/api";
import { formatDate, timeAgo } from "../lib/format";
import type { ExtensionToken } from "../types/api";

/** How long we wait for the extension's `paired` reply before giving up. */
const PAIR_TIMEOUT_MS = 3000;

/** Server cap we stay well inside; the label is only ever a human hint. */
const LABEL_MAX = 60;

/** Shown when the user agent tells us nothing useful. */
const LABEL_FALLBACK = "Browser extension";

type Phase = "idle" | "connecting" | "connected" | "not-installed" | "error";

function errMsg(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/**
 * A short, human name for the connection so the list is not a row of
 * identical dates: "Chrome on Windows", "Safari on macOS". Browser and OS
 * family only, deliberately nothing more identifying than that, and it is a
 * display hint rather than anything the server trusts.
 */
function deviceLabel(userAgent: string): string {
  const ua = userAgent;
  // Order matters: every Chromium browser also claims Chrome and Safari.
  const browser =
    /Edg\/|EdgiOS\//.test(ua) ? "Edge"
    : /OPR\/|OPiOS\/|Opera/.test(ua) ? "Opera"
    : /Firefox\/|FxiOS\//.test(ua) ? "Firefox"
    : /Chrome\/|CriOS\//.test(ua) ? "Chrome"
    : /Safari\//.test(ua) ? "Safari"
    : null;
  const os =
    /Windows/.test(ua) ? "Windows"
    : /Macintosh|Mac OS X/.test(ua) ? "macOS"
    : /CrOS/.test(ua) ? "ChromeOS"
    : /Android/.test(ua) ? "Android"
    : /iPhone|iPad|iPod/.test(ua) ? "iOS"
    : /Linux/.test(ua) ? "Linux"
    : null;

  if (browser && os) return `${browser} on ${os}`.slice(0, LABEL_MAX);
  if (browser) return browser;
  if (os) return `Browser on ${os}`.slice(0, LABEL_MAX);
  return LABEL_FALLBACK;
}

export default function Connect() {
  const tokens = useExtensionTokens();
  const createToken = useCreateExtensionToken();
  const revokeToken = useRevokeExtensionToken();
  const { toast } = useToast();

  // Stable across renders (TanStack Query binds it to the observer), so the
  // message listener can depend on it without re-subscribing every render.
  const refetchTokens = tokens.refetch;

  const [phase, setPhase] = useState<Phase>("idle");
  const [pairError, setPairError] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<ExtensionToken | null>(null);
  const timerRef = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // The extension's content script answers on the same window. Accept the
  // reply only when it really came from this page's own window and origin,
  // and only in our message shape; anything else is ignored silently.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window) return;
      if (event.origin !== window.location.origin) return;
      const data = event.data as
        | { source?: unknown; type?: unknown; previous_token_id?: unknown }
        | null;
      if (data == null || typeof data !== "object") return;
      if (data.source !== "jobsquad-extension" || data.type !== "paired") return;
      clearTimer();
      setPairError(null);
      setPhase("connected");

      // The extension reports the connection this one replaced (a retry, or a
      // re-pair of the same browser). Clean it up so the list stays readable.
      // Connected is already true: this never blocks or reverses it.
      const previous = data.previous_token_id;
      if (typeof previous === "number" && Number.isFinite(previous)) {
        void revokeSupersededToken(previous).then(() => void refetchTokens());
      } else {
        void refetchTokens();
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [clearTimer, refetchTokens]);

  useEffect(() => clearTimer, [clearTimer]);

  const startPairing = async () => {
    clearTimer();
    setPairError(null);
    setPhase("connecting");

    let token: string;
    let tokenId: number;
    try {
      // The value lives in this local only. It is posted to the extension and
      // then dropped: never stored in state, never rendered, never logged.
      const created = await createToken.mutateAsync(deviceLabel(navigator.userAgent));
      token = created.token;
      tokenId = created.id;
    } catch (err) {
      setPhase("error");
      setPairError(errMsg(err, "Couldn't create a connection. Retry."));
      return;
    }

    const origin = window.location.origin;
    window.postMessage(
      {
        source: "jobsquad-app",
        type: "extension-token",
        token,
        token_id: tokenId,
        api_base: origin,
      },
      origin,
    );
    // Drop the mutation's cached result so the token stops being reachable.
    createToken.reset();

    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setPhase("not-installed");
      // The token exists whether or not the extension answered, so show it in
      // the list where the user can revoke it.
      void refetchTokens();
    }, PAIR_TIMEOUT_MS);
  };

  const confirmRevoke = () => {
    if (!confirmTarget) return;
    revokeToken.mutate(confirmTarget.id, {
      onSuccess: () => {
        setConfirmTarget(null);
        toast("Extension revoked");
      },
      onError: (err) => {
        setConfirmTarget(null);
        toast(errMsg(err, "Couldn't revoke that extension. Retry."), "error");
      },
    });
  };

  const busy = phase === "connecting";

  return (
    <div className="mx-auto min-h-screen w-full max-w-3xl p-6">
      <header className="mb-10 flex items-center justify-between gap-4">
        <Link to="/" className="text-xl font-semibold tracking-tight text-ink">
          JobSquad
        </Link>
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors duration-150 ease-out hover:text-ink"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to your groups
        </Link>
      </header>

      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-ink">
          <Puzzle className="h-5 w-5 text-muted" aria-hidden />
          Browser extension
        </h1>
        <p className="mt-1 text-sm text-muted">
          Capture a job posting from any page into your squad's board, without retyping it.
        </p>
      </div>

      <section className="card mb-5 p-5">
        <h2 className="text-sm font-semibold text-ink">What it does</h2>
        <ul className="mt-3 space-y-2 text-sm text-muted">
          <li>
            Reads the job page you are already looking at and fills in the company, title, location
            and posting link.
          </li>
          <li>
            Shows you the extracted fields first. Nothing is saved until you check them and click
            save.
          </li>
          <li>
            Tells you whether someone in your squad already applied there, before you add it.
          </li>
        </ul>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button className="btn-primary" onClick={() => void startPairing()} disabled={busy}>
            {busy ? "Connecting..." : phase === "idle" ? "Connect extension" : "Connect again"}
          </button>
          {phase === "idle" && (
            <p className="text-small text-muted">
              Install the extension first, then connect it from this page.
            </p>
          )}
        </div>

        {phase === "connecting" && (
          <div
            role="status"
            className="mt-4 flex items-center gap-2.5 rounded-md border border-line bg-canvas p-3 text-sm text-ink"
          >
            <Spinner className="h-4 w-4" />
            Waiting for the extension to answer...
          </div>
        )}

        {phase === "connected" && (
          <div
            role="status"
            className="mt-4 flex items-start gap-2.5 rounded-md border border-line bg-canvas p-3 text-sm"
          >
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-status-offer-text" aria-hidden />
            <span className="text-ink">
              Extension connected. Open a job posting and use the extension button, or press
              Ctrl+Shift+J, to capture it.
            </span>
          </div>
        )}

        {phase === "not-installed" && (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2.5 rounded-md border border-line bg-canvas p-3 text-sm"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
            <div className="space-y-1">
              <p className="text-ink">
                We could not reach the extension. Make sure it is installed and enabled, then try
                again.
              </p>
              <p className="text-muted">
                This attempt already created a connection. If you are not going to use it, revoke it
                in the list below.
              </p>
              <button className="btn-ghost mt-2" onClick={() => void startPairing()}>
                Retry
              </button>
            </div>
          </div>
        )}

        {phase === "error" && (
          <div
            role="alert"
            className="mt-4 flex items-start gap-2.5 rounded-md border border-line bg-canvas p-3 text-sm"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
            <div className="space-y-1">
              <p className="text-danger">{pairError}</p>
              <button className="btn-ghost mt-2" onClick={() => void startPairing()}>
                Retry
              </button>
            </div>
          </div>
        )}

        <p className="mt-4 flex items-start gap-1.5 text-[11px] leading-relaxed text-muted">
          <ShieldCheck className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
          The connection is handed to the extension directly and is never shown on this page. Revoke
          it any time below.
        </p>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-ink">Connected extensions</h2>

        {tokens.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : tokens.isError ? (
          <ErrorState
            message="Couldn't load your connected extensions. Retry."
            onRetry={() => void tokens.refetch()}
          />
        ) : tokens.data.length === 0 ? (
          <EmptyState
            icon={Puzzle}
            title="No extensions connected"
            description="Once you connect a browser, it shows up here with when it last saved a job."
          />
        ) : (
          <ul className="card divide-y divide-line">
            {tokens.data.map((t) => (
              <li
                key={t.id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">
                    {t.label ?? "Browser extension"}
                  </p>
                  <p className="font-mono text-[11px] text-muted">
                    Connected {formatDate(t.created_at)}
                    {" - "}
                    {t.last_used_at ? `last used ${timeAgo(t.last_used_at)}` : "not used yet"}
                  </p>
                </div>
                <button
                  className="btn-ghost shrink-0"
                  onClick={() => setConfirmTarget(t)}
                  aria-label={`Revoke ${t.label ?? "browser extension"}`}
                >
                  <Trash2 className="h-4 w-4 text-muted" aria-hidden />
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={confirmTarget !== null}
        onClose={() => setConfirmTarget(null)}
        onConfirm={confirmRevoke}
        title="Revoke this extension?"
        message="It will stop being able to add jobs until you connect it again."
        confirmLabel="Revoke"
        busy={revokeToken.isPending}
      />
    </div>
  );
}
