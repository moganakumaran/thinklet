import { useState } from "react";
import { api } from "../api";

type State = "idle" | "copying" | "copied" | "error";

const RESET_MS: Record<State, number> = {
  idle: 0,
  copying: 0,
  copied: 1800,
  error: 3000,
};

/**
 * Copies the Python-formatted policy to the clipboard, no new tab.
 * Falls back to a temporary textarea on browsers without navigator.clipboard
 * (rare on localhost / HTTPS but cheap to support).
 */
export default function CopyPolicyButton() {
  const [state, setState] = useState<State>("idle");
  const [errMsg, setErrMsg] = useState<string | null>(null);

  async function writeToClipboard(text: string): Promise<void> {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    // Fallback for older browsers / insecure contexts.
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } finally {
      document.body.removeChild(ta);
    }
  }

  async function handleClick() {
    setState("copying");
    setErrMsg(null);
    try {
      const text = await api.fetchPolicy("python");
      await writeToClipboard(text);
      setState("copied");
    } catch (e) {
      setErrMsg(e instanceof Error ? e.message : String(e));
      setState("error");
    } finally {
      const after = RESET_MS[state === "copying" ? "copied" : state];
      if (after > 0) {
        setTimeout(() => setState("idle"), after);
      }
    }
  }

  // Reset back to idle after success/error.
  // (Effect inlined into the setTimeout above; simple enough not to warrant useEffect.)

  const label =
    state === "copying" ? "Copying…"
    : state === "copied" ? "Copied ✓"
    : state === "error" ? "Copy failed"
    : "Copy policy";

  const cls =
    "copy-policy-btn" +
    (state === "copied" ? " is-success" : "") +
    (state === "error" ? " is-error" : "");

  return (
    <button
      onClick={handleClick}
      disabled={state === "copying"}
      className={cls}
      title={
        state === "error" && errMsg
          ? `Copy failed: ${errMsg}`
          : "Copy the THINKING_POLICY Python dict to clipboard"
      }
    >
      {label}
    </button>
  );
}
