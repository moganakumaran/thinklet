import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import type { WasteReport } from "../api";

const fmt$ = (v: number) =>
  v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(4)}` : "$0";

export default function WasteReportView({ report }: { report: WasteReport }) {
  const wastePct = report.total_calls_audited > 0
    ? Math.round((report.calls_with_likely_waste / report.total_calls_audited) * 100)
    : 0;

  const chartData = report.top_wasteful_patterns.map(p => ({
    label: p.task_label ?? "(unlabeled)",
    savings: Number(p.estimated_savings_usd.toFixed(6)),
    calls: p.calls_with_waste,
  }));

  return (
    <>
      <div className="section">
        <h2>Waste Report</h2>
        <div className="headline-grid">
          <div className="headline-card">
            <div className="label">Calls audited</div>
            <div className="value">{report.total_calls_audited}</div>
          </div>
          <div className="headline-card">
            <div className="label">Likely waste</div>
            <div className="value">{report.calls_with_likely_waste} <span style={{fontSize: 14, color: "var(--muted)"}}>({wastePct}%)</span></div>
          </div>
          <div className="headline-card savings">
            <div className="label">Wasted ({report.observed_days.toFixed(1)} days)</div>
            <div className="value">{fmt$(report.estimated_cost_wasted_usd)}</div>
          </div>
          <div className="headline-card projection">
            <div className="label">Monthly projection</div>
            <div className="value">{fmt$(report.monthly_projection_usd)}</div>
          </div>
        </div>
      </div>

      <div className="row-grid">
        <div className="section">
          <h2>Top wasteful prompt patterns</h2>
          {chartData.length === 0 ? (
            <div className="empty">No waste detected.</div>
          ) : (
            <div style={{ height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} layout="vertical" margin={{ left: 20, right: 16, top: 4, bottom: 4 }}>
                  <XAxis type="number" hide />
                  <YAxis dataKey="label" type="category" width={120}
                         tick={{ fill: "var(--text)", fontSize: 12 }} />
                  <Tooltip
                    cursor={{ fill: "rgba(88,166,255,0.06)" }}
                    contentStyle={{ background: "var(--panel-2)", border: "1px solid var(--border)" }}
                    formatter={((v: any, _n: any, ctx: any) =>
                      [`$${Number(v ?? 0).toFixed(6)} (${ctx?.payload?.calls ?? 0} calls)`, "Savings"]) as any}
                  />
                  <Bar dataKey="savings" radius={[0, 4, 4, 0]}>
                    {chartData.map((_, i) => (
                      <Cell key={i} fill="var(--red)" />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="section">
          <h2>Top recommended downgrades</h2>
          {report.recommended_downgrades.length === 0 ? (
            <div className="empty">None.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>From</th><th>To</th><th>Calls</th><th>Savings</th>
                </tr>
              </thead>
              <tbody>
                {report.recommended_downgrades.map((d, i) => (
                  <tr key={i}>
                    <td><LevelPill level={d.from_level} /></td>
                    <td>→ <LevelPill level={d.to_level} /></td>
                    <td>{d.affected_calls}</td>
                    <td className="cell-red">{fmt$(d.estimated_savings_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
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
