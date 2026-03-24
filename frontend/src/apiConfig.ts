declare global {
  interface Window {
    __API_URL__?: string;
  }
}

export const API_BASE = window.__API_URL__ || '';
