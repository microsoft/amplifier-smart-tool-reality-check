"""Token use and cost, summed from the `usage` events an agent provider reports."""

from collections import defaultdict
from typing import Any

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")
NANO = 1e9


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Model calls, tokens, and the provider's own cost, in total and by model.

    For Copilot, `aiu` is `copilot_usage.totalNanoAiu` summed over calls, in AIU, which matches the session's own
    total. Each call's `cost` is the model's premium request multiplier, not a count, so it is kept per model.
    Agent providers that price in money report `cost` by currency, summed as `usd`.
    """
    by_model: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for event in events:
        if event.get("kind") != "usage":
            continue
        data = event.get("data", {})
        totals = by_model[data.get("model") or "unknown"]
        totals["calls"] += 1
        for field in TOKEN_FIELDS:
            totals[field] += data.get(field) or 0
        totals["aiu"] += ((data.get("copilot_usage") or {}).get("totalNanoAiu") or 0) / NANO
        cost = data.get("cost")
        if isinstance(cost, dict):
            totals["usd"] += cost.get("USD") or 0
        elif cost is not None:
            totals["multiplier"] = cost
    total: dict[str, float] = defaultdict(float)
    for totals in by_model.values():
        for field, value in totals.items():
            if field != "multiplier":
                total[field] += value
    return {**total, "by_model": {model: dict(totals) for model, totals in by_model.items()}}
