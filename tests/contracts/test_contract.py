from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.contract.contract import (
    BOARD_OFFSETS,
    CANONICALIZATION_PROFILE,
    DESCRIPTOR_PATH,
    EXAMPLE_DIR,
    PASS_ACTION_ID,
    PUBLIC_RULESET_ID,
    PUBLIC_SEMANTIC_VERSION,
    SAFE_INTEGER_MAX,
    SAFE_INTEGER_MIN,
    SCHEMA_DIR,
    VECTOR_DIR,
    ContractError,
    SchemaCatalog,
    _contract_mixed_groups,
    _occupancy_sets,
    _validate_fixture,
    _validate_mismatch_bundle,
    _validate_mismatch_reproduction_segment,
    _validate_mismatch_result_projection,
    _validate_projection,
    _validate_projection_from_previous,
    _validate_projection_with_predecessor,
    _validate_settlement_closure,
    action_canvas_coordinates,
    canonicalize_json_bytes,
    decode_action,
    decode_action_for_board,
    descriptor_digest,
    encode_canvas_action,
    encode_semantic_action,
    inverse_symmetry_id,
    load_json,
    parse_json_bytes,
    resolve_json_pointer,
    run_check,
    sha256_hex,
    transform_action,
    validate_action_semantics,
    validate_descriptor,
    verify_action_vectors,
    verify_canonicalization_vectors,
)

EXPECTED_PUBLIC_HASH = "a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899"
KINDS = ("NORMAL", "IMMORTAL", "DOUBLE_START", "EIGHTWAY")
KIND_CODES = {kind: index for index, kind in enumerate(KINDS)}


class StrictJsonProfileTests(unittest.TestCase):
    def assert_contract_error(self, code: str, raw: bytes) -> None:
        with self.assertRaises(ContractError) as caught:
            canonicalize_json_bytes(raw)
        self.assertEqual(code, caught.exception.code)

    def test_duplicate_keys_include_escaped_aliases(self) -> None:
        self.assert_contract_error("duplicate-key", b'{"a":1,"a":2}')
        self.assert_contract_error("duplicate-key", b'{"a":{"b":1,"b":2}}')
        self.assert_contract_error("duplicate-key", b'{"a":1,"\\u0061":2}')

    def test_floats_non_ascii_surrogates_and_unsafe_integers_are_rejected(self) -> None:
        self.assert_contract_error("floating-point", b'{"a":1.0}')
        self.assert_contract_error("floating-point", b'{"a":1e0}')
        self.assert_contract_error("non-ascii-string", b'{"a":"\xc3\xa9"}')
        self.assert_contract_error("non-ascii-key", b'{"\xc3\xa9":1}')
        self.assert_contract_error("non-ascii-string", b'{"a":"\\u00e9"}')
        self.assert_contract_error("non-ascii-key", b'{"\\u00e9":1}')
        self.assert_contract_error("non-ascii-string", b'{"a":"\\ud800"}')
        self.assert_contract_error("unsafe-integer", b'{"a":9007199254740992}')
        self.assert_contract_error("unsafe-integer", b'{"a":-9007199254740992}')
        self.assert_contract_error("unsafe-integer", b'{"a":' + b"9" * 5000 + b"}")
        deep = b"[" * 257 + b"0" + b"]" * 257
        self.assertEqual(deep, canonicalize_json_bytes(deep))

    def test_safe_integer_boundaries_and_canonical_order(self) -> None:
        raw = (
            b'{"z":null,"max":9007199254740991,'
            b'"min":-9007199254740991,"a":{"b":2,"a":1}}'
        )
        expected = (
            b'{"a":{"a":1,"b":2},"max":9007199254740991,'
            b'"min":-9007199254740991,"z":null}'
        )
        self.assertEqual(expected, canonicalize_json_bytes(raw))
        self.assertEqual(SAFE_INTEGER_MIN, parse_json_bytes(str(SAFE_INTEGER_MIN).encode()))
        self.assertEqual(SAFE_INTEGER_MAX, parse_json_bytes(str(SAFE_INTEGER_MAX).encode()))

    def test_escape_normalization_controls_del_and_negative_zero(self) -> None:
        self.assertEqual(b'{"n":0}', canonicalize_json_bytes(b'{"n":-0}'))
        self.assertEqual(
            b'{"slash":"/","unicodeEscape":"A"}',
            canonicalize_json_bytes(b'{"unicodeEscape":"\\u0041","slash":"\\/"}'),
        )
        self.assertEqual(
            b'{"del":"\x7f","nul":"\\u0000","unitSeparator":"\\u001f"}',
            canonicalize_json_bytes(b'{"nul":"\\u0000","unitSeparator":"\\u001f","del":"\x7f"}'),
        )

    def test_canonicalize_cli_stdout_is_exact_jcs_bytes_without_newline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "input.json"
            path.write_bytes(b'{"z":-0,"a":1}')
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "contract" / "contract.py"),
                    "canonicalize",
                    str(path),
                ],
                check=True,
                capture_output=True,
            )
        self.assertEqual(b'{"a":1,"z":0}', completed.stdout)
        self.assertEqual(b"", completed.stderr)


class ActionCodecTests(unittest.TestCase):
    def test_all_1445_ids_match_direct_formula_and_round_trip(self) -> None:
        catalog = SchemaCatalog()
        seen = set()
        for action_id in range(1445):
            action = decode_action(action_id)
            validate_action_semantics(action, catalog)
            seen.add(action["actionId"])
            self.assertEqual({"schemaVersion", "actionId", "kind"}, set(action))
            if action["kind"] == "PASS":
                self.assertEqual(PASS_ACTION_ID, action_id)
                self.assertEqual((None, None), action_canvas_coordinates(action))
            else:
                x, y = action_canvas_coordinates(action)
                self.assertIsNotNone(x)
                self.assertIsNotNone(y)
                expected_id = 361 * KIND_CODES[action["kind"]] + 19 * y + x
                self.assertEqual(action_id, expected_id)
                self.assertEqual(action, encode_canvas_action(action["kind"], x, y))
        self.assertEqual(set(range(1445)), seen)

    def test_all_actions_round_trip_through_all_d4_symmetries(self) -> None:
        for action_id in range(1445):
            action = decode_action(action_id)
            for symmetry_id in range(8):
                transformed = transform_action(action, symmetry_id)
                self.assertEqual(action["kind"], transformed["kind"])
                if action["kind"] != "PASS":
                    expected_x, expected_y = action_canvas_coordinates(action)
                    if symmetry_id & 2:
                        expected_x = 18 - expected_x
                    if symmetry_id & 1:
                        expected_y = 18 - expected_y
                    if symmetry_id & 4:
                        expected_x, expected_y = expected_y, expected_x
                    self.assertEqual((expected_x, expected_y), action_canvas_coordinates(transformed))
                self.assertEqual(action, transform_action(transformed, inverse_symmetry_id(symmetry_id)))
                if action_id == PASS_ACTION_ID:
                    self.assertEqual(PASS_ACTION_ID, transformed["actionId"])

    def test_invalid_symmetry_fails_closed_for_pass_and_point_actions(self) -> None:
        for action in (decode_action(0), decode_action(PASS_ACTION_ID)):
            for invalid in (-1, 8, 1.5, "bad", True):
                with self.assertRaises(ContractError) as caught:
                    transform_action(action, invalid)
                self.assertIn(caught.exception.code, {"invalid-integer", "invalid-symmetry"})

    def test_centered_9_13_19_mappings_and_d4_footprints_round_trip(self) -> None:
        for board_size, offset in BOARD_OFFSETS.items():
            self.assertEqual((19 - board_size) // 2, offset)
            for y in range(board_size):
                for x in range(board_size):
                    for kind in KINDS:
                        action = encode_semantic_action(kind, board_size, x, y)
                        expected_canvas_x = x + offset
                        expected_canvas_y = y + offset
                        expected_id = 361 * KIND_CODES[kind] + 19 * expected_canvas_y + expected_canvas_x
                        self.assertEqual(expected_id, action["actionId"])
                        decoded, semantic_x, semantic_y = decode_action_for_board(action["actionId"], board_size)
                        self.assertEqual(action, decoded)
                        self.assertEqual((x, y), (semantic_x, semantic_y))
                        for symmetry_id in range(8):
                            transformed = transform_action(action, symmetry_id)
                            _, transformed_x, transformed_y = decode_action_for_board(transformed["actionId"], board_size)
                            self.assertTrue(0 <= transformed_x < board_size)
                            self.assertTrue(0 <= transformed_y < board_size)

    def test_centered_footprint_rejects_off_board_canvas_actions(self) -> None:
        for board_size in (9, 13):
            offset = BOARD_OFFSETS[board_size]
            outside_points = (
                (offset - 1, offset),
                (offset + board_size, offset),
                (offset, offset - 1),
                (offset, offset + board_size),
            )
            for x, y in outside_points:
                action = encode_canvas_action("NORMAL", x, y)
                with self.assertRaises(ContractError) as caught:
                    decode_action_for_board(action["actionId"], board_size)
                self.assertEqual("point-off-board", caught.exception.code)

    def test_schema_and_semantic_checker_reject_kind_mismatch_and_redundant_coordinates(self) -> None:
        catalog = SchemaCatalog()
        for malformed in (
            {"schemaVersion": "action-v1", "actionId": 1, "kind": "EIGHTWAY"},
            {"schemaVersion": "action-v1", "actionId": 1, "kind": "NORMAL", "canvasX": 1},
        ):
            with self.assertRaises(ContractError):
                validate_action_semantics(malformed, catalog)


class SchemaAndDescriptorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = SchemaCatalog()
        cls.descriptor = load_json(DESCRIPTOR_PATH)
        cls.digest = validate_descriptor(cls.descriptor, cls.catalog)

    def test_all_local_schema_references_resolve_with_exact_dialect_and_ids(self) -> None:
        self.assertEqual(
            {
                "action-v1",
                "ruleset-descriptor-v1",
                "semantic-projection-v1",
                "conformance-fixture-v1",
                "mismatch-bundle-v1",
            },
            set(self.catalog.schemas),
        )
        for schema_name, schema in self.catalog.schemas.items():
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
            self.assertEqual(self.catalog.paths[schema_name].name, schema["$id"])

    def test_schema_catalog_rejects_wrong_dialect_remote_refs_and_dynamic_refs(self) -> None:
        mutations = (
            ("$schema", "https://json-schema.org/draft-07/schema#"),
            ("$ref", "https://example.invalid/external.schema.json"),
            ("$dynamicRef", "#node"),
        )
        for key, value in mutations:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp_dir:
                temp_schema_dir = Path(temp_dir) / "source"
                shutil.copytree(SCHEMA_DIR, temp_schema_dir)
                action_path = temp_schema_dir / "action-v1.schema.json"
                action_schema = json.loads(action_path.read_text(encoding="utf-8"))
                if key == "$schema":
                    action_schema[key] = value
                else:
                    action_schema["allOf"] = [{key: value}]
                action_path.write_text(json.dumps(action_schema, indent=2) + "\n", encoding="utf-8")
                with self.assertRaises(ContractError):
                    SchemaCatalog(temp_schema_dir)

    def test_schema_catalog_rejects_source_symlink_escape_and_scalar_ref_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            temp_schema_dir = temp_root / "source"
            shutil.copytree(SCHEMA_DIR, temp_schema_dir)
            action_path = temp_schema_dir / "action-v1.schema.json"
            external_dir = temp_root / "external"
            external_dir.mkdir()
            external_path = external_dir / "action-v1.schema.json"
            external_path.write_bytes(action_path.read_bytes())
            action_path.unlink()
            action_path.symlink_to(external_path)
            with self.assertRaises(ContractError) as caught:
                SchemaCatalog(temp_schema_dir)
            self.assertEqual("schema-source-escape", caught.exception.code)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_schema_dir = Path(temp_dir) / "source"
            shutil.copytree(SCHEMA_DIR, temp_schema_dir)
            action_path = temp_schema_dir / "action-v1.schema.json"
            action_schema = json.loads(action_path.read_text(encoding="utf-8"))
            action_schema["allOf"] = [{"$ref": "#/$id"}]
            action_path.write_text(json.dumps(action_schema, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(ContractError) as caught:
                SchemaCatalog(temp_schema_dir)
            self.assertEqual("invalid-schema-ref", caught.exception.code)

    def test_schema_conditionals_bind_threshold_phase_provenance_and_minimization(self) -> None:
        fixture = load_json(EXAMPLE_DIR / "conformance-fixture-v1.example.json")
        fixture["configuration"]["threshold"] = 70
        with self.assertRaises(ContractError) as caught:
            self.catalog.validate("conformance-fixture-v1", fixture)
        self.assertEqual("schema-validation", caught.exception.code)

        fixture = load_json(EXAMPLE_DIR / "conformance-fixture-v1.example.json")
        fixture["provenance"]["kind"] = "GENERATED"
        fixture["provenance"]["seed"] = None
        with self.assertRaises(ContractError):
            self.catalog.validate("conformance-fixture-v1", fixture)

        projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
        projection["state"]["phase"] = "TERMINAL"
        with self.assertRaises(ContractError):
            self.catalog.validate("semantic-projection-v1", projection)

        bundle = load_json(EXAMPLE_DIR / "mismatch-bundle-v1.example.json")
        bundle["minimization"]["status"] = "MINIMIZED"
        bundle["minimization"]["reproducible"] = False
        with self.assertRaises(ContractError):
            self.catalog.validate("mismatch-bundle-v1", bundle)

    def test_exposed_collapse_play_requires_atomic_action_count_below_threshold(self) -> None:
        for board_size, threshold in ((9, 34), (13, 70), (19, 150)):
            projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
            projection["state"]["boardSize"] = board_size
            projection["state"]["threshold"] = threshold
            projection["state"]["atomicActionCount"] = threshold - 1
            projection["derived"]["legalActionRanges"] = [
                {"first": PASS_ACTION_ID, "last": PASS_ACTION_ID}
            ]
            self.catalog.validate("semantic-projection-v1", projection)

            projection["state"]["atomicActionCount"] = threshold
            with self.subTest(board_size=board_size), self.assertRaises(ContractError) as caught:
                self.catalog.validate("semantic-projection-v1", projection)
            self.assertEqual("schema-validation", caught.exception.code)

        ordinary = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
        ordinary["state"]["phase"] = "ORDINARY_PLAY"
        ordinary["state"]["settlementCompleted"] = True
        ordinary["state"]["atomicActionCount"] = 150
        self.catalog.validate("semantic-projection-v1", ordinary)

    def test_public_identity_without_embedded_descriptor_requires_official_configuration(self) -> None:
        fixture = load_json(EXAMPLE_DIR / "conformance-fixture-v1.example.json")
        fixture["configuration"]["boardSize"] = 9
        fixture["configuration"]["threshold"] = 34
        with self.assertRaises(ContractError) as caught:
            self.catalog.validate("conformance-fixture-v1", fixture)
        self.assertEqual("schema-validation", caught.exception.code)

        bundle = load_json(EXAMPLE_DIR / "mismatch-bundle-v1.example.json")
        bundle["configuration"]["boardSize"] = 9
        bundle["configuration"]["threshold"] = 34
        with self.assertRaises(ContractError) as caught:
            self.catalog.validate("mismatch-bundle-v1", bundle)
        self.assertEqual("schema-validation", caught.exception.code)

    def test_descriptor_has_frozen_public_identity_and_hash(self) -> None:
        self.assertEqual(PUBLIC_RULESET_ID, self.descriptor["identity"]["rulesetId"])
        self.assertEqual(PUBLIC_SEMANTIC_VERSION, self.descriptor["identity"]["semanticVersion"])
        self.assertEqual(CANONICALIZATION_PROFILE, self.descriptor["canonicalization"]["profile"])
        self.assertEqual("BOARD_LOCAL_ROW_MAJOR", self.descriptor["boardPolicy"]["semanticPointEncoding"]["domain"])
        self.assertEqual(EXPECTED_PUBLIC_HASH, self.digest)
        self.assertEqual(EXPECTED_PUBLIC_HASH, sha256_hex(canonicalize_json_bytes(DESCRIPTOR_PATH.read_bytes())))

    def test_official_semantic_version_rejects_schema_valid_drift_even_nonpublic(self) -> None:
        drifted = copy.deepcopy(self.descriptor)
        drifted["quotas"]["initialByPlayer"]["BLACK"]["IMMORTAL"] = 2
        self.assertNotEqual(self.digest, descriptor_digest(drifted))
        with self.assertRaises(ContractError) as caught:
            validate_descriptor(drifted, self.catalog, require_public=False)
        self.assertEqual("descriptor-validation", caught.exception.code)

    def test_public_identity_semantic_validation_binds_exact_digest(self) -> None:
        projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
        projection["ruleset"]["descriptorSha256"] = "0" * 64
        with self.assertRaises(ContractError) as caught:
            _validate_projection(projection, self.catalog, self.digest)
        self.assertEqual("ruleset-identity-mismatch", caught.exception.code)

    def test_official_semantic_version_cannot_alias_schema_valid_alternative_semantics(self) -> None:
        drifted = copy.deepcopy(self.descriptor)
        drifted["quotas"]["initialByPlayer"]["BLACK"]["IMMORTAL"] = 2
        with self.assertRaises(ContractError) as caught:
            validate_descriptor(drifted, self.catalog, require_public=False)
        self.assertEqual("descriptor-validation", caught.exception.code)

        drifted["identity"]["semanticVersion"] = "0.1.0-draft-q2-black-immortal"
        alternative_digest = validate_descriptor(drifted, self.catalog, require_public=False)
        self.assertNotEqual(PUBLIC_SEMANTIC_VERSION, drifted["identity"]["semanticVersion"])
        self.assertNotEqual(self.digest, alternative_digest)

    def test_in_memory_validation_enforces_strict_profile_before_json_schema(self) -> None:
        projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
        mutations = []
        floating = copy.deepcopy(projection)
        floating["state"]["revision"] = 0.0
        mutations.append((floating, "floating-point"))
        non_ascii = copy.deepcopy(projection)
        non_ascii["fixtureId"] = "fixture-e"
        non_ascii["fixtureId"] += "é"
        mutations.append((non_ascii, "non-ascii-string"))
        unsafe = copy.deepcopy(projection)
        unsafe["state"]["revision"] = SAFE_INTEGER_MAX + 1
        mutations.append((unsafe, "unsafe-integer"))
        for mutation, code in mutations:
            with self.subTest(code=code), self.assertRaises(ContractError) as caught:
                self.catalog.validate("semantic-projection-v1", mutation)
            self.assertEqual(code, caught.exception.code)

    def test_ascii_identifiers_reject_trailing_control_characters(self) -> None:
        projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
        projection["fixtureId"] = "fixture-id\n"
        with self.assertRaises(ContractError) as caught:
            self.catalog.validate("semantic-projection-v1", projection)
        self.assertEqual("schema-validation", caught.exception.code)

    def test_terminal_schema_discriminates_scoring_from_immediate_terminal(self) -> None:
        fixture = load_json(EXAMPLE_DIR / "conformance-fixture-v1.example.json")
        scored = copy.deepcopy(fixture["steps"][-1]["expectedProjection"])
        immediate_score = copy.deepcopy(scored)
        immediate_score["transition"]["transitionKind"] = "IMMEDIATE_TERMINAL"
        immediate_score["transition"]["atomicEvent"] = None
        with self.assertRaises(ContractError):
            self.catalog.validate("semantic-projection-v1", immediate_score)
        atomic_resignation = copy.deepcopy(scored)
        atomic_resignation["transition"]["terminalEvent"]["reason"] = "RESIGNATION"
        atomic_resignation["state"]["terminal"]["reason"] = "RESIGNATION"
        atomic_resignation["state"]["terminal"]["score"] = None
        with self.assertRaises(ContractError):
            self.catalog.validate("semantic-projection-v1", atomic_resignation)

    def test_json_pointer_parser_rejects_invalid_escapes_and_array_indexes(self) -> None:
        document = {"items": ["zero"]}
        for pointer in ("/bad~2escape", "/items/00"):
            with self.assertRaises(ContractError) as caught:
                resolve_json_pointer(document, pointer)
            self.assertEqual("invalid-json-pointer", caught.exception.code)

    def test_descriptor_rejects_unknown_fields_and_unfrozen_substitutes(self) -> None:
        mutations = []
        unknown = copy.deepcopy(self.descriptor)
        unknown["unexpected"] = None
        mutations.append(unknown)
        slug = copy.deepcopy(self.descriptor)
        slug["identity"]["rulesetId"] = "collapse-go"
        mutations.append(slug)
        no_seed = copy.deepcopy(self.descriptor)
        no_seed["positionalSuperko"]["initialPSKSeed"] = False
        mutations.append(no_seed)
        point_major = copy.deepcopy(self.descriptor)
        point_major["actionSpace"]["layout"] = "POINT_MAJOR"
        mutations.append(point_major)
        for mutation in mutations:
            with self.assertRaises(ContractError) as caught:
                validate_descriptor(mutation, self.catalog)
            self.assertEqual("schema-validation", caught.exception.code)


class FixtureAndMismatchInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = SchemaCatalog()
        cls.digest = validate_descriptor(load_json(DESCRIPTOR_PATH), cls.catalog)
        cls.fixture = load_json(EXAMPLE_DIR / "conformance-fixture-v1.example.json")
        cls.double_fixture = load_json(EXAMPLE_DIR / "conformance-fixture-double-settlement-v1.example.json")
        cls.immortal_fixture = load_json(
            EXAMPLE_DIR
            / "conformance-fixture-immortal-true-eye-settlement-v1.example.json"
        )

    def _mixed_topology_projection(self, *, settled: bool = False) -> dict[str, object]:
        projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
        projection["fixtureId"] = (
            "contract-mixed-topology-settled" if settled else "contract-mixed-topology-armed"
        )
        state = projection["state"]
        occupancy = {"black": [0, 10, 29, 30, 40], "white": []}
        state["boardSize"] = 9
        state["threshold"] = 34
        state["revision"] = 5
        state["atomicActionCount"] = 5
        state["logPosition"] = 7 if settled else 5
        state["occupancy"] = copy.deepcopy(occupancy)
        state["stones"] = [
            {"point": 0, "color": "BLACK", "originActionNumber": 4, "sourceId": "stone-4", "originKind": "NORMAL", "specialEventId": None},
            {"point": 10, "color": "BLACK", "originActionNumber": 5, "sourceId": "stone-5", "originKind": "NORMAL", "specialEventId": None},
            {"point": 29, "color": "BLACK", "originActionNumber": 3, "sourceId": "stone-3", "originKind": "IMMORTAL", "specialEventId": "special-3"},
            {"point": 30, "color": "BLACK", "originActionNumber": 2, "sourceId": "stone-2", "originKind": "NORMAL", "specialEventId": None},
            {"point": 40, "color": "BLACK", "originActionNumber": 1, "sourceId": "stone-1", "originKind": "EIGHTWAY", "specialEventId": "special-1"},
        ]
        state["actor"] = "WHITE"
        state["phase"] = "ORDINARY_PLAY" if settled else "COLLAPSE_PLAY"
        state["settlementCompleted"] = settled
        state["pendingDouble"] = None
        state["usedQuotas"]["BLACK"] = {
            "IMMORTAL": 1,
            "DOUBLE_START": 0,
            "EIGHTWAY": 1,
        }
        if settled:
            zero = {"IMMORTAL": 0, "DOUBLE_START": 0, "EIGHTWAY": 0}
            state["remainingQuotas"] = {"BLACK": copy.deepcopy(zero), "WHITE": copy.deepcopy(zero)}
            state["expiredQuotas"] = {
                "BLACK": {"IMMORTAL": 0, "DOUBLE_START": 1, "EIGHTWAY": 0},
                "WHITE": {"IMMORTAL": 1, "DOUBLE_START": 1, "EIGHTWAY": 1},
            }
        else:
            state["remainingQuotas"]["BLACK"] = {
                "IMMORTAL": 0,
                "DOUBLE_START": 1,
                "EIGHTWAY": 0,
            }
        state["ledger"] = [
            {
                "eventId": "special-1",
                "logicalOrder": 0,
                "owner": "BLACK",
                "kind": "EIGHTWAY",
                "sourcePoint": 40,
                "sourceStoneId": "stone-1",
                "abilityState": "INACTIVE" if settled else "ARMED",
                "stoneState": "ON_BOARD",
                "settlementState": "SETTLED" if settled else "PENDING",
                "tombstone": settled,
            },
            {
                "eventId": "special-3",
                "logicalOrder": 2,
                "owner": "BLACK",
                "kind": "IMMORTAL",
                "sourcePoint": 29,
                "sourceStoneId": "stone-3",
                "abilityState": "INACTIVE" if settled else "ARMED",
                "stoneState": "ON_BOARD",
                "settlementState": "SETTLED" if settled else "PENDING",
                "tombstone": settled,
            },
        ]
        state["pskHistory"] = [{"black": [], "white": []}] + [
            copy.deepcopy(occupancy) for _ in range(state["logPosition"])
        ]
        projection["derived"]["legalActionRanges"] = [
            {"first": PASS_ACTION_ID, "last": PASS_ACTION_ID}
        ]
        ordinary_groups = [
            {
                "color": "BLACK",
                "stones": [0],
                "liberties": [1, 9],
                "protected": False,
                "immortalAnchors": [],
                "eightwayAnchors": [],
            },
            {
                "color": "BLACK",
                "stones": [10],
                "liberties": [1, 9, 11, 19],
                "protected": False,
                "immortalAnchors": [],
                "eightwayAnchors": [],
            },
        ]
        if settled:
            ordinary_groups.extend(
                [
                    {
                        "color": "BLACK",
                        "stones": [29, 30],
                        "liberties": [20, 21, 28, 31, 38, 39],
                        "protected": False,
                        "immortalAnchors": [],
                        "eightwayAnchors": [],
                    },
                    {
                        "color": "BLACK",
                        "stones": [40],
                        "liberties": [31, 39, 41, 49],
                        "protected": False,
                        "immortalAnchors": [],
                        "eightwayAnchors": [],
                    },
                ]
            )
        else:
            ordinary_groups.append(
                {
                    "color": "BLACK",
                    "stones": [29, 30, 40],
                    "liberties": [20, 21, 28, 31, 32, 38, 39, 41, 48, 49, 50],
                    "protected": True,
                    "immortalAnchors": [29],
                    "eightwayAnchors": [40],
                }
            )
        projection["debug"]["groups"] = ordinary_groups
        return projection

    def test_mixed_n4_n8_topology_is_recomputed_from_armed_anchors(self) -> None:
        armed = self._mixed_topology_projection()
        _validate_projection(armed, self.catalog, self.digest)
        mixed = armed["debug"]["groups"][-1]
        self.assertEqual([29, 30, 40], mixed["stones"])
        self.assertEqual([29], mixed["immortalAnchors"])
        self.assertEqual([40], mixed["eightwayAnchors"])
        self.assertTrue(mixed["protected"])
        self.assertIn(32, mixed["liberties"])
        self.assertNotIn(22, mixed["liberties"])

        mutations = []
        false_ordinary_diagonal = copy.deepcopy(armed)
        false_ordinary_diagonal["debug"]["groups"] = [
            {
                "color": "BLACK",
                "stones": [0, 10],
                "liberties": [1, 9, 11, 19],
                "protected": False,
                "immortalAnchors": [],
                "eightwayAnchors": [],
            },
            copy.deepcopy(armed["debug"]["groups"][-1]),
        ]
        mutations.append(("false-ordinary-diagonal-edge", false_ordinary_diagonal))

        missing_n8_liberty = copy.deepcopy(armed)
        missing_n8_liberty["debug"]["groups"][-1]["liberties"].remove(32)
        mutations.append(("missing-n8-liberty", missing_n8_liberty))

        ordinary_n8_interface = copy.deepcopy(armed)
        ordinary_n8_interface["debug"]["groups"][-1]["liberties"].append(22)
        ordinary_n8_interface["debug"]["groups"][-1]["liberties"].sort()
        mutations.append(("ordinary-endpoint-false-n8-liberty", ordinary_n8_interface))

        asymmetric_edge = copy.deepcopy(armed)
        asymmetric_edge["debug"]["groups"] = copy.deepcopy(
            armed["debug"]["groups"][:2]
        ) + [
            {
                "color": "BLACK",
                "stones": [29, 30],
                "liberties": [20, 21, 28, 31, 38, 39],
                "protected": True,
                "immortalAnchors": [29],
                "eightwayAnchors": [],
            },
            {
                "color": "BLACK",
                "stones": [40],
                "liberties": [31, 32, 39, 41, 48, 49, 50],
                "protected": False,
                "immortalAnchors": [],
                "eightwayAnchors": [40],
            },
        ]
        mutations.append(("asymmetric-anchor-edge", asymmetric_edge))

        lost_protection = copy.deepcopy(armed)
        lost_protection["debug"]["groups"][-1]["protected"] = False
        mutations.append(("lost-protection-propagation", lost_protection))

        for label, projection in mutations:
            with self.subTest(label=label), self.assertRaises(ContractError) as caught:
                _validate_projection(projection, self.catalog, self.digest)
            self.assertEqual("semantic-invariant", caught.exception.code)

        settled = self._mixed_topology_projection(settled=True)
        _validate_projection(settled, self.catalog, self.digest)
        stale_connection = copy.deepcopy(settled)
        stale_connection["debug"]["groups"] = copy.deepcopy(
            settled["debug"]["groups"][:2]
        ) + [
            {
                "color": "BLACK",
                "stones": [29, 30, 40],
                "liberties": [20, 21, 28, 31, 38, 39, 41, 49],
                "protected": False,
                "immortalAnchors": [],
                "eightwayAnchors": [],
            }
        ]
        with self.assertRaises(ContractError) as caught:
            _validate_projection(stale_connection, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_official_immortal_fixture_binds_true_eye_atomic_and_settlement_states(self) -> None:
        fixture = self.immortal_fixture
        self.assertIsNone(fixture["descriptor"])
        self.assertEqual(
            [
                360, 161, 341, 179, 359, 181, 340, 199, 358, 160,
                322, 162, 320, 198, 339, 200, 541, 1444, 1444,
            ],
            [step["candidate"]["action"]["actionId"] for step in fixture["steps"]],
        )
        armed = fixture["steps"][16]["expectedProjection"]
        center_group = next(
            group for group in armed["debug"]["groups"] if 180 in group["stones"]
        )
        self.assertEqual([], center_group["liberties"])
        self.assertTrue(center_group["protected"])
        self.assertEqual([180], center_group["immortalAnchors"])

        final = fixture["steps"][18]["expectedProjection"]
        atomic = final["transition"]["atomicEvent"]
        self.assertIn(180, atomic["stableOccupancy"]["black"])
        settlement_step = final["transition"]["settlement"]["steps"][0]
        self.assertTrue(settlement_step["abilityDeactivated"])
        self.assertFalse(settlement_step["noOp"])
        self.assertEqual([{"black": [180], "white": []}], settlement_step["removalBatches"])
        state = final["state"]
        self.assertEqual((19, 19, 20), (
            state["atomicActionCount"], state["revision"], state["logPosition"]
        ))
        self.assertEqual(21, len(state["pskHistory"]))
        self.assertEqual(("WHITE", "ORDINARY_PLAY"), (state["actor"], state["phase"]))
        self.assertEqual(
            ("INACTIVE", "CAPTURED", "SETTLED", True),
            (
                state["ledger"][0]["abilityState"],
                state["ledger"][0]["stoneState"],
                state["ledger"][0]["settlementState"],
                state["ledger"][0]["tombstone"],
            ),
        )
        zero = {"IMMORTAL": 0, "DOUBLE_START": 0, "EIGHTWAY": 0}
        self.assertEqual({"BLACK": zero, "WHITE": zero}, state["remainingQuotas"])
        self.assertEqual(
            {
                "BLACK": {"IMMORTAL": 1, "DOUBLE_START": 0, "EIGHTWAY": 0},
                "WHITE": zero,
            },
            state["usedQuotas"],
        )
        self.assertEqual(
            {
                "BLACK": {"IMMORTAL": 0, "DOUBLE_START": 1, "EIGHTWAY": 1},
                "WHITE": {"IMMORTAL": 1, "DOUBLE_START": 1, "EIGHTWAY": 1},
            },
            state["expiredQuotas"],
        )
        _validate_fixture(fixture, self.catalog, self.digest)

    def _nonpublic_initial_fixture(
        self,
        board_size: int = 9,
        quotas: dict[str, dict[str, int]] | None = None,
        semantic_version: str = "0.1.0-draft-n9-qtest",
    ) -> tuple[dict, dict, str]:
        if quotas is None:
            quotas = {
                "BLACK": {"IMMORTAL": 0, "DOUBLE_START": 2, "EIGHTWAY": 1},
                "WHITE": {"IMMORTAL": 3, "DOUBLE_START": 0, "EIGHTWAY": 1},
            }
        threshold = (150 * board_size * board_size + 180) // 361
        descriptor = load_json(DESCRIPTOR_PATH)
        descriptor["identity"]["semanticVersion"] = semantic_version
        descriptor["initialState"]["boardSize"] = board_size
        descriptor["boardPolicy"]["selectedBoardSize"] = board_size
        descriptor["quotas"]["initialByPlayer"] = copy.deepcopy(quotas)
        candidate_digest = validate_descriptor(descriptor, self.catalog, require_public=False)
        identity = {
            "rulesetId": PUBLIC_RULESET_ID,
            "semanticVersion": semantic_version,
            "descriptorSha256": candidate_digest,
        }
        fixture = copy.deepcopy(self.fixture)
        fixture["ruleset"] = identity
        fixture["descriptor"] = descriptor
        fixture["configuration"]["boardSize"] = board_size
        fixture["configuration"]["threshold"] = threshold
        fixture["configuration"]["quotas"] = copy.deepcopy(quotas)
        fixture["steps"] = []
        initial = fixture["initialProjection"]
        initial["ruleset"] = identity
        initial["state"]["boardSize"] = board_size
        initial["state"]["threshold"] = threshold
        initial["state"]["initialQuotas"] = copy.deepcopy(quotas)
        initial["state"]["remainingQuotas"] = copy.deepcopy(quotas)
        legal_ids = [PASS_ACTION_ID]
        for kind in KINDS:
            for y in range(board_size):
                for x in range(board_size):
                    legal_ids.append(encode_semantic_action(kind, board_size, x, y)["actionId"])
        legal_ids.sort()
        ranges = []
        first = last = legal_ids[0]
        for action_id in legal_ids[1:]:
            if action_id == last + 1:
                last = action_id
            else:
                ranges.append({"first": first, "last": last})
                first = last = action_id
        ranges.append({"first": first, "last": last})
        initial["derived"]["legalActionRanges"] = ranges
        return fixture, descriptor, candidate_digest

    def test_nonpublic_fixture_can_encode_9x9_and_nonofficial_quotas(self) -> None:
        fixture, _, candidate_digest = self._nonpublic_initial_fixture()
        self.assertNotEqual(self.digest, candidate_digest)
        _validate_fixture(fixture, self.catalog, self.digest)

    def test_embedded_official_version_cannot_alias_alternative_semantics(self) -> None:
        fixture, descriptor, _ = self._nonpublic_initial_fixture()
        descriptor["identity"]["semanticVersion"] = PUBLIC_SEMANTIC_VERSION
        drifted_digest = descriptor_digest(descriptor)
        fixture["descriptor"] = descriptor
        fixture["ruleset"]["semanticVersion"] = PUBLIC_SEMANTIC_VERSION
        fixture["ruleset"]["descriptorSha256"] = drifted_digest
        fixture["initialProjection"]["ruleset"] = copy.deepcopy(fixture["ruleset"])
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(fixture, self.catalog, self.digest)
        self.assertEqual("descriptor-validation", caught.exception.code)

        bundle = load_json(EXAMPLE_DIR / "mismatch-bundle-v1.example.json")
        bundle["descriptor"] = copy.deepcopy(descriptor)
        bundle["ruleset"] = copy.deepcopy(fixture["ruleset"])
        with self.assertRaises(ContractError) as caught:
            _validate_mismatch_bundle(bundle, self.catalog, self.digest)
        self.assertEqual("descriptor-validation", caught.exception.code)

    def test_wrong_actor_rejection_is_representable_and_side_effect_free(self) -> None:
        fixture = copy.deepcopy(self.fixture)
        result = copy.deepcopy(fixture["initialProjection"])
        result["stepIndex"] = 1
        result["transition"] = {
            "accepted": False,
            "transitionKind": "REJECTED",
            "errorCode": "WRONG_ACTOR",
            "atomicEvent": None,
            "settlement": None,
            "terminalEvent": None,
        }
        fixture["steps"] = [
            {
                "stepIndex": 1,
                "candidateActor": "WHITE",
                "candidate": {"kind": "ACTION", "action": decode_action(PASS_ACTION_ID)},
                "expectedProjection": result,
            }
        ]
        _validate_fixture(fixture, self.catalog, self.digest)

        broken = copy.deepcopy(fixture)
        broken["steps"][0]["candidateActor"] = "BLACK"
        with self.assertRaises(ContractError):
            _validate_fixture(broken, self.catalog, self.digest)

    def test_rejection_precedence_uses_descriptor_order_before_wrong_actor(self) -> None:
        fixture, _, _ = self._nonpublic_initial_fixture()
        previous = fixture["initialProjection"]
        off_board_action = encode_canvas_action("NORMAL", 0, 0)
        result = copy.deepcopy(previous)
        result["stepIndex"] = 1
        result["transition"] = {
            "accepted": False,
            "transitionKind": "REJECTED",
            "errorCode": "POINT_OFF_BOARD",
            "atomicEvent": None,
            "settlement": None,
            "terminalEvent": None,
        }
        fixture["steps"] = [
            {
                "stepIndex": 1,
                "candidateActor": "WHITE",
                "candidate": {"kind": "ACTION", "action": off_board_action},
                "expectedProjection": result,
            }
        ]
        _validate_fixture(fixture, self.catalog, self.digest)

        candidate = {
            "stepIndex": 1,
            "actor": "WHITE",
            "intent": {"kind": "ACTION", "action": off_board_action},
        }
        _validate_mismatch_result_projection(
            result,
            previous,
            candidate,
            self.catalog,
            fixture["ruleset"],
        )

        wrong_precedence = copy.deepcopy(fixture)
        wrong_precedence["steps"][0]["expectedProjection"]["transition"]["errorCode"] = "WRONG_ACTOR"
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(wrong_precedence, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

        ordinary = copy.deepcopy(self.fixture)
        ordinary["steps"] = ordinary["steps"][:3]
        ordinary["steps"][2]["candidateActor"] = "WHITE"
        _validate_fixture(ordinary, self.catalog, self.digest)
        ordinary["steps"][2]["expectedProjection"]["transition"]["errorCode"] = "WRONG_ACTOR"
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(ordinary, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_pass_and_semantic_commit_invariants_reject_impossible_results(self) -> None:
        for mutate in ("capture", "actor", "revision", "log-position"):
            broken = copy.deepcopy(self.fixture)
            first = broken["steps"][0]["expectedProjection"]
            if mutate == "capture":
                first["transition"]["atomicEvent"]["captured"]["black"] = [0]
            elif mutate == "actor":
                first["state"]["actor"] = "BLACK"
            elif mutate == "revision":
                first["state"]["revision"] = 0
            else:
                first["state"]["logPosition"] = 0
            with self.subTest(mutate=mutate), self.assertRaises(ContractError):
                _validate_fixture(broken, self.catalog, self.digest)

    def test_fixture_requires_exact_psk_prefix_and_every_stable_append(self) -> None:
        broken = copy.deepcopy(self.fixture)
        first = broken["steps"][0]["expectedProjection"]
        first["state"]["pskHistory"] = first["state"]["pskHistory"][:1]
        first["transition"]["atomicEvent"]["pskHistoryIndex"] = 0
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(broken, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_scored_terminal_state_requires_terminal_event_and_psk_append(self) -> None:
        broken = copy.deepcopy(self.fixture)
        final_projection = broken["steps"][-1]["expectedProjection"]
        final_projection["transition"]["terminalEvent"] = None
        final_projection["state"]["pskHistory"].pop()
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(broken, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_immediate_resignation_is_schema_valid_non_atomic_and_appends_psk(self) -> None:
        fixture = copy.deepcopy(self.fixture)
        initial = fixture["initialProjection"]
        result = copy.deepcopy(initial)
        result["stepIndex"] = 1
        result["transition"] = {
            "accepted": True,
            "transitionKind": "IMMEDIATE_TERMINAL",
            "errorCode": None,
            "atomicEvent": None,
            "settlement": None,
            "terminalEvent": {
                "eventId": "terminal-1",
                "reason": "RESIGNATION",
                "winner": "WHITE",
                "loser": "BLACK",
                "stableOccupancy": {"black": [], "white": []},
                "pskHistoryIndex": 1,
            },
        }
        result["state"]["revision"] = 1
        result["state"]["logPosition"] = 1
        result["state"]["actor"] = None
        result["state"]["phase"] = "TERMINAL"
        result["state"]["pskHistory"].append({"black": [], "white": []})
        result["state"]["terminal"] = {
            "ended": True,
            "reason": "RESIGNATION",
            "winner": "WHITE",
            "loser": "BLACK",
            "score": None,
        }
        result["derived"]["legalActionRanges"] = []
        fixture["steps"] = [
            {
                "stepIndex": 1,
                "candidateActor": "BLACK",
                "candidate": {"kind": "RESIGNATION"},
                "expectedProjection": result,
            }
        ]
        _validate_fixture(fixture, self.catalog, self.digest)

        changed_counter = copy.deepcopy(fixture)
        changed_counter["steps"][0]["expectedProjection"]["state"]["consecutivePasses"] = 1
        with self.assertRaises(ContractError):
            _validate_fixture(changed_counter, self.catalog, self.digest)

        invented_board = copy.deepcopy(fixture)
        invented = invented_board["steps"][0]["expectedProjection"]
        invented_occupancy = {"black": [0], "white": []}
        invented["transition"]["terminalEvent"]["stableOccupancy"] = copy.deepcopy(invented_occupancy)
        invented["state"]["occupancy"] = copy.deepcopy(invented_occupancy)
        invented["state"]["pskHistory"][-1] = copy.deepcopy(invented_occupancy)
        invented["state"]["stones"] = [
            {"point": 0, "color": "BLACK", "sourceId": "invented-stone", "originKind": "NORMAL", "specialEventId": None}
        ]
        invented["debug"]["groups"] = [
            {
                "color": "BLACK",
                "stones": [0],
                "liberties": [1, 19],
                "protected": False,
                "immortalAnchors": [],
                "eightwayAnchors": [],
            }
        ]
        with self.assertRaises(ContractError):
            _validate_fixture(invented_board, self.catalog, self.digest)

    def test_immediate_terminal_transition_cannot_start_from_terminal_state(self) -> None:
        previous = copy.deepcopy(self.fixture["steps"][-1]["expectedProjection"])
        current = copy.deepcopy(previous)
        current["stepIndex"] += 1
        current["state"]["revision"] += 1
        current["state"]["logPosition"] += 1
        current["state"]["pskHistory"].append(copy.deepcopy(current["state"]["occupancy"]))
        current["transition"] = {
            "accepted": True,
            "transitionKind": "IMMEDIATE_TERMINAL",
            "errorCode": None,
            "atomicEvent": None,
            "settlement": None,
            "terminalEvent": {
                "eventId": f"terminal-{current['state']['logPosition']}",
                "reason": "RESIGNATION",
                "winner": "WHITE",
                "loser": "BLACK",
                "stableOccupancy": copy.deepcopy(current["state"]["occupancy"]),
                "pskHistoryIndex": len(current["state"]["pskHistory"]) - 1,
            },
        }
        with self.assertRaises(ContractError) as caught:
            _validate_projection_from_previous(previous, current)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_timeout_is_available_during_pending_double_without_running_settlement(self) -> None:
        fixture = copy.deepcopy(self.double_fixture)
        fixture["steps"] = fixture["steps"][:1]
        pending = fixture["steps"][0]["expectedProjection"]
        result = copy.deepcopy(pending)
        result["stepIndex"] = 2
        result["transition"] = {
            "accepted": True,
            "transitionKind": "IMMEDIATE_TERMINAL",
            "errorCode": None,
            "atomicEvent": None,
            "settlement": None,
            "terminalEvent": {
                "eventId": "terminal-2",
                "reason": "TIMEOUT",
                "winner": "WHITE",
                "loser": "BLACK",
                "stableOccupancy": {"black": [180], "white": []},
                "pskHistoryIndex": 2,
            },
        }
        result["state"]["revision"] = 2
        result["state"]["logPosition"] = 2
        result["state"]["actor"] = None
        result["state"]["phase"] = "TERMINAL"
        result["state"]["pskHistory"].append({"black": [180], "white": []})
        result["state"]["terminal"] = {
            "ended": True,
            "reason": "TIMEOUT",
            "winner": "WHITE",
            "loser": "BLACK",
            "score": None,
        }
        result["derived"]["legalActionRanges"] = []
        fixture["steps"].append(
            {
                "stepIndex": 2,
                "candidateActor": "BLACK",
                "candidate": {"kind": "TIMEOUT"},
                "expectedProjection": result,
            }
        )
        _validate_fixture(fixture, self.catalog, self.digest)

    def test_nonempty_settlement_trace_requires_ledger_order_and_consecutive_psk_append(self) -> None:
        _validate_fixture(self.double_fixture, self.catalog, self.digest)
        for mutate in ("omit-step", "wrong-ledger", "wrong-index", "renamed-ledger", "false-noop", "removal-on-noop"):
            broken = copy.deepcopy(self.double_fixture)
            final_projection = broken["steps"][-1]["expectedProjection"]
            settlement = final_projection["transition"]["settlement"]
            if mutate == "omit-step":
                settlement["steps"] = []
            elif mutate == "wrong-ledger":
                settlement["steps"][0]["ledgerEventId"] = "other-event"
            elif mutate == "wrong-index":
                settlement["steps"][0]["pskHistoryIndex"] = 3
            elif mutate == "renamed-ledger":
                final_projection["state"]["ledger"][0]["eventId"] = "invented-event"
                final_projection["state"]["stones"][0]["specialEventId"] = "invented-event"
                settlement["steps"][0]["ledgerEventId"] = "invented-event"
            elif mutate == "false-noop":
                settlement["steps"][0]["noOp"] = False
            else:
                settlement["steps"][0]["removalBatches"] = [{"black": [180], "white": []}]
            with self.subTest(mutate=mutate), self.assertRaises(ContractError):
                _validate_fixture(broken, self.catalog, self.digest)

    def test_settlement_closure_rejects_empty_healthy_and_split_batches(self) -> None:
        empty_wave = copy.deepcopy(self.immortal_fixture)
        empty_step = empty_wave["steps"][18]["expectedProjection"]["transition"][
            "settlement"
        ]["steps"][0]
        empty_step["removalBatches"].insert(0, {"black": [], "white": []})
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(empty_wave, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

        healthy_removal = copy.deepcopy(self.immortal_fixture)
        final = healthy_removal["steps"][18]["expectedProjection"]
        settlement_step = final["transition"]["settlement"]["steps"][0]
        settlement_step["removalBatches"] = [{"black": [180, 320], "white": []}]
        stable = copy.deepcopy(settlement_step["stableOccupancy"])
        stable["black"].remove(320)
        settlement_step["stableOccupancy"] = copy.deepcopy(stable)
        final["state"]["occupancy"] = copy.deepcopy(stable)
        final["state"]["stones"] = [
            stone for stone in final["state"]["stones"] if stone["point"] != 320
        ]
        final["state"]["pskHistory"][settlement_step["pskHistoryIndex"]] = copy.deepcopy(
            stable
        )
        final["debug"]["groups"] = _contract_mixed_groups(
            _occupancy_sets(stable),
            final["state"]["ledger"],
            19,
            require_stable=True,
        )
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(healthy_removal, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

        atomic = {"black": [0, 1], "white": [2, 9, 10]}
        ledger = [
            {
                "eventId": "special-1",
                "logicalOrder": 0,
                "owner": "BLACK",
                "kind": "IMMORTAL",
                "sourcePoint": 0,
                "sourceStoneId": "stone-1",
                "abilityState": "ARMED",
                "stoneState": "ON_BOARD",
                "settlementState": "PENDING",
                "tombstone": False,
            }
        ]
        split_settlement = {
            "triggerReason": "PRE_THRESHOLD_TWO_PASSES",
            "handoffActor": "WHITE",
            "steps": [
                {
                    "stepIndex": 0,
                    "ledgerEventId": "special-1",
                    "abilityDeactivated": True,
                    "noOp": False,
                    "removalBatches": [
                        {"black": [0], "white": []},
                        {"black": [1], "white": []},
                    ],
                    "stableOccupancy": {"black": [], "white": [2, 9, 10]},
                    "pskHistoryIndex": 2,
                }
            ],
        }
        with self.assertRaises(ContractError) as caught:
            _validate_settlement_closure(atomic, ledger, split_settlement, 9)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_immortal_fixture_rejects_protection_atomic_and_pop_drift(self) -> None:
        for mutate in (
            "unprotect-anchor",
            "false-liberty",
            "drop-atomic-center",
            "false-deactivation",
        ):
            broken = copy.deepcopy(self.immortal_fixture)
            if mutate in ("unprotect-anchor", "false-liberty"):
                group = next(
                    item
                    for item in broken["steps"][16]["expectedProjection"]["debug"]["groups"]
                    if 180 in item["stones"]
                )
                if mutate == "unprotect-anchor":
                    group["protected"] = False
                else:
                    group["liberties"] = [159]
            elif mutate == "drop-atomic-center":
                final = broken["steps"][18]["expectedProjection"]
                final["transition"]["atomicEvent"]["stableOccupancy"]["black"].remove(180)
            else:
                step = broken["steps"][18]["expectedProjection"]["transition"]["settlement"]["steps"][0]
                step["abilityDeactivated"] = False
            with self.subTest(mutate=mutate), self.assertRaises(ContractError) as caught:
                _validate_fixture(broken, self.catalog, self.digest)
            self.assertEqual("semantic-invariant", caught.exception.code)

    def test_consumed_double_settlement_pop_cannot_coherently_mutate_board(self) -> None:
        broken = copy.deepcopy(self.double_fixture)
        final_projection = broken["steps"][-1]["expectedProjection"]
        settlement_step = final_projection["transition"]["settlement"]["steps"][0]
        empty = {"black": [], "white": []}
        settlement_step["noOp"] = False
        settlement_step["removalBatches"] = [{"black": [180], "white": []}]
        settlement_step["stableOccupancy"] = copy.deepcopy(empty)
        final_projection["state"]["occupancy"] = copy.deepcopy(empty)
        final_projection["state"]["stones"] = []
        final_projection["state"]["ledger"][0]["stoneState"] = "CAPTURED"
        final_projection["state"]["pskHistory"][-1] = copy.deepcopy(empty)
        final_projection["derived"]["legalActionRanges"] = [
            {"first": 0, "last": 360},
            {"first": PASS_ACTION_ID, "last": PASS_ACTION_ID},
        ]
        final_projection["debug"]["groups"] = []
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(broken, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_fixture_binds_atomic_event_action_number(self) -> None:
        broken = copy.deepcopy(self.fixture)
        broken["steps"][0]["expectedProjection"]["transition"]["atomicEvent"]["actionNumber"] = 99
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(broken, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_standalone_projection_binds_atomic_event_to_resulting_action_count(self) -> None:
        projection = copy.deepcopy(self.fixture["steps"][0]["expectedProjection"])
        projection["transition"]["atomicEvent"]["actionNumber"] = 99
        projection["transition"]["atomicEvent"]["eventId"] = "action-99"
        with self.assertRaises(ContractError) as caught:
            _validate_projection(projection, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_exposed_collapse_play_requires_atomic_count_below_threshold(self) -> None:
        for board_size, threshold in ((9, 34), (13, 70), (19, 150)):
            projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
            projection["state"]["boardSize"] = board_size
            projection["state"]["threshold"] = threshold
            projection["state"]["atomicActionCount"] = threshold - 1
            projection["derived"]["legalActionRanges"] = [
                {"first": PASS_ACTION_ID, "last": PASS_ACTION_ID}
            ]
            self.catalog.validate("semantic-projection-v1", projection)
            _validate_projection(projection, self.catalog, self.digest)
            projection["state"]["atomicActionCount"] = threshold
            with self.subTest(board_size=board_size), self.assertRaises(ContractError) as caught:
                _validate_projection(projection, self.catalog, self.digest)
            self.assertEqual("schema-validation", caught.exception.code)

    def test_standalone_projection_rejects_pass_captures(self) -> None:
        projection = copy.deepcopy(self.fixture["steps"][0]["expectedProjection"])
        projection["transition"]["atomicEvent"]["captured"] = {"black": [0], "white": []}
        with self.assertRaises(ContractError) as caught:
            _validate_projection(projection, self.catalog, self.digest)
        self.assertEqual("schema-validation", caught.exception.code)

    def test_projection_predecessor_mode_binds_new_psk_append_and_cli_scope(self) -> None:
        previous = copy.deepcopy(self.fixture["initialProjection"])
        valid_current = copy.deepcopy(self.fixture["steps"][0]["expectedProjection"])
        stale_index = copy.deepcopy(valid_current)
        stale_index["transition"]["atomicEvent"]["pskHistoryIndex"] = 0
        _validate_projection(stale_index, self.catalog, self.digest)
        with self.assertRaises(ContractError) as caught:
            _validate_projection_with_predecessor(previous, stale_index, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)
        _validate_projection_with_predecessor(previous, valid_current, self.catalog, self.digest)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            previous_path = temp_root / "previous.json"
            current_path = temp_root / "current.json"
            stale_path = temp_root / "stale.json"
            previous_path.write_text(json.dumps(previous, indent=2) + "\n", encoding="utf-8")
            current_path.write_text(json.dumps(valid_current, indent=2) + "\n", encoding="utf-8")
            stale_path.write_text(json.dumps(stale_index, indent=2) + "\n", encoding="utf-8")
            command = [
                sys.executable,
                str(REPO_ROOT / "tools" / "contract" / "contract.py"),
                "validate",
                "semantic-projection-v1",
            ]
            missing_predecessor = subprocess.run(command + [str(current_path)], capture_output=True, text=True)
            self.assertEqual(1, missing_predecessor.returncode)
            self.assertIn("predecessor-required", missing_predecessor.stderr)

            standalone = subprocess.run(
                command + [str(stale_path), "--standalone"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual("valid-standalone-projection\n", standalone.stdout)

            contextual = subprocess.run(
                command + [str(current_path), "--predecessor", str(previous_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual("valid-transition\n", contextual.stdout)

            stale_context = subprocess.run(
                command + [str(stale_path), "--predecessor", str(previous_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(1, stale_context.returncode)
            self.assertIn("semantic-invariant", stale_context.stderr)

    def test_small_board_projection_rejects_off_board_debug_and_captured_ledger_points(self) -> None:
        projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
        projection["state"]["boardSize"] = 9
        projection["state"]["threshold"] = 34
        projection["state"]["revision"] = 1
        projection["state"]["logPosition"] = 1
        projection["state"]["atomicActionCount"] = 1
        occupancy = {"black": [0], "white": []}
        projection["state"]["occupancy"] = copy.deepcopy(occupancy)
        projection["state"]["pskHistory"].append(copy.deepcopy(occupancy))
        projection["state"]["stones"] = [
            {
                "point": 0,
                "color": "BLACK",
                "originActionNumber": 1,
                "sourceId": "stone-1",
                "originKind": "NORMAL",
                "specialEventId": None,
            }
        ]
        projection["derived"]["legalActionRanges"] = [{"first": PASS_ACTION_ID, "last": PASS_ACTION_ID}]
        projection["debug"]["groups"] = [
            {
                "color": "BLACK",
                "stones": [0],
                "liberties": [360],
                "protected": False,
                "immortalAnchors": [],
                "eightwayAnchors": [],
            }
        ]
        with self.assertRaises(ContractError) as caught:
            _validate_projection(projection, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

        ledger_projection = load_json(EXAMPLE_DIR / "semantic-projection-v1.example.json")
        ledger_projection["state"]["boardSize"] = 9
        ledger_projection["state"]["threshold"] = 34
        ledger_projection["state"]["atomicActionCount"] = 1
        ledger_projection["state"]["remainingQuotas"]["BLACK"]["IMMORTAL"] = 0
        ledger_projection["state"]["usedQuotas"]["BLACK"]["IMMORTAL"] = 1
        ledger_projection["state"]["ledger"] = [
            {
                "eventId": "special-1",
                "logicalOrder": 0,
                "owner": "BLACK",
                "kind": "IMMORTAL",
                "sourcePoint": 360,
                "sourceStoneId": "stone-1",
                "abilityState": "INACTIVE",
                "stoneState": "CAPTURED",
                "settlementState": "PENDING",
                "tombstone": True,
            }
        ]
        ledger_projection["derived"]["legalActionRanges"] = [
            {"first": PASS_ACTION_ID, "last": PASS_ACTION_ID}
        ]
        with self.assertRaises(ContractError) as caught:
            _validate_projection(ledger_projection, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_special_start_cannot_masquerade_as_normal_without_quota_or_ledger(self) -> None:
        fixture = copy.deepcopy(self.double_fixture)
        fixture["steps"] = fixture["steps"][:1]
        step = fixture["steps"][0]
        action = {"schemaVersion": "action-v1", "actionId": 541, "kind": "IMMORTAL"}
        step["candidate"]["action"] = copy.deepcopy(action)
        projection = step["expectedProjection"]
        projection["transition"]["atomicEvent"]["action"] = copy.deepcopy(action)
        projection["state"]["stones"][0]["originKind"] = "NORMAL"
        projection["state"]["stones"][0]["specialEventId"] = None
        projection["state"]["actor"] = "WHITE"
        projection["state"]["pendingDouble"] = None
        projection["state"]["ledger"] = []
        projection["state"]["remainingQuotas"] = copy.deepcopy(projection["state"]["initialQuotas"])
        projection["state"]["usedQuotas"]["BLACK"]["DOUBLE_START"] = 0
        projection["derived"]["legalActionRanges"] = [
            {"first": 0, "last": 179},
            {"first": 181, "last": 540},
            {"first": 542, "last": 901},
            {"first": 903, "last": 1262},
            {"first": 1264, "last": 1444},
        ]
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(fixture, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_pass_cannot_rewrite_existing_stone_provenance_or_ledger(self) -> None:
        fixture = copy.deepcopy(self.double_fixture)
        fixture["steps"] = fixture["steps"][:2]
        projection = fixture["steps"][1]["expectedProjection"]
        projection["state"]["stones"][0]["originKind"] = "NORMAL"
        projection["state"]["stones"][0]["specialEventId"] = None
        projection["state"]["ledger"] = []
        projection["state"]["remainingQuotas"]["BLACK"]["DOUBLE_START"] = 1
        projection["state"]["usedQuotas"]["BLACK"]["DOUBLE_START"] = 0
        with self.assertRaises(ContractError) as caught:
            _validate_fixture(fixture, self.catalog, self.digest)
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_mismatch_prefix_length_binds_revision_and_atomic_action_count(self) -> None:
        bundle = load_json(EXAMPLE_DIR / "mismatch-bundle-v1.example.json")
        initial = bundle["reproduction"]["initialProjection"]
        pre_candidate = copy.deepcopy(bundle["cppObservation"]["value"])
        pre_candidate["stepIndex"] = 2
        prefix = [
            {"stepIndex": 1, "actor": "WHITE", "action": decode_action(PASS_ACTION_ID)},
            {"stepIndex": 2, "actor": "BLACK", "action": decode_action(PASS_ACTION_ID)},
        ]
        candidate = {
            "stepIndex": 3,
            "actor": "WHITE",
            "intent": {"kind": "ACTION", "action": decode_action(PASS_ACTION_ID)},
        }
        with self.assertRaises(ContractError) as caught:
            _validate_mismatch_reproduction_segment(
                initial,
                prefix,
                pre_candidate,
                candidate,
                self.catalog,
                bundle["ruleset"],
            )
        self.assertEqual("semantic-invariant", caught.exception.code)

    def test_mismatch_bundle_preserves_schema_and_raw_failures(self) -> None:
        base = load_json(EXAMPLE_DIR / "mismatch-bundle-v1.example.json")

        schema_invalid = copy.deepcopy(base)
        invalid_value = copy.deepcopy(schema_invalid["pythonObservation"]["value"])
        del invalid_value["state"]["actor"]
        schema_invalid["pythonObservation"] = {
            "status": "SCHEMA_INVALID",
            "value": invalid_value,
            "rawUtf8Hex": json.dumps(invalid_value, separators=(",", ":")).encode("utf-8").hex(),
            "failure": {"stage": "SCHEMA", "code": "schema-validation"},
        }
        schema_invalid["differences"] = [
            {
                "jsonPointer": "/status",
                "category": "VALUE_MISMATCH",
                "cpp": {"present": True, "canonicalJson": '"VALID"'},
                "python": {"present": True, "canonicalJson": '"SCHEMA_INVALID"'},
            }
        ]
        _validate_mismatch_bundle(schema_invalid, self.catalog, self.digest)

        raw_invalid = copy.deepcopy(base)
        raw_invalid["pythonObservation"] = {
            "status": "RAW_INVALID",
            "value": None,
            "rawUtf8Hex": b'{"broken"'.hex(),
            "failure": {"stage": "JSON", "code": "invalid-json"},
        }
        raw_invalid["differences"] = [
            {
                "jsonPointer": "/status",
                "category": "VALUE_MISMATCH",
                "cpp": {"present": True, "canonicalJson": '"VALID"'},
                "python": {"present": True, "canonicalJson": '"RAW_INVALID"'},
            }
        ]
        _validate_mismatch_bundle(raw_invalid, self.catalog, self.digest)

        mislabeled = copy.deepcopy(base)
        mislabeled["pythonObservation"]["status"] = "VALID"
        mislabeled["pythonObservation"]["failure"] = None
        with self.assertRaises(ContractError):
            _validate_mismatch_bundle(mislabeled, self.catalog, self.digest)

    def test_mismatch_bundle_preserves_each_raw_classification_without_cross_parser_reinterpretation(self) -> None:
        bundle = load_json(EXAMPLE_DIR / "mismatch-bundle-v1.example.json")
        raw = b'{"duplicate":1,"duplicate":2}'.hex()
        bundle["cppObservation"] = {
            "status": "RAW_INVALID",
            "value": None,
            "rawUtf8Hex": raw,
            "failure": {"stage": "JSON", "code": "cpp-malformed-json"},
        }
        bundle["pythonObservation"] = {
            "status": "RAW_INVALID",
            "value": None,
            "rawUtf8Hex": raw,
            "failure": {"stage": "PROFILE", "code": "duplicate-key"},
        }
        bundle["differences"] = [
            {
                "jsonPointer": "/failure/stage",
                "category": "VALUE_MISMATCH",
                "cpp": {"present": True, "canonicalJson": '"JSON"'},
                "python": {"present": True, "canonicalJson": '"PROFILE"'},
            },
            {
                "jsonPointer": "/failure/code",
                "category": "VALUE_MISMATCH",
                "cpp": {"present": True, "canonicalJson": '"cpp-malformed-json"'},
                "python": {"present": True, "canonicalJson": '"duplicate-key"'},
            },
        ]
        preserved_cpp = copy.deepcopy(bundle["cppObservation"])
        preserved_python = copy.deepcopy(bundle["pythonObservation"])
        _validate_mismatch_bundle(bundle, self.catalog, self.digest)
        self.assertEqual(preserved_cpp, bundle["cppObservation"])
        self.assertEqual(preserved_python, bundle["pythonObservation"])

    def test_mismatch_bundle_preserves_parser_specific_raw_classifications(self) -> None:
        bundle = load_json(EXAMPLE_DIR / "mismatch-bundle-v1.example.json")
        duplicate_key_raw = b'{"value":1,"value":2}'.hex()
        bundle["cppObservation"] = {
            "status": "RAW_INVALID",
            "value": None,
            "rawUtf8Hex": duplicate_key_raw,
            "failure": {"stage": "JSON", "code": "cpp-malformed-json"},
        }
        bundle["pythonObservation"] = {
            "status": "RAW_INVALID",
            "value": None,
            "rawUtf8Hex": duplicate_key_raw,
            "failure": {"stage": "PROFILE", "code": "duplicate-key"},
        }
        bundle["differences"] = [
            {
                "jsonPointer": "/failure/code",
                "category": "VALUE_MISMATCH",
                "cpp": {"present": True, "canonicalJson": '"cpp-malformed-json"'},
                "python": {"present": True, "canonicalJson": '"duplicate-key"'},
            }
        ]
        _validate_mismatch_bundle(bundle, self.catalog, self.digest)
        self.assertEqual("cpp-malformed-json", bundle["cppObservation"]["failure"]["code"])
        self.assertEqual("duplicate-key", bundle["pythonObservation"]["failure"]["code"])

    def test_mismatch_bundle_rejects_false_metadata_observations_and_categories(self) -> None:
        bundle = load_json(EXAMPLE_DIR / "mismatch-bundle-v1.example.json")
        for mutate in ("same-implementation", "bad-length", "bad-observation", "bad-category", "duplicate-pointer"):
            broken = copy.deepcopy(bundle)
            if mutate == "same-implementation":
                broken["implementations"]["python"]["implementationId"] = broken["implementations"]["cpp"]["implementationId"]
            elif mutate == "bad-length":
                broken["minimization"]["originalPrefixLength"] = 99
            elif mutate == "bad-observation":
                broken["differences"][0]["python"]["canonicalJson"] = '"WHITE"'
            elif mutate == "bad-category":
                broken["differences"][0]["category"] = "ARRAY_LENGTH_MISMATCH"
            else:
                broken["differences"].append(copy.deepcopy(broken["differences"][0]))
            with self.subTest(mutate=mutate), self.assertRaises(ContractError):
                _validate_mismatch_bundle(broken, self.catalog, self.digest)


class VectorCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = SchemaCatalog()

    def test_action_vector_checker_rejects_removed_required_section_cases(self) -> None:
        for section in ("invalidEnvelopes", "d4RoundTrips"):
            vector = load_json(VECTOR_DIR / "action-v1.json")
            vector[section] = []
            with self.subTest(section=section), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "action-v1.json"
                path.write_text(json.dumps(vector, indent=2) + "\n", encoding="utf-8")
                with self.assertRaises(ContractError) as caught:
                    verify_action_vectors(self.catalog, path)
                self.assertEqual("vector-coverage", caught.exception.code)

    def test_action_vector_checker_rejects_unknown_case_fields(self) -> None:
        vector = load_json(VECTOR_DIR / "action-v1.json")
        vector["familyBoundaries"][0]["unexpected"] = None
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "action-v1.json"
            path.write_text(json.dumps(vector, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(ContractError) as caught:
                verify_action_vectors(self.catalog, path)
            self.assertEqual("invalid-vector", caught.exception.code)

    def test_action_vector_checker_enforces_exhaustive_footprints_and_exact_types(self) -> None:
        mutations = []

        bad_footprint = load_json(VECTOR_DIR / "action-v1.json")
        bad_footprint["exhaustiveBoardFootprints"]["perBoard"]["9"]["rejectedRecordCount"] -= 1
        mutations.append((bad_footprint, "vector-mismatch"))

        boolean_kind_code = load_json(VECTOR_DIR / "action-v1.json")
        boolean_kind_code["familyBoundaries"][0]["kindCode"] = False
        mutations.append((boolean_kind_code, "invalid-integer"))

        invalid_pass_board = load_json(VECTOR_DIR / "action-v1.json")
        pass_case = next(case for case in invalid_pass_board["d4RoundTrips"] if case["inputAction"]["kind"] == "PASS")
        pass_case["boardSize"] = "19"
        mutations.append((invalid_pass_board, "invalid-integer"))

        malformed_case = load_json(VECTOR_DIR / "action-v1.json")
        malformed_case["centeredMappings"][0] = "not-an-object"
        mutations.append((malformed_case, "invalid-vector"))

        for vector, expected_code in mutations:
            with self.subTest(expected_code=expected_code), tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "action-v1.json"
                path.write_text(json.dumps(vector, indent=2) + "\n", encoding="utf-8")
                with self.assertRaises(ContractError) as caught:
                    verify_action_vectors(self.catalog, path)
                self.assertEqual(expected_code, caught.exception.code)

    def test_canonicalization_vector_checker_rejects_removed_required_cases(self) -> None:
        vector = load_json(VECTOR_DIR / "canonicalization-v1.json")
        vector["invalidCases"] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "canonicalization-v1.json"
            path.write_text(json.dumps(vector, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(ContractError) as caught:
                verify_canonicalization_vectors(path)
            self.assertEqual("vector-coverage", caught.exception.code)


class FullContractCheckTests(unittest.TestCase):
    def test_check_mode_verifies_every_contract_artifact(self) -> None:
        self.assertEqual(EXPECTED_PUBLIC_HASH, run_check())


if __name__ == "__main__":
    unittest.main()
