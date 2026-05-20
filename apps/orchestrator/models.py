from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

from lib.config import SLUG_PATTERN


class SlackSpec(BaseModel):
    bot_token: str
    app_token: str
    channel_id: str | None = None


class ComposioSpec(BaseModel):
    mcp_api_key: str | None = None


class LlmSpec(BaseModel):
    provider: str | None = None
    model: str | None = None


class CreateAgentRequest(BaseModel):
    name: str
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


JobStatus = Literal["queued", "running", "succeeded", "failed"]
StepStatus = Literal["queued", "running", "succeeded", "failed"]


class StepState(BaseModel):
    name: str
    status: StepStatus = "queued"
    error: str | None = None


class AgentResult(BaseModel):
    name: str
    container_name: str
    server_ip: str
    host: str
    gateway_port: int
    status: str


class JobState(BaseModel):
    job_id: str
    status: JobStatus = "queued"
    steps: list[StepState] = []
    result: AgentResult | None = None
    error: str | None = None
