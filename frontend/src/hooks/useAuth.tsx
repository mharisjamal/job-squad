import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiGet, apiSend, clearToken, getToken, setToken } from "../lib/api";
import type { AuthResponse, LoginPayload, RegisterPayload, User } from "../types/api";

type AuthStatus = "loading" | "anon" | "authed";

interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(getToken() ? "loading" : "anon");
  const [user, setUser] = useState<User | null>(null);

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

  const logout = useCallback(() => {
    clearToken();
    localStorage.removeItem("last_group");
    setUser(null);
    setStatus("anon");
  }, []);

  const value = useMemo(
    () => ({ status, user, login, register, logout }),
    [status, user, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
