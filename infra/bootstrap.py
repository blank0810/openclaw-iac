# =============================================================================
# bootstrap.py — ONE-TIME FIRST-RUN SCRIPT. Run as root. Do not re-run.
#
# After this script completes:
#   - User overlord101 exists with SSH key access
#   - Port 22 is firewalled; SSH only accepts connections on port 2222
#   - Root login via SSH is permanently disabled
#   - UFW and fail2ban are active
#
# Invocation (run once from project root):
#   pyinfra --user root --port 22 --key $SSH_KEY_PATH $SERVER3_IP infra/bootstrap.py
#
# All subsequent deploys use:
#   pyinfra infra/inventory.py infra/deploy.py
# =============================================================================

from pyinfra import local

# Step 1: Create deploy user and install SSH keys
local.include("infra/tasks/deploy_user.py")

# Step 2: Harden SSH, enable UFW, configure fail2ban
# NOTE: sshd restarts at the end of this task — root SSH is disabled after it.
local.include("infra/tasks/hardening.py")
