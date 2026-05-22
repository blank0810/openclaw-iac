# Repository Guidelines

## Project Structure & Module Organization

This is a Python monorepo for Cloudesk infrastructure and agent experiments. `infra/` contains Pyinfra entrypoints, inventories, task modules, and uploaded server files. `group_data/` holds shared non-secret deployment config. `apps/slack-agent/` contains the Slack Managed Agents MVP, with source in `src/` and setup helpers in `scripts/`. `apps/zeroclaw/` holds ZeroClaw evaluation notes and install tooling. `docker/` contains compose stacks, including historical `docker/chaos/` material and active ZeroClaw workspace/config templates. Project notes and plans live in `docs/`.

## Build, Test, and Development Commands

- `./scripts/setup-local.sh` creates `.venv`, installs root requirements, and copies `.env.example` to `.env` if needed.
- `source .venv/bin/activate && set -a; source .env; set +a` activates Python and loads deployment variables.
- `pyinfra infra/inventories/bootstrap.py infra/bootstrap.py` performs first-time Server 3 bootstrap as root.
- `pyinfra infra/inventories/deploy.py infra/deploy.py --dry` previews standard deployment changes.
- `pyinfra infra/inventories/deploy.py infra/deploy.py` applies the repeatable deploy flow.
- `cd apps/slack-agent && python -m venv .venv && .venv/bin/pip install -r requirements.txt` prepares the Slack app environment.
- `cd apps/slack-agent && .venv/bin/python src/app.py` runs the Slack bot locally after required API and Slack env vars are set.

## Coding Style & Naming Conventions

Use Python 3.10+ with 4-space indentation, type hints where they clarify contracts, and small task-focused modules. Keep Pyinfra concerns split by file under `infra/tasks/`, and include them from orchestrators with `local.include()`. Prefer explicit environment access for required deploy values, for example `os.environ["SERVER3_IP"]`, so missing configuration fails loudly. Name docs with dated prefixes when they are plans, e.g. `docs/plans/2026-05-11-topic.md`.

## Testing Guidelines

No formal test suite is configured yet. For infrastructure changes, run the relevant Pyinfra command with `--dry` before applying. For Slack agent changes, run the app locally and exercise DM, mention, OAuth-link, and tool-dispatch paths. Add future tests under an obvious `tests/` package using `test_*.py` names.

## Commit & Pull Request Guidelines

History uses Conventional Commit-style messages such as `feat(chaos): ...`, `chore(repo): ...`, and `docs(plans): ...`; follow that pattern with a narrow scope. Pull requests should describe behavior changes, list verification commands, link any relevant plan or issue, and include screenshots/log excerpts for Slack or deployment UX changes.

## Security & Configuration Tips

Never commit `.env`, `.pem`, API keys, Slack tokens, Composio credentials, or real server IPs. Use `.env.example` as the public contract. OpenClaw/Chaos files are historical unless a decision explicitly reverses that direction.
