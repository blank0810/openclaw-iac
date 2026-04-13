from pyinfra import host
from pyinfra.facts.files import Directory, File
from pyinfra.operations import files, server

deploy_path = host.data.deploy_path
deploy_user = host.data.deploy_user

# Ensure the application directory exists and is owned by the deploy user.
files.directory(
    name=f"Create {deploy_path}",
    path=deploy_path,
    user=deploy_user,
    group=deploy_user,
    mode="750",
)

# Upload the Docker Compose file.
files.put(
    name="Upload docker-compose.yml",
    src="docker/docker-compose.yml",
    dest=f"{deploy_path}/docker-compose.yml",
    user=deploy_user,
    group=deploy_user,
    mode="644",
)

# Upload .env with tight permissions — it contains secrets.
files.put(
    name="Upload .env",
    src=".env",
    dest=f"{deploy_path}/.env",
    user=deploy_user,
    group=deploy_user,
    mode="600",
)

# --- Jarvis Agent (existing) ---
files.directory(
    name=f"Create {deploy_path}/openclaw_data",
    path=f"{deploy_path}/openclaw_data",
    user="1000",
    group="1000",
    mode="700",
)

config_dest = f"{deploy_path}/openclaw_data/openclaw.json"
config_exists = host.get_fact(File, path=config_dest)

if not config_exists:
    files.put(
        name="Seed Jarvis openclaw.json (first deploy only)",
        src="docker/openclaw.json",
        dest=config_dest,
        user="1000",
        group="1000",
        mode="600",
    )

# --- Chaos Agent (isolated subdirectory — see docs/plans/2026-04-09-chaos-agent-separation-design.md) ---
chaos_dir = f"{deploy_path}/chaos"
chaos_data_dir = f"{chaos_dir}/data"
legacy_chaos_data_dir = f"{deploy_path}/openclaw_data_chaos"
chaos_backup_dir = f"{deploy_path}/openclaw_data_chaos.bak.2026-04-09"
chaos_seeded_sentinel = f"{deploy_path}/.chaos-seeded"

# Facts gathered at run start — used by the sentinel guard in Step 10 and the
# migration-needed guard in Steps 2-3.
legacy_data_exists = host.get_fact(Directory, path=legacy_chaos_data_dir)
chaos_data_dir_exists = host.get_fact(Directory, path=chaos_data_dir)
chaos_already_seeded = host.get_fact(File, path=chaos_seeded_sentinel)

# Migration is needed only when the legacy directory still exists AND the new
# location doesn't yet (i.e., we're about to do the one-time mv). Steps 2-3
# (docker stop + barrier) only need to fire when migration is pending — on
# re-runs after a successful refactor, bouncing Chaos has no functional purpose.
needs_migration = legacy_data_exists and not chaos_data_dir_exists

# === STEP 1: Pre-flight sanity guard — detect silent data loss case ===
# If the sentinel claims Chaos is already seeded BUT the live config file is missing,
# something catastrophic happened (manual delete, volume corruption, failed rollback).
# Abort the deploy rather than let OpenClaw initialize fresh defaults.
server.shell(
    name="Pre-flight: detect sentinel + missing-config silent data loss case",
    commands=[
        (
            f"if [ -f {chaos_seeded_sentinel} ] && "
            f"   [ -d {chaos_data_dir} ] && "
            f"   sudo test ! -f {chaos_data_dir}/openclaw.json; then "
            f"  echo 'FATAL: sentinel exists but chaos/data/openclaw.json is missing.' >&2; "
            f"  echo 'Manual intervention required. See plan Section 10 rollback.' >&2; "
            f"  exit 1; "
            f"fi"
        )
    ],
    _timeout=30,
)

# === STEPS 2 & 3: Stop Chaos + barrier ONLY when migration is pending ===
# Avoids bouncing Chaos on re-runs that have nothing to migrate.
# When migration IS needed, the bind mount must be released before the mv in Step 7.
# Container restarts to pick up new compose configs are handled by `docker compose up -d`
# in Step 11, which only recreates when the service hash actually changes.
if needs_migration:
    # Step 2: Explicit graceful stop with extended grace (default --remove-orphans
    # grace is 10s, too short when Composio MCP shutdown RPCs hang).
    server.shell(
        name="Stop Chaos container gracefully (30s grace) — required for data migration",
        commands=["docker stop -t 30 openclaw-chaos || true"],
        _timeout=60,
    )

    # Step 3: Barrier — `docker stop` can return before the container is fully removed.
    # Poll for up to 60s. Fails loudly if Chaos is still running after the timeout.
    server.shell(
        name="Barrier: wait for Chaos container to fully exit before mv",
        commands=[
            (
                "for i in $(seq 1 60); do "
                "  if [ -z \"$(docker ps -a -q --filter name=openclaw-chaos --filter status=running)\" ] && "
                "     [ -z \"$(docker ps -a -q --filter name=openclaw-chaos --filter status=restarting)\" ]; then "
                "    exit 0; "
                "  fi; "
                "  sleep 1; "
                "done; "
                "echo 'FATAL: Chaos container still running after 60s. Aborting.' >&2; exit 1"
            )
        ],
        _timeout=90,
    )

# === STEP 4: Pull Jarvis image (runs before Jarvis compose up) ===
server.shell(
    name="Pull Jarvis OpenClaw image",
    commands=[f"cd {deploy_path} && docker compose pull"],
    _timeout=300,
)

# === STEP 5: Bring up Jarvis-only compose (sweeps any remaining orphan) ===
# Chaos is already stopped in Step 2-3, so --remove-orphans is just bookkeeping here.
# Plain `up -d` (no --force-recreate) keeps Jarvis untouched when its hash is unchanged.
server.shell(
    name="Start Jarvis via docker compose (Chaos already stopped)",
    commands=[f"cd {deploy_path} && docker compose up -d --remove-orphans"],
    _timeout=180,
)

# === STEP 6: Create chaos subdir (owned by uid 1000 so the container can read it) ===
files.directory(
    name=f"Create {chaos_dir}",
    path=chaos_dir,
    user="1000",
    group="1000",
    mode="750",
)

# === STEP 7: One-time data migration: openclaw_data_chaos -> chaos/data (with backup) ===
# Safe now because Chaos is stopped (Steps 2-3) and bind mount is released.
# Guarded so it only runs when the source exists and destination doesn't.
# Needs sudo because openclaw_data_chaos is mode 700 owned by uid 1000.
server.shell(
    name="Migrate Chaos data directory (one-time, guarded, with backup)",
    commands=[
        (
            f"if [ -d {legacy_chaos_data_dir} ] && [ ! -d {chaos_data_dir} ]; then "
            f"  cp -a {legacy_chaos_data_dir} {chaos_backup_dir} && "
            f"  mv {legacy_chaos_data_dir} {chaos_data_dir}; "
            f"fi"
        )
    ],
    _sudo=True,
    _timeout=300,
)

# === STEP 8: Ensure chaos/data exists even on fresh hosts (no-op if migration ran) ===
files.directory(
    name=f"Ensure {chaos_data_dir}",
    path=chaos_data_dir,
    user="1000",
    group="1000",
    mode="700",
)

# === STEP 9: Upload Chaos's dedicated compose file ===
files.put(
    name="Upload chaos/docker-compose.yml",
    src="docker/chaos/docker-compose.yml",
    dest=f"{chaos_dir}/docker-compose.yml",
    user=deploy_user,
    group=deploy_user,
    mode="644",
)

# --- Chaos SearXNG sidecar ---
# Directory must be root-owned. SearXNG's container entrypoint runs as root
# but cap_drop: ALL removes DAC_OVERRIDE, so it cannot write to directories
# it doesn't own. On first boot, SearXNG auto-generates settings.yml from
# its built-in template. Operators tune engines/UI on the server afterward.
chaos_searxng_dir = f"{chaos_dir}/searxng_data"

files.directory(
    name=f"Create {chaos_searxng_dir}",
    path=chaos_searxng_dir,
    user="0",
    group="0",
    mode="755",
    _sudo=True,
)

# === STEP 10: Sentinel-guarded seed-once ===
# Only fires when:
#   - legacy_data_exists is False (no migration happening this run), AND
#   - chaos_already_seeded is False (no prior seed on this host)
# This correctly handles: fresh host, existing server first-run-after-refactor,
# subsequent idempotent runs, and post-rollback re-attempts.
if not legacy_data_exists and not chaos_already_seeded:
    files.put(
        name="Seed Chaos openclaw.json (fresh host, first deploy)",
        src="docker/chaos/openclaw.json",
        dest=f"{chaos_data_dir}/openclaw.json",
        user="1000",
        group="1000",
        mode="600",
    )

# === STEP 11: Pull Chaos image and bring up Chaos via its own compose file ===
server.shell(
    name="Pull Chaos OpenClaw image",
    commands=[f"cd {chaos_dir} && docker compose --env-file ../.env pull"],
    _timeout=300,
)

server.shell(
    name="Start Chaos via its dedicated compose file",
    commands=[
        f"cd {chaos_dir} && docker compose --env-file ../.env up -d --remove-orphans"
    ],
    _timeout=180,
)

# === STEP 12: Unconditionally ensure the sentinel exists at the end of the Chaos section ===
# Idempotent: no-op if already present. Marks this host as "Chaos initialized" so
# subsequent runs correctly skip the seed step even when the legacy dir is gone.
files.file(
    name="Ensure Chaos seeded sentinel",
    path=chaos_seeded_sentinel,
    touch=True,
    user=deploy_user,
    group=deploy_user,
    mode="644",
)
