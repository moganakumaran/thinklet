import type { WasteMapCell } from "../api";

const fmt$ = (v: number) =>
  v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(4)}` : "$0";

interface Props {
  cells: WasteMapCell[];
  onCellClick: (cell: WasteMapCell) => void;
}

const verdictLabel: Record<string, string> = {
  equivalent: "Likely waste",
  materially_different: "Quality risk",
  uncertain: "Uncertain",
  degraded: "Thinking justified",
};

export default function WasteMap({ cells, onCellClick }: Props) {
  if (cells.length === 0) return <div className="empty">No groups yet.</div>;
  return (
    <div className="map-grid">
      {cells.map((c) => (
        <div
          key={`${c.task_label}-${c.prompt_hash}`}
          className={`map-cell ${c.color}`}
          onClick={() => onCellClick(c)}
        >
          <h3>{c.task_label}</h3>
          <div className="sub">
            {verdictLabel[c.verdict] ?? c.verdict} · {c.span_count} calls
          </div>
          <div className="sub">
            {c.original_level}{c.recommended_level ? ` → ${c.recommended_level}` : ""}
          </div>
          {c.equivalent_sample_count > 0 && (
            <div className="confidence-badge" title={`${(c.equivalent_rate * 100).toFixed(0)}% of audited samples had a safe downgrade`}>
              {c.equivalent_sample_count}/{c.span_count} equivalent
            </div>
          )}
          <div className="savings" style={{ color: c.color === "red" ? "var(--red)" : "var(--muted)" }}>
            {c.estimated_savings_usd > 0 ? fmt$(c.estimated_savings_usd) : "—"}
          </div>
        </div>
      ))}
    </div>
  );
}
