# Trip2: two-agent trip planner for ASI:One

| Agent | File | Difficulty | Job |
|---|---|---|---|
| Weather Agent | `weather_agent.py` | Easy | Live forecast (Open-Meteo) for users and for the Planner |
| Trip Planner Agent | `planner_agent.py` | Harder | Understands intent, asks follow-ups, calls Weather Agent, builds 3 budget packages, recommends one |

## Run
1. `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\Scripts\activate`)
2. `pip install -r requirements.txt`
3. `cp .env.example .env` and set both seeds (any long random text).
4. Terminal 1: `python weather_agent.py`. Copy its `agent1q...` address from the log into `WEATHER_AGENT_ADDRESS` in `.env`.
5. Terminal 2: `python planner_agent.py`
6. In each terminal log, open the **Agent inspector** link, click **Connect**, choose **Mailbox**.
7. On agentverse.ai open each agent, add a good description + README, then chat with it from ASI:One.

## Try
- `weather in Manali for 4 days` (Weather Agent)
- `Plan Delhi to Manali, 3 days, 2 people, under ₹15000` (Planner Agent)
- `Plan a trip to Goa` (follow-up questions, then answers merge)

## Test without the platform
`python -c "from weather_agent import fetch_weather; print(fetch_weather('Manali',3))"` (needs both seeds in .env)

## Agent 3: College Planner (`college_agent.py`)
- Edit `data/schedule.json` with your real timetable, exams, deadlines, holidays.
- Add `COLLEGE_SEED` to `.env`, run `python college_agent.py` (port 8003), connect Mailbox.
- Copy its `agent1q...` address into `COLLEGE_AGENT_ADDRESS` in `.env`, then restart `planner_agent.py`.
- Try in ASI:One: `schedule tomorrow`, `when am I free for 3 days`, `add exam Physics on 12 Nov`.
- Test logic offline: `python tests/test_college.py`

## College Planner: works for any college
Tell the agent once: `I study at <your college>, <branch>, <year>`. Calendar sources, best first:
1. `data/colleges/<college>.json` if it exists (IIT Mandi is bundled as an example; copy it to add more).
2. `calendar link <url>`: paste your college's academic-calendar PDF/page link. ASI1 reads it and saves it (needs `ASI1_API_KEY`; check the dates after).
3. Quick commands: `add semester 3 Aug to 26 Nov`, `add exams 28 Nov to 5 Dec`, `add break 7 Dec to 3 Jan`, `add exam Physics on 12 Nov`.
4. Otherwise: typical Indian semesters (Jan-Apr, Aug-Nov, ASSUMED, weekdays) + India public holidays.
Your private course timetable is not fetched (it is behind college logins). `data/schedule.json` is an optional override.
Offline test: `python tests/test_college.py`
