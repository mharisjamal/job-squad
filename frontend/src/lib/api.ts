// Thin fetch wrapper: relative paths only, Bearer auth, 401 -> /auth.

const TOKEN_KEY = "jobsquad_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/**
 * Public credential endpoints where 401 is a normal answer ("wrong password",
 * "wrong code"), not an expired session. These must surface the server's
 * message to the form instead of triggering a sign-out redirect.
 */
const PUBLIC_AUTH_PATHS = [
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/config",
];

function isPublicAuthPath(path: string): boolean {
  const clean = path.split("?")[0];
  return PUBLIC_AUTH_PATHS.some((p) => clean === p || clean.startsWith(`${p}/`));
}

function handleUnauthorized(): void {
  clearToken();
  if (window.location.pathname !== "/auth") {
    window.location.assign("/auth");
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      // FastAPI 422 validation error shape
      const first = data.detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg;
    }
  } catch {
    // fall through to generic message
  }
  return `Request failed (${res.status})`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body != null) headers.set("Content-Type", "application/json");

  const res = await fetch(path, { ...init, headers });

  if (res.status === 401 && !isPublicAuthPath(path)) {
    handleUnauthorized();
    throw new ApiError(401, "Session expired. Please sign in again.");
  }
  if (!res.ok) {
    throw new ApiError(res.status, await parseError(res));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiSend<T>(
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  return request<T>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** Append the access token as a query param (EventSource / <a download> cannot send headers). */
export function sseUrl(path: string): string {
  const token = getToken();
  if (!token) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}access_token=${encodeURIComponent(token)}`;
}

/** Same mechanism, clearer name for CSV export links. */
export function downloadUrl(path: string): string {
  return sseUrl(path);
}
