import { Component, ReactNode } from "react";
import { Link } from "react-router-dom";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div style={{ padding: 32, maxWidth: 640, margin: "40px auto", background: "#fff", borderRadius: 8, border: "1px solid #cbd5e1", boxShadow: "0 4px 12px rgba(0,0,0,0.08)" }}>
          <h2 style={{ color: "#032d60", marginTop: 0 }}>Something went wrong</h2>
          <p style={{ color: "#475569", fontSize: 14 }}>
            An unexpected error occurred while rendering this page.
          </p>
          {this.state.error?.message && (
            <pre style={{ background: "#fef2f2", color: "#991b1b", padding: 12, borderRadius: 6, fontSize: 12, overflowX: "auto" }}>
              {this.state.error.message}
            </pre>
          )}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button className="slds-button"
              type="button"
              onClick={() => window.location.reload()}
              style={{ background: "#0176d3", color: "#fff", border: 0, borderRadius: 4, padding: "8px 16px", fontWeight: 600, cursor: "pointer" }}
            >
              Reload page
            </button>
            <Link
              to="/"
              style={{ display: "inline-flex", alignItems: "center", textDecoration: "none", color: "#0176d3", padding: "8px 16px", fontWeight: 600 }}
            >
              Return to Leads
            </Link>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
