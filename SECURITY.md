# Security Policy

PortClaw is designed as a local-first agent. Private portfolio data, API keys, local config, message logs, and audit runs should stay on the user's machine.

## Do Not Commit

Do not commit these files or folders:

- `.env`
- `config/local_config.json`
- `audit_runs/`
- `messages/`
- private portfolio files
- API keys or provider tokens

The repository includes safe templates:

- `.env.example`
- `config/local_config.example.json`
- `data/portfolio.example.json`

## API Keys

Use the local setup wizard or environment variables:

```bash
python agent.py setup
```

The setup wizard writes local secrets to `config/local_config.json`, which is ignored by git.

## Reporting Issues

For public issue trackers, do not paste API keys, private holdings, audit outputs, or full message logs.
