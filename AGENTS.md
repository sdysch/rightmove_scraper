# Rightmove Tracker — Agent Guide

## Quick start

```bash
uv sync                    # install deps
uv sync --group dev        # include dev (pytest, ruff)
cp .env.example .env       # then fill in secrets
uv run python rightmove_tracker.py
```

## Commands (order matters — CI runs in this sequence)

```bash
uv run ruff check          # lint
uv run ruff format --check # formatting check
uv run pytest              # tests (32, no external deps — all mocked)
```

## Project structure

Single-module Python project (no `src/`, no package init). The entire app is `rightmove_tracker.py` with `main()` as entrypoint. Tests are in `tests/`.

## Conventions

- Ruff config: `line-length = 100`, `quote-style = single`, lint rules `E,F,I,W,UP`
- Python 3.10+ (target `py310`)
- Use `uv` for everything (not pip/poetry)
- Single quotes for strings unless double quotes improve readability

## Architecture notes

- **No Supabase client library** — uses `requests` directly against the Supabase REST API with `service_role` key + `Prefer: resolution=merge-duplicates` for upserts
- Module-level env var loading (`os.environ.get(...)` at import time) — patching these in tests requires `patch('rightmove_tracker.SUPABASE_URL', ...)`
- **First run**: captures baseline state, no notifications sent
- **Empty scrape**: preserves existing DB state (doesn't clear/overwrite)
- **Daily digest**: sends "no changes" Telegram at 19:00 UTC if nothing happened
- **Telegram limit**: messages chunked at 4096 chars

## Supabase schema

Table `property_state` with PK `property_id` (text), plus `price`, `first_seen_price`, `address`, `url`, `bedrooms`, `property_type`, `first_seen_at`, `updated_at`.

## GitHub Actions

- **Scrape** (`scrape.yml`): runs hourly 07-19 UTC on cron, also supports `workflow_dispatch` and `repository_dispatch`
- **CI** (`ci.yml`): on push/PR to `main` — lint → format → gitleaks → pytest
- **Cleanup** (`cleanup-runs.yml`): nightly, deletes workflow runs older than 7 days
- Secrets: `SEARCH_URL`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`

## Pre-commit

```yaml
- gitleaks (secret scanning)
- ruff-check --fix
- ruff-format
```
