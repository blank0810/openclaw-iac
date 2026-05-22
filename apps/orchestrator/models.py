from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

from lib.config import SLUG_PATTERN


def _no_control_chars(v: str | None) -> str | None:
    """Reject any control character (\\x00-\\x1f, \\x7f). These survive
    _toml_str() unescaped and would corrupt the agent.toml — and because
    load_config scans every agents/* dir, one malformed file breaks ALL
    subsequent creates. Caught here so no disk write ever happens (clean 422)."""
    if v is not None and any(ord(c) < 0x20 or ord(c) == 0x7F for c in v):
        raise ValueError("control characters are not allowed")
    return v


class SlackSpec(BaseModel):
    bot_token: str
    app_token: str
    channel_id: str | None = None

    @field_validator("bot_token", "app_token", "channel_id")
    @classmethod
    def _reject_control_chars(cls, v: str | None) -> str | None:
        return _no_control_chars(v)


class ComposioSpec(BaseModel):
    mcp_api_key: str | None = None

    @field_validator("mcp_api_key")
    @classmethod
    def _reject_control_chars(cls, v: str | None) -> str | None:
        return _no_control_chars(v)


class LlmSpec(BaseModel):
    provider: str | None = None
    model: str | None = None


class CreateAgentRequest(BaseModel):
    name: str
    user_id: str
    display_name: str | None = None
    slack: SlackSpec | None = None
    composio: ComposioSpec | None = None
    llm: LlmSpec | None = None

    @field_validator("name")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError(
                f"name must match {SLUG_PATTERN.pattern} "
                "(lowercase letters, digits, hyphen; start with letter/digit)"
            )
        return v

    @field_validator("user_id")
    @classmethod
    def _valid_user_id(cls, v: str) -> str:
        if not v:
            raise ValueError("user_id must not be empty")
        return _no_control_chars(v)


JobStatus = Literal["queued", "running", "succeeded", "failed"]
StepStatus = Literal["queued", "running", "succeeded", "failed"]


class StepState(BaseModel):
    name: str
    status: StepStatus = "queued"
    error: str | None = None


class AgentResult(BaseModel):
    user_id: str
    name: str
    display_name: str
    container_name: str
    container_id: str
    image: str
    server_ip: str
    host: str
    gateway_port: int
    status: str


class JobState(BaseModel):
    job_id: str
    slug: str | None = None
    status: JobStatus = "queued"
    steps: list[StepState] = []
    result: AgentResult | None = None
    error: str | None = None


class DeleteResult(BaseModel):
    removed: str                        # container name (f"zeroclaw-{slug}")
    container_id: str | None = None
    network_removed: str | None = None  # f"zc-{slug}" if it was removed
    status: str = "deleted"


class SetProviderRequest(BaseModel):
    profile: str                        # a name from the server-side registry

    @field_validator("profile")
    @classmethod
    def _valid_profile(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("profile must not be empty")
        return _no_control_chars(v)


class RestoreRequest(BaseModel):
    name: str                           # agent slug; date is a path param

    @field_validator("name")
    @classmethod
    def _valid_slug(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError(f"name must match {SLUG_PATTERN.pattern}")
        return v


class BackupResult(BaseModel):
    name: str
    date: str                           # YYYY-MM-DD
    location: str                       # absolute path to the zip on the host
    size_bytes: int
    status: str = "ok"
