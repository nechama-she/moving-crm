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
  originalAdmin: User | null;
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
  const [originalAdmin, setOriginalAdmin] = useState<User | null>(() => {
    const saved = sessionStorage.getItem("impersonation_admin_user");
    return saved ? JSON.parse(saved) : null;
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
    setToken(null);
    setUser(null);
    setOriginalAdmin(null);
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

    if (!originalAdmin) {
      sessionStorage.setItem("impersonation_admin_token", token);
      sessionStorage.setItem("impersonation_admin_user", JSON.stringify(user));
      setOriginalAdmin(user);
    }
    localStorage.setItem("token", data.token);
    localStorage.setItem("user", JSON.stringify(data.user));
    setToken(data.token);
    setUser(data.user);
  };

  const stopImpersonating = () => {
    const adminToken = sessionStorage.getItem("impersonation_admin_token");
    const savedAdmin = sessionStorage.getItem("impersonation_admin_user");
    if (!adminToken || !savedAdmin) return;
    const adminUser = JSON.parse(savedAdmin) as User;
    localStorage.setItem("token", adminToken);
    localStorage.setItem("user", JSON.stringify(adminUser));
    sessionStorage.removeItem("impersonation_admin_token");
    sessionStorage.removeItem("impersonation_admin_user");
    setToken(adminToken);
    setUser(adminUser);
    setOriginalAdmin(null);
  };

  return (
    <AuthContext.Provider value={{ token, user, login, updateUser, impersonate, stopImpersonating, isImpersonating: Boolean(originalAdmin), originalAdmin, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}
