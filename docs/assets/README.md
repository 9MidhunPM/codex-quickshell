# Screenshot assets

`home.png`, `usage.png`, and `agents.png` are real captures of the rendered
Quickshell interface, rather than concept images or mockups. The preview uses
synthetic demo data with transport disabled: no connection to a Codex daemon or
live account is made to produce these images.

The displayed allowances, credits, sessions, models, and workspaces are examples.
They do not document a real account or imply that every installation has those
values. The images capture only the application interface, with no personal
desktop content.

From the repository root, regenerate all three images with:

```sh
python3 scripts/capture_screenshots.py
```

The script renders the actual dashboard component using its own explicit demo
fixture, at twice the display resolution. Its temporary profile has telemetry
and IPC disabled, and PNGs are checked for embedded text or EXIF metadata.
Inspect regenerated images before publishing them, and never
replace these assets with captures of a live account.
