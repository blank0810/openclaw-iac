from __future__ import annotations

import socket
import subprocess
from pathlib import Path

from lib.audit import append_audit_line, default_actor
from lib.config import load_config


def _ssh_check(host: str, user: str, port: int, key_path: Path) -> bool:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            "-i",
            str(key_path),
            "-p",
            str(port),
            f"{user}@{host}",
            "true",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _run_pyinfra(deploy_file: str, *, dry: bool = False, verbose: int = 0) -> int:
    cmd = ["pyinfra", "-y", "lib/inventory.py", deploy_file]
    if dry:
        cmd.append("--dry")
    if verbose > 0:
        cmd.append("-" + ("v" * min(verbose, 3)))
    return subprocess.run(cmd, check=False).returncode


def _do_deploy(cfg, dry: bool, verbose: int = 0) -> int:
    try:
        sock = socket.create_connection((cfg.server_host, 22), timeout=5)
        close = getattr(sock, "close", None)
        if close:
            close()
    except OSError:
        print(f"cannot reach {cfg.server_host}:22")
        return 1

    if _ssh_check(cfg.server_host, cfg.deploy_user, cfg.ssh_port, cfg.deploy_ssh_key_path):
        return _run_pyinfra("lib/deploy_runtime.py", dry=dry, verbose=verbose)

    if not _ssh_check(cfg.server_host, "root", 22, cfg.root_ssh_key_path):
        print("cannot auth as deploy user or root")
        return 1

    prepare = _run_pyinfra("lib/bootstrap_prepare.py", dry=dry, verbose=verbose)
    if prepare:
        return prepare

    if not _ssh_check(cfg.server_host, cfg.deploy_user, cfg.ssh_port, cfg.deploy_ssh_key_path):
        print("deploy-user SSH key verification failed; refusing hardening")
        return 1

    hardening = _run_pyinfra("lib/bootstrap_hardening.py", dry=dry, verbose=verbose)
    if hardening:
        return hardening
    return _run_pyinfra("lib/deploy_runtime.py", dry=dry, verbose=verbose)


def cmd_deploy(project_root: Path | None = None, dry: bool = False, verbose: int = 0) -> int:
    cfg = load_config(project_root)
    rc = _do_deploy(cfg, dry, verbose=verbose)
    append_audit_line(
        cfg,
        actor=default_actor(),
        cmd="server.deploy",
        agent=None,
        image=None,
        result="ok" if rc == 0 else "fail",
    )
    return rc
