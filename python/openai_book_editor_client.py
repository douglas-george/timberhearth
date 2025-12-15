"""
openai_book_editor_client_json.py  (robust JSON parsing update)

Fixes common "JSON parse failed" issues by:
- Extracting the first top-level JSON object from model output (balanced braces)
- Allowing leading/trailing whitespace or accidental prose before/after JSON
- Providing clearer error messages with the raw text snippet

The editor is still instructed to return strict JSON; this just makes the client resilient.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence, TypedDict, Literal, List
import json


DEFAULT_MODEL = "gpt-5.2"
DEFAULT_MAX_OUTPUT_TOKENS = 10000


@dataclass(frozen=True)
class EditorOptions:
    max_words: Optional[int] = 800
    enforce_sections: bool = True
    ask_clarifying_questions: bool = True


BOOK_EDITOR_JSON_SYSTEM_PROMPT = """\
You are a professional book editor experienced in developmental and line editing for fiction and non-fiction.

You MUST respond with a single JSON object (no markdown, no backticks, no commentary).

Your job:
- Provide honest, kind, specific feedback that improves clarity, coherence, impact, and readability
- Preserve the author’s voice, tone, intent, and continuity
- Critique the writing, not the writer
- When a change might alter meaning/tone or you lack context, ask clarifying questions (but keep them brief)

Schema (strict):
{
  "general_feedback": {
    "summary": string,
    "purpose_audience": string,
    "structure_flow": string,
    "voice_style": string,
    "clarity_coherence": string,
    "pacing": string,
    "strengths": string,
    "top_priorities": string
  },
  "items": [
    {
      "id": string,                  // "E1", "E2", ...
      "category": string,            // e.g. "structure", "pacing", "clarity", "voice", "continuity", "grammar", "dialogue"
      "title": string,               // short label
      "detail": string,              // explanation & rationale
      "evidence": [string],          // short quoted snippets (<= 20 words each) or location hints (e.g. "Paragraph 3")
      "suggested_change": string,    // actionable recommendation
      "priority": "high"|"med"|"low",
      "risk": "low"|"med"|"high"
    }
  ],
  "clarifying_questions": [string]   // 0-3 questions
}

Rules:
- Keep evidence snippets short (<= 20 words each).
- Provide 5-15 items depending on excerpt length.
- If you are unsure, include the concern as an item with risk="high" and ask a clarifying question.
- Do NOT include author responses; the app will collect those.
"""


GHOST_WRITER_JSON_SYSTEM_PROMPT = """\
You are a professional ghostwriter who revises and drafts text to implement an author’s intent.
You collaborate with an editor by translating editorial feedback into concrete changes, while preserving the author’s voice, tone, worldbuilding rules, and narrative priorities.

Inputs you may receive:
- Original text (required to revise)
- Editor feedback (optional but common)
- Author responses / guidance (optional but high priority)

Rules:
- Do not invent missing details. If required input is missing or contradictory, ask 1–3 brief clarifying questions.
- Prioritize the author’s guidance over the editor’s suggestions when they conflict.
- Preserve names, facts, continuity, and style unless explicitly instructed to change them.
- Make changes that are purposeful; avoid “polishing” that alters voice.

You MUST respond with a single JSON object (no markdown, no backticks, no commentary).
Schema:
{
  "status": "needs_clarification" | "revised",
  "questions": string[],
  "change_summary": string[],
  "revised_text": string
}

Requirements:
- If you need info to proceed, set status="needs_clarification", ask 1–3 questions,
  and set revised_text="" and change_summary=[].
- Otherwise set status="revised", questions must be [], provide change_summary as an array of strings,
  and provide revised_text in full.
"""


def ask(
    *,
    client: Any,
    user_prompt: str,
    system_prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    extra_input: Optional[Sequence[dict[str, Any]]] = None,
) -> str:
    input_messages: list[dict[str, Any]] = []
    if system_prompt:
        input_messages.append({"role": "system", "content": system_prompt})
    if extra_input:
        input_messages.extend(list(extra_input))
    input_messages.append({"role": "user", "content": user_prompt})

    try:
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")
        print(model)
        print(f"...................................................................")
        print(input_messages)
        print(f"...................................................................")
        print(max_output_tokens)
        print(f">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>")

        response = client.responses.create(
            model=model,
            input=input_messages,
            max_output_tokens=max_output_tokens,
        )
        text = getattr(response, "output_text", None)
        if not text:
            raise RuntimeError("No output_text returned by the API response.")
        
        print(f"<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")
        print(text)
        print(f"<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<")

        return text
    except Exception as e:
        raise RuntimeError(f"LLM request failed: {e}") from e


def _extract_first_json_object(text: str) -> str:
    """
    Extract the first top-level JSON object from a string.
    Handles cases where the model accidentally adds extra text before/after JSON.

    Strategy: find first '{', then scan for balanced braces while respecting strings.
    """
    if text is None:
        raise RuntimeError("No text to parse (None).")

    s = text.strip()
    start = s.find("{")
    if start < 0:
        raise RuntimeError(f"No '{{' found in model output. Output starts with:\n{s[:500]}")

    i = start
    depth = 0
    in_str = False
    esc = False

    while i < len(s):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
        i += 1

    raise RuntimeError(
        "Unbalanced JSON braces in model output. Output starts with:\n" + s[:500]
    )


class EditorFeedbackItem(TypedDict):
    id: str
    category: str
    title: str
    detail: str
    evidence: List[str]
    suggested_change: str
    priority: Literal["high", "med", "low"]
    risk: Literal["low", "med", "high"]


class EditorGeneralFeedback(TypedDict):
    summary: str
    purpose_audience: str
    structure_flow: str
    voice_style: str
    clarity_coherence: str
    pacing: str
    strengths: str
    top_priorities: str


class EditorFeedbackJSON(TypedDict):
    general_feedback: EditorGeneralFeedback
    items: List[EditorFeedbackItem]
    clarifying_questions: List[str]


class AuthorResponse(TypedDict):
    id: str
    response: str


class EditorFeedbackWithResponses(TypedDict):
    general_feedback: EditorGeneralFeedback
    items: List[EditorFeedbackItem]
    clarifying_questions: List[str]
    author_responses: List[AuthorResponse]


def _loads_json_robust(raw: str) -> dict:
    """
    Robust json loader: extracts first JSON object then loads.
    """
    extracted = _extract_first_json_object(raw)
    try:
        return json.loads(extracted)
    except Exception as e:
        raise RuntimeError(
            "JSON parse failed even after extraction.\n"
            f"Extracted JSON starts with:\n{extracted[:500]}\n\n"
            f"Original output starts with:\n{(raw or '')[:500]}"
        ) from e


def _validate_editor_json(raw: str) -> EditorFeedbackJSON:
    data = _loads_json_robust(raw)

    if not isinstance(data, dict):
        raise RuntimeError("Editor JSON must be an object.")

    for key in ("general_feedback", "items", "clarifying_questions"):
        if key not in data:
            raise RuntimeError(f"Editor JSON missing '{key}'.")

    gf = data["general_feedback"]
    if not isinstance(gf, dict):
        raise RuntimeError("'general_feedback' must be an object.")

    gf_keys = [
        "summary",
        "purpose_audience",
        "structure_flow",
        "voice_style",
        "clarity_coherence",
        "pacing",
        "strengths",
        "top_priorities",
    ]
    missing_gf = [k for k in gf_keys if k not in gf or not isinstance(gf[k], str)]
    if missing_gf:
        raise RuntimeError(f"general_feedback missing/invalid keys: {missing_gf}")

    items = data["items"]
    if not isinstance(items, list) or len(items) == 0:
        raise RuntimeError("'items' must be a non-empty list.")

    seen_ids: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            raise RuntimeError("Each item must be an object.")
        req = ["id", "category", "title", "detail", "evidence", "suggested_change", "priority", "risk"]
        for k in req:
            if k not in it:
                raise RuntimeError(f"Item missing '{k}'.")
        if not isinstance(it["id"], str) or not it["id"].strip():
            raise RuntimeError("Item.id must be non-empty string.")
        if it["id"] in seen_ids:
            raise RuntimeError(f"Duplicate item id: {it['id']}")
        seen_ids.add(it["id"])

        if it["priority"] not in ("high", "med", "low"):
            raise RuntimeError(f"Item.priority invalid: {it['priority']}")
        if it["risk"] not in ("low", "med", "high"):
            raise RuntimeError(f"Item.risk invalid: {it['risk']}")
        if not isinstance(it["evidence"], list) or not all(isinstance(x, str) for x in it["evidence"]):
            raise RuntimeError("Item.evidence must be list[str].")

    cq = data["clarifying_questions"]
    if not isinstance(cq, list) or not all(isinstance(x, str) for x in cq):
        raise RuntimeError("'clarifying_questions' must be list[str].")
    if len(cq) > 3:
        raise RuntimeError("'clarifying_questions' must have at most 3 questions.")

    return data  # type: ignore[return-value]


def book_feedback_ask_json(
    *,
    client: Any,
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_output_tokens: int = 10000,
    options: Optional[EditorOptions] = None,
) -> EditorFeedbackWithResponses:
    opts = options or EditorOptions(max_words=900, enforce_sections=False, ask_clarifying_questions=True)
    user_prompt = prompt.strip()
    if opts.max_words is not None:
        user_prompt += f"\n\n---\nConstraint: Keep your JSON fields concise; aim for <= ~{opts.max_words} words total."

    raw = ask(
        client=client,
        user_prompt=user_prompt,
        system_prompt=BOOK_EDITOR_JSON_SYSTEM_PROMPT,
        model=model,
        max_output_tokens=max_output_tokens,
    )

    parsed = _validate_editor_json(raw)
    author_responses: List[AuthorResponse] = [{"id": it["id"], "response": ""} for it in parsed["items"]]

    return {
        "general_feedback": parsed["general_feedback"],
        "items": parsed["items"],
        "clarifying_questions": parsed["clarifying_questions"],
        "author_responses": author_responses,
    }


class GhostwriterResult(TypedDict):
    status: Literal["needs_clarification", "revised"]
    questions: list[str]
    change_summary: list[str]
    revised_text: str


def _validate_ghost_json(raw: str) -> GhostwriterResult:
    data = _loads_json_robust(raw)

    required = {"status", "questions", "change_summary", "revised_text"}
    if not isinstance(data, dict) or not required.issubset(data.keys()):
        raise RuntimeError("Ghostwriter JSON missing required keys.")

    status = data.get("status")
    if status not in ("needs_clarification", "revised"):
        raise RuntimeError(f"Ghostwriter JSON invalid status={status}.")

    questions = data.get("questions") or []
    change_summary = data.get("change_summary") or []
    revised_text = data.get("revised_text") or ""

    if not isinstance(questions, list) or not all(isinstance(x, str) for x in questions):
        raise RuntimeError("Ghostwriter JSON 'questions' must be list[str].")
    if not isinstance(change_summary, list) or not all(isinstance(x, str) for x in change_summary):
        raise RuntimeError("Ghostwriter JSON 'change_summary' must be list[str].")
    if not isinstance(revised_text, str):
        raise RuntimeError("Ghostwriter JSON 'revised_text' must be str.")

    if status == "needs_clarification":
        if len(questions) == 0:
            raise RuntimeError("status='needs_clarification' requires at least 1 question.")
        if revised_text.strip() or len(change_summary) > 0:
            raise RuntimeError("status='needs_clarification' must have empty revised_text and empty change_summary.")
    else:
        if len(questions) != 0:
            raise RuntimeError("status='revised' requires questions=[].")
        if not revised_text.strip():
            raise RuntimeError("status='revised' requires non-empty revised_text.")

    return {
        "status": status,
        "questions": questions,
        "change_summary": change_summary,
        "revised_text": revised_text,
    }


def ghost_writer_ask_json(
    *,
    client: Any,
    original_text: str,
    editor_feedback_json: Optional[EditorFeedbackWithResponses] = None,
    author_guidance: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_output_tokens: int = 2600,
) -> GhostwriterResult:
    parts: list[str] = ["ORIGINAL TEXT (revise this):\n" + (original_text or "").strip()]

    if editor_feedback_json is not None:
        parts.append("EDITOR FEEDBACK (JSON):\n" + json.dumps(editor_feedback_json, ensure_ascii=False, indent=2))

    if author_guidance:
        parts.append("AUTHOR GUIDANCE (highest priority when conflicting):\n" + author_guidance.strip())

    user_prompt = "\n\n---\n\n".join(parts)

    raw = ask(
        client=client,
        user_prompt=user_prompt,
        system_prompt=GHOST_WRITER_JSON_SYSTEM_PROMPT,
        model=model,
        max_output_tokens=max_output_tokens,
    )
    return _validate_ghost_json(raw)
