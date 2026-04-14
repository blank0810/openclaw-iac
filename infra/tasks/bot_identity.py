"""Seed OpenClaw workspace files (identity + skills) for all agents.

Follows the seed-once model per agent. A marker file (.identity-seeded) tracks
whether seeding has been done. After seeding, OpenClaw self-manages the workspace.

To force re-seed an agent: delete its .identity-seeded marker and redeploy.

Chaos note (2026-04-09): Chaos moved from `openclaw_data_chaos/` to `chaos/data/`
as part of the separation refactor. The legacy-dir fact is used as a second guard
to avoid re-seeding when the first-deploy-after-refactor migration is about to run.
See docs/plans/2026-04-09-chaos-agent-separation-design.md.
"""

from pyinfra import host
from pyinfra.operations import files, server
from pyinfra.facts.files import Directory, File

deploy_path = host.data.deploy_path

# Facts gathered at run start — used by the Chaos guard below.
chaos_legacy_data_exists = host.get_fact(
    Directory, path=f"{deploy_path}/openclaw_data_chaos"
)

# Each agent's data directory and workspace source.
agents = {
    "chaos": {
        "data_dir": "chaos/data",
        "workspace_src": "docker/workspace",
    },
}

for agent_name, agent_conf in agents.items():
    workspace_path = f"{deploy_path}/{agent_conf['data_dir']}/workspace"
    marker = f"{workspace_path}/.identity-seeded"

    identity_seeded = host.get_fact(File, path=marker)

    # Chaos-specific guard: on the first deploy after the separation refactor,
    # chaos/data does not exist yet at fact-gather time (migration runs later in
    # app_deploy.py). If the legacy openclaw_data_chaos still exists, we know the
    # migration is about to preserve the live workspace — DO NOT re-seed.
    skip_due_to_pending_migration = (
        agent_name == "chaos" and chaos_legacy_data_exists
    )

    if not identity_seeded and not skip_due_to_pending_migration:
        files.directory(
            name=f"[{agent_name}] Ensure workspace directory exists",
            path=workspace_path,
            user="1000",
            group="1000",
            mode="755",
        )

        files.directory(
            name=f"[{agent_name}] Ensure memory directory exists",
            path=f"{workspace_path}/memory",
            user="1000",
            group="1000",
            mode="755",
        )

        for skill_dir in ["channel-setup", "integration-setup"]:
            files.directory(
                name=f"[{agent_name}] Ensure {skill_dir} skill directory exists",
                path=f"{workspace_path}/skills/{skill_dir}",
                user="1000",
                group="1000",
                mode="755",
            )

        ws_src = agent_conf["workspace_src"]
        for filename in ["SOUL.md", "IDENTITY.md", "USER.md", "HEARTBEAT.md"]:
            files.put(
                name=f"[{agent_name}] Seed {filename}",
                src=f"{ws_src}/{filename}",
                dest=f"{workspace_path}/{filename}",
                user="1000",
                group="1000",
                mode="644",
            )

        for skill_dir in ["channel-setup", "integration-setup"]:
            files.put(
                name=f"[{agent_name}] Seed {skill_dir} skill",
                src=f"{ws_src}/skills/{skill_dir}/SKILL.md",
                dest=f"{workspace_path}/skills/{skill_dir}/SKILL.md",
                user="1000",
                group="1000",
                mode="644",
            )

        bootstrap_exists = host.get_fact(File, path=f"{workspace_path}/BOOTSTRAP.md")
        if bootstrap_exists:
            server.shell(
                name=f"[{agent_name}] Remove BOOTSTRAP.md",
                commands=[f"rm {workspace_path}/BOOTSTRAP.md"],
            )

        server.shell(
            name=f"[{agent_name}] Create identity-seeded marker",
            commands=[f"touch {marker} && chown 1000:1000 {marker}"],
        )
    elif skip_due_to_pending_migration:
        server.shell(
            name=f"[{agent_name}] Skipping identity seed (legacy data pending migration)",
            commands=[
                f"echo '{agent_name} legacy data still present; app_deploy.py will migrate it. Skipping identity seed to avoid overwriting drifted workspace.'"
            ],
        )
    else:
        server.shell(
            name=f"[{agent_name}] Identity already seeded (skipping)",
            commands=[f"echo '{agent_name} identity already seeded, skipping.'"],
        )
