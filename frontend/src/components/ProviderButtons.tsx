import type { OAuthProvider } from "../types/api";

/** Where the deep link is parked across the full-page OAuth round trip. */
export const POST_AUTH_REDIRECT_KEY = "post_auth_redirect";

function GoogleMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 48 48" aria-hidden focusable="false">
      <path
        fill="#4285F4"
        d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.69 28.18C11.25 26.86 11 25.45 11 24s.25-2.86.69-4.18v-5.7H4.34C2.85 17.09 2 20.45 2 24s.85 6.91 2.34 9.88l7.35-5.7z"
      />
      <path
        fill="#EA4335"
        d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"
      />
    </svg>
  );
}

function GitHubMark() {
  // currentColor so the mark flips with the theme (ink on both).
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden focusable="false">
      <path
        fill="currentColor"
        d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z"
      />
    </svg>
  );
}

function LinkedInMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden focusable="false">
      <path
        fill="#0A66C2"
        d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.63-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.45v6.29zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z"
      />
    </svg>
  );
}

const PROVIDER_META: Record<OAuthProvider, { label: string; mark: () => JSX.Element }> = {
  google: { label: "Google", mark: GoogleMark },
  github: { label: "GitHub", mark: GitHubMark },
  linkedin: { label: "LinkedIn", mark: LinkedInMark },
};

/**
 * Social sign-in buttons plus an "or" divider. Renders nothing (no divider)
 * when the server has no providers configured.
 */
export function ProviderButtons({
  providers,
  redirectTo,
}: {
  providers: OAuthProvider[];
  redirectTo?: string;
}) {
  if (providers.length === 0) return null;

  const go = (provider: OAuthProvider) => {
    // The provider round trip is a full page navigation, so the deep link
    // cannot ride in router state. Park it for /auth/callback to pick up.
    if (redirectTo) sessionStorage.setItem(POST_AUTH_REDIRECT_KEY, redirectTo);
    else sessionStorage.removeItem(POST_AUTH_REDIRECT_KEY);
    window.location.assign(`/api/auth/oauth/${provider}/start`);
  };

  return (
    <div className="mb-5">
      <div className="space-y-2">
        {providers.map((p) => {
          const meta = PROVIDER_META[p];
          const Mark = meta.mark;
          return (
            <button
              key={p}
              type="button"
              onClick={() => go(p)}
              className="flex h-9 w-full items-center justify-center gap-2.5 rounded-md border border-line bg-paper px-3.5 text-sm font-medium text-ink transition-colors duration-150 ease-out hover:bg-canvas"
            >
              <Mark />
              Continue with {meta.label}
            </button>
          );
        })}
      </div>
      <div className="mt-5 flex items-center gap-3" aria-hidden>
        <span className="h-px flex-1 bg-line" />
        <span className="text-xs text-muted">or</span>
        <span className="h-px flex-1 bg-line" />
      </div>
    </div>
  );
}
