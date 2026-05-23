export type LogKind = "info" | "running" | "ok" | "error";

export interface LogLine {
  ts: string;            // "HH:MM:SS"
  kind: LogKind;
  text: string;
}

const ICONS: Record<LogKind, string> = {
  info: "•",
  running: "⋯",
  ok: "✓",
  error: "✗",
};

const COLORS: Record<LogKind, string> = {
  info: "var(--muted)",
  running: "var(--accent)",
  ok: "var(--green)",
  error: "var(--red)",
};

export default function AuditProgressLog({ lines }: { lines: LogLine[] }) {
  if (lines.length === 0) return null;
  return (
    <div className="audit-log">
      {lines.map((l, i) => (
        <div key={i} className="audit-log-row">
          <span className="audit-log-ts">{l.ts}</span>
          <span
            className="audit-log-icon"
            style={{ color: COLORS[l.kind] }}
          >
            {l.kind === "running" ? (
              <span className="audit-log-spinner">⋯</span>
            ) : (
              ICONS[l.kind]
            )}
          </span>
          <span className="audit-log-text">{l.text}</span>
        </div>
      ))}
    </div>
  );
}
