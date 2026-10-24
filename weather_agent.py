"""AGENT 1: Weather Agent.
Provides live weather forecasts using Open-Meteo with NLP city extraction.
"""
import asyncio
import os
import re
import requests
from dotenv import load_dotenv
from datetime import datetime, timezone
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    chat_protocol_spec,
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
)
from common import WeatherRequest, WeatherResponse, now

load_dotenv()
mailbox_key = os.getenv("MAILBOX_KEY")
print("API Key loaded:", bool(mailbox_key))

agent = Agent(
    name="weather-agent",
    seed=os.environ["WEATHER_SEED"],
    port=8011,
    network="testnet",
    mailbox=f"{mailbox_key}@https://agentverse.ai" if mailbox_key else None,
)

chat_proto = Protocol(spec=chat_protocol_spec)

# Comprehensive presets for fast lookup and fallback
PRESETS = {
    "manali": (32.2432, 77.1892), "shimla": (31.1048, 77.1734),
    "rishikesh": (30.0869, 78.2676), "jaipur": (26.9124, 75.7873),
    "goa": (15.2993, 74.1240), "delhi": (28.6139, 77.2090), 
    "mumbai": (19.0760, 72.8777), "lonavala": (18.7537, 73.4057),
    "alibaug": (18.6414, 72.8722), "iit mandi": (31.7754, 76.9861),
    "barcelona": (41.3851, 2.1734), "reykjavik": (64.1466, -21.9426),
    "london": (51.5074, -0.1278), "new york": (40.7128, -74.0060),
    "new york city": (40.7128, -74.0060), "paris": (48.8566, 2.3522),
}

def extract_city_from_text(text: str) -> str:
    """Extracts city entity from natural language sentences."""
    t_lower = text.lower()
    
    # 1. Check known presets first
    for city in PRESETS.keys():
        if city in t_lower:
            return city.title()
            
    # 2. Look for prepositions indicating location (e.g., "in Barcelona", "for London")
    m = re.search(r'\b(?:in|for|at|near|around)\s+([a-zA-Z\s]+)(?:\s+(?:this|today|tomorrow|weekend|evening|hourly|forecast))?', text, re.I)
    if m:
        candidate = m.group(1).strip()
        # Clean up trailing filler words
        candidate = re.sub(r'\b(this|today|tomorrow|weekend|evening|hourly|forecast)\b.*', '', candidate, flags=re.I).strip()
        if len(candidate) > 2:
            return candidate.title()
            
    # 3. Fallback to LLM entity extraction if MAILBOX_KEY is available
    key = os.getenv("MAILBOX_KEY")
    if key:
        try:
            prompt = "Extract ONLY the city or location name from the user's message. Reply with ONLY the city name as a string, or 'None' if none exists."
            resp = requests.post(
                "https://api.asi1.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "asi1-mini", "temperature": 0,
                      "messages": [{"role": "system", "content": prompt},
                                   {"role": "user", "content": text}]}, timeout=8)
            extracted = resp.json()["choices"][0]["message"]["content"].strip().strip('"\'')
            if extracted and extracted.lower() != "none" and len(extracted) < 30:
                return extracted
        except Exception:
            pass
            
    return ""


def fetch_weather(city: str, days: int = 3) -> str:
    cleaned_city = extract_city_from_text(city) or city.strip()
    c_lower = cleaned_city.strip().lower()
    
    lat, lon = PRESETS.get(c_lower, (None, None))
    try:
        if lat is None:
            geo = requests.get(f"https://geocoding-api.open-meteo.com/v1/search?name={cleaned_city}&count=1", timeout=5).json()
            if not geo.get("results"):
                return f"I couldn't find a location named '{cleaned_city}'. Could you please specify a valid city name?"
            lat, lon = geo["results"][0]["latitude"], geo["results"][0]["longitude"]
        
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto"
        data = requests.get(url, timeout=5).json()
        daily = data.get("daily", {})
        times = daily.get("time", [])[:days]
        tmax = daily.get("temperature_2m_max", [])[:days]
        tmin = daily.get("temperature_2m_min", [])[:days]
        rain = daily.get("precipitation_probability_max", [])[:days]
        
        lines = [f"**Weather Forecast for {cleaned_city.title()} ({days} days):**"]
        for d, mx, mn, r in zip(times, tmax, tmin, rain):
            lines.append(f"• **{d}**: High {mx}°C, Low {mn}°C | Rain risk: {r}%")
        return "\n".join(lines)
    except Exception as e:
        return f"Weather service error: {str(e)}"

@agent.on_message(WeatherRequest)
async def on_weather_request(ctx: Context, sender: str, msg: WeatherRequest):
    summary = fetch_weather(msg.city, msg.days)
    ok = "couldn't find" not in summary.lower() and "error" not in summary.lower()
    await ctx.send(sender, WeatherResponse(ok=ok, city=msg.city, summary=summary, error="" if ok else summary))

@chat_proto.on_message(ChatMessage)
async def on_chat_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id
        )
    )
    
    query_text = ""
    for item in msg.content:
        if isinstance(item, TextContent):
            query_text = item.text
            break
            
    summary = fetch_weather(query_text, 3)
    reply_msg = ChatMessage(
        timestamp=datetime.now(timezone.utc),
        content=[TextContent(type="text", text=summary)]
    )
    await ctx.send(sender, reply_msg)

@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass

agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()