from __future__ import annotations

DEFAULT_EXEC_DENY_PATTERNS: tuple[str, ...] = (
    "env",
    "printenv",
    "set",
    "export",
    "export -p",
    "cat *.env",
    "cat */.env",
    "cat */zeroclaw.env",
    "cat /opt/zeroclaw/**",
    "cat /etc/**",
    "cat /root/**",
    "cat /home/**",
    "python -c*os.environ*",
    "python3 -c*os.environ*",
    "node -e*process.env*",
    "bash -c*env",
    "sh -c*env",
    "grep -r * /etc",
    "find / -name *.env",
    "curl*169.254.169.254*",
)


def default_exec_deny_patterns() -> tuple[str, ...]:
    return DEFAULT_EXEC_DENY_PATTERNS
