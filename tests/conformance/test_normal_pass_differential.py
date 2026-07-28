from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

CONFORMANCE_DIR = Path(__file__).resolve().parent
if str(CONFORMANCE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFORMANCE_DIR))

import normal_pass_differential as diff  # noqa: E402


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

    def test_probe_matches_repeated_complete_corpus_deterministically(self) -> None:
        first = diff.run_differential(
            self.probe,
            seed="opt-in-integration",
            candidate_count=1600,
        )
        second = diff.run_differential(
            self.probe,
            seed="opt-in-integration",
            candidate_count=1600,
        )
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(first, second)
        self.assertEqual(1600, first["randomCandidateCount"])
        self.assertEqual(1445, first["randomUniqueActionIds"])
        self.assertEqual(
            first["candidateCount"],
            first["accepted"] + first["rejected"] + first["unsupported"],
        )
        self.assertEqual([9, 13, 19], first["thresholdBoardSizes"])
        self.assertGreaterEqual(first["settlementReasonCounts"]["THRESHOLD"], 3)
        self.assertTrue(first["rehearsalOnly"])

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
