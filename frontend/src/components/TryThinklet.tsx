import { useRef, useState } from "react";
import {
  api,
  type Span,
  type SpanDetail,
  type ThinkingLevel,
} from "../api";
import AuditDAG from "./AuditDAG";
import AuditProgressLog, { type LogLine, type LogKind } from "./AuditProgressLog";

const FREE_TIER_ETA_S = 90;

const LEVELS: ThinkingLevel[] = ["minimal", "low", "medium", "high"];

const fmt$ = (v: number) =>
  v >= 1 ? `$${v.toFixed(2)}` : v > 0 ? `$${v.toFixed(6)}` : "$0";

function ts() {
  return new Date().toTimeString().slice(0, 8);
}

interface Props {
  onAuditComplete?: () => void;
}

export default function TryThinklet({ onAuditComplete }: Props) {
  const [prompt, setPrompt] = useState("Describe this image in one sentence.");
  const [taskLabel, setTaskLabel] = useState("try_it");
  const [thinkingLevel, setThinkingLevel] = useState<ThinkingLevel>("high");
  const [image, setImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);
  const [detail, setDetail] = useState<SpanDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function appendLog(kind: LogKind, text: string) {
    setLog((prev) => [...prev, { ts: ts(), kind, text }]);
  }

  // Replace the last "running" line with a final ok/error variant so the log
  // stays compact: one in-progress -> one completed line per phase.
  function finishLastRunning(kind: LogKind, text: string) {
    setLog((prev) => {
      const out = prev.slice();
      for (let i = out.length - 1; i >= 0; i--) {
        if (out[i].kind === "running") {
          out[i] = { ts: ts(), kind, text };
          return out;
        }
      }
      // Fallback: just append.
      out.push({ ts: ts(), kind, text });
      return out;
    });
  }

  function handleImagePick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setImage(f);
    setImagePreview(null);
    if (f) {
      if (f.size > 4 * 1024 * 1024) {
        setFormError("Image too large (>4MB). Pick a smaller file.");
        setImage(null);
        if (fileInputRef.current) fileInputRef.current.value = "";
        return;
      }
      const reader = new FileReader();
      reader.onload = () => setImagePreview(reader.result as string);
      reader.readAsDataURL(f);
    }
  }

  function clearImage() {
    setImage(null);
    setImagePreview(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function runAudit() {
    setFormError(null);
    if (!prompt.trim()) {
      setFormError("Prompt is required.");
      return;
    }
    setRunning(true);
    setDetail(null);
    setLog([]);

    try {
      // Step 1: capture
      appendLog(
        "info",
        `Running on free-tier Gemini — expect ~${FREE_TIER_ETA_S}s total.`
      );
      appendLog("running", `Capturing original at ${thinkingLevel.toUpperCase()}…`);
      let span: Span;
      try {
        span = await api.auditCapture({
          prompt,
          taskLabel: taskLabel || "try_it",
          thinkingLevel,
          image,
        });
      } catch (e: any) {
        finishLastRunning("error", `Capture failed: ${e?.message ?? e}`);
        return;
      }
      finishLastRunning(
        "ok",
        `Captured (${thinkingLevel.toUpperCase()}) — ` +
          `${span.thinking_tokens ?? "—"} thinking tokens, ` +
          `${fmt$(span.estimated_cost_usd)}, response: ${
            (span.response_redacted ?? "").slice(0, 60)
          }${(span.response_redacted ?? "").length > 60 ? "…" : ""}`
      );

      // Step 2: replay
      appendLog(
        "running",
        `Replaying at lower thinking levels (paced for free-tier 5 RPM)…`
      );
      try {
        const r = await api.auditReplay(span.id);
        finishLastRunning(
          "ok",
          `Replays — ${r.completed ?? 0} ok / ${r.failed ?? 0} failed ` +
            `(${r.jobs_processed ?? 0} processed).`
        );
      } catch (e: any) {
        finishLastRunning("error", `Replay failed: ${e?.message ?? e}`);
        return;
      }

      // Step 3: judge
      appendLog("running", `Judging equivalence (deterministic + LLM)…`);
      try {
        const j = await api.auditJudge(span.id);
        finishLastRunning(
          "ok",
          `Judges — ${j.judged ?? 0} verdicts written ` +
            `(${j.skipped_existing ?? 0} skipped).`
        );
      } catch (e: any) {
        finishLastRunning("error", `Judge failed: ${e?.message ?? e}`);
        return;
      }

      // Step 4: fetch detail to render the DAG
      appendLog("running", `Loading audit detail…`);
      let d: SpanDetail;
      try {
        d = await api.spanDetail(span.id);
      } catch (e: any) {
        finishLastRunning("error", `Detail fetch failed: ${e?.message ?? e}`);
        return;
      }
      const bestSaving = d.judges
        .filter((j) => j.verdict === "equivalent")
        .map((j) => j.estimated_savings_usd)
        .sort((a, b) => b - a)[0];
      finishLastRunning(
        "ok",
        bestSaving > 0
          ? `Done — best downgrade saves ${fmt$(bestSaving)} per call.`
          : `Done — no safe downgrade detected (HIGH appears justified).`
      );
      setDetail(d);

      // Refresh parent dashboard (Waste Map, etc.) so the new cell appears.
      onAuditComplete?.();
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="section try-thinklet">
      <h2>Audit a call</h2>
      <p className="try-thinklet-help">
        Type a prompt (and optionally upload an image). Thinklet will capture
        the call, replay it at lower thinking budgets, have a judge compare the
        responses, and render the result as a DAG below.
      </p>

      <div className="try-thinklet-form">
        <label className="try-thinklet-field">
          <span>Prompt</span>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="What should Gemini do?"
            disabled={running}
          />
        </label>

        <div className="try-thinklet-row">
          <label className="try-thinklet-field">
            <span>Thinking level</span>
            <select
              value={thinkingLevel}
              onChange={(e) => setThinkingLevel(e.target.value as ThinkingLevel)}
              disabled={running}
            >
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l.toUpperCase()}
                </option>
              ))}
            </select>
          </label>

          <label className="try-thinklet-field">
            <span>Task label</span>
            <input
              type="text"
              value={taskLabel}
              onChange={(e) => setTaskLabel(e.target.value)}
              placeholder="try_it"
              disabled={running}
            />
          </label>

          <label className="try-thinklet-field">
            <span>Image (optional)</span>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={handleImagePick}
              disabled={running}
            />
          </label>
        </div>

        {imagePreview && (
          <div className="try-thinklet-preview">
            <img src={imagePreview} alt="upload preview" />
            <button onClick={clearImage} disabled={running}>
              Clear image
            </button>
          </div>
        )}

        {formError && <div className="try-thinklet-error">{formError}</div>}

        <div className="try-thinklet-actions">
          <button
            onClick={runAudit}
            disabled={running || !prompt.trim()}
            className="try-thinklet-submit"
          >
            {running ? "Auditing…" : "Run audit"}
          </button>
        </div>
      </div>

      <AuditProgressLog lines={log} />

      {detail && (
        <div style={{ marginTop: 18 }}>
          <h3 className="audit-dag-title">Audit DAG</h3>
          <AuditDAG detail={detail} />
        </div>
      )}
    </div>
  );
}
