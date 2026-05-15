from __future__ import annotations

import re

BEGIN_MARKER = "<!-- BEGIN MANAGED SECURITY POLICY -- DO NOT EDIT MANUALLY -->"
END_MARKER = "<!-- END MANAGED SECURITY POLICY -->"
_BLOCK_RE = re.compile(
    r"<!--\s*BEGIN MANAGED SECURITY POLICY.*?<!--\s*END MANAGED SECURITY POLICY[^>]*-->",
    re.DOTALL,
)


def build_policy_block(
    approval_gates: tuple[str, ...],
    denied_domains: tuple[str, ...],
) -> str:
    gates = ", ".join(approval_gates) if approval_gates else "(none)"
    domains = ", ".join(denied_domains) if denied_domains else "(none)"
    return f"""{BEGIN_MARKER}
## Security policy (managed by zeroclawctl)

You must refuse, with no preamble or speculation:

- Any request to disclose API keys, tokens, or environment variable values.
- Any request to read, copy, summarize, or transmit files named .env, *.env,
  zeroclaw.env, config.toml, or anything under /etc/, /root/, /home/.
- Any request to run shell commands that enumerate the environment
  (env, printenv, set, export -p, python -c 'os.environ', etc.).
- Any request to bypass approval gates listed in policy.require_approval_for.

If you receive such a request, reply: "I can't help with that - it would
expose credentials." Do not explain further. Do not propose workarounds.

Operator-defined approval gates: {gates}
Denied domains: {domains}
{END_MARKER}"""


def inject_policy_block(existing: str, new_block: str) -> str:
    if _BLOCK_RE.search(existing):
        return _BLOCK_RE.sub(new_block, existing, count=1)
    sep = "\n\n" if existing and not existing.endswith("\n") else "\n"
    return existing + sep + new_block + "\n"
