"""Runs inside the evaluation environment, with reality-check installed beside it: the judge agent.

`judge.py CONFIG` reads the prompt, schema, and model from CONFIG, runs one agent through reality-check's
intelligence, writes each event to events.jsonl beside CONFIG as it happens, and the result to result.json.
"""

import asyncio
import json
from pathlib import Path
import sys

from reality_check.intelligence.interface import resolve_intelligence
from reality_check.intelligence.schemas import AgentRequest, HostWorkspace


async def judge(config_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    intelligence = resolve_intelligence(config["agent_provider"], config["model"])
    intelligence.preflight()
    run = await intelligence.start(
        AgentRequest(
            prompt=config["prompt"],
            model=config["model"],
            reasoning_effort=config["reasoning_effort"],
            workspace=HostWorkspace(path=Path(config["workspace"])),
            timeout_seconds=config["timeout_seconds"],
            output_schema=config["output_schema"],
        )
    )
    with (config_path.parent / "events.jsonl").open("a", encoding="utf-8") as events:
        async for event in run.events():
            events.write(event.model_dump_json() + "\n")
            events.flush()
    result = await run.result()
    (config_path.parent / "result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(judge(Path(sys.argv[1])))
