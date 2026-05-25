declare global {
  interface Window {
    __DISPATCH_API_BASE__?: string;
  }
}

export const API_BASE: string =
  window.__DISPATCH_API_BASE__ ??
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  "http://localhost:8001";
