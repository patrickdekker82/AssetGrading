"""Thin wrapper around the Anthropic SDK so the rest of the app (and the tests) see plain results."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field

# The SDK logs request lines at INFO; keep them out of the app log, like the data providers.
for name in ("anthropic", "httpx", "httpx2"):
    logging.getLogger(name).setLevel(logging.WARNING)


@dataclass
class LlmResult:
    """One answer: the text block(s), why the model stopped and the token usage. `error` when it failed."""

    stop_reason: str | None = None
    text: str = ""
    usage: dict = field(default_factory=dict)
    model: str | None = None
    request_id: str | None = None
    error: str | None = None


USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def from_message(msg) -> LlmResult:
    usage = {k: int(getattr(msg.usage, k, 0) or 0) for k in USAGE_FIELDS}
    text = "".join(b.text for b in msg.content if b.type == "text")
    return LlmResult(stop_reason=msg.stop_reason, text=text, usage=usage, model=msg.model,
                     request_id=getattr(msg, "_request_id", None) or getattr(msg, "id", None))


class AnthropicClient:
    """Direct calls and the Message Batches API (50% cheaper, results within 24 hours)."""

    def __init__(self, api_key: str):
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=120.0)

    def create(self, params: dict) -> LlmResult:
        try:
            return from_message(self._client.messages.create(**params))
        except self._anthropic.APIError as exc:
            return LlmResult(error=f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"[:500])

    def submit_batch(self, requests: list[tuple[str, dict]]) -> str:
        batch = self._client.messages.batches.create(
            requests=[{"custom_id": cid, "params": params} for cid, params in requests])
        return batch.id

    def batch_status(self, batch_id: str) -> str:
        """in_progress, canceling or ended."""
        return self._client.messages.batches.retrieve(batch_id).processing_status

    def cancel_batch(self, batch_id: str) -> None:
        self._client.messages.batches.cancel(batch_id)

    def batch_results(self, batch_id: str) -> Iterator[tuple[str, LlmResult]]:
        for item in self._client.messages.batches.results(batch_id):
            r = item.result
            if r.type == "succeeded":
                yield item.custom_id, from_message(r.message)
            elif r.type == "errored":
                yield item.custom_id, LlmResult(error=f"errored: {r.error.error.type}: {r.error.error.message}"[:500])
            else:
                yield item.custom_id, LlmResult(error=r.type)
