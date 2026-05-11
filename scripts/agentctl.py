"""agentctl - multi-tenant IaC CLI for ZeroClaw deployments."""

import argparse
import getpass
import json as _json
import os
from pathlib import Path
import re
import subprocess
import sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib

SLUG_RE = re.compile(r"^agent-[a-z0-9]([a-z0-9-]{0,27}[a-z0-9])?$")


class SlugError(ValueError):
    """Raised when a tenant slug fails validation."""


def validate_slug(slug: str) -> None:
    if "--" in slug:
        raise SlugError(f"invalid slug (double dash): {slug!r}")
    if not SLUG_RE.match(slug):
        raise SlugError(f"invalid slug {slug!r}: must match {SLUG_RE.pattern}")


def init_tenant(slug: str, *, repo_root: Path, provider: str) -> Path:
    """Scaffold tenants/<slug>/{tenant.toml, .env} from the templates."""
    validate_slug(slug)
    if provider not in ("anthropic", "litellm"):
        raise ValueError(f"provider must be anthropic or litellm, got {provider!r}")

    tenant_dir = repo_root / "tenants" / slug
    if tenant_dir.exists():
        raise FileExistsError(f"{tenant_dir} already exists")

    template_dir = repo_root / "tenants" / "_template"
    tenant_toml = (template_dir / "tenant.toml.example").read_text()
    env_file = (template_dir / ".env.example").read_text()

    tenant_dir.mkdir(parents=True)
    (tenant_dir / "tenant.toml").write_text(
        tenant_toml.replace("{{provider}}", provider)
    )
    (tenant_dir / ".env").write_text(env_file)
    (tenant_dir / ".env").chmod(0o600)
    return tenant_dir


def create_tenant_interactive(slug: str, *, repo_root: Path) -> Path:
    """Prompt for tenant settings and write tenant.toml plus .env."""
    validate_slug(slug)
    tenant_dir = repo_root / "tenants" / slug
    if tenant_dir.exists():
        raise FileExistsError(f"{tenant_dir} already exists")

    default_display = _display_name_from_slug(slug)
    display_name = _prompt("Display name", default_display)
    provider = _prompt_choice("Provider", ["litellm", "anthropic"], "litellm")
    model = _prompt("Model", "claude-haiku-4-5")

    slack_bot_token = getpass.getpass("Slack bot token (xoxb-...): ").strip()
    slack_app_token = getpass.getpass("Slack app token (xapp-...): ").strip()

    anthropic_api_key = ""
    litellm_base_url = ""
    litellm_api_key = ""
    if provider == "litellm":
        litellm_base_url = _prompt("LiteLLM base URL", "http://10.0.0.4:4000/v1")
        litellm_api_key = getpass.getpass("LiteLLM API key: ").strip()
    else:
        anthropic_api_key = getpass.getpass("Anthropic API key: ").strip()

    composio_api_key = getpass.getpass("Composio API key (optional): ").strip()
    composio_entity_id = _prompt("Composio entity ID", "default")

    tenant_dir.mkdir(parents=True)
    (tenant_dir / "tenant.toml").write_text(
        "\n".join(
            [
                f'agent_name = "{display_name}"',
                f'zeroclaw_provider = "{provider}"',
                f'zeroclaw_model = "{model}"',
                "",
                "slack_mention_only = false",
                "slack_thread_replies = true",
                "slack_use_markdown_blocks = true",
                "slack_stream_drafts = false",
                "",
            ]
        )
    )
    (tenant_dir / ".env").write_text(
        "\n".join(
            [
                "# Per-tenant secrets - NEVER commit.",
                f"SLACK_BOT_TOKEN={slack_bot_token}",
                f"SLACK_APP_TOKEN={slack_app_token}",
                "SLACK_SIGNING_SECRET=",
                "",
                f"ANTHROPIC_API_KEY={anthropic_api_key}",
                f"LITELLM_BASE_URL={litellm_base_url}",
                f"LITELLM_API_KEY={litellm_api_key}",
                "",
                f"COMPOSIO_API_KEY={composio_api_key}",
                f"COMPOSIO_ENTITY_ID={composio_entity_id}",
                "",
            ]
        )
    )
    (tenant_dir / ".env").chmod(0o600)
    return tenant_dir


def _display_name_from_slug(slug: str) -> str:
    return slug.removeprefix("agent-").replace("-", " ").title()


def _prompt(label: str, default: str) -> str:
    raw = input(f"{label} [{default}]: ").strip()
    return raw or default


def _prompt_choice(label: str, choices: list[str], default: str) -> str:
    while True:
        value = _prompt(f"{label} ({'/'.join(choices)})", default)
        if value in choices:
            return value
        print(f"Please choose one of: {', '.join(choices)}", file=sys.stderr)


def _pyinfra_cmd(task: str, agent_name: str, extra: list[str]) -> list[str]:
    """Compose the pyinfra subprocess invocation."""
    return [
        ".venv/bin/pyinfra",
        "-y",
        "infra/inventories/deploy.py",
        f"infra/tasks/{task}.py",
        *extra,
    ]


def _load_envs(repo_root: Path, slug: str) -> dict[str, str]:
    """Source root .env then tenants/<slug>/.env; tenant values win."""
    env = os.environ.copy()
    for path in [repo_root / ".env", repo_root / "tenants" / slug / ".env"]:
        if not path.exists():
            continue
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    tenant_toml = repo_root / "tenants" / slug / "tenant.toml"
    if tenant_toml.exists():
        cfg = tomllib.loads(tenant_toml.read_text())
        mapping = {
            "agent_name": "AGENT_NAME_DISPLAY",
            "zeroclaw_provider": "ZEROCLAW_PROVIDER",
            "zeroclaw_model": "ZEROCLAW_MODEL",
            "slack_channel_id": "SLACK_CHANNEL_ID",
            "slack_mention_only": "SLACK_MENTION_ONLY",
            "slack_thread_replies": "SLACK_THREAD_REPLIES",
            "slack_use_markdown_blocks": "SLACK_USE_MARKDOWN_BLOCKS",
            "slack_stream_drafts": "SLACK_STREAM_DRAFTS",
        }
        for key, env_key in mapping.items():
            if key in cfg:
                env[env_key] = _env_value(cfg[key])
        if "slack_allowed_users" in cfg:
            env["SLACK_ALLOWED_USERS"] = _json.dumps(cfg["slack_allowed_users"])
    env["AGENT_NAME"] = slug
    return env


def _env_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def cmd_init(args: argparse.Namespace, repo_root: Path) -> int:
    init_tenant(args.name, repo_root=repo_root, provider=args.provider)
    print(
        f"created tenants/{args.name}/. fill in .env, then run: "
        f"agentctl new {args.name}"
    )
    return 0


def cmd_create(args: argparse.Namespace, repo_root: Path) -> int:
    try:
        create_tenant_interactive(args.name, repo_root=repo_root)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"created tenants/{args.name}/")
    deploy_now = input("Deploy now? [y/N]: ").strip().lower()
    if deploy_now in ("y", "yes"):
        args.dry_run = False
        return cmd_new(args, repo_root)
    print(f"run when ready: scripts/agentctl new {args.name}")
    return 0


def cmd_new(args: argparse.Namespace, repo_root: Path) -> int:
    tenant_dir = repo_root / "tenants" / args.name
    if not tenant_dir.exists():
        print(
            f"error: {tenant_dir} does not exist. run: agentctl init {args.name}",
            file=sys.stderr,
        )
        return 2
    if not (tenant_dir / ".env").exists():
        print(f"error: {tenant_dir}/.env missing", file=sys.stderr)
        return 2
    env = _load_envs(repo_root, args.name)
    extra = ["--dry"] if args.dry_run else []
    return subprocess.call(
        _pyinfra_cmd("agent_new", args.name, extra), env=env, cwd=str(repo_root)
    )


def cmd_remove(args: argparse.Namespace, repo_root: Path) -> int:
    confirmation = input(
        f"type the agent name to confirm removal of {args.name!r}: "
    ).strip()
    if confirmation != args.name:
        print("aborted", file=sys.stderr)
        return 1
    env = _load_envs(repo_root, args.name)
    return subprocess.call(
        _pyinfra_cmd("agent_remove", args.name, []), env=env, cwd=str(repo_root)
    )


def cmd_list(args: argparse.Namespace, repo_root: Path) -> int:
    """List deployed tenants by SSHing to the host and inspecting containers."""
    server3_ip = os.environ.get("SERVER3_IP") or _read_env_var(
        repo_root / ".env", "SERVER3_IP"
    )
    ssh_key = os.environ.get("SSH_KEY_PATH") or _read_env_var(
        repo_root / ".env", "SSH_KEY_PATH"
    )
    ssh_port = (
        os.environ.get("SSH_PORT")
        or _read_env_var(repo_root / ".env", "SSH_PORT")
        or "2222"
    )
    ssh_user = (
        os.environ.get("SSH_USER")
        or _read_env_var(repo_root / ".env", "SSH_USER")
        or "overlord101"
    )

    cmd = [
        "ssh",
        "-i",
        ssh_key,
        "-p",
        ssh_port,
        "-o",
        "ConnectTimeout=10",
        f"{ssh_user}@{server3_ip}",
        "sudo docker ps -a --filter name='^agent-' "
        "--format '{{.Names}}|{{.Status}}|{{.Image}}'",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"ssh failed: {result.stderr.strip()}", file=sys.stderr)
        return 1

    rows = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        name, status, image = line.split("|", 2)
        rows.append({"name": name, "status": status, "image": image})

    if args.json:
        print(_json.dumps(rows, indent=2))
    else:
        if not rows:
            print("no tenants deployed")
            return 0
        w_name = max(len(row["name"]) for row in rows)
        w_stat = max(len(row["status"]) for row in rows)
        for row in rows:
            print(f"{row['name']:<{w_name}}  {row['status']:<{w_stat}}  {row['image']}")
    return 0


def _read_env_var(env_file: Path, key: str) -> str | None:
    if not env_file.exists():
        return None
    for raw_line in env_file.read_text().splitlines():
        line = raw_line.strip()
        if line.startswith(f"{key}="):
            return line.partition("=")[2].strip().strip('"').strip("'")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("name")
    p_init.add_argument(
        "--provider", choices=["anthropic", "litellm"], default="anthropic"
    )

    p_create = sub.add_parser("create")
    p_create.add_argument("name")

    p_new = sub.add_parser("new")
    p_new.add_argument("name")
    p_new.add_argument("--dry-run", action="store_true")

    p_remove = sub.add_parser("remove")
    p_remove.add_argument("name")

    p_list = sub.add_parser("list")
    p_list.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    repo_root = Path.cwd()

    try:
        validate_slug(args.name) if hasattr(args, "name") else None
    except SlugError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return {
        "init": cmd_init,
        "create": cmd_create,
        "new": cmd_new,
        "remove": cmd_remove,
        "list": cmd_list,
    }[args.cmd](args, repo_root)


if __name__ == "__main__":
    sys.exit(main())
