from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

CONFORMANCE_DIR = Path(__file__).resolve().parent
if str(CONFORMANCE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFORMANCE_DIR))

import normal_pass_differential as diff  # noqa: E402


def _capturing_double_request() -> dict[str, object]:
    builder = diff._EpisodeBuilder.create("legacy-capturing-double", 9, "ONE")
    for actor, x, y in (
        (diff.Color.BLACK, 0, 1),
        (diff.Color.WHITE, 1, 1),
        (diff.Color.BLACK, 1, 0),
        (diff.Color.WHITE, 8, 8),
        (diff.Color.BLACK, 2, 1),
        (diff.Color.WHITE, 8, 7),
    ):
        builder.add(actor, diff.board_action_v1(9, x, y))
    builder.add(
        diff.Color.BLACK,
        diff.board_action_v1(9, 1, 2, diff.ActionKind.DOUBLE_START),
    )
    return builder.request()


def _legacy_eightway_boundary_requests(prefix: str) -> list[dict[str, object]]:
    suicide = diff._EpisodeBuilder.create(f"{prefix}-eightway-suicide", 9, "ONE")
    black_fillers = ((0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (0, 2), (2, 2), (8, 2))
    white_ring = ((3, 3), (4, 3), (5, 3), (3, 4), (5, 4), (3, 5), (4, 5), (5, 5))
    for black_point, white_point in zip(black_fillers, white_ring):
        suicide.add(diff.Color.BLACK, diff.board_action_v1(9, *black_point))
        suicide.add(diff.Color.WHITE, diff.board_action_v1(9, *white_point))
    suicide.add(
        diff.Color.BLACK,
        diff.board_action_v1(9, 4, 4, diff.ActionKind.EIGHTWAY),
    )

    psk = diff._EpisodeBuilder.create(f"{prefix}-eightway-psk", 9, "ONE")
    for actor, x, y in (
        (diff.Color.BLACK, 1, 2),
        (diff.Color.WHITE, 1, 1),
        (diff.Color.BLACK, 3, 2),
        (diff.Color.WHITE, 3, 1),
        (diff.Color.BLACK, 2, 3),
        (diff.Color.WHITE, 2, 0),
        (diff.Color.BLACK, 8, 8),
        (diff.Color.WHITE, 2, 2),
        (diff.Color.BLACK, 2, 1),
    ):
        psk.add(actor, diff.board_action_v1(9, x, y))
    psk.add(
        diff.Color.WHITE,
        diff.board_action_v1(9, 2, 2, diff.ActionKind.EIGHTWAY),
    )
    return [suicide.request(), psk.request()]


PINNED_LEGACY_SEED = "opt-in-integration"
PINNED_LEGACY_RANDOM_CANDIDATE_COUNT = 1600
PINNED_LEGACY_SUMMARY = {
    "accepted": 526,
    "boardCandidateCounts": {"9": 642, "13": 605, "19": 662},
    "candidateCount": 1909,
    "curatedCandidateCount": 309,
    "episodeCount": 27,
    "errorCounts": {
        "INVALID_PHASE": 15,
        "NONE": 526,
        "POINT_OCCUPIED": 16,
        "POINT_OFF_BOARD": 654,
        "POSITIONAL_SUPERKO": 1,
        "QUOTA_EXHAUSTED": 508,
        "SUICIDE": 1,
        "TERMINAL_STATE": 7,
        "UNSUPPORTED_BY_SLICE": 3,
        "WRONG_ACTOR": 178,
    },
    "generatorVersion": "sha256-counter-v0-unfrozen",
    "protocolVersion": "normal-pass-diff-v0-unfrozen",
    "randomCandidateCount": 1600,
    "randomUniqueActionIds": 1445,
    "rehearsalOnly": True,
    "rejected": 1380,
    "scope": "NORMAL_PASS_SLICE_UNFROZEN_V0",
    "seed": "opt-in-integration",
    "settlementReasonCounts": {
        "NONE": 1898,
        "PRE_THRESHOLD_TWO_PASSES": 8,
        "THRESHOLD": 3,
    },
    "sha256": "297e38b15aae76e507d71e7bda1fb38b0d320ed102fd6f99644c6ed758051cf1",
    "thresholdBoardSizes": [9, 13, 19],
    "unsupported": 3,
}


class Sha256CounterGeneratorTests(unittest.TestCase):
    def test_counter_bytes_are_domain_separated_and_reproducible(self) -> None:
        seed = b"counter-test"
        expected0 = hashlib.sha256(
            diff.Sha256CounterRng._DOMAIN
            + len(seed).to_bytes(8, "big")
            + seed
            + (0).to_bytes(16, "big")
        ).digest()
        expected1 = hashlib.sha256(
            diff.Sha256CounterRng._DOMAIN
            + len(seed).to_bytes(8, "big")
            + seed
            + (1).to_bytes(16, "big")
        ).digest()
        rng = diff.Sha256CounterRng(seed)
        self.assertEqual(expected0 + expected1[:8], rng.bytes(40))

        first = diff.Sha256CounterRng("same-seed")
        second = diff.Sha256CounterRng("same-seed")
        self.assertEqual(
            [first.randbelow(1445) for _ in range(100)],
            [second.randbelow(1445) for _ in range(100)],
        )

    def test_action_v1_generation_covers_exact_kind_major_envelopes(self) -> None:
        boundaries = (
            (0, "NORMAL"),
            (360, "NORMAL"),
            (361, "IMMORTAL"),
            (721, "IMMORTAL"),
            (722, "DOUBLE_START"),
            (1082, "DOUBLE_START"),
            (1083, "EIGHTWAY"),
            (1443, "EIGHTWAY"),
            (1444, "PASS"),
        )
        for action_id, kind in boundaries:
            with self.subTest(action_id=action_id):
                self.assertEqual(
                    {
                        "schemaVersion": "action-v1",
                        "actionId": action_id,
                        "kind": kind,
                    },
                    diff.action_v1(action_id),
                )
        self.assertEqual(100, diff.board_action_v1(9, 0, 0)["actionId"])
        self.assertEqual(60, diff.board_action_v1(13, 0, 0)["actionId"])
        self.assertEqual(0, diff.board_action_v1(19, 0, 0)["actionId"])

    def test_random_corpus_is_exact_count_deterministic_and_structured(self) -> None:
        count = diff.MIN_RANDOM_CANDIDATE_COUNT + 130
        first = diff.generate_random_episodes("unit-corpus", count)
        second = diff.generate_random_episodes("unit-corpus", count)
        self.assertEqual(first, second)
        self.assertTrue(
            any("-sha-" in frame["episodeId"] for frame in first),
            "test corpus must exercise the SHA-driven random suffix",
        )
        self.assertEqual(count, sum(len(frame["steps"]) for frame in first))
        self.assertTrue(
            all(len(frame["steps"]) <= diff.MAX_EPISODE_STEPS for frame in first)
        )
        self.assertEqual({9, 13, 19}, {frame["boardSize"] for frame in first})
        self.assertEqual({"ZERO"}, {frame["quotaMode"] for frame in first})

        action_ids = {
            step["action"]["actionId"]
            for frame in first
            for step in frame["steps"]
        }
        self.assertEqual(set(range(1445)), action_ids)

        errors: set[str] = set()
        phases: set[str] = set()
        statuses: set[str] = set()
        for frame in first[:3]:
            response = diff.oracle_episode_response(frame)
            for observation in response["observations"]:
                errors.add(observation["errorCode"])
                phases.add(observation["phase"])
                statuses.add(observation["status"])
        self.assertTrue(
            {
                "WRONG_ACTOR",
                "POINT_OCCUPIED",
                "INVALID_PHASE",
                "TERMINAL_STATE",
                "POINT_OFF_BOARD",
            }.issubset(errors)
        )
        self.assertTrue({"COLLAPSE_PLAY", "ORDINARY_PLAY", "TERMINAL"}.issubset(phases))
        self.assertTrue({"ACCEPTED", "REJECTED"}.issubset(statuses))

    def test_curated_cases_cover_capture_psk_scoring_and_unsupported(self) -> None:
        frames = diff.generate_curated_episodes()
        responses = {frame["episodeId"]: diff.oracle_episode_response(frame) for frame in frames}

        capture = responses["curated-capture-9-zero"]["observations"][-2]
        self.assertEqual([19, 21], capture["captures"]["white"])
        self.assertEqual("ACCEPTED", capture["status"])

        psk = responses["curated-psk-9-zero"]["observations"][-1]
        self.assertEqual("POSITIONAL_SUPERKO", psk["errorCode"])
        self.assertEqual("REJECTED", psk["status"])

        basic = responses["curated-basic-terminal-9-zero"]["observations"]
        self.assertTrue(any(observation["terminalScoring"] for observation in basic))
        self.assertEqual("POINT_OFF_BOARD", basic[-1]["errorCode"])
        self.assertEqual("TERMINAL", basic[-1]["phase"])
        self.assertTrue(basic[-1]["score"]["isScored"])

        unsupported = responses["curated-unsupported-9-one"]["observations"]
        self.assertEqual(
            ["UNSUPPORTED", "UNSUPPORTED", "UNSUPPORTED"],
            [observation["status"] for observation in unsupported[:3]],
        )
        self.assertTrue(
            all(
                observation["errorCode"] == "UNSUPPORTED_BY_SLICE"
                for observation in unsupported[:3]
            )
        )

        for board_size, threshold in ((9, 34), (13, 70), (19, 150)):
            observations = responses[
                f"curated-threshold-{board_size}-zero"
            ]["observations"]
            self.assertEqual(threshold, len(observations))
            self.assertEqual(threshold, observations[-1]["A"])
            self.assertEqual("THRESHOLD", observations[-1]["settlementReason"])
            self.assertEqual("ORDINARY_PLAY", observations[-1]["phase"])
            self.assertEqual(0, observations[-1]["consecutivePasses"])
    def test_legacy_adapter_discards_legal_capturing_double_tentative_state(self) -> None:
        request = _capturing_double_request()
        prefix = diff._EpisodeBuilder.create("legacy-capturing-prefix", 9, "ONE")
        for step in request["steps"][:-1]:
            prefix.add(diff.Color(step["candidateActor"]), step["action"])
        action = request["steps"][-1]["action"]
        before = prefix.state
        tentative = diff.apply_action(before, diff.Color.BLACK, action)
        self.assertTrue(tentative.accepted)
        self.assertEqual((10,), tentative.atomic_event.captured.white)
        with self.assertRaises(diff.UnsupportedSliceAction):
            diff._apply_v0_slice_action(before, diff.Color.BLACK, action)
        self.assertEqual(before, prefix.state)

        response = diff.oracle_episode_response(request)
        rejected = response["observations"][-1]
        previous = response["observations"][-2]
        self.assertEqual("UNSUPPORTED", rejected["status"])
        self.assertEqual("UNSUPPORTED_BY_SLICE", rejected["errorCode"])
        self.assertEqual({"black": [], "white": []}, rejected["captures"])
        self.assertEqual(previous["A"], rejected["A"])
        self.assertEqual(previous["blackOccupancy"], rejected["blackOccupancy"])
        self.assertEqual(previous["whiteOccupancy"], rejected["whiteOccupancy"])
        self.assertEqual(previous["remainingQuotas"], rejected["remainingQuotas"])

    def test_legacy_adapter_keeps_immortal_psk_mechanics_unsupported(self) -> None:
        builder = diff._EpisodeBuilder.create("legacy-v0-immortal-psk", 9, "ONE")
        for actor, x, y in (
            (diff.Color.BLACK, 1, 2),
            (diff.Color.WHITE, 1, 1),
            (diff.Color.BLACK, 3, 2),
            (diff.Color.WHITE, 3, 1),
            (diff.Color.BLACK, 2, 3),
            (diff.Color.WHITE, 2, 0),
            (diff.Color.BLACK, 8, 8),
            (diff.Color.WHITE, 2, 2),
            (diff.Color.BLACK, 2, 1),
        ):
            builder.add(actor, diff.board_action_v1(9, x, y))
        before = builder.state
        action = diff.board_action_v1(9, 2, 2, diff.ActionKind.IMMORTAL)
        with self.assertRaises(diff.UnsupportedSliceAction):
            diff._apply_v0_slice_action(before, diff.Color.WHITE, action)
        builder.add(diff.Color.WHITE, action)
        self.assertIs(before, builder.state)
        response = diff.oracle_episode_response(builder.request())
        observation = response["observations"][-1]
        self.assertEqual("UNSUPPORTED", observation["status"])
        self.assertEqual("UNSUPPORTED_BY_SLICE", observation["errorCode"])
        self.assertEqual(response["observations"][-2]["A"], observation["A"])
        self.assertEqual(
            response["observations"][-2]["blackOccupancy"],
            observation["blackOccupancy"],
        )
        self.assertEqual(
            response["observations"][-2]["whiteOccupancy"],
            observation["whiteOccupancy"],
        )

    def test_legacy_adapter_maps_eightway_suicide_and_psk_to_unsupported_rollback(self) -> None:
        for request in _legacy_eightway_boundary_requests("python-v0"):
            response = diff.oracle_episode_response(request)
            previous, observation = response["observations"][-2:]
            with self.subTest(episode=request["episodeId"]):
                self.assertEqual("UNSUPPORTED", observation["status"])
                self.assertEqual("UNSUPPORTED_BY_SLICE", observation["errorCode"])
                for field in (
                    "A",
                    "actor",
                    "blackOccupancy",
                    "phase",
                    "pskHistory",
                    "remainingQuotas",
                    "whiteOccupancy",
                ):
                    self.assertEqual(previous[field], observation[field], field)


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = {
            "protocolVersion": diff.PROTOCOL_VERSION,
            "episodeId": "protocol-unit",
            "boardSize": 9,
            "quotaMode": "ZERO",
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(1444),
                }
            ],
        }

    def test_closed_request_and_action_envelopes(self) -> None:
        self.assertIs(self.request, diff.validate_episode_request(self.request))

        unknown = deepcopy(self.request)
        unknown["transport"] = "production"
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_request(unknown)

        wrong_version = deepcopy(self.request)
        wrong_version["protocolVersion"] = "semantic-projection-v1"
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_request(wrong_version)

        malformed_action = deepcopy(self.request)
        malformed_action["steps"][0]["action"]["x"] = 0
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_request(malformed_action)

        boolean_board = deepcopy(self.request)
        boolean_board["boardSize"] = True
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_request(boolean_board)

    def test_request_resource_bounds_are_enforced(self) -> None:
        too_many_steps = deepcopy(self.request)
        too_many_steps["steps"] = too_many_steps["steps"] * (
            diff.MAX_EPISODE_STEPS + 1
        )
        with self.assertRaisesRegex(diff.ProtocolError, "resource limit"):
            diff.validate_episode_request(too_many_steps)

        with mock.patch.object(diff, "MAX_REQUEST_FRAME_BYTES", 32):
            with self.assertRaisesRegex(diff.ProtocolError, "1 MiB request limit"):
                diff.validate_episode_request(self.request)

        with self.assertRaises(ValueError):
            diff.generate_random_episodes(
                "too-large",
                diff.MAX_RANDOM_CANDIDATE_COUNT + 1,
            )

    def test_timeout_is_converted_to_probe_error(self) -> None:
        with self.assertRaisesRegex(diff.ProbeError, "corpus deadline"):
            diff._run_probe_process(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(1)",
                ],
                "",
                0.01,
            )

    def test_nonfinite_and_nonpositive_process_timeouts_fail_closed(self) -> None:
        for invalid_timeout in (float("inf"), float("nan"), 0.0, -1.0, True):
            with self.subTest(invalid_timeout=invalid_timeout):
                with self.assertRaises(diff.ProbeError):
                    diff._run_probe_process(
                        [sys.executable, "-c", "pass"], "", invalid_timeout
                    )

        with self.assertRaises(diff.ProbeOutputDecodeError) as invalid_utf8:
            diff._run_probe_process(
                [
                    sys.executable,
                    "-c",
                    "import os; os.write(1, b'\\xff\\n')",
                ],
                "",
                5,
            )
        self.assertEqual("stdout", invalid_utf8.exception.stream_name)
        self.assertEqual(0, invalid_utf8.exception.response_index)

    def test_process_output_is_bounded_before_decoding(self) -> None:
        with mock.patch.object(diff, "MAX_PROBE_STDOUT_BYTES", 32):
            with self.assertRaisesRegex(diff.ProbeError, "bounded process output"):
                diff._run_probe_process(
                    [
                        sys.executable,
                        "-c",
                        "import sys; sys.stdout.buffer.write(b'x' * 4096)",
                    ],
                    "",
                    5,
                )

    def test_inherited_grandchild_pipes_are_bounded_by_timeout(self) -> None:
        script = (
            "import os,subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)']); "
            "os._exit(0)"
        )
        started = time.perf_counter()
        with self.assertRaisesRegex(diff.ProbeError, "corpus deadline"):
            diff._run_probe_process([sys.executable, "-c", script], "", 0.2)
        self.assertLess(time.perf_counter() - started, 1.5)

    def test_repository_oracle_modules_are_pinned_to_this_checkout(self) -> None:
        self.assertEqual(str(diff.PYTHON_ROOT), sys.path[0])
        for module_name in (
            "mutago",
            "mutago.collapse_go",
            "mutago.collapse_go.normal_pass_oracle",
        ):
            module_path = Path(sys.modules[module_name].__file__).resolve()
            try:
                module_path.relative_to(diff.PYTHON_ROOT)
            except ValueError as exc:  # pragma: no cover - assertion detail
                self.fail(f"{module_name} resolved outside the checkout: {exc}")

        foreign_name = "mutago.foreign_test_module"
        foreign = mock.Mock(__file__="/outside/checkout/oracle.py")
        with mock.patch.dict(sys.modules, {foreign_name: foreign}):
            with self.assertRaisesRegex(ImportError, "outside this checkout"):
                diff._require_repository_oracle_module(foreign_name)

    def test_malformed_response_diagnostics_include_reproduction_context(self) -> None:
        expected_manifest = {
            "candidateCount": diff.MIN_RANDOM_CANDIDATE_COUNT,
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "seed": "diagnostic-seed",
        }
        request_line = diff.canonical_json(self.request)
        action_prefix = diff.canonical_json(self.request["steps"])
        cases = (
            (
                "malformed-json",
                diff._ProbeProcessResult(0, '{"bad":\n', ""),
                diff.ProtocolError,
                "responseIndex=0",
            ),
            (
                "non-newline",
                diff._ProbeProcessResult(0, "{}", ""),
                diff.ProbeError,
                "responseIndex=0",
            ),
            (
                "wrong-line-count",
                diff._ProbeProcessResult(0, "{}\n{}\n", ""),
                diff.ProbeError,
                "responseIndex=1",
            ),
        )
        for name, completed, error_type, response_index in cases:
            with self.subTest(name=name):
                with (
                    mock.patch.object(
                        diff, "generate_curated_episodes", return_value=[self.request]
                    ),
                    mock.patch.object(
                        diff, "generate_random_episodes", return_value=[]
                    ),
                    mock.patch.object(
                        diff,
                        "oracle_episode_response",
                        return_value=diff.oracle_episode_response(self.request),
                    ),
                    mock.patch.object(
                        diff, "_run_probe_process", return_value=completed
                    ),
                ):
                    with self.assertRaises(error_type) as caught:
                        diff.run_differential(
                            sys.executable,
                            seed="diagnostic-seed",
                            candidate_count=diff.MIN_RANDOM_CANDIDATE_COUNT,
                        )
                diagnostic = str(caught.exception)
                self.assertIn(response_index, diagnostic)
                self.assertIn(
                    f"manifest={diff.canonical_json(expected_manifest)}", diagnostic
                )
                self.assertIn(f"canonicalRequest={request_line}", diagnostic)
                self.assertIn(f"actionPrefix={action_prefix}", diagnostic)

        with (
            mock.patch.object(
                diff, "generate_curated_episodes", return_value=[self.request]
            ),
            mock.patch.object(diff, "generate_random_episodes", return_value=[]),
            mock.patch.object(
                diff,
                "oracle_episode_response",
                return_value=diff.oracle_episode_response(self.request),
            ),
            mock.patch.object(
                diff,
                "_run_probe_process",
                side_effect=diff.ProbeOutputDecodeError("stdout", 3, 0),
            ),
        ):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_differential(
                    sys.executable,
                    seed="diagnostic-seed",
                    candidate_count=diff.MIN_RANDOM_CANDIDATE_COUNT,
                )
        diagnostic = str(caught.exception)
        self.assertIn("stdout is not UTF-8", diagnostic)
        self.assertIn("responseIndex=0", diagnostic)
        self.assertIn(
            f"manifest={diff.canonical_json(expected_manifest)}", diagnostic
        )
        self.assertIn(f"canonicalRequest={request_line}", diagnostic)
        self.assertIn(f"actionPrefix={action_prefix}", diagnostic)

    def test_canonical_response_parser_rejects_noncanonical_and_duplicates(self) -> None:
        expected = diff.oracle_episode_response(self.request)
        line = diff.canonical_json(expected)
        self.assertEqual('{"del":"\x7f"}', diff.canonical_json({"del": "\x7f"}))
        self.assertEqual(
            expected,
            diff.parse_canonical_response_line(line, self.request),
        )

        noncanonical = json.dumps(expected, sort_keys=False)
        self.assertNotEqual(line, noncanonical)
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(noncanonical, self.request)

        duplicate = '{"episodeId":"protocol-unit","episodeId":"again"}'
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(duplicate, self.request)

        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line('{"value":1.5}', self.request)

        with mock.patch.object(diff, "MAX_RESPONSE_FRAME_BYTES", 16):
            with self.assertRaisesRegex(diff.ProtocolError, "16 MiB response limit"):
                diff.parse_canonical_response_line(line, self.request)

    def test_response_validation_rejects_unknown_and_malformed_nested_fields(self) -> None:
        response = diff.oracle_episode_response(self.request)

        unknown = deepcopy(response)
        unknown["observations"][0]["authoritative"] = True
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(unknown, self.request)

        bad_captures = deepcopy(response)
        bad_captures["observations"][0]["captures"]["black"] = "not-an-array"
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(bad_captures, self.request)

        bad_quota = deepcopy(response)
        bad_quota["observations"][0]["remainingQuotas"]["black"][
            "immortal"
        ] = True
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(bad_quota, self.request)

        bad_score = deepcopy(response)
        bad_score["observations"][0]["score"]["winner"] = "GREEN"
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(bad_score, self.request)

        bad_history = deepcopy(response)
        bad_history["observations"][0]["pskHistory"][0]["metadata"] = 1
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(bad_history, self.request)

        bad_status = deepcopy(response)
        bad_status["observations"][0]["status"] = ["ACCEPTED"]
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(bad_status, self.request)


class ComparatorTests(unittest.TestCase):
    def test_exact_comparator_finds_first_nested_field_and_type_mismatch(self) -> None:
        expected = {
            "observations": [
                {"captures": {"black": [1, 2], "white": []}, "A": 3}
            ]
        }
        reordered = deepcopy(expected)
        reordered["observations"][0]["captures"]["black"] = [2, 1]
        with self.assertRaisesRegex(
            diff.DifferentialMismatch,
            r"observations\[0\]\.captures\.black\[0\]",
        ):
            diff.compare_exact(expected, reordered, episode_id="compare-order")

        boolean = deepcopy(expected)
        boolean["observations"][0]["A"] = True
        with self.assertRaisesRegex(diff.DifferentialMismatch, "type int != bool"):
            diff.compare_exact(expected, boolean, episode_id="compare-type")

    def test_exact_comparator_accepts_identical_projection(self) -> None:
        value = diff.oracle_episode_response(
            diff.generate_curated_episodes()[0]
        )
        diff.compare_exact(value, deepcopy(value), episode_id="identical")

    def test_reproduction_context_contains_manifest_request_and_action_prefix(self) -> None:
        request = {
            "protocolVersion": diff.PROTOCOL_VERSION,
            "episodeId": "reproduction-unit",
            "boardSize": 9,
            "quotaMode": "ZERO",
            "steps": [
                {"candidateActor": "BLACK", "action": diff.action_v1(0)},
                {"candidateActor": "WHITE", "action": diff.action_v1(1)},
            ],
        }
        manifest = {
            "candidateCount": 2000,
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "seed": "custom-seed",
        }
        request_line = diff.canonical_json(request)
        context = diff._reproduction_context(manifest, request, request_line, 1)
        self.assertIn(diff.canonical_json(manifest), context)
        self.assertIn(f"canonicalRequest={request_line}", context)
        self.assertIn(
            f"actionPrefix={diff.canonical_json(request['steps'][:1])}", context
        )


@unittest.skipUnless(
    os.environ.get("MUTAGO_COLLAPSE_SLICE_PROBE"),
    "set MUTAGO_COLLAPSE_SLICE_PROBE to opt into executable integration",
)
class ExecutableIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = Path(os.environ["MUTAGO_COLLAPSE_SLICE_PROBE"])

    def test_probe_matches_pinned_legacy_summary_and_digest_deterministically(self) -> None:
        first = diff.run_differential(
            self.probe,
            seed=PINNED_LEGACY_SEED,
            candidate_count=PINNED_LEGACY_RANDOM_CANDIDATE_COUNT,
        )
        second = diff.run_differential(
            self.probe,
            seed=PINNED_LEGACY_SEED,
            candidate_count=PINNED_LEGACY_RANDOM_CANDIDATE_COUNT,
        )
        self.assertEqual(PINNED_LEGACY_SUMMARY, first)
        self.assertEqual(PINNED_LEGACY_SUMMARY, second)
        self.assertEqual(1600, first["randomCandidateCount"])
        self.assertEqual(1445, first["randomUniqueActionIds"])
        self.assertEqual(
            first["candidateCount"],
            first["accepted"] + first["rejected"] + first["unsupported"],
        )
        self.assertEqual([9, 13, 19], first["thresholdBoardSizes"])
        self.assertGreaterEqual(first["settlementReasonCounts"]["THRESHOLD"], 3)
        self.assertTrue(first["rehearsalOnly"])

    def test_probe_legacy_adapter_discards_capturing_double_transaction(self) -> None:
        request = _capturing_double_request()
        completed = diff._run_probe_process(
            [str(self.probe)], diff.canonical_json(request) + "\n", 5
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual("", completed.stderr)
        self.assertTrue(completed.stdout.endswith("\n"))
        actual = diff.parse_canonical_response_line(completed.stdout[:-1], request)
        expected = diff.oracle_episode_response(request)
        self.assertEqual(expected, actual)
        rejected = actual["observations"][-1]
        previous = actual["observations"][-2]
        self.assertEqual("UNSUPPORTED", rejected["status"])
        self.assertEqual({"black": [], "white": []}, rejected["captures"])
        self.assertEqual(previous["A"], rejected["A"])
        self.assertEqual(previous["blackOccupancy"], rejected["blackOccupancy"])
        self.assertEqual(previous["whiteOccupancy"], rejected["whiteOccupancy"])
        self.assertEqual(previous["remainingQuotas"], rejected["remainingQuotas"])

    def test_probe_keeps_immortal_psk_mechanics_legacy_unsupported(self) -> None:
        builder = diff._EpisodeBuilder.create("cpp-v0-immortal-psk", 9, "ONE")
        for actor, x, y in (
            (diff.Color.BLACK, 1, 2),
            (diff.Color.WHITE, 1, 1),
            (diff.Color.BLACK, 3, 2),
            (diff.Color.WHITE, 3, 1),
            (diff.Color.BLACK, 2, 3),
            (diff.Color.WHITE, 2, 0),
            (diff.Color.BLACK, 8, 8),
            (diff.Color.WHITE, 2, 2),
            (diff.Color.BLACK, 2, 1),
        ):
            builder.add(actor, diff.board_action_v1(9, x, y))
        builder.add(
            diff.Color.WHITE,
            diff.board_action_v1(9, 2, 2, diff.ActionKind.IMMORTAL),
        )
        request = builder.request()
        completed = diff._run_probe_process(
            [str(self.probe)], diff.canonical_json(request) + "\n", 5
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual("", completed.stderr)
        actual = diff.parse_canonical_response_line(completed.stdout[:-1], request)
        expected = diff.oracle_episode_response(request)
        self.assertEqual(expected, actual)
        self.assertEqual("UNSUPPORTED", actual["observations"][-1]["status"])

    def test_probe_maps_eightway_suicide_and_psk_to_legacy_unsupported(self) -> None:
        for request in _legacy_eightway_boundary_requests("cpp-v0"):
            completed = diff._run_probe_process(
                [str(self.probe)], diff.canonical_json(request) + "\n", 5
            )
            with self.subTest(episode=request["episodeId"]):
                self.assertEqual(0, completed.returncode)
                self.assertEqual("", completed.stderr)
                actual = diff.parse_canonical_response_line(completed.stdout[:-1], request)
                self.assertEqual(diff.oracle_episode_response(request), actual)
                previous, observation = actual["observations"][-2:]
                self.assertEqual("UNSUPPORTED", observation["status"])
                self.assertEqual(previous["pskHistory"], observation["pskHistory"])
                self.assertEqual(previous["blackOccupancy"], observation["blackOccupancy"])
                self.assertEqual(previous["whiteOccupancy"], observation["whiteOccupancy"])

    def test_probe_fails_closed_on_malformed_frame(self) -> None:
        completed = subprocess.run(
            [str(self.probe)],
            input='{"bad":true}\n',
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
        self.assertNotEqual(0, completed.returncode)
        self.assertEqual("", completed.stdout)
        self.assertIn("Malformed normal-pass differential frame", completed.stderr)

    def test_probe_enforces_frame_step_and_termination_bounds(self) -> None:
        over_limit = subprocess.run(
            [str(self.probe)],
            input=" " * (diff.MAX_REQUEST_FRAME_BYTES + 1) + "\n",
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
        self.assertNotEqual(0, over_limit.returncode)
        self.assertEqual("", over_limit.stdout)
        self.assertIn("exceeds the 1 MiB request limit", over_limit.stderr)

        unterminated_request = {
            "protocolVersion": diff.PROTOCOL_VERSION,
            "episodeId": "unterminated",
            "boardSize": 9,
            "quotaMode": "ZERO",
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(1444),
                }
            ],
        }
        unterminated = subprocess.run(
            [str(self.probe)],
            input=diff.canonical_json(unterminated_request),
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
        self.assertNotEqual(0, unterminated.returncode)
        self.assertEqual("", unterminated.stdout)
        self.assertIn("not newline-terminated", unterminated.stderr)

        too_many_steps = deepcopy(unterminated_request)
        too_many_steps["episodeId"] = "too-many-steps"
        too_many_steps["steps"] = too_many_steps["steps"] * (
            diff.MAX_EPISODE_STEPS + 1
        )
        step_limit = subprocess.run(
            [str(self.probe)],
            input=diff.canonical_json(too_many_steps) + "\n",
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=5,
        )
        self.assertNotEqual(0, step_limit.returncode)
        self.assertEqual("", step_limit.stdout)
        self.assertIn("resource limit", step_limit.stderr)


if __name__ == "__main__":
    unittest.main()
