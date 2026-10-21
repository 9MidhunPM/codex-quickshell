# Contributing

Use Python 3.11+, Node, Quickshell, and Qt 6's declarative tooling. Run `make check`
before proposing changes. `QT_BIN_DIR` selects a nonstandard Qt 6 tools directory;
`QML_IMPORT_PATH` adds import roots to the lint check. Do not accidentally use the
Qt 5 tools that some distributions put first on `PATH`.

Python tests use synthetic metadata and temporary directories. Socket tests may
be skipped by a sandbox; run those in a Linux environment that permits Unix
sockets before release. Qt tests run offscreen and exercise layout, navigation,
formatting and state. They do not replace a real `qs` run: Quickshell's embedded
core APIs cannot be loaded into a plain `qmltestrunner` process.

Check the runnable examples and preview in a separate Quickshell instance. Use
an explicit `qs -p` path and unique IPC target; do not restart your existing shell
or production bridge for a fixture test. Synthetic preview states are selected
with `CODEX_QUICKSHELL_PREVIEW_STATE=fresh|stale|partial|offline`.

## Privacy before publication

```sh
python3 scripts/check_privacy.py --history
gitleaks dir --redact .
gitleaks git --redact --log-opts=--all .
```

The guard scans tracked working files plus every reachable commit tree,
including deleted blobs and commit metadata. To add personal strings locally,
use `--deny-file /path/outside/checkout/private-deny-list`. Never commit that
file. Reports identify rules and locations without printing the matched values.
Keep scanner reports outside the checkout too. Manually review images and new
file types; neither scanner guarantees that arbitrary private information is
absent. Commit public GitHub noreply identity rather than private email addresses.

Use focused commits that explain behavior and validation. Do not add generated
personal configuration, live daemon snapshots, screenshots of account data,
tokens, or captured conversations. See [SECURITY.md](SECURITY.md) for the trust
boundary and private vulnerability reporting.
