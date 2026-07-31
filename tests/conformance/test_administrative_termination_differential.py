from __future__ import annotations

import copy
import hashlib
import io
import os
import subprocess
import sys
import time
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

CONFORMANCE_DIR = Path(__file__).resolve().parent
if str(CONFORMANCE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFORMANCE_DIR))

import administrative_termination_differential as diff  # noqa: E402
import double_move_differential as v1  # noqa: E402
import immortal_differential as v2  # noqa: E402
import normal_pass_differential as v0  # noqa: E402
import test_double_move_differential as v1_tests  # noqa: E402
import test_eightway_differential as v3_tests  # noqa: E402
import test_full_rule_differential as v4_tests  # noqa: E402
import test_immortal_differential as v2_tests  # noqa: E402
import test_normal_pass_differential as v0_tests  # noqa: E402


# Reviewed bounded transcript from two identical complete executable runs.
PINNED_ADMINISTRATIVE_TERMINATION_DEFAULT_DIGEST: str | None = (
    "b77d2053bfd3474e6e5c772e2369473202e6bb3bcb90fde21940eddc3b6206da"
)


def request(
    steps: list[dict[str, object]], episode_id: str = "unit-admin"
) -> dict[str, object]:
    return diff._request(episode_id, steps)


class ClosedRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.action = diff.action_candidate(
            diff.Color.BLACK, diff.board_action_v1(9, 0, 0)
        )
        self.resignation = diff.administrative_candidate(
            diff.Color.WHITE, "RESIGNATION"
        )
        self.timeout = diff.administrative_candidate(diff.Color.BLACK, "TIMEOUT")

    def test_literal_generator_domain_and_outer_shape_are_distinct(self) -> None:
        self.assertEqual(
            "administrative-termination-diff-v5-unfrozen", diff.PROTOCOL_VERSION
        )
        self.assertEqual(
            "sha256-counter-administrative-termination-v5-unfrozen",
            diff.GENERATOR_VERSION,
        )
        self.assertNotEqual(diff.GENERATOR_VERSION, diff.v4.GENERATOR_VERSION)
        self.assertNotEqual(diff.GENERATOR_DOMAIN, diff.v4.v3.DEFAULT_SEED.encode())
        frame = request([self.action])
        self.assertEqual(
            {
                "protocolVersion",
                "episodeId",
                "boardSize",
                "initialQuotas",
                "steps",
            },
            set(frame),
        )
        self.assertEqual({"candidateActor", "candidate"}, set(frame["steps"][0]))

    def test_candidate_union_is_exactly_closed(self) -> None:
        for step, fields in (
            (self.action, {"kind", "action"}),
            (self.resignation, {"kind"}),
            (self.timeout, {"kind"}),
        ):
            with self.subTest(kind=step["candidate"]["kind"]):
                self.assertEqual(fields, set(step["candidate"]))
                diff.validate_episode_request(request([step]))

    def test_invalid_candidate_shapes_fail_closed(self) -> None:
        base = request([self.action])
        mutations = []

        def mutate(candidate: object) -> None:
            item = copy.deepcopy(base)
            item["steps"][0]["candidate"] = candidate
            mutations.append(item)

        for candidate in (
            None,
            [],
            {},
            {"kind": "ACTION"},
            {"action": self.action["candidate"]["action"]},
            {"kind": "ACTION", "action": self.action["candidate"]["action"], "x": 0},
            {"kind": "RESIGNATION", "action": self.action["candidate"]["action"]},
            {"kind": "TIMEOUT", "unknown": None},
            {"kind": "CANCEL"},
            {"kind": 1},
        ):
            mutate(candidate)

        redundant_action = copy.deepcopy(self.action["candidate"])
        redundant_action["action"]["x"] = 0
        mutate(redundant_action)
        wrong_kind = copy.deepcopy(self.action["candidate"])
        wrong_kind["action"]["kind"] = "IMMORTAL"
        mutate(wrong_kind)

        outer_unknown = copy.deepcopy(base)
        outer_unknown["unknown"] = None
        mutations.append(outer_unknown)
        step_unknown = copy.deepcopy(base)
        step_unknown["steps"][0]["unknown"] = None
        mutations.append(step_unknown)
        bad_actor = copy.deepcopy(base)
        bad_actor["steps"][0]["candidateActor"] = "EMPTY"
        mutations.append(bad_actor)
        old_shape = copy.deepcopy(base)
        old_shape["steps"][0] = {
            "candidateActor": "BLACK",
            "action": diff.action_v1(diff.PASS_ACTION_ID),
        }
        mutations.append(old_shape)
        wrong_protocol = copy.deepcopy(base)
        wrong_protocol["protocolVersion"] = diff.v4.PROTOCOL_VERSION
        mutations.append(wrong_protocol)

        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(diff.ProtocolError):
                diff.validate_episode_request(mutation)

    def test_bool_quota_step_limit_and_frame_limit_fail_closed(self) -> None:
        bad_bool = request([self.action])
        bad_bool["initialQuotas"]["BLACK"]["IMMORTAL"] = False
        too_many = request([self.action])
        too_many["steps"] *= diff.MAX_EPISODE_STEPS + 1
        huge_id = request([self.action])
        huge_id["episodeId"] = "x" * (diff.MAX_REQUEST_FRAME_BYTES + 1)
        for frame in (bad_bool, too_many, huge_id):
            with self.assertRaises(diff.ProtocolError):
                diff.validate_episode_request(frame)


class ProjectionAndOracleTests(unittest.TestCase):
    def test_state_projection_is_dedicated_complete_and_stable_only_legal(self) -> None:
        frame = request(
            [
                diff.action_candidate(
                    diff.Color.BLACK,
                    diff.board_action_v1(9, 4, 4, diff.ActionKind.DOUBLE_START),
                ),
                diff.administrative_candidate(diff.Color.WHITE, "TIMEOUT"),
            ],
            "projection-pending-admin",
        )
        response = diff.oracle_episode_response(frame)
        expected_fields = diff._STATE_FIELDS
        for state in [response["initialState"]] + [
            item["state"] for item in response["observations"]
        ]:
            self.assertEqual(expected_fields, frozenset(state))
            self.assertIn("settlementCompleted", state)
            self.assertIn("pendingDouble", state)
            self.assertIn("ledger", state)
            self.assertIn("stones", state)
            self.assertIn("pskHistory", state)
            self.assertIn("legalActionRanges", state)
        pending = response["observations"][0]["state"]["pendingDouble"]
        terminal = response["observations"][1]["state"]
        self.assertEqual(pending, terminal["pendingDouble"])
        self.assertFalse(terminal["settlementCompleted"])
        self.assertEqual("TIMEOUT", terminal["terminal"]["reason"])
        self.assertEqual("WHITE", terminal["terminal"]["loser"])
        self.assertEqual("BLACK", terminal["terminal"]["winner"])
        self.assertIsNone(terminal["terminal"]["score"])
        self.assertEqual([], terminal["legalActionRanges"])

        transition = response["observations"][1]["transition"]
        self.assertEqual(diff._ADMIN_TRANSITION_FIELDS, frozenset(transition))
        self.assertNotIn("action", transition)
        self.assertNotIn("atomicEvent", transition)
        self.assertNotIn("atomicSnapshot", transition)
        self.assertNotIn("settlement", transition)
        self.assertNotIn("score", transition)
        self.assertEqual("IMMEDIATE_TERMINAL", transition["transitionKind"])
        self.assertEqual(1, transition["positionalSuperkoAppends"])
        self.assertEqual(
            diff._IMMEDIATE_TERMINAL_EVENT_FIELDS,
            frozenset(transition["terminalEvent"]),
        )

    def test_accepted_admin_preserves_every_frozen_audit_field(self) -> None:
        frame = request(
            [
                diff.action_candidate(
                    diff.Color.BLACK,
                    diff.board_action_v1(9, 2, 2, diff.ActionKind.IMMORTAL),
                ),
                diff.action_candidate(diff.Color.WHITE, diff.action_v1(diff.PASS_ACTION_ID)),
                diff.administrative_candidate(diff.Color.BLACK, "RESIGNATION"),
            ],
            "preservation",
        )
        response = diff.oracle_episode_response(frame)
        before = response["observations"][1]["state"]
        after = response["observations"][2]["state"]
        for field in (
            "occupancy",
            "stones",
            "groups",
            "ledger",
            "pendingDouble",
            "initialQuotas",
            "remainingQuotas",
            "usedQuotas",
            "expiredQuotas",
            "atomicActionCount",
            "consecutivePasses",
            "settledLedgerCount",
            "settlementCompleted",
        ):
            self.assertEqual(before[field], after[field], field)
        self.assertEqual(before["pskHistory"] + [before["occupancy"]], after["pskHistory"])
        self.assertEqual(before["revision"] + 1, after["revision"])
        self.assertEqual(before["logPosition"] + 1, after["logPosition"])
        self.assertEqual(before["eventLogLength"] + 1, after["eventLogLength"])
        self.assertEqual(
            before["stableTerminalEventCount"] + 1,
            after["stableTerminalEventCount"],
        )

    def test_both_reasons_both_losers_and_noncurrent_loser_are_accepted(self) -> None:
        cases = (
            ("RESIGNATION", diff.Color.BLACK),
            ("RESIGNATION", diff.Color.WHITE),
            ("TIMEOUT", diff.Color.BLACK),
            ("TIMEOUT", diff.Color.WHITE),
        )
        for reason, loser in cases:
            with self.subTest(reason=reason, loser=loser.value):
                frame = request(
                    [diff.administrative_candidate(loser, reason)],
                    f"both-{reason.lower()}-{loser.value.lower()}",
                )
                result = diff.oracle_episode_response(frame)["observations"][0]
                self.assertTrue(result["transition"]["accepted"])
                self.assertEqual(reason, result["state"]["terminal"]["reason"])
                self.assertEqual(loser.value, result["state"]["terminal"]["loser"])
        noncurrent = diff.oracle_episode_response(
            request(
                [diff.administrative_candidate(diff.Color.WHITE, "TIMEOUT")],
                "noncurrent-white-loses-while-black-acts",
            )
        )["observations"][0]
        self.assertEqual("WHITE", noncurrent["state"]["terminal"]["loser"])

    def test_action_transition_is_the_existing_atomic_transition_projection(self) -> None:
        steps = [
            diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 0, 0)),
            diff.action_candidate(diff.Color.WHITE, diff.action_v1(diff.PASS_ACTION_ID)),
        ]
        v5_request = request(steps, "action-parity-v5")
        v5_response = diff.oracle_episode_response(v5_request)
        v4_request = {
            "boardSize": 9,
            "episodeId": "action-parity-v4",
            "initialQuotas": copy.deepcopy(v5_request["initialQuotas"]),
            "protocolVersion": diff.v4.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": step["candidateActor"],
                    "action": copy.deepcopy(step["candidate"]["action"]),
                }
                for step in steps
            ],
        }
        v4_response = diff.v4.oracle_episode_response(v4_request)
        self.assertEqual(
            [item["transition"] for item in v4_response["observations"]],
            [item["transition"] for item in v5_response["observations"]],
        )

    def test_repeated_admin_and_action_after_terminal_reject_without_state_change(self) -> None:
        frame = request(
            [
                diff.administrative_candidate(diff.Color.BLACK, "RESIGNATION"),
                diff.administrative_candidate(diff.Color.WHITE, "TIMEOUT"),
                diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 0, 0)),
            ],
            "terminal-rejections",
        )
        response = diff.oracle_episode_response(frame)
        terminal = response["observations"][0]["state"]
        for observation in response["observations"][1:]:
            self.assertEqual(terminal, observation["state"])
            transition = observation["transition"]
            self.assertFalse(transition["accepted"])
            self.assertEqual("TERMINAL_STATE", transition["errorCode"])
            self.assertEqual(0, transition["positionalSuperkoAppends"])
            self.assertIsNone(transition["terminalEvent"])

    def test_second_ordinary_pass_scores_and_later_admin_rejects(self) -> None:
        frame = next(
            item
            for item in diff.generate_curated_episodes()
            if item["episodeId"]
            == "score-second-ordinary-pass-then-admin-and-action-reject"
        )
        response = diff.oracle_episode_response(frame)
        score_state = response["observations"][3]["state"]
        self.assertEqual("SCORE", score_state["terminal"]["reason"])
        self.assertEqual("WHITE", score_state["terminal"]["winner"])
        self.assertIsNotNone(score_state["terminal"]["score"])
        for observation in response["observations"][4:]:
            self.assertEqual(score_state, observation["state"])
            self.assertEqual("TERMINAL_STATE", observation["transition"]["errorCode"])

    def test_expected_semantics_calls_rule_apis_and_both_mask_views(self) -> None:
        frame = request(
            [
                diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 0, 0)),
                diff.administrative_candidate(diff.Color.WHITE, "TIMEOUT"),
            ],
            "independent-api-calls",
        )
        with mock.patch.object(
            diff, "apply_action", wraps=diff.apply_action
        ) as action_api, mock.patch.object(
            diff,
            "apply_administrative_termination",
            wraps=diff.apply_administrative_termination,
        ) as admin_api, mock.patch.object(
            diff.v4,
            "enumerate_action_legality",
            wraps=diff.v4.enumerate_action_legality,
        ) as enumerate_api, mock.patch.object(
            diff.v4,
            "derive_legal_mask",
            wraps=diff.v4.derive_legal_mask,
        ) as mask_api:
            diff.oracle_episode_response(frame)
        action_api.assert_called_once()
        admin_api.assert_called_once()
        self.assertEqual(3, enumerate_api.call_count)
        self.assertEqual(3, mask_api.call_count)


class CuratedCoverageAndD4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.requests = diff.generate_curated_episodes()
        cls.responses = [diff.oracle_episode_response(item) for item in cls.requests]
        cls.requests_by_id = {item["episodeId"]: item for item in cls.requests}
        cls.responses_by_id = {item["episodeId"]: item for item in cls.responses}

    def test_required_boundary_episodes_reach_the_named_stable_boundary(self) -> None:
        expectations = {
            "admin-after-one-collapse-pass": ("TERMINAL", False, 1),
            "admin-pending-double-noncurrent-loser": ("TERMINAL", False, 0),
            "admin-ordinary-boundary-after-early-second-pass": ("TERMINAL", True, 0),
            "admin-one-pass-ordinary-boundary": ("TERMINAL", True, 1),
            "admin-after-threshold-action": ("TERMINAL", True, 0),
            "admin-before-final-threshold-action-at-a-t-minus-1": (
                "TERMINAL",
                False,
                0,
            ),
            "admin-pending-double-current-loser-timeout-at-a-t-minus-1": (
                "TERMINAL",
                False,
                0,
            ),
            "admin-after-pending-normal-continuation-at-threshold": (
                "TERMINAL",
                True,
                0,
            ),
            "admin-after-pending-pass-continuation-at-threshold": (
                "TERMINAL",
                True,
                0,
            ),
        }
        for episode_id, (phase, settled, passes) in expectations.items():
            with self.subTest(episode_id=episode_id):
                final = self.responses_by_id[episode_id]["observations"][-1]["state"]
                self.assertEqual(phase, final["phase"])
                self.assertEqual(settled, final["settlementCompleted"])
                self.assertEqual(passes, final["consecutivePasses"])
        pending = self.responses_by_id["admin-pending-double-noncurrent-loser"][
            "observations"
        ][-1]["state"]
        self.assertIsNotNone(pending["pendingDouble"])

        for episode_id in (
            "admin-before-final-threshold-action-at-a-t-minus-1",
            "admin-pending-double-current-loser-timeout-at-a-t-minus-1",
        ):
            with self.subTest(episode_id=episode_id):
                response = self.responses_by_id[episode_id]
                admin_observation = response["observations"][-2]
                attempted_action = response["observations"][-1]
                self.assertEqual(
                    admin_observation["state"]["threshold"] - 1,
                    admin_observation["state"]["atomicActionCount"],
                )
                self.assertTrue(admin_observation["transition"]["accepted"])
                self.assertEqual(
                    "TERMINAL_STATE", attempted_action["transition"]["errorCode"]
                )
                self.assertEqual(admin_observation["state"], attempted_action["state"])
        pending_timeout = self.responses_by_id[
            "admin-pending-double-current-loser-timeout-at-a-t-minus-1"
        ]["observations"][-2]
        self.assertEqual("TIMEOUT", pending_timeout["state"]["terminal"]["reason"])
        self.assertEqual(
            pending_timeout["state"]["pendingDouble"]["owner"],
            pending_timeout["state"]["terminal"]["loser"],
        )

    def test_ordering_is_only_the_ordered_candidate_sequence(self) -> None:
        for frame in self.requests:
            self.assertEqual(diff._REQUEST_FIELDS, frozenset(frame))
            for step in frame["steps"]:
                self.assertEqual({"candidateActor", "candidate"}, set(step))
                self.assertNotIn("race", step)
                self.assertNotIn("priority", step)
                self.assertNotIn("timestamp", step)

    def test_genesis_prefix_full_extended_reexecution_is_exact(self) -> None:
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "unit-reexecution",
        }
        diff._compare_reexecution_and_d4(
            self.responses_by_id,
            self.responses_by_id,
            self.requests_by_id,
            manifest,
        )

    def test_d4_bases_have_reachable_special_settlement_and_admin_anchors(self) -> None:
        for board_size in (9, 13, 19):
            response = self.responses_by_id[f"curated-admin-d4-{board_size}-0"]
            diff._validate_d4_reachability_anchor(response, board_size, "python")
            observations = response["observations"]
            self.assertEqual(
                ["IMMORTAL", "DOUBLE_START", "EIGHTWAY"],
                [
                    observations[index]["transition"]["action"]["kind"]
                    for index in (0, 2, 4)
                ],
            )
            self.assertTrue(
                all(
                    observations[index]["transition"]["accepted"]
                    for index in (0, 2, 4, 6, 8)
                )
            )

    def test_all_eight_d4_and_inverses_cover_9_13_19(self) -> None:
        for board_size in (9, 13, 19):
            base_id = f"curated-admin-d4-{board_size}-0"
            base_request = self.requests_by_id[base_id]
            for symmetry in range(8):
                with self.subTest(board_size=board_size, symmetry=symmetry):
                    target_id = f"curated-admin-d4-{board_size}-{symmetry}"
                    transformed = diff.transform_response(
                        self.responses_by_id[base_id],
                        base_request,
                        symmetry,
                        target_id,
                    )
                    self.assertEqual(self.responses_by_id[target_id], transformed)
                    inverse = diff.INVERSE_SYMMETRY_IDS[symmetry]
                    restored = diff.transform_response(
                        self.responses_by_id[target_id],
                        self.requests_by_id[target_id],
                        inverse,
                        base_id,
                    )
                    self.assertEqual(self.responses_by_id[base_id], restored)

    def test_random_generator_is_bounded_deterministic_and_domain_separated(self) -> None:
        first = diff.generate_random_episodes("same-seed", 33)
        second = diff.generate_random_episodes("same-seed", 33)
        self.assertEqual(first, second)
        self.assertNotEqual(first, diff.generate_random_episodes("other-seed", 33))
        self.assertEqual(33, sum(len(item["steps"]) for item in first))
        self.assertTrue(all(len(item["steps"]) <= 16 for item in first))
        with self.assertRaises(ValueError):
            diff.generate_random_episodes("seed", diff.MAX_RANDOM_CANDIDATE_COUNT + 1)

    def test_seed_is_bounded_printable_ascii_and_cli_failure_is_safe(self) -> None:
        for seed in ("", "é", "line\nbreak", "x" * (diff.MAX_SEED_BYTES + 1)):
            with self.subTest(seed=ascii(seed)), self.assertRaises(ValueError):
                diff.generate_random_episodes(seed, 0)

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            result = diff.main(
                [
                    "--probe",
                    diff.__file__,
                    "--seed",
                    "é",
                    "--candidate-count",
                    "0",
                ]
            )
        message = stderr.getvalue()
        self.assertEqual(1, result)
        self.assertNotIn("Traceback", message)
        self.assertIn("seed must contain printable ASCII only", message)
        self.assertIn('"seed":null', message)
        self.assertIn('"seedInputAsciiRepr"', message)

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            result = diff.main(
                [
                    "--probe",
                    diff.__file__,
                    "--seed",
                    "é",
                    "--candidate-count",
                    str(diff.JSON_SAFE_INTEGER_MAX + 1),
                ]
            )
        message = stderr.getvalue()
        self.assertEqual(1, result)
        self.assertNotIn("Traceback", message)
        self.assertIn('"requestedRandomCandidateCount":null', message)
        self.assertIn('"requestedRandomCandidateCountAsciiRepr"', message)


class ResponseAndDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = request(
            [
                diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 0, 0)),
                diff.administrative_candidate(diff.Color.WHITE, "TIMEOUT"),
            ],
            "diagnostic",
        )
        self.expected = diff.oracle_episode_response(self.request)
        self.manifest = {
            "generatorDomainSha256": hashlib.sha256(diff.GENERATOR_DOMAIN).hexdigest(),
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "diagnostic",
        }

    def test_every_stable_state_expands_and_compares_all_1445_bits(self) -> None:
        actual = copy.deepcopy(self.expected)
        ranges = actual["observations"][0]["state"]["legalActionRanges"]
        bits = list(diff.v4.validate_legal_action_ranges(ranges))
        differing = next(index for index, bit in enumerate(bits) if bit)
        bits[differing] = False
        actual["observations"][0]["state"]["legalActionRanges"] = (
            diff.v4.compress_legal_bits(bits)
        )
        with self.assertRaises(diff.DifferentialMismatch) as caught:
            diff.validate_episode_response(
                actual,
                self.request,
                self.expected,
                manifest=self.manifest,
                request_line=diff.canonical_json(self.request),
            )
        message = str(caught.exception)
        self.assertIn(f"first differing actionId={differing}", message)
        self.assertIn("candidatePrefix=", message)
        self.assertIn("preCandidateState=", message)
        self.assertIn("candidate=", message)

    def test_correlated_malformed_state_and_transition_semantics_fail_closed(self) -> None:
        mutations = []

        def add(mutator) -> None:
            actual = copy.deepcopy(self.expected)
            mutator(actual)
            mutations.append(actual)

        add(
            lambda value: value["observations"][0]["transition"]["atomicEvent"].__setitem__(
                "actionNumber", 99
            )
        )
        add(lambda value: value["observations"][0]["state"].__setitem__("groups", []))
        add(
            lambda value: value["observations"][1]["transition"]["terminalEvent"].__setitem__(
                "revision", 99
            )
        )
        add(lambda value: value["observations"][1]["state"].__setitem__("revision", 99))
        add(
            lambda value: value["observations"][0]["transition"].__setitem__(
                "accepted", False
            )
        )
        add(
            lambda value: value["observations"][0]["state"].__setitem__(
                "pskHistory", None
            )
        )
        add(lambda value: value["initialState"].__setitem__("atomicActionCount", False))
        add(lambda value: value["observations"][0].__setitem__("stepIndex", True))

        for mutation in mutations:
            with self.subTest(), self.assertRaises(diff.ProtocolError):
                diff.validate_episode_response(
                    mutation, self.request, copy.deepcopy(mutation)
                )

    def test_correlated_action_rejection_legality_and_capture_mutations_fail_closed(
        self,
    ) -> None:
        single = request([self.request["steps"][0]], "correlated-action")
        rewritten = diff.oracle_episode_response(single)
        observation = rewritten["observations"][0]
        observation["state"] = copy.deepcopy(rewritten["initialState"])
        observation["transition"] = {
            "accepted": False,
            "action": copy.deepcopy(single["steps"][0]["candidate"]["action"]),
            "atomicEvent": None,
            "atomicSnapshot": None,
            "candidateActor": "BLACK",
            "errorCode": "WRONG_ACTOR",
            "positionalSuperkoAppends": 0,
            "settlement": None,
            "status": "REJECTED",
            "terminalEvent": None,
            "transitionKind": "REJECTED",
        }
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(rewritten, single, copy.deepcopy(rewritten))

        missing_legality = diff.oracle_episode_response(single)
        missing_legality["initialState"]["legalActionRanges"] = []
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(
                missing_legality, single, copy.deepcopy(missing_legality)
            )

        capture_steps = [
            diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 0, 1)),
            diff.action_candidate(diff.Color.WHITE, diff.board_action_v1(9, 1, 1)),
            diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 1, 0)),
            diff.action_candidate(diff.Color.WHITE, diff.board_action_v1(9, 2, 1)),
            diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 1, 2)),
            diff.action_candidate(diff.Color.WHITE, diff.board_action_v1(9, 8, 8)),
            diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 2, 0)),
            diff.action_candidate(diff.Color.WHITE, diff.board_action_v1(9, 8, 7)),
            diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 2, 2)),
            diff.action_candidate(diff.Color.WHITE, diff.board_action_v1(9, 8, 6)),
            diff.action_candidate(diff.Color.BLACK, diff.board_action_v1(9, 3, 1)),
        ]
        capture_request = request(capture_steps, "correlated-capture-order")
        capture_response = diff.oracle_episode_response(capture_request)
        captured = capture_response["observations"][-1]["transition"]["atomicEvent"][
            "captured"
        ]["white"]
        self.assertEqual([10, 11], captured)
        captured[:] = [11, 10, 10]
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(
                capture_response,
                capture_request,
                copy.deepcopy(capture_response),
            )

    def test_identical_malformed_observation_reports_its_exact_prefix(self) -> None:
        malformed = copy.deepcopy(self.expected)
        malformed["observations"][0]["transition"]["atomicEvent"][
            "actionNumber"
        ] = 99
        with self.assertRaises(diff.ProtocolError) as caught:
            diff.parse_canonical_response_line(
                diff.canonical_json(malformed),
                self.request,
                copy.deepcopy(malformed),
            )
        self.assertEqual(
            1,
            getattr(caught.exception, "_administrative_candidate_prefix_length"),
        )

    def test_top_level_nonobject_header_and_missing_observation_prefix_fail_closed(
        self,
    ) -> None:
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line("[]", self.request, self.expected)

        for field, value in (
            ("episodeId", "wrong-episode"),
            ("protocolVersion", "wrong-protocol"),
            ("unknown", None),
        ):
            with self.subTest(field=field):
                malformed = copy.deepcopy(self.expected)
                malformed[field] = value
                self.assertEqual(
                    0,
                    diff._first_observation_difference_prefix(
                        self.expected, malformed
                    ),
                )
                with self.assertRaises(diff.ProtocolError) as caught:
                    diff.parse_canonical_response_line(
                        diff.canonical_json(malformed), self.request, self.expected
                    )
                self.assertEqual(
                    0,
                    getattr(
                        caught.exception,
                        "_administrative_candidate_prefix_length",
                    ),
                )

        common_bad_header = copy.deepcopy(self.expected)
        common_bad_header["protocolVersion"] = "wrong-protocol"
        with self.assertRaises(diff.ProtocolError) as caught:
            diff.parse_canonical_response_line(
                diff.canonical_json(common_bad_header),
                self.request,
                copy.deepcopy(common_bad_header),
            )
        self.assertEqual(
            0,
            getattr(caught.exception, "_administrative_candidate_prefix_length"),
        )

        missing = copy.deepcopy(self.expected)
        missing["observations"].pop()
        self.assertEqual(
            2,
            diff._first_observation_difference_prefix(self.expected, missing),
        )
        with self.assertRaises(diff.ProtocolError) as caught:
            diff.parse_canonical_response_line(
                diff.canonical_json(missing), self.request, self.expected
            )
        self.assertEqual(
            2,
            getattr(caught.exception, "_administrative_candidate_prefix_length"),
        )

        common_missing = copy.deepcopy(missing)
        with self.assertRaises(diff.ProtocolError) as caught:
            diff.parse_canonical_response_line(
                diff.canonical_json(common_missing),
                self.request,
                copy.deepcopy(common_missing),
            )
        self.assertEqual(
            2,
            getattr(caught.exception, "_administrative_candidate_prefix_length"),
        )

        common_empty = copy.deepcopy(self.expected)
        common_empty["observations"] = []
        with self.assertRaises(diff.ProtocolError) as caught:
            diff.parse_canonical_response_line(
                diff.canonical_json(common_empty),
                self.request,
                copy.deepcopy(common_empty),
            )
        self.assertEqual(
            1,
            getattr(caught.exception, "_administrative_candidate_prefix_length"),
        )

    def test_pre_candidate_oracle_failures_are_attributed_to_prefix_zero(self) -> None:
        with mock.patch.object(
            diff,
            "state_projection",
            side_effect=diff.ProtocolError("initial projection failed"),
        ):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.oracle_episode_response(self.request)
        self.assertEqual(
            0,
            getattr(caught.exception, "_administrative_candidate_prefix_length"),
        )

        with mock.patch.object(
            diff, "generate_curated_episodes", return_value=[self.request]
        ), mock.patch.object(
            diff, "generate_random_episodes", return_value=[]
        ), mock.patch.object(
            diff,
            "oracle_episode_response",
            side_effect=diff.ProtocolError("pre-candidate failure without annotation"),
        ):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.run_differential(diff.__file__, candidate_count=0)
        message = str(caught.exception)
        self.assertIn("candidatePrefix=[]", message)
        self.assertIn("candidate=null", message)

    def test_unknown_fields_and_forbidden_legality_placement_fail_closed(self) -> None:
        mutations = []
        unknown = copy.deepcopy(self.expected)
        unknown["unknown"] = None
        mutations.append(unknown)
        transition = copy.deepcopy(self.expected)
        transition["observations"][1]["transition"]["action"] = None
        mutations.append(transition)
        event = copy.deepcopy(self.expected)
        event["observations"][1]["transition"]["terminalEvent"]["score"] = None
        mutations.append(event)
        nested_legal = copy.deepcopy(self.expected)
        nested_legal["observations"][0]["transition"]["atomicEvent"][
            "legalActionRanges"
        ] = []
        mutations.append(nested_legal)
        for mutation in mutations:
            with self.subTest(), self.assertRaises(diff.ProtocolError):
                diff.validate_episode_response(mutation, self.request, self.expected)

    def test_hostile_field_names_cannot_suppress_trusted_context(self) -> None:
        hostile = copy.deepcopy(self.expected)
        for name in (
            "manifest",
            "canonicalRequest",
            "candidatePrefix",
            "preCandidateState",
            "candidate",
            "responseIndex",
            "completedResponseCount",
        ):
            hostile[name] = "attacker"
        response_line = diff.canonical_json(hostile)
        completed = types.SimpleNamespace(
            returncode=0, stderr="", stdout=response_line + "\n"
        )
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [self.request],
                    [self.expected],
                    manifest=self.manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        self.assertIn("manifest=" + diff.canonical_json(self.manifest), message)
        self.assertIn("canonicalRequest=" + diff.canonical_json(self.request), message)
        self.assertIn("candidatePrefix=", message)
        self.assertIn("preCandidateState=", message)
        self.assertIn("candidate=", message)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=0", message)

    def test_restricted_profile_response_parsing_is_canonical_and_strict(self) -> None:
        line = diff.canonical_json(self.expected)
        parsed = diff.parse_canonical_response_line(line, self.request, self.expected)
        self.assertEqual(self.expected, parsed)
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(" " + line, self.request, self.expected)
        duplicate = line.replace(
            '"episodeId":"diagnostic"',
            '"episodeId":"diagnostic","episodeId":"again"',
            1,
        )
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(duplicate, self.request, self.expected)

        escaped_alias = line.replace(
            '"episodeId":"diagnostic"',
            '"episodeId":"diagnostic","episode\\u0049d":"again"',
            1,
        )
        unsafe_number = line[:-1] + ',"unknown":9007199254740992}'
        deep_value = "[" * 1000 + "null" + "]" * 1000
        deep_response = line[:-1] + ',"unknown":' + deep_value + "}"
        for hostile in (escaped_alias, unsafe_number, deep_response):
            with self.subTest(hostile=hostile[:40]), self.assertRaises(
                diff.ProtocolError
            ):
                diff.parse_canonical_response_line(
                    hostile, self.request, self.expected
                )

    def test_checkout_pinned_resource_limits_and_absolute_deadline_are_reused(self) -> None:
        self.assertEqual(diff.v4.MAX_REQUEST_FRAME_BYTES, diff.MAX_REQUEST_FRAME_BYTES)
        self.assertEqual(diff.v4.MAX_RESPONSE_FRAME_BYTES, diff.MAX_RESPONSE_FRAME_BYTES)
        self.assertEqual(diff.v4.MAX_PROBE_STDOUT_BYTES, diff.MAX_PROBE_STDOUT_BYTES)
        self.assertEqual(diff.v4.MAX_PROBE_STDERR_BYTES, diff.MAX_PROBE_STDERR_BYTES)
        self.assertEqual(diff.v4.PROBE_TIMEOUT_SECONDS, diff.PROBE_TIMEOUT_SECONDS)
        with self.assertRaises(diff.ProbeError):
            diff.validate_episode_response(
                self.expected,
                self.request,
                self.expected,
                deadline=0.0,
            )

    def test_operational_timeout_and_failure_never_synthesize_semantic_timeout(self) -> None:
        action_only = request(
            [diff.action_candidate(diff.Color.BLACK, diff.action_v1(diff.PASS_ACTION_ID))],
            "operational-not-semantic",
        )
        expected = diff.oracle_episode_response(action_only)
        self.assertNotIn("TIMEOUT", diff.canonical_json(action_only))
        before = copy.deepcopy(expected)
        for error in (
            diff.ProbeError("operational timeout"),
            diff.ProbeError("process failure"),
            diff.hardened.ProbeOutputDecodeError("stdout", 3, 0),
        ):
            with self.subTest(error=str(error)), mock.patch.object(
                diff.hardened, "_run_probe_process", side_effect=error
            ):
                with self.assertRaises(diff.ProbeError) as caught:
                    diff.run_probe_requests(
                        diff.__file__,
                        [action_only],
                        [expected],
                        manifest=self.manifest,
                        deadline=diff.hardened._new_deadline(10),
                    )
                self.assertIn(str(error), str(caught.exception))
                self.assertEqual(before, expected)
                self.assertNotIn("IMMEDIATE_TERMINAL", str(caught.exception))

    def test_stateful_sequence_is_materialized_once_before_process_use(self) -> None:
        alternate = request(
            [diff.administrative_candidate(diff.Color.BLACK, "RESIGNATION")],
            "alternate-stateful-request",
        )

        class SubstitutingSequence:
            def __init__(self) -> None:
                self.iterations = 0

            def __len__(self) -> int:
                return 1

            def __iter__(self):
                self.iterations += 1
                item = self_request if self.iterations == 1 else alternate
                return iter((item,))

            def __getitem__(self, index):
                if index == 0:
                    return self_request
                raise IndexError(index)

        self_request = self.request
        sequence = SubstitutingSequence()
        response_line = diff.canonical_json(self.expected)
        with mock.patch.object(
            diff.hardened,
            "_run_probe_process",
            return_value=types.SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=response_line + "\n",
            ),
        ):
            responses, _ = diff.run_probe_requests(
                diff.__file__,
                sequence,
                [self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        self.assertEqual(1, sequence.iterations)
        self.assertEqual([self.expected], responses)

    def test_snapshot_iteration_honors_deadline_and_wraps_iterator_failures(self) -> None:
        class SlowSequence:
            def __iter__(self):
                time.sleep(0.03)
                yield self_request

        self_request = self.request
        with self.assertRaises(diff.ProbeError) as caught:
            diff.run_probe_requests(
                diff.__file__,
                SlowSequence(),
                [self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(0.01),
            )
        message = str(caught.exception)
        self.assertIn("request snapshot", message)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=0", message)
        self.assertIn("manifest=" + diff.canonical_json(self.manifest), message)

        class FailingSequence:
            def __iter__(self):
                raise RuntimeError("iterator exploded")

        with self.assertRaises(diff.ProbeError) as caught:
            diff.run_probe_requests(
                diff.__file__,
                FailingSequence(),
                [self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        message = str(caught.exception)
        self.assertIn("request sequence snapshot failed: iterator exploded", message)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=0", message)

        for error_type in (diff.ProtocolError, diff.DifferentialMismatch):
            class HostileDomainSequence:
                def __iter__(self):
                    raise error_type(
                        "responseIndex=999; candidatePrefix=attacker"
                    )

            with self.subTest(error_type=error_type.__name__):
                with self.assertRaises(diff.ProbeError) as caught:
                    diff.run_probe_requests(
                        diff.__file__,
                        HostileDomainSequence(),
                        [self.expected],
                        manifest=self.manifest,
                        deadline=diff.hardened._new_deadline(10),
                    )
                message = str(caught.exception)
                self.assertLess(
                    message.index("responseIndex=0"),
                    message.index("responseIndex=999"),
                )
                self.assertLess(
                    message.index("candidatePrefix=[]"),
                    message.index("candidatePrefix=attacker"),
                )
                self.assertIn(
                    "manifest=" + diff.canonical_json(self.manifest),
                    message,
                )

        class DiscardingProtocolError(diff.ProtocolError):
            def __init__(self, _message: str) -> None:
                super().__init__(
                    "responseIndex=999; candidatePrefix=attacker"
                )

        class MultiArgumentProtocolError(diff.ProtocolError):
            def __init__(self, first: str, second: str) -> None:
                super().__init__(first, second)

        class UnrenderableProtocolError(diff.ProtocolError):
            def __str__(self) -> str:
                raise RuntimeError("rendering failed")

        for hostile_error in (
            DiscardingProtocolError("discard trusted context"),
            MultiArgumentProtocolError("first", "second"),
            UnrenderableProtocolError("unrenderable"),
        ):
            class HostileSubclassSequence:
                def __iter__(self):
                    raise hostile_error

            with self.subTest(error_type=type(hostile_error).__name__):
                with self.assertRaises(diff.ProbeError) as caught:
                    diff.run_probe_requests(
                        diff.__file__,
                        HostileSubclassSequence(),
                        [self.expected],
                        manifest=self.manifest,
                        deadline=diff.hardened._new_deadline(10),
                    )
                message = str(caught.exception)
                self.assertIn("responseIndex=0", message)
                self.assertIn("candidatePrefix=[]", message)
                self.assertIn(
                    "manifest=" + diff.canonical_json(self.manifest),
                    message,
                )

        class HostileRuntimeError(RuntimeError):
            render_calls = 0

            def __str__(self) -> str:
                type(self).render_calls += 1
                raise LookupError("attacker __str__ failure")

        hostile_runtime = HostileRuntimeError(
            "responseIndex=999; candidatePrefix=attacker"
        )

        class HostileRuntimeSequence:
            def __iter__(self):
                raise hostile_runtime

        with self.assertRaises(diff.ProbeError) as caught:
            diff.run_probe_requests(
                diff.__file__,
                HostileRuntimeSequence(),
                [self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        message = str(caught.exception)
        self.assertEqual(0, HostileRuntimeError.render_calls)
        self.assertLess(message.index("responseIndex=0"), message.index("responseIndex=999"))
        self.assertLess(
            message.index("candidatePrefix=[]"),
            message.index("candidatePrefix=attacker"),
        )

        oversized = diff.ProtocolError("x" * 100_000)
        self.assertEqual(4096, len(diff._safe_exception_text(oversized)))
        self.assertTrue(diff._safe_exception_text(oversized).endswith("..."))

        class HostileDecodeError(diff.hardened.ProbeOutputDecodeError):
            render_calls = 0

            def __str__(self) -> str:
                type(self).render_calls += 1
                raise LookupError("decode __str__ escaped")

        hostile_decode = HostileDecodeError("stdout", 3, 0)

        class HostileDecodeSequence:
            def __iter__(self):
                raise hostile_decode

        with self.assertRaises(diff.ProbeError) as caught:
            diff.run_probe_requests(
                diff.__file__,
                HostileDecodeSequence(),
                [self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        message = str(caught.exception)
        self.assertEqual(0, HostileDecodeError.render_calls)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=0", message)
        self.assertIn("manifest=" + diff.canonical_json(self.manifest), message)

        class HostileActionError(ValueError):
            render_calls = 0

            def __str__(self) -> str:
                type(self).render_calls += 1
                raise LookupError("hostile rendering escaped")

        class HostileAction(dict):
            def __deepcopy__(self, memo):
                return self

            def keys(self):
                raise HostileActionError(
                    "responseIndex=999; candidatePrefix=attacker"
                )

        hostile_request = copy.deepcopy(self.request)
        hostile_request["steps"][0]["candidate"]["action"] = HostileAction(
            hostile_request["steps"][0]["candidate"]["action"]
        )
        with self.assertRaises(diff.ProbeError) as caught:
            diff.run_probe_requests(
                diff.__file__,
                [hostile_request],
                [self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        message = str(caught.exception)
        self.assertEqual(0, HostileActionError.render_calls)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=0", message)
        self.assertIn("manifest=" + diff.canonical_json(self.manifest), message)

        first_request = copy.deepcopy(self.request)
        first_request["episodeId"] = "first-request"
        second_request = copy.deepcopy(hostile_request)
        second_request["episodeId"] = "second-request"
        HostileActionError.render_calls = 0
        with self.assertRaises(diff.ProbeError) as caught:
            diff.run_probe_requests(
                diff.__file__,
                [first_request, second_request],
                [self.expected, self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        message = str(caught.exception)
        self.assertEqual(0, HostileActionError.render_calls)
        self.assertIn("responseIndex=1", message)
        self.assertIn("completedResponseCount=0", message)
        self.assertIn("canonicalRequest=null", message)
        self.assertNotIn("first-request", message)
        self.assertNotIn("second-request", message)

    def test_stateful_sequence_cannot_truncate_requests_silently(self) -> None:
        class VanishingSequence:
            def __len__(self) -> int:
                return 1

            def __iter__(self):
                return iter(())

            def __getitem__(self, index):
                if index == 0:
                    return self_request
                raise IndexError(index)

        self_request = self.request
        with self.assertRaises(diff.ProbeError) as caught:
            diff.run_probe_requests(
                diff.__file__,
                VanishingSequence(),
                [self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        self.assertIn("expected response count differs", str(caught.exception))

    def test_missing_and_extra_response_lines_fail_closed(self) -> None:
        response_line = diff.canonical_json(self.expected)
        for stdout, expected_error in (
            ("", "probe output is not newline-terminated"),
            (
                response_line + "\n" + response_line + "\n",
                "probe response line count differs",
            ),
        ):
            with self.subTest(stdout_length=len(stdout)), mock.patch.object(
                diff.hardened,
                "_run_probe_process",
                return_value=types.SimpleNamespace(
                    returncode=0, stderr="", stdout=stdout
                ),
            ):
                with self.assertRaises(diff.ProbeError) as caught:
                    diff.run_probe_requests(
                        diff.__file__,
                        [self.request],
                        [self.expected],
                        manifest=self.manifest,
                        deadline=diff.hardened._new_deadline(10),
                    )
                self.assertIn(expected_error, str(caught.exception))

    def test_newline_heavy_stdout_is_scanned_without_split_materialization(self) -> None:
        class NoSplitString(str):
            def split(self, *args, **kwargs):
                raise AssertionError("stdout.split must not be used")

        stdout = NoSplitString("\n" * 100_000)
        with mock.patch.object(
            diff.hardened,
            "_run_probe_process",
            return_value=types.SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=stdout,
            ),
        ):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [self.request],
                    [self.expected],
                    manifest=self.manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        self.assertIn("probe response line count differs", str(caught.exception))

    def test_nonzero_exit_counts_only_validated_response_prefix(self) -> None:
        spoofed = "{}\n{}\n{}\n"
        completed = types.SimpleNamespace(
            returncode=2, stderr="candidatePrefix=attacker", stdout=spoofed
        )
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [self.request],
                    [self.expected],
                    manifest=self.manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        self.assertIn("completedResponseCount=0", message)
        self.assertLess(message.index("completedResponseCount=0"), message.index("attacker"))

    def test_malformed_expected_snapshot_cannot_break_trusted_failure_context(self) -> None:
        completed = types.SimpleNamespace(returncode=2, stderr="probe failed", stdout="")
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [self.request],
                    [{}],
                    manifest=self.manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=0", message)
        self.assertIn("preCandidateState=null", message)
        self.assertIn("failure=probe exited with 2", message)
        self.assertNotIn("KeyError", message)

    def test_invalid_utf8_reports_no_unvalidated_completed_responses(self) -> None:
        with mock.patch.object(
            diff.hardened,
            "_run_probe_process",
            side_effect=diff.hardened.ProbeOutputDecodeError("stdout", 17, 7),
        ):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [self.request],
                    [self.expected],
                    manifest=self.manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=0", message)

    def test_untrusted_diagnostic_labels_follow_trusted_context(self) -> None:
        hostile = copy.deepcopy(self.expected)
        hostile["candidatePrefix=attacker; responseIndex=999"] = None
        completed = types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=diff.canonical_json(hostile) + "\n",
        )
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [self.request],
                    [self.expected],
                    manifest=self.manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        self.assertLess(message.index("responseIndex=0"), message.index("responseIndex=999"))
        self.assertLess(
            message.index("candidatePrefix="), message.index("candidatePrefix=attacker")
        )

    def test_final_digest_step_cannot_overrun_absolute_deadline(self) -> None:
        response_line = diff.canonical_json(self.expected)
        completed = types.SimpleNamespace(
            returncode=0, stderr="", stdout=response_line + "\n"
        )
        original_check = diff._check_deadline

        def fail_final_digest(deadline, phase: str) -> None:
            if phase == "Administrative transcript digest completion":
                raise diff.ProbeError("final digest deadline")
            original_check(deadline, phase)

        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ), mock.patch.object(diff, "_check_deadline", side_effect=fail_final_digest):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [self.request],
                    [self.expected],
                    manifest=self.manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        self.assertIn("final digest deadline", message)
        self.assertIn("responseIndex=0", message)
        self.assertIn("completedResponseCount=1", message)
        self.assertIn("manifest=" + diff.canonical_json(self.manifest), message)
        self.assertIn("canonicalRequest=" + diff.canonical_json(self.request), message)
        self.assertIn("candidatePrefix=", message)
        self.assertIn("preCandidateState=", message)
        self.assertIn("candidate=", message)

    def test_digest_framing_and_response_counts_are_trusted(self) -> None:
        response_line = diff.canonical_json(self.expected)
        completed = types.SimpleNamespace(
            returncode=0, stderr="", stdout=response_line + "\n"
        )
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            actual, digest = diff.run_probe_requests(
                diff.__file__,
                [self.request],
                [self.expected],
                manifest=self.manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        self.assertEqual([self.expected], actual)
        expected_digest = hashlib.sha256()
        for record in (
            diff.canonical_json(self.manifest),
            diff.canonical_json(self.request),
            response_line,
        ):
            encoded = record.encode("utf-8")
            expected_digest.update(len(encoded).to_bytes(8, "big"))
            expected_digest.update(encoded)
        self.assertEqual(expected_digest.hexdigest(), digest)


class HistoricalPinsTests(unittest.TestCase):
    def test_v0_through_v4_protocols_generators_and_reviewed_digests_are_unchanged(self) -> None:
        self.assertEqual(
            (
                "normal-pass-diff-v0-unfrozen",
                "double-move-diff-v1-unfrozen",
                "immortal-diff-v2-unfrozen",
                "eightway-diff-v3-unfrozen",
                "full-rule-diff-v4-unfrozen",
            ),
            (
                v0.PROTOCOL_VERSION,
                v1.PROTOCOL_VERSION,
                v2.PROTOCOL_VERSION,
                diff.v4.v3.PROTOCOL_VERSION,
                diff.v4.PROTOCOL_VERSION,
            ),
        )
        self.assertEqual(
            (
                "sha256-counter-v0-unfrozen",
                "sha256-counter-double-v1-unfrozen",
                "sha256-counter-immortal-v2-unfrozen",
                "sha256-counter-eightway-v3-unfrozen",
                "sha256-counter-full-rule-v4-unfrozen",
            ),
            (
                v0.GENERATOR_VERSION,
                v1.GENERATOR_VERSION,
                v2.GENERATOR_VERSION,
                diff.v4.v3.GENERATOR_VERSION,
                diff.v4.GENERATOR_VERSION,
            ),
        )
        self.assertEqual(
            b"MutaGo normal-pass differential v0 unfrozen\x00",
            v0.Sha256CounterRng._DOMAIN,
        )
        self.assertEqual(
            b"MutaGo Double Increment 1 differential v1 unfrozen\x00",
            v1.Sha256CounterRng._DOMAIN,
        )
        self.assertIn(
            b"MutaGo Immortal Increment 2 v2\x00",
            v2.generate_random_episodes.__code__.co_consts,
        )
        self.assertIn(
            b"MutaGo Eightway Increment 3 v3\x00",
            diff.v4.v3.generate_random_episodes.__code__.co_consts,
        )
        self.assertEqual(
            (
                "297e38b15aae76e507d71e7bda1fb38b0d320ed102fd6f99644c6ed758051cf1",
                "644a4401cbc3adb7a09b787b84fb3ce54d60f6f63c8692a4e04192ab592eed15",
                "a2f7cb99bcbbb4c3d9d17e79aa7796ea4bc247cad049a515770f7c24f65e6d0b",
                "fa3ffd3afb4cec03c855d23d9f27ae0e16081fc1c4bc3eb101085fb7dbc0e6f1",
                "9df79d33e0e38593091d4ead82e1fac08d013f93c19d4c18f94e365eb6809596",
            ),
            (
                v0_tests.PINNED_LEGACY_SUMMARY["sha256"],
                v1_tests.PINNED_DOUBLE_DEFAULT_DIGEST,
                v2_tests.PINNED_IMMORTAL_DEFAULT_DIGEST,
                v3_tests.PINNED_EIGHTWAY_DEFAULT_DIGEST,
                v4_tests.PINNED_FULL_RULE_DEFAULT_DIGEST,
            ),
        )
        self.assertEqual(
            "b77d2053bfd3474e6e5c772e2369473202e6bb3bcb90fde21940eddc3b6206da",
            PINNED_ADMINISTRATIVE_TERMINATION_DEFAULT_DIGEST,
        )

    def test_cpp_probe_uses_real_reducer_entry_points_and_cmake_target_is_unchanged(self) -> None:
        probe = (CONFORMANCE_DIR.parents[1] / "cpp/tests/collapsereducerprobe.cpp").read_text(
            "ascii"
        )
        start = probe.index("json processAdministrativeTerminationRequest")
        end = probe.index("json processFrame", start)
        carrier = probe[start:end]
        self.assertIn("CollapseGoReducer::apply(candidateState,candidateActor,action)", carrier)
        self.assertIn("CollapseGoReducer::terminate(candidateState,candidateActor,reason)", carrier)
        for forbidden in (
            "candidateState.phase =",
            "candidateState.actor =",
            "candidateState.terminalState",
            "candidateState.positionalSuperkoHistory",
        ):
            self.assertNotIn(forbidden, carrier)
        score_start = probe.index("json terminalEventJson")
        score_end = probe.index("json exactTransitionJson", score_start)
        score_projection = probe[score_start:score_end]
        self.assertIn("result.terminalEvent", score_projection)
        self.assertIn("event.validateAgainstCommittedState(after)", score_projection)
        self.assertNotIn("after.getScore()", score_projection)
        cmake = (CONFORMANCE_DIR.parents[1] / "cpp/CMakeLists.txt").read_text("ascii")
        self.assertIn("probe serves v0-v5 test-only UNFROZEN carriers", cmake)
        self.assertEqual(1, cmake.count("add_executable(mutago-collapse-slice-probe"))


@unittest.skipUnless(
    os.environ.get("MUTAGO_COLLAPSE_ADMINISTRATIVE_TERMINATION_PROBE"),
    "set MUTAGO_COLLAPSE_ADMINISTRATIVE_TERMINATION_PROBE for executable integration",
)
class ExecutableIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = Path(
            os.environ["MUTAGO_COLLAPSE_ADMINISTRATIVE_TERMINATION_PROBE"]
        ).resolve()

    @unittest.skipIf(
        PINNED_ADMINISTRATIVE_TERMINATION_DEFAULT_DIGEST is None,
        "v5 executable transcript digest awaits two identical reviewed executions",
    )
    def test_default_corpus_runs_twice_identically_with_reviewed_pin(self) -> None:
        first = diff.run_differential(self.probe)
        second = diff.run_differential(self.probe)
        self.assertEqual(first, second)
        self.assertEqual(PINNED_ADMINISTRATIVE_TERMINATION_DEFAULT_DIGEST, first["sha256"])
        self.assertEqual(
            "ADMINISTRATIVE_TERMINATION_DIFF_V5_UNFROZEN_TEST_ONLY", first["scope"]
        )
        self.assertFalse(first["gateRule1MClaimed"])
        self.assertFalse(first["gateProdClaimed"])
        self.assertEqual(
            {
                "episodeCount": 53,
                "candidateCount": 539,
                "curatedCandidateCount": 475,
                "actionAccepted": 418,
                "actionRejected": 62,
                "administrativeAccepted": 48,
                "administrativeRejected": 11,
                "stableStateLegalityComparisons": 592,
                "legalBitComparisons": 855440,
            },
            {
                key: first[key]
                for key in (
                    "episodeCount",
                    "candidateCount",
                    "curatedCandidateCount",
                    "actionAccepted",
                    "actionRejected",
                    "administrativeAccepted",
                    "administrativeRejected",
                    "stableStateLegalityComparisons",
                    "legalBitComparisons",
                )
            },
        )
        self.assertTrue(first["genesisPrefixFullExtendedReexecutionExact"])
        self.assertNotIn("checkpointPrefixFullSuffixReexecutionExact", first)

    def test_selected_curated_boundaries_match_cpp_and_python(self) -> None:
        selected_ids = {
            "admin-pending-double-noncurrent-loser",
            "admin-before-final-threshold-action-at-a-t-minus-1",
            "admin-pending-double-current-loser-timeout-at-a-t-minus-1",
            "admin-after-pending-normal-continuation-at-threshold",
            "admin-after-pending-pass-continuation-at-threshold",
            "score-second-ordinary-pass-then-admin-and-action-reject",
            "curated-admin-d4-19-7",
        }
        requests = [
            item for item in diff.generate_curated_episodes() if item["episodeId"] in selected_ids
        ]
        expected = [diff.oracle_episode_response(item) for item in requests]
        manifest = {
            "generatorDomainSha256": hashlib.sha256(diff.GENERATOR_DOMAIN).hexdigest(),
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "selected-executable-boundaries",
        }
        actual, _ = diff.run_probe_requests(
            self.probe,
            requests,
            expected,
            manifest=manifest,
            deadline=diff.hardened._new_deadline(60),
        )
        self.assertEqual(expected, actual)

    def test_v5_cpp_parser_fails_closed_on_hostile_raw_frames(self) -> None:
        frame = request(
            [diff.administrative_candidate(diff.Color.WHITE, "TIMEOUT")],
            "raw-v5",
        )
        canonical = diff.canonical_json(frame)
        invalid: dict[str, bytes] = {}

        def encoded(label: str, value: Mapping[str, object]) -> None:
            invalid[label] = (diff.canonical_json(value) + "\n").encode("ascii")

        outer = copy.deepcopy(frame)
        outer["unknown"] = None
        encoded("unknown-outer", outer)
        step = copy.deepcopy(frame)
        step["steps"][0]["unknown"] = None
        encoded("unknown-step", step)
        admin_action = copy.deepcopy(frame)
        admin_action["steps"][0]["candidate"]["action"] = diff.action_v1(
            diff.PASS_ACTION_ID
        )
        encoded("admin-with-action", admin_action)
        action_missing = copy.deepcopy(frame)
        action_missing["steps"][0]["candidate"] = {"kind": "ACTION"}
        encoded("action-missing-action", action_missing)
        unknown_kind = copy.deepcopy(frame)
        unknown_kind["steps"][0]["candidate"] = {"kind": "CANCEL"}
        encoded("unknown-candidate-kind", unknown_kind)
        wrong_version = copy.deepcopy(frame)
        wrong_version["protocolVersion"] = "administrative-termination-diff-v5-unknown"
        encoded("wrong-version", wrong_version)
        invalid.update(
            {
                "duplicate-key": (
                    canonical.replace(
                        '"episodeId":"raw-v5"',
                        '"episodeId":"raw-v5","episodeId":"again"',
                        1,
                    )
                    + "\n"
                ).encode("ascii"),
                "escaped-alias-key": (
                    canonical.replace(
                        '"episodeId":"raw-v5"',
                        '"episodeId":"raw-v5","episode\\u0049d":"again"',
                        1,
                    )
                    + "\n"
                ).encode("ascii"),
                "noncanonical-whitespace": (" " + canonical + "\n").encode("ascii"),
                "missing-newline": canonical.encode("ascii"),
                "non-ascii": (canonical.replace("raw-v5", "é", 1) + "\n").encode(
                    "utf-8"
                ),
                "malformed-utf8": canonical.replace("raw-v5", "raw-ÿ", 1).encode(
                    "latin-1"
                )
                + b"\n",
                "deep-nesting": (
                    canonical[:-1]
                    + ',"unknown":'
                    + "[" * 1000
                    + "null"
                    + "]" * 1000
                    + "}\n"
                ).encode("ascii"),
                "float-quota": (
                    canonical.replace('"EIGHTWAY":1', '"EIGHTWAY":1.0', 1) + "\n"
                ).encode("ascii"),
                "unsafe-quota": (
                    canonical.replace(
                        '"EIGHTWAY":1', '"EIGHTWAY":9007199254740992', 1
                    )
                    + "\n"
                ).encode("ascii"),
                "oversized-frame": b" " * (diff.MAX_REQUEST_FRAME_BYTES + 1) + b"\n",
            }
        )
        for label, payload in invalid.items():
            with self.subTest(label=label):
                completed = subprocess.run(
                    [str(self.probe)],
                    input=payload,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=10,
                )
                self.assertNotEqual(0, completed.returncode)
                self.assertEqual(b"", completed.stdout)
                self.assertLessEqual(len(completed.stderr), diff.MAX_PROBE_STDERR_BYTES)
                self.assertTrue(
                    completed.stderr.startswith(b"mutago-collapse-slice-probe: ")
                )

    def test_probe_dispatches_a_mixed_v0_through_v5_stream(self) -> None:
        protocols = (
            v0.PROTOCOL_VERSION,
            v1.PROTOCOL_VERSION,
            v2.PROTOCOL_VERSION,
            diff.v4.v3.PROTOCOL_VERSION,
            diff.v4.PROTOCOL_VERSION,
            diff.PROTOCOL_VERSION,
        )
        legacy_action = diff.action_v1(diff.PASS_ACTION_ID)
        requests: list[dict[str, object]] = [
            {
                "boardSize": 9,
                "episodeId": "mixed-v0",
                "protocolVersion": protocols[0],
                "quotaMode": "ZERO",
                "steps": [{"action": legacy_action, "candidateActor": "BLACK"}],
            }
        ]
        for index, protocol in enumerate(protocols[1:5], start=1):
            requests.append(
                {
                    "boardSize": 9,
                    "episodeId": f"mixed-v{index}",
                    "initialQuotas": diff.quotas(),
                    "protocolVersion": protocol,
                    "steps": [{"action": legacy_action, "candidateActor": "BLACK"}],
                }
            )
        requests.append(
            request(
                [diff.administrative_candidate(diff.Color.WHITE, "TIMEOUT")],
                "mixed-v5",
            )
        )
        payload = "".join(diff.canonical_json(item) + "\n" for item in requests)
        completed = subprocess.run(
            [str(self.probe)],
            input=payload,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual("", completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(6, len(lines))
        self.assertEqual(
            list(protocols),
            [
                diff.v4.v3.parse_json_bytes(line.encode("ascii"))["protocolVersion"]
                for line in lines
            ],
        )


if __name__ == "__main__":
    unittest.main()
