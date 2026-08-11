"""The generic validated-generate loop, driven by the mock provider."""

import json
from datetime import datetime, timedelta

from elifelse.providers.base import CompletionResult
from elifelse.providers.budget import TokenBudget
from elifelse.providers.mock import MockProvider
from elifelse.structured.registry import menu_schema

MENU = menu_schema(["A", "B"])


async def test_scripted_playback(config):
    p = MockProvider(config, script=[{"thinking": "t1", "choice": "B"}])
    result = await p.generate("pick one", schema=MENU)
    assert result["choice"] == "B"


async def test_invalid_then_valid_retries(config):
    p = MockProvider(
        config,
        script=[
            "garbage not json",
            json.dumps({"thinking": "t", "choice": "NOPE"}),
            {"thinking": "t", "choice": "A"},
        ],
    )
    result = await p.generate("pick", schema=MENU)
    assert result["choice"] == "A"
    assert len(p.calls) == 3


async def test_always_invalid_returns_error_never_bad_value(config):
    bad = json.dumps({"thinking": "t", "choice": "ESCAPE"})
    p = MockProvider(config, script=[bad] * 10)
    result = await p.generate("pick", schema=MENU)
    assert "error" in result
    assert "choice" not in result  # the bad value never reaches the caller
    assert len(p.calls) == 5  # exactly 5 attempts


# ~~~ transient failures ~~~
RATE_LIMITED = '429: {"error":{"message":"temporarily rate-limited upstream"}}'


def _waiting_provider(config, script):
    """A mock that records what it was asked to sleep for instead of sleeping."""
    p = MockProvider(config, script=script)
    waits: list[float] = []

    async def _record(seconds: float) -> None:
        waits.append(seconds)

    p._sleep = _record
    return p, waits


async def test_rate_limit_is_waited_out_and_the_call_succeeds(config):
    p, waits = _waiting_provider(
        config,
        [
            CompletionResult(text=None, error=RATE_LIMITED),
            CompletionResult(text=None, error="connection_error: server disconnected"),
            {"thinking": "finally", "choice": "A"},
        ],
    )
    result = await p.generate("pick", schema=MENU, skip_delay=True)
    assert result["choice"] == "A"
    # Backoff doubles: roughly 5s then 10s, plus jitter.
    assert len(waits) == 2
    assert 5 <= waits[0] < 6.5
    assert 10 <= waits[1] < 13


async def test_waiting_out_a_rate_limit_does_not_spend_a_validation_attempt(config):
    """The model never answered, so there's nothing to hold against it: all
    five attempts are still there once the provider comes back."""
    p, _ = _waiting_provider(
        config,
        [CompletionResult(text=None, error=RATE_LIMITED)] * 3
        + [json.dumps({"thinking": "t", "choice": "ESCAPE"})] * 5,
    )
    result = await p.generate("pick", schema=MENU, skip_delay=True)
    assert "error" in result
    assert len(p.calls) == 8  # 3 waited out + 5 real attempts


async def test_a_permanent_error_is_not_retried(config):
    """Waiting can't fix a bad key, so the caller hears about it immediately."""
    p, waits = _waiting_provider(
        config,
        [CompletionResult(text=None, error="401: invalid api key")]
        + [{"thinking": "t", "choice": "A"}],
    )
    result = await p.generate("pick", schema=MENU, skip_delay=True)
    assert result["error"].startswith("401")
    assert waits == []
    assert len(p.calls) == 1


async def test_retries_give_up_and_report_the_error(config):
    config.provider.transient_retries = 2
    p, waits = _waiting_provider(
        config, [CompletionResult(text=None, error=RATE_LIMITED)] * 5
    )
    result = await p.generate("pick", schema=MENU, skip_delay=True)
    assert "429" in result["error"]
    assert len(waits) == 2  # capped by transient_retries
    assert len(p.calls) == 3


async def test_transient_retries_can_be_turned_off(config):
    config.provider.transient_retries = 0
    p, waits = _waiting_provider(
        config, [CompletionResult(text=None, error=RATE_LIMITED)]
    )
    assert "error" in await p.generate("pick", schema=MENU, skip_delay=True)
    assert waits == []


async def test_background_calls_wait_out_rate_limits_too(config):
    p, waits = _waiting_provider(
        config,
        [CompletionResult(text=None, error=RATE_LIMITED), "a summary"],
    )
    assert await p.raw_completion([{"role": "user", "content": "summarize"}]) == "a summary"
    assert len(waits) == 1


async def test_the_next_call_waits_instead_of_charging_on(config):
    """Giving up must not turn into a fast loop: whatever calls next pauses
    first, and the pause grows while the outage lasts."""
    config.provider.transient_retries = 1
    p, waits = _waiting_provider(
        config, [CompletionResult(text=None, error=RATE_LIMITED)] * 6
    )
    await p.generate("pick", schema=MENU, skip_delay=True)   # gives up
    assert p.transient_failures == 1
    waits.clear()

    await p.generate("pick", schema=MENU, skip_delay=True)   # waits first
    assert len(waits) == 2  # the hold-off, then the one in-call retry
    assert waits[0] >= 5
    assert p.transient_failures == 2

    waits.clear()
    await p.generate("pick", schema=MENU, skip_delay=True)
    assert waits[0] >= 10  # longer each time it stays down


async def test_the_hold_off_clears_once_the_provider_answers(config):
    p, waits = _waiting_provider(
        config, [{"thinking": "t", "choice": "A"}]
    )
    p.transient_failures = 3
    result = await p.generate("pick", schema=MENU, skip_delay=True)
    assert result["choice"] == "A"
    assert len(waits) == 1  # waited once, then it worked
    assert p.transient_failures == 0


async def test_a_rejected_response_is_not_treated_as_an_outage(config):
    """The model answering with nonsense means it's up, so nothing holds off."""
    p, waits = _waiting_provider(
        config, [json.dumps({"thinking": "t", "choice": "ESCAPE"})] * 5
    )
    assert "error" in await p.generate("pick", schema=MENU, skip_delay=True)
    assert p.transient_failures == 0
    assert waits == []


async def test_auto_mode_picks_option(config):
    p = MockProvider(config, always_option=1)
    result = await p.generate("pick", schema=MENU)
    assert result["choice"] == "B"


async def test_context_grows_and_assistant_stored(config):
    p = MockProvider(config, script=[{"thinking": "t", "response": "hi there", "return_to_menu": False}])
    schema = {
        "type": "object",
        "properties": {
            "thinking": {"type": "string"},
            "response": {"type": "string"},
            "return_to_menu": {"type": "boolean"},
        },
        "required": ["thinking", "response", "return_to_menu"],
        "additionalProperties": False,
    }
    await p.generate("hello", schema=schema)
    roles = [m["role"] for m in p.context.messages]
    assert roles == ["user", "assistant"]
    assert "hi there" in p.context.messages[1]["content"]


async def test_skip_context_isolated_call(config):
    p = MockProvider(config)
    p.set_system_prompt("sys")
    await p.generate("isolated question", schema=MENU, skip_context=True)
    assert len(p.context.messages) == 0
    sent = p.calls[0]["messages"]
    assert sent[0]["role"] == "system"
    assert "isolated question" in sent[1]["content"]


async def test_raw_completion_no_context(config):
    p = MockProvider(config, script=["a raw summary"])
    out = await p.raw_completion([{"role": "user", "content": "summarize"}])
    assert out == "a raw summary"
    assert len(p.context.messages) == 0
    assert p.calls[0]["raw"] is True


async def test_budget_trips_and_resets(config):
    fake_now = datetime(2026, 7, 3, 12, 0, 0)

    def clock():
        return fake_now

    budget = TokenBudget(daily_limit=10, clock=clock)
    p = MockProvider(config)
    p.budget = budget

    long_reply = {"thinking": "x" * 200, "choice": "A"}
    p.feed(long_reply)
    await p.generate("pick", schema=MENU)
    assert budget.used > 0
    budget.record(1000)
    assert budget.exceeded

    # Next day: resets
    fake_now = fake_now + timedelta(days=1)
    assert not budget.exceeded
    assert budget.used == 0


async def test_unlimited_budget_never_exceeded(config):
    b = TokenBudget(daily_limit=0)
    b.record(10_000_000)
    assert not b.exceeded
    assert b.remaining is None


async def test_utility_model_routing(config):
    config.provider.utility_model = "small-model"
    p = MockProvider(config, script=["ok"])
    await p.raw_completion([{"role": "user", "content": "x"}])
    assert p.calls[0]["model"] == "small-model"


async def test_schema_registry_decorators():
    from elifelse.structured.registry import SchemaRegistry

    reg = SchemaRegistry()

    def add_speech(schema):
        schema["properties"]["speech"] = {"type": "string"}
        schema["required"] = list(schema.get("required", [])) + ["speech"]
        return schema

    reg.add_decorator("speech", add_speech)
    plain = reg.menu(["A"])
    assert "speech" not in plain["properties"]
    reg.activate_decorator("speech")
    decorated = reg.menu(["A"])
    assert "speech" in decorated["properties"]
    assert "speech" in decorated["required"]
    reg.deactivate_decorator("speech")
    assert "speech" not in reg.menu(["A"])["properties"]
    # core schema untouched
    assert "speech" not in reg.get("chat_response")["properties"]
