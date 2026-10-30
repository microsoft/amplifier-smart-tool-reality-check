import assert from "node:assert/strict";
import test from "node:test";

import { blocksOf, latestSaid, toolSteps } from "../src/lib/activity.ts";
import { isCut, readEvent, readToolCall } from "../src/lib/api.ts";
import { app } from "../src/lib/host.ts";

const ref = { checks_directory: "/project/checks", check_id: "check" };

function event(id, kind, text = "", data = {}) {
  return {
    id,
    check_id: ref.check_id,
    time: `2026-10-27T00:00:0${id}Z`,
    kind,
    text,
    data,
  };
}

const events = [
  event(1, "started", "Check check started.", {
    request:
      "Check the page...[cut at 500 of 900 chars; full: line 1 of events.jsonl]",
    origin: "app",
  }),
  event(2, "progress", "Opening the page."),
  event(3, "reasoning", "**Plan**\nOpen it."),
  event(4, "tool", 'bash {"command": "curl http://localhost"}', {
    tool_call_id: "call-1",
    tool_name: "bash",
    phase: "call",
  }),
  event(6, "tool", "<html>", {
    tool_call_id: "call-1",
    success: false,
    phase: "result",
  }),
  event(7, "steered", "Use the second account.", {
    steering: "mid-turn",
    origin: "app",
  }),
  event(8, "finished", "Check done.", { status: "done", report: "# Report" }),
];

test("events become the timeline's request, messages, steps, steering, and ending", () => {
  const blocks = blocksOf(events, false, "Check the page, whole");

  assert.deepEqual(
    blocks.map((block) => block.kind),
    ["request", "said", "steps", "steered", "ended"],
  );
  const [request, said, steps, steered, ended] = blocks;
  assert.deepEqual(
    [request.text, request.origin],
    ["Check the page, whole", "app"],
  );
  assert.equal(said.text, "Opening the page.");
  const [reasoning, tool] = steps.steps;
  assert.equal(reasoning.title, "Plan");
  assert.deepEqual(
    [tool.verb, tool.target, tool.event, tool.resultEvent],
    ["Ran", "curl http://localhost", 4, 6],
  );
  assert.deepEqual([tool.result, tool.success], ["<html>", false]);
  assert.equal(steps.finished, events[4].time);
  assert.equal(steered.origin, "app");
  assert.deepEqual([ended.status, ended.remedy], ["done", null]);
  assert.equal(latestSaid(events), events[1]);
  assert.equal(toolSteps(blocks).length, 1);
});

test("a failure ends the timeline with its remedy, and the request falls back to the started event's", () => {
  const failed = event(2, "failed", "No model.", {
    code: "model-not-available",
    remedy: "Pick another.",
  });

  const [request, ended] = blocksOf([events[0], failed], false);

  assert.equal(request.text, events[0].data.request);
  assert.deepEqual([ended.status, ended.remedy], ["failed", "Pick another."]);
});

test("a tool call reads whole from its call to its result, the result found by its call's id", async (t) => {
  const asked = [];
  t.mock.method(app, "callServerTool", async ({ arguments: args }) => {
    asked.push(args);
    return {
      structuredContent: {
        check: {},
        state: "done",
        process_log: null,
        events: [
          event(4, "tool", "bash", {
            tool_call_id: "call-1",
            phase: "call",
            arguments: { command: "curl" },
          }),
          event(5, "tool", "other", { tool_call_id: "call-2", phase: "call" }),
          event(6, "tool", "<html>", {
            tool_call_id: "call-1",
            phase: "result",
          }),
        ],
      },
    };
  });

  const full = await readToolCall(ref, 4, 6);

  assert.deepEqual(asked, [
    { ...ref, after_event: 3, before_event: 7, truncate: false },
  ]);
  assert.deepEqual(full.call?.data.arguments, { command: "curl" });
  assert.equal(full.result?.id, 6);
});

test("the cut marker is told from text that only mentions one", () => {
  assert.equal(
    isCut(
      `${"x".repeat(500)}...[cut at 500 of 3,319 chars; full: line 64 of events.jsonl]`,
    ),
    true,
  );
  assert.equal(isCut("Opening the page."), false);
  assert.equal(
    isCut(
      "...[cut at 500 of 3,319 chars; full: line 64 of events.jsonl] is the marker.",
    ),
    false,
  );
});

test("one event reads whole by its id", async (t) => {
  const asked = [];
  t.mock.method(app, "callServerTool", async ({ arguments: args }) => {
    asked.push(args);
    return {
      structuredContent: {
        check: {},
        state: "done",
        process_log: null,
        events: [event(2, "progress", "Whole.")],
      },
    };
  });

  const whole = await readEvent(ref, 2);

  assert.deepEqual(asked, [
    { ...ref, after_event: 1, before_event: 3, truncate: false },
  ]);
  assert.equal(whole?.text, "Whole.");
});
