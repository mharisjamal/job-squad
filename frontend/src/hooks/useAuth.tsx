import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiGet, apiSend, clearToken, getToken, setToken } from "../lib/api";
import type {
  AuthConfig,
  AuthResponse,
  LoginPayload,
  OAuthProvider,
  RegisterPayload,
  RegisterStartRequest,
  RegisterStartResponse,
  User,
} from "../types/api";

type AuthStatus = "loading" | "anon" | "authed";

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  /** True when this server requires email verification to sign up. */
  otpRequired: boolean;
  /** OAuth providers configured on this server; empty means no social buttons. */
  providers: OAuthProvider[];
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  startRegistration: (payload: RegisterStartRequest) => Promise<RegisterStartResponse>;
  verifyRegistration: (email: string, code: string) => Promise<void>;
  /** Adopts a token handed back by the OAuth callback and resolves the session. */
  adoptToken: (token: string) => Promise<void>;
  logout: () => void;
}

const KNOWN_PROVIDERS: OAuthProvider[] = ["google", "github", "linkedin"];

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(getToken() ? "loading" : "anon");
  const [user, setUser] = useState<User | null>(null);
  const [otpRequired, setOtpRequired] = useState(false);
  const [providers, setProviders] = useState<OAuthProvider[]>([]);

  useEffect(() => {
    let cancelled = false;
    if (!getToken()) return;
    apiGet<User>("/api/auth/me")
      .then((u) => {
        if (cancelled) return;
        setUser(u);
        setStatus("authed");
      })
      .catch(() => {
        if (cancelled) return;
        // 401 already cleared the token via the api layer; anything else
        // (backend down) also lands on the auth screen rather than a dead app.
        setUser(null);
        setStatus("anon");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Public probe: works logged out, and on an older server that lacks the
  // route we fall back to open registration with no social buttons.
  useEffect(() => {
    let cancelled = false;
    apiGet<AuthConfig>("/api/auth/config")
      .then((cfg) => {
        if (cancelled) return;
        setOtpRequired(Boolean(cfg.otp_required));
        // Render only providers we have a button for, in a stable order.
        const offered = Array.isArray(cfg.providers) ? cfg.providers : [];
        setProviders(KNOWN_PROVIDERS.filter((p) => offered.includes(p)));
      })
      .catch(() => {
        if (cancelled) return;
        setOtpRequired(false);
        setProviders([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const acceptAuth = useCallback((res: AuthResponse) => {
    setToken(res.token);
    setUser(res.user);
    setStatus("authed");
  }, []);

  const login = useCallback(
    async (payload: LoginPayload) => {
      acceptAuth(await apiSend<AuthResponse>("POST", "/api/auth/login", payload));
    },
    [acceptAuth],
  );

  const register = useCallback(
    async (payload: RegisterPayload) => {
      acceptAuth(await apiSend<AuthResponse>("POST", "/api/auth/register", payload));
    },
    [acceptAuth],
  );

  const startRegistration = useCallback(
    (payload: RegisterStartRequest) =>
      apiSend<RegisterStartResponse>("POST", "/api/auth/register/start", payload),
    [],
  );

  const verifyRegistration = useCallback(
    async (email: string, code: string) => {
      acceptAuth(
        await apiSend<AuthResponse>("POST", "/api/auth/register/verify", { email, code }),
      );
    },
    [acceptAuth],
  );

  const adoptToken = useCallback(async (token: string) => {
    setToken(token);
    try {
      const u = await apiGet<User>("/api/auth/me");
      setUser(u);
      setStatus("authed");
    } catch (err) {
      clearToken();
      setUser(null);
      setStatus("anon");
      throw err;
    }
  }, []);

  const logout = useCallback(() => {
    clearToken();
    localStorage.removeItem("last_group");
    setUser(null);
    setStatus("anon");
  }, []);

  const value = useMemo(
    () => ({
      status,
      user,
      otpRequired,
      providers,
      login,
      register,
      startRegistration,
      verifyRegistration,
      adoptToken,
      logout,
    }),
    [
      status,
      user,
      otpRequired,
      providers,
      login,
      register,
      startRegistration,
      verifyRegistration,
      adoptToken,
      logout,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
