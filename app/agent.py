"""Claude tool-use loop. State (the ClientBrief) lives here, not in the LLM."""
import json
import os
from typing import Optional

from anthropic import Anthropic

from .models import ClientBrief, Recommendation
from .tools import build_recommendation

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

SYSTEM_PROMPT = """You are a media-strategy assistant for Kargo. A media strategist will paste a client brief in plain English. Your job:

1. If the user's message describes a NEW client or brief (different advertiser, or any "a [vertical] brand wants..." style intro), call `reset_brief` FIRST to clear any leftover state from a prior brief. Only skip the reset when the user is clearly answering a follow-up about the brief already in progress.
2. Parse the brief and call `set_brief_fields` with every field you can identify.
3. If required fields are still missing (vertical, kpi, geo, budget_usd), ask ONE concise follow-up question covering all missing fields. Do not call `generate_recommendation` yet.
4. Once required fields are present, call `generate_recommendation`.
5. After the recommendation returns, respond with ONLY a single short sentence introducing the recommendation (e.g. "Here is the best fit for Acme Shoes:"). The UI renders the product details, metrics, rationale, and rejected alternatives as a structured card — do NOT repeat those in your text reply.

Rules:
- Valid verticals: Retail, Finance, Travel, QSR, Entertainment.
- Valid geos: US, EMEA, APAC.
- Valid KPIs: "ctr" (click-through rate) or "ivr" (in-view rate).
- Never invent numbers. Only state numbers returned by tools.
- Be terse. The user is a busy strategist."""


TOOLS = [
    {
        "name": "reset_brief",
        "description": (
            "Clear all fields on the current brief. Call this when the user starts "
            "describing a new client or brief, so leftover values from a prior "
            "brief do not bleed into the new one."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "set_brief_fields",
        "description": (
            "Set or update one or more fields on the current client brief. "
            "Call this whenever the user provides relevant information. "
            "Only include fields you can identify; omit unknown fields."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "advertiser": {"type": "string"},
                "vertical": {
                    "type": "string",
                    "enum": ["Retail", "Finance", "Travel", "QSR", "Entertainment"],
                },
                "kpi": {"type": "string", "enum": ["ctr", "ivr"]},
                "geo": {"type": "string", "enum": ["US", "EMEA", "APAC"]},
                "budget_usd": {"type": "number"},
                "impression_goal": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "generate_recommendation",
        "description": (
            "Run the recommendation algorithm against the current brief. "
            "Only call this once all required fields (vertical, kpi, geo, budget_usd) are set."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


class MediaAgent:
    def __init__(self):
        self.client = Anthropic()
        self.history: list[dict] = []
        self.brief = ClientBrief()
        self.latest_recommendation: Optional[Recommendation] = None

    def _brief_state_message(self) -> str:
        filled = self.brief.model_dump(exclude_none=True)
        missing = self.brief.missing_required()
        return (
            f"Current brief state: {json.dumps(filled) if filled else '(empty)'}. "
            f"Missing required fields: {missing if missing else 'none'}."
        )

    def _run_tool(self, name: str, args: dict) -> dict:
        if name == "reset_brief":
            self.brief = ClientBrief()
            self.latest_recommendation = None
            return {"ok": True, "brief": {}}
        if name == "set_brief_fields":
            for k, v in args.items():
                setattr(self.brief, k, v)
            return {
                "ok": True,
                "brief": self.brief.model_dump(exclude_none=True),
                "missing_required": self.brief.missing_required(),
            }
        if name == "generate_recommendation":
            missing = self.brief.missing_required()
            if missing:
                return {"ok": False, "error": f"Cannot recommend; missing {missing}"}
            rec = build_recommendation(self.brief)
            self.latest_recommendation = rec
            return {"ok": True, "recommendation": rec.model_dump()}
        return {"ok": False, "error": f"Unknown tool {name}"}

    def chat(self, user_message: str) -> str:
        """Run one user turn. Returns the assistant's final text response."""
        self.history.append({"role": "user", "content": user_message})

        # Inject the current brief state as a fresh system note each turn so the
        # model always knows what slots are already filled.
        system = SYSTEM_PROMPT + "\n\n" + self._brief_state_message()

        while True:
            resp = self.client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=system,
                tools=TOOLS,
                messages=self.history,
            )
            self.history.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                # Final text turn.
                return "".join(
                    b.text for b in resp.content if getattr(b, "type", None) == "text"
                )

            # Execute every tool_use block in this turn, return results together.
            tool_results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result = self._run_tool(block.name, block.input or {})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
            self.history.append({"role": "user", "content": tool_results})
            # Refresh state line for the next iteration.
            system = SYSTEM_PROMPT + "\n\n" + self._brief_state_message()
