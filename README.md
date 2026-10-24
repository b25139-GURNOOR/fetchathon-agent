# Campus Workflow Agent

Student-focused assistant that works inside **ASI:One** through the Agent Chat Protocol.

## What it does
- **Weather** - live 3-day forecast (Open-Meteo) for IIT Mandi or any city/campus you name. Example: `weather at IIT Mandi tomorrow`
- **DSA** - practice plan or a daily/weekly study schedule. Example: `give me a DSA schedule`
- **Projects** - a project/deployment checklist. Example: `checklist for my Flask project`
- **Study schedule** - a time-blocked template. Example: `plan my week at IIT Mandi`

Understands typos (`weathr`, `algoritm`) and picks up college names (`IIT Mandi`, `NIT Hamirpur`, `... University`).
Plans are templates, and the weather is live data; when a live lookup fails it says so instead of making numbers up.

## Run
```bash
pip install -r requirements.txt
python agent.py
```
Open the Agent Inspector link printed in the logs and connect the agent with **Mailbox** so ASI:One can reach it.

## Test
```bash
python test.py --unit   # instant, offline
python test.py          # + live agent-to-agent test over the Chat Protocol
pytest test.py          # unit tests under pytest
```
