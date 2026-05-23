import type { Span } from "../api";

const fmt$ = (v: number) =>
  v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(6)}` : "$0";

interface Props {
  spans: Span[];
  onRowClick: (id: string) => void;
}

export default function TraceFeed({ spans, onRowClick }: Props) {
  if (spans.length === 0) return <div className="empty">No spans yet.</div>;
  return (
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Task</th>
          <th>Model</th>
          <th>Level</th>
          <th>Input</th>
          <th>Output</th>
          <th>Thinking</th>
          <th>Latency</th>
          <th>Cost</th>
        </tr>
      </thead>
      <tbody>
        {spans.slice(0, 30).map((s) => (
          <tr key={s.id} className="clickable" onClick={() => onRowClick(s.id)}>
            <td>{new Date(s.created_at).toLocaleTimeString()}</td>
            <td>{s.task_label ?? "—"}</td>
            <td>{s.model}</td>
            <td><LevelPill level={s.thinking_level_used} /></td>
            <td>{s.input_tokens}</td>
            <td>{s.output_tokens}</td>
            <td>{s.thinking_tokens ?? "—"}</td>
            <td>{s.latency_ms} ms</td>
            <td>{fmt$(s.estimated_cost_usd)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LevelPill({ level }: { level: string }) {
  const color = { minimal: "#3fb950", low: "#58a6ff", medium: "#d29922", high: "#f85149" }[level] ?? "#8b949e";
  return (
    <span style={{
      display: "inline-block",
      padding: "1px 8px",
      borderRadius: 4,
      background: `${color}22`,
      color,
      fontSize: 11,
      fontWeight: 600,
      textTransform: "uppercase",
    }}>{level}</span>
  );
}
