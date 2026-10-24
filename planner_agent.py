"""AGENT 2 (harder): Trip Planner Agent (orchestrator)."""
from dotenv import load_dotenv

load_dotenv()

import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
import json
import math
import os
import re

import requests
from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    chat_protocol_spec, ChatMessage, ChatAcknowledgement,
)

from booking_links import build_links
from common import (WeatherRequest, WeatherResponse, FreeSlotsRequest,
                    FreeSlotsResponse, ack, say, text_of)

load_dotenv()
mailbox_key = os.getenv("MAILBOX_KEY")
print("API Key loaded:", bool(os.getenv("MAILBOX_KEY")))
agent = Agent(
    name="trip-planner-agent",
    seed=os.environ["PLANNER_SEED"],
    port=8012,
    network="testnet",
    mailbox=f"{mailbox_key}@https://agentverse.ai",
)
chat_proto = Protocol(spec=chat_protocol_spec)

WEATHER_ADDR = os.getenv("WEATHER_AGENT_ADDRESS", "")
COLLEGE_ADDR = os.getenv("COLLEGE_AGENT_ADDRESS", "")
REQUIRED = ["origin", "destination", "days", "budget"]

INVALID_CITIES = {"whether", "go", "trip", "plan", "somewhere", "place", "near", "around", "bunk"}

TRANSPORT = {
    "manali": (1800, 2800, 6500), "shimla": (1200, 2200, 5000),
    "rishikesh": (700, 1500, 4000), "jaipur": (600, 1200, 3500),
    "goa": (3500, 5500, 9000), "lonavala": (500, 1000, 2500), "alibaug": (400, 900, 2200),
}
TIERS = ["Budget", "Comfort", "Premium"]
STAY_PER_ROOM_NIGHT = (800, 2000, 4500)
FOOD_PER_PERSON_DAY = (400, 700, 1200)
ACTIVITIES_PER_PERSON_DAY = (300, 600, 1200)
TIER_NOTES = {
    "manali": ("Overnight Volvo bus, guesthouse", "AC Volvo, 3-star hotel", "Cab/flight to Bhuntar, resort"),
    "shimla": ("Volvo bus, budget hotel", "AC bus, 3-star hotel", "Private cab, luxury resort"),
    "lonavala": ("Local train/bus, cottage", "AC bus, resort", "Private cab, premium villa"),
}

async def send_with_retry(ctx, destination, message, retries=3):
    for attempt in range(retries):
        try:
            await ctx.send(destination, message)
            ctx.logger.info("Message delivered successfully!")
            return
        except Exception as e:
            ctx.logger.warning(f"Attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2)
    ctx.logger.error("Failed to deliver message after multiple retries.")


def llm_parse(text: str):
    key = os.getenv("MAILBOX_KEY")
    if not key:
        return None
    try:
        prompt = ("Extract a trip request from the user's message. Reply with ONLY JSON: "
                  '{"origin": str|null, "destination": str|null, "days": int|null, '
                  '"budget": int|null (total in INR), "travellers": int|null}')
        r = requests.post(
            "https://api.asi1.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "asi1-mini", "temperature": 0,
                  "messages": [{"role": "system", "content": prompt},
                               {"role": "user", "content": text}]},
            timeout=15)
        content = r.json()["choices"][0]["message"]["content"]
        return json.loads(re.search(r"\{.*\}", content, re.S).group())
    except Exception:
        return None


MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_date(text: str):
    from datetime import date
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*", text, re.I)
    if not m:
        return None
    today = date.today()
    try:
        d = date(today.year, MONTHS[m.group(2).lower()], int(m.group(1)))
        if d < today:
            d = d.replace(year=today.year + 1)
        return d.isoformat()
    except ValueError:
        return None


def regex_parse(text: str) -> dict:
    out = {}
    d = parse_date(text)
    if d:
        out["date"] = d
    m = re.search(r"from\s+([A-Za-z]+(?: [A-Za-z]+)?)\s+to\s+([A-Za-z]+)", text, re.I) \
        or re.search(r"([A-Za-z]+)\s+to\s+([A-Za-z]+)", text, re.I)
    if m:
        out["origin"], out["destination"] = m.group(1).strip(), m.group(2).strip()
    
    # Also check if a known destination is explicitly named in the text (e.g., "Shimla", "Lonavala")
    t_lower = text.lower()
    for dest in TRANSPORT.keys():
        if dest in t_lower and "destination" not in out:
            out["destination"] = dest.title()

    m = re.search(r"(\d+)\s*(?:day|days|night|nights)", text, re.I)
    if m:
        out["days"] = int(m.group(1))
    m = re.search(r"(?:₹|rs\.?|inr|under|budget(?: of)?)\s*([\d,]+(?:\.\d+)?)\s*(k)?", text, re.I)
    if m:
        val = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        if val >= 1000:
            out["budget"] = int(val)
    m = re.search(r"(\d+)\s*(?:people|persons|travellers|travelers|friends|pax)", text, re.I)
    if m:
        out["travellers"] = int(m.group(1))
    elif re.search(r"\bsolo\b|\balone\b", text, re.I):
        out["travellers"] = 1
    return out


def validate_city(city: str) -> str:
    if not city:
        return ""
    cleaned = city.strip().lower()
    if cleaned in INVALID_CITIES or len(cleaned) < 3:
        return ""
    return city.strip()


def understand(text: str) -> dict:
    data = {k: v for k, v in (llm_parse(text) or {}).items() if v is not None}
    regex_data = regex_parse(text)
    for k, v in regex_data.items():
        data.setdefault(k, v)
        
    if "destination" in data:
        valid_dest = validate_city(data["destination"])
        if not valid_dest:
            data.pop("destination", None)
            
    if "origin" in data:
        valid_orig = validate_city(data["origin"])
        if valid_orig:
            data["origin"] = valid_orig
        else:
            data["origin"] = "Mumbai" if "mumbai" in text.lower() else "Delhi"
            
    return data


def build_packages(req: dict):
    dest = req["destination"].strip().lower()
    n = int(req.get("travellers", 1))
    days = int(req["days"])
    nights = max(1, days - 1)
    rooms = math.ceil(n / 2)
    transport = TRANSPORT.get(dest, (1000, 2000, 4000)) # default fallback pricing
    pkgs = []
    for i, name in enumerate(TIERS):
        t = (transport[i] * n)
        stay = STAY_PER_ROOM_NIGHT[i] * rooms * nights
        food = FOOD_PER_PERSON_DAY[i] * n * days
        act = ACTIVITIES_PER_PERSON_DAY[i] * n * days
        pkgs.append({"tier": name, "transport": t, "stay": stay, "food": food,
                     "activities": act, "total": t + stay + food + act,
                     "note": TIER_NOTES.get(dest, ("", "", ""))[i]})
    return pkgs, dest in TRANSPORT


async def get_weather(ctx: Context, city: str, days: int) -> str:
    if not WEATHER_ADDR:
        return "_(Weather agent not configured, skipped.)_"
    for attempt in (1, 2):
        try:
            reply, status = await ctx.send_and_receive(
                WEATHER_ADDR, WeatherRequest(city=city, days=min(days, 7)),
                response_type=WeatherResponse, timeout=25)
            if isinstance(reply, WeatherResponse):
                return reply.summary if reply.ok else f"_(Weather unavailable: {reply.error})_"
            ctx.logger.warning(f"weather attempt {attempt} failed: {status}")
        except Exception as e:
            ctx.logger.warning(f"weather attempt {attempt} error: {e}")
    return "_(Weather agent didn't respond, so the forecast is skipped. Plan is still valid.)_"


async def get_free_windows(ctx: Context, days: int):
    if not COLLEGE_ADDR:
        return []
    for attempt in (1, 2):
        try:
            reply, status = await ctx.send_and_receive(
                COLLEGE_ADDR, FreeSlotsRequest(days_needed=days),
                response_type=FreeSlotsResponse, timeout=25)
            if isinstance(reply, FreeSlotsResponse):
                return reply.windows if reply.ok else []
            ctx.logger.warning(f"college attempt {attempt} failed: {status}")
        except Exception as e:
            ctx.logger.warning(f"college attempt {attempt} error: {e}")
    return []


def inr(x: int) -> str:
    return f"₹{x:,}"


def llm_format_travel_response(req: dict, pkgs: list, weather: str, windows: list) -> str:
    key = os.getenv("MAILBOX_KEY")
    if not key:
        return None
    try:
        prompt = (
            "You are an elite, enthusiastic AI travel concierge. "
            "Given the user's trip request, calculated budget packages, weather forecast, and college free windows, "
            "craft a polished, engaging, narrative-driven travel itinerary and budget breakdown."
        )
        payload = {
            "request": req,
            "packages": pkgs,
            "weather": weather,
            "free_windows": [w.dict() for w in windows] if windows else []
        }
        resp = requests.post(
            "https://api.asi1.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "asi1-mini", "temperature": 0.7,
                  "messages": [{"role": "system", "content": prompt},
                               {"role": "user", "content": f"Here is the trip data: {json.dumps(payload)}"}]}, timeout=25)
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def render(req: dict, pkgs, known_route: bool, weather: str, windows=None) -> str:
    n, days, budget = int(req.get("travellers", 1)), int(req["days"]), int(req["budget"])
    lines = [f"## {req['origin'].title()} → {req['destination'].title()} · {days} days · {n} traveller(s) · budget {inr(budget)}", ""]
    fitting = [p for p in pkgs if p["total"] <= budget]
    for p in pkgs:
        ok = "✅ fits" if p["total"] <= budget else f"❌ over by {inr(p['total'] - budget)}"
        lines.append(f"**{p['tier']}** — **{inr(p['total'])}** {ok}")
    lines.append("")
    if fitting:
        best = fitting[-1]
        lines.append(f"**Recommendation: {best['tier']}** — best comfort within your budget.")
    if windows:
        lines += ["", "### 📅 Free in your college schedule"]
        lines += [f"- {w.start} to {w.end}" for w in windows[:3]]
    lines += ["", f"### Weather in {req['destination'].title()}", weather]
    links, tip = build_links(req["origin"], req["destination"], req.get("date", ""), days, n)
    lines += ["", "### 🎟️ Book it"]
    lines += [f"- [{name}]({url})" for name, url in links]
    return "\n".join(lines)


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ack(ctx, sender, msg)
    text = text_of(msg)
    if not text:
        return

    # FIX: If the user asks a pure weather question, don't hijack it into a trip planner flow!
    t_lower = text.lower()
    if "weather" in t_lower or "rain" in t_lower or "forecast" in t_lower:
        if WEATHER_ADDR:
            # Extract city if possible
            city = "Shimla" if "shimla" in t_lower else ("Manali" if "manali" in t_lower else "Delhi")
            for c in list(TRANSPORT.keys()) + ["mumbai", "delhi"]:
                if c in t_lower:
                    city = c.title()
                    break
            try:
                reply, _ = await ctx.send_and_receive(
                    WEATHER_ADDR, WeatherRequest(city=city, days=3),
                    response_type=WeatherResponse, timeout=20)
                if isinstance(reply, WeatherResponse) and reply.ok:
                    await say(ctx, sender, reply.summary)
                    return
            except Exception:
                pass

    saved = json.loads(ctx.storage.get(sender) or "{}")
    fresh = await asyncio.to_thread(understand, text)
    if fresh.get("destination") and saved.get("destination") \
            and fresh["destination"].lower() != saved["destination"].lower():
        saved = {}
    req = {**saved, **fresh}
    
    if not req.get("origin"):
        req["origin"] = "Mumbai" if "mumbai" in t_lower else "Delhi"
        
    ctx.storage.set(sender, json.dumps(req))

    if not req.get("destination") or req.get("destination", "").lower() in INVALID_CITIES:
        await say(ctx, sender, "I'd love to help you plan that trip! Could you please specify a concrete destination (e.g., Shimla, Lonavala, or Manali)?")
        return

    missing = [k for k in REQUIRED if k not in req]
    if missing:
        ask = {"origin": "where you're starting from", "destination": "where you want to go",
               "days": "how many days", "budget": "your total budget in ₹"}
        await say(ctx, sender, "Almost there! Please tell me " + ", ".join(ask[m] for m in missing) + ".")
        return

    await say(ctx, sender, "Planning your trip, checking costs and weather...")
    pkgs, known = build_packages(req)
    weather_task = asyncio.create_task(get_weather(ctx, req["destination"], int(req["days"])))
    windows = await get_free_windows(ctx, int(req["days"])) if not req.get("date") else []
    if windows and not req.get("date"):
        req["date"] = windows[0].start
    weather = await weather_task

    response_text = llm_format_travel_response(req, pkgs, weather, windows)
    if not response_text:
        response_text = render(req, pkgs, known, weather, windows)

    await say(ctx, sender, response_text)
    ctx.storage.set(sender, "{}")


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()