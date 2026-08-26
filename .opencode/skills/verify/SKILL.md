---
name: verify
description: Run the full green-check verification loop for contract-change-intel (compose, ruff, mypy, pytest). Use after any change to app/, migrations/, tests/, pyproject.toml, or docker-compose.yml, or when asked to verify/check/confirm the project passes.
---

# Verify

Run in order. Stop at the first red step, fix the cause (not the symptom), rerun from that step.

```sh
docker compose up -d --wait                          # 1. Postgres ready on host port 5433
uv run ruff check . && uv run ruff format --check .  # 2. lint + format (CI parity)
uv run mypy app migrations/env.py                    # 3. typecheck (CI parity)
uv run pytest                                        # 4. integration tests
```

Rules:

- Step 1 is idempotent/fast when already up. If 5433 is unreachable, fix compose —
  never fall back to 5432 (occupied by an unrelated stack).
- pytest applies migrations itself via `tests/conftest.py`; no manual upgrade needed.
  If a fresh migration was just authored, additionally sanity-run
  `uv run alembic upgrade head` once.
- All four green ⇒ report "verify: clean". Otherwise report the failing step with its
  actual output, then stop and wait for direction.
