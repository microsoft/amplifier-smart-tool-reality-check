# Vision

An agent that builds an app often says the app works, but no one has used it yet.
Tests pass, the agent claims success, yet a real user clicks a button and gets something unexpected.
Reality Check closes the gap between "the agent says it works" and "a user can do what they came to do," and it keeps the cost of knowing that appropriate to the value it brings.

The caller gives it an app and tells it what to validate.
It uses the app as a real user does, records what happens, and gives evidence for each result that comes from what the tool recorded.
It keeps the scripts it writes along the way, so a later run reuses or updates them instead of starting over, and uses a model only for what changed.

**A run is worth the time it takes.**
- A run earns its place by what it covers and catches for the time it costs.
- A change runs only the testing it can affect. A change to the billing page tests billing and that page, not everything. A broader run is there when the caller asks for it.
- A run fits after a large change, not after every small one. The same assertions on each change belong in scripted tests, which are faster and cheaper.

## Example Uses

- "My app is <here>. Check that a new user can sign up and send a message."
- "Here is my repository. Set it up as if it were deployed, and check that the dashboard loads in under three seconds with no console errors."
- "Click through every page and every settings submenu, and fix where spacing, icons, wording, or controls are not consistent with each other or with our design system, such as a styled dropdown that opens a plain browser list, or an arrow icon that touches the border."
- "Check every link on the site, and check that each filter on the transactions page changes the results the way its label says."
- "The app runs on my other machine at `http://home-server-2:3000`. Use my browser on this Mac, where I am already signed in, and check the new export button."
- "Run the baseline from last week against this branch, and tell me what changed that the diff does not explain."

## Ways of working

People build and run apps in many places at once. A developer can write code in Amplifier on a Mac, build on a headless Linux box, run the app in a universe on a second machine, and open it in a browser on a third. 
Reality Check must work in all of these, not only when everything is on one machine. 
This is what we have to consider:

- **Where the agent runs**: the caller's harness (Copilot, Codex, etc) or invoked through the lib or CLI directly, on the caller's machine.
- **Where the software being tested runs**:
  - a local process, such as a simple HTTP server
  - a site that is already deployed
  - a [Digital Twin Universe](https://github.com/microsoft/amplifier-smart-tool-digital-twin-universe) on this machine or on another machine on the network
  - a native app on a Mac, Windows, or mobile
  - an app that is not running yet, which Reality Check sets up in a new universe
- **Where the user's view is**:
  - a browser and a screen inside a universe
  - the caller's own browser, which is already signed in
  - computer use on the host or on another machine
  - a Terminal UI
  - a device or simulator for a mobile app

Reality Check does not hard-code one path. It ships a few things the agent can reach for: Digital Twin Universe, a screen and browser inside a universe, and so forth. 
It also gives guidance on the other paths: SSH and Tailscale to reach other machines, LAN URLs instead of `localhost`, attaching to a browser that is already open, and testers for native apps. 
The agent chooses from what it finds in the caller's environment and what is appropriate for the task at hand.

A universe that Reality Check made is destroyed after the run, or kept for more runs if the caller asks. Reality Check never destroys universes or other infrastructure it did not create.

## Working with Reality Check

**It does not work in a degraded state without telling you.**
Reality Check first investigates the task it was given, including the request and any context that came with it.
When that investigation shows that something seems off, Reality Check stops and asks before it continues.
For example: computer use is not enabled, a tester for the app's platform is not installed, a browser cannot be reached, or the app has no realistic data.
You or your agent can then say "I have that", fix it, or tell it to continue anyway.
When nothing is off, it does not ask. It starts the work.

**Before large work, it can show what it will do.**
When you ask for it, a long or exhaustive run, such as "every page and every settings submenu", starts with a short view of what it will test and how it will reach the app.
When you do not, and nothing seems off, it starts the work.
The points that need your attention come first. The rest is only there to keep you informed.
When the host can show it, this view is visual, not a wall of text.

**It does the tedious parts for you.**
A password or access code that Reality Check made, it enters itself.
A sign-in that belongs to you, it gives to you: it opens the sign-in page and waits, or it uses a browser where you are already signed in.

**It does not forget half the list.**
Every item you asked about is covered, even in a long run. At the end, you see what it tested and what it did not.

**It looks past "does the button work".**
It finds problems that the code does not show, such as a page that polls every second for a 28 MB response, or a page that becomes slow with real data or a slow network.
When a test would be stronger with realistic data or a throttled network, it suggests that.

**It shows, it does not only tell.**
Each result comes with what Reality Check saw: screenshots, requests, console messages, and timings.
A result that it could not record is marked as such. It is never reported as a pass.

**It says when another tool fits better.**
Reality Check is not a general testing expert.
When it is asked to write, fix, or run a project's own tests, or to be a release gate or CI step, it says so and gives the request back to the caller instead of starting a run. Scripted tests are faster and cheaper there.
A broad request such as "validate my app" is still in scope. It takes longer, and Reality Check says so.

**It follows your team's standards.**
A team records its standards in the project, such as its design system.
Every run follows them.

**You can see every run in one place.**
`reality-check app` shows every run on this machine, past and active, with its report, evidence, and what its agent did.
In a host that shows MCP Apps, the same view opens in the host.
The app only shows past or active runs. Your agent starts, steers, and stops them through the tool.

## Goals

- There is one main capability that tests an app and returns a verdict for each step, with the evidence for it.
- The request is plain language. A Markdown file is ordinary context, not a special format.
- On request, the plan is shown before the work starts, in a clear form, and uses the host's rendering (such as an MCP App) when the host has it.
- Each failure names the step, the action, and what the record shows at that time. For example: "Step 2 (click Send): POST /api/chat returned 500, TypeError in console."
- Two ways to run:
  - One shot: test a list of steps and return a report.
  - Interactive: start the app, ask for tests one at a time, get evidence for each, then stop the app.
- A later run can be given earlier runs' directories, and the request says how to use them, such as comparing against them.
- Many runs can happen at the same time, from many sessions, without interference. For example, ten agents each fix an issue and test it before they open a PR.
- The evidence is both a human readable dashboard, but also a structured report for agents with references to images and other pieces of evidence.
- A user finds any earlier run without knowing its ID or folder, and an agent does the same through the library.
- A capable agent can use the parts of a run on its own, such as seeing and using the app or reading what was recorded, without asking Reality Check's own agent.

## Non-Goals

- Building or running a provisioning engine. The Digital Twin Universe library does that.
- Writing, maintaining, or running a project's own tests, such as unit tests, end-to-end suites, or CI config.
- Load testing at scale, or security testing.
- Being specific to one product or one harness. Each app is a user of the tool, not a part of it.
- Managing the caller's machines, SSH keys, or network.
- Starting or steering runs from the app.
- Being a deterministic release gate or a CI step. Scripted tests are faster and cheaper there.

## Later

These are out of scope for now. The design must not block them.

- Simulated services, such as mail, chat, and documents.
- Unattended testing of a deployed app behind real sign-in, such as Easy Auth, where no one has signed in before.

## Principles

- Start with keeping harnesses (Amplifier Agent, Copilot, Codex, etc.) "vanilla" and add features (like MCPs, skills, context, workflows, etc.) only as the need arrives. Agents are very capable out of the box, we should let them work.
- Give guidance, not one fixed path. Reality Check suggests ways to reach and see an app; the agent decides with what it has.
- Evidence over claims. A verdict stands on what was recorded, not on what the agent says.
- Judge consistency, not taste. Reality Check fixes what is inconsistent or unfinished, and follows the project's own design system when there is one.
- As little model as possible. Anything that can run without a model does, including steps such as clicking through a flow, filling forms, and reading requests, and a flow it already tested on an earlier run. Reality Check's agent writes scripts for this work instead of exploring one step at a time. It spends model time only where judgment adds value: what it sees, what to explore next, and what a script did not expect.
- Cost is visible. Each run reports how long it took and what it cost.
- The library is the tool. The CLI and any other surface are thin wrappers over it.
- Deterministic capabilities run with no model provider configured, and never refuse to load without one.
- The intelligence is behind an interface, so another implementation is a new module rather than a rewrite.
- The tool works on Windows, macOS, and Linux seamlessly.
