# Expected finding

Signing in to Unified over its LAN URL ends at a page that does not load.

- At https://home-server-2:8941/login, a correct username and password get `303 See Other` with `Location: https://127.0.0.1:8941/` (or `https://127.0.0.1:8941<next path>` when the login URL has `?next=`), instead of a path on https://home-server-2:8941.
- A browser on any other machine follows it to its own 127.0.0.1 and fails with `ERR_CONNECTION_REFUSED`. `curl -L` fails with `Failed to connect to 127.0.0.1 port 8941`.
- The session cookie is set before the redirect, so opening https://home-server-2:8941/ by hand afterward shows the app signed in. Pages, the API, and live updates over the WebSocket all work.
- A wrong password redirects correctly, back to `/login?error=1` on the address used.
- On the server itself, or through an SSH port forward, sign-in at https://127.0.0.1:8941 lands back on the same address and works. Sign-in at https://localhost:8941 lands on 127.0.0.1 without the session, back at the login page.

The key evidence is a `POST /login` answered `303`, followed by a failed request to https://127.0.0.1:8941/, in a browser's network log, or the `Location` header from curl.

Cause: `patches/sign-in-landing.patch` changes `post_login` in `amplifier_web/auth.py` to redirect to `landing_url()`, an absolute URL on 127.0.0.1 with the server's port and the request's scheme, instead of the relative `next` path. On the server it is in `~/.local/share/uv/tools/amplifier-unified/lib/python3.13/site-packages/amplifier_web/auth.py`. The server's logs do not record the redirect; the journal shows only the PAM lines of each sign-in.

## Setup

home-server-2 runs Unified as a systemd user service (`amplifier-unified service status`), set up as `docs/DEPLOYMENT.md` describes: public origin `https://home-server-2:8941`, `setup-tls` with Unified's local CA, bind `home-server-2` and `127.0.0.1`.

The update is two installs, both done when the server's image is built, before the check starts:

1. Unified's latest release, then the setup above, with automatic update checks and installs turned off in Settings, Updates.
2. `uv tool install --force git+https://github.com/microsoft/amplifier-unified@main`, answered with the current main plus `patches/sign-in-landing.patch`. It replaces the installed code and keeps the config, certificates, settings, and service.

The update does not use Unified's own updater, the server has no data from before the update, and the version number may not change. The twin has the CA in `~/home-server-2-ca.crt`, the password in `~/.config/home-server-2-password`, and `ssh home-server-2` with a key. The twin reaches the server through the environment's HTTP proxy, which passes its TLS through unchanged. Containers on the twin's Docker resolve `home-server-2` through the LAN's router.

Unified is connected to OpenAI, as its owner did in Settings, AI connections: the connection `openai` with the default model `gpt-6.1-sol` and the balanced model rules that first setup turns on, its key in `~/.amplifier/keys.env` and the rest in `~/.amplifier/settings.yaml`. The model rules may choose another OpenAI model for some work. A new chat gets a real reply from the model, which is part of a healthy server.

The twin is the owner's machine, so it already trusts the server's CA, as DEPLOYMENT.md's "Trust the CA on each client" has it:

- The system store (`/usr/local/share/ca-certificates/home-server-2.crt`), and the bundle the environment's `SSL_CERT_FILE`, `CURL_CA_BUNDLE`, `REQUESTS_CA_BUNDLE`, and `NODE_EXTRA_CA_CERTS` name, so plain `curl`, Python, and Node verify the server.
- The user's NSS database, `~/.pki/nssdb`, trusted for SSL. Chromium and Firefox read it, and so does Playwright's bundled Chromium: it opens https://home-server-2:8941 with no certificate error and no extra options.

A tool that reads none of these, such as a browser with its own profile directory or a program with its own bundle, needs the CA from `~/home-server-2-ca.crt` given to it; that is trusting it properly, not turning off checks.

## The server after the check

The fingerprints in the task's materials tell whether the server changed. The list of changed files is long and is mostly Unified's own data. Unified changes its own data under `~/.amplifier-unified` whenever it is used: its databases (`*.sqlite3*`), `diagnostics/`, and `foundation/cache/`, where it fetches bundles the first time the app is opened. These are not changes by the agent. A change to the installed tool, `~/.config/systemd/user`, `~/.amplifier-unified/config`, or the AI connection in `~/.amplifier/settings.yaml` and `~/.amplifier/keys.env` shows as a different digest in the fingerprints, and a restart of the service as a later start time.

## Not defects of the update

- A report that the twin does not trust the server's certificate is a false finding. Only a tool that reads none of the twin's stores fails to verify it, and the fix is to give that tool the CA.
- With certificate checks turned off, the browser still refuses to fetch the service worker script, logging `An SSL certificate error occurred when fetching the script.`, and the app registers no service worker. Browsers do not let a page override certificate checks for service worker scripts.
- Automatic update checks are off, so Updates shows no recent check.
- Settings shows "Test runner not ready": no managed Linux test host is set up, which is the owner's choice, not a failure.
- The pages and Updates name the app "Amplifier"; that is Unified's own naming.
- Every sign-in logs `PAM unable to dlopen(pam_lastlog.so)` and `pam_group(login:setcred): unable to set the group membership`, from Ubuntu 24.04's PAM configuration.
- `ssh home-server-2 amplifier-unified ...` does not find the command, since a non-interactive SSH shell does not add `~/.local/bin` to `PATH`; `bash -lc` does.
- The installed commit differs from the commit of GitHub's main, since main is rebuilt with the patch for this environment.
