# Contributing

Thanks for helping improve PortClaw.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python agent.py init
python agent.py setup
python agent.py status
```

## Project Principles

- Keep private data local by default.
- Keep rules and risk models upstream of LLM explanation.
- Keep every report auditable through structured `DailyBrief` inputs.
- Do not commit secrets, private holdings, generated audit runs, or message logs.

## Before Opening A Pull Request

Run:

```bash
python -m compileall src agent.py examples
python agent.py portfolio
python agent.py ask "Why is my portfolio risky today?"
```
