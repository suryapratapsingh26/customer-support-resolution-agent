"""Minimal OpenAI-compatible chat completion client with no provider SDK dependency."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from app.schemas.resolution import ResolutionRecommendation


class LLMProviderError(RuntimeError):
    """Raised when the configured LLM cannot return a valid recommendation."""


class OpenAICompatibleProvider:
    def __init__(self, api_key: str | None, model: str, base_url: str, timeout: float = 30):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def recommend(self, payload: dict) -> ResolutionRecommendation:
        if not self.api_key:
            raise LLMProviderError("LLM provider is not configured.")
        system = (
            "You are a customer support recommendation assistant. Use only the supplied facts and policy excerpts. "
            "Never invent customer, order, payment, shipment, or policy facts. If information is absent, say so. "
            "Do not decide refund eligibility, calculate or assert an authoritative refund amount, execute any action, "
            "or imply that an action has been approved. Recommend human review. Return only a JSON object matching "
            "the requested schema, with no markdown."
        )
        schema = ResolutionRecommendation.model_json_schema()
        request_body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system + "\nSchema: " + json.dumps(schema)},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
        }
        request = Request(
            self.base_url + "/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
            content = decoded["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Completion content is not text.")
            result = ResolutionRecommendation.model_validate_json(content)
            # The model cannot override trusted workflow fields or suppress review.
            result.ticket_id = int(payload["ticket"]["id"])
            result.retrieved_knowledge_sources = payload["sources"]
            result.human_review_recommended = True
            return result
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, IndexError,
                TypeError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            raise LLMProviderError("LLM provider failed to return a valid recommendation.") from exc
