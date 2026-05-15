#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gevent import monkey

monkey.patch_all()

from lib import audit, backup, server, tenants, workspace  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zeroclawctl")
    sub = parser.add_subparsers(dest="command", required=True)

    server_parser = sub.add_parser("server")
    server_sub = server_parser.add_subparsers(dest="server_command", required=True)
    server_deploy = server_sub.add_parser("deploy")
    server_deploy.add_argument("--dry", action="store_true")
    server_deploy.set_defaults(func=lambda args: server.cmd_deploy(dry=args.dry))

    tenants_parser = sub.add_parser("tenants")
    tenants_sub = tenants_parser.add_subparsers(dest="tenant_command", required=True)

    create = tenants_sub.add_parser("create")
    create.add_argument("--name", required=True)
    create.set_defaults(func=lambda args: tenants.cmd_create(args.name))

    deploy = tenants_sub.add_parser("deploy")
    deploy.add_argument("--name", required=True)
    deploy.add_argument("--pull-image", action="store_true")
    deploy.set_defaults(
        func=lambda args: tenants.cmd_deploy(args.name, pull_image=args.pull_image)
    )

    status = tenants_sub.add_parser("status")
    status.set_defaults(func=lambda args: tenants.cmd_status())

    fetch = tenants_sub.add_parser("fetch")
    fetch.add_argument("--name", required=True)
    fetch.add_argument("--force", action="store_true")
    fetch.set_defaults(func=lambda args: tenants.cmd_fetch(args.name, force=args.force))

    shell = tenants_sub.add_parser("shell")
    shell.add_argument("--name", required=True)
    shell.set_defaults(func=lambda args: tenants.cmd_shell(args.name))

    remove = tenants_sub.add_parser("remove")
    remove.add_argument("--name", required=True)
    remove.set_defaults(func=lambda args: tenants.cmd_remove(args.name))

    restore = tenants_sub.add_parser("restore")
    restore.add_argument("--name", required=True)
    restore.add_argument("--from", dest="from_ts")
    restore.set_defaults(func=lambda args: tenants.cmd_restore(args.name, ts=args.from_ts))

    logs = tenants_sub.add_parser("logs")
    logs.add_argument("--name", required=True)
    logs.add_argument("--follow", action="store_true")
    logs.set_defaults(func=lambda args: tenants.cmd_logs(args.name, follow=args.follow))

    workspace_parser = sub.add_parser("workspace")
    workspace_sub = workspace_parser.add_subparsers(dest="workspace_command", required=True)
    for cmd_name, func in (
        ("status", workspace.cmd_status),
        ("fetch", workspace.cmd_fetch),
        ("deploy", workspace.cmd_deploy),
    ):
        cmd = workspace_sub.add_parser(cmd_name)
        cmd.add_argument("--name", required=True)
        if cmd_name in {"fetch", "deploy"}:
            cmd.add_argument("--force", action="store_true")
            cmd.set_defaults(func=lambda args, f=func: f(args.name, force=args.force))
        else:
            cmd.set_defaults(func=lambda args, f=func: f(args.name))
    session_clear = workspace_sub.add_parser("session-clear")
    session_clear.add_argument("--name", required=True)
    session_clear.set_defaults(func=lambda args: workspace.cmd_session_clear(args.name))

    backup_parser = sub.add_parser("backup")
    backup_group = backup_parser.add_mutually_exclusive_group(required=True)
    backup_group.add_argument("--name")
    backup_group.add_argument("--all", action="store_true")
    backup_parser.set_defaults(
        func=lambda args: backup.cmd_backup(None if args.all else args.name)
    )

    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--tenant")
    audit_parser.add_argument("--since")
    audit_parser.set_defaults(
        func=lambda args: audit.cmd_audit(tenant=args.tenant, since=args.since)
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
