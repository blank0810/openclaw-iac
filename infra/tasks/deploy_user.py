"""
deploy_user.py — Create the deploy user and configure SSH access.

Run as root during bootstrap (infra/bootstrap.py). Idempotent: safe to re-run.

Operations:
  1. Create user overlord101 with home dir and bash shell
  2. Ensure overlord101 is in the sudo group
  3. Create ~/.ssh/ with mode 700
  4. Write authorized_keys from team_ssh_keys with mode 600
  5. Write passwordless sudoers drop-in to /etc/sudoers.d/overlord101
"""

from io import StringIO

from pyinfra import host
from pyinfra.operations import files, server

# Pull shared config from group_data/all.py
deploy_user = host.data.deploy_user          # "overlord101"
team_ssh_keys = host.data.team_ssh_keys      # list of SSH public key strings

# ---------------------------------------------------------------------------
# 1. Create the deploy user
# ---------------------------------------------------------------------------
server.user(
    name=f"Create user {deploy_user}",
    user=deploy_user,
    present=True,
    home=f"/home/{deploy_user}",
    shell="/bin/bash",
    ensure_home=True,
)

# ---------------------------------------------------------------------------
# 2. Add to sudo group
# ---------------------------------------------------------------------------
server.group(
    name="Ensure sudo group exists",
    group="sudo",
    present=True,
)

server.user(
    name=f"Add {deploy_user} to sudo group",
    user=deploy_user,
    groups=["sudo"],
    append=True,
)

# ---------------------------------------------------------------------------
# 3. Create ~/.ssh/ directory with correct permissions
# ---------------------------------------------------------------------------
files.directory(
    name=f"Create /home/{deploy_user}/.ssh",
    path=f"/home/{deploy_user}/.ssh",
    present=True,
    user=deploy_user,
    group=deploy_user,
    mode="700",
)

# ---------------------------------------------------------------------------
# 4. Write authorized_keys from team_ssh_keys
# ---------------------------------------------------------------------------
if not team_ssh_keys:
    raise RuntimeError(
        "team_ssh_keys is empty in group_data/all.py — "
        "add at least one public key before running bootstrap, "
        "or you will be locked out of the server."
    )

authorized_keys_content = "\n".join(team_ssh_keys) + "\n"

files.put(
    name=f"Upload authorized_keys for {deploy_user}",
    src=StringIO(authorized_keys_content),
    dest=f"/home/{deploy_user}/.ssh/authorized_keys",
    user=deploy_user,
    group=deploy_user,
    mode="600",
)

# ---------------------------------------------------------------------------
# 5. Passwordless sudoers drop-in
# ---------------------------------------------------------------------------
sudoers_content = f"{deploy_user} ALL=(ALL) NOPASSWD:ALL\n"

files.put(
    name=f"Write sudoers drop-in for {deploy_user}",
    src=StringIO(sudoers_content),
    dest=f"/etc/sudoers.d/{deploy_user}",
    user="root",
    group="root",
    mode="440",
)
