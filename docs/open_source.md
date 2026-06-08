# Open Source Readiness

This project is safe to publish when only source files, docs, examples, and templates are included.

## Safe To Publish

- `src/`
- `docs/`
- `examples/`
- `agent.py`
- `README.md`
- `requirements.txt`
- `.env.example`
- `config/local_config.example.json`
- `data/portfolio.example.json`
- `data/portfolio_template.csv`
- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`

## Keep Local

- `.env`
- `config/local_config.json`
- `audit_runs/`
- `messages/`
- real portfolio files
- `data/portfolio.local.json`
- API keys
- channel bot tokens
- generated `config/local_config.json` with selected commercial data keys

## Recommended First Commit

```bash
git init
git add .
git status
git commit -m "Initial PortClaw release"
```

Review `git status` before committing and make sure ignored local files are not listed.
