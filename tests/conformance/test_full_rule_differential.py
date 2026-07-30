from __future__ import annotations

import copy
import hashlib
import inspect
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

CONFORMANCE_DIR = Path(__file__).resolve().parent
if str(CONFORMANCE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFORMANCE_DIR))

import full_rule_differential as diff  # noqa: E402


# Reviewed deterministic transcript for the bounded v4 default corpus.  This is
# independent of, and does not alter, any historical v0-v3 pin.
PINNED_FULL_RULE_DEFAULT_DIGEST: str | None = (
    "9df79d33e0e38593091d4ead82e1fac08d013f93c19d4c18f94e365eb6809596"
)


class LegalRangeCanonicalityTests(unittest.TestCase):
    def test_empty_full_and_sparse_masks_round_trip_maximally(self) -> None:
        cases = [
            [False] * diff.ACTION_COUNT,
            [True] * diff.ACTION_COUNT,
            [index in {0, 1, 3, 360, 361, 721, 1082, 1443, 1444}
             for index in range(diff.ACTION_COUNT)],
        ]
        for bits in cases:
            with self.subTest(true_count=sum(bits)):
                ranges = diff.compress_legal_bits(bits)
                self.assertEqual(tuple(bits), diff.validate_legal_action_ranges(ranges))
                self.assertEqual(ranges, diff.compress_legal_bits(tuple(bits)))
        self.assertEqual([], diff.compress_legal_bits([False] * diff.ACTION_COUNT))
        self.assertEqual(
            [{"first": 0, "last": 1444}],
            diff.compress_legal_bits([True] * diff.ACTION_COUNT),
        )

    def test_noncanonical_or_noninteger_ranges_fail_closed(self) -> None:
        invalid = (
            None,
            {},
            [{"first": False, "last": 0}],
            [{"first": 0, "last": True}],
            [{"first": -1, "last": 0}],
            [{"first": 0, "last": 1445}],
            [{"first": 2, "last": 1}],
            [{"first": 0, "last": 1}, {"first": 1, "last": 2}],
            [{"first": 4, "last": 4}, {"first": 2, "last": 2}],
            [{"first": 0, "last": 1}, {"first": 2, "last": 2}],
            [{"first": 0, "last": 1, "unknown": 2}],
            [{"first": 0}],
            [{"last": 0}],
            [{"first": 0.0, "last": 0}],
            [{"first": 0, "last": "0"}],
        )
        for ranges in invalid:
            with self.subTest(ranges=ranges), self.assertRaises(diff.ProtocolError):
                diff.validate_legal_action_ranges(ranges)

    def test_bit_vector_requires_exactly_1445_real_bools(self) -> None:
        with self.assertRaises(diff.ProtocolError):
            diff.compress_legal_bits([False] * (diff.ACTION_COUNT - 1))
        with self.assertRaises(diff.ProtocolError):
            diff.compress_legal_bits([False] * diff.ACTION_COUNT + [False])
        not_bool = [False] * diff.ACTION_COUNT
        not_bool[17] = 0
        with self.assertRaises(diff.ProtocolError):
            diff.compress_legal_bits(not_bool)


class V3AdapterAndProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = diff.load_contract_fixture()
        diff.validate_contract_fixture(cls.fixture)
        cls.request = diff.fixture_request(cls.fixture)
        cls.response = diff.oracle_episode_response(cls.request)

    def test_request_shape_is_exactly_v3_except_protocol_literal(self) -> None:
        v3_request = diff.v3.fixture_request(self.fixture)
        adapted = copy.deepcopy(self.request)
        self.assertEqual(diff.PROTOCOL_VERSION, adapted.pop("protocolVersion"))
        self.assertEqual(diff.v3.PROTOCOL_VERSION, v3_request.pop("protocolVersion"))
        self.assertEqual(v3_request, adapted)

        unknown = copy.deepcopy(self.request)
        unknown["unknown"] = None
        wrong = copy.deepcopy(self.request)
        wrong["protocolVersion"] = diff.v3.PROTOCOL_VERSION
        for mutation in (unknown, wrong):
            with self.assertRaises(diff.ProtocolError):
                diff.validate_episode_request(mutation)

    def test_response_adds_legality_only_to_stable_state_top_level(self) -> None:
        self.assertIn("legalActionRanges", self.response["initialState"])
        for observation in self.response["observations"]:
            self.assertIn("legalActionRanges", observation["state"])
            transition = observation["transition"]
            self.assertNotIn("legalActionRanges", transition)
            if transition["atomicSnapshot"] is not None:
                self.assertNotIn("legalActionRanges", transition["atomicSnapshot"])
            if transition["atomicEvent"] is not None:
                self.assertNotIn("legalActionRanges", transition["atomicEvent"])
            if transition["settlement"] is not None:
                self.assertNotIn("legalActionRanges", transition["settlement"])
                for step in transition["settlement"]["steps"]:
                    self.assertNotIn("legalActionRanges", step)
                    for batch in step["removalBatches"]:
                        self.assertNotIn("legalActionRanges", batch)
            if transition["terminalEvent"] is not None:
                self.assertNotIn("legalActionRanges", transition["terminalEvent"])

    def test_strict_adapter_strips_only_stable_legality_and_delegates_v3(self) -> None:
        stripped = diff._strip_legality_to_v3(
            self.response, self.request, label="unit response"
        )
        expected_v3 = diff.v3.oracle_episode_response(diff._to_v3_request(self.request))
        self.assertEqual(expected_v3, stripped)
        self.assertEqual(diff.v3.PROTOCOL_VERSION, stripped["protocolVersion"])
        self.assertEqual(diff.PROTOCOL_VERSION, self.response["protocolVersion"])
        with mock.patch.object(
            diff.v3,
            "validate_episode_response",
            wraps=diff.v3.validate_episode_response,
        ) as delegated:
            diff.validate_episode_response(self.response, self.request, self.response)
        delegated.assert_called_once()

        drift = copy.deepcopy(self.response)
        drift["observations"][4]["state"]["eightwayAnchors"] = []
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(drift, self.request, self.response)

    def test_missing_or_forbidden_legality_placement_fails_closed(self) -> None:
        missing = copy.deepcopy(self.response)
        del missing["observations"][0]["state"]["legalActionRanges"]
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(missing, self.request, self.response)

        surplus = copy.deepcopy(self.response)
        surplus["observations"].append({"state": {}})
        with self.assertRaisesRegex(diff.ProtocolError, "observation count differs"):
            diff.validate_episode_response(surplus, self.request, self.response)

        deep_unknown = copy.deepcopy(self.response)
        nested: object = None
        for _ in range(1500):
            nested = [nested]
        deep_unknown["initialState"]["unknown"] = nested
        with self.assertRaises(diff.ProtocolError):
            diff.validate_episode_response(deep_unknown, self.request, self.response)

        placements = []
        atomic = copy.deepcopy(self.response)
        atomic["observations"][0]["transition"]["atomicEvent"][
            "legalActionRanges"
        ] = []
        placements.append(atomic)

        snapshot = copy.deepcopy(self.response)
        snapshot["observations"][0]["transition"]["atomicSnapshot"][
            "legalActionRanges"
        ] = []
        placements.append(snapshot)

        settlement = copy.deepcopy(self.response)
        final_settlement = settlement["observations"][-1]["transition"]["settlement"]
        final_settlement["steps"][0]["legalActionRanges"] = []
        placements.append(settlement)

        removal = copy.deepcopy(self.response)
        batches = removal["observations"][-1]["transition"]["settlement"][
            "steps"
        ][0]["removalBatches"]
        self.assertTrue(batches)
        batches[0]["legalActionRanges"] = []
        placements.append(removal)

        for mutation in placements:
            with self.subTest(), self.assertRaises(diff.ProtocolError):
                diff.validate_episode_response(mutation, self.request, self.response)

    def test_terminal_event_and_pre_scoring_snapshot_forbid_legality(self) -> None:
        terminal_request = copy.deepcopy(self.request)
        terminal_request["episodeId"] = "full-rule-terminal-placement"
        terminal_request["steps"].extend(
            (
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                },
                {
                    "candidateActor": "WHITE",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                },
            )
        )
        terminal_response = diff.oracle_episode_response(terminal_request)
        final = terminal_response["observations"][-1]["transition"]
        self.assertIsNotNone(final["terminalEvent"])
        self.assertIsNotNone(final["atomicSnapshot"])
        for field in ("terminalEvent", "atomicSnapshot"):
            mutation = copy.deepcopy(terminal_response)
            mutation["observations"][-1]["transition"][field][
                "legalActionRanges"
            ] = []
            with self.subTest(field=field), self.assertRaises(diff.ProtocolError):
                diff.validate_episode_response(
                    mutation, terminal_request, terminal_response
                )

    def test_v3_globals_and_historical_fixture_digest_remain_unchanged(self) -> None:
        expected = (
            "eightway-diff-v3-unfrozen",
            "sha256-counter-eightway-v3-unfrozen",
            "mutago-eightway-increment-3",
            256,
            "c644dd9c6fb65cc3472f1f6764b168d4d0aaac5f8af37691a2cc7e5b90929182",
        )
        snapshot = (
            diff.v3.PROTOCOL_VERSION,
            diff.v3.GENERATOR_VERSION,
            diff.v3.DEFAULT_SEED,
            diff.v3.DEFAULT_CANDIDATE_COUNT,
            diff.v3.PINNED_FIXTURE_LEGAL_RANGES_SHA256,
        )
        self.assertEqual(expected, snapshot)
        diff.generate_curated_episodes(self.fixture)
        self.assertEqual(expected, (
            diff.v3.PROTOCOL_VERSION,
            diff.v3.GENERATOR_VERSION,
            diff.v3.DEFAULT_SEED,
            diff.v3.DEFAULT_CANDIDATE_COUNT,
            diff.v3.PINNED_FIXTURE_LEGAL_RANGES_SHA256,
        ))
        self.assertEqual(
            diff.PINNED_FIXTURE_LEGAL_RANGES_SHA256,
            diff._fixture_legal_ranges_digest(self.fixture),
        )

    def test_v4_corpus_is_an_explicit_protocol_adapter_over_v3_sequences(self) -> None:
        v3_curated = diff.v3.generate_curated_episodes(self.fixture)
        v4_curated = diff.generate_curated_episodes(self.fixture)
        self.assertEqual(len(v3_curated), len(v4_curated))
        for left, right in zip(v3_curated, v4_curated):
            left = copy.deepcopy(left)
            right = copy.deepcopy(right)
            self.assertEqual(diff.v3.PROTOCOL_VERSION, left.pop("protocolVersion"))
            self.assertEqual(diff.PROTOCOL_VERSION, right.pop("protocolVersion"))
            self.assertEqual(left, right)

        v3_random = diff.v3.generate_random_episodes(diff.DEFAULT_SEED, 64)
        v4_random = diff.generate_random_episodes(diff.DEFAULT_SEED, 64)
        self.assertEqual(
            [request["steps"] for request in v3_random],
            [request["steps"] for request in v4_random],
        )


class PythonLegalityIndependenceTests(unittest.TestCase):
    def test_every_stable_state_calls_both_legality_apis_without_action_sweep(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "python-legality-independence",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                },
                {
                    "candidateActor": "WHITE",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                },
            ],
        }
        stable_state_count = len(request["steps"]) + 1
        with (
            mock.patch.object(
                diff,
                "enumerate_action_legality",
                wraps=diff.enumerate_action_legality,
            ) as enumerate_mock,
            mock.patch.object(
                diff, "derive_legal_mask", wraps=diff.derive_legal_mask
            ) as mask_mock,
            mock.patch.object(
                diff.v3,
                "_apply_v3_adapter",
                wraps=diff.v3._apply_v3_adapter,
            ) as apply_mock,
            mock.patch.object(
                diff.hardened,
                "_run_probe_process",
                side_effect=AssertionError("Python expected values called C++"),
            ),
        ):
            response = diff.oracle_episode_response(request)
        self.assertEqual(stable_state_count, enumerate_mock.call_count)
        self.assertEqual(stable_state_count, mask_mock.call_count)
        self.assertEqual(len(request["steps"]), apply_mock.call_count)
        for _, _, ranges in diff._stable_legality_entries(response):
            self.assertEqual(1445, len(diff.validate_legal_action_ranges(ranges)))

    def test_disagreement_between_python_legality_apis_fails_at_first_bit(self) -> None:
        state = diff.v3.new_game(diff.v3._oracle_config(diff.quotas(), 9))
        good = diff.derive_legal_mask(state)
        broken = list(good)
        broken[73] = not broken[73]
        with mock.patch.object(diff, "derive_legal_mask", return_value=tuple(broken)):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.python_legal_action_ranges(state)
        self.assertIn("first differing actionId=73", str(caught.exception))

    def test_corpus_legality_disagreement_keeps_exact_genesis_context(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "python-legality-corpus-context",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                }
            ],
        }
        state = diff.v3.new_game(diff.v3._oracle_config(diff.quotas(), 9))
        broken = list(diff.derive_legal_mask(state))
        broken[73] = not broken[73]
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "python-legality-corpus-context",
        }
        with (
            mock.patch.object(diff, "load_contract_fixture", return_value={}),
            mock.patch.object(diff, "validate_contract_fixture"),
            mock.patch.object(
                diff, "generate_curated_episodes", return_value=[request]
            ),
            mock.patch.object(diff, "generate_random_episodes", return_value=[]),
            mock.patch.object(
                diff, "derive_legal_mask", return_value=tuple(broken)
            ),
            mock.patch.object(diff.hardened, "_run_probe_process") as supervisor,
        ):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.run_differential(
                    "unused-probe",
                    seed=manifest["seed"],
                    candidate_count=0,
                )
        supervisor.assert_not_called()
        message = str(caught.exception)
        for token in (
            "first differing actionId=73",
            f"manifest={diff.canonical_json(manifest)}",
            f"canonicalRequest={diff.canonical_json(request)}",
            "actionPrefix=[]",
        ):
            self.assertIn(token, message)

    def test_legality_projection_does_not_generate_expected_bits_by_applying_actions(self) -> None:
        source = inspect.getsource(diff.python_legal_action_ranges)
        self.assertNotIn("apply_action", source)
        self.assertNotIn("_apply_v3_adapter", source)
        self.assertIn("enumerate_action_legality", source)
        self.assertIn("derive_legal_mask", source)


class FullBitMismatchDiagnosticTests(unittest.TestCase):
    def test_first_differing_action_and_full_reproduction_context_precede_generic_compare(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "all-bit-diagnostic",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                }
            ],
        }
        expected = diff.oracle_episode_response(request)
        actual = copy.deepcopy(expected)
        bits = list(
            diff.validate_legal_action_ranges(
                actual["initialState"]["legalActionRanges"]
            )
        )
        bits[0] = not bits[0]
        actual["initialState"]["legalActionRanges"] = diff.compress_legal_bits(bits)
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "diagnostic-seed",
        }
        with mock.patch.object(
            diff.v3,
            "validate_episode_response",
            side_effect=AssertionError("generic v3 validation ran first"),
        ):
            with self.assertRaises(diff.DifferentialMismatch) as caught:
                diff.validate_episode_response(
                    actual,
                    request,
                    expected,
                    manifest=manifest,
                    request_line=diff.canonical_json(request),
                )
        message = str(caught.exception)
        for token in (
            "first differing actionId=0",
            "pythonExpected=",
            "cppActual=",
            "manifest=",
            "canonicalRequest=",
            "actionPrefix=[]",
            '"seed":"diagnostic-seed"',
        ):
            self.assertIn(token, message)

    def test_probe_mismatch_adds_response_index_without_losing_bit_context(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "probe-bit-diagnostic",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                }
            ],
        }
        expected = diff.oracle_episode_response(request)
        actual = copy.deepcopy(expected)
        bits = list(
            diff.validate_legal_action_ranges(
                actual["observations"][0]["state"]["legalActionRanges"]
            )
        )
        bits[1444] = not bits[1444]
        actual["observations"][0]["state"]["legalActionRanges"] = (
            diff.compress_legal_bits(bits)
        )
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "probe-diagnostic",
        }
        completed = types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=diff.canonical_json(actual) + "\n",
        )
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            with self.assertRaises(diff.DifferentialMismatch) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [request],
                    [expected],
                    manifest=manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        for token in (
            "first differing actionId=1444",
            "observations[0].state",
            "responseIndex=0",
            "completedResponseCount=0",
            "manifest=",
            "canonicalRequest=",
            "actionPrefix=",
        ):
            self.assertIn(token, message)
        self.assertEqual(1, message.count("manifest="))
        self.assertEqual(1, message.count("canonicalRequest="))
        self.assertEqual(1, message.count("actionPrefix="))

    def test_hostile_field_names_cannot_suppress_trusted_probe_context(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "hostile-context-field-names",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                }
            ],
        }
        expected = diff.oracle_episode_response(request)
        actual = copy.deepcopy(expected)
        actual["manifest="] = None
        actual["canonicalRequest="] = None
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "trusted-probe-context",
        }
        completed = types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=diff.canonical_json(actual) + "\n",
        )
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [request],
                    [expected],
                    manifest=manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        for token in (
            "responseIndex=0",
            "completedResponseCount=0",
            f"manifest={diff.canonical_json(manifest)}",
            f"canonicalRequest={diff.canonical_json(request)}",
            f"actionPrefix={diff.canonical_json(request['steps'])}",
        ):
            self.assertIn(token, message)

    def test_malformed_initial_ranges_keep_the_exact_empty_prefix(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "malformed-range-prefix",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                }
            ],
        }
        expected = diff.oracle_episode_response(request)
        actual = copy.deepcopy(expected)
        actual["initialState"]["legalActionRanges"] = [
            {"first": False, "last": 0}
        ]
        completed = types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=diff.canonical_json(actual) + "\n",
        )
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "malformed-range-prefix",
        }
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
                    [request],
                    [expected],
                    manifest=manifest,
                    deadline=diff.hardened._new_deadline(10),
                )
        message = str(caught.exception)
        self.assertIn("actual initialState.legalActionRanges", message)
        self.assertIn("actionPrefix=[]", message)
        self.assertIn("responseIndex=0", message)
        self.assertEqual(1, message.count("manifest="))
        self.assertEqual(1, message.count("canonicalRequest="))
        self.assertEqual(1, message.count("actionPrefix="))


class D4LegalityTests(unittest.TestCase):
    def test_all_families_use_full_canvas_pass_is_fixed_and_inverse_restores(self) -> None:
        source_ids = {
            0,
            18,
            19,
            180,
            360,
            361 + 2,
            361 + 359,
            722 + 40,
            1083 + 320,
            diff.PASS_ACTION_ID,
        }
        source = diff.compress_legal_bits(
            [action_id in source_ids for action_id in range(diff.ACTION_COUNT)]
        )
        source_bits = diff.validate_legal_action_ranges(source)
        no_pass = diff.compress_legal_bits(
            [action_id in source_ids - {diff.PASS_ACTION_ID}
             for action_id in range(diff.ACTION_COUNT)]
        )
        for symmetry in range(8):
            transformed = diff.transform_legal_action_ranges(source, symmetry)
            transformed_bits = diff.validate_legal_action_ranges(transformed)
            transformed_no_pass = diff.validate_legal_action_ranges(
                diff.transform_legal_action_ranges(no_pass, symmetry)
            )
            with self.subTest(symmetry=symmetry):
                self.assertTrue(transformed_bits[diff.PASS_ACTION_ID])
                self.assertFalse(transformed_no_pass[diff.PASS_ACTION_ID])
                self.assertEqual(
                    [], diff.transform_legal_action_ranges([], symmetry)
                )
                for action_id in source_ids - {diff.PASS_ACTION_ID}:
                    family, point = divmod(action_id, 361)
                    target = family * 361 + diff.transform_board_point(
                        19, point, symmetry
                    )
                    self.assertTrue(transformed_bits[target])
                inverse = diff.INVERSE_SYMMETRY_IDS[symmetry]
                restored = diff.transform_legal_action_ranges(
                    transformed, inverse
                )
                self.assertEqual(source_bits, diff.validate_legal_action_ranges(restored))

    def test_reexecution_matches_transformed_response_and_inverse(self) -> None:
        base_request = diff.eightway_immortal_split_request(9, "full-rule-d4-base")
        base = diff.oracle_episode_response(base_request)
        for symmetry in range(8):
            target_id = f"full-rule-d4-{symmetry}"
            transformed_request = diff.transform_request(
                base_request, symmetry, target_id
            )
            actual = diff.oracle_episode_response(transformed_request)
            expected = diff.transform_response(base, 9, symmetry, target_id)
            inverse = diff.INVERSE_SYMMETRY_IDS[symmetry]
            restored = diff.transform_response(actual, 9, inverse, base["episodeId"])
            with self.subTest(symmetry=symmetry):
                self.assertEqual(expected, actual)
                self.assertEqual(base, restored)


class FixtureBindingAndReexecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = diff.load_contract_fixture()
        diff.validate_contract_fixture(cls.fixture)
        cls.full_request = diff.fixture_request(cls.fixture)
        cls.full = diff.oracle_episode_response(cls.full_request)
        cls.reexecution_requests = diff.fixture_reexecution_requests(cls.fixture)
        cls.responses = {
            request["episodeId"]: diff.oracle_episode_response(request)
            for request in cls.reexecution_requests
        }

    def test_official_fixture_literals_bind_all_stable_runtime_masks(self) -> None:
        fixture_ranges = diff._fixture_ranges(self.fixture)
        response_ranges = [
            entry[2] for entry in diff._stable_legality_entries(self.full)
        ]
        self.assertEqual(len(fixture_ranges), len(response_ranges))
        for index, (literal, runtime) in enumerate(
            zip(fixture_ranges, response_ranges)
        ):
            with self.subTest(step=index):
                self.assertEqual(
                    diff.validate_legal_action_ranges(literal),
                    diff.validate_legal_action_ranges(runtime),
                )

    def test_fixture_transition_projection_still_matches_historical_v3_binding(self) -> None:
        stripped = diff._strip_legality_to_v3(
            self.full, self.full_request, label="fixture response"
        )
        diff.hardened.compare_exact(
            diff.v3.normalized_contract_fixture(self.fixture),
            diff.v3.strip_v3_response(stripped),
            episode_id="full-rule-v4-fixture-v3-binding",
        )

    def test_fixture_prefix_full_reexecution_and_suffix_are_immutable(self) -> None:
        self.assertEqual(
            self.full["observations"][:5],
            self.responses["fixture-eightway-placement-prefix"]["observations"],
        )
        self.assertEqual(
            self.full["observations"][:8],
            self.responses["fixture-eightway-mixed-protection-prefix"]["observations"],
        )
        self.assertEqual(
            self.full["observations"][:9],
            self.responses["fixture-eightway-pre-trigger-prefix"]["observations"],
        )
        reexecuted = copy.deepcopy(
            self.responses["fixture-eightway-full-reexecution"]
        )
        reexecuted["episodeId"] = self.full["episodeId"]
        self.assertEqual(self.full, reexecuted)
        self.assertEqual(
            self.full["observations"],
            self.responses["fixture-eightway-post-settlement-suffix"][
                "observations"
            ][:10],
        )


class ProtocolResourceAndDigestTests(unittest.TestCase):
    def test_v3_resource_limits_and_deadline_are_reused(self) -> None:
        self.assertEqual(diff.v3.MAX_REQUEST_FRAME_BYTES, diff.MAX_REQUEST_FRAME_BYTES)
        self.assertEqual(diff.v3.MAX_RESPONSE_FRAME_BYTES, diff.MAX_RESPONSE_FRAME_BYTES)
        self.assertEqual(diff.v3.MAX_PROBE_STDOUT_BYTES, diff.MAX_PROBE_STDOUT_BYTES)
        self.assertEqual(diff.v3.MAX_PROBE_STDERR_BYTES, diff.MAX_PROBE_STDERR_BYTES)
        self.assertEqual(diff.v3.MAX_EPISODE_STEPS, diff.MAX_EPISODE_STEPS)
        self.assertEqual(diff.v3.MAX_TEST_QUOTA, diff.MAX_TEST_QUOTA)
        self.assertEqual(diff.v3.PROBE_TIMEOUT_SECONDS, diff.PROBE_TIMEOUT_SECONDS)

        request = diff.eightway_immortal_split_request(9, "deadline-validation")
        expected = diff.oracle_episode_response(request)
        with self.assertRaises(diff.ProbeError):
            diff.validate_episode_response(
                expected, request, expected, deadline=0.0
            )

    def test_wide_unknown_container_obeys_the_absolute_deadline(self) -> None:
        request = diff.eightway_immortal_split_request(9, "wide-deadline")
        expected = diff.oracle_episode_response(request)
        actual = copy.deepcopy(expected)
        actual["initialState"]["unknown"] = [None] * 100_000
        with self.assertRaises(diff.ProbeError):
            diff.validate_episode_response(
                actual,
                request,
                expected,
                deadline=diff.hardened._new_deadline(0.001),
            )
        with self.assertRaises(diff.ProbeError):
            diff._strip_legality_to_v3(
                actual,
                request,
                label="wide strip response",
                deadline=diff.hardened._new_deadline(0.001),
            )

    def test_expected_count_fails_before_process_launch_with_context(self) -> None:
        request = diff.eightway_immortal_split_request(9, "expected-count")
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "expected-count",
        }
        with mock.patch.object(diff.hardened, "_run_probe_process") as supervisor:
            with self.assertRaises(diff.ProbeError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
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

    def test_preprobe_deadline_has_complete_available_context(self) -> None:
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

    def test_probe_adapter_preserves_v3_length_prefixed_digest_framing(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "digest-framing",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                }
            ],
        }
        expected = diff.oracle_episode_response(request)
        response_line = diff.canonical_json(expected)
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "digest-framing",
        }
        completed = types.SimpleNamespace(
            returncode=0, stderr="", stdout=response_line + "\n"
        )
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ) as supervisor:
            actual, digest = diff.run_probe_requests(
                diff.__file__,
                [request],
                [expected],
                manifest=manifest,
                deadline=diff.hardened._new_deadline(10),
            )
        self.assertEqual([expected], actual)
        payload = supervisor.call_args.args[1]
        self.assertEqual(diff.canonical_json(request) + "\n", payload)

        expected_digest = hashlib.sha256()
        diff.v3._digest_record(expected_digest, diff.canonical_json(manifest))
        diff.v3._digest_record(expected_digest, diff.canonical_json(request))
        diff.v3._digest_record(expected_digest, response_line)
        self.assertEqual(expected_digest.hexdigest(), digest)

    def test_deep_raw_response_fails_closed_with_reproduction_context(self) -> None:
        request = {
            "boardSize": 9,
            "episodeId": "deep-raw-response",
            "initialQuotas": diff.quotas(),
            "protocolVersion": diff.PROTOCOL_VERSION,
            "steps": [
                {
                    "candidateActor": "BLACK",
                    "action": diff.action_v1(diff.PASS_ACTION_ID),
                }
            ],
        }
        expected = diff.oracle_episode_response(request)
        canonical = diff.canonical_json(expected)
        deep_value = "[" * 1000 + "null" + "]" * 1000
        response_line = canonical[:-1] + ',"unknown":' + deep_value + "}"
        completed = types.SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=response_line + "\n",
        )
        manifest = {
            "generatorVersion": diff.GENERATOR_VERSION,
            "protocolVersion": diff.PROTOCOL_VERSION,
            "randomCandidateCount": 0,
            "seed": "deep-raw-response",
        }
        with mock.patch.object(
            diff.hardened, "_run_probe_process", return_value=completed
        ):
            with self.assertRaises(diff.ProtocolError) as caught:
                diff.run_probe_requests(
                    diff.__file__,
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

    def test_failure_context_includes_v4_manifest_request_and_prefix(self) -> None:
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
            diff.PROTOCOL_VERSION,
            "canonicalRequest=",
            "actionPrefix=",
        ):
            self.assertIn(token, context)


@unittest.skipUnless(
    os.environ.get("MUTAGO_COLLAPSE_FULL_RULE_PROBE"),
    "set MUTAGO_COLLAPSE_FULL_RULE_PROBE for executable integration",
)
class ExecutableIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.probe = Path(os.environ["MUTAGO_COLLAPSE_FULL_RULE_PROBE"]).resolve()

    @unittest.skipIf(
        PINNED_FULL_RULE_DEFAULT_DIGEST is None,
        "v4 executable transcript digest awaits an available reviewed probe",
    )
    def test_default_corpus_runs_twice_identically_with_pinned_digest(self) -> None:
        first = diff.run_differential(self.probe)
        second = diff.run_differential(self.probe)
        self.assertEqual(first, second)
        self.assertEqual(PINNED_FULL_RULE_DEFAULT_DIGEST, first["sha256"])
        self.assertEqual("FULL_RULE_DIFF_V4_UNFROZEN_TEST_ONLY", first["scope"])
        self.assertTrue(first["unfrozenTestOnly"])
        self.assertFalse(first["gateRule1MClaimed"])
        self.assertFalse(first["gateProdClaimed"])

    def test_official_fixture_matches_cpp_with_all_stable_masks(self) -> None:
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
                "seed": "official-full-rule-fixture",
            },
            deadline=diff.hardened._new_deadline(30),
        )
        self.assertEqual(expected, actual[0])
        self.assertEqual(
            len(request["steps"]) + 1,
            len(diff._stable_legality_entries(actual[0])),
        )

    def test_v4_cpp_parser_fails_closed_on_hostile_raw_frames(self) -> None:
        request = diff.eightway_immortal_split_request(9, "raw-v4")
        canonical = diff.canonical_json(request)

        unknown = copy.deepcopy(request)
        unknown["unknown"] = None
        wrong_version = copy.deepcopy(request)
        wrong_version["protocolVersion"] = "full-rule-diff-v4-unknown"
        redundant_coordinate = copy.deepcopy(request)
        redundant_coordinate["steps"][0]["action"]["x"] = 0
        unknown_quota = copy.deepcopy(request)
        unknown_quota["initialQuotas"]["BLACK"]["EXTRA"] = 0

        hostile = {
            "unknown-outer": (diff.canonical_json(unknown) + "\n").encode("ascii"),
            "wrong-version": (
                diff.canonical_json(wrong_version) + "\n"
            ).encode("ascii"),
            "redundant-coordinate": (
                diff.canonical_json(redundant_coordinate) + "\n"
            ).encode("ascii"),
            "unknown-quota": (
                diff.canonical_json(unknown_quota) + "\n"
            ).encode("ascii"),
            "duplicate-key": (
                canonical.replace(
                    '"episodeId":"raw-v4"',
                    '"episodeId":"raw-v4","episodeId":"again"',
                    1,
                )
                + "\n"
            ).encode("ascii"),
            "escaped-alias-key": (
                canonical.replace(
                    '"episodeId":"raw-v4"',
                    '"episodeId":"raw-v4","episode\\u0049d":"again"',
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
            "non-ascii": (canonical.replace("raw-v4", "é", 1) + "\n").encode(
                "utf-8"
            ),
            "malformed-utf8": canonical.replace("raw-v4", "raw-ÿ", 1).encode(
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
                self.assertTrue(
                    completed.stderr.startswith(b"mutago-collapse-slice-probe: ")
                )

    def test_probe_dispatches_a_mixed_v0_through_v4_stream(self) -> None:
        protocols = (
            "normal-pass-diff-v0-unfrozen",
            "double-move-diff-v1-unfrozen",
            "immortal-diff-v2-unfrozen",
            diff.v3.PROTOCOL_VERSION,
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
                        "action": diff.action_v1(diff.PASS_ACTION_ID),
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
                            "action": diff.action_v1(diff.PASS_ACTION_ID),
                            "candidateActor": "BLACK",
                        }
                    ],
                }
            )
        payload = "".join(
            diff.canonical_json(request) + "\n" for request in requests
        )
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
        self.assertEqual(5, len(lines))
        self.assertEqual(
            list(protocols),
            [
                diff.v3.parse_json_bytes(line.encode("ascii"))["protocolVersion"]
                for line in lines
            ],
        )


if __name__ == "__main__":
    unittest.main()
