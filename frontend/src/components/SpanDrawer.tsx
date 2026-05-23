import { useEffect, useState } from "react";
import { api, type CellHistory, type SpanDetail } from "../api";

const fmt$ = (v: number) =>
  v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(6)}` : "$0";

const levelRank: Record<string, number> = { minimal: 0, low: 1, medium: 2, high: 3 };

export default function SpanDrawer({ spanId, onClose }: { spanId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<SpanDetail | null>(null);
  const [history, setHistory] = useState<CellHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setHistory(null);
    api.spanDetail(spanId)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
        // Fetch run history for this cell so we can show "5/5 equivalent"
        // and a list of sibling audits.
        const label = d.span.task_label ?? "(unlabeled)";
        api.cellHistory({
          task_label: label,
          prompt_hash: d.span.prompt_hash,
          original_level: d.span.thinking_level_used,
        })
          .then((h) => alive && setHistory(h))
          .catch(() => {/* history is optional */});
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, [spanId]);

  // Pick the "best" judge for the drill-down: lowest-level equivalent, or
  // highest-confidence non-uncertain, or just the first.
  let bestJudge = null;
  let bestReplay = null;
  if (detail) {
    const equiv = detail.judges
      .filter(j => j.verdict === "equivalent")
      .sort((a, b) => levelRank[a.alternative_level] - levelRank[b.alternative_level]);
    bestJudge = equiv[0]
      ?? detail.judges.find(j => j.verdict !== "uncertain")
      ?? detail.judges[0]
      ?? null;
    bestReplay = bestJudge
      ? detail.replays.find(r => r.id === bestJudge!.replay_result_id) ?? null
      : null;
  }

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <div className="drawer">
        <button onClick={onClose} style={{ float: "right" }}>Close</button>
        <h2>Call detail</h2>
        {error && <div className="empty">Error: {error}</div>}
        {!detail && !error && <div className="loading">Loading…</div>}
        {detail && (
          <>
            <div className="meta">
              {detail.span.task_label ?? "(unlabeled)"} · {detail.span.model}
              {" · "}
              created {new Date(detail.span.created_at).toLocaleString()}
            </div>

            <div><strong>Prompt:</strong></div>
            <pre style={{
              background: "var(--panel-2)", border: "1px solid var(--border)",
              borderRadius: 6, padding: 10, whiteSpace: "pre-wrap",
              fontSize: 12, marginTop: 6,
            }}>{detail.span.prompt_redacted ?? "—"}</pre>

            {bestJudge && bestReplay ? (
              <>
                <div className="compare">
                  <div>
                    <div className="meta">Original · {detail.span.thinking_level_used}</div>
                    <div style={{ fontSize: 12, margin: "6px 0 10px" }}>
                      {detail.span.response_redacted}
                    </div>
                    <div className="meta">
                      thinking: {detail.span.thinking_tokens ?? "—"} tok · latency {detail.span.latency_ms}ms
                    </div>
                    <div style={{ fontWeight: 600, marginTop: 6 }}>
                      {fmt$(detail.span.estimated_cost_usd)}
                    </div>
                  </div>
                  <div>
                    <div className="meta">Replay · {bestReplay.target_thinking_level}</div>
                    <div style={{ fontSize: 12, margin: "6px 0 10px" }}>
                      {bestReplay.response_redacted}
                    </div>
                    <div className="meta">
                      thinking: {bestReplay.thinking_tokens ?? "—"} tok · latency {bestReplay.latency_ms}ms
                    </div>
                    <div style={{ fontWeight: 600, marginTop: 6 }}>
                      {fmt$(bestReplay.estimated_cost_usd)}
                    </div>
                  </div>
                </div>

                <div style={{ marginTop: 14 }}>
                  <span className={`verdict-pill ${bestJudge.verdict}`}>
                    {bestJudge.verdict.replace("_", " ")}
                  </span>
                  <span style={{ marginLeft: 10, color: "var(--muted)" }}>
                    confidence {(bestJudge.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                {bestJudge.reasoning && (
                  <div style={{ marginTop: 8, fontSize: 13, color: "var(--text)" }}>
                    {bestJudge.reasoning}
                  </div>
                )}
                {bestJudge.estimated_savings_usd > 0 && (
                  <div style={{ marginTop: 16, fontSize: 16, fontWeight: 600, color: "var(--red)" }}>
                    Potential savings: {fmt$(bestJudge.estimated_savings_usd)} per call
                  </div>
                )}
              </>
            ) : (
              <div className="empty">No judge results yet.</div>
            )}

            {detail.judges.length > 1 && (
              <>
                <h2 style={{ marginTop: 24, fontSize: 13, textTransform: "uppercase", color: "var(--muted)" }}>
                  All replay verdicts
                </h2>
                <table>
                  <thead>
                    <tr>
                      <th>Level</th><th>Verdict</th><th>Conf.</th><th>Savings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.judges.map(j => (
                      <tr key={j.id}>
                        <td>{j.alternative_level}</td>
                        <td><span className={`verdict-pill ${j.verdict}`}>{j.verdict.replace("_", " ")}</span></td>
                        <td>{(j.confidence * 100).toFixed(0)}%</td>
                        <td className={j.estimated_savings_usd > 0 ? "cell-red" : ""}>
                          {fmt$(j.estimated_savings_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            {history && history.sample_count > 1 && (
              <>
                <h2 style={{ marginTop: 24, fontSize: 13, textTransform: "uppercase", color: "var(--muted)" }}>
                  Audit history for this pattern ({history.sample_count} samples)
                </h2>
                <table>
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Thinking</th>
                      <th>Cost</th>
                      <th>Best verdict</th>
                      <th>Savings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.samples.map(s => (
                      <tr key={s.span_id} className={s.span_id === detail.span.id ? "highlight-row" : ""}>
                        <td>{new Date(s.created_at).toLocaleString()}</td>
                        <td>{s.thinking_tokens ?? "—"}</td>
                        <td>{fmt$(s.estimated_cost_usd)}</td>
                        <td>
                          {s.best_verdict && (
                            <span className={`verdict-pill ${s.best_verdict}`}>
                              {s.best_verdict.replace("_", " ")}
                              {s.best_alternative_level ? ` @ ${s.best_alternative_level}` : ""}
                            </span>
                          )}
                        </td>
                        <td className={s.best_savings_usd > 0 ? "cell-red" : ""}>
                          {fmt$(s.best_savings_usd)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </div>
    </>
  );
}
