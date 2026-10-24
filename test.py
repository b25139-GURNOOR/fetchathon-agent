"""Tests for the Campus Workflow Agent.

    python test.py            # unit tests, then a live agent-to-agent test over the Chat Protocol
    python test.py --unit     # unit tests only (instant, no networking)
    pytest test.py            # unit tests under pytest

The live test starts the agent and a test client together in one process (no Agentverse account,
mailbox or open ports needed), sends real ChatMessages and checks the replies.
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
from datetime import datetime, timezone
from uuid import uuid4

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import agent as campus  # noqa: E402
from agent import build_reply, detect_intents, extract_college, extract_weather_place  # noqa: E402

# ------------------------------------------------------------------------------------------
# Unit tests
# ------------------------------------------------------------------------------------------


def test_agent_address_is_stable_for_the_seed():
    from uagents_core.identity import Identity

    # your existing address must not change when the seed isn't overridden
    assert Identity.from_seed(campus.SEED, 0).address == \
        "agent1q2tz9u0jxh6v07s5r84vua9ycdvpvkt63q2z3ddjfkhwflgzvs44uklhyl2"


def test_intents_basic():
    assert detect_intents("What's the weather tomorrow?") == {"weather"}
    assert detect_intents("Can you give me a DSA schedule?") == {"dsa", "schedule"}
    assert detect_intents("help with my Flask project") == {"project"}
    assert detect_intents("plan my week") == {"schedule"}


def test_intents_tolerate_typos():
    assert "weather" in detect_intents("weathr in mandi")
    assert "weather" in detect_intents("wather today")
    assert "dsa" in detect_intents("algoritm practice")
    assert "project" in detect_intents("my projct is late")
    assert "schedule" in detect_intents("make a schedul")


def test_intents_no_false_positives():
    # the original substring matching mistook all of these for weather / schedule / code requests
    for text in ["I'm training for placements", "my attempt at the lab failed", "please explain recursion",
                 "take the train to Delhi", "decode this message", "what is a terrain map"]:
        assert detect_intents(text) == set(), text


def test_college_extraction():
    assert extract_college("schedule for iit mandi") == "IIT Mandi"
    assert extract_college("What's the weather at IIT Mandi tomorrow?") == "IIT Mandi"
    assert extract_college("DSA plan at NIT Hamirpur please") == "NIT Hamirpur"
    assert extract_college("I study at Delhi Technological University") == "Delhi Technological University"
    assert extract_college("for College of Engineering Pune") == "College of Engineering Pune"
    assert extract_college("help for my college") is None                 # no name given
    assert extract_college("college of engineering") is None             # no preposition: not a name
    assert extract_college("no college mentioned here") is None
    assert extract_college("iit students need a plan") == "IIT"           # 'students' is not a campus name


def test_weather_place_extraction():
    assert extract_weather_place("weather in shimla tomorrow") == "Shimla"
    assert extract_weather_place("forecast for new delhi") == "New Delhi"
    assert extract_weather_place("what's the weather today") is None


FAKE_FORECAST = {"daily": {
    "time": ["2026-10-24", "2026-10-25", "2026-10-26"],
    "temperature_2m_max": [22.4, 21.0, 19.6], "temperature_2m_min": [9.1, 8.0, 7.5],
    "precipitation_probability_max": [10, 65, 20]}}


def _patch_network(monkeypatch=None, fail=False):
    def fake(url, params, timeout=6.0):
        if fail:
            raise RuntimeError("network down")
        if "geocoding" in url:
            return {"results": [{"name": "Shimla", "admin1": "Himachal Pradesh", "latitude": 31.1, "longitude": 77.17}]}
        return FAKE_FORECAST
    if monkeypatch:
        monkeypatch.setattr(campus, "fetch_json", fake)
    else:
        campus.fetch_json = fake


def test_weather_uses_real_forecast_data(monkeypatch):
    _patch_network(monkeypatch)
    out = asyncio.run(build_reply("what's the weather at IIT Mandi tomorrow?"))
    assert "IIT Mandi (Kamand)" in out                      # known campus, no geocoding call needed
    assert "Tomorrow:** 8–21 °C, rain chance 65%" in out    # numbers come from the API data
    assert "umbrella" in out                                # rain >= 50% triggers advice
    assert "verified" not in out.lower()


def test_weather_other_city_uses_geocoding(monkeypatch):
    _patch_network(monkeypatch)
    out = asyncio.run(build_reply("weather in shimla"))
    assert "Shimla, Himachal Pradesh" in out


def test_weather_failure_is_honest_not_fabricated(monkeypatch):
    _patch_network(monkeypatch, fail=True)
    out = asyncio.run(build_reply("weather at iit mandi"))
    assert "couldn't" in out and "°C" not in out


def test_dsa_schedule_vs_plan():
    sched = asyncio.run(build_reply("Can you give me a DSA schedule?"))
    assert "study schedule" in sched and "Weekly rotation" in sched
    plan = asyncio.run(build_reply("help me with dsa at iit mandi"))
    assert "practice plan - IIT Mandi" in plan


def test_project_and_schedule_and_help():
    assert "project checklist" in asyncio.run(build_reply("flask project help")).lower()
    assert "schedule template - IIT Mandi" in asyncio.run(build_reply("plan my timetable at iit mandi"))
    assert "Campus Workflow Agent" in asyncio.run(build_reply("asdf qwerty"))


def test_mern_gets_a_node_checklist_not_python(monkeypatch=None):
    for q in ["Checklist for my MERN project", "MERN stack checklist", "help with my mern project at iit mandi"]:
        out = asyncio.run(build_reply(q))
        assert "MERN project checklist" in out, q
        assert "package.json" in out and "Express" in out and "MongoDB" in out and "React" in out
        assert "requirements.txt" not in out and "pyproject" not in out and "Python version" not in out
        assert "Tell me your stack" not in out          # the user already told us
    assert "IIT Mandi" in asyncio.run(build_reply("help with my mern project at iit mandi"))


def test_other_stacks_are_recognised():
    assert "MEAN project checklist" in asyncio.run(build_reply("MEAN stack checklist"))
    assert "Angular" in asyncio.run(build_reply("MEAN stack checklist"))
    assert "MEVN project checklist" in asyncio.run(build_reply("my mevn project"))
    assert "Node.js project checklist" in asyncio.run(build_reply("node.js and express project"))
    dj = asyncio.run(build_reply("steps to deploy my django project"))
    assert "Django project checklist" in dj and "manage.py" in dj and "package.json" not in dj
    fl = asyncio.run(build_reply("Checklist for my Flask project"))
    assert "Python project checklist" in fl and "requirements.txt" in fl and "Tell me your stack" not in fl


def test_unknown_stack_asks_once_and_is_stack_neutral():
    out = asyncio.run(build_reply("help me finish my project"))
    assert "Tell me your stack" in out and "package.json" in out and "requirements.txt" in out


def test_stack_words_do_not_cause_false_positives():
    for text in ["what does mean in statistics", "reverse a linked list node", "I react badly to coffee",
                 "mean and median of an array"]:
        assert "project" not in detect_intents(text), text


def test_time_table_two_words():
    assert detect_intents("give me a time table") == {"schedule"}


def test_no_fabricated_claims_in_any_reply():
    for q in ["dsa", "project", "schedule", "hello"]:
        out = asyncio.run(build_reply(q)).lower()
        assert "verified" not in out and "executed automated" not in out


UNIT_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]


class _MP:
    """Tiny stand-in for pytest's monkeypatch so `python test.py` needs no pytest."""

    def __init__(self):
        self._undo = []

    def setattr(self, obj, name, value):
        self._undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, old in reversed(self._undo):
            setattr(obj, name, old)


def run_unit_tests() -> bool:
    ok = True
    for fn in UNIT_TESTS:
        mp = _MP()
        try:
            fn(mp) if "monkeypatch" in fn.__code__.co_varnames[: fn.__code__.co_argcount] else fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  FAIL  {fn.__name__}: {type(exc).__name__}: {exc}")
        finally:
            mp.undo()
    return ok


# ------------------------------------------------------------------------------------------
# Live test: real Chat Protocol messages between a client and the agent (in-process Bureau)
# ------------------------------------------------------------------------------------------

PROMPTS = [  # (prompt, substrings that must appear, substrings that must NOT appear)
    ("Can you give me a DSA schedule?", ["study schedule", "Weekly rotation"], ["Weather"]),
    ("What's the weather at IIT Mandi tomorrow?", ["IIT Mandi"], []),
    ("I'm training for placements", ["Campus Workflow Agent"], ["Weather outlook"]),
    ("asdf qwerty", ["I can help with"], []),
]


def _free_port(exclude: int = 0) -> int:
    """Ask the OS for an unused port, so the test never collides with a running agent.py."""
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port != exclude:
            return port


def run_live_test() -> int:
    from uagents import Agent, Bureau, Context, Protocol
    from uagents_core.contrib.protocols.chat import (
        ChatAcknowledgement, ChatMessage, EndSessionContent, TextContent, chat_protocol_spec,
    )

    loop = campus.ensure_event_loop()
    _patch_network(fail=False)  # deterministic weather, so the test also passes offline
    port = _free_port()
    # throwaway identity: the test must not touch your real agent's address or port
    target = campus.create_agent(mailbox=False, port=port, seed="campus_live_test_seed", loop=loop)
    client = Agent(name="test_client", seed="test_seed_123", port=_free_port(exclude=port), loop=loop)
    chat = Protocol(spec=chat_protocol_spec)
    state = {"i": 0, "failures": []}

    async def send_prompt(ctx: Context):
        prompt = PROMPTS[state["i"]][0]
        print(f"\n🧑 {prompt}", flush=True)
        await ctx.send(target.address, ChatMessage(
            timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
            content=[TextContent(type="text", text=prompt)]))

    @client.on_event("startup")
    async def start(ctx: Context):
        await asyncio.sleep(2)
        await send_prompt(ctx)

        async def watchdog():
            await asyncio.sleep(150)
            print("\n❌ Timed out waiting for the agent's reply", flush=True)
            os._exit(1)
        asyncio.create_task(watchdog())

    @chat.on_message(ChatMessage)
    async def on_reply(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        text = " ".join(c.text for c in msg.content if isinstance(c, TextContent))
        ended = any(isinstance(c, EndSessionContent) for c in msg.content)
        print(f"🤖 {text}\n", flush=True)
        _, must, must_not = PROMPTS[state["i"]]
        for s in must:
            if s not in text:
                state["failures"].append(f"prompt {state['i'] + 1}: missing {s!r}")
        for s in must_not:
            if s in text:
                state["failures"].append(f"prompt {state['i'] + 1}: unexpected {s!r}")
        if not ended:
            state["failures"].append(f"prompt {state['i'] + 1}: reply did not end the session")
        state["i"] += 1
        if state["i"] < len(PROMPTS):
            await send_prompt(ctx)
            return
        await asyncio.sleep(0.3)
        if state["failures"]:
            print("❌ LIVE TEST FAILED:\n  " + "\n  ".join(state["failures"]), flush=True)
            os._exit(1)
        print(f"✅ LIVE TEST PASSED ({len(PROMPTS)} prompts over the Agent Chat Protocol)", flush=True)
        os._exit(0)

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    client.include(chat)
    bureau = Bureau(port=port, loop=loop)
    bureau.add(target)
    bureau.add(client)
    bureau.run()
    return 1


if __name__ == "__main__":
    print("Unit tests")
    passed = run_unit_tests()
    if not passed:
        sys.exit(1)
    if "--unit" in sys.argv:
        print("\nAll unit tests passed.")
        sys.exit(0)
    print("\nLive test (starts the agent and a client in-process)...")
    sys.exit(run_live_test())
