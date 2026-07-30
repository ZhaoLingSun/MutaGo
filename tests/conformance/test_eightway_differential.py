from __future__ import annotations

import copy
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

CONFORMANCE_DIR = Path(__file__).resolve().parent
if str(CONFORMANCE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFORMANCE_DIR))

import eightway_differential as diff  # noqa: E402


PINNED_EIGHTWAY_DEFAULT_DIGEST = (
    "fa3ffd3afb4cec03c855d23d9f27ae0e16081fc1c4bc3eb101085fb7dbc0e6f1"
)


class ContractFixtureBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = diff.load_contract_fixture()
        diff.validate_contract_fixture(cls.fixture)
        cls.request = diff.fixture_request(cls.fixture)
        cls.response = diff.oracle_episode_response(cls.request)

    def test_official_descriptor_null_sequence_and_legal_ranges_are_pinned(self) -> None:
        self.assertIsNone(self.fixture["descriptor"])
        self.assertEqual("contract-eightway-immortal-split", self.fixture["fixtureId"])
        self.assertEqual(19, self.fixture["configuration"]["boardSize"])
        self.assertEqual(
            [521, 161, 342, 179, 1263, 181, 360, 199, 1444, 1444],
            [step["action"]["actionId"] for step in self.request["steps"]],
        )
        self.assertEqual(
            diff.PINNED_FIXTURE_LEGAL_RANGES_SHA256,
            diff._fixture_legal_ranges_digest(self.fixture),
        )

    def test_independent_execution_matches_every_literal_fixture_projection(self) -> None:
        diff.hardened.compare_exact(
            diff.normalized_contract_fixture(self.fixture),
            diff.strip_v3_response(self.response),
            episode_id=self.fixture["fixtureId"],
        )

    def test_checked_in_fixture_matches_the_bounded_official_generator(self) -> None:
        self.assertEqual(self.fixture, diff.build_official_contract_fixture())

    def test_fixture_binds_mixed_protection_atomic_split_and_reverse_pop(self) -> None:
        placed = self.response["observations"][4]["state"]
        mixed = next(group for group in placed["groups"] if 180 in group["stones"])
        self.assertEqual([160, 180], mixed["stones"])
        self.assertEqual([160], mixed["immortalAnchors"])
        self.assertEqual([180], mixed["eightwayAnchors"])
        self.assertTrue(mixed["protected"])

        final = self.response["observations"][-1]
        atomic = final["transition"]["atomicSnapshot"]
        self.assertIn(180, atomic["occupancy"]["black"])
        self.assertEqual([160], atomic["immortalAnchors"])
        self.assertEqual([180], atomic["eightwayAnchors"])
        settlement = final["transition"]["settlement"]
        self.assertEqual(
            [("special-5", "EIGHTWAY"), ("special-1", "IMMORTAL")],
            [(step["ledgerEventId"], step["kind"]) for step in settlement["steps"]],
        )
        self.assertEqual(
            [{"black": [180], "white": []}],
            settlement["steps"][0]["removalBatches"],
        )
        self.assertEqual([], settlement["steps"][1]["removalBatches"])
        self.assertEqual(13, len(final["state"]["pskHistory"]))
        self.assertEqual((10, 12), (
            final["state"]["revision"], final["state"]["logPosition"]
        ))
        self.assertEqual("BLACK", settlement["handoffActor"])


class CuratedCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = diff.load_contract_fixture()
        cls.requests = diff.generate_curated_episodes(fixture)
        cls.responses = {
            request["episodeId"]: diff.oracle_episode_response(request)
            for request in cls.requests
        }

    def test_no_action_kind_is_unsupported_in_v3(self) -> None:
        kinds = set()
        for request in self.requests:
            for observation in self.responses[request["episodeId"]]["observations"]:
                transition = observation["transition"]
                kinds.add(transition["action"]["kind"])
                self.assertNotEqual("UNSUPPORTED", transition["status"])
                self.assertNotEqual("UNSUPPORTED_BY_SLICE", transition["errorCode"])
        self.assertEqual(
            {"NORMAL", "PASS", "DOUBLE_START", "IMMORTAL", "EIGHTWAY"},
            kinds,
        )

    def test_n8_only_liberty_distinguishes_eightway_from_normal_suicide(self) -> None:
        response = self.responses["curated-n8-liberty-versus-normal-suicide-9"]
        normal = response["observations"][-2]
        eightway = response["observations"][-1]
        self.assertEqual(("REJECTED", "SUICIDE"), (
            normal["transition"]["status"], normal["transition"]["errorCode"]
        ))
        self.assertEqual("ACCEPTED", eightway["transition"]["status"])
        group = next(group for group in eightway["state"]["groups"] if 40 in group["stones"])
        self.assertEqual([40], group["eightwayAnchors"])
        self.assertTrue({30, 32, 48, 50}.issubset(group["liberties"]))
        self.assertEqual(len(group["liberties"]), len(set(group["liberties"])))

    def test_either_endpoint_shoulders_and_color_separation_are_exact(self) -> None:
        response = self.responses[
            "curated-eightway-endpoints-shoulders-separation-9"
        ]
        after_shoulders = response["observations"][3]["state"]
        connected = next(group for group in after_shoulders["groups"] if 40 in group["stones"])
        self.assertEqual([30, 40], connected["stones"])
        self.assertEqual([40], connected["eightwayAnchors"])
        final_groups = response["observations"][-1]["state"]["groups"]
        black_at_ten = next(group for group in final_groups if 10 in group["stones"])
        black_at_twenty = next(group for group in final_groups if 20 in group["stones"])
        self.assertNotEqual(black_at_ten["stones"], black_at_twenty["stones"])
        white_eightway = next(group for group in final_groups if 60 in group["stones"])
        self.assertIn(50, white_eightway["stones"])
        self.assertNotIn(20, white_eightway["stones"])
        for group in final_groups:
            self.assertEqual(len(group["liberties"]), len(set(group["liberties"])))

    def test_captured_pending_eightway_pops_as_auditable_noop(self) -> None:
        final = self.responses["curated-captured-pending-eightway-noop-9"][
            "observations"
        ][-1]
        ledger = final["state"]["ledger"][0]
        step = final["transition"]["settlement"]["steps"][0]
        self.assertEqual(("INACTIVE", "CAPTURED", "SETTLED", True), (
            ledger["abilityState"], ledger["stoneState"],
            ledger["settlementState"], ledger["tombstone"],
        ))
        self.assertEqual((False, True, []), (
            step["abilityDeactivated"], step["noOp"], step["removalBatches"]
        ))

    def test_action_t_is_snapshotted_before_eightway_pop(self) -> None:
        final = self.responses["curated-action-t-eightway-9"]["observations"][-1]
        self.assertEqual(34, final["transition"]["atomicEvent"]["actionNumber"])
        self.assertIn(40, final["transition"]["atomicSnapshot"]["occupancy"]["white"])
        settlement = final["transition"]["settlement"]
        self.assertEqual("THRESHOLD", settlement["triggerReason"])
        self.assertEqual("EIGHTWAY", settlement["steps"][0]["kind"])
        self.assertEqual(
            [{"black": [], "white": [40]}],
            settlement["steps"][0]["removalBatches"],
        )

    def test_eightway_psk_rejection_and_quota_above_one_roll_back_exactly(self) -> None:
        for episode, error in (
            ("curated-eightway-placement-capture-psk-rollback-9", "POSITIONAL_SUPERKO"),
            ("curated-eightway-quotas-above-one-9", "QUOTA_EXHAUSTED"),
            ("curated-eightway-surrounded-center-suicide-9", "SUICIDE"),
        ):
            response = self.responses[episode]
            previous, rejected = response["observations"][-2:]
            with self.subTest(episode=episode):
                self.assertEqual(error, rejected["transition"]["errorCode"])
                self.assertEqual(previous["state"], rejected["state"])
        quota_state = self.responses["curated-eightway-quotas-above-one-9"][
            "observations"
        ][-2]["state"]
        self.assertEqual(2, quota_state["usedQuotas"]["BLACK"]["EIGHTWAY"])
        self.assertEqual(2, quota_state["usedQuotas"]["WHITE"]["EIGHTWAY"])

    def test_global_order_and_newer_capture_make_older_source_noop(self) -> None:
        global_final = self.responses["curated-global-interleaved-i-d-e-order-9"][
            "observations"
        ][-1]
        self.assertEqual(
            ["special-5", "special-3", "special-2", "special-1"],
            [
                step["ledgerEventId"]
                for step in global_final["transition"]["settlement"]["steps"]
            ],
        )
        captured = self.responses[
            "curated-newer-immortal-captures-older-eightway-noop-9"
        ]["observations"][-1]["transition"]["settlement"]["steps"]
        self.assertEqual(["special-17", "special-1"], [step["ledgerEventId"] for step in captured])
        self.assertEqual([{"black": [40, 49], "white": []}], captured[0]["removalBatches"])
        self.assertEqual((False, True, []), (
            captured[1]["abilityDeactivated"], captured[1]["noOp"], captured[1]["removalBatches"]
        ))

    def test_eightway_rejection_precedence_is_exact(self) -> None:
        response = self.responses["curated-eightway-rejection-precedence-9"]
        errors = [item["transition"]["errorCode"] for item in response["observations"]]
        self.assertEqual(
            [
                "POINT_OFF_BOARD",
                "WRONG_ACTOR",
                "QUOTA_EXHAUSTED",
                None,
                "DOUBLE_CONTINUATION_KIND_FORBIDDEN",
                None,
                None,
                None,
                "INVALID_PHASE",
                None,
                None,
                "TERMINAL_STATE",
            ],
            errors,
        )


class D4AndReexecutionTests(unittest.TestCase):
    def test_rich_asymmetric_d4_and_inverse_cover_9_13_19(self) -> None:
        for board_size in (9, 13, 19):
            base_request = diff.eightway_immortal_split_request(
                board_size, f"unit-d4-{board_size}-base"
            )
            base = diff.oracle_episode_response(base_request)
            for symmetry in range(8):
                target_id = f"unit-d4-{board_size}-{symmetry}"
                transformed_request = diff.transform_request(
                    base_request, symmetry, target_id
                )
                actual = diff.oracle_episode_response(transformed_request)
                expected = diff.transform_response(
                    base, board_size, symmetry, target_id
                )
                with self.subTest(board=board_size, symmetry=symmetry):
                    self.assertEqual(expected, actual)
                    restored = diff.transform_response(
                        actual,
                        board_size,
                        diff.INVERSE_SYMMETRY_IDS[symmetry],
                        base_request["episodeId"],
                    )
                    self.assertEqual(base, restored)

    def test_fixture_prefixes_and_suffix_do_not_rewrite_prior_observations(self) -> None:
        fixture = diff.load_contract_fixture()
        full_request = diff.fixture_request(fixture)
        full = diff.oracle_episode_response(full_request)
        responses = {
            request["episodeId"]: diff.oracle_episode_response(request)
            for request in diff.fixture_reexecution_requests(fixture)
        }
        self.assertEqual(
            full["observations"][:5],
            responses["fixture-eightway-placement-prefix"]["observations"],
        )
        self.assertEqual(
            full["observations"][:8],
            responses["fixture-eightway-mixed-protection-prefix"]["observations"],
        )
        self.assertEqual(
            full["observations"][:9],
            responses["fixture-eightway-pre-trigger-prefix"]["observations"],
        )
        self.assertEqual(
            full["observations"],
            responses["fixture-eightway-post-settlement-suffix"]["observations"][:10],
        )


class ProtocolAndResourceTests(unittest.TestCase):
    def test_request_is_closed_and_bounded(self) -> None:
        request = diff.eightway_immortal_split_request(9, "closed-request")
        mutations = []
        unknown = copy.deepcopy(request)
        unknown["unknown"] = None
        mutations.append(unknown)
        wrong_version = copy.deepcopy(request)
        wrong_version["protocolVersion"] = "eightway-diff-v4-unfrozen"
        mutations.append(wrong_version)
        empty = copy.deepcopy(request)
        empty["steps"] = []
        mutations.append(empty)
        quota = copy.deepcopy(request)
        quota["initialQuotas"]["BLACK"]["EIGHTWAY"] = 5
        mutations.append(quota)
        redundant_coordinate = copy.deepcopy(request)
        redundant_coordinate["steps"][0]["action"]["x"] = 8
        mutations.append(redundant_coordinate)
        for mutation in mutations:
            with self.subTest(keys=sorted(mutation)), self.assertRaises(diff.ProtocolError):
                diff.validate_episode_request(mutation)

    def test_response_rejects_unsupported_vocabulary_and_state_drift(self) -> None:
        request = diff.eightway_immortal_split_request(9, "closed-response")
        expected = diff.oracle_episode_response(request)
        unsupported = copy.deepcopy(expected)
        transition = unsupported["observations"][0]["transition"]
        transition["accepted"] = False
        transition["atomicEvent"] = None
        transition["atomicSnapshot"] = None
        transition["errorCode"] = "UNSUPPORTED_BY_SLICE"
        transition["positionalSuperkoAppends"] = 0
        transition["settlement"] = None
        transition["status"] = "UNSUPPORTED"
        transition["terminalEvent"] = None
        transition["transitionKind"] = "UNSUPPORTED"
        unsupported["observations"][0]["state"] = copy.deepcopy(expected["initialState"])
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(unsupported, request, expected)

        drift = copy.deepcopy(expected)
        drift["observations"][4]["state"]["eightwayAnchors"] = []
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(drift, request, expected)

    def test_limits_and_failure_context_are_complete(self) -> None:
        self.assertEqual(1024 * 1024, diff.MAX_REQUEST_FRAME_BYTES)
        self.assertEqual(96 * 1024 * 1024, diff.MAX_RESPONSE_FRAME_BYTES)
        self.assertEqual(160, diff.MAX_EPISODE_STEPS)
        self.assertEqual(4, diff.MAX_TEST_QUOTA)
        request = diff.eightway_immortal_split_request(9, "context")
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "context",
        }
        context = diff._probe_failure_context(
            manifest,
            [request],
            [diff.canonical_json(request)],
            response_index=0,
            completed_response_count=0,
        )
        for token in (
            "responseIndex=0",
            "completedResponseCount=0",
            "manifest=",
            "canonicalRequest=",
            "actionPrefix=",
        ):
            self.assertIn(token, context)

    def test_preprobe_probe_error_has_full_available_reproduction_context(self) -> None:
        with mock.patch.object(
            diff,
            "load_contract_fixture",
            side_effect=diff.ProbeError("fixture deadline"),
        ):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_differential("unused-probe")
        message = str(caught.exception)
        for token in (
            "responseIndex=0",
            "completedResponseCount=0",
            "manifest=",
            "canonicalRequest=null",
            "actionPrefix=[]",
        ):
            self.assertIn(token, message)
    def test_shape_deadline_and_expected_count_fail_closed(self) -> None:
        request = diff.eightway_immortal_split_request(9, "bounded-validation")
        expected = diff.oracle_episode_response(request)
        with self.assertRaises(diff.ProbeError):
            diff._validate_shape(
                expected,
                expected,
                "deadline-shape",
                deadline=0.0,
            )

        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "expected-count",
        }
        with mock.patch.object(diff.hardened, "_run_probe_process") as supervisor:
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    "unused-probe",
                    [request],
                    [],
                    manifest=manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        supervisor.assert_not_called()
        message = str(caught.exception)
        self.assertIn("expected response count differs", message)
        self.assertIn("canonicalRequest=", message)
        self.assertIn("actionPrefix=", message)

    def test_d4_and_prefix_failures_report_the_exact_request_context(self) -> None:
        fixture = diff.load_contract_fixture()
        requests = diff.generate_curated_episodes(fixture)
        requests_by_id = {request["episodeId"]: request for request in requests}
        responses = {
            request["episodeId"]: diff.oracle_episode_response(request)
            for request in requests
        }
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "contextual-checks",
        }

        mutated = copy.deepcopy(responses)
        prefix_id = "fixture-eightway-placement-prefix"
        mutated[prefix_id]["observations"][0]["stepIndex"] = 99
        with self.assertRaises(diff.DifferentialMismatch) as mismatch:
            diff._compare_fixture_d4_and_prefixes(
                fixture,
                responses,
                mutated,
                requests_by_id,
                manifest,
            )
        mismatch_message = str(mismatch.exception)
        self.assertIn(prefix_id, mismatch_message)
        self.assertIn("canonicalRequest=", mismatch_message)
        self.assertIn("actionPrefix=", mismatch_message)

        with mock.patch.object(
            diff,
            "transform_response",
            side_effect=diff.ProbeError("D4 deadline"),
        ):
            with self.assertRaises(diff.ProbeError) as deadline:
                diff._compare_fixture_d4_and_prefixes(
                    fixture,
                    responses,
                    responses,
                    requests_by_id,
                    manifest,
                )
        deadline_message = str(deadline.exception)
        self.assertIn("curated-d4-eightway-9-0", deadline_message)
        self.assertIn("canonicalRequest=", deadline_message)
        self.assertIn("actionPrefix=", deadline_message)


@unittest.skipUnless(
    os.environ.get("MUTAGO_COLLAPSE_EIGHTWAY_PROBE"),
    "set MUTAGO_COLLAPSE_EIGHTWAY_PROBE for executable integration",
)
class ExecutableIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = Path(os.environ["MUTAGO_COLLAPSE_EIGHTWAY_PROBE"]).resolve()

    def test_default_corpus_runs_twice_identically_with_pinned_digest(self) -> None:
        first = diff.run_differential(self.probe)
        second = diff.run_differential(self.probe)
        self.assertEqual(first, second)
        self.assertEqual(PINNED_EIGHTWAY_DEFAULT_DIGEST, first["sha256"])
        self.assertEqual(0, first["unsupported"])
        self.assertEqual(
            first["candidateCount"],
            first["curatedCandidateCount"] + first["randomCandidateCount"],
        )
        self.assertFalse(first["gateRule1MClaimed"])
        self.assertFalse(first["gateProdClaimed"])

    def test_v3_cpp_parser_fails_closed_on_hostile_raw_frames(self) -> None:
        request = diff.eightway_immortal_split_request(9, "raw-v3")
        canonical = diff.canonical_json(request)

        unknown = copy.deepcopy(request)
        unknown["unknown"] = None
        wrong_version = copy.deepcopy(request)
        wrong_version["protocolVersion"] = "eightway-diff-v3-unknown"
        redundant_coordinate = copy.deepcopy(request)
        redundant_coordinate["steps"][0]["action"]["x"] = 0
        unknown_quota = copy.deepcopy(request)
        unknown_quota["initialQuotas"]["BLACK"]["EXTRA"] = 0

        hostile = {
            "unknown-outer": (diff.canonical_json(unknown) + "\n").encode("ascii"),
            "wrong-version": (diff.canonical_json(wrong_version) + "\n").encode("ascii"),
            "redundant-coordinate": (
                diff.canonical_json(redundant_coordinate) + "\n"
            ).encode("ascii"),
            "unknown-quota": (diff.canonical_json(unknown_quota) + "\n").encode("ascii"),
            "duplicate-key": (
                canonical.replace(
                    '"episodeId":"raw-v3"',
                    '"episodeId":"raw-v3","episodeId":"again"',
                    1,
                )
                + "\n"
            ).encode("ascii"),
            "escaped-alias-key": (
                canonical.replace(
                    '"episodeId":"raw-v3"',
                    '"episodeId":"raw-v3","episode\\u0049d":"again"',
                    1,
                )
                + "\n"
            ).encode("ascii"),
            "escaped-single-key": (
                canonical.replace(
                    '"protocolVersion"', '"protocol\\u0056ersion"', 1
                )
                + "\n"
            ).encode("ascii"),
            "noncanonical-whitespace": (" " + canonical + "\n").encode("ascii"),
            "missing-newline": canonical.encode("ascii"),
            "non-ascii": (canonical.replace("raw-v3", "é", 1) + "\n").encode(
                "utf-8"
            ),
            "malformed-utf8": canonical.replace("raw-v3", "raw-ÿ", 1).encode(
                "latin-1"
            )
            + b"\n",
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
        for label, payload in hostile.items():
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
                self.assertTrue(completed.stderr.startswith(b"mutago-collapse-slice-probe: "))

    def test_probe_dispatches_a_mixed_v0_v1_v2_v3_stream(self) -> None:
        protocols = (
            "normal-pass-diff-v0-unfrozen",
            "double-move-diff-v1-unfrozen",
            "immortal-diff-v2-unfrozen",
            diff.PROTOCOL_VERSION,
        )
        requests = [
            {
                "boardSize": 9,
                "episodeId": "mixed-v0",
                "protocolVersion": protocols[0],
                "quotaMode": "ZERO",
                "steps": [
                    {
                        "action": diff.action_v1(1444),
                        "candidateActor": "BLACK",
                    }
                ],
            }
        ]
        for index, protocol in enumerate(protocols[1:], start=1):
            requests.append(
                {
                    "boardSize": 9,
                    "episodeId": f"mixed-v{index}",
                    "initialQuotas": diff.quotas(),
                    "protocolVersion": protocol,
                    "steps": [
                        {
                            "action": diff.action_v1(1444),
                            "candidateActor": "BLACK",
                        }
                    ],
                }
            )
        payload = "".join(diff.canonical_json(request) + "\n" for request in requests)
        completed = subprocess.run(
            [str(self.probe)],
            input=payload,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual("", completed.stderr)
        lines = completed.stdout.splitlines()
        self.assertEqual(4, len(lines))
        self.assertEqual(
            list(protocols),
            [diff.parse_json_bytes(line.encode("ascii"))["protocolVersion"] for line in lines],
        )

    def test_official_fixture_matches_cpp_with_complete_v3_projection(self) -> None:
        request = diff.fixture_request()
        expected = diff.oracle_episode_response(request)
        actual, _ = diff.run_probe_requests(
            self.probe,
            [request],
            [expected],
            manifest={
                "generatorVersion": diff.GENERATOR_VERSION,
                "protocolVersion": diff.PROTOCOL_VERSION,
                "randomCandidateCount": 0,
                "seed": "official-eightway-fixture",
            },
            deadline=diff.hardened._new_deadline(30),
        )
        self.assertEqual(expected, actual[0])
        self.assertTrue(
            any(
                observation["state"]["eightwayAnchors"]
                for observation in actual[0]["observations"]
            )
        )


if __name__ == "__main__":
    unittest.main()
