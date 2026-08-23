import { useState } from "react";

type MessageTab = "unanswered" | "ended";

export default function UnansweredMessagesPage() {
  const [tab, setTab] = useState<MessageTab>("unanswered");
  const headers = tab === "unanswered"
    ? ["Client", "Platform", "Message", "Rep", "Company", "Message Time", "Action"]
    : ["Client", "Platform", "Message", "Rep", "Company", "Message Time"];

  return (
    <main style={{ padding: 24, width: "100%", maxWidth: 1280, margin: "0 auto", boxSizing: "border-box" }}>
      <h1 style={{ margin: 0, color: "#032d60", fontSize: 24 }}>Unanswered Messages</h1>
      <p style={{ margin: "6px 0 20px", color: "#64748b" }}>Monitor client messages waiting for a response.</p>

      <div style={{ display: "flex", gap: 8, borderBottom: "1px solid #d8dde6", marginBottom: 16 }}>
        {([
          ["unanswered", "Unanswered Messages", 0],
          ["ended", "Ended Chats", 0],
        ] as const).map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            style={{
              border: 0,
              borderBottom: tab === key ? "3px solid #0b5cab" : "3px solid transparent",
              background: "transparent",
              color: tab === key ? "#032d60" : "#475569",
              padding: "11px 16px",
              fontWeight: tab === key ? 700 : 500,
              cursor: "pointer",
            }}
          >
            {label} ({count})
          </button>
        ))}
      </div>

      <section style={{ background: "#fff", border: "1px solid #d8dde6", borderRadius: 10, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
          <thead>
            <tr style={{ background: "#f8fafc", borderBottom: "1px solid #d8dde6" }}>
              {headers.map((header) => (
                <th key={header} style={{ padding: "13px 16px", color: "#475569", fontSize: 12, textAlign: "left", textTransform: "uppercase", letterSpacing: "0.03em" }}>
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td colSpan={headers.length} style={{ padding: 32, color: "#64748b", textAlign: "center" }}>
                {tab === "unanswered" ? "No unanswered messages." : "No ended chats."}
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </main>
  );
}
