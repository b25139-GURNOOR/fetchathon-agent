"""Shared message models + chat helpers used by both agents."""
from datetime import datetime, timezone
from uuid import uuid4

from uagents import Model, Context
from uagents_core.contrib.protocols.chat import (
    ChatMessage, ChatAcknowledgement, TextContent,
)


class WeatherRequest(Model):
    city: str
    days: int = 3


class WeatherResponse(Model):
    ok: bool
    city: str = ""
    summary: str = ""
    error: str = ""


def now():
    return datetime.now(timezone.utc)


async def ack(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=now(), acknowledged_msg_id=msg.msg_id))


def text_of(msg: ChatMessage) -> str:
    return " ".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()


async def say(ctx: Context, sender: str, text: str):
    await ctx.send(sender, ChatMessage(
        timestamp=now(), msg_id=uuid4(),
        content=[TextContent(type="text", text=text)]))


# ---- College Planner <-> Trip Planner messages ----
from typing import List  # noqa: E402


class FreeWindow(Model):
    start: str  # ISO date, e.g. 2026-11-14
    end: str    # ISO date
    label: str = ""  # e.g. "Sat-Mon, no classes"


class FreeSlotsRequest(Model):
    days_needed: int = 3
    from_date: str = ""  # optional ISO date
    to_date: str = ""    # optional ISO date


class FreeSlotsResponse(Model):
    ok: bool
    windows: List[FreeWindow] = []
    error: str = ""
