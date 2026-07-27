# Infrastructure Scripts

Auditable bootstrap, migration, verification, and operational helper scripts belong here. Scripts must be non-destructive by default, validate targets, avoid embedded secrets, and document required privileges.

Current helpers provide cross-platform pytest category selection, guarded cleanup, and local Ollama administration. Cleanup removes only explicitly allowlisted generated directories located below the repository root.

- `check_ollama_readiness.py` checks the loopback Ollama server and verifies that all configured models are present.
- `pull_ollama_models.py` explicitly downloads configured models. It never runs during Compose startup; use `--only` to limit a download to one or more model roles.

The Ollama scripts accept only an explicit loopback URL and validated model names. Override model defaults with command-line options or `OLLAMA_*_MODEL` environment variables.
