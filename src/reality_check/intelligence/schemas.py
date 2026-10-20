"""What an intelligence implementation is asked to do, what it reports while it works, and what it answers with."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from reality_check.schemas import DEFAULT_INTELLIGENCE_REASONING_EFFORT, ReasoningEffort

# How a steering message lands: in the current turn, when the agent next reads input, or by restarting the run.
Steering = Literal["mid-turn", "queued", "restart"]
AgentEventKind = Literal["message", "reasoning", "tool_call", "tool_result", "usage", "terminal"]
# The images an agent can be shown, by suffix.
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class HostWorkspace(BaseModel):
    """A directory on this machine; the agent's tools execute here."""

    path: Path


class McpServer(BaseModel):
    """A local MCP server the agent starts and talks to over stdio."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = Field(default=None, description="The server's environment; None inherits the agent's")
    cwd: Path | None = None


class AgentRequest(BaseModel):
    """One agent run: a prompt, a model, and optionally a place to work and tools to add."""

    prompt: str
    model: str
    workspace: HostWorkspace | None = Field(
        default=None, description="The agent's working directory; None leaves it to the agent provider"
    )
    reasoning_effort: ReasoningEffort | None = Field(
        default=DEFAULT_INTELLIGENCE_REASONING_EFFORT, description="None sends none, for a model that takes none"
    )
    timeout_seconds: int | None = Field(gt=0, description="How long the run may take; None for no limit")
    resume: str | None = Field(
        default=None,
        description="The session_id of an earlier result to continue in, so the agent keeps what it learned; None starts fresh",
    )
    mcp_servers: dict[str, McpServer] = Field(
        default_factory=dict, description="MCP servers added beside the agent provider's built-in tools, by name"
    )
    skill_directories: list[Path] = Field(
        default_factory=list, description="Directories of Agent Skills the agent may load when a task needs one"
    )
    output_schema: dict[str, Any] | None = Field(
        default=None, description="JSON schema the structured output must satisfy; None asks for text only"
    )
    images: list[Path] = Field(default_factory=list, description="Images shown to the agent with the prompt")
    session_directory: Path | None = Field(
        default=None,
        description="Where the agent provider keeps this run's session, so it can be read and resumed from there; None "
        "leaves it where the agent provider keeps its sessions",
    )


class AgentEvent(BaseModel):
    """One thing the agent did, in the same shape for every agent provider; `terminal` comes last, once."""

    time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    kind: AgentEventKind
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """The run's outcome; in-flight agent failures set `error` instead of raising."""

    output: dict[str, Any] | None = Field(
        default=None, description="The structured output, conforming to the request's schema when one was given"
    )
    text: str = Field(default="", description="The agent's final message")
    error: str | None = None
    cancelled: bool = Field(default=False, description="Whether the run ended because it was cancelled")
    session_id: str | None = Field(
        default=None, description="Identifies this run's session so a later request can resume it"
    )
