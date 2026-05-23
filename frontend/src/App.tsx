import { useCallback, useEffect, useState } from "react";
import "./index.css";
import { api, type Health, type Span, type WasteMapCell, type WasteReport } from "./api";
import WasteReportView from "./components/WasteReport";
import WasteMap from "./components/WasteMap";
import TraceFeed from "./components/TraceFeed";
import SpanDrawer from "./components/SpanDrawer";
import TryThinklet from "./components/TryThinklet";
import CopyPolicyButton from "./components/CopyPolicyButton";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [report, setReport] = useState<WasteReport | null>(null);
  const [cells, setCells] = useState<WasteMapCell[] | null>(null);
  const [spans, setSpans] = useState<Span[] | null>(null);
  const [openSpanId, setOpenSpanId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refetchAll = useCallback(() => {
    Promise.all([api.health(), api.wasteReport(), api.wasteMap(), api.spans(50)])
      .then(([h, r, m, s]) => {
        setHealth(h); setReport(r); setCells(m); setSpans(s);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    refetchAll();
  }, [refetchAll]);

  const demoMode = report?.demo_mode ?? health?.demo_mode ?? false;

  const onCellClick = (cell: WasteMapCell) => {
    const match = spans?.find(
      (s) => (s.task_label ?? "(unlabeled)") === cell.task_label
        && s.prompt_hash === cell.prompt_hash
        && s.thinking_level_used === cell.original_level
    );
    if (match) setOpenSpanId(match.id);
  };

  if (error) return <div className="app-shell"><div className="empty">Error: {error}</div></div>;

  return (
    <div className="app-shell">
      <div className="app-header">
        <div>
          <h1>
            Thinklet
            <span className="tagline">tells you when your agent thought too hard.</span>
          </h1>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {demoMode && <span className="demo-badge">Demo Mode</span>}
          <CopyPolicyButton />
          <a
            href={api.policyUrl("python")}
            target="_blank"
            rel="noopener noreferrer"
            className="export-policy-btn"
            title="Open the THINKING_POLICY Python dict in a new tab"
          >
            Open policy ↗
          </a>
        </div>
      </div>

      <TryThinklet onAuditComplete={refetchAll} />

      {report ? (
        <WasteReportView report={report} />
      ) : (
        <div className="section loading">Loading waste report…</div>
      )}

      <div className="section">
        <h2>Waste Map</h2>
        {cells ? <WasteMap cells={cells} onCellClick={onCellClick} />
               : <div className="loading">Loading…</div>}
      </div>

      <div className="section">
        <h2>Recent calls</h2>
        {spans ? <TraceFeed spans={spans} onRowClick={setOpenSpanId} />
               : <div className="loading">Loading…</div>}
      </div>

      {openSpanId && (
        <SpanDrawer spanId={openSpanId} onClose={() => setOpenSpanId(null)} />
      )}
    </div>
  );
}
