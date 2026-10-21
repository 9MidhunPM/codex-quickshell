# Security policy

Report vulnerabilities privately through this repository's GitHub security
advisories. Do not include live tokens, account identifiers, prompts, payment
details, or unredacted daemon responses in public issues.

## Boundary

This is a local Linux desktop module, running as the logged-in user. It protects
against accidental data publication, unsafe commands from metadata, and other
local users connecting to the status socket. It cannot isolate the account from
malicious applications already running with the same UID, a compromised Codex
binary/daemon, a modified checkout, or the system administrator.

- The bridge uses an already-running daemon and validates the ownership and
  permissions of its control socket. It never starts a daemon or logs in.
- The RPC interface exposes a fixed metadata-only allowlist. Thread reads use
  `includeTurns: false`. No prompt, completion, tool execution, thread mutation,
  credit purchase, payment, or billing API is implemented.
- Account identity is hashed in memory only to invalidate data after account
  switches. Account identity fields, email, tokens, raw responses, prompts and
  turns are excluded from UI snapshots; the `cwd` field becomes its basename.
- Project basenames, agent nicknames, model names, session UUIDs, state, plan,
  allowances and credits are still sensitive metadata. The UI displays them
  locally. User-assigned metadata labels can themselves contain sensitive text;
  the field allowlist is not a semantic secret scrubber. Avoid screen sharing or
  publishing a live screenshot unintentionally.
- The runtime directory is user-owned and private; the bridge socket is `0600`
  and checks Linux peer credentials. It does not listen on a TCP port.
- Frames, UI commands, strings, page sizes, total thread counts, and per-client
  queues are bounded. Malformed responses produce safe failure states.
- External actions use literal argument vectors, fixed official dashboard URLs,
  and fresh known UUID resume targets. No shell is invoked. `--disable-actions`
  blocks application launches at the backend boundary.
- The installer creates only new owned files, records hashes in a private
  manifest, refuses foreign paths/symlinks, and verifies ownership on removal.
  Custom test roots never control the real user service manager.

Codex's own authenticated daemon may contact its service for the metadata reads.
This module does not send model requests or card operations. Opening a Billing
page is browser navigation only; actions performed manually on that website are
outside this module.

## Publication controls

Only synthetic fixtures belong in tests and public images. Never add `.env`,
saved authentication, daemon state, rollout files, databases, private screenshots,
or personal dotfiles. The publication guard checks tracked files and all reachable
Git history; an independent secret scanner should also be used before release.
Scanners reduce risk and cannot establish that arbitrary files contain no private
information. Review new assets manually and keep additional deny lists outside
the repository.

Scope security review across the Python bridge, QML parser/rendering boundary,
installer, examples, packaging and CI. Treat daemon values as untrusted input.
Preserve the same-user boundary and no automatic external-action behavior when
contributing. Supported security fixes target the latest release on `main`.
