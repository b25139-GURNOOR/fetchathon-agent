"""Campus Workflow Agent - discoverable on ASI:One through the Agent Chat Protocol.

Run locally:   python agent.py
Then open the Agent Inspector link printed in the logs and click "Connect" -> "Mailbox"
so Agentverse / ASI:One can reach the agent running on your machine.
"""
from __future__ import annotations

import asyncio
import difflib
import os
import re
from datetime import date, datetime, timezone
from uuid import uuid4

import requests
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

try:  # optional: load CAMPUS_AGENT_SEED etc. from a .env file
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# The seed decides the agent's address. Keep it out of public repos: set CAMPUS_AGENT_SEED in .env.
# (The fallback is your original seed, so the address you already use doesn't change.)
SEED = os.getenv("CAMPUS_AGENT_SEED", "iit_mandi_campus_agent_seed_987")
DEFAULT_CAMPUS = os.getenv("DEFAULT_CAMPUS", "IIT Mandi")
PORT = int(os.getenv("CAMPUS_AGENT_PORT", "8000"))

DESCRIPTION = (
    "Campus workflow assistant for students: live 3-day campus weather forecast, DSA / coding "
    "practice plans and schedules, project checklists, and study-schedule templates."
)

# --------------------------------------------------------------------------------------------
# Event loop (Python 3.14 no longer creates one implicitly, and uAgents asks for it at startup)
# --------------------------------------------------------------------------------------------


def ensure_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


# --------------------------------------------------------------------------------------------
# Intent detection: whole-word matching + typo tolerance (no more "training" -> weather)
# --------------------------------------------------------------------------------------------

INTENT_WORDS = {
    "weather": {"weather", "forecast", "temperature", "temp", "rain", "climate", "umbrella", "humidity"},
    "dsa": {"dsa", "leetcode", "algorithm", "algorithms", "algo", "coding", "codeforces", "competitive",
            "datastructures", "structures"},
    "project": {"project", "projects", "flask", "simulation", "simulations", "simulator", "deployment",
                "deploy", "deploying", "backend", "frontend", "python", "mern", "mevn", "nodejs", "reactjs",
                "nextjs", "mongodb", "mongoose", "django", "fastapi"},
    "schedule": {"schedule", "timetable", "routine", "planner", "plan", "planning", "timing", "timings"},
}
# Only longer, distinctive words are fuzzy-matched; short ones ("rain", "temp") must match exactly,
# otherwise "train"/"attempt" would be mistaken for weather.
FUZZY_WORDS = {
    "weather": ["weather", "forecast", "temperature"],
    "dsa": ["algorithm", "algorithms", "leetcode", "codeforces"],
    "project": ["project", "projects", "simulation", "simulator", "deployment"],
    "schedule": ["schedule", "timetable", "planner"],
}
_FUZZY_LOOKUP = {w: intent for intent, words in FUZZY_WORDS.items() for w in words}


def detect_intents(query: str) -> set[str]:
    found: set[str] = set()
    q = re.sub(r"\btime\s+table\b", "timetable", query.lower())
    if re.search(r"\bmean\s+stack\b", q):  # "mean" alone is an ordinary English word
        found.add("project")
    for tok in re.findall(r"[a-z0-9]+", q):
        for intent, words in INTENT_WORDS.items():
            if tok in words:
                found.add(intent)
        if len(tok) >= 6 and tok not in _FUZZY_LOOKUP:
            close = difflib.get_close_matches(tok, _FUZZY_LOOKUP, n=1, cutoff=0.85)
            if close:
                found.add(_FUZZY_LOOKUP[close[0]])
    return found


# --------------------------------------------------------------------------------------------
# College / place extraction
# --------------------------------------------------------------------------------------------

ACRONYMS = {"iit", "nit", "iiit", "bits", "iim", "iiser", "iisc", "vit", "dtu", "nsut"}
_STOP_AFTER_ACRONYM = {"for", "and", "in", "at", "the", "is", "to", "students", "student", "campus", "or",
                       "of", "on", "tomorrow", "today", "please", "this", "next", "weather", "schedule"}


_SMALL_WORDS = {"of", "and", "the", "for"}


def _pretty(name: str) -> str:
    words = name.split()
    return " ".join(
        w.upper() if w in ACRONYMS else (w if (w in _SMALL_WORDS and i) else w.capitalize())
        for i, w in enumerate(words)
    )


def extract_college(query: str) -> str | None:
    """'iit mandi' -> 'IIT Mandi'; 'delhi technological university' -> 'Delhi Technological University'."""
    q = query.lower()
    m = re.search(r"\b(iiit|iisc|iiser|iit|nit|bits|iim)\b(?:[\s-]+([a-z]+))?", q)
    if m:
        name = m.group(1)
        second = m.group(2)
        if second and second not in _STOP_AFTER_ACRONYM:
            name += f" {second}"
        return _pretty(name)
    # "at Delhi Technological University", "for College of Engineering Pune" - needs a preposition,
    # so phrases like "my college" or "no college" are not mistaken for a campus name
    m = re.search(
        r"\b(?:at|for|from|in)\s+((?:[a-z]+\s+){0,3}?(?:university|institute|college)"
        r"(?:\s+of\s+[a-z]+(?:\s+[a-z]+)?)?)\b",
        q,
    )
    if m:
        name = re.sub(r"^(?:the|my|our|a|an)\s+", "", m.group(1).strip())
        if name not in {"university", "institute", "college"}:
            return _pretty(name)
    m = re.search(r"\buniversity\s+of\s+[a-z]+(?:\s+[a-z]+)?", q)
    return _pretty(m.group(0)) if m else None


def extract_weather_place(query: str) -> str | None:
    """'weather in Shimla tomorrow' -> 'Shimla' (None when no place is named)."""
    q = query.lower()
    m = re.search(r"\b(?:in|at|for|near|around|of)\s+([a-z][a-z ]{1,30})", q)
    if not m:
        return None
    words = []
    for w in m.group(1).split():
        if w in {"today", "tomorrow", "tonight", "please", "now", "this", "next", "weekend", "week",
                 "and", "is", "will", "be", "like", "right", "campus", "forecast", "weather"}:
            break
        words.append(w)
    return _pretty(" ".join(words)) if words else None


# --------------------------------------------------------------------------------------------
# Live weather (Open-Meteo: free, no API key)
# --------------------------------------------------------------------------------------------

KNOWN_CAMPUSES = {  # approximate coordinates, enough for a weather forecast
    "iit mandi": (31.7814, 76.9951, "IIT Mandi (Kamand)"),
    "iit delhi": (28.5450, 77.1926, "IIT Delhi"),
    "iit bombay": (19.1334, 72.9133, "IIT Bombay"),
    "iit madras": (12.9915, 80.2337, "IIT Madras"),
    "iit kanpur": (26.5123, 80.2329, "IIT Kanpur"),
    "iit kharagpur": (22.3149, 87.3105, "IIT Kharagpur"),
}


def fetch_json(url: str, params: dict, timeout: float = 6.0) -> dict:
    r = requests.get(url, params=params, timeout=timeout,
                     headers={"User-Agent": "campus-workflow-agent/1.0"})
    r.raise_for_status()
    return r.json()


def resolve_place(name: str) -> tuple[float, float, str]:
    known = KNOWN_CAMPUSES.get(name.strip().lower())
    if known:
        return known
    data = fetch_json("https://geocoding-api.open-meteo.com/v1/search", {"name": name, "count": 1})
    hit = (data.get("results") or [None])[0]
    if not hit:
        raise LookupError(name)
    label = ", ".join(x for x in (hit.get("name"), hit.get("admin1")) if x)
    return hit["latitude"], hit["longitude"], label or name


def _day_label(iso: str, i: int) -> str:
    if i == 0:
        return "Today"
    if i == 1:
        return "Tomorrow"
    return date.fromisoformat(iso).strftime("%A")


def format_forecast(place: str, daily: dict) -> str:
    lines = [f"🌤️ **3-day weather outlook for {place}**", ""]
    for i, day in enumerate(daily["time"]):
        hi, lo = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        rain = daily.get("precipitation_probability_max", [None] * 3)[i]
        extra = f", rain chance {rain}%" if rain is not None else ""
        lines.append(f"• **{_day_label(day, i)}:** {lo:.0f}–{hi:.0f} °C{extra}")
    peak = max((r or 0) for r in daily.get("precipitation_probability_max", [0]))
    if peak >= 50:
        lines += ["", "☔ Good chance of rain on at least one day - carry an umbrella."]
    lines += ["", "_Live data from Open-Meteo._"]
    return "\n".join(lines)


async def weather_report(place_query: str | None) -> str:
    name = place_query or DEFAULT_CAMPUS
    try:
        lat, lon, label = await asyncio.to_thread(resolve_place, name)
    except LookupError:
        return f"I couldn't find a place called **{name}**. Try a city or campus name, e.g. *weather at IIT Mandi*."
    except Exception:  # noqa: BLE001 - network problems must not crash the agent
        return "I couldn't reach the weather service just now. Please try again in a minute."
    try:
        data = await asyncio.to_thread(
            fetch_json,
            "https://api.open-meteo.com/v1/forecast",
            {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
             "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"},
        )
        return format_forecast(label, data["daily"])
    except Exception:  # noqa: BLE001
        return "I couldn't fetch the live forecast just now. Please try again in a minute."


# --------------------------------------------------------------------------------------------
# Plans and checklists (templates - clearly labelled as such)
# --------------------------------------------------------------------------------------------


def dsa_plan(college: str) -> str:
    return (
        f"🎯 **DSA practice plan - {college}**\n\n"
        "1. **Concept review (30 min):** one topic at a time - arrays, trees, graphs, DP.\n"
        "2. **Implementation:** solve problems in C++ or Python; start with the brute force, then optimise.\n"
        "3. **Complexity check:** write down time and space (e.g. $O(N)$, $O(N \\log N)$) for every solution.\n"
        "4. **Edge cases:** empty input, single element, duplicates, maximum constraints.\n\n"
        "Ask for a *DSA schedule* if you want this split into daily time blocks."
    )


def dsa_schedule(college: str) -> str:
    return (
        f"🎯 **DSA study schedule - {college}** (about 2.5 hours/day)\n\n"
        "**Daily blocks**\n"
        "• 0:00–0:30 - revise one concept\n"
        "• 0:30–1:45 - solve 2–3 problems (1 easy warm-up, 1–2 medium)\n"
        "• 1:45–2:15 - review: complexity + edge cases for each solution\n"
        "• 2:15–2:30 - log mistakes and what to revisit\n\n"
        "**Weekly rotation**\n"
        "• Mon Arrays/Strings · Tue Linked lists/Stacks/Queues · Wed Trees · Thu Graphs · "
        "Fri Dynamic programming · Sat Timed mock contest · Sun Revision of logged mistakes\n\n"
        "_This is a template - shift the blocks around your lectures and labs._"
    )


def detect_stack(query: str) -> str | None:
    """Which tech stack did the user name? -> 'mern' | 'mevn' | 'mean' | 'node' | 'django' | 'python' | None"""
    q = query.lower()
    toks = set(re.findall(r"[a-z0-9]+", q))
    for key in ("mern", "mevn"):
        if key in toks:
            return key
    if re.search(r"\bmean\s+stack\b", q):
        return "mean"
    if "django" in toks:
        return "django"
    if toks & {"nodejs", "reactjs", "nextjs", "mongodb", "mongoose"} or (
            "node" in toks and toks & {"js", "express", "expressjs"}) or ("express" in toks and "js" in toks):
        return "node"
    if toks & {"flask", "fastapi", "python"}:
        return "python"
    return None


_NODE_FRONTEND = {"mern": ("MERN", "React"), "mevn": ("MEVN", "Vue"), "mean": ("MEAN", "Angular"),
                  "node": ("Node.js", "your frontend")}


def _node_checklist(stack: str, college: str) -> str:
    label, ui = _NODE_FRONTEND[stack]
    return (
        f"⚙️ **{label} project checklist - {college}**\n\n"
        "1. **Environment:** pin a Node LTS version (`engines` in `package.json` or an `.nvmrc`), commit "
        "`package-lock.json`, and keep secrets in `.env` with a committed `.env.example`. "
        "A common layout is separate `client/` and `server/` folders, each with its own `package.json`.\n"
        "2. **Backend (Node + Express + MongoDB):** read `MONGODB_URI` and `PORT` from env, connect with "
        "Mongoose, split routes / controllers / models, validate input, add one central error handler, "
        "and configure CORS for your frontend's origin. Add auth (JWT + hashed passwords) if you need accounts.\n"
        f"3. **Frontend ({ui}):** set the API base URL from an env variable, handle loading and error "
        "states for every request, and guard protected routes.\n"
        "4. **Before you submit or deploy:** make sure `npm start`, `npm run build` and `npm test` work from a "
        "clean clone, allow your server's IP in MongoDB Atlas, set the production env vars on your host, "
        "and put the setup steps in the README."
    )


def _django_checklist(college: str) -> str:
    return (
        f"⚙️ **Django project checklist - {college}**\n\n"
        "1. **Environment:** use a virtualenv, pin `requirements.txt`, and note the Python version.\n"
        "2. **Settings:** read `SECRET_KEY`, `DEBUG` and database settings from env; set `ALLOWED_HOSTS`.\n"
        "3. **App logic:** models + migrations (`makemigrations`, `migrate`), keep business logic out of views, "
        "write tests with `python manage.py test`.\n"
        "4. **Before you submit or deploy:** `DEBUG=False`, run `collectstatic`, and put setup steps in the README."
    )


def _python_checklist(college: str) -> str:
    return (
        f"⚙️ **Python project checklist - {college}**\n\n"
        "1. **Environment:** pin dependencies (`requirements.txt` / `pyproject.toml`) and note the Python version.\n"
        "2. **Backend:** keep core logic in plain functions so it can be tested without the web layer.\n"
        "3. **Frontend / API:** connect user input to your endpoints and handle error states.\n"
        "4. **Before you submit:** run the tests, write setup steps in the README, and deploy or record a demo."
    )


def _generic_checklist(college: str) -> str:
    return (
        f"⚙️ **Project checklist - {college}**\n\n"
        "1. **Environment:** pin dependencies in your stack's manifest (`package.json`, `requirements.txt`, "
        "`pom.xml`, ...) and note the runtime version.\n"
        "2. **Backend:** keep core logic separate from the web layer so it can be tested on its own.\n"
        "3. **Frontend / API:** connect user input to your endpoints and handle loading and error states.\n"
        "4. **Before you submit:** run the tests from a clean clone, write setup steps in the README, and "
        "deploy or record a demo.\n\n"
        "Tell me your stack (e.g. *MERN*, *Flask*, *Django*) and I'll make this specific."
    )


def project_checklist(college: str, query: str = "") -> str:
    stack = detect_stack(query)
    if stack in _NODE_FRONTEND:
        return _node_checklist(stack, college)
    if stack == "django":
        return _django_checklist(college)
    if stack == "python":
        return _python_checklist(college)
    return _generic_checklist(college)


def generic_schedule(college: str) -> str:
    return (
        f"📅 **Academic schedule template - {college}**\n\n"
        "• **09:00–11:30:** lectures and coursework\n"
        "• **14:00–17:00:** lab / practical or project work\n"
        "• **19:00–20:30:** coding practice and problem solving\n\n"
        "_This is a starting template. Send me your actual timetable and goals and I'll adjust it._"
    )


HELP = (
    "👋 I'm the **Campus Workflow Agent**. I can help with:\n\n"
    "• **Weather** - e.g. *weather at IIT Mandi tomorrow* (live forecast)\n"
    "• **DSA** - e.g. *give me a DSA schedule*\n"
    "• **Projects** - e.g. *checklist for my MERN project* (also Flask, Django)\n"
    "• **Study schedule** - e.g. *plan my week*\n\n"
    "Mention your college (like *IIT Mandi*) and I'll personalise the answer."
)


async def build_reply(query: str) -> str:
    intents = detect_intents(query)
    college = extract_college(query)
    label = college or "your campus"

    if "weather" in intents:
        return await weather_report(extract_weather_place(query) or college)
    if "dsa" in intents:
        return dsa_schedule(label) if "schedule" in intents else dsa_plan(label)
    if "project" in intents:
        return project_checklist(label, query)
    if "schedule" in intents:
        return generic_schedule(label)
    return HELP


# --------------------------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------------------------


def _reply(text: str, end_session: bool = True) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def create_agent(
    mailbox: bool = True, port: int = PORT, seed: str | None = None, loop: asyncio.AbstractEventLoop | None = None
) -> Agent:
    kwargs = {}
    readme = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")
    if os.path.exists(readme):
        kwargs["readme_path"] = readme

    agent = Agent(
        name="campus_workflow_agent",
        seed=seed or SEED,
        port=port,
        mailbox=mailbox,               # lets ASI:One reach an agent running on your laptop
        description=DESCRIPTION,
        publish_agent_details=True,
        loop=loop,
        network="testnet",
        **kwargs,
    )

    # The Agent Chat Protocol is what ASI:One speaks. A custom ChatMessage model will not work.
    chat = Protocol(spec=chat_protocol_spec)

    @chat.on_message(ChatMessage)
    async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))

        text = " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
        if not text:
            if any(isinstance(c, StartSessionContent) for c in msg.content):
                await ctx.send(sender, _reply(HELP, end_session=False))
            return
        ctx.logger.info(f"query from {sender[:16]}...: {text}")
        try:
            answer = await build_reply(text)
        except Exception:  # noqa: BLE001 - always answer something
            ctx.logger.exception("failed to build reply")
            answer = "Sorry, something went wrong on my side. Please try again."
        await ctx.send(sender, _reply(answer))

    @chat.on_message(ChatAcknowledgement)
    async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        ctx.logger.debug(f"ack for {msg.acknowledged_msg_id}")

    @agent.on_event("startup")
    async def on_start(ctx: Context):
        ctx.logger.info("Campus Workflow Agent started")
        ctx.logger.info(f"Agent address: {ctx.agent.address}")

    agent.include(chat, publish_manifest=True)
    return agent


if __name__ == "__main__":
    create_agent(loop=ensure_event_loop()).run()
