"""AGENT 3: College Planner Agent.
- Chat in ASI:One: schedule, exams, deadlines, free windows, add events.
- Answers FreeSlotsRequest from the Trip Planner so trips never clash with exams/deadlines.
Edit data/schedule.json with your real timetable first.
"""
from dotenv import load_dotenv
                              
                              
load_dotenv()  
              




import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
import os

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    chat_protocol_spec, ChatMessage, ChatAcknowledgement,
)

import college_logic as logic
from common import FreeSlotsRequest, FreeSlotsResponse, ack, say, text_of

load_dotenv()
mailbox_key = os.getenv("AGENTVERSE_KEY")
print("API Key loaded:", bool(os.getenv("MAILBOX_KEY")))
agent = Agent(
    name="college-planner-agent",
    seed=os.environ["COLLEGE_SEED"],
    port=8013,
    network="testnet",              
    mailbox=f"{mailbox_key}@https://agentverse.ai",
    
)
async def send_with_retry(ctx, destination, message, retries=3):
    for attempt in range(retries):
        try:
            await ctx.send(destination, message)
            ctx.logger.info("Message delivered successfully!")
            return
        except Exception as e:
            ctx.logger.warning(f"Attempt {attempt + 1} failed: {e}")
            await asyncio.sleep(2) # Wait 2 seconds before retrying
    ctx.logger.error("Failed to deliver message after multiple retries.")
chat_proto = Protocol(spec=chat_protocol_spec)


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ack(ctx, sender, msg)
    text = text_of(msg)
    if not text:
        return
    try:
        if logic.will_search(text):
            await say(ctx, sender, "Searching the web for your college's academic calendar, this can take a minute...")
        reply = await asyncio.to_thread(logic.handle_text, text)
    except Exception as e:
        ctx.logger.exception("college chat error")
        reply = f"Sorry, I couldn't read the schedule file ({type(e).__name__}). Check data/schedule.json."
    await say(ctx, sender, reply)


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@agent.on_message(FreeSlotsRequest)
async def on_free_slots(ctx: Context, sender: str, msg: FreeSlotsRequest):
    ctx.logger.info(f"FreeSlotsRequest from {sender[:14]}...: {msg.days_needed} days")
    try:
        windows = await asyncio.to_thread(logic.get_windows, msg.days_needed)
        await ctx.send(sender, FreeSlotsResponse(ok=True, windows=windows))
    except Exception as e:
        await ctx.send(sender, FreeSlotsResponse(ok=False, error=str(e)))


agent.include(chat_proto, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
