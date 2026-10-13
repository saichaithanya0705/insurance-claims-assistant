"""One small real call per role through the configured Anthropic models: does the key work, do the model names exist, does a forced
tool call come back in the schema, and how long does each take?

    python scripts/test_live_anthropic.py

Reads ANTHROPIC_API_KEY and the model names from `.env.local` (git-ignored). Prints model, seconds and token counts only: never the key,
never the claim text beyond a one-line synthetic example. Costs a few cents at most.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.agents.stage_agents import Agents
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.llm.client import CompletionClient, CompletionError


def main() -> int:
    settings = Settings()
    if settings.llm_provider != "anthropic":
        print("LLM_PROVIDER is not 'anthropic'; set it in .env.local (see .env.local.example).")
        return 2
    print(f"key configured: {bool(settings.anthropic_api_key.get_secret_value())} (length {len(settings.anthropic_api_key.get_secret_value())})")
    events: list[tuple] = []
    agents = Agents(settings, lambda *a, **k: events.append(a))
    claim = ClaimInput.model_validate(DEMO_CASES[0]["claim"])
    evidence = [{"source_id": "claim:input", "title": "Submitted claim", "text": str(claim.model_dump(mode="json")), "provenance": "user_input"}]
    steps = (
        ("classification", lambda: agents.classify(claim, "live-check")),
        ("investigation", lambda: agents.investigate(claim, evidence, [], "live-check")),
    )
    failed = 0
    for purpose, call in steps:
        started = time.perf_counter()
        try:
            result = call()
            usage = next((e[2].get("usage") for e in reversed(events) if e[1] == "model_output"), {})
            print(f"{purpose:15s} ok   {settings.model_for(purpose):18s} {time.perf_counter() - started:5.1f}s  tokens {usage}  -> {str(result)[:90]}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            kinds = [e[2].get("error_kind") or e[2].get("status_code") for e in events if e[1] == "model_failure"]
            print(f"{purpose:15s} FAIL {settings.model_for(purpose):18s} {type(error).__name__}: {error} {kinds}")
    # the shortest structured call that is not a role of the application, to see the raw round trip and the recommendation model
    from claims.agents.stage_agents import Recommendations

    for name in {settings.model_for("recommendation"), settings.model_for("intake")}:
        started = time.perf_counter()
        try:
            out = CompletionClient(settings, lambda *a, **k: None).complete(
                [{"role": "system", "content": "Return the answer in the structure given."},
                 {"role": "user", "content": "One action: verify submitted facts, citing claim:input, reason 'Check the dates.'"}],
                Recommendations, model=name, run_id="live-check",
            )
            print(f"{'round trip':15s} ok   {name:18s} {time.perf_counter() - started:5.1f}s  -> {out.recommendations[0].action}")
        except CompletionError as error:
            failed += 1
            print(f"{'round trip':15s} FAIL {name:18s} {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
