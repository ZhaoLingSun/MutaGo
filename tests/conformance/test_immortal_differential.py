from __future__ import annotations

import copy
import os
import subprocess
import sys
import time
import unittest
from unittest import mock
from pathlib import Path

CONFORMANCE_DIR = Path(__file__).resolve().parent
if str(CONFORMANCE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFORMANCE_DIR))

import immortal_differential as diff


PINNED_IMMORTAL_DEFAULT_SUMMARY = {
    "accepted": 745,
    "candidateCount": 927,
    "contractFixtureValidated": True,
    "curatedCandidateCount": 671,
    "d4BoardSizes": [9, 13, 19],
    "d4Metamorphic": True,
    "deterministicActionReexecutionAndPrefixesExact": True,
    "episodeCount": 46,
    "errorCounts": {
        "DOUBLE_CONTINUATION_KIND_FORBIDDEN": 9,
        "INVALID_PHASE": 14,
        "NONE": 745,
        "POINT_OCCUPIED": 9,
        "POINT_OFF_BOARD": 81,
        "POSITIONAL_SUPERKO": 1,
        "QUOTA_EXHAUSTED": 14,
        "TERMINAL_STATE": 27,
        "UNSUPPORTED_BY_SLICE": 7,
        "WRONG_ACTOR": 20,
    },
    "fixtureId": "contract-immortal-true-eye-settlement",
    "fixtureNormalized": True,
    "gateProdClaimed": False,
    "gateRule1MClaimed": False,
    "generatorVersion": "sha256-counter-immortal-v2-unfrozen",
    "protocolVersion": "immortal-diff-v2-unfrozen",
    "randomCandidateCount": 256,
    "rejected": 175,
    "scope": "IMMORTAL_INCREMENT_2_UNFROZEN_TEST_ONLY",
    "seed": "mutago-immortal-increment-2",
    "settlementReasonCounts": {
        "NONE": 889,
        "PRE_THRESHOLD_TWO_PASSES": 37,
        "THRESHOLD": 1,
    },
    "sha256": "a2f7cb99bcbbb4c3d9d17e79aa7796ea4bc247cad049a515770f7c24f65e6d0b",
    "unsupported": 7,
}
PINNED_IMMORTAL_DEFAULT_DIGEST = PINNED_IMMORTAL_DEFAULT_SUMMARY["sha256"]


class ContractFixtureBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = diff.load_contract_fixture()
        diff.validate_contract_fixture(cls.fixture)
        cls.request = diff.fixture_request(cls.fixture)
        cls.response = diff.oracle_episode_response(cls.request)

    def test_official_sequence_and_literal_legal_ranges_are_pinned(self) -> None:
        self.assertEqual(
            [
                360, 161, 341, 179, 359, 181, 340, 199, 358, 160,
                322, 162, 320, 198, 339, 200, 541, 1444, 1444,
            ],
            [step["action"]["actionId"] for step in self.request["steps"]],
        )
        self.assertEqual(
            diff.PINNED_FIXTURE_LEGAL_RANGES_SHA256,
            diff._fixture_legal_ranges_digest(self.fixture),
        )
        self.assertIsNone(self.fixture["descriptor"])
        for step_index, empty_diagonals in ((8, 4), (10, 3), (12, 2), (14, 1)):
            projection = self.fixture["steps"][step_index - 1]["expectedProjection"]
            ranges = projection["derived"]["legalActionRanges"]
            self.assertTrue(any(item["first"] <= 1263 <= item["last"] for item in ranges))
            occupied = set(projection["state"]["occupancy"]["black"])
            occupied.update(projection["state"]["occupancy"]["white"])
            self.assertEqual(
                empty_diagonals,
                len({160, 162, 198, 200} - occupied),
            )
        step16_ranges = self.fixture["steps"][15]["expectedProjection"]["derived"][
            "legalActionRanges"
        ]
        self.assertFalse(
            any(item["first"] <= 1263 <= item["last"] for item in step16_ranges)
        )

    def test_contract_projection_matches_independent_oracle_exactly(self) -> None:
        diff.hardened.compare_exact(
            diff.normalized_contract_fixture(self.fixture),
            diff.strip_v2_response(self.response),
            episode_id="python-immortal-contract-binding",
        )

    def test_true_eye_atomic_and_final_states_bind_every_requested_counter(self) -> None:
        armed = self.response["observations"][16]
        center = next(
            group for group in armed["state"]["groups"] if 180 in group["stones"]
        )
        self.assertEqual([], center["liberties"])
        self.assertTrue(center["protected"])
        self.assertEqual([180], center["immortalAnchors"])

        final = self.response["observations"][18]
        transition = final["transition"]
        self.assertIn(180, transition["atomicSnapshot"]["occupancy"]["black"])
        self.assertEqual(19, transition["atomicEvent"]["pskHistoryIndex"])
        step = transition["settlement"]["steps"][0]
        self.assertEqual([{"black": [180], "white": []}], step["removalBatches"])
        self.assertTrue(step["abilityDeactivated"])
        self.assertFalse(step["noOp"])
        state = final["state"]
        self.assertEqual((19, 19, 20, 20), (
            state["atomicActionCount"], state["revision"],
            state["logPosition"], state["eventLogLength"],
        ))
        self.assertEqual(21, len(state["pskHistory"]))
        self.assertEqual(("WHITE", "ORDINARY_PLAY"), (state["actor"], state["phase"]))
        self.assertEqual(
            ("INACTIVE", "CAPTURED", "SETTLED", True),
            tuple(
                state["ledger"][0][field]
                for field in ("abilityState", "stoneState", "settlementState", "tombstone")
            ),
        )
        self.assertEqual(
            {"IMMORTAL": 1, "DOUBLE_START": 0, "EIGHTWAY": 0},
            state["usedQuotas"]["BLACK"],
        )
        self.assertEqual(
            {"IMMORTAL": 0, "DOUBLE_START": 0, "EIGHTWAY": 0},
            state["remainingQuotas"]["BLACK"],
        )


class CuratedCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = diff.load_contract_fixture()
        cls.requests = diff.generate_curated_episodes(fixture)
        cls.responses = {
            request["episodeId"]: diff.oracle_episode_response(request)
            for request in cls.requests
        }

    def test_normal_and_double_attach_to_protected_zero_liberty_group(self) -> None:
        for suffix in ("normal", "double"):
            response = self.responses[f"curated-protected-{suffix}-attachment-9"]
            final = response["observations"][-1]
            state = final["state"]
            group = next(item for item in state["groups"] if 40 in item["stones"])
            self.assertEqual([], group["liberties"])
            self.assertTrue(group["protected"])
            self.assertEqual([40], group["immortalAnchors"])
            self.assertIn(41, group["stones"])
            self.assertEqual([], final["transition"]["atomicEvent"]["captured"]["black"])
            self.assertIn(40, state["occupancy"]["black"])

    def test_two_anchor_and_mixed_ledger_pop_in_global_reverse_order(self) -> None:
        two = self.responses["curated-two-anchor-reverse-pop-9"]["observations"][-1]
        steps = two["transition"]["settlement"]["steps"]
        self.assertEqual(["special-15", "special-13"], [step["ledgerEventId"] for step in steps])
        self.assertEqual((True, False, []), (
            steps[0]["abilityDeactivated"], steps[0]["noOp"], steps[0]["removalBatches"]
        ))
        self.assertEqual([{"black": [40, 41], "white": []}], steps[1]["removalBatches"])

        mixed = self.responses[
            "curated-mixed-double-immortal-reverse-order-9"
        ]["observations"][-1]["transition"]["settlement"]["steps"]
        self.assertEqual(
            [("special-4", "IMMORTAL"), ("special-2", "DOUBLE_START"), ("special-1", "IMMORTAL")],
            [(step["ledgerEventId"], step["kind"]) for step in mixed],
        )
        self.assertEqual([False, True, False], [step["noOp"] for step in mixed])

    def test_source_capture_after_settlement_has_no_refund(self) -> None:
        final = self.responses[
            "curated-settled-source-capture-no-refund-9"
        ]["observations"][-1]
        self.assertEqual([0], final["transition"]["atomicEvent"]["captured"]["black"])
        event = final["state"]["ledger"][0]
        self.assertEqual(("INACTIVE", "CAPTURED", "SETTLED", True), (
            event["abilityState"], event["stoneState"], event["settlementState"], event["tombstone"]
        ))
        self.assertEqual(1, final["state"]["usedQuotas"]["BLACK"]["IMMORTAL"])
        self.assertEqual(0, final["state"]["remainingQuotas"]["BLACK"]["IMMORTAL"])

    def test_rejection_precedence_psk_and_unsupported_eightway_are_rollback_exact(self) -> None:
        control = self.responses["curated-control-precedence-rollback-9"]
        errors = [item["transition"]["errorCode"] for item in control["observations"]]
        self.assertIn("WRONG_ACTOR", errors)
        self.assertIn("DOUBLE_CONTINUATION_KIND_FORBIDDEN", errors)
        self.assertIn("QUOTA_EXHAUSTED", errors)
        self.assertIn("UNSUPPORTED_BY_SLICE", errors)

        precedence = self.responses["curated-occupied-before-quota-precedence-9"]
        precedence_errors = [
            item["transition"]["errorCode"] for item in precedence["observations"]
        ]
        self.assertEqual("POINT_OCCUPIED", precedence_errors[2])
        self.assertEqual("QUOTA_EXHAUSTED", precedence_errors[-2])
        self.assertEqual("QUOTA_EXHAUSTED", precedence_errors[-1])

        psk = self.responses["curated-occupancy-only-psk-immortal-9"]
        self.assertEqual("POSITIONAL_SUPERKO", psk["observations"][-1]["transition"]["errorCode"])
        for response in (control, precedence, psk):
            previous = response["initialState"]
            for observation in response["observations"]:
                if observation["transition"]["status"] != "ACCEPTED":
                    self.assertEqual(previous, observation["state"])
                previous = observation["state"]

    def test_action_t_and_two_pass_settlement_are_both_present(self) -> None:
        action_t = self.responses["curated-action-t-immortal-9"]["observations"][-1]
        self.assertEqual(34, action_t["transition"]["atomicEvent"]["actionNumber"])
        self.assertEqual("THRESHOLD", action_t["transition"]["settlement"]["triggerReason"])
        self.assertIn(40, action_t["transition"]["atomicSnapshot"]["occupancy"]["white"])
        official = self.responses["contract-immortal-true-eye-settlement"]["observations"][-1]
        self.assertEqual(
            "PRE_THRESHOLD_TWO_PASSES",
            official["transition"]["settlement"]["triggerReason"],
        )


class D4AndReexecutionTests(unittest.TestCase):
    def test_all_eight_d4_and_inverse_transform_every_v2_projection_on_9_13_19(self) -> None:
        for board_size in (9, 13, 19):
            base_request = diff.true_eye_settlement_request(
                board_size, f"unit-d4-{board_size}-base"
            )
            base = diff.oracle_episode_response(
                diff.transform_request(base_request, 0, f"unit-d4-{board_size}-0")
            )
            for symmetry in range(8):
                target_id = f"unit-d4-{board_size}-{symmetry}"
                target_request = diff.transform_request(base_request, symmetry, target_id)
                target = diff.oracle_episode_response(target_request)
                expected = diff.transform_response(
                    base, board_size, symmetry, target_id
                )
                self.assertEqual(expected, target)
                restored = diff.transform_response(
                    target,
                    board_size,
                    diff.INVERSE_SYMMETRY_IDS[symmetry],
                    base["episodeId"],
                )
                self.assertEqual(base, restored)

    def test_armed_pretrigger_full_reexecution_and_suffix_prefixes_are_immutable(self) -> None:
        fixture = diff.load_contract_fixture()
        full = diff.oracle_episode_response(diff.fixture_request(fixture))
        responses = {
            request["episodeId"]: diff.oracle_episode_response(request)
            for request in diff.fixture_reexecution_requests(fixture)
        }
        self.assertEqual(full["observations"][:17], responses["fixture-immortal-armed-prefix"]["observations"])
        self.assertEqual(full["observations"][:18], responses["fixture-immortal-pre-trigger-prefix"]["observations"])
        replayed = copy.deepcopy(responses["fixture-immortal-full-reexecution"])
        replayed["episodeId"] = full["episodeId"]
        self.assertEqual(full, replayed)
        self.assertEqual(
            full["observations"],
            responses["fixture-immortal-post-settlement-suffix"]["observations"][:19],
        )


class ProtocolAndResourceTests(unittest.TestCase):
    def test_request_and_response_are_closed_and_restricted(self) -> None:
        request = diff.true_eye_settlement_request(9, "protocol-shape")
        expected = diff.oracle_episode_response(request)
        extra_request = copy.deepcopy(request)
        extra_request["unknown"] = None
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_request(extra_request)

        extra_response = copy.deepcopy(expected)
        extra_response["initialState"]["unknown"] = None
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(extra_response), request, expected
            )
        duplicate = '{"protocolVersion":"immortal-diff-v2-unfrozen","protocolVersion":"immortal-diff-v2-unfrozen"}'
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(duplicate, request, expected)

        malformed = []
        fake_settlement = copy.deepcopy(expected)
        fake_settlement["observations"][0]["transition"]["settlement"] = {}
        malformed.append(("fake-settlement", fake_settlement))
        empty_settlement = copy.deepcopy(expected)
        empty_settlement["observations"][-1]["transition"]["settlement"]["steps"] = []
        malformed.append(("empty-settlement", empty_settlement))
        wrong_event_id = copy.deepcopy(expected)
        wrong_event_id["observations"][0]["transition"]["atomicEvent"]["eventId"] = "action-999"
        malformed.append(("wrong-event-id", wrong_event_id))
        wrong_append_count = copy.deepcopy(expected)
        wrong_append_count["observations"][0]["transition"]["positionalSuperkoAppends"] = 999
        malformed.append(("wrong-append-count", wrong_append_count))
        for label, response in malformed:
            with self.subTest(label=label), self.assertRaises(diff.ProtocolError):
                diff.parse_canonical_response_line(
                    diff.canonical_json(response), request, expected
                )

    def test_atomic_snapshot_ledger_and_source_identities_fail_closed(self) -> None:
        request = diff._two_anchor_request()
        expected = diff.oracle_episode_response(request)
        final_snapshot = expected["observations"][-1]["transition"]["atomicSnapshot"]
        self.assertEqual(2, len(final_snapshot["ledger"]))

        mutations = []
        forged_event = copy.deepcopy(expected)
        forged_event["observations"][-1]["transition"]["atomicSnapshot"]["ledger"][0][
            "eventId"
        ] = "special-999"
        mutations.append(("forged-event", forged_event))

        duplicate_event = copy.deepcopy(expected)
        duplicate_ledger = duplicate_event["observations"][-1]["transition"][
            "atomicSnapshot"
        ]["ledger"]
        duplicate_ledger[1]["eventId"] = duplicate_ledger[0]["eventId"]
        mutations.append(("duplicate-event", duplicate_event))

        removed_entry = copy.deepcopy(expected)
        removed_entry["observations"][-1]["transition"]["atomicSnapshot"]["ledger"].pop()
        mutations.append(("removed-entry", removed_entry))

        stale_source = copy.deepcopy(expected)
        stale_ledger = stale_source["observations"][-1]["transition"]["atomicSnapshot"][
            "ledger"
        ]
        stale_ledger[1]["sourceStoneId"] = stale_ledger[0]["sourceStoneId"]
        mutations.append(("stale-source-reuse", stale_source))

        source_point_mismatch = copy.deepcopy(expected)
        source_point_mismatch["observations"][-1]["transition"]["atomicSnapshot"][
            "ledger"
        ][1]["sourcePoint"] = 42
        mutations.append(("source-point-mismatch", source_point_mismatch))

        stale_lifecycle = copy.deepcopy(expected)
        stale_lifecycle["observations"][-1]["transition"]["atomicSnapshot"]["ledger"][
            1
        ]["tombstone"] = True
        mutations.append(("stale-lifecycle", stale_lifecycle))

        wrong_settlement_event = copy.deepcopy(expected)
        wrong_settlement_event["observations"][-1]["transition"]["settlement"]["steps"][
            0
        ]["ledgerEventId"] = "special-999"
        mutations.append(("wrong-settlement-event", wrong_settlement_event))

        wrong_settlement_source = copy.deepcopy(expected)
        wrong_settlement_source["observations"][-1]["transition"]["settlement"]["steps"][
            0
        ]["sourcePoint"] = 42
        mutations.append(("wrong-settlement-source", wrong_settlement_source))

        for label, response in mutations:
            with self.subTest(label=label), self.assertRaises(diff.ProtocolError):
                diff.parse_canonical_response_line(
                    diff.canonical_json(response), request, expected
                )

    def test_accepted_progression_history_control_and_counters_fail_closed(self) -> None:
        request = diff.true_eye_settlement_request(9, "hostile-accepted-progression")
        expected = diff.oracle_episode_response(request)
        mutations = []

        forged_atomic_prefix = copy.deepcopy(expected)
        atomic_history = forged_atomic_prefix["observations"][-1]["transition"][
            "atomicSnapshot"
        ]["pskHistory"]
        atomic_history[1] = copy.deepcopy(atomic_history[2])
        mutations.append(("forged-old-atomic-psk-entry", forged_atomic_prefix))

        rewritten_then_healed = copy.deepcopy(expected)
        rewritten_history = rewritten_then_healed["observations"][-2]["state"][
            "pskHistory"
        ]
        rewritten_history[1] = copy.deepcopy(rewritten_history[2])
        mutations.append(("result-prefix-rewrite-then-heal", rewritten_then_healed))

        forged_actor = copy.deepcopy(expected)
        first = forged_actor["observations"][0]
        first["transition"]["atomicSnapshot"]["actor"] = "BLACK"
        first["state"]["actor"] = "BLACK"
        mutations.append(("forged-next-actor", forged_actor))

        forged_phase = copy.deepcopy(expected)
        first = forged_phase["observations"][0]
        first["transition"]["atomicSnapshot"]["phase"] = "ORDINARY_PLAY"
        first["transition"]["atomicSnapshot"]["settlementCompleted"] = True
        first["state"]["phase"] = "ORDINARY_PLAY"
        first["state"]["settlementCompleted"] = True
        mutations.append(("forged-control-phase", forged_phase))

        forged_pass_count = copy.deepcopy(expected)
        first = forged_pass_count["observations"][0]
        first["transition"]["atomicSnapshot"]["consecutivePasses"] = 1
        first["state"]["consecutivePasses"] = 1
        mutations.append(("forged-pass-counter", forged_pass_count))

        forged_event_counters = copy.deepcopy(expected)
        final_state = forged_event_counters["observations"][-1]["state"]
        final_state["settledLedgerCount"] = 0
        final_state["stableTerminalEventCount"] = 1
        mutations.append(("forged-settlement-terminal-counters", forged_event_counters))

        for label, response in mutations:
            with self.subTest(label=label), self.assertRaises(diff.ProtocolError):
                diff.parse_canonical_response_line(
                    diff.canonical_json(response), request, expected
                )

    def test_settlement_trigger_handoff_and_terminal_preservation_fail_closed(self) -> None:
        settlement_request = diff.true_eye_settlement_request(
            9, "hostile-settlement-control"
        )
        settlement_expected = diff.oracle_episode_response(settlement_request)

        wrong_reason = copy.deepcopy(settlement_expected)
        wrong_reason["observations"][-1]["transition"]["settlement"][
            "triggerReason"
        ] = "THRESHOLD"
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(wrong_reason),
                settlement_request,
                settlement_expected,
            )

        paired_handoff = copy.deepcopy(settlement_expected)
        final = paired_handoff["observations"][-1]
        final["transition"]["settlement"]["handoffActor"] = "BLACK"
        final["state"]["actor"] = "BLACK"
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(paired_handoff),
                settlement_request,
                settlement_expected,
            )

        builder = diff.EpisodeBuilder("hostile-scoring-terminal", 9)
        builder.accepted(diff.Color.BLACK, diff.board_action_v1(9, 0, 0))
        builder.accepted(diff.Color.WHITE, diff.action_v1(diff.PASS_ACTION_ID))
        builder.accepted(diff.Color.BLACK, diff.action_v1(diff.PASS_ACTION_ID))
        builder.accepted(diff.Color.WHITE, diff.action_v1(diff.PASS_ACTION_ID))
        builder.accepted(diff.Color.BLACK, diff.action_v1(diff.PASS_ACTION_ID))
        terminal_request = builder.request()
        terminal_expected = diff.oracle_episode_response(terminal_request)

        moved_terminal_board = copy.deepcopy(terminal_expected)
        terminal_observation = moved_terminal_board["observations"][-1]
        terminal_state = terminal_observation["state"]
        terminal_state["occupancy"]["black"] = [8]
        terminal_state["stones"][0]["point"] = 8
        terminal_state["groups"] = [
            {
                "color": "BLACK",
                "eightwayAnchors": [],
                "immortalAnchors": [],
                "liberties": [7, 17],
                "protected": False,
                "stones": [8],
            }
        ]
        terminal_state["pskHistory"][-1] = {"black": [8], "white": []}
        terminal_observation["transition"]["terminalEvent"]["stableOccupancy"] = {
            "black": [8],
            "white": [],
        }
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(moved_terminal_board),
                terminal_request,
                terminal_expected,
            )

        forged_terminal_quota = copy.deepcopy(terminal_expected)
        final_quota = forged_terminal_quota["observations"][-1]["state"]
        final_quota["remainingQuotas"]["BLACK"]["DOUBLE_START"] = 1
        final_quota["expiredQuotas"]["BLACK"]["DOUBLE_START"] = 0
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(forged_terminal_quota),
                terminal_request,
                terminal_expected,
            )

        forged_margin = copy.deepcopy(terminal_expected)
        forged_margin["observations"][-1]["state"]["terminal"]["score"]["margin"][
            "numerator"
        ] += 2
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(forged_margin),
                terminal_request,
                terminal_expected,
            )

    def test_nested_group_projection_failures_are_rejected(self) -> None:
        request = diff.true_eye_settlement_request(9, "hostile-nested-groups")
        expected = diff.oracle_episode_response(request)
        mutations = []

        forged_liberties = copy.deepcopy(expected)
        forged_liberties["observations"][0]["transition"]["atomicSnapshot"]["groups"][
            0
        ]["liberties"] = [0, 79]
        mutations.append(("forged-liberties", forged_liberties))

        wrong_color = copy.deepcopy(expected)
        wrong_color["observations"][0]["transition"]["atomicSnapshot"]["groups"][0][
            "color"
        ] = "WHITE"
        mutations.append(("wrong-color", wrong_color))

        duplicate_liberty = copy.deepcopy(expected)
        duplicate_liberty["observations"][0]["transition"]["atomicSnapshot"]["groups"][
            0
        ]["liberties"] = [71, 71]
        mutations.append(("duplicate-liberty", duplicate_liberty))

        out_of_range = copy.deepcopy(expected)
        out_of_range["observations"][0]["transition"]["atomicSnapshot"]["groups"][0][
            "liberties"
        ] = [71, 99]
        mutations.append(("out-of-range-liberty", out_of_range))

        wrong_order = copy.deepcopy(expected)
        wrong_order["observations"][1]["transition"]["atomicSnapshot"]["groups"].reverse()
        mutations.append(("wrong-group-order", wrong_order))

        missing_anchor = copy.deepcopy(expected)
        protected_group = next(
            group
            for group in missing_anchor["observations"][16]["transition"][
                "atomicSnapshot"
            ]["groups"]
            if 40 in group["stones"]
        )
        protected_group["immortalAnchors"] = []
        mutations.append(("missing-anchor", missing_anchor))

        nonsettling_final_drift = copy.deepcopy(expected)
        nonsettling_final_drift["observations"][0]["state"]["groups"][0][
            "liberties"
        ] = [0, 79]
        mutations.append(("nonsettling-final-drift", nonsettling_final_drift))

        for label, response in mutations:
            with self.subTest(label=label), self.assertRaises(diff.ProtocolError):
                diff.parse_canonical_response_line(
                    diff.canonical_json(response), request, expected
                )

    def test_initial_state_is_exactly_derived_from_request(self) -> None:
        builder = diff.EpisodeBuilder("hostile-request-initial-binding", 9)
        builder.accepted(diff.Color.BLACK, diff.action_v1(diff.PASS_ACTION_ID))
        request = builder.request()
        expected = diff.oracle_episode_response(request)

        wrong_board = copy.deepcopy(expected)
        board_states = [wrong_board["initialState"]]
        board_states.extend(observation["state"] for observation in wrong_board["observations"])
        board_states.extend(
            observation["transition"]["atomicSnapshot"]
            for observation in wrong_board["observations"]
            if observation["transition"]["atomicSnapshot"] is not None
        )
        for state in board_states:
            state["boardSize"] = 13
            state["threshold"] = 18
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(wrong_board), request, expected
            )

        wrong_quota = copy.deepcopy(expected)
        quota_states = [wrong_quota["initialState"]]
        quota_states.extend(observation["state"] for observation in wrong_quota["observations"])
        quota_states.extend(
            observation["transition"]["atomicSnapshot"]
            for observation in wrong_quota["observations"]
            if observation["transition"]["atomicSnapshot"] is not None
        )
        for state in quota_states:
            state["initialQuotas"]["BLACK"]["EIGHTWAY"] = 2
            state["remainingQuotas"]["BLACK"]["EIGHTWAY"] = 2
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(wrong_quota), request, expected
            )

    def test_limits_and_rejection_vocabulary_are_explicit(self) -> None:
        self.assertEqual(160, diff.MAX_EPISODE_STEPS)
        self.assertEqual(1024 * 1024, diff.MAX_REQUEST_FRAME_BYTES)
        self.assertEqual(64 * 1024 * 1024, diff.MAX_RESPONSE_FRAME_BYTES)
        self.assertEqual(256 * 1024 * 1024, diff.MAX_PROBE_STDOUT_BYTES)
        self.assertEqual(1024 * 1024, diff.MAX_PROBE_STDERR_BYTES)
        self.assertNotIn("UNSUPPORTED_BY_SLICE", diff.SUPPORTED_REJECTION_CODES)

    def test_random_manifest_count_is_unambiguous_and_deterministic(self) -> None:
        first = diff.generate_random_episodes("unit-immortal-seed", 64)
        second = diff.generate_random_episodes("unit-immortal-seed", 64)
        self.assertEqual(first, second)
        self.assertEqual(64, sum(len(request["steps"]) for request in first))

    def test_malformed_response_reports_manifest_request_index_and_full_prefix(self) -> None:
        builder = diff.EpisodeBuilder("malformed-response-context", 9)
        builder.accepted(diff.Color.BLACK, diff.board_action_v1(9, 0, 0))
        request = builder.request()
        expected = diff.oracle_episode_response(request)
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "malformed-response-context",
        }
        completed = diff.hardened._ProbeProcessResult(0, "{}\n", "")
        with mock.patch.object(diff.hardened, "_run_probe_process", return_value=completed):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.run_probe_requests(
                    __file__,
                    [request],
                    [expected],
                    manifest=manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        self.assertIn("responseIndex=0", message)
        self.assertIn("manifest=", message)
        self.assertIn("canonicalRequest=", message)
        self.assertIn("actionPrefix=", message)

        failed = diff.hardened._ProbeProcessResult(7, "", "invariant failed")
        with mock.patch.object(diff.hardened, "_run_probe_process", return_value=failed):
            with self.assertRaises(diff.ProbeError) as failed_context:
                diff.run_probe_requests(
                    __file__,
                    [request],
                    [expected],
                    manifest=manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        failed_message = str(failed_context.exception)
        self.assertIn("probe exited with 7", failed_message)
        self.assertIn("manifest=", failed_message)
        self.assertIn("canonicalRequest=", failed_message)
        self.assertIn("actionPrefix=", failed_message)

    def test_all_supervision_probe_errors_include_reproduction_context(self) -> None:
        builder = diff.EpisodeBuilder("probe-error-context", 9)
        builder.accepted(diff.Color.BLACK, diff.board_action_v1(9, 0, 0))
        request = builder.request()
        expected = diff.oracle_episode_response(request)
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "probe-error-context",
        }
        failures = (
            ("timeout", "probe timed out"),
            ("stdout-overflow", "probe stdout exceeded its byte limit"),
            ("stderr-overflow", "probe stderr exceeded its byte limit"),
            ("inherited-pipe-timeout", "inherited grandchild pipe remained open"),
            ("write-failure", "probe stdin writer failed"),
        )
        for label, message in failures:
            with self.subTest(label=label), mock.patch.object(
                diff.hardened,
                "_run_probe_process",
                side_effect=diff.ProbeError(message),
            ):
                with self.assertRaises(diff.ProbeError) as caught:
                    diff.run_probe_requests(
                        __file__,
                        [request],
                        [expected],
                        manifest=manifest,
                        deadline=diff.hardened._new_deadline(10),
                    )
                rendered = str(caught.exception)
                self.assertIn(message, rendered)
                self.assertIn("responseIndex=0", rendered)
                self.assertIn("completedResponseCount=0", rendered)
                self.assertIn("manifest=", rendered)
                self.assertIn("canonicalRequest=", rendered)
                self.assertIn("actionPrefix=", rendered)

        with self.assertRaises(diff.ProbeError) as missing:
            diff.run_probe_requests(
                Path("/definitely/missing/mutago-probe"),
                [request],
                [expected],
                manifest=manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        self.assertIn("canonicalRequest=", str(missing.exception))

        with self.assertRaises(diff.ProbeError) as expired:
            diff.run_probe_requests(
                __file__,
                [request],
                [expected],
                manifest=manifest,
                deadline=0.0,
            )
        self.assertIn("canonicalRequest=", str(expired.exception))

    def test_response_validation_deadline_probe_error_keeps_reproduction_context(self) -> None:
        builder = diff.EpisodeBuilder("response-parse-deadline", 9)
        builder.accepted(diff.Color.BLACK, diff.board_action_v1(9, 0, 0))
        request = builder.request()
        expected = diff.oracle_episode_response(request)
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "response-parse-deadline",
        }
        completed = diff.hardened._ProbeProcessResult(
            0, diff.canonical_json(expected) + "\n", ""
        )

        def finish_after_deadline(*_args, **_kwargs):
            time.sleep(0.05)
            return completed

        with mock.patch.object(
            diff.hardened, "_run_probe_process", side_effect=finish_after_deadline
        ):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    __file__,
                    [request],
                    [expected],
                    manifest=manifest,
                    deadline=diff.hardened._new_deadline(0.01),
                )
        message = str(caught.exception)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=0", message)
        self.assertIn("manifest=", message)
        self.assertIn("canonicalRequest=", message)
        self.assertIn("actionPrefix=", message)


@unittest.skipUnless(
    os.environ.get("MUTAGO_COLLAPSE_IMMORTAL_PROBE"),
    "set MUTAGO_COLLAPSE_IMMORTAL_PROBE for executable integration",
)
class ExecutableIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = Path(os.environ["MUTAGO_COLLAPSE_IMMORTAL_PROBE"]).resolve()

    def test_default_corpus_is_pinned_and_two_runs_are_identical(self) -> None:
        first = diff.run_differential(self.probe)
        second = diff.run_differential(self.probe)
        self.assertEqual(first, second)
        self.assertEqual(PINNED_IMMORTAL_DEFAULT_SUMMARY, first)
        self.assertEqual(PINNED_IMMORTAL_DEFAULT_DIGEST, first["sha256"])
        self.assertEqual(diff.DEFAULT_CANDIDATE_COUNT, first["randomCandidateCount"])
        self.assertEqual(
            first["candidateCount"],
            first["curatedCandidateCount"] + first["randomCandidateCount"],
        )
        self.assertGreater(first["accepted"], 0)
        self.assertGreater(first["rejected"], 0)
        self.assertGreater(first["unsupported"], 0)

    def test_v2_eightway_is_explicitly_unsupported_without_state_change(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "integration-v2-eightway-unsupported",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.board_action_v1(9, 4, 4, diff.ActionKind.EIGHTWAY),
                }
            ],
        }
        expected = diff.oracle_episode_response(request)
        actual, _ = diff.run_probe_requests(
            self.probe,
            [request],
            [expected],
            manifest={
                "generatorVersion": diff.GENERATOR_VERSION,
                "protocolVersion": diff.PROTOCOL_VERSION,
                "randomCandidateCount": 0,
                "seed": "integration-v2-eightway-unsupported",
            },
            deadline=diff.hardened._new_deadline(10),
        )
        self.assertEqual(expected, actual[0])
        observation = actual[0]["observations"][0]
        self.assertEqual("UNSUPPORTED", observation["transition"]["status"])
        self.assertEqual(actual[0]["initialState"], observation["state"])

    def test_v2_malformed_request_fails_closed_without_partial_output(self) -> None:
        request = diff.true_eye_settlement_request(9, "integration-v2-malformed")
        request["unknown"] = None
        completed = subprocess.run(
            [str(self.probe)],
            input=diff.canonical_json(request) + "\n",
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("", completed.stdout)
        self.assertIn("Malformed normal-pass differential frame", completed.stderr)


if __name__ == "__main__":
    unittest.main()
