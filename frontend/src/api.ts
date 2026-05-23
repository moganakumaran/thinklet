// Thinklet API client — thin fetch wrappers.

const BASE = (import.meta as any).env?.VITE_BACKEND_URL ?? "http://localhost:8000";

export type ThinkingLevel = "minimal" | "low" | "medium" | "high";
export type Verdict = "equivalent" | "degraded" | "materially_different" | "uncertain";

export interface Span {
  id: string;
  created_at: string;
  trace_id?: string | null;
  call_id?: string | null;
  prompt_hash: string;
  prompt_redacted?: string | null;
  response_redacted?: string | null;
  model: string;
  thinking_level_used: ThinkingLevel;
  input_tokens: number;
  output_tokens: number;
  thinking_tokens?: number | null;
  total_tokens: number;
  latency_ms: number;
  estimated_cost_usd: number;
  task_label?: string | null;
  source: "real" | "demo";
}

export interface TopWastePattern {
  task_label: string | null;
  calls_with_waste: number;
  estimated_savings_usd: number;
  typical_original_level: ThinkingLevel;
  typical_recommended_level: ThinkingLevel;
}

export interface RecommendedDowngrade {
  from_level: ThinkingLevel;
  to_level: ThinkingLevel;
  affected_calls: number;
  estimated_savings_usd: number;
}

export interface WasteReport {
  total_calls_audited: number;
  calls_with_likely_waste: number;
  estimated_cost_wasted_usd: number;
  monthly_projection_usd: number;
  observed_days: number;
  top_wasteful_patterns: TopWastePattern[];
  recommended_downgrades: RecommendedDowngrade[];
  demo_mode: boolean;
}

export interface WasteMapCell {
  task_label: string;
  prompt_hash: string;
  original_level: ThinkingLevel;
  recommended_level: ThinkingLevel | null;
  verdict: Verdict;
  color: "red" | "yellow" | "green";
  span_count: number;
  estimated_savings_usd: number;
  equivalent_sample_count: number;
  equivalent_rate: number;
}

export interface CellSampleSummary {
  span_id: string;
  created_at: string;
  thinking_tokens: number | null;
  estimated_cost_usd: number;
  best_verdict: Verdict | null;
  best_alternative_level: ThinkingLevel | null;
  best_savings_usd: number;
}

export interface CellHistory {
  task_label: string;
  prompt_hash: string;
  original_level: ThinkingLevel;
  sample_count: number;
  samples: CellSampleSummary[];
}

export interface JudgeResult {
  id: string;
  span_id: string;
  replay_result_id: string;
  original_level: ThinkingLevel;
  alternative_level: ThinkingLevel;
  verdict: Verdict;
  confidence: number;
  reasoning?: string | null;
  votes?: string[] | null;
  recommended_level?: ThinkingLevel | null;
  estimated_savings_usd: number;
}

export interface ReplayResult {
  id: string;
  span_id: string;
  target_thinking_level: ThinkingLevel;
  response_redacted?: string | null;
  input_tokens: number;
  output_tokens: number;
  thinking_tokens?: number | null;
  latency_ms: number;
  estimated_cost_usd: number;
}

export interface SpanDetail {
  span: Span;
  replays: ReplayResult[];
  judges: JudgeResult[];
}

export interface Health {
  status: "ok";
  demo_mode: boolean;
  db_path: string;
  span_count: number;
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

async function postJson<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { method: "POST" });
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

export interface AuditCaptureParams {
  prompt: string;
  taskLabel?: string;
  thinkingLevel?: ThinkingLevel;
  model?: string;
  image?: File | null;
}

export interface JobSummary {
  jobs_created?: number;
  jobs_processed?: number;
  completed?: number;
  failed?: number;
  judged?: number;
  skipped_existing?: number;
}

async function auditCapture(p: AuditCaptureParams): Promise<Span> {
  const fd = new FormData();
  fd.append("prompt", p.prompt);
  if (p.taskLabel) fd.append("task_label", p.taskLabel);
  if (p.thinkingLevel) fd.append("thinking_level", p.thinkingLevel);
  if (p.model) fd.append("model", p.model);
  if (p.image) fd.append("image", p.image);
  const r = await fetch(`${BASE}/audit/capture`, { method: "POST", body: fd });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`/audit/capture -> ${r.status}: ${text.slice(0, 200)}`);
  }
  return r.json();
}

export const api = {
  health: () => get<Health>("/health"),
  spans: (limit = 50) => get<Span[]>(`/spans?limit=${limit}`),
  spanDetail: (id: string) => get<SpanDetail>(`/spans/${id}/detail`),
  wasteReport: () => get<WasteReport>("/waste-report"),
  wasteMap: () => get<WasteMapCell[]>("/waste-map"),
  cellHistory: (params: { task_label: string; prompt_hash: string; original_level: string; limit?: number }) =>
    get<CellHistory>(
      `/cell-history?task_label=${encodeURIComponent(params.task_label)}` +
      `&prompt_hash=${encodeURIComponent(params.prompt_hash)}` +
      `&original_level=${encodeURIComponent(params.original_level)}` +
      `&limit=${params.limit ?? 50}`,
    ),
  policyUrl: (format: "json" | "python" | "yaml" = "python") =>
    `${BASE}/policy?format=${format}`,
  fetchPolicy: async (format: "json" | "python" | "yaml" = "python"): Promise<string> => {
    const r = await fetch(`${BASE}/policy?format=${format}`);
    if (!r.ok) throw new Error(`/policy -> ${r.status}`);
    return r.text();
  },
  auditCapture,
  auditReplay: (id: string) => postJson<JobSummary>(`/audit/${id}/replay`),
  auditJudge: (id: string) => postJson<JobSummary>(`/audit/${id}/judge`),
};
