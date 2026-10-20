# Library Reference

Every capability of Reality Check is reachable from `reality_check.lib`.
All other surfaces, including the CLI, are thin wrappers over the library and add no capability of their own.

## Check software

The main capability. Give it a request and, optionally, where the software is. An agent investigates the task, uses the software as a user does, gathers evidence, and the check ends with a report.
Model-backed. Asynchronous: a check runs for minutes, so it streams events while it works and can be steered.

```python
async def check_software(
    request: str,                     # what to check, in plain words; may name files, read relative to the working directory
    target: str | None = None,        # where the software is: a URL, a universe id, a profile, a path, or a description; None when the request says
    resume: str | None = None,        # an earlier check's check_id: continue its agent session, with request as the next message
    previous_checks: list[Path] | None = None,  # earlier checks' directories, for the request to refer to
    ask_first: AskFirst = "when-off", # when to stop and ask before the work starts; see below
    keep_running: bool = False,       # leave running what this check started, for later checks
    checks_directory: Path = DEFAULT_CHECKS_DIRECTORY,  # where checks are kept; .agents/reality-check, relative to the working directory
    agent_provider: AgentProvider | None = None,  # copilot, amplifier-agent, codex, or claude; when None, the resumed check's, else the first installed, copilot first
    model: str | None = None,         # the agent provider's default in DEFAULT_INTELLIGENCE_MODELS when None; one of INTELLIGENCE_MODELS
    reasoning_effort: ReasoningEffort | None = None,  # high when None, and none sent for a model that takes none
    timeout_seconds: int | None = DEFAULT_TIMEOUT_SECONDS,  # 3600; None for no limit; see below
    images: list[Path] | None = None, # images shown to the agent with the request; copied into the check
    origin: str = DEFAULT_ORIGIN,     # who starts the check, such as "app" or "claude-code:<session id>"; "unknown" by default
    detach: bool = False,             # run the check in a process of its own that outlives this one
    intelligence: Intelligence | None = None,
) -> CheckRun
```

Without an injected `intelligence`, a model not in `INTELLIGENCE_MODELS`, an effort it does not take, or images for a model without vision raise at once, before the check exists. When the agent starts, the agent provider's own client checks the same against the account, so a model the account does not have fails the check instead of running another.

`check_software` returns as soon as the check has started. The `CheckRun` is the handle to it:

```python
class CheckRun(Protocol):
    check_id: str
    directory: Path

    def events(self) -> AsyncIterator[CheckEvent]   # from the start, then live until the check ends
    async def steer(self, message: str) -> None     # a message to the agent while it works
    async def cancel(self) -> None                  # end the check; its session can still be resumed
    async def result(self) -> CheckResult           # wait for the end
```

`InProcessCheckRun` runs the agent in this process. With `detach`, `DetachedCheckRun` follows a check that runs in a process of its own, started apart from the caller's session and job, through the files it writes; what that process prints goes to `process.log` in the check. A check that cannot start raises the same error either way. `detach` with an `intelligence` raises `detach-with-intelligence`.

Another process can steer or cancel a running check by its `check_id`. The message or the cancel is written to the check's directory and acted on by the process that runs the check. Both are deterministic.

```python
def steer_check(
    check_id: str, message: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY, origin: str = DEFAULT_ORIGIN
) -> None

def cancel_check(check_id: str, checks_directory: Path = DEFAULT_CHECKS_DIRECTORY) -> None
```

Both raise `check-not-found`, `check-not-running` when the check has ended, and `check-crashed` when its process is gone before it ended. A crashed check is resumed like any other; resuming a check that is still running raises `check-running`.

`CheckEvent` carries the `check_id`, a time, a `kind`, and the text or data for it:

```
started     the check began; its check_id, directory, and the whole request: the arguments, the process, and the AgentRequest
progress    what the agent is doing, in its words
reasoning   what the agent thought, when the model thinks
tool        a tool the agent called, and its result; text is shortened, data keeps the arguments and result in full
usage       one model call's tokens, with fresh_input_tokens, and its billing when the agent provider reports one
steered     a steering message was delivered, or `error` says why not; `origin` says who sent it
finished    the CheckResult
failed      a RealityCheckError, with its code and remedy
```

### Stopping to ask, and resuming

The agent first investigates the task: the request, its context, the target, and what the caller's machine has.
`ask_first` decides when it stops there before the work starts:

```
when-off   stop only when something seems off, such as computer use not enabled or a tester not installed; the default
always     stop and show what it will check and how
never      do not stop; what seems off is noted in the report, and the check goes on as far as it can
```

A check that stops ends `done`, and its report holds what it needs from the caller. The caller answers with a new check: `check_software(request="<the answer>", resume=<check_id>)`.
`resume` continues the same agent session on the same agent provider, so nothing the agent learned is lost. It is also how checks follow each other on software that was kept running: each one resumes the last.

### Result

```
CheckResult
  check_id, status (done | cancelled | timed-out), session_id, agent_provider
  report: the agent's final message, its report in Markdown
  directory: the check's directory
  next: the exact command that resumes this check
  timeout_seconds: the check's deadline; None when it had none
  elapsed_seconds
  usage: CheckUsage
    model_calls, fresh_input_tokens, cache_read_tokens, cache_write_tokens, output_tokens, reasoning_tokens
    billing: what the agent provider bills, by unit such as USD or AIU; empty when it reports none
```

`fresh_input_tokens` is input read from no cache, counted the same way for every agent provider; the `input_tokens` of a `usage` event is the agent provider's own count, which may include cached tokens.

### Timeouts

A check stopped at its deadline often has no report, so set `timeout_seconds` generously: about an hour for a focused request, several hours for a broad one, and None for a long checklist. At 85% of it, the check steers the agent, with origin `reality-check`, to stop testing and report in the time left. A check still running at the deadline is cancelled, ends `timed-out`, and raises `CheckTimeoutError`, whose `result` holds what it had; its `failed` event has code `check-timeout`.

A report that says the software failed is a result, not an exception.

### The check's directory

```
<checks_directory>/<check_id>/
  check.json     the CheckRecord: the request, model, status, timeout_seconds, usage, session_id, pid, last_event, origin, images
  events.jsonl   every CheckEvent, in full
  report.md      the agent's final message
  session/       the agent provider's own state for the session, resumed from a copy by a later check
  images/        the images the agent was shown
  evidence/      what the agent recorded; report.md refers to each file relative to the check's directory
  steer/, cancel what other processes write for the running check
  process.log    what a detached check's process printed
```

## Read check activity

A check's state and its activity, from its files, in any process: what was asked, what the agent said, thought, and did, steering, and how it ended. Deterministic.

```python
def read_check_activity(
    check_id: str,
    after: int | None = None,         # the cursor of an earlier read: only what came after
    tool_call_id: str | None = None,  # only that tool call and its result, with arguments, result, and detailed_result
    checks_directory: Path = DEFAULT_CHECKS_DIRECTORY,
) -> CheckActivity
```

`CheckActivity` holds the `CheckRecord`, the `state` (`running`, `crashed`, `done`, `cancelled`, `timed-out`, or `failed`), the `process_log` path when there is one, the `entries`, and the `cursor` to pass as `after`. Each `ActivityEntry` has a time, a `kind` (`request`, `said`, `reasoning`, `tool`, `tool-result`, `usage`, `steered`, `ended`), its text, the `origin` of a request or steering, and data.
Raises `check-not-found`, `bad-cursor`, and `tool-call-not-found`.

## List intelligence models

The models a check runs on, `INTELLIGENCE_MODELS` for the installed agent providers, each with its reasoning efforts and whether it can be shown images, and what runs when none is given. Deterministic: it asks no agent provider.

```python
def list_intelligence_models() -> IntelligenceModels
```

The list is the models Reality Check supports and recommends, not what an agent provider offers, and changes only with the tool.

## Install computer use

Installs cua-driver, which checks drive desktop apps with, once per machine. Deterministic: it asks no agent provider.

```python
def install_computer_use() -> ComputerUseInstall
```

The version is pinned with the SHA-256 of each release asset. An install of that version on PATH or from cua-driver's own installer is used as it is; otherwise the asset is downloaded, checked against its hash, and unpacked into reality-check's user data folder. The target is the desktop to drive: under WSL it is Windows, so the Windows build goes into the Windows user's LocalAppData. On macOS, `CuaDriver.app` goes into `/Applications`, where its permissions attach. Run again, it reports what is there.

## What the agent gets

The check runs the way a sub-agent does: the agent provider's harness as it ships, with its built-in tools, and a short prompt made from a template. Reality Check adds only:

- The prompt. The template fills in the request, the target, the paths of the files the request names, the check's `evidence/` directory, the previous checks' directories, whether computer use is enabled, `ask_first`, and `keep_running`. It says what the report, the agent's final message, must cover, not how to do the work.
- Skills: the ones in [Skills for checking software](#skills-for-checking-software), passed as skill directories, so the agent loads one only when the task needs it.
- Digital Twin Universe: its CLI, by the path in this environment, and its skill. The agent uses it to launch a universe, to work in one the caller named, and to destroy what it launched, unless `keep_running` is set.
- Computer use: when `install_computer_use` has run and the desktop allows it, the check starts the cua-driver daemon and gives the agent a command that runs cua-driver and the using-computer-use skill. When cua-driver is not installed, the prompt gives the agent `install-computer-use` and the command it will run through, and the check makes computer use ready as soon as the install is there. When it cannot be used for any other reason, the prompt says why and what enables it, and `ask_first` decides whether the agent stops. A daemon the check started is stopped when the last check using it ends; one the user started is left running.

Everything else, such as a browser on another machine or a tester the caller installed, the agent finds and uses on its own. When the agent needs more from Reality Check, it is added here, and not built in ahead of need.

Reality Check never destroys what it did not start. The agent reports anything it started and did not stop, with the command that stops it.

## Skills for checking software

General skills for checking software as a user does, each a deterministic capability that returns the skill's content, the way `--help` returns a capability's.
The agent in `check_software` gets the same skills, and a caller's agent can read one when it does a check itself.

```python
def reaching_software_skill() -> str    # reaching software where it runs: LAN URLs instead of localhost, SSH and Tailscale, universes on another machine
def using_software_skill() -> str       # seeing and using software as a user: a browser that is already open, computer use, a terminal, testers for native apps
def using_computer_use_skill() -> str   # driving a desktop app's real UI through cua-driver: screenshots, the accessibility tree, input
def gathering_evidence_skill() -> str   # what evidence to gather for each kind of software, and where to put it
```

Each skill is a directory under `skills/` in the package, in the [Agent Skills](https://agentskills.io/specification) format, and a row in `CAPABILITIES`. It is returned in the same wrapper as `skill()`, so the reader knows where its files are.
A new skill is a new directory and a new `<name>_skill` capability.

## Intelligence

Model-backed capabilities run through the `Intelligence` protocol in `reality_check.intelligence.interface`:

```python
class Intelligence(Protocol):
    implementation: str
    steering: Steering  # "mid-turn", "queued", or "restart"

    def preflight(self) -> None: ...
    async def start(self, request: AgentRequest) -> AgentRun: ...


class AgentRun(Protocol):
    def events(self) -> AsyncIterator[AgentEvent]: ...
    async def steer(self, message: str) -> None: ...
    async def cancel(self) -> None: ...
    async def result(self) -> AgentResult: ...
```

`preflight` raises `RealityCheckError` naming what to configure when the implementation cannot run.
`start` starts one agent and returns once it runs, and may raise `RealityCheckError` for a request its implementation cannot run. `AgentRequest` holds the prompt, model, optional reasoning effort, optional workspace, optional output schema, the MCP servers and skill directories to add, the `images` shown with the prompt, `resume`, and `session_directory`, where the agent provider keeps the session when set. `AgentResult` holds the agent's final message, the structured output, or the error, and the `session_id`.
With an output schema, the agent answers in that schema: through a `submit` tool on `copilot` and `amplifier-agent`, and through the SDK's own structured output on `codex` and `claude`. A missing or invalid answer is sent back to the agent twice at most; after that the result's `error` says why.
The agent provider's built-in tools are always kept. Every implementation runs with its agent provider's telemetry turned off, approves every tool call, and keeps the caller's instructions out where its SDK allows.
Setting `AgentRequest.resume` to an earlier `AgentResult.session_id` continues that session instead of starting a fresh one, so the agent keeps what it learned. Every implementation resumes across processes.
`cancel` drains the run so that its session can still be resumed.

`AgentEvent` is one shape for every agent provider: a time, a `kind` (`message`, `reasoning`, `tool_call`, `tool_result`, `usage`, `terminal`), and its text or data. Each implementation maps its SDK's own events onto it.

`steer` sends a message to a running agent. How it lands depends on the agent provider, and `steering` says which:

```
mid-turn   delivered into the current turn                             copilot (send, mode "immediate"), codex (turn.steer)
queued     delivered when the agent next reads input                   claude (query while a response streams)
restart    the turn is cancelled and the message starts the next turn  amplifier-agent, which refuses a second turn while one runs
```

Only `copilot` takes MCP servers; the others raise `mcp-not-supported` for a request that has any.

`resolve_intelligence(agent_provider)` returns a shipped implementation, one per agent provider, each installed through the extra of the same name:

- `copilot`: `CopilotIntelligence`, built on the [GitHub Copilot SDK](https://github.com/github/copilot-sdk) and signed in through the GitHub CLI. A session is resumed with `resume_session`, from the session state the Copilot CLI keeps, or from `session_directory` passed as `config_directory`. Before a session, the run's own client lists the account's models, and `start` raises `model-not-available`, `bad-reasoning-effort`, or `model-without-vision`. Images are file attachments on the first prompt. MCP servers and skill directories are passed when the session is created or resumed. The `submit` tool is a terminal tool, so a valid call ends the turn. Session telemetry is off. Its `usage` events also carry the SDK's `cost`, the model's premium request multiplier, and `copilot_usage`.
- `amplifier-agent`: `AmplifierAgentIntelligence`, built on [Amplifier Agent](https://github.com/microsoft/amplifier-agent), in process. The model is `<provider>/<model>`, and `preflight` checks that provider's credentials. Sessions live in `session_directory`, else under the platform's per-user state directory, in `reality-check/amplifier-agent`, and are resumed with `resume_session`. Skill directories are set on the agent, which is built for each request. The `AGENTS.md` files that apply to the workspace are always part of its instructions. Its `usage` events carry `cost` by currency.
- `codex`: `CodexIntelligence`, built on the [OpenAI Codex SDK](https://github.com/openai/codex/tree/main/sdk/python) and run with the user's Codex sign-in and `~/.codex/config.toml`, with full access and no approval prompts. A session is a Codex thread, resumed with `thread_resume` from the Codex home; a copy of its rollout is kept in `session_directory`. Skill directories are copied into the workspace's `.agents/skills`, where Codex finds them, and left there.
- `claude`: `ClaudeIntelligence`, built on the [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) and run without the user's Claude Code settings, with the credentials Claude Code resolves from the environment: `ANTHROPIC_API_KEY`, or a cloud provider's, as [its docs](https://code.claude.com/docs/en/agent-sdk/quickstart) describe. Sessions are kept in `session_directory`, else where Claude Code keeps them, and resumed with the `resume` option; a plain completion runs in the platform's per-user state directory, in `reality-check/claude`. Skill directories are copied into one local plugin there, `reality-check`. Its `usage` events carry `cost` by currency.

Without an agent provider named, the first installed in that order is used, so `copilot` is the default; one that is not installed raises `RealityCheckError` with the command that installs it.
`select_intelligence(intelligence, agent_provider, model, DEFAULT_INTELLIGENCE_MODELS)` is what a capability calls: an injected `intelligence` wins, and `model` falls back to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS`.
Another implementation is a module satisfying the protocol and a branch in that factory.

## Manifest

The tool's `SMART_TOOL.md` as structured data: the frontmatter as fields, the Markdown below it as `Manifest.body`.

```python
def load_manifest() -> Manifest
```

## Skill

What an agent reads once it has decided to drive the tool: the manifest body and the capability list, wrapped so the reader knows where the tool's files are.
Naming a capability returns that capability's own skill instead: the same wrapper, a heading carrying the capability's name, whether it is deterministic or model-backed, and the Markdown beside its code, which covers its arguments, a worked invocation, and its result.
The CLI's `--help` prints exactly this, the tool's at the root and the capability's on a command.
Raises `RealityCheckError` when the name is not a capability, naming the ones that are.

```python
def skill(capability: str | None = None) -> str
```

The capabilities the skill lists, one entry each, driven by the same table the CLI is built from:

```python
class Capability(NamedTuple):
    name: str
    summary: str
    model_backed: bool
    skill: str
    resources: tuple[str, ...] = ()
```

- `name` and `summary`: the command's name and its line in the tool's capability list.
- `model_backed`: whether it runs through the `Intelligence` interface, which decides the kind shown in both skills.
- `skill`: the capability's skill body, a Markdown file relative to the installed package root, written without frontmatter, title, or kind line because the renderer supplies them.
- `resources`: the files that body refers to, relative to the installed package root, listed under `<skill_resources>` in the capability's skill. The block is omitted when there are none.

## Version

The installed package's version, from its metadata. The CLI's `--version` prints it.

```python
def version() -> str
```

## Adding a capability

A capability's code goes in `reality_check/capabilities/<name>/`, with its prompts, templates, and its own `skill_<capability>.md` beside it, named on its row in `core/skill.py` `CAPABILITIES`, and `lib.py` gets a facade function that imports it and is the only caller of it.
Each capability of the library gets a section here: what it does and when to reach for it, the signature `lib.py` exposes, what each argument means, and what it returns or raises.
Model-backed capabilities say so, and take `agent_provider`, `model`, `reasoning_effort`, and `intelligence`. `model` defaults to the agent provider's entry in `DEFAULT_INTELLIGENCE_MODELS` and `reasoning_effort` to `high`, both from `reality_check.schemas`.
