"""Behavior tests for the collector's deliberately small display projection."""

from copy import deepcopy
import json
import unittest

from codex_status.model import (
    MAX_ANCESTRY,
    mark_usage_stale,
    normalize_agents,
    normalize_usage,
    unavailable_agents,
    unavailable_usage,
)


def thread_id(number):
    return f"00000000-0000-4000-8000-{number:012d}"


def thread(number, **changes):
    result = {
        "id": thread_id(number),
        "status": {"type": "active", "activeFlags": []},
        "name": f"Agent {number}",
        "cwd": "/private/user/repository",
        "model": "configured-model",
        "ephemeral": False,
        "canAcceptDirectInput": True,
    }
    result.update(changes)
    return result


def usage_snapshot(**changes):
    result = {
        "limitId": "codex",
        "primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 1234},
    }
    result.update(changes)
    return {"rateLimits": result}


class UsageProjectionTests(unittest.TestCase):
    def test_actual_window_duration_determines_weekly_label(self):
        data = normalize_usage(usage_snapshot(secondary={
            "usedPercent": 60, "windowDurationMins": 10080, "resetsAt": 4567
        }), "plus", 100)
        self.assertEqual(data["state"], "fresh")
        self.assertEqual(data["observedAt"], 100)
        self.assertEqual(data["plan"], "plus")
        self.assertEqual(data["buckets"][0]["windows"], [
            {"label": "5-hour", "remainingPercent": 75, "resetsAt": 1234,
             "durationMinutes": 300},
            {"label": "Weekly", "remainingPercent": 40, "resetsAt": 4567,
             "durationMinutes": 10080},
        ])
        data = normalize_usage(usage_snapshot(secondary={
            "usedPercent": 5, "windowDurationMins": 60
        }), None, 100)
        self.assertEqual(data["buckets"][0]["windows"][1]["label"], "1-hour")

    def test_multiple_buckets_replace_legacy_view_without_double_count(self):
        response = usage_snapshot()
        response["rateLimitsByLimitId"] = {
            "specific": {"limitId": "different", "limitName": "Specific model",
                         "primary": {"usedPercent": 20}},
            "other": {"primary": {"usedPercent": 40}},
        }
        data = normalize_usage(response, None, 100)
        self.assertEqual([b["id"] for b in data["buckets"]], ["specific", "other"])
        self.assertEqual(data["buckets"][0]["name"], "Specific model")
        self.assertEqual(data["buckets"][0]["windows"][0]["label"], "Usage window")

    def test_missing_or_unusable_map_falls_back_to_single_bucket(self):
        for value in (None, {}, [], {"bad": None}, {"bad": {}}):
            response = usage_snapshot()
            response["rateLimitsByLimitId"] = value
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_usage(response, None, 100)["buckets"][0]["id"],
                    "codex",
                )

    def test_remaining_percent_clamps_without_inventing_invalid_values(self):
        for used, remaining in ((-10, 100), (150, 0), (2.5, 97.5)):
            data = normalize_usage(usage_snapshot(primary={"usedPercent": used}), None, 100)
            self.assertEqual(data["buckets"][0]["windows"][0]["remainingPercent"], remaining)
        for used in (True, False, "10", None, float("nan"), float("inf"), 10**1000):
            with self.subTest(used=str(used)[:30]):
                data = normalize_usage(usage_snapshot(primary={"usedPercent": used}), None, 100)
                self.assertEqual(data["state"], "unavailable")
                self.assertEqual(data["buckets"], [])

    def test_invalid_duration_and_reset_remain_unknown(self):
        for duration in (True, "10080", -1, 0, float("nan"), 2.5):
            data = normalize_usage(usage_snapshot(primary={
                "usedPercent": 15, "windowDurationMins": duration, "resetsAt": True
            }), None, 100)
            window = data["buckets"][0]["windows"][0]
            self.assertEqual(window["label"], "Usage window")
            self.assertIsNone(window["durationMinutes"])
            self.assertIsNone(window["resetsAt"])

    def test_zero_unlimited_and_unavailable_credits_are_distinct(self):
        for credits in (
            {"balance": "0", "hasCredits": False, "unlimited": False},
            {"balance": None, "hasCredits": True, "unlimited": True},
            {"balance": "12.50", "hasCredits": True, "unlimited": False},
        ):
            data = normalize_usage(usage_snapshot(credits=credits), None, 100)
            self.assertEqual(data["buckets"][0]["credits"], credits)
        for credits in (None, {}, {"balance": "0", "hasCredits": 0, "unlimited": False}):
            data = normalize_usage(usage_snapshot(credits=credits), None, 100)
            self.assertIsNone(data["buckets"][0]["credits"])
        data = normalize_usage(usage_snapshot(primary=None, credits={
            "balance": "0", "hasCredits": False, "unlimited": False
        }), None, 100)
        self.assertEqual(data["state"], "fresh")
        self.assertEqual(data["buckets"][0]["windows"], [])

    def test_long_nonzero_credit_balances_keep_the_entire_amount(self):
        for balance in (
            "0." + "0" * 78 + "1",
            "1" + "0" * 79 + "e-80",
            "1e-" + "0" * 78 + "1",
            "0." + "0" * 253 + "1",
        ):
            with self.subTest(length=len(balance)):
                credits = {
                    "balance": balance, "hasCredits": True, "unlimited": False,
                }
                data = normalize_usage(usage_snapshot(credits=credits), None, 100)
                self.assertEqual(data["buckets"][0]["credits"], credits)

    def test_oversized_credit_balance_has_no_numeric_prefix(self):
        for balance in ("0." + "0" * 254 + "1", "9" * 257, "1e-" + "0" * 253 + "1"):
            with self.subTest(length=len(balance)):
                data = normalize_usage(usage_snapshot(credits={
                    "balance": balance, "hasCredits": True, "unlimited": False,
                }), None, 100)
                credits = data["buckets"][0]["credits"]
                self.assertEqual(credits, {
                    "balance": None, "hasCredits": True, "unlimited": False,
                    "balanceTruncated": True,
                })
                self.assertNotIn(balance, json.dumps(data))

    def test_credit_balance_cap_applies_after_safe_text_normalization(self):
        balance = "0." + "0" * 253 + "1"
        data = normalize_usage(usage_snapshot(credits={
            "balance": "\n " + balance + "\x1b\t",
            "hasCredits": True, "unlimited": False,
            "balanceTruncated": True,
        }), None, 100)
        self.assertEqual(data["buckets"][0]["credits"], {
            "balance": balance, "hasCredits": True, "unlimited": False,
        })

    def test_null_windows_do_not_become_fake_weekly_allowance(self):
        data = normalize_usage(usage_snapshot(secondary=None), None, 100)
        self.assertEqual(len(data["buckets"][0]["windows"]), 1)
        self.assertEqual(normalize_usage({}, None, 100), unavailable_usage())

    def test_staleness_keeps_observation_and_does_not_mutate_snapshot(self):
        fresh = normalize_usage(usage_snapshot(), "plus", 100)
        stale = mark_usage_stale(fresh)
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["observedAt"], 100)
        self.assertEqual(fresh["state"], "fresh")
        stale["buckets"].clear()
        self.assertEqual(len(fresh["buckets"]), 1)
        self.assertEqual(mark_usage_stale(unavailable_usage()), unavailable_usage())

    def test_projection_drops_credentials_email_and_unrelated_fields(self):
        response = usage_snapshot()
        response.update(email="PRIVATE_EMAIL", accessToken="PRIVATE_TOKEN",
                        accountId="PRIVATE_ID", rateLimitUpsell={"text": "PRIVATE_TEXT"})
        result = normalize_usage(response, "plus", 100)
        serialized = json.dumps(result)
        self.assertNotIn("PRIVATE_", serialized)
        self.assertEqual(set(result), {"state", "observedAt", "plan", "buckets"})
        json.dumps(result, allow_nan=False)


class AgentProjectionTests(unittest.TestCase):
    def test_runtime_states_and_active_count_exclude_waiting_agents(self):
        rows = [
            thread(1),
            thread(2, status={"type": "active", "activeFlags": ["waitingOnApproval"]}),
            thread(3, status={"type": "active", "activeFlags": ["waitingOnUserInput"]}),
            thread(4, status={"type": "idle"}),
            thread(5, status={"type": "systemError"}),
            thread(6, status={"type": "future-status"}),
        ]
        result = normalize_agents(rows, 100)
        self.assertEqual(result["activeCount"], 1)
        self.assertEqual([a["state"] for a in result["items"]], [
            "working", "waiting_approval", "waiting_input", "idle", "error", "unavailable"
        ])
        self.assertEqual(result["observedAt"], 100)

    def test_parent_tree_and_nearest_openable_parent(self):
        rows = [
            thread(3, parentThreadId=thread_id(2), canAcceptDirectInput=False),
            thread(1),
            thread(2, parentThreadId=thread_id(1), canAcceptDirectInput=False),
        ]
        result = normalize_agents(rows, 100)
        self.assertEqual([a["id"] for a in result["items"]],
                         [thread_id(1), thread_id(2), thread_id(3)])
        self.assertEqual([a["depth"] for a in result["items"]], [0, 1, 2])
        self.assertEqual(result["items"][2]["openTargetId"], thread_id(1))
        self.assertEqual(result["items"][2]["openLabel"], "Open parent session")
        rows[2]["canAcceptDirectInput"] = True
        result = normalize_agents(rows, 100)
        self.assertEqual(result["items"][2]["openTargetId"], thread_id(2))

    def test_fork_is_not_a_parent_and_missing_parent_is_not_opened(self):
        result = normalize_agents([
            thread(1, forkedFromId=thread_id(2)),
            thread(2, parentThreadId=thread_id(99), canAcceptDirectInput=False),
        ], 100)
        self.assertIsNone(result["items"][0]["parentId"])
        self.assertEqual(result["items"][0]["depth"], 0)
        self.assertIsNone(result["items"][1]["openTargetId"])

    def test_only_explicit_capability_and_persistent_uuid_can_open(self):
        rows = [
            thread(1, ephemeral=True),
            thread(2, canAcceptDirectInput=None),
            thread(3, canAcceptDirectInput=1),
            thread(4, ephemeral=0),
            thread(5),
        ]
        result = normalize_agents(rows, 100)
        self.assertEqual([a["openTargetId"] for a in result["items"]],
                         [None, None, None, None, thread_id(5)])
        self.assertEqual(result["items"][-1]["openLabel"], "Open session")

    def test_missing_malformed_and_raced_rows_are_excluded(self):
        rows = [
            None, {}, thread(1, id=";malicious command"), thread(2, status=None),
            thread(3, status={"type": "notLoaded"}), thread(4),
        ]
        result = normalize_agents(rows, 100)
        self.assertEqual([a["id"] for a in result["items"]], [thread_id(4)])
        self.assertEqual(normalize_agents([], 100)["activeCount"], 0)
        self.assertIsNone(unavailable_agents()["activeCount"])
        self.assertEqual(normalize_agents(None, 100), unavailable_agents())

    def test_duplicate_last_valid_observation_wins_without_duplicate_counts(self):
        result = normalize_agents([
            thread(1), thread(1, status={"type": "idle"}, canAcceptDirectInput=False)
        ], 100)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["activeCount"], 0)
        self.assertIsNone(result["items"][0]["openTargetId"])
        raced = normalize_agents([
            thread(1), thread(1, status={"type": "notLoaded"})
        ], 100)
        self.assertEqual(raced["items"], [])
        self.assertEqual(raced["activeCount"], 0)

    def test_incomplete_active_status_does_not_claim_a_working_agent(self):
        result = normalize_agents([thread(1, status={"type": "active"})], 100)
        self.assertEqual(result["items"][0]["state"], "unavailable")
        self.assertEqual(result["activeCount"], 0)

    def test_cycles_and_deep_trees_are_bounded_without_lost_nodes(self):
        rows = [
            thread(1, parentThreadId=thread_id(2)),
            thread(2, parentThreadId=thread_id(1)),
            thread(3, parentThreadId=thread_id(3)),
        ]
        result = normalize_agents(rows, 100)
        self.assertEqual(len(result["items"]), 3)
        self.assertIsNone(result["items"][0]["parentId"])
        rows = [thread(i, parentThreadId=thread_id(i - 1)) for i in range(1, 100)]
        result = normalize_agents(rows, 100)
        self.assertEqual(len(result["items"]), 99)
        self.assertLessEqual(max(a["depth"] for a in result["items"]), MAX_ANCESTRY)
        self.assertEqual(len({a["id"] for a in result["items"]}), 99)

    def test_titles_use_only_explicit_metadata_and_paths_use_basename(self):
        rows = [
            thread(1, name=None, agentNickname="Nickname"),
            thread(2, name="", agentRole="Reviewer"),
            thread(3, name=None, preview="PRIVATE_PROMPT",
                   cwd="/PRIVATE_PATH/repository", email="PRIVATE_EMAIL",
                   turns=[{"text": "PRIVATE_TRANSCRIPT"}], auth={"token": "PRIVATE_TOKEN"}),
        ]
        before = deepcopy(rows)
        result = normalize_agents(rows, 100)
        titles = {a["id"]: a["title"] for a in result["items"]}
        self.assertEqual(titles[thread_id(1)], f"Session {thread_id(1)[:8]}")
        self.assertEqual(titles[thread_id(2)], "Reviewer")
        self.assertEqual(titles[thread_id(3)], f"Session {thread_id(3)[:8]}")
        nicknames = {a["id"]: a["nickname"] for a in result["items"]}
        self.assertEqual(nicknames[thread_id(1)], "Nickname")
        self.assertIsNone(nicknames[thread_id(2)])
        self.assertTrue(all(a["workspace"] == "repository" for a in result["items"]))
        self.assertNotIn("PRIVATE_", json.dumps(result))
        self.assertEqual(rows, before)
        self.assertEqual(set(result["items"][0]), {
            "id", "parentId", "title", "nickname", "workspace", "model", "state",
            "openTargetId", "openLabel", "depth",
        })

    def test_task_identity_is_primary_and_codex_nickname_is_secondary(self):
        source = {"subAgent": {"thread_spawn": {
            "parent_thread_id": thread_id(1), "depth": 1,
            "agent_path": "/root/quickshell_inspect", "agent_nickname": "Sample A",
            "agent_role": None,
        }}}
        result = normalize_agents([
            thread(2, name=None, parentThreadId=thread_id(1), source=source,
                   agentNickname="Sample A", model="gpt-6-astra")
        ], 100)
        row = result["items"][0]
        self.assertEqual(row["title"], "quickshell inspect")
        self.assertEqual(row["nickname"], "Sample A")
        self.assertEqual(row["model"], "gpt-6-astra")
        self.assertNotIn("agent_path", row)
        self.assertNotIn("/root/", json.dumps(result))

    def test_title_precedence_keeps_explicit_name_then_task_then_recorded_role(self):
        source = {"subAgent": {"thread_spawn": {
            "agent_path": "/root/parent_task/codex_sources",
            "agent_role": "Source role", "agent_nickname": "Sample B",
        }}}
        named = normalize_agents([
            thread(1, name="Explicit task title", agentRole="Top role", source=source)
        ], 100)["items"][0]
        self.assertEqual(named["title"], "Explicit task title")
        self.assertEqual(named["nickname"], "Sample B")
        task = normalize_agents([
            thread(1, name=None, agentRole="Top role", source=source)
        ], 100)["items"][0]
        self.assertEqual(task["title"], "codex sources")
        source["subAgent"]["thread_spawn"]["agent_path"] = None
        role = normalize_agents([
            thread(1, name=None, agentRole="Top role", source=source)
        ], 100)["items"][0]
        self.assertEqual(role["title"], "Top role")
        role = normalize_agents([
            thread(1, name=None, agentRole=None, source=source)
        ], 100)["items"][0]
        self.assertEqual(role["title"], "Source role")

    def test_missing_task_label_never_promotes_nickname_to_primary_title(self):
        rows = [
            thread(1, name=None, agentNickname="Sample A"),
            thread(2, name=None, parentThreadId=thread_id(1), agentNickname="Sample B"),
            thread(3, name=None, source={"subAgent": "review"}, agentNickname="Sample C"),
        ]
        result = normalize_agents(rows, 100)
        by_id = {row["id"]: row for row in result["items"]}
        self.assertEqual(by_id[thread_id(1)]["title"], f"Session {thread_id(1)[:8]}")
        self.assertEqual(by_id[thread_id(2)]["title"], f"Subagent {thread_id(2)[:8]}")
        self.assertEqual(by_id[thread_id(3)]["title"], f"Subagent {thread_id(3)[:8]}")

    def test_configured_models_remain_per_thread_without_parent_or_spawn_fallback(self):
        rows = [
            thread(1, model="gpt-6.1-sol"),
            thread(2, parentThreadId=thread_id(1), model="gpt-6-astra"),
            thread(3, parentThreadId=thread_id(1), model=None,
                   source={"subAgent": {"thread_spawn": {"model": "gpt-6-astra"}}}),
        ]
        rows[2]["spawnModel"] = "gpt-6-astra"
        rows[2]["turns"] = [{"model": "gpt-6-astra"}]
        result = normalize_agents(rows, 100)
        models = {row["id"]: row["model"] for row in result["items"]}
        self.assertEqual(models, {
            thread_id(1): "gpt-6.1-sol", thread_id(2): "gpt-6-astra", thread_id(3): None,
        })

    def test_malformed_source_shapes_do_not_supply_labels_or_nicknames(self):
        sources = [
            None, True, [], "PRIVATE_SOURCE",
            {"subAgent": None}, {"subAgent": []}, {"subAgent": True},
            {"subAgent": {"thread_spawn": "PRIVATE_SOURCE"}},
            {"subAgent": {"thread_spawn": []}},
            {"agent_path": "/root/PRIVATE_TASK", "agent_nickname": "PRIVATE_NICKNAME"},
            {"subAgent": {"agent_path": "/root/PRIVATE_TASK",
                          "agent_nickname": "PRIVATE_NICKNAME"}},
        ]
        for source in sources:
            with self.subTest(source=source):
                result = normalize_agents([thread(1, name=None, source=source)], 100)
                row = result["items"][0]
                self.assertEqual(row["title"], f"Session {thread_id(1)[:8]}")
                self.assertIsNone(row["nickname"])
                self.assertNotIn("PRIVATE_", json.dumps(result))

    def test_invalid_task_paths_fall_back_without_leaking_full_paths(self):
        for path in (
            None, True, [], "", "/root", "/root/", "/root//task", "/root/../task",
            "/root/task/.", "/root/task/", "/root/___", "/root/task\\other",
            "/private/user/task", "relative_task",
        ):
            with self.subTest(path=path):
                source = {"subAgent": {"thread_spawn": {"agent_path": path}}}
                row = normalize_agents([
                    thread(1, name=None, source=source, agentRole="Recorded role")
                ], 100)["items"][0]
                self.assertEqual(row["title"], "Recorded role")
                self.assertIsNone(row["nickname"])

    def test_nicknames_and_task_labels_are_sanitized_and_bounded(self):
        source = {"subAgent": {"thread_spawn": {
            "agent_path": "/root/" + "task_" * 50 + "\x00end",
            "agent_nickname": "Source\nnickname\x1b" + "x" * 100,
        }}}
        row = normalize_agents([
            thread(1, name=None, source=source, agentNickname={"invalid": True})
        ], 100)["items"][0]
        self.assertLessEqual(len(row["nickname"]), 80)
        self.assertNotIn("\n", row["nickname"])
        self.assertNotIn("\x1b", row["nickname"])
        self.assertLessEqual(len(row["title"]), 160)
        self.assertNotIn("_", row["title"])
        self.assertNotIn("\x00", row["title"])
        row = normalize_agents([
            thread(1, source=source, agentNickname="Top level")
        ], 100)["items"][0]
        self.assertEqual(row["nickname"], "Top level")

    def test_display_strings_are_bounded_and_control_characters_removed(self):
        result = normalize_agents([
            thread(1, name="hello\nworld\x00" + "x" * 300,
                   cwd="C:\\private\\project", model="model\x1b[1m")
        ], 100)
        row = result["items"][0]
        self.assertLessEqual(len(row["title"]), 160)
        self.assertNotIn("\x00", row["title"])
        self.assertNotIn("\n", row["title"])
        self.assertNotIn("\x1b", row["model"])
        self.assertEqual(row["workspace"], "project")


if __name__ == "__main__":
    unittest.main()
