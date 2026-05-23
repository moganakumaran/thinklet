"""Multimodal contents helpers.

Gemini's `generate_content` accepts:
  - a plain string
  - a list of strings
  - a list of Part objects / dicts: {"text": ...} or {"inline_data": {...}}
    or {"file_data": {...}}

Thinklet stores these as a normalized JSON list of dicts so we can:
  1. Hash them deterministically for prompt_hash (image bytes included).
  2. Persist them so the replay engine can re-issue the same call.
  3. Render a short structural summary for the dashboard (no raw bytes).
"""
from __future__ import annotations

import base64
import hashlib
import json
from typing import Any


# ---------------- normalization ----------------

def normalize_contents(contents: Any) -> list[dict]:
    """Return a canonical list of part dicts.

    Each part is one of:
      {"type": "text", "value": str}
      {"type": "inline_data", "mime_type": str, "data_b64": str}
      {"type": "file_data", "mime_type": str | None, "file_uri": str}
    """
    if isinstance(contents, str):
        return [{"type": "text", "value": contents}]

    out: list[dict] = []
    for item in contents:
        out.append(_normalize_part(item))
    return out


def _normalize_part(part: Any) -> dict:
    # Plain string -> text part.
    if isinstance(part, str):
        return {"type": "text", "value": part}

    # Plain bytes -> assume image/png as a hopeful default; users should
    # really pass dicts with explicit mime_type, but this lets quick tests
    # work without ceremony.
    if isinstance(part, (bytes, bytearray)):
        return {
            "type": "inline_data",
            "mime_type": "application/octet-stream",
            "data_b64": base64.b64encode(bytes(part)).decode("ascii"),
        }

    if isinstance(part, dict):
        if "text" in part:
            return {"type": "text", "value": part["text"]}
        if "inline_data" in part:
            d = part["inline_data"]
            data = d.get("data", b"")
            if isinstance(data, (bytes, bytearray)):
                data_b64 = base64.b64encode(bytes(data)).decode("ascii")
            else:
                # Already base64-encoded string.
                data_b64 = str(data)
            return {
                "type": "inline_data",
                "mime_type": d.get("mime_type") or "application/octet-stream",
                "data_b64": data_b64,
            }
        if "file_data" in part:
            d = part["file_data"]
            return {
                "type": "file_data",
                "mime_type": d.get("mime_type"),
                "file_uri": d.get("file_uri") or "",
            }

    # Last-ditch best-effort: try to read attributes off a Gemini Part object.
    text = getattr(part, "text", None)
    if text is not None:
        return {"type": "text", "value": text}
    inline = getattr(part, "inline_data", None)
    if inline is not None:
        data = getattr(inline, "data", b"")
        mime = getattr(inline, "mime_type", None) or "application/octet-stream"
        if isinstance(data, (bytes, bytearray)):
            data_b64 = base64.b64encode(bytes(data)).decode("ascii")
        else:
            data_b64 = str(data)
        return {"type": "inline_data", "mime_type": mime, "data_b64": data_b64}

    raise TypeError(f"Unsupported content part: {type(part).__name__}")


# ---------------- hashing ----------------

def hash_contents(model: str, contents: Any) -> str:
    """Deterministic 32-char hash of (model, contents).

    Hashing iterates the normalized parts in order, including binary blob
    bytes — so two calls with the same caption but different images get
    different hashes (which is what we want for grouping).
    """
    parts = normalize_contents(contents)
    h = hashlib.sha256()
    h.update(model.encode())
    for p in parts:
        h.update(b"|")
        h.update(p["type"].encode())
        h.update(b"|")
        if p["type"] == "text":
            h.update(p["value"].encode())
        elif p["type"] == "inline_data":
            h.update(p["mime_type"].encode())
            h.update(b"|")
            # Hash decoded bytes (not the base64) so different encodings
            # of the same image collide correctly.
            try:
                raw = base64.b64decode(p["data_b64"])
            except Exception:
                raw = p["data_b64"].encode()
            h.update(hashlib.sha256(raw).digest())
        elif p["type"] == "file_data":
            h.update((p.get("mime_type") or "").encode())
            h.update(b"|")
            h.update(p["file_uri"].encode())
    return h.hexdigest()[:32]


# ---------------- redaction summary ----------------

def redact_contents(contents: Any, *, text_limit: int = 500) -> str:
    """Short human-readable summary stored in spans.prompt_redacted.

    For a plain text prompt this is just the text (truncated). For
    multimodal calls it's a one-line shape like:
      "text(38 chars) + inline_data(image/png, 67 bytes)"
    """
    parts = normalize_contents(contents)
    if len(parts) == 1 and parts[0]["type"] == "text":
        v = parts[0]["value"]
        return v if len(v) <= text_limit else v[:text_limit] + "..."
    summaries: list[str] = []
    for p in parts:
        if p["type"] == "text":
            summaries.append(f"text({len(p['value'])} chars)")
        elif p["type"] == "inline_data":
            try:
                size = len(base64.b64decode(p["data_b64"]))
            except Exception:
                size = len(p["data_b64"])
            summaries.append(f"inline_data({p['mime_type']}, {size} bytes)")
        elif p["type"] == "file_data":
            summaries.append(f"file_data({p['file_uri']})")
    return " + ".join(summaries)


# ---------------- serialization ----------------

def serialize_contents(contents: Any) -> str:
    """JSON string suitable for the spans.contents_json column."""
    return json.dumps(normalize_contents(contents))


def to_gemini_contents(contents_json: str):
    """Inverse of serialize_contents — rebuilds a Gemini-ready contents list.

    Only called from the replay engine when re-issuing a real call. The
    `google-genai` SDK is imported lazily so this module stays importable
    in demo-only environments.
    """
    parts = json.loads(contents_json)
    from google.genai import types
    out = []
    for p in parts:
        if p["type"] == "text":
            out.append(p["value"])
        elif p["type"] == "inline_data":
            raw = base64.b64decode(p["data_b64"])
            out.append(
                types.Part(
                    inline_data=types.Blob(
                        data=raw, mime_type=p["mime_type"],
                    )
                )
            )
        elif p["type"] == "file_data":
            out.append(
                types.Part(
                    file_data=types.FileData(
                        file_uri=p["file_uri"],
                        mime_type=p.get("mime_type"),
                    )
                )
            )
    return out
