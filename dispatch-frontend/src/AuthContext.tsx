import { createContext, useContext, useState, useEffect, type ReactNode } from "react";
import { API_BASE } from "./apiConfig";
import type { AuthUser } from "./types";

interface AuthContextType {
  token: string | null;
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("dispatch_token"));
  const [user, setUser] = useState<AuthUser | null>(() => {
    const saved = localStorage.getItem("dispatch_user");
    return saved ? (JSON.parse(saved) as AuthUser) : null;
  });
  const [loading, setLoading] = useState(!!token);

  useEffect(() => {
    if (!token) return;
    fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders(token) })
      .then((res) => {
        if (!res.ok) throw new Error("expired");
        return res.json() as Promise<AuthUser>;
      })
      .then((u) => {
        setUser(u);
        localStorage.setItem("dispatch_user", JSON.stringify(u));
      })
      .catch(() => {
        setToken(null);
        setUser(null);
        localStorage.removeItem("dispatch_token");
        localStorage.removeItem("dispatch_user");
      })
      .finally(() => setLoading(false));
  }, [token]);

  const login = async (email: string, password: string) => {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Login failed" }));
      throw new Error((err as { detail?: string }).detail ?? "Login failed");
    }
    const data = (await res.json()) as { token: string; user: AuthUser };
    localStorage.setItem("dispatch_token", data.token);
    localStorage.setItem("dispatch_user", JSON.stringify(data.user));
    setToken(data.token);
    setUser(data.user);
  };

  const logout = () => {
    localStorage.removeItem("dispatch_token");
    localStorage.removeItem("dispatch_user");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ token, user, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}
