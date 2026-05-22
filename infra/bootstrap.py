# =============================================================================
# bootstrap.py — ONE-TIME FIRST-RUN SCRIPT. Run as root. Do not re-run.
#
# After this script completes:
#   - User overlord101 exists with SSH key access
#   - SSH listens on ports 22 AND 2222 (set in group_data/all.py +
#     infra/files/sshd_config; UFW opens both, fail2ban watches both)
#   - Root login via SSH is permanently disabled
#   - UFW and fail2ban are active
#
# Invocation (from project root):
#   pyinfra infra/inventories/bootstrap.py infra/bootstrap.py
#
# All subsequent deploys use:
#   pyinfra infra/inventories/deploy.py infra/deploy.py
# =============================================================================

from pyinfra import local

# Step 1: Create deploy user and install SSH keys
local.include("infra/tasks/deploy_user.py")

# Step 2: Harden SSH, enable UFW, configure fail2ban
# NOTE: sshd restarts at the end of this task — root SSH is disabled after it.
local.include("infra/tasks/hardening.py")
