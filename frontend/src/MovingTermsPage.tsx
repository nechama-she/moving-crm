import { Link } from "react-router-dom";
import CustomerQuestionManager from "./CustomerQuestionManager";

export default function MovingTermsPage() {
  return (
    <main style={{ padding: "20px clamp(12px, 3vw, 24px)", overflow: "auto", flex: 1, minHeight: 0 }}>
      <Link to="/settings" className="slds-button" style={{ marginBottom: 16 }}>Back to Settings</Link>
      <CustomerQuestionManager />
    </main>
  );
}
