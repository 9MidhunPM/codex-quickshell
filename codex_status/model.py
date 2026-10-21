"""Small, credential-free projections of Codex app-server responses.

Only the explicitly selected display fields leave this module. Runtime status
comes from the connected daemon, never from a persisted turn or an old preview.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from uuid import UUID


MAX_ANCESTRY = 32
MAX_BUCKETS = 128
MAX_CREDIT_BALANCE = 256
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _text(value: object, limit: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(_CONTROL_CHARS.sub(" ", value).split()).strip()
    return value[:limit] or None


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value):
            return None
    except (OverflowError, TypeError):
        return None
    return value


def _timestamp(value: object) -> int | float | None:
    value = _number(value)
    return value if value is not None and value >= 0 else None


def _duration(value: object) -> int | None:
    value = _number(value)
    if value is None or value <= 0 or value != int(value):
        return None
    return int(value)


def _window(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    used = _number(value.get("usedPercent"))
    if used is None:
        return None
    duration = _duration(value.get("windowDurationMins"))
    if duration == 10080:
        label = "Weekly"
    elif duration is None:
        label = "Usage window"
    elif duration % 60 == 0:
        label = f"{duration // 60}-hour"
    else:
        label = f"{duration}-minute"
    return {
        "label": label,
        "remainingPercent": max(0, min(100, 100 - used)),
        "resetsAt": _timestamp(value.get("resetsAt")),
        "durationMinutes": duration,
    }


def _credits(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    has_credits = value.get("hasCredits")
    unlimited = value.get("unlimited")
    # These required boolean fields distinguish zero from unavailable.
    if not isinstance(has_credits, bool) or not isinstance(unlimited, bool):
        return None
    # A numeric prefix is a different amount: never truncate and then let the
    # frontend interpret it. One extra character detects the shared display cap.
    balance = _text(value.get("balance"), MAX_CREDIT_BALANCE + 1)
    truncated = balance is not None and len(balance) > MAX_CREDIT_BALANCE
    result = {
        "balance": None if truncated else balance,
        "hasCredits": has_credits,
        "unlimited": unlimited,
    }
    if truncated:
        result["balanceTruncated"] = True
    return result


def unavailable_usage() -> dict:
    return {"state": "unavailable", "observedAt": None, "plan": None, "buckets": []}


def normalize_usage(response: dict, plan: str | None, observed_at: float) -> dict:
    """Normalize a full rate-limit snapshot, retaining provider units as text."""
    result = unavailable_usage()
    result["plan"] = _text(plan, 80)
    if not isinstance(response, dict):
        return result
    buckets = []
    by_id = response.get("rateLimitsByLimitId")
    entries = list(by_id.items())[:MAX_BUCKETS] if isinstance(by_id, dict) else []
    # A missing, empty, or unusable multi-bucket map uses the legacy snapshot.
    entries = [(key, value) for key, value in entries if isinstance(value, dict)]
    if not entries and isinstance(response.get("rateLimits"), dict):
        snapshot = response["rateLimits"]
        entries = [(snapshot.get("limitId") or "codex", snapshot)]
    for key, value in entries:
        bucket_id = _text(key, 160)
        if bucket_id is None:
            continue
        windows = [
            window for field in ("primary", "secondary")
            if (window := _window(value.get(field))) is not None
        ]
        credits = _credits(value.get("credits"))
        if not windows and credits is None:
            continue
        buckets.append({
            "id": bucket_id,
            "name": _text(value.get("limitName")) or bucket_id,
            "windows": windows,
            "credits": credits,
        })
    if not buckets and isinstance(by_id, dict) and "rateLimits" in response:
        return normalize_usage({"rateLimits": response["rateLimits"]}, plan, observed_at)
    if buckets:
        result.update(
            state="fresh", observedAt=_timestamp(observed_at), buckets=buckets
        )
    return result


def mark_usage_stale(usage: dict) -> dict:
    """Preserve the last full snapshot and its original observation timestamp."""
    result = deepcopy(usage)
    if result.get("state") in ("fresh", "stale") and result.get("buckets"):
        result["state"] = "stale"
    return result


def _uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except (ValueError, AttributeError):
        return None


def _workspace(value: object) -> str:
    if not isinstance(value, str):
        return ""
    basename = value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return _text(basename, 120) or ""


def _subagent_metadata(source: object) -> tuple[dict, bool]:
    """Read only the typed subagent branch of an app-server SessionSource."""
    if not isinstance(source, dict):
        return {}, False
    subagent = source.get("subAgent")
    if isinstance(subagent, str):
        return {}, subagent in {"review", "compact", "memory_consolidation"}
    if not isinstance(subagent, dict):
        return {}, False
    spawn = subagent.get("thread_spawn")
    if isinstance(spawn, dict):
        return spawn, True
    return {}, _text(subagent.get("other")) is not None


def _task_label(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 4096:
        return None
    if not value.startswith("/root/") or "\\" in value:
        return None
    segments = value[6:].split("/")
    if any(not segment or segment in {".", ".."} for segment in segments):
        return None
    return _text(segments[-1].replace("_", " "))


def _runtime_state(status: object) -> str | None:
    if not isinstance(status, dict):
        return None
    kind = status.get("type")
    if kind == "notLoaded" or not isinstance(kind, str) or not kind:
        return None
    if kind == "active":
        flags = status.get("activeFlags")
        if not isinstance(flags, list):
            return "unavailable"
        if "waitingOnApproval" in flags:
            return "waiting_approval"
        if "waitingOnUserInput" in flags:
            return "waiting_input"
        return "working"
    return {"idle": "idle", "systemError": "error"}.get(kind, "unavailable")


def unavailable_agents() -> dict:
    return {
        "state": "unavailable",
        "observedAt": None,
        "activeCount": None,
        "items": [],
    }


def normalize_agents(threads: list[dict], observed_at: float) -> dict:
    """Project live metadata into a bounded tree, with safe explicit open targets."""
    if not isinstance(threads, list):
        return unavailable_agents()
    nodes: dict[str, dict] = {}
    openable: set[str] = set()
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        thread_id = _uuid(thread.get("id"))
        state = _runtime_state(thread.get("status"))
        if thread_id is None or state is None:
            # A missing or unloaded thread can race a loaded/list response.
            if thread_id is not None:
                nodes.pop(thread_id, None)
                openable.discard(thread_id)
            continue
        parent_id = _uuid(thread.get("parentThreadId"))
        spawn, is_subagent = _subagent_metadata(thread.get("source"))
        fallback_label = "Subagent" if parent_id is not None or is_subagent else "Session"
        nodes[thread_id] = {
            "id": thread_id,
            "parentId": parent_id,
            "title": (
                _text(thread.get("name"))
                or _task_label(spawn.get("agent_path"))
                or _text(thread.get("agentRole"))
                or _text(spawn.get("agent_role"))
                or f"{fallback_label} {thread_id[:8]}"
            ),
            "nickname": (
                _text(thread.get("agentNickname"), 80)
                or _text(spawn.get("agent_nickname"), 80)
            ),
            "workspace": _workspace(thread.get("cwd")),
            # This is only this thread's configured model. Neither the parent
            # nor historical spawn settings establish its current selection.
            "model": _text(thread.get("model"), 100),
            "state": state,
            "openTargetId": None,
            "openLabel": None,
            "depth": 0,
        }
        openable.discard(thread_id)
        if (
            thread.get("canAcceptDirectInput") is True
            and thread.get("ephemeral") is False
        ):
            openable.add(thread_id)

    # Break malformed cyclic ancestry deterministically, without recursion.
    for thread_id in sorted(nodes):
        path: list[str] = []
        seen: dict[str, int] = {}
        cursor = thread_id
        while cursor in nodes:
            if cursor in seen:
                cycle = path[seen[cursor]:]
                nodes[min(cycle)]["parentId"] = None
                break
            if len(path) >= MAX_ANCESTRY:
                # Bound traversals as well as display indentation.
                nodes[cursor]["parentId"] = None
                break
            seen[cursor] = len(path)
            path.append(cursor)
            cursor = nodes[cursor]["parentId"]

    for thread_id, node in nodes.items():
        cursor = thread_id
        for distance in range(MAX_ANCESTRY + 1):
            if cursor not in nodes:
                break
            if node["openTargetId"] is None and cursor in openable:
                node["openTargetId"] = cursor
                node["openLabel"] = (
                    "Open session" if cursor == thread_id else "Open parent session"
                )
            parent = nodes[cursor]["parentId"]
            if parent not in nodes:
                node["depth"] = distance
                break
            cursor = parent

    # Stable preorder keeps parents immediately ahead of their descendants.
    children: dict[str | None, list[str]] = {}
    for thread_id, node in nodes.items():
        parent = node["parentId"] if node["parentId"] in nodes else None
        children.setdefault(parent, []).append(thread_id)
    for siblings in children.values():
        siblings.sort(key=lambda key: (nodes[key]["title"].casefold(), key))
    stack = list(reversed(children.get(None, [])))
    items = []
    while stack:
        thread_id = stack.pop()
        items.append(nodes[thread_id])
        stack.extend(reversed(children.get(thread_id, [])))
    return {
        "state": "fresh",
        "observedAt": _timestamp(observed_at),
        "activeCount": sum(node["state"] == "working" for node in items),
        "items": items,
    }
