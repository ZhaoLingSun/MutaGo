from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFORMANCE_DIR = Path(__file__).resolve().parent
for path in (REPO_ROOT, CONFORMANCE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import double_move_differential as diff  # noqa: E402
from tools.contract.contract import (  # noqa: E402
    DESCRIPTOR_PATH,
    ContractError,
    SchemaCatalog,
    _validate_fixture,
    load_json,
    validate_descriptor,
)

PINNED_DOUBLE_DEFAULT_DIGEST = (
    "644a4401cbc3adb7a09b787b84fb3ce54d60f6f63c8692a4e04192ab592eed15"
)


class ContractFixtureBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = diff.load_contract_fixture()
        cls.request = diff.fixture_request(cls.fixture)
        cls.normalized = diff.normalize_contract_fixture(cls.fixture)

    def test_checked_in_fixture_is_schema_and_semantic_invariant_valid(self) -> None:
        catalog = SchemaCatalog()
        digest = validate_descriptor(load_json(DESCRIPTOR_PATH), catalog)
        _validate_fixture(self.fixture, catalog, digest)

        # The frozen contract remains complete even though Increment 1 executes
        # only its Double-relevant normalized projection.
        for projection in (
            self.fixture["initialProjection"],
            *(step["expectedProjection"] for step in self.fixture["steps"]),
        ):
            self.assertIn("legalActionRanges", projection["derived"])
            self.assertIn("groups", projection["debug"])
        self.assertEqual(
            [{"first": 0, "last": 1444}],
            self.fixture["initialProjection"]["derived"]["legalActionRanges"],
        )

    def test_independent_python_execution_matches_literal_fixture_projection(self) -> None:
        actual = diff.oracle_episode_response(self.request)
        diff.compare_exact(
            self.normalized,
            actual,
            episode_id=self.fixture["fixtureId"],
        )
        self.assertEqual(3, len(actual["observations"]))

        start, continuation, settlement = actual["observations"]
        self.assertEqual("special-1", start["state"]["pendingDouble"]["eventId"])
        self.assertEqual("BLACK", start["state"]["actor"])
        self.assertIsNone(continuation["state"]["pendingDouble"])
        self.assertEqual("WHITE", continuation["state"]["actor"])
        self.assertEqual(
            "PRE_THRESHOLD_TWO_PASSES",
            settlement["transition"]["settlement"]["triggerReason"],
        )
        self.assertEqual(
            ["special-1"],
            [
                step["ledgerEventId"]
                for step in settlement["transition"]["settlement"]["steps"]
            ],
        )
        self.assertEqual([], settlement["transition"]["settlement"]["steps"][0]["removalBatches"])
        self.assertTrue(settlement["transition"]["settlement"]["steps"][0]["noOp"])

    def test_exact_event_counter_and_append_formulas_hold_for_fixture(self) -> None:
        states = [self.normalized["initialState"]] + [
            observation["state"] for observation in self.normalized["observations"]
        ]
        for state in states:
            atomic = state["atomicActionCount"]
            settled = state["settledLedgerCount"]
            terminal = state["stableTerminalEventCount"]
            self.assertEqual(atomic, state["revision"])
            self.assertEqual(atomic + settled + terminal, state["logPosition"])
            self.assertEqual(
                1 + atomic + settled + terminal,
                len(state["pskHistory"]),
            )

        final = states[-1]
        self.assertEqual(final["pskHistory"][1], final["pskHistory"][2])
        self.assertEqual(final["pskHistory"][2], final["pskHistory"][3])
        self.assertEqual(final["pskHistory"][3], final["pskHistory"][4])
        self.assertEqual("SETTLED", final["ledger"][0]["settlementState"])
        self.assertTrue(final["ledger"][0]["tombstone"])

    def test_contract_normalizer_rejects_fixture_drift(self) -> None:
        broken = copy.deepcopy(self.fixture)
        broken["steps"][-1]["expectedProjection"]["transition"]["settlement"]["steps"][0][
            "pskHistoryIndex"
        ] = 3
        with self.assertRaises((ContractError, diff.ProtocolError)):
            catalog = SchemaCatalog()
            digest = validate_descriptor(load_json(DESCRIPTOR_PATH), catalog)
            _validate_fixture(broken, catalog, digest)
            diff.normalize_contract_fixture(broken)
    def test_contract_normalizer_rejects_narrowed_derived_legal_ranges(self) -> None:
        broken = copy.deepcopy(self.fixture)
        broken["initialProjection"]["derived"]["legalActionRanges"][0]["last"] = 1443
        with self.assertRaisesRegex(diff.ProtocolError, "pinned contract binding"):
            diff.normalize_contract_fixture(broken)


class CoverageAndDeterministicReexecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.requests = diff.generate_curated_episodes()
        cls.responses = {
            request["episodeId"]: diff.oracle_episode_response(request)
            for request in cls.requests
        }

    def test_curated_corpus_covers_required_acceptance_and_rejections(self) -> None:
        statuses: set[str] = set()
        errors: set[str] = set()
        reasons: set[str] = set()
        kinds: set[str] = set()
        for request in self.requests:
            response = self.responses[request["episodeId"]]
            for observation in response["observations"]:
                transition = observation["transition"]
                statuses.add(transition["status"])
                errors.add(transition["errorCode"] or "NONE")
                kinds.add(transition["action"]["kind"])
                if transition["settlement"] is not None:
                    reasons.add(transition["settlement"]["triggerReason"])

        self.assertEqual({"ACCEPTED", "REJECTED", "UNSUPPORTED"}, statuses)
        self.assertTrue({"NORMAL", "PASS", "DOUBLE_START"}.issubset(kinds))
        self.assertTrue(
            {
                "WRONG_ACTOR",
                "DOUBLE_CONTINUATION_KIND_FORBIDDEN",
                "DOUBLE_THRESHOLD",
                "QUOTA_EXHAUSTED",
                "POINT_OCCUPIED",
                "SUICIDE",
                "POSITIONAL_SUPERKO",
                "INVALID_PHASE",
                "TERMINAL_STATE",
                "UNSUPPORTED_BY_SLICE",
            }.issubset(errors)
        )
        self.assertEqual({"THRESHOLD", "PRE_THRESHOLD_TWO_PASSES"}, reasons)

    def test_immortal_mechanical_psk_remains_legacy_unsupported_and_rolls_back(self) -> None:
        builder = diff.EpisodeBuilder.create("legacy-v1-immortal-psk", 9)
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
            transition = builder.add(actor, diff.board_action_v1(9, x, y))
            self.assertIsNotNone(transition)
            self.assertTrue(transition.accepted)
        before = builder.state
        self.assertIsNone(
            builder.add(
                diff.Color.WHITE,
                diff.board_action_v1(9, 2, 2, diff.ActionKind.IMMORTAL),
            )
        )
        self.assertIs(before, builder.state)
        response = diff.oracle_episode_response(builder.request())
        observation = response["observations"][-1]
        self.assertEqual("UNSUPPORTED", observation["transition"]["status"])
        self.assertEqual("UNSUPPORTED_BY_SLICE", observation["transition"]["errorCode"])
        self.assertEqual(response["observations"][-2]["state"], observation["state"])

    def test_captured_double_source_and_noop_settlement_remain_auditable(self) -> None:
        response = self.responses["curated-d4-capture-9-0"]
        capture = response["observations"][8]
        self.assertEqual([10], capture["transition"]["atomicEvent"]["captured"]["black"])
        self.assertEqual("CAPTURED", capture["state"]["ledger"][0]["stoneState"])
        self.assertEqual(0, capture["state"]["remainingQuotas"]["BLACK"]["DOUBLE_START"])
        self.assertEqual(1, capture["state"]["usedQuotas"]["BLACK"]["DOUBLE_START"])

        settlement = response["observations"][10]
        step = settlement["transition"]["settlement"]["steps"][0]
        self.assertEqual("special-1", step["ledgerEventId"])
        self.assertTrue(step["noOp"])
        self.assertFalse(step["abilityDeactivated"])
        self.assertEqual([], step["removalBatches"])
        self.assertEqual("SETTLED", settlement["state"]["ledger"][0]["settlementState"])

    def test_multiple_entries_pop_global_newest_to_oldest_and_keep_duplicates(self) -> None:
        response = self.responses["curated-multiple-double-ledger-9"]
        final = response["observations"][-1]
        self.assertEqual(
            ["special-8", "special-6", "special-3", "special-1"],
            [
                step["ledgerEventId"]
                for step in final["transition"]["settlement"]["steps"]
            ],
        )
        self.assertEqual(
            ["special-1", "special-3", "special-6", "special-8"],
            [entry["eventId"] for entry in final["state"]["ledger"]],
        )
        self.assertEqual(15, final["state"]["logPosition"])
        self.assertEqual(16, len(final["state"]["pskHistory"]))
        action_index = final["transition"]["atomicEvent"]["pskHistoryIndex"]
        suffix = final["state"]["pskHistory"][action_index:]
        self.assertEqual(5, len(suffix))
        self.assertTrue(all(item == suffix[0] for item in suffix))

    def test_threshold_boundary_accepts_t_minus_1_pair_and_rejects_too_late(self) -> None:
        legal = self.responses["curated-threshold-legal-9"]
        self.assertEqual(34, legal["observations"][-1]["state"]["atomicActionCount"])
        self.assertEqual(
            "THRESHOLD",
            legal["observations"][-1]["transition"]["settlement"]["triggerReason"],
        )
        self.assertEqual("ORDINARY_PLAY", legal["observations"][-1]["state"]["phase"])

        late = self.responses["curated-threshold-too-late-9"]
        self.assertEqual(
            "DOUBLE_THRESHOLD",
            late["observations"][-1]["transition"]["errorCode"],
        )
        self.assertEqual(33, late["observations"][-1]["state"]["atomicActionCount"])

    def test_deterministic_action_reexecution_and_prefixes_are_exact_at_pending_and_settlement(self) -> None:
        request = diff.fixture_request()
        first = diff.oracle_episode_transitions(request)
        second = diff.oracle_episode_transitions(copy.deepcopy(request))
        self.assertEqual(first, second)
        self.assertEqual(first[-1].settlement, second[-1].settlement)
        self.assertEqual(first[-1].settlement.steps, second[-1].settlement.steps)

        pending_prefix = copy.deepcopy(request)
        pending_prefix["episodeId"] = "fixture-pending-prefix"
        pending_prefix["steps"] = pending_prefix["steps"][:1]
        pending = diff.oracle_episode_transitions(pending_prefix)
        self.assertEqual(first[:1], pending)
        self.assertIsNotNone(pending[-1].state.pending_double)

        pre_settlement_prefix = copy.deepcopy(request)
        pre_settlement_prefix["episodeId"] = "fixture-pre-settlement-prefix"
        pre_settlement_prefix["steps"] = pre_settlement_prefix["steps"][:2]
        before_settlement = diff.oracle_episode_transitions(pre_settlement_prefix)
        self.assertEqual(first[:2], before_settlement)
        self.assertIsNone(before_settlement[-1].state.pending_double)

        post = copy.deepcopy(request)
        post["episodeId"] = "fixture-post-settlement-suffix"
        post["steps"].append(
            {
                "candidateActor": "BLACK",
                "action": diff.board_action_v1(19, 0, 0),
            }
        )
        post_first = diff.oracle_episode_transitions(post)
        post_second = diff.oracle_episode_transitions(copy.deepcopy(post))
        self.assertEqual(post_first, post_second)
        self.assertEqual(first, post_first[:3])
        self.assertEqual("ORDINARY_PLAY", post_first[2].state.phase.value)


class D4MetamorphicTests(unittest.TestCase):
    def test_actions_sources_transitions_and_inverse_round_trip_across_sizes(self) -> None:
        for board_size in (9, 13, 19):
            base_request = diff.capture_settlement_request(
                board_size, f"d4-unit-{board_size}-base"
            )
            base_response = diff.oracle_episode_response(base_request)
            for symmetry in range(8):
                with self.subTest(board_size=board_size, symmetry=symmetry):
                    transformed_request = diff.transform_request(
                        base_request,
                        symmetry,
                        f"d4-unit-{board_size}-{symmetry}",
                    )
                    transformed_response = diff.oracle_episode_response(
                        transformed_request
                    )
                    expected = diff.transform_response(
                        base_response,
                        board_size,
                        symmetry,
                        transformed_request["episodeId"],
                    )
                    diff.compare_exact(
                        expected,
                        transformed_response,
                        episode_id=transformed_request["episodeId"],
                    )

                    inverse = diff.INVERSE_SYMMETRY_IDS[symmetry]
                    restored = diff.transform_response(
                        transformed_response,
                        board_size,
                        inverse,
                        base_response["episodeId"],
                    )
                    diff.compare_exact(
                        base_response,
                        restored,
                        episode_id=f"d4-inverse-{board_size}-{symmetry}",
                    )
                    for original, transformed in zip(
                        base_request["steps"], transformed_request["steps"]
                    ):
                        restored_action = diff.transform_action(
                            transformed["action"], board_size, inverse
                        )
                        self.assertEqual(original["action"], restored_action)

                    capture = transformed_response["observations"][8]
                    self.assertTrue(
                        capture["transition"]["atomicEvent"]["captured"]["black"]
                    )
                    settlement = transformed_response["observations"][10]
                    self.assertEqual(
                        ["special-1"],
                        [
                            step["ledgerEventId"]
                            for step in settlement["transition"]["settlement"]["steps"]
                        ],
                    )
                    self.assertEqual(
                        settlement["transition"]["settlement"]["steps"][0][
                            "pskHistoryIndex"
                        ],
                        settlement["transition"]["atomicEvent"]["pskHistoryIndex"]
                        + 1,
                    )


class ProtocolAndResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = diff.fixture_request()

    def test_closed_request_response_and_checkout_pinning(self) -> None:
        self.assertEqual(str(diff.PYTHON_ROOT), sys.path[0])
        for module_name in (
            "mutago",
            "mutago.collapse_go",
            "mutago.collapse_go.normal_pass_oracle",
        ):
            module_path = Path(sys.modules[module_name].__file__).resolve()
            module_path.relative_to(diff.PYTHON_ROOT)

        unknown = copy.deepcopy(self.request)
        unknown["production"] = True
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_request(unknown)

        malformed_action = copy.deepcopy(self.request)
        malformed_action["steps"][0]["action"]["x"] = 9
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_request(malformed_action)

        bad_quota = copy.deepcopy(self.request)
        bad_quota["initialQuotas"]["BLACK"]["DOUBLE_START"] = 5
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_request(bad_quota)

    def test_frame_step_process_and_deadline_limits_are_explicit(self) -> None:
        too_many = copy.deepcopy(self.request)
        too_many["steps"] = too_many["steps"] * (diff.MAX_EPISODE_STEPS + 1)
        with self.assertRaisesRegex(diff.ProtocolError, "resource limit"):
            diff.validate_episode_request(too_many)

        with mock.patch.object(diff, "MAX_REQUEST_FRAME_BYTES", 32):
            with self.assertRaisesRegex(diff.ProtocolError, "1 MiB"):
                diff.validate_episode_request(self.request)

        with self.assertRaisesRegex(diff.ProbeError, "corpus deadline"):
            diff._run_probe_process(
                [sys.executable, "-c", "import time; time.sleep(1)"],
                "",
                diff._new_deadline(0.01),
            )

        for invalid_timeout in (float("inf"), float("nan"), 0.0, -1.0, True):
            with self.subTest(invalid_timeout=invalid_timeout):
                with self.assertRaises(ValueError):
                    diff._new_deadline(invalid_timeout)
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
                diff._new_deadline(5),
            )
        self.assertEqual("stdout", invalid_utf8.exception.stream_name)
        self.assertEqual(0, invalid_utf8.exception.response_index)

        with mock.patch.object(diff, "MAX_PROBE_STDOUT_BYTES", 32):
            with self.assertRaisesRegex(diff.ProbeError, "bounded process output"):
                diff._run_probe_process(
                    [
                        sys.executable,
                        "-c",
                        "import sys; sys.stdout.buffer.write(b'x' * 4096)",
                    ],
                    "",
                    diff._new_deadline(5),
                )

    def test_inherited_grandchild_pipes_are_bounded_by_timeout(self) -> None:
        script = (
            "import os,subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(5)']); "
            "os._exit(0)"
        )
        deadline = diff._new_deadline(0.2)
        started = time.perf_counter()
        with self.assertRaisesRegex(diff.ProbeError, "corpus deadline"):
            diff._run_probe_process([sys.executable, "-c", script], "", deadline)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.5)
        self.assertLess(time.monotonic(), deadline + 0.5)

    def test_probe_handoff_preserves_absolute_deadline_and_expiry_prevents_launch(self) -> None:
        absolute_deadline = 11.0
        completed = diff._ProbeProcessResult(
            0,
            diff.canonical_json(diff.oracle_episode_response(self.request)) + "\n",
            "",
        )
        with (
            mock.patch.object(diff.time, "monotonic", return_value=10.0),
            mock.patch.object(
                diff, "_run_probe_process", return_value=completed
            ) as supervisor,
        ):
            diff.run_probe_requests(
                sys.executable,
                [self.request],
                deadline=absolute_deadline,
            )
        self.assertEqual(absolute_deadline, supervisor.call_args.args[2])

        with (
            mock.patch.object(
                diff.time, "monotonic", side_effect=[10.0, 12.0]
            ),
            mock.patch.object(diff.subprocess, "Popen") as popen,
        ):
            with self.assertRaisesRegex(diff.ProbeError, "probe pre-launch"):
                diff._run_probe_process(
                    [sys.executable, "-c", "pass"],
                    "",
                    absolute_deadline,
                )
        popen.assert_not_called()

    def test_one_absolute_deadline_propagates_and_stops_non_probe_work(self) -> None:
        clock = [10.0]
        observed_deadlines: list[float] = []

        def phase(name: str, result):
            def run(*args, deadline=None, **kwargs):
                observed_deadlines.append(deadline)
                clock[0] += 0.2
                diff._check_deadline(deadline, name)
                return result

            return run

        with (
            mock.patch.object(diff.time, "monotonic", side_effect=lambda: clock[0]),
            mock.patch.object(diff, "load_contract_fixture", side_effect=phase("fixture", {})),
            mock.patch.object(diff, "validate_contract_fixture", side_effect=phase("schema", None)),
            mock.patch.object(diff, "generate_curated_episodes", side_effect=phase("curated", [])),
            mock.patch.object(
                diff,
                "generate_random_episodes",
                side_effect=phase("random", [self.request]),
            ),
            mock.patch.object(
                diff,
                "oracle_episode_response",
                side_effect=phase("Python oracle execution", {}),
            ),
        ):
            with self.assertRaisesRegex(
                diff.ProbeError, "Python oracle execution"
            ):
                diff.run_differential(
                    "/unused/probe",
                    candidate_count=diff.MIN_RANDOM_CANDIDATE_COUNT,
                    timeout_seconds=0.9,
                )
        self.assertTrue(observed_deadlines)
        self.assertEqual({10.9}, set(observed_deadlines))

    def test_exact_comparison_and_d4_fail_closed_after_deadline(self) -> None:
        with mock.patch.object(
            diff.time, "monotonic", side_effect=[0.0, 0.0, 2.0]
        ):
            with self.assertRaisesRegex(diff.ProbeError, "exact response comparison"):
                diff.compare_exact(
                    {"nested": [1]},
                    {"nested": [1]},
                    episode_id="deadline-compare",
                    deadline=1.0,
                )

        response = diff.oracle_episode_response(self.request)
        with mock.patch.object(diff.time, "monotonic", side_effect=[0.0, 2.0]):
            with self.assertRaisesRegex(diff.ProbeError, "D4 response transformation"):
                diff.transform_response(
                    response,
                    self.request["boardSize"],
                    0,
                    "deadline-d4",
                    deadline=1.0,
                )

    def test_strict_fixture_loader_rejects_hostile_json_profile_inputs(self) -> None:
        invalid_payloads = {
            "duplicate": b'{"fixtureId":"a","fixtureId":"b"}',
            "escaped-alias": b'{"fixtureId":"a","fixture\\u0049d":"b"}',
            "float": b'{"value":1.0}',
            "non-finite": b'{"value":NaN}',
            "unsafe-integer": b'{"value":9007199254740992}',
            "non-ascii-string": '{"value":"é"}'.encode("utf-8"),
            "escaped-non-ascii-string": b'{"value":"\\u00e9"}',
            "surrogate-string": b'{"value":"\\ud800"}',
            "non-ascii-key": '{"é":1}'.encode("utf-8"),
            "escaped-non-ascii-key": b'{"\\u00e9":1}',
            "malformed-utf8": b'{"value":"\xff"}',
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            for name, payload in invalid_payloads.items():
                with self.subTest(name=name):
                    path.write_bytes(payload)
                    with self.assertRaises(ContractError):
                        diff.load_contract_fixture(path)

    def test_malformed_response_diagnostics_include_reproduction_context(self) -> None:
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 64,
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
                with mock.patch.object(
                    diff, "_run_probe_process", return_value=completed
                ):
                    with self.assertRaises(error_type) as caught:
                        diff.run_probe_requests(
                            sys.executable,
                            [self.request],
                            manifest=manifest,
                        )
                diagnostic = str(caught.exception)
                self.assertIn(response_index, diagnostic)
                self.assertIn(
                    f"manifest={diff.canonical_json(manifest)}", diagnostic
                )
                self.assertIn(f"canonicalRequest={request_line}", diagnostic)
                self.assertIn(f"actionPrefix={action_prefix}", diagnostic)

        with mock.patch.object(
            diff,
            "_run_probe_process",
            side_effect=diff.ProbeOutputDecodeError("stdout", 3, 0),
        ):
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    sys.executable,
                    [self.request],
                    manifest=manifest,
                )
        diagnostic = str(caught.exception)
        self.assertIn("stdout is not UTF-8", diagnostic)
        self.assertIn("responseIndex=0", diagnostic)
        self.assertIn(f"manifest={diff.canonical_json(manifest)}", diagnostic)
        self.assertIn(f"canonicalRequest={request_line}", diagnostic)
        self.assertIn(f"actionPrefix={action_prefix}", diagnostic)

    def test_canonical_parser_rejects_unknown_noncanonical_and_duplicate_data(self) -> None:
        expected = diff.oracle_episode_response(self.request)
        line = diff.canonical_json(expected)
        self.assertEqual(
            expected,
            diff.parse_canonical_response_line(line, self.request),
        )

        noncanonical = json.dumps(expected, sort_keys=False)
        self.assertNotEqual(line, noncanonical)
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(noncanonical, self.request)

        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                '{"episodeId":"a","episodeId":"b"}', self.request
            )

        unknown = copy.deepcopy(expected)
        unknown["observations"][0]["state"]["productionRevision"] = 1
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(diff.canonical_json(unknown), self.request)

    def test_closed_rejection_classification_rejects_all_contradictions(self) -> None:
        rejected_request = copy.deepcopy(self.request)
        rejected_request["episodeId"] = "closed-rejection-validation"
        rejected_request["steps"][0]["candidateActor"] = "WHITE"
        rejected_response = diff.oracle_episode_response(rejected_request)
        transition = rejected_response["observations"][0]["transition"]
        self.assertEqual("REJECTED", transition["status"])
        self.assertEqual("REJECTED", transition["transitionKind"])
        self.assertEqual("WRONG_ACTOR", transition["errorCode"])

        mutations = {
            "accepted-status": {"status": "ACCEPTED"},
            "accepted-boolean": {"accepted": True},
            "unknown-code": {"errorCode": "FUTURE_REJECTION"},
            "unsupported-as-rejection": {"errorCode": "UNSUPPORTED_BY_SLICE"},
            "unsupported-status-with-rejection": {"status": "UNSUPPORTED"},
            "unsupported-kind-with-rejection": {"transitionKind": "UNSUPPORTED"},
        }
        for name, changes in mutations.items():
            with self.subTest(name=name):
                broken = copy.deepcopy(rejected_response)
                broken["observations"][0]["transition"].update(changes)
                with self.assertRaises(diff.ProtocolError):
                    diff.parse_canonical_response_line(
                        diff.canonical_json(broken), rejected_request
                    )

    def test_nested_terminal_ledger_and_group_adapter_drift_is_rejected(self) -> None:
        terminal_request = diff.capture_settlement_request(9, "nested-terminal-validation")
        terminal_response = diff.oracle_episode_response(terminal_request)
        broken_terminal = copy.deepcopy(terminal_response)
        broken_terminal["observations"][-1]["state"]["terminal"] = {"ended": True}
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(broken_terminal), terminal_request
            )

        broken_margin = copy.deepcopy(terminal_response)
        broken_margin["observations"][-1]["state"]["terminal"]["score"]["margin"][
            "numerator"
        ] += 2
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(broken_margin), terminal_request
            )

        broken_quota_lifecycle = copy.deepcopy(terminal_response)
        post_settlement_state = broken_quota_lifecycle["observations"][10]["state"]
        post_settlement_state["remainingQuotas"]["BLACK"]["IMMORTAL"] = 1
        post_settlement_state["expiredQuotas"]["BLACK"]["IMMORTAL"] = 0
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(broken_quota_lifecycle), terminal_request
            )

        fixture_response = diff.oracle_episode_response(self.request)
        broken_ledger = copy.deepcopy(fixture_response)
        broken_ledger["observations"][0]["state"]["ledger"][0]["sourcePoint"] = 181
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(broken_ledger), self.request
            )

        broken_groups = copy.deepcopy(fixture_response)
        broken_groups["observations"][0]["state"]["groups"][0]["liberties"].pop()
        with self.assertRaises(diff.ProtocolError):
            diff.parse_canonical_response_line(
                diff.canonical_json(broken_groups), self.request
            )

    def test_seeded_random_corpus_is_exact_and_deterministic(self) -> None:
        first = diff.generate_random_episodes("deterministic", 128)
        second = diff.generate_random_episodes("deterministic", 128)
        self.assertEqual(first, second)
        self.assertEqual(128, sum(len(request["steps"]) for request in first))
        self.assertTrue(all(len(request["steps"]) <= 32 for request in first))
        self.assertEqual(
            hashlib.sha256(
                diff.Sha256CounterRng._DOMAIN
                + len(b"seed").to_bytes(8, "big")
                + b"seed"
                + (0).to_bytes(16, "big")
            ).digest(),
            diff.Sha256CounterRng("seed").bytes(32),
        )


@unittest.skipUnless(
    os.environ.get("MUTAGO_COLLAPSE_SLICE_PROBE"),
    "set MUTAGO_COLLAPSE_SLICE_PROBE to opt into executable integration",
)
class ExecutableIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = Path(os.environ["MUTAGO_COLLAPSE_SLICE_PROBE"])

    def test_contract_fixture_executes_in_cpp_and_matches_normalized_contract(self) -> None:
        request = diff.fixture_request()
        responses, _ = diff.run_probe_requests(self.probe, [request])
        expected = diff.normalize_contract_fixture()
        diff.compare_exact(expected, responses[0], episode_id=request["episodeId"])

    def test_cpp_keeps_immortal_psk_mechanics_legacy_unsupported(self) -> None:
        builder = diff.EpisodeBuilder.create("cpp-v1-immortal-psk", 9)
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
        expected = diff.oracle_episode_response(request)
        responses, _ = diff.run_probe_requests(self.probe, [request])
        diff.compare_exact(expected, responses[0], episode_id=request["episodeId"])
        self.assertEqual(
            "UNSUPPORTED", responses[0]["observations"][-1]["transition"]["status"]
        )

    def test_cpp_action_reexecution_and_prefixes_are_immutable_at_pending_and_settlement_boundaries(self) -> None:
        full = diff.fixture_request()
        pending = copy.deepcopy(full)
        pending["episodeId"] = "cpp-pending-prefix"
        pending["steps"] = pending["steps"][:1]
        before_settlement = copy.deepcopy(full)
        before_settlement["episodeId"] = "cpp-before-settlement-prefix"
        before_settlement["steps"] = before_settlement["steps"][:2]
        reexecution = copy.deepcopy(full)
        reexecution["episodeId"] = "cpp-full-action-reexecution"

        responses, _ = diff.run_probe_requests(
            self.probe, [pending, before_settlement, full, reexecution]
        )
        pending_response, before_response, full_response, reexecution_response = responses
        self.assertEqual(
            pending_response["observations"], full_response["observations"][:1]
        )
        self.assertEqual(
            before_response["observations"], full_response["observations"][:2]
        )
        comparable = copy.deepcopy(reexecution_response)
        comparable["episodeId"] = full_response["episodeId"]
        self.assertEqual(full_response, comparable)

    def test_bounded_differential_repeats_with_matching_digest(self) -> None:
        first = diff.run_differential(self.probe)
        second = diff.run_differential(self.probe)
        self.assertEqual(first, second)
        self.assertEqual(PINNED_DOUBLE_DEFAULT_DIGEST, first["sha256"])
        self.assertEqual(996, first["candidateCount"])
        self.assertEqual(484, first["curatedCandidateCount"])
        self.assertEqual(512, first["randomCandidateCount"])
        self.assertFalse(first["gateRule1MClaimed"])
        self.assertTrue(first["contractFixtureValidated"])
        self.assertTrue(first["fixtureNormalized"])
        self.assertTrue(first["d4Metamorphic"])
        self.assertTrue(first["deterministicActionReexecutionAndPrefixesExact"])
        self.assertEqual("DOUBLE_INCREMENT_1_UNFROZEN_TEST_ONLY", first["scope"])
        self.assertGreater(first["accepted"], 0)
        self.assertGreater(first["rejected"], 0)
        self.assertGreater(first["unsupported"], 0)

    def test_new_mode_fails_closed_without_partial_output(self) -> None:
        malformed = copy.deepcopy(diff.fixture_request())
        malformed["unknown"] = None
        completed = subprocess.run(
            [str(self.probe)],
            input=diff.canonical_json(malformed) + "\n",
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


if __name__ == "__main__":
    unittest.main()
