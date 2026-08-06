import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { API_BASE } from "./apiConfig";

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  must_change_password?: boolean;
}

interface AuthContextType {
  token: string | null;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  updateUser: (user: User) => void;
  impersonate: (userId: string) => Promise<void>;
  stopImpersonating: () => void;
  isImpersonating: boolean;
  previousUser: User | null;
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
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("token"));
  const [user, setUser] = useState<User | null>(() => {
    const saved = localStorage.getItem("user");
    return saved ? JSON.parse(saved) : null;
  });
  const [loading, setLoading] = useState(!!token);
  const [impersonationStack, setImpersonationStack] = useState<Array<{ token: string; user: User }>>(() => {
    const saved = sessionStorage.getItem("impersonation_session_stack");
    if (saved) return JSON.parse(saved);
    const legacyToken = sessionStorage.getItem("impersonation_admin_token");
    const legacyUser = sessionStorage.getItem("impersonation_admin_user");
    return legacyToken && legacyUser ? [{ token: legacyToken, user: JSON.parse(legacyUser) }] : [];
  });

  useEffect(() => {
    if (!token) return;
    fetch(`${API_BASE}/api/auth/me`, { headers: authHeaders(token) })
      .then((res) => {
        if (!res.ok) throw new Error("expired");
        return res.json();
      })
      .then((u) => {
        setUser(u);
        localStorage.setItem("user", JSON.stringify(u));
      })
      .catch(() => {
        setToken(null);
        setUser(null);
        localStorage.removeItem("token");
        localStorage.removeItem("user");
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
      throw new Error(err.detail || "Login failed");
    }
    const data = await res.json();
    localStorage.setItem("token", data.token);
    localStorage.setItem("user", JSON.stringify(data.user));
    setToken(data.token);
    setUser(data.user);
  };

  const logout = () => {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    sessionStorage.removeItem("impersonation_admin_token");
    sessionStorage.removeItem("impersonation_admin_user");
    sessionStorage.removeItem("impersonation_session_stack");
    setToken(null);
    setUser(null);
    setImpersonationStack([]);
  };

  const updateUser = (updatedUser: User) => {
    localStorage.setItem("user", JSON.stringify(updatedUser));
    setUser(updatedUser);
  };

  const impersonate = async (userId: string) => {
    if (!token || !user || !["admin", "dispatch"].includes(user.role)) throw new Error("Impersonation access required");
    const response = await fetch(`${API_BASE}/api/auth/impersonate/${userId}`, {
      method: "POST",
      headers: authHeaders(token),
    });
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.detail || "Failed to impersonate user");

    const nextStack = [...impersonationStack, { token, user }];
    sessionStorage.setItem("impersonation_session_stack", JSON.stringify(nextStack));
    sessionStorage.removeItem("impersonation_admin_token");
    sessionStorage.removeItem("impersonation_admin_user");
    setImpersonationStack(nextStack);
    localStorage.setItem("token", data.token);
    localStorage.setItem("user", JSON.stringify(data.user));
    setToken(data.token);
    setUser(data.user);
  };

  const stopImpersonating = () => {
    if (!impersonationStack.length) return;
    const previousSession = impersonationStack[impersonationStack.length - 1];
    const nextStack = impersonationStack.slice(0, -1);
    localStorage.setItem("token", previousSession.token);
    localStorage.setItem("user", JSON.stringify(previousSession.user));
    if (nextStack.length) sessionStorage.setItem("impersonation_session_stack", JSON.stringify(nextStack));
    else sessionStorage.removeItem("impersonation_session_stack");
    setToken(previousSession.token);
    setUser(previousSession.user);
    setImpersonationStack(nextStack);
  };

  const previousUser = impersonationStack.length ? impersonationStack[impersonationStack.length - 1].user : null;

  return (
    <AuthContext.Provider value={{ token, user, login, updateUser, impersonate, stopImpersonating, isImpersonating: impersonationStack.length > 0, previousUser, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}
