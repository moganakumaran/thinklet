import type { SpanDetail, ThinkingLevel } from "../api";

const fmt$ = (v: number) =>
  v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(6)}` : "$0";

const LEVEL_RANK: Record<string, number> = {
  minimal: 0, low: 1, medium: 2, high: 3,
};

const VERDICT_LABEL: Record<string, string> = {
  equivalent: "equivalent",
  degraded: "degraded",
  materially_different: "materially diff.",
  uncertain: "uncertain",
};

const VERDICT_COLOR: Record<string, string> = {
  equivalent: "var(--green)",
  degraded: "var(--red)",
  materially_different: "var(--red)",
  uncertain: "var(--yellow)",
};

function LevelPill({ level }: { level: ThinkingLevel }) {
  const color =
    { minimal: "#3fb950", low: "#58a6ff", medium: "#d29922", high: "#f85149" }[level] ??
    "#8b949e";
  return (
    <span
      style={{
        display: "inline-block",
        padding: "1px 8px",
        borderRadius: 4,
        background: `${color}22`,
        color,
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase",
      }}
    >
      {level}
    </span>
  );
}

export default function AuditDAG({ detail }: { detail: SpanDetail }) {
  const { span, replays, judges } = detail;

  // For each judge, find its matching replay so we can render side-by-side.
  const rows = judges
    .slice()
    .sort(
      (a, b) =>
        LEVEL_RANK[a.alternative_level] - LEVEL_RANK[b.alternative_level]
    )
    .map((j) => {
      const replay = replays.find((r) => r.id === j.replay_result_id);
      return { judge: j, replay };
    });

  // Pick the "best" downgrade for the recommendation node: lowest-level
  // equivalent verdict with positive savings.
  const equivalents = rows
    .filter((r) => r.judge.verdict === "equivalent" && r.judge.estimated_savings_usd > 0)
    .sort(
      (a, b) =>
        LEVEL_RANK[a.judge.alternative_level] -
        LEVEL_RANK[b.judge.alternative_level]
    );
  const best = equivalents[0] ?? null;

  return (
    <div className="audit-dag">
      {/* COLUMN 1: original */}
      <div className="dag-col">
        <div className="dag-col-title">Original</div>
        <div className="dag-node dag-node-original" title={span.response_redacted ?? ""}>
          <LevelPill level={span.thinking_level_used} />
          <div className="dag-node-stat">
            <span>thinking</span>
            <strong>{span.thinking_tokens ?? "—"}</strong>
          </div>
          <div className="dag-node-stat">
            <span>cost</span>
            <strong>{fmt$(span.estimated_cost_usd)}</strong>
          </div>
          <div className="dag-node-stat">
            <span>latency</span>
            <strong>{span.latency_ms} ms</strong>
          </div>
          <div className="dag-node-resp" title={span.response_redacted ?? ""}>
            {(span.response_redacted ?? "").slice(0, 90) || "—"}
          </div>
        </div>
      </div>

      {/* COLUMN 2: replays */}
      <div className="dag-col">
        <div className="dag-col-title">Replays</div>
        {rows.length === 0 ? (
          <div className="dag-empty">no replays yet</div>
        ) : (
          rows.map(({ replay, judge }) =>
            replay ? (
              <div
                className="dag-node dag-node-replay"
                key={replay.id}
                title={replay.response_redacted ?? ""}
              >
                <LevelPill level={replay.target_thinking_level} />
                <div className="dag-node-stat">
                  <span>thinking</span>
                  <strong>{replay.thinking_tokens ?? "—"}</strong>
                </div>
                <div className="dag-node-stat">
                  <span>cost</span>
                  <strong>{fmt$(replay.estimated_cost_usd)}</strong>
                </div>
                <div className="dag-node-stat">
                  <span>latency</span>
                  <strong>{replay.latency_ms} ms</strong>
                </div>
                <div className="dag-node-resp" title={replay.response_redacted ?? ""}>
                  {(replay.response_redacted ?? "").slice(0, 90) || "—"}
                </div>
              </div>
            ) : (
              <div className="dag-node dag-node-replay" key={judge.id}>
                <LevelPill level={judge.alternative_level} />
                <div className="dag-empty" style={{ marginTop: 6 }}>
                  no replay result
                </div>
              </div>
            )
          )
        )}
      </div>

      {/* COLUMN 3: judges */}
      <div className="dag-col">
        <div className="dag-col-title">Judge</div>
        {rows.length === 0 ? (
          <div className="dag-empty">—</div>
        ) : (
          rows.map(({ judge }) => (
            <div className="dag-node dag-node-judge" key={judge.id}>
              <div
                className="dag-verdict-pill"
                style={{
                  background: `${VERDICT_COLOR[judge.verdict]}22`,
                  color: VERDICT_COLOR[judge.verdict],
                  borderColor: `${VERDICT_COLOR[judge.verdict]}55`,
                }}
              >
                {VERDICT_LABEL[judge.verdict] ?? judge.verdict}
              </div>
              <div className="dag-node-stat">
                <span>conf</span>
                <strong>{Math.round(judge.confidence * 100)}%</strong>
              </div>
              {judge.estimated_savings_usd > 0 && (
                <div className="dag-node-stat" style={{ color: "var(--red)" }}>
                  <span>save</span>
                  <strong>{fmt$(judge.estimated_savings_usd)}</strong>
                </div>
              )}
              {judge.reasoning && (
                <div
                  className="dag-node-resp"
                  title={judge.reasoning}
                  style={{ fontStyle: "italic" }}
                >
                  {judge.reasoning.slice(0, 80)}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* COLUMN 4: recommendation */}
      <div className="dag-col">
        <div className="dag-col-title">Recommendation</div>
        {best ? (
          <div className="dag-node dag-node-recommend">
            <div className="dag-recommend-label">downgrade to</div>
            <LevelPill level={best.judge.alternative_level} />
            <div className="dag-recommend-savings">
              save {fmt$(best.judge.estimated_savings_usd)} / call
            </div>
            <div className="dag-recommend-sub">
              orig was{" "}
              <LevelPill level={span.thinking_level_used} />
            </div>
          </div>
        ) : (
          <div className="dag-node dag-node-recommend">
            <div className="dag-recommend-label">keep as-is</div>
            <LevelPill level={span.thinking_level_used} />
            <div className="dag-recommend-sub">
              no lower level was equivalent
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
