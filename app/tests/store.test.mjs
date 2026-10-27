import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate } from "node:timers/promises";

import { app } from "../src/lib/host.ts";
import { select } from "../src/lib/store.ts";

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
        entries: [],
        cursor: 0,
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
