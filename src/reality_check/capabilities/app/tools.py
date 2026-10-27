"""What the app's MCP server offers: the tool that opens the app, the tools its view calls, and its resources."""

from mcp.server.apps import APP_MIME_TYPE
from mcp.types import Resource, ResourceTemplate, Tool, ToolAnnotations

VIEW_URI = "ui://reality-check/app"
EVIDENCE_PREFIX = "reality-check://checks/"
APP_ONLY = {"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}}
# Copy buttons in the view write to the clipboard, which a sandboxed frame may only do when its host allows.
VIEW_META = {"ui": {"permissions": {"clipboardWrite": {}}}}
CHECK_ARGUMENTS = {
    "check_id": {"type": "string"},
    "checks_directory": {"type": "string", "description": "Absolute, as the check's summary gives it."},
}
OPEN_APP = Tool(
    name="open_app",
    description="Show the Reality Check app, where the user sees every check on this machine, past and running, with "
    "its report, evidence, and what its agent did, and return its browser URL. Hosts that render MCP Apps show it "
    "inline. Call it with the check's ID after starting a check, or when the user asks to see their checks. The app "
    "only shows checks; start, steer, and cancel them with the tool.",
    input_schema={
        "type": "object",
        "properties": {
            "check_id": {"type": "string", "description": "The check to open on; the newest when omitted."},
            "checks_directory": {
                "type": "string",
                "description": "Where that check is kept, absolute or relative to where this server started. Omit "
                "it to find the check in every project.",
            },
        },
    },
    # It serves a page on 127.0.0.1 and destroys nothing, so hosts that gate tools on these hints call it unasked.
    annotations=ToolAnnotations(destructive_hint=False, idempotent_hint=True, open_world_hint=False),
    _meta={"ui": {"resourceUri": VIEW_URI}},
)
LIST_CHECKS = Tool(
    name="list_checks",
    description="Every check on this machine, newest first, the check the app was last asked to open, and whether "
    "this machine can show a folder in a file manager. Called by the view.",
    input_schema={"type": "object", "properties": {}},
    _meta=APP_ONLY,
)
READ_CHECK = Tool(
    name="read_check",
    description="A check with its report and evidence. Called by the view.",
    input_schema={"type": "object", "properties": CHECK_ARGUMENTS, "required": ["check_id", "checks_directory"]},
    _meta=APP_ONLY,
)
READ_CHECK_ACTIVITY = Tool(
    name="read_check_activity",
    description="What a check's agent was asked, said, thought, and did, from a cursor, or one tool call in full. "
    "Called by the view.",
    input_schema={
        "type": "object",
        "properties": {**CHECK_ARGUMENTS, "after": {"type": "integer"}, "tool_call_id": {"type": "string"}},
        "required": ["check_id", "checks_directory"],
    },
    _meta=APP_ONLY,
)
OPEN_CHECK_FOLDER = Tool(
    name="open_check_folder",
    description="Show a check's folder in the file manager of the machine the app runs on. Called by the view.",
    input_schema={"type": "object", "properties": CHECK_ARGUMENTS, "required": ["check_id", "checks_directory"]},
    _meta=APP_ONLY,
)
VIEW_TOOLS = [LIST_CHECKS, READ_CHECK, READ_CHECK_ACTIVITY, OPEN_CHECK_FOLDER]
VIEW = Resource(uri=VIEW_URI, name="Reality Check app", mime_type=APP_MIME_TYPE)
EVIDENCE_FILE = ResourceTemplate(
    name="Evidence file",
    uri_template=f"{EVIDENCE_PREFIX}{{checks_directory}}/{{check_id}}/{{+path}}",
    description="A file from a check's evidence folder, as base64, for the app's view. `checks_directory` is the "
    "absolute checks directory, percent-encoded; `path` is the file's path from `read_check`, such as "
    "`evidence/01-home.png`.",
)
