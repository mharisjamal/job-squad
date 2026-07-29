import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { PageSpinner } from "../components/ui/Spinner";
import { POST_AUTH_REDIRECT_KEY } from "../components/ProviderButtons";

const ERROR_MESSAGES: Record<string, string> = {
  email_unverified:
    "That provider did not confirm your email address. Create your account with email instead.",
  access_denied: "Sign-in was cancelled.",
  state_invalid: "That sign-in link expired. Try again.",
  expired: "That sign-in link expired. Try again.",
};

function messageFor(slug: string): string {
  return ERROR_MESSAGES[slug] ?? "Sign-in failed. Try again.";
}

/** Reads and clears the deep link parked before the provider round trip. */
function consumeSavedRedirect(): string | null {
  const saved = sessionStorage.getItem(POST_AUTH_REDIRECT_KEY);
  sessionStorage.removeItem(POST_AUTH_REDIRECT_KEY);
  return saved && saved !== "/auth" ? saved : null;
}

/**
 * OAuth return target. The server sends the session token in the URL FRAGMENT
 * (never the query string), so it is not logged or sent in a Referer header.
 * We read it, strip it from the address bar, then resolve the session.
 *
 * This route is mounted in both the logged-out and logged-in route trees:
 * adopting the token flips the app to "authed" mid-flight, and staying mounted
 * across that switch is what keeps the saved deep link intact.
 */
export default function AuthCallback() {
  const { adoptToken, status } = useAuth();
  const navigate = useNavigate();
  // Captured on first render, before the fragment is stripped.
  const hashRef = useRef(window.location.hash);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const params = new URLSearchParams(hashRef.current.replace(/^#/, ""));
    const token = params.get("token");
    const error = params.get("error");

    const stripFragment = () => {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    };

    if (token) {
      stripFragment();
      adoptToken(token)
        .then(() => navigate(consumeSavedRedirect() ?? "/", { replace: true }))
        .catch(() =>
          navigate("/auth", {
            replace: true,
            state: { authError: "Sign-in failed. Try again." },
          }),
        );
      return;
    }

    if (error) {
      stripFragment();
      consumeSavedRedirect();
      navigate("/auth", { replace: true, state: { authError: messageFor(error) } });
      return;
    }

    // No fragment: either a stale visit, or this instance remounted after the
    // session resolved. Honour the saved deep link when we are already in.
    const saved = consumeSavedRedirect();
    if (status === "authed") navigate(saved ?? "/", { replace: true });
    else navigate("/auth", { replace: true });
  }, [adoptToken, navigate, status]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <PageSpinner label="Signing you in..." />
    </div>
  );
}
