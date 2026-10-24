import asyncio
from uagents import Agent, Context, Model

# Clean event loop initialization for Python 3.14+
try:
    asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# 1. Define Request and Response models
class AcademicRequest(Model):
    prompt: str

class AcademicResponse(Model):
    response: str

# 2. Agent initialize with mailbox enabled
campus_agent = Agent(
    name="campus_workflow_agent",
    seed="iit_mandi_campus_agent_seed_987",
    port=8000,
    endpoint=["http://127.0.0.1:8000/submit"],
    mailbox=True
)

# 3. Startup event
@campus_agent.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"🚀 Agent started successfully!")
    ctx.logger.info(f"📍 Agent Address: {campus_agent.address}")

# 4. Multi-step reasoning / Tool execution function
def generate_academic_plan(query: str) -> str:
    query_lower = query.lower()
    
    if "dsa" in query_lower or "leetcode" in query_lower:
        return r"""🎯 **Multi-Step DSA Execution Plan:**
1. **Concept Review:** 30 mins on Striver's Graph/DP sheet.
2. **Problem Solving:** Solve 2 LeetCode problems (1 Medium, 1 Hard) in C++.
3. **Complexity Analysis:** Verify time complexity ($O(N)$ or $O(N \log N)$).
4. **Outcome:** Code committed to GitHub repository."""
    elif "project" in query_lower or "flask" in query_lower:
        return r"""⚙️ **Project Workflow Orchestration:**
1. **Backend Check:** Verify Flask server endpoints and WebSocket handlers.
2. **Simulation Logic:** Run Python physics/calculation script.
3. **Integration:** Connect frontend canvas inputs to backend state.
4. **Outcome:** Simulation pipeline ready for deployment."""
    else:
        return f"""💡 **General Campus Query Processed:**
Analyzed request: '{query}'.
Recommended action: Break down tasks into modular C++/Python scripts, check resource constraints, and execute via automated workflow."""

# 5. Message handler
@campus_agent.on_message(model=AcademicRequest, replies={AcademicResponse})
async def handle_academic_request(ctx: Context, sender: str, msg: AcademicRequest):
    ctx.logger.info(f"📥 Message received from {sender}: {msg.prompt}")
    
    # Execute multi-step planning tool
    result_plan = generate_academic_plan(msg.prompt)
    
    await ctx.send(sender, AcademicResponse(response=result_plan))

if __name__ == "__main__":
    campus_agent.run()