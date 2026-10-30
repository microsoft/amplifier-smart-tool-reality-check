import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate } from "node:timers/promises";

import { app } from "../src/lib/host.ts";
import { select, snapshot } from "../src/lib/store.ts";

test("the first poll refreshes detail when activity sees completion after detail was read", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const activity = Promise.withResolvers();
  const ref = { checks_directory: "/project/checks", check_id: "check" };
  const running = {
    check_id: ref.check_id,
    request: "Check the page",
    ended_at: null,
  };
  const done = { ...running, ended_at: "2026-10-27T00:00:00Z" };
  let detailReads = 0;
  let activityReads = 0;
  t.mock.method(app, "callServerTool", async ({ name }) => {
    if (name === "read_check") {
      detailReads += 1;
      return {
        structuredContent: {
          check: detailReads === 1 ? running : done,
          state: detailReads === 1 ? "running" : "done",
          project: { root: "/project", checks_directory: ref.checks_directory },
          report: detailReads === 1 ? null : "# Report\nDone.",
          evidence: [],
        },
      };
    }
    assert.equal(name, "read_check_activity");
    activityReads += 1;
    if (activityReads === 1) {
      await activity.promise;
    }
    return {
      structuredContent: {
        check: done,
        state: "done",
        events: [],
        process_log: null,
      },
    };
  });

  select(ref);
  await setImmediate();
  assert.equal(detailReads, 1);
  activity.resolve();
  await setImmediate();

  assert.equal(detailReads, 2);
  assert.equal(activityReads, 2);
  t.mock.timers.tick(10_000);
  await setImmediate();
  assert.equal(detailReads, 2);
  assert.equal(activityReads, 2);
});

test("activity is polled after the last event read, and read from the start when that event is gone", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const ref = { checks_directory: "/project/checks", check_id: "polled" };
  const record = {
    check_id: ref.check_id,
    request: "Check it",
    ended_at: null,
  };
  const event = (id, kind) => ({
    id,
    check_id: ref.check_id,
    time: "2026-10-27T00:00:00Z",
    kind,
    text: "",
    data: {},
  });
  const reads = [];
  t.mock.method(app, "callServerTool", async ({ name, arguments: args }) => {
    if (name === "read_check") {
      return {
        structuredContent: {
          check: record,
          state: "running",
          project: { root: "/project", checks_directory: ref.checks_directory },
          report: null,
          evidence: [],
        },
      };
    }
    reads.push(args.after_event);
    if (reads.length === 2) {
      return {
        isError: true,
        content: [{ type: "text", text: "Check polled has no event 3." }],
        structuredContent: { code: "event-not-found" },
      };
    }
    return {
      structuredContent: {
        check: record,
        state: reads.length === 1 ? "running" : "done",
        events:
          reads.length === 1
            ? [event(1, "started"), event(3, "progress")]
            : reads.length === 3
              ? [event(1, "started")]
              : [],
        process_log: null,
      },
    };
  });

  select(ref);
  await setImmediate();
  t.mock.timers.tick(1_000);
  await setImmediate();
  await setImmediate();

  // Once more after it stops running, after the one event the log now has.
  assert.deepEqual(reads, [undefined, 3, undefined, 1]);
});

test("a cut message or reasoning is read whole once and shown whole, and a whole one is never read again", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const ref = { checks_directory: "/project/checks", check_id: "cut" };
  const record = {
    check_id: ref.check_id,
    request: "Check it",
    ended_at: null,
  };
  const marker = (line) =>
    `...[cut at 500 of 1,200 chars; full: line ${line} of events.jsonl]`;
  const event = (id, kind, text) => ({
    id,
    check_id: ref.check_id,
    time: "2026-10-27T00:00:00Z",
    kind,
    text,
    data: {},
  });
  const short = [
    event(1, "started", "Started."),
    event(2, "progress", `${"m".repeat(500)}${marker(2)}`),
    event(3, "reasoning", `${"r".repeat(500)}${marker(3)}`),
    event(4, "progress", "Short."),
  ];
  const whole = {
    2: event(2, "progress", "m".repeat(1200)),
    3: event(3, "reasoning", "r".repeat(1200)),
  };
  const polls = [];
  const wholeReads = [];
  t.mock.method(app, "callServerTool", async ({ name, arguments: args }) => {
    if (name === "read_check") {
      return {
        structuredContent: {
          check: record,
          state: "running",
          project: { root: "/project", checks_directory: ref.checks_directory },
          report: null,
          evidence: [],
        },
      };
    }
    if (args.truncate === false) {
      wholeReads.push([args.after_event, args.before_event]);
      return {
        structuredContent: {
          check: record,
          state: "running",
          process_log: null,
          events: [whole[args.after_event + 1]],
        },
      };
    }
    polls.push(args.after_event);
    return {
      structuredContent: {
        check: record,
        state: "running",
        process_log: null,
        events: polls.length === 1 ? short : [],
      },
    };
  });

  select(ref);
  for (let poll = 0; poll < 3; poll += 1) {
    await setImmediate();
    await setImmediate();
    t.mock.timers.tick(1_000);
  }
  await setImmediate();

  assert.deepEqual(polls.slice(0, 3), [undefined, 4, 4]);
  assert.deepEqual(wholeReads, [
    [1, 3],
    [2, 4],
  ]);
  const key = `${ref.checks_directory}\n${ref.check_id}`;
  assert.deepEqual(
    snapshot().activities[key].events.map((each) => each.text),
    ["Started.", "m".repeat(1200), "r".repeat(1200), "Short."],
  );
});
