"""Generate a dental SOAP chart from a transcript using the Anthropic API.

The system prompt is loaded from prompts/dental_chart.md and cached at the
API layer (cache_control on the system block) so repeat charts within 5
minutes don't re-pay for the prompt tokens.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from anthropic import Anthropic

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "dental_chart.md"


@dataclass
class ChartResult:
    text: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def generate_chart(
    transcript: str,
    patient_name: str,
    visit_date: str,
) -> ChartResult:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment.")

    model = os.environ.get("CHART_MODEL", "claude-sonnet-4-6")
    client = Anthropic(api_key=api_key)
    system_prompt = _load_system_prompt()

    user_message = (
        f"Patient name: {patient_name}\n"
        f"Visit date: {visit_date}\n\n"
        f"Transcript:\n<transcript>\n{transcript}\n</transcript>\n\n"
        "Produce the chart note now, following the format specified in the system prompt."
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    text_parts = [block.text for block in response.content if block.type == "text"]
    text = "\n".join(text_parts).strip()

    usage = response.usage
    return ChartResult(
        text=text,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
    )
