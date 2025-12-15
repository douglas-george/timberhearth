"""
OpenAI Responses API helper utilities for consistent prompt roles.

Improvements over the original snippet:
- Uses *actual* system messages (role="system") instead of embedding "SYSTEM PROMPT" in user text.
- Provides a concise, high-signal editor system prompt.
- Adds optional output-format guardrails.
- Adds basic error handling and configurable token limits.
"""

from __future__ import annotations
from openai import OpenAI
from dataclasses import dataclass
from typing import Any, Optional, Sequence, Union
from story import chapter1


# -----------------------------
# Configuration / constants
# -----------------------------

DEFAULT_MODEL = "gpt-5.2"
DEFAULT_MAX_OUTPUT_TOKENS = 2048


@dataclass(frozen=True)
class EditorOptions:
    """
    Options to shape book-editor feedback consistency.
    """
    # If set, asks the model to keep the response under roughly this many words.
    max_words: Optional[int] = 800

    # If True, enforces a consistent 3-section output format.
    enforce_sections: bool = True

    # If True, asks clarifying questions when intent is unclear.
    ask_clarifying_questions: bool = True


BOOK_EDITOR_SYSTEM_PROMPT = """\
You are a professional book editor experienced in developmental and line editing for fiction and non-fiction.

Goals:
- Improve clarity, coherence, impact, and readability
- Preserve the author's voice, tone, and intent
- Be honest but kind; critique the writing, not the writer

For each excerpt:
1) Provide a concise high-level editorial critique (purpose, structure, pacing, voice).
2) Provide specific and actionable suggestions for improvement. Ask clarifying questions with each suggestion for improvement as needed.
"""

GHOST_WRITER_SYSTEM_PROMPT = """\
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

Process:
1) Identify the key goals and constraints from the editor feedback and author guidance.
2) Apply revisions: fix clarity, structure, pacing, and line-level issues as appropriate.
3) Ensure the revised text remains coherent and consistent with the original intent.

Output format (use these headings exactly):
- Change Summary (bulleted list, grouped by: Structure/Pacing, Clarity, Voice/Style, Continuity)
- Revised Text (full revised passage)
"""



# -----------------------------
# Core API wrapper
# -----------------------------

def ask(
    *,
    client: Any,
    user_prompt: str,
    system_prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    extra_input: Optional[Sequence[dict[str, Any]]] = None,
) -> str:
    """
    Send a single prompt to the model and return the aggregated text answer.

    Args:
        client: An initialized OpenAI client instance.
        user_prompt: The user message content.
        system_prompt: Optional system instructions.
        model: Model id.
        max_output_tokens: Output token cap.
        extra_input: Optional additional messages before the user message (e.g., prior context).
                    Must be a sequence of {"role": "...", "content": "..."} dicts.

    Returns:
        response.output_text (SDK convenience aggregated text)

    Raises:
        RuntimeError: If the request fails or no text is returned.
    """
    input_messages: list[dict[str, Any]] = []

    if system_prompt:
        input_messages.append({"role": "system", "content": system_prompt})

    if extra_input:
        input_messages.extend(list(extra_input))

    input_messages.append({"role": "user", "content": user_prompt})

    try:
        response = client.responses.create(
            model=model,
            input=input_messages,
            max_output_tokens=max_output_tokens,
        )
        text = getattr(response, "output_text", None)
        if not text:
            raise RuntimeError("No output_text returned by the API response.")
        return text
    except Exception as e:
        raise RuntimeError(f"LLM request failed: {e}") from e


# -----------------------------
# Specialized helper: book editor
# -----------------------------

def _build_editor_user_prompt(user_prompt: str, options: EditorOptions) -> str:
    """
    Adds lightweight formatting/length guardrails to the *user* prompt (not system prompt),
    so the system prompt remains reusable and stable.
    """
    constraints: list[str] = []

    if options.enforce_sections:
        constraints.append(
            "Format your response using these sections exactly:\n"
            "- Editorial Overview\n"
            "- Line-Level Notes\n"
            "- Suggested Revision"
        )

    if options.max_words is not None:
        constraints.append(f"Keep the total response under ~{options.max_words} words unless I ask for more detail.")

    if options.ask_clarifying_questions:
        constraints.append("If my intent is unclear, ask 1 brief clarifying question at the end.")

    if constraints:
        return f"{user_prompt}\n\n---\nConstraints:\n" + "\n".join(f"- {c}" for c in constraints)

    return user_prompt


def book_feedback_ask(
    *,
    client: Any,
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    options: Optional[EditorOptions] = None,
) -> str:
    """
    Request professional book-editor feedback on the given prompt/excerpt.

    Args:
        client: An initialized OpenAI client instance.
        prompt: The excerpt or instructions to the editor.
        model: Model id.
        max_output_tokens: Output token cap.
        options: EditorOptions for format/length.

    Returns:
        Editor feedback as text.
    """
    opts = options or EditorOptions()
    shaped_user_prompt = _build_editor_user_prompt(prompt, opts)

    return ask(
        client=client,
        user_prompt=shaped_user_prompt,
        system_prompt=BOOK_EDITOR_SYSTEM_PROMPT,
        model=model,
        max_output_tokens=max_output_tokens,
    )


def ghost_writer_ask(
    *,
    client: Any,
    original_text: str,
    editor_feedback: str | None = None,
    author_guidance: str | None = None,
    model: str = DEFAULT_MODEL,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> str:
    parts = [
        "ORIGINAL TEXT (revise this):\n" + original_text.strip()
    ]
    if editor_feedback:
        parts.append("EDITOR FEEDBACK:\n" + editor_feedback.strip())
    if author_guidance:
        parts.append("AUTHOR GUIDANCE (highest priority when conflicting):\n" + author_guidance.strip())

    user_prompt = "\n\n---\n\n".join(parts)

    return ask(
        client=client,
        user_prompt=user_prompt,
        system_prompt=GHOST_WRITER_SYSTEM_PROMPT,
        model=model,
        max_output_tokens=max_output_tokens,
    )


if __name__ == "__main__":
    client = OpenAI()

    options = EditorOptions(
        max_words=700,          # keep feedback concise
        enforce_sections=True,  # consistent structure
        ask_clarifying_questions=True,
    )

    feedback = book_feedback_ask(
        client=client,
        prompt=chapter1,
        options=options,
    )

    revised = ghost_writer_ask(
        client=client,
        original_text=chapter1,
        editor_feedback=feedback,
        author_guidance="Keep the whimsical tone. Do not change character names. Tighten pacing in the middle.",
        max_output_tokens=1600,
    )


    print(feedback)