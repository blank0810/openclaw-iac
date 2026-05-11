"""agentctl - multi-tenant IaC CLI for ZeroClaw deployments."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

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
    env["AGENT_NAME"] = slug
    return env


def cmd_init(args: argparse.Namespace, repo_root: Path) -> int:
    init_tenant(args.name, repo_root=repo_root, provider=args.provider)
    print(
        f"created tenants/{args.name}/. fill in .env, then run: "
        f"agentctl new {args.name}"
    )
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
    raise NotImplementedError("list not yet implemented")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentctl")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("name")
    p_init.add_argument(
        "--provider", choices=["anthropic", "litellm"], default="anthropic"
    )

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
        "new": cmd_new,
        "remove": cmd_remove,
        "list": cmd_list,
    }[args.cmd](args, repo_root)


if __name__ == "__main__":
    sys.exit(main())
