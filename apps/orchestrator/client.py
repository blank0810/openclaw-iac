#!/usr/bin/env python
"""zc — orchestrator API launch CLI.

A thin client over the deployed orchestrator API. `zc launch` opens an SSH
tunnel to the server's localhost:8000, POSTs an agent spec, polls the job to
completion, then offers to drop you into the agent's ZeroClaw terminal chat.

Connectivity, secrets, and flow are documented in
docs/plans/2026-05-22-zc-launch-cli-design.md. This module imports nothing
from the Pyinfra/gevent stack; it only needs lib.config for SSH/server
settings (same .env as everything else).
"""

from __future__ import annotations

import argparse
import getpass
import re
import socket
import subprocess
import sys
import time

import requests

from lib.config import SLUG_PATTERN, DeploymentConfig, load_config

DEFAULT_LOCAL_PORT = 8000
REMOTE_PORT = 8000


class OrchestratorError(RuntimeError):
    """A non-2xx API response or a job that ended in a failed state."""


# --- input handling -------------------------------------------------------


def validate_inputs(name: str, user_id: str) -> list[str]:
    """Client-side validation run before any network/SSH work."""
    errors: list[str] = []
    if not SLUG_PATTERN.match(name):
        errors.append(f"invalid agent slug: {name!r} (must match {SLUG_PATTERN.pattern})")
    if not user_id or not user_id.strip():
        errors.append("--user-id must not be empty")
    return errors


def build_payload(
    *,
    name: str,
    user_id: str,
    display_name: str | None = None,
    slack_bot_token: str | None = None,
    slack_app_token: str | None = None,
    slack_channel_id: str | None = None,
    composio_mcp_key: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> dict:
    """Assemble the CreateAgentRequest JSON body from resolved values.

    Optional sections are emitted only when their fields are present; anything
    omitted inherits from agents/_defaults.toml server-side.
    """
    payload: dict = {"name": name, "user_id": user_id}
    if display_name:
        payload["display_name"] = display_name
    if slack_bot_token and slack_app_token:
        slack: dict = {"bot_token": slack_bot_token, "app_token": slack_app_token}
        if slack_channel_id:
            slack["channel_id"] = slack_channel_id
        payload["slack"] = slack
    if composio_mcp_key:
        payload["composio"] = {"mcp_api_key": composio_mcp_key}
    if llm_provider or llm_model:
        llm: dict = {}
        if llm_provider:
            llm["provider"] = llm_provider
        if llm_model:
            llm["model"] = llm_model
        payload["llm"] = llm
    return payload


def gather_secrets(args, *, _getpass=getpass.getpass, _input=input) -> dict:
    """Resolve Slack/Composio secrets from flags or hidden prompts.

    Mirrors `zeroclawctl agents create`: a bare --slack/--composio triggers
    prompts; passing any explicit value activates the section but skips it.
    Returns resolved kwargs for build_payload.
    """
    slack_passthrough = any(
        v is not None
        for v in (args.slack_bot_token, args.slack_app_token, args.slack_channel_id)
    )
    composio_passthrough = args.composio_mcp_key is not None

    slack_bot = args.slack_bot_token
    slack_app = args.slack_app_token
    slack_channel = args.slack_channel_id
    composio_key = args.composio_mcp_key

    if args.slack and not slack_passthrough:
        slack_bot = _getpass("Slack bot token (xoxb-...): ").strip()
        if slack_bot and not slack_bot.startswith("xoxb-"):
            print("warning: bot token does not start with xoxb-")
        slack_app = _getpass("Slack app token (xapp-...): ").strip()
        if slack_app and not slack_app.startswith("xapp-"):
            print("warning: app token does not start with xapp-")
        channel = _input("Slack channel ID to scope to (blank for all): ").strip()
        slack_channel = channel or None

    if args.composio and not composio_passthrough:
        composio_key = _getpass("Composio MCP API key (ck_...): ").strip() or None
        if composio_key and not composio_key.startswith("ck_"):
            print("warning: Composio MCP key does not start with ck_")

    return {
        "slack_bot_token": slack_bot,
        "slack_app_token": slack_app,
        "slack_channel_id": slack_channel,
        "composio_mcp_key": composio_key,
        "llm_provider": args.llm_provider,
        "llm_model": args.llm_model,
    }


# --- ssh / tunnel ---------------------------------------------------------


def tunnel_cmd(cfg: DeploymentConfig, local_port: int = DEFAULT_LOCAL_PORT) -> list[str]:
    return [
        "ssh",
        "-i",
        str(cfg.deploy_ssh_key_path),
        "-p",
        str(cfg.ssh_port),
        # Fail loudly instead of piggybacking on a stale tunnel: if the local
        # bind fails, ssh exits non-zero rather than staying up with a dead
        # forward (which would make requests hang until they time out).
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=3",
        "-N",
        "-L",
        f"127.0.0.1:{local_port}:127.0.0.1:{REMOTE_PORT}",
        f"{cfg.deploy_user}@{cfg.server_host}",
    ]


def chat_cmd(cfg: DeploymentConfig, slug: str) -> list[str]:
    return [
        "ssh",
        "-t",
        "-i",
        str(cfg.deploy_ssh_key_path),
        "-p",
        str(cfg.ssh_port),
        f"{cfg.deploy_user}@{cfg.server_host}",
        f"docker exec -it zeroclaw-{slug} zeroclaw agent",
    ]


def open_tunnel(cfg: DeploymentConfig, local_port: int = DEFAULT_LOCAL_PORT):
    """Start the SSH tunnel as a background process. Caller must close it."""
    return subprocess.Popen(
        tunnel_cmd(cfg, local_port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def close_tunnel(proc) -> None:
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def wait_for_port(host: str, port: int, timeout: float = 10.0, *, proc=None) -> bool:
    """Wait until ``host:port`` accepts a connection. If ``proc`` (the tunnel
    process) exits first, bail immediately — with ExitOnForwardFailure that
    means the local bind failed (port already in use by a stale tunnel)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


# --- api calls ------------------------------------------------------------


def create_agent(base_url: str, payload: dict, *, session) -> str:
    resp = session.post(f"{base_url}/v1/agent/create", json=payload, timeout=30)
    if resp.status_code == 202:
        return resp.json()["job_id"]
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    raise OrchestratorError(f"POST /v1/agent/create {resp.status_code}: {detail}")


def delete_agent(base_url: str, name: str, *, session) -> dict:
    resp = session.delete(f"{base_url}/v1/agent/delete/{name}", timeout=60)
    if resp.status_code == 200:
        return resp.json()
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    raise OrchestratorError(f"DELETE /v1/agent/delete/{name} {resp.status_code}: {detail}")


def _detail(resp) -> str:
    try:
        return resp.json().get("detail", resp.text)
    except ValueError:
        return resp.text


def list_providers(base_url: str, *, session) -> dict:
    resp = session.get(f"{base_url}/v1/providers", timeout=30)
    if resp.status_code != 200:
        raise OrchestratorError(f"GET /v1/providers {resp.status_code}: {_detail(resp)}")
    return resp.json()


def set_default_provider(base_url: str, profile: str, *, session) -> dict:
    resp = session.put(
        f"{base_url}/v1/config/provider", json={"profile": profile}, timeout=30
    )
    if resp.status_code != 200:
        raise OrchestratorError(
            f"PUT /v1/config/provider {resp.status_code}: {_detail(resp)}"
        )
    return resp.json()


def set_agent_provider(base_url: str, name: str, profile: str, *, session) -> str:
    resp = session.put(
        f"{base_url}/v1/agent/{name}/provider", json={"profile": profile}, timeout=30
    )
    if resp.status_code == 202:
        return resp.json()["job_id"]
    raise OrchestratorError(
        f"PUT /v1/agent/{name}/provider {resp.status_code}: {_detail(resp)}"
    )


def restore_agent(base_url: str, name: str, date: str, *, session) -> str:
    resp = session.post(
        f"{base_url}/v1/agent/restore/{date}", json={"name": name}, timeout=30
    )
    if resp.status_code == 202:
        return resp.json()["job_id"]
    raise OrchestratorError(
        f"POST /v1/agent/restore/{date} {resp.status_code}: {_detail(resp)}"
    )


def backup_agent(base_url: str, name: str, *, session) -> dict:
    resp = session.post(f"{base_url}/v1/agent/{name}/backup", timeout=120)
    if resp.status_code == 200:
        return resp.json()
    raise OrchestratorError(
        f"POST /v1/agent/{name}/backup {resp.status_code}: {_detail(resp)}"
    )


def poll_job(
    base_url: str,
    job_id: str,
    *,
    session,
    interval: float = 2.0,
    timeout: float = 300.0,
    on_poll=None,
    _sleep=time.sleep,
    _now=time.monotonic,
) -> dict:
    deadline = _now() + timeout
    while _now() < deadline:
        resp = session.get(f"{base_url}/v1/agent/job/{job_id}", timeout=30)
        resp.raise_for_status()
        job = resp.json()
        if on_poll is not None:
            on_poll(job)
        if job["status"] in ("succeeded", "failed"):
            return job
        _sleep(interval)
    raise TimeoutError(f"job {job_id} did not finish within {timeout}s")


def _step_streamer():
    """Return a callback for poll_job that prints each server-side step once,
    as it reaches a terminal state, so the operator sees live provisioning
    progress (render_config -> ensure_network -> pull_image -> run_container)."""
    seen: dict[str, str] = {}

    def on_poll(job: dict) -> None:
        for step in job.get("steps", []):
            name, status = step["name"], step["status"]
            if seen.get(name) == status:
                continue
            seen[name] = status
            if status == "running":
                print(f"        - {name} ...")
            elif status == "succeeded":
                print(f"        - {name}: ok")
            elif status == "failed":
                print(f"        - {name}: FAILED ({step.get('error', '')})")

    return on_poll


# --- output ---------------------------------------------------------------


def _print_result(result: dict) -> None:
    print("\nagent provisioned:")
    for key in (
        "user_id",
        "name",
        "display_name",
        "container_name",
        "container_id",
        "image",
        "server_ip",
        "gateway_port",
        "status",
    ):
        if key in result and result[key] is not None:
            print(f"  {key:<15} {result[key]}")


def chat(cfg: DeploymentConfig, slug: str, *, runner=subprocess.run) -> int:
    """Drop into the agent's ZeroClaw TUI over an interactive SSH session."""
    print(f"\nconnecting to {slug} (ctrl-d / 'exit' to leave)...\n")
    rc = runner(chat_cmd(cfg, slug)).returncode
    if rc != 0:
        print(
            f"\nchat exited with code {rc}. if it never started, the hardened "
            f"container (read-only rootfs, UID 65534) may reject the TUI. "
            f"reproduce manually with:\n  {' '.join(chat_cmd(cfg, slug))}"
        )
    return rc


# --- commands -------------------------------------------------------------


def cmd_launch(args, *, _input=input) -> int:
    errors = validate_inputs(args.name, args.user_id)
    if errors:
        for e in errors:
            print(e)
        return 1

    cfg = load_config()
    secrets = gather_secrets(args)
    payload = build_payload(
        name=args.name,
        user_id=args.user_id,
        display_name=args.display_name,
        **secrets,
    )

    base_url = f"http://127.0.0.1:{args.local_port}"
    session = requests.Session()
    proc = None
    try:
        print(f"[1/4] opening SSH tunnel to {cfg.server_host}:{REMOTE_PORT}")
        proc = open_tunnel(cfg, args.local_port)
        if not wait_for_port("127.0.0.1", args.local_port, proc=proc):
            if proc.poll() is not None:
                print(
                    f"      could not open tunnel: local port {args.local_port} is already "
                    f"in use (a stale tunnel?). close it and retry:\n"
                    f"        pkill -f 'ssh.*-L.*{args.local_port}'"
                )
            else:
                print("      tunnel did not come up on local port; aborting")
            return 1
        print(f"      tunnel up on 127.0.0.1:{args.local_port}")

        print(f"[2/4] POST {base_url}/v1/agent/create  (create {args.name!r} for user {args.user_id!r})")
        job_id = create_agent(base_url, payload, session=session)

        print(f"[3/4] polling GET {base_url}/v1/agent/job/{job_id}")
        job = poll_job(base_url, job_id, session=session, on_poll=_step_streamer())

        if job["status"] != "succeeded":
            print(f"\n[4/4] job FAILED: {job.get('error')}")
            for step in job.get("steps", []):
                print(f"        - {step['name']}: {step['status']}")
            return 1
        print("[4/4] succeeded")
        _print_result(job.get("result") or {})
    except (OrchestratorError, TimeoutError) as e:
        print(f"\nerror: {e}")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"\nnetwork error talking to the API through the tunnel: {e}")
        return 1
    finally:
        close_tunnel(proc)

    answer = _input(f"\nChat with {args.name} now? [y/N]: ").strip().lower()
    if answer in ("y", "yes"):
        return chat(cfg, args.name)
    print(f"later: zc chat --name {args.name}")
    return 0


def cmd_chat(args) -> int:
    return chat(load_config(), args.name)


def _with_tunnel(cfg, local_port, fn):
    """Open the tunnel, call fn(base_url, session), always close it. Returns the
    fn result, or None if the tunnel failed or the call raised a known error."""
    base_url = f"http://127.0.0.1:{local_port}"
    session = requests.Session()
    proc = None
    try:
        proc = open_tunnel(cfg, local_port)
        if not wait_for_port("127.0.0.1", local_port, proc=proc):
            if proc.poll() is not None:
                print(
                    f"could not open tunnel: local port {local_port} is already in use "
                    f"(a stale tunnel?). close it and retry:\n"
                    f"  pkill -f 'ssh.*-L.*{local_port}'"
                )
            else:
                print("tunnel did not come up on local port; aborting")
            return None
        try:
            return fn(base_url, session)
        except (OrchestratorError, TimeoutError) as e:
            print(f"\nerror: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"\nnetwork error talking to the API through the tunnel: {e}")
            return None
    finally:
        close_tunnel(proc)


def cmd_provider_list(args) -> int:
    data = _with_tunnel(
        load_config(), args.local_port, lambda b, s: list_providers(b, session=s)
    )
    if data is None:
        return 1
    cur = data.get("default", {})
    print(
        f"current default: profile={cur.get('profile')} "
        f"provider={cur.get('provider')} model={cur.get('model')}"
    )
    print("profiles:")
    for p in data.get("profiles", []):
        mark = "  <- active" if p["name"] == cur.get("profile") else ""
        keyed = "" if p.get("api_key_set") else "  (no key!)"
        print(f"  {p['name']:<10} {p['provider']}  ({p['model']}){mark}{keyed}")
    return 0


def cmd_provider_set(args) -> int:
    data = _with_tunnel(
        load_config(),
        args.local_port,
        lambda b, s: set_default_provider(b, args.profile, session=s),
    )
    if data is None:
        return 1
    d = data.get("default", {})
    print(f"default provider set -> {d.get('profile')} ({d.get('provider')} | {d.get('model')})")
    print("applies to NEW agents; existing containers keep their config until re-created")
    return 0


def cmd_agent_set_provider(args) -> int:
    if not SLUG_PATTERN.match(args.name):
        print(f"invalid agent name: {args.name}")
        return 1

    def fn(base_url, session):
        job_id = set_agent_provider(base_url, args.name, args.profile, session=session)
        print(f"switching {args.name} -> profile {args.profile!r} (recreating container)")
        print(f"polling GET {base_url}/v1/agent/job/{job_id}")
        return poll_job(base_url, job_id, session=session, on_poll=_step_streamer())

    job = _with_tunnel(load_config(), args.local_port, fn)
    if job is None:
        return 1
    if job["status"] != "succeeded":
        print(f"\nswitch FAILED: {job.get('error')}")
        return 1
    print(f"\n{args.name} is now on profile {args.profile!r}")
    _print_result(job.get("result") or {})
    return 0


def cmd_restore(args) -> int:
    if not SLUG_PATTERN.match(args.name):
        print(f"invalid agent name: {args.name}")
        return 1
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        print("date must be YYYY-MM-DD")
        return 1

    def fn(base_url, session):
        job_id = restore_agent(base_url, args.name, args.date, session=session)
        print(f"restoring {args.name} from {args.date} (snapshot current, then recreate)")
        print(f"polling GET {base_url}/v1/agent/job/{job_id}")
        return poll_job(base_url, job_id, session=session, on_poll=_step_streamer())

    job = _with_tunnel(load_config(), args.local_port, fn)
    if job is None:
        return 1
    if job["status"] != "succeeded":
        print(f"\nrestore FAILED: {job.get('error')}")
        return 1
    print(f"\n{args.name} restored from {args.date}")
    _print_result(job.get("result") or {})
    return 0


def cmd_backup(args) -> int:
    if not SLUG_PATTERN.match(args.name):
        print(f"invalid agent name: {args.name}")
        return 1
    data = _with_tunnel(
        load_config(), args.local_port, lambda b, s: backup_agent(b, args.name, session=s)
    )
    if data is None:
        return 1
    print(f"backed up {data['name']} ({data.get('size_bytes')} bytes)")
    print(f"location: {data['location']}")
    return 0


def cmd_delete(args, *, _input=input) -> int:
    if not SLUG_PATTERN.match(args.name):
        print(f"invalid agent name: {args.name}")
        return 1
    if not args.yes:
        answer = _input(
            f"Delete agent {args.name} (stop + remove container zeroclaw-{args.name})? [y/N]: "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("aborted")
            return 1

    cfg = load_config()
    base_url = f"http://127.0.0.1:{args.local_port}"
    session = requests.Session()
    proc = None
    try:
        print(f"[1/2] opening SSH tunnel to {cfg.server_host}:{REMOTE_PORT}")
        proc = open_tunnel(cfg, args.local_port)
        if not wait_for_port("127.0.0.1", args.local_port, proc=proc):
            if proc.poll() is not None:
                print(
                    f"      could not open tunnel: local port {args.local_port} is already "
                    f"in use (a stale tunnel?). close it and retry:\n"
                    f"        pkill -f 'ssh.*-L.*{args.local_port}'"
                )
            else:
                print("      tunnel did not come up on local port; aborting")
            return 1

        print(f"[2/2] DELETE {base_url}/v1/agent/delete/{args.name}")
        result = delete_agent(base_url, args.name, session=session)
        print(f"      removed {result['removed']}")
        if result.get("network_removed"):
            print(f"      removed network {result['network_removed']}")
    except (OrchestratorError, TimeoutError) as e:
        print(f"\nerror: {e}")
        return 1
    except requests.exceptions.RequestException as e:
        print(f"\nnetwork error talking to the API through the tunnel: {e}")
        return 1
    finally:
        close_tunnel(proc)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zc")
    sub = parser.add_subparsers(dest="command", required=True)

    launch = sub.add_parser("launch", help="create an agent via the API, then chat")
    launch.add_argument("--name", required=True)
    launch.add_argument("--user-id", dest="user_id", required=True)
    launch.add_argument("--display-name", dest="display_name")
    launch.add_argument("--slack", action="store_true", help="enable Slack + prompt for tokens")
    launch.add_argument("--slack-bot-token", dest="slack_bot_token")
    launch.add_argument("--slack-app-token", dest="slack_app_token")
    launch.add_argument("--slack-channel-id", dest="slack_channel_id")
    launch.add_argument("--composio", action="store_true", help="enable Composio + prompt for key")
    launch.add_argument("--composio-mcp-key", dest="composio_mcp_key")
    launch.add_argument("--llm-provider", dest="llm_provider")
    launch.add_argument("--llm-model", dest="llm_model")
    launch.add_argument("--local-port", dest="local_port", type=int, default=DEFAULT_LOCAL_PORT)
    launch.set_defaults(func=cmd_launch)

    chat_p = sub.add_parser("chat", help="re-attach to a running agent's TUI")
    chat_p.add_argument("--name", required=True)
    chat_p.set_defaults(func=cmd_chat)

    delete_p = sub.add_parser("delete", help="stop + remove an agent's container via the API")
    delete_p.add_argument("--name", required=True)
    delete_p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    delete_p.add_argument("--local-port", dest="local_port", type=int, default=DEFAULT_LOCAL_PORT)
    delete_p.set_defaults(func=cmd_delete)

    # provider list | provider set --profile X  (global default for NEW agents)
    provider_p = sub.add_parser("provider", help="manage the default LLM provider")
    provider_sub = provider_p.add_subparsers(dest="provider_cmd", required=True)
    pl = provider_sub.add_parser("list", help="list registry profiles + current default")
    pl.add_argument("--local-port", dest="local_port", type=int, default=DEFAULT_LOCAL_PORT)
    pl.set_defaults(func=cmd_provider_list)
    ps = provider_sub.add_parser("set", help="set the global default provider profile")
    ps.add_argument("--profile", required=True)
    ps.add_argument("--local-port", dest="local_port", type=int, default=DEFAULT_LOCAL_PORT)
    ps.set_defaults(func=cmd_provider_set)

    # agent set-provider --name N --profile X  (live switch, recreates container)
    agent_p = sub.add_parser("agent", help="per-agent operations")
    agent_sub = agent_p.add_subparsers(dest="agent_cmd", required=True)
    asp = agent_sub.add_parser("set-provider", help="switch a running agent's provider (live)")
    asp.add_argument("--name", required=True)
    asp.add_argument("--profile", required=True)
    asp.add_argument("--local-port", dest="local_port", type=int, default=DEFAULT_LOCAL_PORT)
    asp.set_defaults(func=cmd_agent_set_provider)

    # restore --name N --date YYYY-MM-DD  (from a host backup zip, recreates container)
    restore_p = sub.add_parser("restore", help="restore an agent's state from a backup + recreate")
    restore_p.add_argument("--name", required=True)
    restore_p.add_argument("--date", required=True, help="backup date, YYYY-MM-DD")
    restore_p.add_argument("--local-port", dest="local_port", type=int, default=DEFAULT_LOCAL_PORT)
    restore_p.set_defaults(func=cmd_restore)

    # backup --name N  (manual on-demand backup, returns the zip location)
    backup_p = sub.add_parser("backup", help="back up an agent's state to a host zip now")
    backup_p.add_argument("--name", required=True)
    backup_p.add_argument("--local-port", dest="local_port", type=int, default=DEFAULT_LOCAL_PORT)
    backup_p.set_defaults(func=cmd_backup)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
