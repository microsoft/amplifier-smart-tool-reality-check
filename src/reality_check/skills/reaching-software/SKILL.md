---
name: reaching-software
description: >-
  Reach software where it runs when checking it as a user: a local process, a deployed site, a
  Digital Twin Universe on this or another machine, or an app that is not running yet. Use when the
  app, the agent, and the user's view may be on different machines, or a URL does not answer.
---

A check has three places, and each can be on a different machine: where you run, where the
software runs, and where the user's view is (a browser, a screen, a terminal, a device). Find out
which is which before you open anything.

## Find where it runs

- A URL in the request: open it from where the user's view will be, not only from here.
- A port on this machine: `ss -ltnp` (Linux), `lsof -iTCP -sTCP:LISTEN` (macOS), or
  `netstat -ano` (Windows) shows what listens and on which address.
- A universe: `digital-twin-universe list` and `status --id <id>` give its state and the URLs
  the host can open.
- A repository and no running app: launch it in a new universe from a profile
  (`digital-twin-universe create-profile`, or `launch` with an existing one), as if deployed.
  Destroy it after the check unless asked to keep it.

## localhost is relative

`localhost` means the machine or container the request runs in.

- From inside a container or universe, the host's `localhost` is not reachable. Use the host's
  LAN address or name, or `host.docker.internal` where Docker provides it.
- From a browser on another machine, use the serving machine's LAN IP, hostname, or Tailscale
  name, such as `http://home-server-2:3000`. A server bound to `127.0.0.1` answers only locally;
  say so in the report rather than changing how it is started without being asked.
- Check reachability first with `curl -sS -o /dev/null -w '%{http_code} %{time_total}\n' <url>`
  from the place the user's view is.

## Other machines

- SSH: run commands there with `ssh <host> '<command>'`, and forward a port with
  `ssh -N -L 3000:localhost:3000 <host>` so `http://localhost:3000` here reaches the app there.
  Use only keys and hosts already configured; never create or change them.
- Tailscale: `tailscale status` lists the machines on the tailnet and their names; a tailnet name
  works like a LAN name.
- A universe on another machine: run `digital-twin-universe` there over SSH. Its URLs are
  `localhost` on that machine, so reach them through a port forward or that machine's name.

## When it cannot be reached

Name what you tried, from where, and what answered: the URL, the command, and its output. A
check that could not reach the software reports each item as not checked, never as a pass.
