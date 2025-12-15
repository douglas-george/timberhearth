from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional, Tuple

import dash
from dash import dcc, html, Input, Output, State, callback_context, no_update
from openai import OpenAI

from openai_book_editor_client import (
    BOOK_EDITOR_JSON_SYSTEM_PROMPT,
    GHOST_WRITER_JSON_SYSTEM_PROMPT,
)

# -----------------------------
# Setup
# -----------------------------

client = OpenAI()
app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "Editor → Responses → Ghostwriter (JSON)"

DEFAULT_EDITOR_MAX_OUTPUT_TOKENS = 5000
DEFAULT_GHOST_MAX_OUTPUT_TOKENS = 6000


# -----------------------------
# Small UI helpers
# -----------------------------

def card(title: str, children):
    return html.Div(
        style={
            "border": "1px solid #ddd",
            "borderRadius": "12px",
            "padding": "12px",
            "marginBottom": "12px",
            "boxShadow": "0 1px 2px rgba(0,0,0,0.05)",
            "background": "white",
        },
        children=[html.H4(title, style={"marginTop": 0})] + children,
    )


def details_prompt(title: str, textarea_id: str):
    return html.Details(
        open=False,
        style={
            "marginTop": "10px",
            "padding": "10px",
            "border": "1px dashed #bbb",
            "borderRadius": "10px",
            "background": "#fafafa",
        },
        children=[
            html.Summary(title, style={"cursor": "pointer", "fontWeight": 600}),
            html.Div(
                style={"marginTop": "10px"},
                children=[
                    dcc.Textarea(
                        id=textarea_id,
                        value="",
                        style={"width": "100%", "height": "220px", "fontFamily": "monospace"},
                    ),
                ],
            ),
        ],
    )


def toast_component(toast_data: dict) -> html.Div:
    toast_data = toast_data or {}
    open_ = bool(toast_data.get("open"))

    title = toast_data.get("title", "Done")
    body = toast_data.get("body", "")
    level = toast_data.get("level", "success")  # success | info | warn | error

    border = {"success": "#2ecc71", "info": "#3498db", "warn": "#f1c40f", "error": "#e74c3c"}.get(level, "#3498db")

    container_style = {
        "position": "fixed",
        "right": "16px",
        "bottom": "16px",
        "width": "360px",
        "background": "#fff",
        "borderLeft": f"6px solid {border}",
        "boxShadow": "0 8px 24px rgba(0,0,0,0.15)",
        "borderRadius": "10px",
        "padding": "12px 14px",
        "zIndex": 9999,
        "display": "block" if open_ else "none",
    }

    return html.Div(
        style=container_style,
        children=[
            html.Div(
                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                children=[
                    html.Div(title, style={"fontWeight": 700, "fontSize": "16px"}),
                    html.Button(
                        "×",
                        id="btn-close-toast",
                        n_clicks=0,
                        style={"border": "none", "background": "transparent", "fontSize": "18px", "cursor": "pointer"},
                        title="Close",
                    ),
                ],
            ),
            html.Div(body, style={"marginTop": "8px", "whiteSpace": "pre-wrap", "fontSize": "13px", "color": "#333"}),
            html.Div("Auto-hides in a few seconds.", style={"marginTop": "8px", "fontSize": "11px", "color": "#666"}),
        ],
    )


# -----------------------------
# Robust JSON extraction/parsing
# -----------------------------

def extract_first_json_object(text: str) -> str:
    s = (text or "").strip()
    start = s.find("{")
    if start < 0:
        raise RuntimeError("No '{' found in model output.")
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
                    return s[start:i+1]
        i += 1
    raise RuntimeError("Unbalanced JSON braces (likely truncated output). Increase max_output_tokens.")


def loads_json_robust(text: str) -> dict:
    extracted = extract_first_json_object(text)
    try:
        return json.loads(extracted)
    except Exception as e:
        raise RuntimeError(f"JSON parse failed.\nExtracted starts with:\n{extracted[:500]}") from e


def usage_from_response(resp: Any) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract input/output tokens from Responses API response. The OpenAI SDK exposes `response.usage`
    with `input_tokens` and `output_tokens`.
    """
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None, None
    # usage can be a pydantic model or dict-like
    input_tokens = getattr(usage, "input_tokens", None) if not isinstance(usage, dict) else usage.get("input_tokens")
    output_tokens = getattr(usage, "output_tokens", None) if not isinstance(usage, dict) else usage.get("output_tokens")
    return input_tokens, output_tokens



def sync_author_responses_from_ui(data: dict, response_values: list[str] | None) -> dict:
    """Persist current UI response textareas into data["author_responses"]."""
    data = data or {}
    editor = (data.get("editor_feedback") or {})
    items = editor.get("items") or []
    vals = response_values or []
    data["author_responses"] = [
        {"id": item.get("id"), "response": (vals[i] if i < len(vals) else "")}
        for i, item in enumerate(items)
    ]
    return data

# -----------------------------
# Layout
# -----------------------------

app.layout = html.Div(
    style={"maxWidth": "1200px", "margin": "0 auto", "padding": "16px"},
    children=[
        dcc.Store(
            id="store",
            data={
                "draft_text": "",
                "editor_feedback": None,     # dict
                "author_responses": [],      # list[{id,response}]
                "ghost_result": None,        # dict
                "editor_prompt": BOOK_EDITOR_JSON_SYSTEM_PROMPT,
                "ghost_prompt": GHOST_WRITER_JSON_SYSTEM_PROMPT,
            },
        ),
        dcc.Store(id="toast-store", data={"open": False}),
        dcc.Interval(id="toast-timer", interval=6000, n_intervals=0, disabled=True),

        html.Div(id="toast-container", children=toast_component({"open": False})),

        html.H2("Chapter Workflow"),

        dcc.Loading(
            fullscreen=True,
            type="circle",
            children=[
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "12px"},
                    children=[
                        card(
                            "1) Draft",
                            [
                                dcc.Textarea(
                                    id="draft-text",
                                    value="",
                                    style={"width": "100%", "height": "260px"},
                                ),
                                html.Div(
                                    style={"marginTop": "8px"},
                                    children=[
                                        html.Button("Save Draft", id="btn-save-draft"),
                                        html.Button("Run Editor (JSON)", id="btn-run-editor", style={"marginLeft": "8px"}),
                                        html.Button("Run Ghostwriter", id="btn-run-ghost", style={"marginLeft": "8px"}),
                                        html.Button("Save Responses", id="btn-save-responses", style={"marginLeft": "8px"}),
                                    ],
                                ),
                                html.Div(id="status", style={"marginTop": "8px"}),

                                details_prompt("Editor system prompt (editable)", "editor-prompt"),
                                details_prompt("Ghostwriter system prompt (editable)", "ghost-prompt"),
                            ],
                        ),
                        card(
                            "2) Editor Feedback (items + your responses)",
                            [
                                html.Div(id="editor-general"),
                                html.Hr(),
                                html.Div(id="editor-items"),
                            ],
                        ),
                    ],
                ),

                html.Hr(),

                card(
                    "3) Ghostwriter Output",
                    [
                        html.Div(id="ghost-status"),
                        html.Pre(id="ghost-change-summary", style={"whiteSpace": "pre-wrap"}),
                        dcc.Textarea(id="ghost-revised-text", value="", style={"width": "100%", "height": "340px"}),
                    ],
                ),
            ],
        ),
    ],
)


# -----------------------------
# Hydrate prompt + draft fields from store
# -----------------------------

@app.callback(
    Output("draft-text", "value"),
    Output("editor-prompt", "value"),
    Output("ghost-prompt", "value"),
    Input("store", "data"),
)
def hydrate_inputs(data):
    data = data or {}
    return (
        data.get("draft_text", ""),
        data.get("editor_prompt", BOOK_EDITOR_JSON_SYSTEM_PROMPT),
        data.get("ghost_prompt", GHOST_WRITER_JSON_SYSTEM_PROMPT),
    )


# -----------------------------
# Render toast
# -----------------------------

@app.callback(
    Output("toast-container", "children"),
    Input("toast-store", "data"),
)
def render_toast(toast_data):
    return toast_component(toast_data or {})


# -----------------------------
# Render main views
# -----------------------------

@app.callback(
    Output("editor-general", "children"),
    Output("editor-items", "children"),
    Output("ghost-status", "children"),
    Output("ghost-change-summary", "children"),
    Output("ghost-revised-text", "value"),
    Input("store", "data"),
)
def render_views(data):
    data = data or {}
    editor = data.get("editor_feedback")
    responses = {r["id"]: r.get("response", "") for r in (data.get("author_responses") or [])}
    ghost = data.get("ghost_result")

    # General feedback (no clarifying questions here anymore)
    if not editor:
        general_view = html.Div("(No editor feedback yet.)")
        items_view = html.Div("")
    else:
        gf = editor["general_feedback"]
        general_view = html.Div(
            children=[
                html.H4("General Feedback"),
                html.Ul(
                    [
                        html.Li(f"Summary: {gf['summary']}"),
                        html.Li(f"Purpose/Audience: {gf['purpose_audience']}"),
                        html.Li(f"Structure/Flow: {gf['structure_flow']}"),
                        html.Li(f"Voice/Style: {gf['voice_style']}"),
                        html.Li(f"Clarity/Coherence: {gf['clarity_coherence']}"),
                        html.Li(f"Pacing: {gf['pacing']}"),
                        html.Li(f"Strengths: {gf['strengths']}"),
                        html.Li(f"Top Priorities: {gf['top_priorities']}"),
                    ]
                ),
            ]
        )

        # One card per item, with response box
        item_cards = []
        for item in editor["items"]:
            item_cards.append(
                card(
                    f"{item['id']} · {item['category']} · {item['priority']}",
                    [
                        html.Div(html.B(item["title"])),
                        html.Div(item["detail"], style={"marginTop": "6px"}),
                        html.Div(
                            ["Evidence: ", html.Ul([html.Li(e) for e in item.get("evidence", [])])],
                            style={"marginTop": "6px"} if item.get("evidence") else {"display": "none"},
                        ),
                        html.Div(html.B("Suggested change / question:"), style={"marginTop": "6px"}),
                        html.Div(item["suggested_change"]),
                        html.Div(html.B("Your response:"), style={"marginTop": "10px"}),
                        dcc.Textarea(
                            id={"type": "author-response", "id": item["id"]},
                            value=responses.get(item["id"], ""),
                            style={"width": "100%", "height": "90px"},
                            placeholder="Agree / disagree / revise / answer…",
                        ),
                    ],
                )
            )
        items_view = html.Div(item_cards)

    # Ghost view
    if not ghost:
        ghost_status = "(No ghostwriter output yet.)"
        ghost_summary = ""
        ghost_text = ""
    else:
        ghost_status = f"Status: {ghost.get('status', '')}"
        if ghost.get("status") == "revised":
            ghost_summary = "\n".join(ghost.get("change_summary", []))
            ghost_text = ghost.get("revised_text", "")
        else:
            ghost_summary = "\n".join(ghost.get("questions", []))
            ghost_text = ""

    return general_view, items_view, ghost_status, ghost_summary, ghost_text


# -----------------------------
# Hide toast after timer or close button
# -----------------------------

@app.callback(
    Output("toast-store", "data", allow_duplicate=True),
    Output("toast-timer", "disabled", allow_duplicate=True),
    Input("toast-timer", "n_intervals"),
    Input("btn-close-toast", "n_clicks"),
    State("toast-store", "data"),
    prevent_initial_call=True,
)
def auto_hide_toast(n_intervals, close_clicks, toast_data):
    toast_data = toast_data or {"open": False}
    trig = callback_context.triggered_id

    if trig == "btn-close-toast" and close_clicks:
        toast_data["open"] = False
        return toast_data, True

    if trig == "toast-timer" and n_intervals:
        toast_data["open"] = False
        return toast_data, True

    return no_update, no_update


# -----------------------------
# Single callback orchestration (Option A)
# -----------------------------

@app.callback(
    Output("store", "data"),
    Output("status", "children"),
    Output("toast-store", "data"),
    Output("toast-timer", "disabled"),
    Input("btn-save-draft", "n_clicks"),
    Input("btn-run-editor", "n_clicks"),
    Input("btn-run-ghost", "n_clicks"),
    Input("btn-save-responses", "n_clicks"),
        State("draft-text", "value"),
    State("editor-prompt", "value"),
    State("ghost-prompt", "value"),
    State("store", "data"),
    State("toast-store", "data"),
    State({"type": "author-response", "id": dash.ALL}, "value"),
    prevent_initial_call=True,
)
def orchestrate(save_draft, run_editor, run_ghost, save_responses, draft_text, editor_prompt, ghost_prompt, data, toast_data, response_values):
    data = data or {}
    toast_data = toast_data or {"open": False}
    trig = callback_context.triggered_id

    # persist prompt edits
    if isinstance(editor_prompt, str) and editor_prompt.strip():
        data["editor_prompt"] = editor_prompt
    if isinstance(ghost_prompt, str) and ghost_prompt.strip():
        data["ghost_prompt"] = ghost_prompt


    if trig == "btn-save-draft":
        data["draft_text"] = draft_text or ""
        return data, "Draft saved.", no_update, no_update

    # Run editor (JSON) + show toast with timing and tokens
    if trig == "btn-run-editor":
        if not (draft_text or "").strip():
            return data, "Paste a draft first.", no_update, no_update

        data["draft_text"] = draft_text

        started = time.perf_counter()
        resp = client.responses.create(
            model="gpt-5.2",
            input=[
                {"role": "system", "content": editor_prompt},
                # A little guardrail to keep size predictable:
                {"role": "user", "content": draft_text + "\n\n---\nReturn 8–12 items. Keep fields concise."},
            ],
            max_output_tokens=DEFAULT_EDITOR_MAX_OUTPUT_TOKENS,
        )
        elapsed = time.perf_counter() - started

        # Parse editor JSON
        editor_json = loads_json_robust(resp.output_text)

        # Move clarifying questions into the item list (so you can respond in-line)
        cq = editor_json.get("clarifying_questions") or []
        if cq:
            items = editor_json.get("items") or []

            def _norm(s: str) -> str:
                return " ".join((s or "").strip().lower().split())

            # Detect existing question-like items to avoid duplicates
            existing_q = set()
            for it in items:
                if not isinstance(it, dict):
                    continue
                cat = str(it.get("category", "")).lower()
                title = str(it.get("title", "")).lower()
                suggested = str(it.get("suggested_change", ""))
                detail = str(it.get("detail", "")).lower()
                if cat == "clarifying_question" or "clarifying" in title or ("question" in detail and cat in ("clarity", "structure", "voice", "continuity", "grammar")):
                    existing_q.add(_norm(suggested))

            next_idx = 1
            for q in cq:
                if _norm(q) in existing_q:
                    continue
                items.append(
                    {
                        "id": f"CQ{next_idx}",
                        "category": "clarifying_question",
                        "title": "Clarifying question",
                        "detail": "Please answer this so the ghostwriter can implement changes correctly.",
                        "evidence": [],
                        "suggested_change": q,
                        "priority": "high",
                        "risk": "high",
                    }
                )
                next_idx += 1

            editor_json["items"] = items
            editor_json["clarifying_questions"] = []  # keep general area clean
            editor_json["clarifying_questions"] = []  # keep general area clean

        # Initialize author response list (blank)
        data["editor_feedback"] = editor_json
        data["author_responses"] = [{"id": it["id"], "response": ""} for it in (editor_json.get("items") or [])]
        data["ghost_result"] = None

        in_tok, out_tok = usage_from_response(resp)

        toast_data = {
            "open": True,
            "level": "success",
            "title": "Editor complete",
            "body": f"Time: {elapsed:.2f}s\nInput tokens: {in_tok}\nOutput tokens: {out_tok}",
        }
        return data, "Editor feedback generated.", toast_data, False  # enable timer

    if trig == "btn-save-responses":
        # Save current response textboxes into store without rerendering on each keystroke
        data = sync_author_responses_from_ui(data, response_values)
        return data, "Responses saved.", no_update, no_update

    # Run ghostwriter + show toast with timing and tokens
    if trig == "btn-run-ghost":
        if not data.get("draft_text", "").strip():
            return data, "No draft found.", no_update, no_update
        if not data.get("editor_feedback"):
            return data, "Run the editor first.", no_update, no_update

        # Capture latest responses from UI (in case you did not click "Save Responses")
        data = sync_author_responses_from_ui(data, response_values)

        # Merge author responses into the feedback JSON for the ghostwriter prompt
        editor_json = dict(data["editor_feedback"])
        editor_json["author_responses"] = data.get("author_responses", [])

        gw_user_prompt = "\n\n---\n\n".join(
            [
                "ORIGINAL TEXT (revise this):\n" + data["draft_text"],
                "EDITOR FEEDBACK (JSON):\n" + json.dumps(editor_json, ensure_ascii=False, indent=2),
                "AUTHOR GUIDANCE:\nFollow my per-item responses exactly. Preserve voice and continuity.",
            ]
        )

        started = time.perf_counter()
        resp = client.responses.create(
            model="gpt-5.2",
            input=[
                {"role": "system", "content": ghost_prompt},
                {"role": "user", "content": gw_user_prompt},
            ],
            max_output_tokens=DEFAULT_GHOST_MAX_OUTPUT_TOKENS,
        )
        elapsed = time.perf_counter() - started

        ghost_json = loads_json_robust(resp.output_text)
        data["ghost_result"] = ghost_json

        in_tok, out_tok = usage_from_response(resp)
        toast_data = {
            "open": True,
            "level": "success",
            "title": "Ghostwriter complete",
            "body": f"Time: {elapsed:.2f}s\nInput tokens: {in_tok}\nOutput tokens: {out_tok}",
        }
        return data, "Ghostwriter complete.", toast_data, False

    return data, no_update, no_update, no_update


if __name__ == "__main__":
    app.run(debug=True)