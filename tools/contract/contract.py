#!/usr/bin/env python3
"""MutaGo executable-contract parser, canonicalizer, validator, and checker."""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Sequence
from urllib.parse import unquote, urldefrag, urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

try:
    from referencing import Registry, Resource
except ImportError:  # jsonschema < 4.18 does not depend on referencing.
    Registry = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]

VALIDATOR_SUPPORTS_REGISTRY = (
    Registry is not None
    and Resource is not None
    and "registry" in inspect.signature(Draft202012Validator.__init__).parameters
)
if VALIDATOR_SUPPORTS_REGISTRY:
    RefResolver = None  # type: ignore[assignment]
else:
    from jsonschema import RefResolver

SAFE_INTEGER_MIN = -9007199254740991
SAFE_INTEGER_MAX = 9007199254740991
PUBLIC_RULESET_ID = "mutago.collapse-go"
PUBLIC_SEMANTIC_VERSION = "0.1.0-draft"
CANONICALIZATION_PROFILE = "rfc8785-jcs-ascii-safe-integer-v1"

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "schemas" / "source"
RULESET_DIR = REPO_ROOT / "rulesets" / "collapse-go"
DESCRIPTOR_PATH = RULESET_DIR / "descriptor-v0.1.0-draft.json"
VECTOR_DIR = RULESET_DIR / "vectors"
EXAMPLE_DIR = REPO_ROOT / "tests" / "contracts" / "examples"

SCHEMA_FILES = {
    "action-v1": "action-v1.schema.json",
    "ruleset-descriptor-v1": "ruleset-descriptor-v1.schema.json",
    "semantic-projection-v1": "semantic-projection-v1.schema.json",
    "conformance-fixture-v1": "conformance-fixture-v1.schema.json",
    "mismatch-bundle-v1": "mismatch-bundle-v1.schema.json",
}

BOARD_OFFSETS = {9: 5, 13: 3, 19: 0}
BOARD_THRESHOLDS = {9: 34, 13: 70, 19: 150}
ACTION_KIND_CODES = {
    "NORMAL": 0,
    "IMMORTAL": 1,
    "DOUBLE_START": 2,
    "EIGHTWAY": 3,
}
ACTION_CODE_KINDS = {value: key for key, value in ACTION_KIND_CODES.items()}
PASS_ACTION_ID = 1444
INVERSE_SYMMETRY_IDS = (0, 1, 2, 3, 4, 6, 5, 7)
LOWERCASE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LOWERCASE_HEX_RE = re.compile(r"^(?:[0-9a-f]{2})*$")
REJECTION_PRECEDENCE = (
    "POINT_OFF_BOARD",
    "TERMINAL_STATE",
    "INVALID_PHASE",
    "WRONG_ACTOR",
    "DOUBLE_CONTINUATION_KIND_FORBIDDEN",
    "DOUBLE_CONTINUATION_REQUIRED",
    "DOUBLE_THRESHOLD",
    "QUOTA_EXHAUSTED",
    "POINT_OCCUPIED",
    "SUICIDE",
    "POSITIONAL_SUPERKO",
    "INTERNAL_INVARIANT",
)
EARLY_REJECTION_CODES = frozenset(REJECTION_PRECEDENCE[:4])


class ContractError(ValueError):
    """Deterministic contract failure with a stable machine code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _raise(code: str, message: str) -> None:
    raise ContractError(code, message)


def _parse_integer(token: str) -> int:
    negative = token.startswith("-")
    digits = token[1:] if negative else token
    normalized = digits.lstrip("0") or "0"
    safe_magnitude = str(SAFE_INTEGER_MAX)
    if len(normalized) > len(safe_magnitude) or (
        len(normalized) == len(safe_magnitude) and normalized > safe_magnitude
    ):
        _raise("unsafe-integer", f"integer is outside the safe signed range: {token}")
    value = int(token, 10)
    if value < SAFE_INTEGER_MIN or value > SAFE_INTEGER_MAX:
        _raise("unsafe-integer", f"integer is outside the safe signed range: {token}")
    return value


def _reject_float(token: str) -> None:
    _raise("floating-point", f"floating-point JSON numbers are not allowed: {token}")


def _reject_constant(token: str) -> None:
    _raise("invalid-json-number", f"non-JSON numeric constant is not allowed: {token}")


def _object_from_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _raise("duplicate-key", f"duplicate object key: {key!r}")
        result[key] = value
    return result


def _validate_profile_value(value: Any, path: str = "") -> None:
    stack: list[tuple[Any, str, bool]] = [(value, path, False)]
    active_containers: set[int] = set()
    while stack:
        current, current_path, leaving = stack.pop()
        if leaving:
            active_containers.remove(id(current))
            continue
        if current is None or type(current) is bool:
            continue
        if type(current) is int:
            if current < SAFE_INTEGER_MIN or current > SAFE_INTEGER_MAX:
                _raise("unsafe-integer", f"unsafe integer at {current_path or '/'}: {current}")
            continue
        if type(current) is float:
            _raise("floating-point", f"floating-point value at {current_path or '/'}")
        if isinstance(current, str):
            if any(ord(character) > 0x7F for character in current):
                _raise("non-ascii-string", f"non-ASCII string at {current_path or '/'}")
            continue
        if isinstance(current, list):
            container_id = id(current)
            if container_id in active_containers:
                _raise("circular-reference", f"circular array reference at {current_path or '/'}")
            active_containers.add(container_id)
            stack.append((current, current_path, True))
            for index in range(len(current) - 1, -1, -1):
                stack.append((current[index], f"{current_path}/{index}", False))
            continue
        if isinstance(current, dict):
            container_id = id(current)
            if container_id in active_containers:
                _raise("circular-reference", f"circular object reference at {current_path or '/'}")
            active_containers.add(container_id)
            stack.append((current, current_path, True))
            for key, item in reversed(list(current.items())):
                if not isinstance(key, str):
                    _raise("invalid-object-key", f"non-string object key at {current_path or '/'}")
                if any(ord(character) > 0x7F for character in key):
                    _raise("non-ascii-key", f"non-ASCII object key at {current_path or '/'}")
                escaped = key.replace("~", "~0").replace("/", "~1")
                stack.append((item, f"{current_path}/{escaped}", False))
            continue
        _raise("unsupported-json-type", f"unsupported value type at {current_path or '/'}: {type(current).__name__}")


def parse_json_bytes(raw: bytes, *, enforce_profile: bool = True) -> Any:
    """Parse UTF-8 JSON with duplicate-key, number, and optional profile checks."""

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContractError("invalid-utf8", f"input is not valid UTF-8: {error}") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_from_pairs,
            parse_int=_parse_integer,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except ContractError:
        raise
    except RecursionError as error:
        raise ContractError("resource-limit", "JSON nesting exceeds this parser's runtime recursion limit") from error
    except json.JSONDecodeError as error:
        raise ContractError("invalid-json", f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}") from error
    if enforce_profile:
        _validate_profile_value(value)
    return value


def load_json(path: Path, *, enforce_profile: bool = True) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ContractError("io-error", f"cannot read {path}: {error}") from error
    return parse_json_bytes(raw, enforce_profile=enforce_profile)


def canonicalize(value: Any) -> bytes:
    """Apply the restricted RFC 8785/JCS profile and return canonical UTF-8."""

    _validate_profile_value(value)
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except RecursionError as error:
        raise ContractError("resource-limit", "JSON nesting exceeds this canonicalizer's runtime recursion limit") from error
    return text.encode("utf-8")


def canonicalize_json_bytes(raw: bytes) -> bytes:
    return canonicalize(parse_json_bytes(raw, enforce_profile=True))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def descriptor_digest(descriptor: Any) -> str:
    return sha256_hex(canonicalize(descriptor))


def _json_pointer_parts(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        _raise("invalid-json-pointer", f"JSON Pointer must be empty or start with '/': {pointer}")
    parts: list[str] = []
    for raw_part in pointer[1:].split("/"):
        if re.search(r"~(?:[^01]|$)", raw_part):
            _raise("invalid-json-pointer", f"invalid RFC 6901 escape in JSON Pointer: {pointer}")
        part = raw_part.replace("~1", "/").replace("~0", "~")
        parts.append(part)
    return parts


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    current = document
    for part in _json_pointer_parts(pointer):
        if isinstance(current, dict):
            if part not in current:
                _raise("json-pointer-missing", f"JSON Pointer does not exist: {pointer}")
            current = current[part]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", part):
                _raise("invalid-json-pointer", f"array index is not canonical in JSON Pointer: {pointer}")
            index = int(part, 10)
            if index >= len(current):
                _raise("json-pointer-missing", f"array index is outside JSON Pointer target: {pointer}")
            current = current[index]
        else:
            _raise("json-pointer-missing", f"JSON Pointer crosses a scalar: {pointer}")
    return current


def mutate_json_pointer(document: Any, operation: str, pointer: str, value: Any = None) -> Any:
    result = copy.deepcopy(document)
    parts = _json_pointer_parts(pointer)
    if not parts:
        _raise("invalid-json-pointer", "root mutation is not supported by contract vectors")
    parent_pointer = "" if len(parts) == 1 else "/" + "/".join(
        part.replace("~", "~0").replace("/", "~1") for part in parts[:-1]
    )
    parent = resolve_json_pointer(result, parent_pointer)
    final = parts[-1]
    if not isinstance(parent, MutableMapping):
        _raise("invalid-json-pointer", f"mutation parent is not an object: {pointer}")
    if operation == "ADD":
        if final in parent:
            _raise("invalid-vector", f"ADD target already exists: {pointer}")
        parent[final] = copy.deepcopy(value)
    elif operation == "REPLACE":
        if final not in parent:
            _raise("invalid-vector", f"REPLACE target does not exist: {pointer}")
        parent[final] = copy.deepcopy(value)
    elif operation == "REMOVE":
        if final not in parent:
            _raise("invalid-vector", f"REMOVE target does not exist: {pointer}")
        del parent[final]
    else:
        _raise("invalid-vector", f"unknown mutation operation: {operation}")
    return result


def _walk_schema_keyword(value: Any, keyword: str, path: tuple[Any, ...] = ()) -> Iterator[tuple[tuple[Any, ...], Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == keyword:
                yield path, item
            yield from _walk_schema_keyword(item, keyword, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_schema_keyword(item, keyword, path + (index,))


def _walk_refs(value: Any) -> Iterator[str]:
    for _, reference in _walk_schema_keyword(value, "$ref"):
        if not isinstance(reference, str):
            _raise("invalid-schema-ref", "$ref must be a string")
        yield reference


def _schema_anchor_targets(value: Any, anchor: str) -> list[Any]:
    targets: list[Any] = []
    if isinstance(value, dict):
        if value.get("$anchor") == anchor or value.get("$dynamicAnchor") == anchor:
            targets.append(value)
        for item in value.values():
            targets.extend(_schema_anchor_targets(item, anchor))
    elif isinstance(value, list):
        for item in value:
            targets.extend(_schema_anchor_targets(item, anchor))
    return targets


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


class SchemaCatalog:
    """Load Draft 2020-12 source schemas and resolve only repository-local refs."""

    def __init__(self, schema_dir: Path = SCHEMA_DIR):
        self.schema_dir = schema_dir.resolve()
        expected_filenames = set(SCHEMA_FILES.values())
        actual_filenames = {path.name for path in self.schema_dir.glob("*.schema.json")}
        if actual_filenames != expected_filenames:
            _raise("schema-set-mismatch", f"schema source file set differs: {sorted(actual_filenames)}")
        self.paths: dict[str, Path] = {}
        self.schemas: dict[str, Any] = {}
        for schema_name, filename in SCHEMA_FILES.items():
            candidate_path = self.schema_dir / filename
            path = candidate_path.resolve()
            if not _is_within(path, self.schema_dir) or path.name != filename:
                _raise("schema-source-escape", f"schema source must remain in schemas/source: {candidate_path}")
            if not path.is_file():
                _raise("missing-schema", f"missing schema source: {path}")
            schema = load_json(path, enforce_profile=True)
            if not isinstance(schema, dict):
                _raise("invalid-schema", f"{filename} root must be a JSON object")
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                _raise("schema-dialect-mismatch", f"{filename} must declare JSON Schema Draft 2020-12")
            id_locations = list(_walk_schema_keyword(schema, "$id"))
            if id_locations != [((), filename)]:
                _raise("schema-id-mismatch", f"{filename} must have exactly one root $id equal to its filename")
            if list(_walk_schema_keyword(schema, "$dynamicRef")):
                _raise("unsupported-dynamic-ref", f"{filename} may not use $dynamicRef")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise ContractError("invalid-schema", f"{filename} is not a valid Draft 2020-12 schema: {error.message}") from error
            anchors = [anchor for _, anchor in _walk_schema_keyword(schema, "$anchor")]
            anchors.extend(anchor for _, anchor in _walk_schema_keyword(schema, "$dynamicAnchor"))
            if len(anchors) != len(set(anchors)):
                _raise("duplicate-schema-anchor", f"{filename} contains duplicate static/dynamic anchor names")
            self.paths[schema_name] = path
            self.schemas[schema_name] = schema
        self._verify_local_references()
        self.store: dict[str, Any] = {}
        for schema_name, path in self.paths.items():
            schema = self.schemas[schema_name]
            self.store[path.as_uri()] = schema
            self.store[path.name] = schema
        self.registry = None
        if VALIDATOR_SUPPORTS_REGISTRY:
            assert Registry is not None and Resource is not None
            registry = Registry(retrieve=self._reject_registry_retrieval)
            for schema_name, path in self.paths.items():
                resource = Resource.from_contents(self.schemas[schema_name])
                registry = registry.with_resource(path.as_uri(), resource)
            self.registry = registry

    @staticmethod
    def _reject_registry_retrieval(uri: str) -> Any:
        _raise("external-schema-ref", f"schema registry retrieval is forbidden: {uri}")

    def _verify_local_references(self) -> None:
        by_path = {path: self.schemas[name] for name, path in self.paths.items()}
        for schema_name, schema in self.schemas.items():
            source_path = self.paths[schema_name]
            for reference in _walk_refs(schema):
                split = urlsplit(reference)
                if split.scheme or split.netloc or split.query:
                    _raise("external-schema-ref", f"schema ref must be local in {source_path.name}: {reference}")
                reference_path, fragment = urldefrag(reference)
                if reference_path:
                    target_path = (source_path.parent / unquote(reference_path)).resolve()
                else:
                    target_path = source_path
                if not _is_within(target_path, self.schema_dir):
                    _raise("schema-ref-escape", f"schema ref escapes schemas/source in {source_path.name}: {reference}")
                if target_path not in by_path:
                    _raise("missing-schema-ref", f"schema ref target is not a declared local schema: {reference}")
                if fragment:
                    decoded_fragment = unquote(fragment)
                    if decoded_fragment.startswith("/"):
                        target = resolve_json_pointer(by_path[target_path], decoded_fragment)
                    else:
                        anchor_targets = _schema_anchor_targets(by_path[target_path], decoded_fragment)
                        if len(anchor_targets) != 1:
                            _raise(
                                "invalid-schema-ref",
                                f"schema anchor must resolve exactly once: {reference}",
                            )
                        target = anchor_targets[0]
                    if not isinstance(target, dict) and type(target) is not bool:
                        _raise("invalid-schema-ref", f"schema ref target is not a schema object or boolean: {reference}")

    def validate(self, schema_name: str, instance: Any) -> None:
        if schema_name not in self.schemas:
            _raise("unknown-schema", f"unknown schema name: {schema_name}")
        _validate_profile_value(instance)
        schema = self.schemas[schema_name]
        path = self.paths[schema_name]
        if self.registry is not None:
            validator = Draft202012Validator(schema, registry=self.registry)
        else:
            assert RefResolver is not None
            resolver = RefResolver(base_uri=path.as_uri(), referrer=schema, store=self.store)
            validator = Draft202012Validator(schema, resolver=resolver)
        errors = sorted(
            validator.iter_errors(instance),
            key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
        )
        if errors:
            error = errors[0]
            pointer = "".join(
                "/" + str(part).replace("~", "~0").replace("/", "~1")
                for part in error.absolute_path
            )
            location = pointer or "/"
            raise ContractError("schema-validation", f"{schema_name} validation failed at {location}: {error.message}")


def _require_object(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _raise("invalid-vector", f"{context} must be an object")
    return value


def _require_array(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        _raise("invalid-vector", f"{context} must be an array")
    return value


def _json_values_equal(left: Any, right: Any) -> bool:
    return canonicalize(left) == canonicalize(right)


def _require_json_equal(actual: Any, expected: Any, code: str, message: str) -> None:
    if not _json_values_equal(actual, expected):
        _raise(code, message)


def _require_vector_string(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        _raise("invalid-vector", f"{context} must be {'an' if allow_empty else 'a nonempty'} ASCII string")
    return value


def _require_lowercase_sha256(value: Any, context: str) -> str:
    if not isinstance(value, str) or not LOWERCASE_SHA256_RE.fullmatch(value):
        _raise("invalid-vector", f"{context} must be a lowercase SHA-256 hex string")
    return value


def _vector_case_ids(value: Any, context: str) -> list[str]:
    cases = _require_array(value, context)
    ids: list[str] = []
    for index, case in enumerate(cases):
        case_object = _require_object(case, f"{context}/{index}")
        ids.append(_require_vector_string(case_object.get("id"), f"{context}/{index}.id"))
    return ids


def _require_exact_keys(value: Mapping[str, Any], expected: Iterable[str], context: str) -> None:
    _require_object(value, context)
    expected_set = set(expected)
    actual_set = set(value)
    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set)
        unknown = sorted(actual_set - expected_set)
        _raise("invalid-vector", f"{context} keys differ; missing={missing}, unknown={unknown}")


def _require_exact_int(value: Any, context: str) -> int:
    if type(value) is not int:
        _raise("invalid-integer", f"{context} must be an integer")
    if value < SAFE_INTEGER_MIN or value > SAFE_INTEGER_MAX:
        _raise("unsafe-integer", f"{context} is outside the safe signed range")
    return value


def _require_board_size(board_size: Any) -> int:
    board_size = _require_exact_int(board_size, "boardSize")
    if board_size not in BOARD_OFFSETS:
        _raise("unsupported-board-size", f"unsupported board size: {board_size}")
    return board_size


def _require_canvas_point(x: Any, y: Any) -> tuple[int, int]:
    x = _require_exact_int(x, "canvasX")
    y = _require_exact_int(y, "canvasY")
    if not 0 <= x < 19 or not 0 <= y < 19:
        _raise("point-off-board", f"canvas point is outside 19x19: ({x},{y})")
    return x, y


def encode_canvas_action(kind: str, x: Any, y: Any) -> dict[str, Any]:
    if kind not in ACTION_KIND_CODES:
        _raise("unknown-action-kind", f"unknown point action kind: {kind!r}")
    x, y = _require_canvas_point(x, y)
    action_id = 361 * ACTION_KIND_CODES[kind] + 19 * y + x
    return {"schemaVersion": "action-v1", "actionId": action_id, "kind": kind}


def pass_action() -> dict[str, Any]:
    return {"schemaVersion": "action-v1", "actionId": PASS_ACTION_ID, "kind": "PASS"}


def decode_action(action_id: Any) -> dict[str, Any]:
    action_id = _require_exact_int(action_id, "actionId")
    if action_id < 0 or action_id > PASS_ACTION_ID:
        _raise("action-id-out-of-range", f"action ID is outside 0..1444: {action_id}")
    if action_id == PASS_ACTION_ID:
        return pass_action()
    kind_code = action_id // 361
    return {"schemaVersion": "action-v1", "actionId": action_id, "kind": ACTION_CODE_KINDS[kind_code]}


def action_canvas_coordinates(action: Any) -> tuple[int | None, int | None]:
    validate_action_semantics(action)
    if action["kind"] == "PASS":
        return None, None
    point_index = action["actionId"] % 361
    y, x = divmod(point_index, 19)
    return x, y


def encode_semantic_action(kind: str, board_size: Any, x: Any, y: Any) -> dict[str, Any]:
    board_size = _require_board_size(board_size)
    x = _require_exact_int(x, "semanticX")
    y = _require_exact_int(y, "semanticY")
    if not 0 <= x < board_size or not 0 <= y < board_size:
        _raise("point-off-board", f"semantic point is outside {board_size}x{board_size}: ({x},{y})")
    offset = BOARD_OFFSETS[board_size]
    return encode_canvas_action(kind, x + offset, y + offset)


def decode_action_for_board(action_id: Any, board_size: Any) -> tuple[dict[str, Any], int | None, int | None]:
    board_size = _require_board_size(board_size)
    action = decode_action(action_id)
    if action["kind"] == "PASS":
        return action, None, None
    canvas_x, canvas_y = action_canvas_coordinates(action)
    assert canvas_x is not None and canvas_y is not None
    offset = BOARD_OFFSETS[board_size]
    semantic_x = canvas_x - offset
    semantic_y = canvas_y - offset
    if not 0 <= semantic_x < board_size or not 0 <= semantic_y < board_size:
        _raise("point-off-board", f"action {action_id} lies outside centered {board_size}x{board_size} footprint")
    return action, semantic_x, semantic_y


def _expected_early_rejection_code(
    previous_state: Mapping[str, Any],
    candidate_actor: str,
    candidate_intent: Mapping[str, Any],
) -> str | None:
    applicable: set[str] = set()
    if candidate_intent["kind"] == "ACTION":
        action = candidate_intent["action"]
        if action["kind"] != "PASS":
            try:
                decode_action_for_board(action["actionId"], previous_state["boardSize"])
            except ContractError as error:
                if error.code != "point-off-board":
                    raise
                applicable.add("POINT_OFF_BOARD")
        if previous_state["phase"] == "ORDINARY_PLAY" and action["kind"] not in {"NORMAL", "PASS"}:
            applicable.add("INVALID_PHASE")
    if previous_state["phase"] == "TERMINAL":
        applicable.add("TERMINAL_STATE")
    if previous_state["actor"] is not None and candidate_actor != previous_state["actor"]:
        applicable.add("WRONG_ACTOR")
    return next((code for code in REJECTION_PRECEDENCE if code in applicable), None)


def _assert_rejection_precedence(
    previous_state: Mapping[str, Any],
    candidate_actor: str,
    candidate_intent: Mapping[str, Any],
    actual_error_code: str,
    context: str,
) -> None:
    if candidate_intent["kind"] != "ACTION":
        if actual_error_code == "TERMINAL_STATE" and previous_state["phase"] != "TERMINAL":
            _raise("semantic-invariant", f"{context} reports TERMINAL_STATE without a terminal predecessor")
        if actual_error_code == "WRONG_ACTOR" and (
            previous_state["actor"] is None or candidate_actor == previous_state["actor"]
        ):
            _raise("semantic-invariant", f"{context} reports WRONG_ACTOR for the authoritative candidate actor")
        return
    expected = _expected_early_rejection_code(previous_state, candidate_actor, candidate_intent)
    if expected is not None:
        if actual_error_code != expected:
            _raise(
                "semantic-invariant",
                f"{context} must report {expected} before {actual_error_code} under descriptor rejection precedence",
            )
    elif actual_error_code in EARLY_REJECTION_CODES:
        _raise("semantic-invariant", f"{context} reports inapplicable early rejection {actual_error_code}")


def validate_action_semantics(action: Any, catalog: SchemaCatalog | None = None) -> None:
    if catalog is not None:
        catalog.validate("action-v1", action)
    if not isinstance(action, dict):
        _raise("invalid-action", "action must be an object")
    action_id = action.get("actionId")
    expected = decode_action(action_id)
    if action != expected:
        _raise("action-codec-mismatch", f"typed action does not match kind-major ID: expected {expected}")


def transform_canvas_point(x: Any, y: Any, symmetry_id: Any) -> tuple[int, int]:
    x, y = _require_canvas_point(x, y)
    symmetry_id = _require_exact_int(symmetry_id, "symmetryId")
    if symmetry_id < 0 or symmetry_id > 7:
        _raise("invalid-symmetry", f"symmetry ID is outside 0..7: {symmetry_id}")
    if symmetry_id & 2:
        x = 18 - x
    if symmetry_id & 1:
        y = 18 - y
    if symmetry_id & 4:
        x, y = y, x
    return x, y


def transform_action(action: Any, symmetry_id: Any) -> dict[str, Any]:
    validate_action_semantics(action)
    symmetry_id = _require_exact_int(symmetry_id, "symmetryId")
    if symmetry_id < 0 or symmetry_id > 7:
        _raise("invalid-symmetry", f"symmetry ID is outside 0..7: {symmetry_id}")
    if action["kind"] == "PASS":
        return pass_action()
    canvas_x, canvas_y = action_canvas_coordinates(action)
    assert canvas_x is not None and canvas_y is not None
    x, y = transform_canvas_point(canvas_x, canvas_y, symmetry_id)
    return encode_canvas_action(action["kind"], x, y)


def inverse_symmetry_id(symmetry_id: Any) -> int:
    symmetry_id = _require_exact_int(symmetry_id, "symmetryId")
    if symmetry_id < 0 or symmetry_id > 7:
        _raise("invalid-symmetry", f"symmetry ID is outside 0..7: {symmetry_id}")
    return INVERSE_SYMMETRY_IDS[symmetry_id]


def _public_identity(digest: str) -> dict[str, str]:
    return {
        "rulesetId": PUBLIC_RULESET_ID,
        "semanticVersion": PUBLIC_SEMANTIC_VERSION,
        "descriptorSha256": digest,
    }


def _descriptor_identity(descriptor: Mapping[str, Any], digest: str) -> dict[str, str]:
    return {
        "rulesetId": descriptor["identity"]["rulesetId"],
        "semanticVersion": descriptor["identity"]["semanticVersion"],
        "descriptorSha256": digest,
    }


def _expected_identity(identity_or_digest: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(identity_or_digest, str):
        return _public_identity(identity_or_digest)
    return identity_or_digest


def _assert_ruleset_identity(value: Any, identity_or_digest: str | Mapping[str, Any], context: str) -> None:
    if value != _expected_identity(identity_or_digest):
        _raise("ruleset-identity-mismatch", f"{context} does not match the expected rules identity")


def _assert_public_identity(value: Any, digest: str, context: str) -> None:
    _assert_ruleset_identity(value, digest, context)


def validate_descriptor(descriptor: Any, catalog: SchemaCatalog, *, require_public: bool = True) -> str:
    catalog.validate("ruleset-descriptor-v1", descriptor)
    identity = descriptor["identity"]
    if identity["rulesetId"] != PUBLIC_RULESET_ID:
        _raise("descriptor-validation", "rulesetId is not mutago.collapse-go")
    if require_public and identity["semanticVersion"] != PUBLIC_SEMANTIC_VERSION:
        _raise("descriptor-validation", "public semantic version is not 0.1.0-draft")
    if (
        identity["internalVariantEnumIsPublicIdentity"]
        or identity["repositorySlugIsPublicIdentity"]
        or identity["runtimeModeLabelsArePublicIdentity"]
    ):
        _raise("descriptor-validation", "internal enums, repository slugs, and runtime labels are not public identity")
    canonical = descriptor["canonicalization"]
    expected_profile_fields = {
        "profile": CANONICALIZATION_PROFILE,
        "rfc8785Base": True,
        "characterEncoding": "UTF-8",
        "stringDomain": "ASCII",
        "safeIntegerMinimum": SAFE_INTEGER_MIN,
        "safeIntegerMaximum": SAFE_INTEGER_MAX,
        "rejectDuplicateKeys": True,
        "rejectFloatingPoint": True,
        "rejectNonAsciiStrings": True,
        "rejectNonAsciiObjectKeys": True,
        "rejectUnknownDescriptorFields": True,
        "digestAlgorithm": "SHA-256",
        "digestEncoding": "LOWERCASE_HEX",
    }
    for key, expected in expected_profile_fields.items():
        if canonical.get(key) != expected:
            _raise("descriptor-validation", f"canonicalization.{key} differs from the frozen profile")
    versions = descriptor["versions"]
    expected_versions = {
        "rulesetDescriptorSchemaVersion": 1,
        "actionCodecVersion": 1,
        "modelVersion": 19,
        "inputsVersion": 9,
        "trainingSchemaVersion": 1,
        "canvasSize": 19,
        "spatialFeatureCount": 38,
        "globalFeatureCount": 67,
        "flatActionCount": 1445,
    }
    if versions != expected_versions:
        _raise("descriptor-validation", "frozen ABI versions differ")
    if descriptor["initialState"]["initialPSKSeed"] is not True:
        _raise("descriptor-validation", "initialState.initialPSKSeed must be true")
    psk = descriptor["positionalSuperko"]
    if psk["initialPSKSeed"] is not True or psk["initialEmptyOccupancyEntryIndex"] != 0:
        _raise("descriptor-validation", "initial empty occupancy must be PSK history entry zero")
    board_policy = descriptor["boardPolicy"]
    if board_policy["selectedBoardSize"] != descriptor["initialState"]["boardSize"]:
        _raise("descriptor-validation", "selected board size must match the initial state board size")
    if require_public and board_policy["selectedBoardSize"] != 19:
        _raise("descriptor-validation", "public descriptor must select the official 19x19 board")
    expected_point_encoding = {
        "domain": "BOARD_LOCAL_ROW_MAJOR",
        "formula": "BOARD_SIZE*Y+X",
        "minimum": 0,
        "maximumRule": "BOARD_SIZE*BOARD_SIZE-1",
        "independentOfCenteredActionCanvas": True,
        "usedBy": [
            "OCCUPANCY",
            "STONES",
            "CAPTURES",
            "LIBERTIES",
            "PSK_HISTORY",
            "SETTLEMENT_REMOVALS",
        ],
    }
    if board_policy["semanticPointEncoding"] != expected_point_encoding:
        _raise("descriptor-validation", "semantic projection point encoding differs")
    if board_policy["runtimeClassificationLabelsAffectIdentity"]:
        _raise("descriptor-validation", "runtime board classifications cannot affect semantic identity")
    if [board["size"] for board in board_policy["allowedBoardSizes"]] != [9, 13, 19]:
        _raise("descriptor-validation", "board-size policy must enumerate centered 9, 13, and 19 in order")
    for board in board_policy["allowedBoardSizes"]:
        size = board["size"]
        expected_threshold = (150 * size * size + 180) // 361
        if BOARD_THRESHOLDS.get(size) != expected_threshold or board["threshold"] != expected_threshold:
            _raise("descriptor-validation", f"threshold policy mismatch for board size {size}")
        if board["canvasOffsetX"] != BOARD_OFFSETS[size] or board["canvasOffsetY"] != BOARD_OFFSETS[size]:
            _raise("descriptor-validation", f"centering mismatch for board size {size}")
    action_space = descriptor["actionSpace"]
    if action_space["layout"] != "KIND_MAJOR" or action_space["passActionId"] != PASS_ACTION_ID:
        _raise("descriptor-validation", "action space is not the frozen kind-major layout")
    if action_space["canonicalJsonEnvelopeFields"] != ["schemaVersion", "actionId", "kind"]:
        _raise("descriptor-validation", "canonical action envelope fields differ")
    if not action_space["coordinatesDerivedUniquelyFromActionId"] or action_space["redundantCoordinateFieldsAllowed"]:
        _raise("descriptor-validation", "action coordinates must be derived and redundant fields rejected")
    for family in action_space["pointFamilies"]:
        kind = family["kind"]
        code = ACTION_KIND_CODES[kind]
        if family != {
            "kind": kind,
            "kindCode": code,
            "firstActionId": 361 * code,
            "lastActionId": 361 * code + 360,
        }:
            _raise("descriptor-validation", f"action family boundary mismatch for {kind}")
    quotas = descriptor["quotas"]
    official_quota = {"IMMORTAL": 1, "DOUBLE_START": 1, "EIGHTWAY": 1}
    if require_public and quotas["initialByPlayer"] != {"BLACK": official_quota, "WHITE": official_quota}:
        _raise("descriptor-validation", "public complete per-player quota vectors are not 1/1/1")
    if quotas["configurableQuotaDomain"] != "PER_PLAYER_INDEPENDENT_NONNEGATIVE_SAFE_INTEGER_VECTOR":
        _raise("descriptor-validation", "quota configuration domain differs")
    if quotas["runtimeExperimentalLabelAffectsIdentity"]:
        _raise("descriptor-validation", "runtime quota labels cannot affect semantic identity")
    event_model = descriptor["eventModel"]
    expected_event_commit_fields = {
        "acceptedImmediateTerminalEventCount": 1,
        "scoringTransitionAddsTerminalEventAfterFinalPass": True,
        "stateRevisionIncrementPerAcceptedCandidate": 1,
        "committedLogPositionIncrementPerEmittedSemanticEvent": 1,
        "rejectedCandidateRevisionAndLogIncrement": 0,
    }
    for key, expected in expected_event_commit_fields.items():
        if event_model[key] != expected:
            _raise("descriptor-validation", f"eventModel.{key} differs from the semantic commit boundary")
    if descriptor["abilities"]["DOUBLE_MOVE"]["startLegalityCondition"] != "A+2<=T":
        _raise("descriptor-validation", "Double start threshold condition differs")
    placement = descriptor["placementTransaction"]
    if placement["orderedSteps"][0] != "VALIDATE_CANONICAL_ACTION_KIND_AND_CENTERED_BOARD_FOOTPRINT":
        _raise("descriptor-validation", "placement transaction must fail closed on action kind and board footprint first")
    if (
        placement["rejectionCodeSelection"] != "FIRST_APPLICABLE_IN_REJECTION_PRECEDENCE"
        or placement["rejectionPrecedence"] != list(REJECTION_PRECEDENCE)
    ):
        _raise("descriptor-validation", "rejection error-code precedence differs from the frozen contract")
    if descriptor["deadStoneHandling"]["mvpShortcutStatus"] != "DEFERRED":
        _raise("descriptor-validation", "MVP dead-stone shortcut must remain deferred")
    scoring = descriptor["scoring"]
    if scoring["komi"] != {"recipient": "WHITE", "numerator": 15, "denominator": 2}:
        _raise("descriptor-validation", "komi must be represented exactly as 15/2 for White")
    expected_scoring_fields = {
        "scoreDenominator": 2,
        "blackScoreNumeratorFormula": "2*(BLACK_STONES+BLACK_EMPTY_AREA)",
        "whiteScoreNumeratorFormula": "2*(WHITE_STONES+WHITE_EMPTY_AREA)+15",
        "marginNumeratorFormula": "ABS(BLACK_SCORE_NUMERATOR-WHITE_SCORE_NUMERATOR)",
        "tiePossible": False,
    }
    for key, expected in expected_scoring_fields.items():
        if scoring[key] != expected:
            _raise("descriptor-validation", f"scoring.{key} differs from exact Chinese-area scoring")
    termination = descriptor["termination"]
    for key in ("ordinaryPlayTwoConsecutivePasses", "resignation", "timeout"):
        behavior = termination[key]
        if not behavior["emitsTerminalEvent"] or not behavior["terminalEventHasStablePostState"]:
            _raise("descriptor-validation", f"{key} must emit a stable terminal event")
        if not behavior["appendsStableOccupancyToPSK"]:
            _raise("descriptor-validation", f"{key} must append terminal stable occupancy to PSK")
    expected_preserved = [
        "BOARD_OCCUPANCY",
        "STONES_AND_SOURCE_IDENTITIES",
        "ATOMIC_ACTION_COUNT",
        "CONSECUTIVE_PASSES",
        "SETTLEMENT_COMPLETED",
        "PENDING_DOUBLE",
        "QUOTAS",
        "SPECIAL_EVENT_LEDGER",
    ]
    expected_changed = [
        "PHASE",
        "CURRENT_ACTOR",
        "TERMINAL_RESULT",
        "STATE_REVISION",
        "LOG_POSITION",
        "PSK_HISTORY",
    ]
    for key in ("resignation", "timeout"):
        behavior = termination[key]
        if behavior["acceptedAtExposedDecisionBoundaries"] != ["COLLAPSE_PLAY", "ORDINARY_PLAY"]:
            _raise("descriptor-validation", f"{key} exposed acceptance boundaries differ")
        if not behavior["acceptedDuringPendingDouble"]:
            _raise("descriptor-validation", f"{key} must be accepted during pending Double")
        if behavior["settlementIntentAcceptanceBoundary"] != "NONE_SETTLEMENT_IS_ATOMIC_AND_UNEXPOSED":
            _raise("descriptor-validation", f"{key} must not invent an intent boundary inside settlement")
        if behavior["preservedStateFields"] != expected_preserved or behavior["changedStateFields"] != expected_changed:
            _raise("descriptor-validation", f"{key} terminal state preservation contract differs")
    canonical_descriptor = canonicalize(descriptor)
    digest = sha256_hex(canonical_descriptor)
    if identity["semanticVersion"] == PUBLIC_SEMANTIC_VERSION:
        official_descriptor = load_json(DESCRIPTOR_PATH, enforce_profile=True)
        if canonical_descriptor != canonicalize(official_descriptor):
            _raise(
                "descriptor-validation",
                "semanticVersion 0.1.0-draft may identify only the official canonical descriptor",
            )
    if not LOWERCASE_SHA256_RE.fullmatch(digest):
        _raise("descriptor-validation", "descriptor digest is not lowercase SHA-256")
    return digest


def _decode_vector_input(input_value: Any, context: str) -> bytes:
    if not isinstance(input_value, dict):
        _raise("invalid-vector", f"{context}.input must be an object")
    _require_exact_keys(input_value, ("encoding", "data"), f"{context}.input")
    if input_value["encoding"] != "UTF-8-HEX":
        _raise("invalid-vector", f"{context}.input encoding must be UTF-8-HEX")
    data = input_value["data"]
    if not isinstance(data, str) or not LOWERCASE_HEX_RE.fullmatch(data):
        _raise("invalid-vector", f"{context}.input.data must be lowercase even-length hex")
    return bytes.fromhex(data)


def verify_canonicalization_vectors(path: Path = VECTOR_DIR / "canonicalization-v1.json") -> None:
    vectors = load_json(path, enforce_profile=True)
    if not isinstance(vectors, dict):
        _raise("invalid-vector", "canonicalization vector root must be an object")
    _require_exact_keys(vectors, ("vectorVersion", "profile", "validCases", "invalidCases"), "canonicalization vectors")
    if vectors["vectorVersion"] != "canonicalization-v1" or vectors["profile"] != CANONICALIZATION_PROFILE:
        _raise("invalid-vector", "canonicalization vector version/profile mismatch")
    expected_valid_ids = [
        "empty-object",
        "ascii-key-order",
        "nested-safe-integers",
        "escape-normalization",
        "negative-zero-integer",
        "top-level-array",
        "control-escapes-and-del",
    ]
    expected_invalid_ids = [
        "duplicate-top-level-key",
        "duplicate-nested-key",
        "duplicate-escaped-key-alias",
        "floating-point-decimal",
        "floating-point-exponent",
        "unsafe-positive-integer",
        "unsafe-negative-integer",
        "overlong-positive-integer",
        "non-ascii-string",
        "non-ascii-key",
        "escaped-non-ascii-string",
        "escaped-non-ascii-key",
        "lone-surrogate-string",
        "non-json-number",
        "invalid-utf8",
        "malformed-json",
        "leading-zero-integer",
    ]
    if _vector_case_ids(vectors["validCases"], "canonicalization valid cases") != expected_valid_ids:
        _raise("vector-coverage", "canonicalization valid-case inventory differs")
    if _vector_case_ids(vectors["invalidCases"], "canonicalization invalid cases") != expected_invalid_ids:
        _raise("vector-coverage", "canonicalization invalid-case inventory differs")
    seen: set[str] = set()
    for case in vectors["validCases"]:
        _require_exact_keys(case, ("id", "input", "expectedCanonicalUtf8", "sha256"), "canonicalization valid case")
        case_id = case["id"]
        if case_id in seen:
            _raise("invalid-vector", f"duplicate canonicalization case ID: {case_id}")
        seen.add(case_id)
        raw = _decode_vector_input(case["input"], case_id)
        canonical = canonicalize_json_bytes(raw)
        expected_text = _require_vector_string(
            case["expectedCanonicalUtf8"],
            f"{case_id}.expectedCanonicalUtf8",
            allow_empty=True,
        )
        expected = expected_text.encode("utf-8")
        if canonical != expected:
            _raise("vector-mismatch", f"canonical bytes differ for {case_id}")
        digest = sha256_hex(canonical)
        expected_digest = _require_lowercase_sha256(case["sha256"], f"{case_id}.sha256")
        if digest != expected_digest:
            _raise("vector-mismatch", f"canonical SHA-256 differs for {case_id}")
    for case in vectors["invalidCases"]:
        _require_exact_keys(case, ("id", "input", "expectedErrorCode"), "canonicalization invalid case")
        case_id = case["id"]
        if case_id in seen:
            _raise("invalid-vector", f"duplicate canonicalization case ID: {case_id}")
        seen.add(case_id)
        raw = _decode_vector_input(case["input"], case_id)
        expected_error_code = _require_vector_string(case["expectedErrorCode"], f"{case_id}.expectedErrorCode")
        try:
            canonicalize_json_bytes(raw)
        except ContractError as error:
            if error.code != expected_error_code:
                _raise("vector-mismatch", f"{case_id} expected {expected_error_code}, got {error.code}")
        else:
            _raise("vector-mismatch", f"invalid canonicalization case unexpectedly succeeded: {case_id}")


def verify_descriptor_invalid_vectors(
    catalog: SchemaCatalog,
    path: Path = VECTOR_DIR / "descriptor-invalid-v1.json",
) -> None:
    vectors = load_json(path, enforce_profile=True)
    _require_exact_keys(vectors, ("vectorVersion", "baseDescriptor", "cases"), "descriptor invalid vectors")
    if vectors["vectorVersion"] != "descriptor-invalid-v1":
        _raise("invalid-vector", "descriptor invalid vector version mismatch")
    base_descriptor = _require_vector_string(vectors["baseDescriptor"], "descriptor invalid baseDescriptor")
    base_path = (path.parent / base_descriptor).resolve()
    if base_path != DESCRIPTOR_PATH.resolve():
        _raise("invalid-vector", "descriptor invalid vectors must target the public descriptor")
    base = load_json(base_path, enforce_profile=True)
    expected_case_ids = [
        "unknown-top-level-field",
        "unknown-nested-field",
        "missing-public-ruleset-id",
        "repository-slug-is-not-public-id",
        "initial-psk-seed-must-be-true",
        "initial-state-psk-seed-must-be-true",
        "point-major-layout-rejected",
        "dead-stone-shortcut-is-deferred",
        "digest-encoding-must-be-lowercase",
        "semantic-version-is-frozen",
        "official-version-semantic-drift-rejected-nonpublic",
    ]
    if _vector_case_ids(vectors["cases"], "descriptor invalid cases") != expected_case_ids:
        _raise("vector-coverage", "descriptor invalid-case inventory differs")
    seen: set[str] = set()
    for case in vectors["cases"]:
        required = {"id", "operation", "jsonPointer", "expectedErrorCode"}
        optional = {"value", "requirePublic"}
        actual = set(case)
        if not required.issubset(actual) or not actual.issubset(required | optional):
            _raise("invalid-vector", f"descriptor invalid case keys differ: {case.get('id')}")
        case_id = case["id"]
        if case_id in seen:
            _raise("invalid-vector", f"duplicate descriptor invalid case ID: {case_id}")
        seen.add(case_id)
        operation = _require_vector_string(case["operation"], f"{case_id}.operation")
        pointer = _require_vector_string(case["jsonPointer"], f"{case_id}.jsonPointer", allow_empty=True)
        expected_error_code = _require_vector_string(case["expectedErrorCode"], f"{case_id}.expectedErrorCode")
        require_public = case.get("requirePublic", True)
        if type(require_public) is not bool:
            _raise("invalid-vector", f"{case_id}.requirePublic must be a boolean")
        mutated = mutate_json_pointer(base, operation, pointer, case.get("value"))
        try:
            validate_descriptor(mutated, catalog, require_public=require_public)
        except ContractError as error:
            if error.code != expected_error_code:
                _raise("vector-mismatch", f"{case_id} expected {expected_error_code}, got {error.code}")
        else:
            _raise("vector-mismatch", f"invalid descriptor case unexpectedly succeeded: {case_id}")


def _exhaustive_action_codec_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for action_id in range(PASS_ACTION_ID + 1):
        action = decode_action(action_id)
        canvas_x, canvas_y = action_canvas_coordinates(action)
        records.append(
            {
                "actionId": action_id,
                "kind": action["kind"],
                "canvasX": canvas_x,
                "canvasY": canvas_y,
            }
        )
    return records


def _exhaustive_centered_mapping_records(board_size: int) -> list[dict[str, Any]]:
    offset = BOARD_OFFSETS[board_size]
    records: list[dict[str, Any]] = []
    for semantic_y in range(board_size):
        for semantic_x in range(board_size):
            canvas_x = semantic_x + offset
            canvas_y = semantic_y + offset
            canvas_point = 19 * canvas_y + canvas_x
            records.append(
                {
                    "semanticX": semantic_x,
                    "semanticY": semantic_y,
                    "semanticPointIndex": board_size * semantic_y + semantic_x,
                    "canvasX": canvas_x,
                    "canvasY": canvas_y,
                    "canvasPointIndex": canvas_point,
                    "actionIds": {
                        kind: 361 * kind_code + canvas_point
                        for kind, kind_code in ACTION_KIND_CODES.items()
                    },
                }
            )
    return records


def _exhaustive_board_footprint_records(
    board_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for action_id in range(PASS_ACTION_ID + 1):
        action = decode_action(action_id)
        try:
            _, semantic_x, semantic_y = decode_action_for_board(action_id, board_size)
        except ContractError as error:
            if error.code != "point-off-board":
                raise
            rejected.append(
                {
                    "actionId": action_id,
                    "kind": action["kind"],
                    "expectedErrorCode": error.code,
                }
            )
        else:
            accepted.append(
                {
                    "actionId": action_id,
                    "kind": action["kind"],
                    "semanticX": semantic_x,
                    "semanticY": semantic_y,
                }
            )
    return accepted, rejected


def _exhaustive_d4_action_ids(symmetry_id: int) -> list[int]:
    return [transform_action(decode_action(action_id), symmetry_id)["actionId"] for action_id in range(PASS_ACTION_ID + 1)]


def verify_action_vectors(catalog: SchemaCatalog, path: Path = VECTOR_DIR / "action-v1.json") -> None:
    vectors = load_json(path, enforce_profile=True)
    _require_exact_keys(
        vectors,
        (
            "vectorVersion",
            "constants",
            "exhaustiveCodec",
            "familyBoundaries",
            "centeredMappings",
            "exhaustiveCenteredMappings",
            "exhaustiveBoardFootprints",
            "offBoardRejections",
            "invalidEnvelopes",
            "d4RoundTrips",
            "exhaustiveD4",
        ),
        "action vectors",
    )
    if vectors["vectorVersion"] != "action-v1":
        _raise("invalid-vector", "action vector version mismatch")
    expected_constants = {
        "canvasSize": 19,
        "canvasPointCount": 361,
        "kindStride": 361,
        "flatActionCount": 1445,
        "passActionId": 1444,
        "boardOffsets": {"9": 5, "13": 3, "19": 0},
        "semanticPointEncoding": "BOARD_LOCAL_ROW_MAJOR",
        "inverseSymmetryIds": list(INVERSE_SYMMETRY_IDS),
    }
    _require_json_equal(
        vectors["constants"],
        expected_constants,
        "vector-mismatch",
        "action vector constants differ from Action Schema V1",
    )
    exhaustive_records = _exhaustive_action_codec_records()
    for action_id in range(PASS_ACTION_ID + 1):
        validate_action_semantics(decode_action(action_id), catalog)
    expected_exhaustive_codec = {
        "recordCount": 1445,
        "recordOrder": "ACTION_ID_ASCENDING",
        "recordFields": ["actionId", "kind", "canvasX", "canvasY"],
        "canonicalRecordsSha256": sha256_hex(canonicalize(exhaustive_records)),
    }
    _require_json_equal(
        vectors["exhaustiveCodec"],
        expected_exhaustive_codec,
        "vector-mismatch",
        "exhaustive 1445-action codec digest differs",
    )
    expected_centered_ids = [
        f"n{size}-{label}"
        for size in (9, 13, 19)
        for label in ("top-left", "asymmetric", "center", "bottom-right")
    ]
    if _vector_case_ids(vectors["centeredMappings"], "centered mapping cases") != expected_centered_ids:
        _raise("vector-coverage", "centered mapping case inventory differs")
    expected_offboard_ids = [
        f"semantic-n{size}-{kind.lower()}-{label}"
        for size in (9, 13, 19)
        for kind in ACTION_KIND_CODES
        for label in ("x-negative", "x-too-large", "y-negative", "y-too-large")
    ]
    expected_offboard_ids += [
        f"canvas-footprint-n{size}-{kind.lower()}-{label}"
        for size in (9, 13)
        for kind in ACTION_KIND_CODES
        for label in ("left", "right", "top", "bottom")
    ]
    expected_offboard_ids += [
        f"canvas-{kind.lower()}-{label}"
        for kind in ACTION_KIND_CODES
        for label in ("x-negative", "x-too-large", "y-negative", "y-too-large")
    ]
    expected_offboard_ids += [
        "semantic-x-noninteger",
        "semantic-board-unsupported",
        "semantic-board-boolean",
        "canvas-x-noninteger",
        "decode-noninteger",
        "decode-boolean",
        "decode-negative",
        "decode-too-large",
        "unknown-kind",
    ]
    if _vector_case_ids(vectors["offBoardRejections"], "off-board rejection cases") != expected_offboard_ids:
        _raise("vector-coverage", "off-board rejection case inventory differs")
    expected_invalid_envelope_ids = [
        "unknown-schema-version",
        "action-id-kind-mismatch",
        "redundant-coordinate-field",
        "missing-schema-version",
        "missing-action-id",
        "missing-kind",
        "unknown-envelope-kind",
    ]
    if _vector_case_ids(vectors["invalidEnvelopes"], "invalid action envelope cases") != expected_invalid_envelope_ids:
        _raise("vector-coverage", "invalid action-envelope case inventory differs")
    expected_d4_ids = [
        f"d4-n{size}-{kind.lower()}-s{symmetry}"
        for size in (9, 13, 19)
        for kind in ACTION_KIND_CODES
        for symmetry in range(8)
    ] + [f"d4-pass-s{symmetry}" for symmetry in range(8)]
    if _vector_case_ids(vectors["d4RoundTrips"], "D4 round-trip cases") != expected_d4_ids:
        _raise("vector-coverage", "D4 round-trip case inventory differs")
    family_boundaries = _require_array(vectors["familyBoundaries"], "action family boundaries")
    boundary_kinds = [
        _require_object(case, f"action family boundaries/{index}").get("kind")
        for index, case in enumerate(family_boundaries)
    ]
    expected_boundary_kinds = ["NORMAL", "IMMORTAL", "DOUBLE_START", "EIGHTWAY", "PASS"]
    if boundary_kinds != expected_boundary_kinds:
        _raise("vector-mismatch", "action family boundary order differs")
    for case in family_boundaries:
        _require_exact_keys(case, ("kind", "kindCode", "first", "last"), "action family boundary case")
        kind = case["kind"]
        for endpoint in ("first", "last"):
            validate_action_semantics(case[endpoint], catalog)
        if kind == "PASS":
            if case["kindCode"] is not None or case["first"] != pass_action() or case["last"] != pass_action():
                _raise("vector-mismatch", "PASS boundary differs")
        else:
            code = ACTION_KIND_CODES[kind]
            if _require_exact_int(case["kindCode"], f"{kind}.kindCode") != code:
                _raise("vector-mismatch", f"kind code differs for {kind}")
            if case["first"] != encode_canvas_action(kind, 0, 0):
                _raise("vector-mismatch", f"first action differs for {kind}")
            if case["last"] != encode_canvas_action(kind, 18, 18):
                _raise("vector-mismatch", f"last action differs for {kind}")
    for case in vectors["centeredMappings"]:
        _require_exact_keys(
            case,
            (
                "id",
                "boardSize",
                "semanticX",
                "semanticY",
                "semanticPointIndex",
                "canvasX",
                "canvasY",
                "canvasPointIndex",
                "actionIds",
            ),
            "centered mapping case",
        )
        board_size = _require_board_size(case["boardSize"])
        semantic_x = _require_exact_int(case["semanticX"], f"{case['id']}.semanticX")
        semantic_y = _require_exact_int(case["semanticY"], f"{case['id']}.semanticY")
        offset = BOARD_OFFSETS[board_size]
        expected_semantic_point = board_size * semantic_y + semantic_x
        if _require_exact_int(case["semanticPointIndex"], f"{case['id']}.semanticPointIndex") != expected_semantic_point:
            _raise("vector-mismatch", f"board-local point index differs for {case['id']}")
        expected_canvas_x = semantic_x + offset
        expected_canvas_y = semantic_y + offset
        if (
            _require_exact_int(case["canvasX"], f"{case['id']}.canvasX") != expected_canvas_x
            or _require_exact_int(case["canvasY"], f"{case['id']}.canvasY") != expected_canvas_y
        ):
            _raise("vector-mismatch", f"centered mapping differs for {case['id']}")
        expected_canvas_point = 19 * expected_canvas_y + expected_canvas_x
        if _require_exact_int(case["canvasPointIndex"], f"{case['id']}.canvasPointIndex") != expected_canvas_point:
            _raise("vector-mismatch", f"canvas point index differs for {case['id']}")
        expected_ids = {
            kind: encode_semantic_action(kind, board_size, semantic_x, semantic_y)["actionId"]
            for kind in ACTION_KIND_CODES
        }
        _require_json_equal(
            case["actionIds"],
            expected_ids,
            "vector-mismatch",
            f"centered action IDs differ for {case['id']}",
        )
    expected_exhaustive_centered = {
        "recordOrder": "SEMANTIC_ROW_MAJOR",
        "recordFields": [
            "semanticX",
            "semanticY",
            "semanticPointIndex",
            "canvasX",
            "canvasY",
            "canvasPointIndex",
            "actionIds",
        ],
        "perBoard": {
            str(board_size): {
                "recordCount": board_size * board_size,
                "canonicalRecordsSha256": sha256_hex(
                    canonicalize(_exhaustive_centered_mapping_records(board_size))
                ),
            }
            for board_size in (9, 13, 19)
        },
    }
    _require_json_equal(
        vectors["exhaustiveCenteredMappings"],
        expected_exhaustive_centered,
        "vector-mismatch",
        "exhaustive centered semantic-to-action mapping digests differ",
    )
    expected_footprints: dict[str, Any] = {
        "inputOrder": "ACTION_ID_ASCENDING",
        "acceptedRecordFields": ["actionId", "kind", "semanticX", "semanticY"],
        "rejectedRecordFields": ["actionId", "kind", "expectedErrorCode"],
        "perBoard": {},
    }
    for board_size in (9, 13, 19):
        accepted_records, rejected_records = _exhaustive_board_footprint_records(board_size)
        expected_footprints["perBoard"][str(board_size)] = {
            "acceptedRecordCount": len(accepted_records),
            "acceptedCanonicalRecordsSha256": sha256_hex(canonicalize(accepted_records)),
            "rejectedRecordCount": len(rejected_records),
            "rejectedCanonicalRecordsSha256": sha256_hex(canonicalize(rejected_records)),
        }
    _require_json_equal(
        vectors["exhaustiveBoardFootprints"],
        expected_footprints,
        "vector-mismatch",
        "exhaustive centered-board acceptance/rejection digests differ",
    )
    for case in vectors["offBoardRejections"]:
        case_id = case["id"]
        operation = _require_vector_string(case["operation"], f"{case_id}.operation")
        expected_keys_by_operation = {
            "ENCODE_SEMANTIC": ("id", "operation", "boardSize", "kind", "x", "y", "expectedErrorCode"),
            "DECODE_FOR_BOARD": ("id", "operation", "boardSize", "actionId", "expectedErrorCode"),
            "DECODE": ("id", "operation", "actionId", "expectedErrorCode"),
            "ENCODE_CANVAS": ("id", "operation", "kind", "x", "y", "expectedErrorCode"),
        }
        if operation not in expected_keys_by_operation:
            _raise("invalid-vector", f"unknown off-board vector operation: {operation}")
        _require_exact_keys(case, expected_keys_by_operation[operation], "off-board rejection case")
        expected_error_code = _require_vector_string(case["expectedErrorCode"], f"{case_id}.expectedErrorCode")
        try:
            if operation == "ENCODE_SEMANTIC":
                encode_semantic_action(case["kind"], case["boardSize"], case["x"], case["y"])
            elif operation == "DECODE_FOR_BOARD":
                decode_action_for_board(case["actionId"], case["boardSize"])
            elif operation == "DECODE":
                decode_action(case["actionId"])
            elif operation == "ENCODE_CANVAS":
                encode_canvas_action(case["kind"], case["x"], case["y"])
            else:
                _raise("invalid-vector", f"unknown off-board vector operation: {operation}")
        except ContractError as error:
            if error.code != expected_error_code:
                _raise("vector-mismatch", f"{case_id} expected {expected_error_code}, got {error.code}")
        else:
            _raise("vector-mismatch", f"off-board case unexpectedly succeeded: {case_id}")
    for case in vectors["invalidEnvelopes"]:
        _require_exact_keys(case, ("id", "action", "expectedErrorCode"), "invalid action envelope case")
        case_id = case["id"]
        expected_error_code = _require_vector_string(case["expectedErrorCode"], f"{case_id}.expectedErrorCode")
        try:
            validate_action_semantics(case["action"], catalog)
        except ContractError as error:
            if error.code != expected_error_code:
                _raise("vector-mismatch", f"{case_id} expected {expected_error_code}, got {error.code}")
        else:
            _raise("vector-mismatch", f"invalid action envelope unexpectedly succeeded: {case_id}")
    for case in vectors["d4RoundTrips"]:
        _require_exact_keys(
            case,
            (
                "id",
                "boardSize",
                "symmetryId",
                "inverseSymmetryId",
                "inputAction",
                "expectedAction",
                "expectedSemanticX",
                "expectedSemanticY",
            ),
            "D4 round-trip case",
        )
        validate_action_semantics(case["inputAction"], catalog)
        validate_action_semantics(case["expectedAction"], catalog)
        board_size = _require_board_size(case["boardSize"])
        symmetry_id = _require_exact_int(case["symmetryId"], f"{case['id']}.symmetryId")
        expected_inverse = inverse_symmetry_id(symmetry_id)
        if _require_exact_int(case["inverseSymmetryId"], f"{case['id']}.inverseSymmetryId") != expected_inverse:
            _raise("vector-mismatch", f"inverse symmetry differs for {case['id']}")
        transformed = transform_action(case["inputAction"], symmetry_id)
        if transformed != case["expectedAction"]:
            _raise("vector-mismatch", f"D4 output differs for {case['id']}")
        round_trip = transform_action(transformed, expected_inverse)
        if round_trip != case["inputAction"]:
            _raise("vector-mismatch", f"D4 round trip differs for {case['id']}")
        if transformed["kind"] == "PASS":
            if case["expectedSemanticX"] is not None or case["expectedSemanticY"] is not None:
                _raise("vector-mismatch", f"PASS semantic coordinates must be null for {case['id']}")
        else:
            _, semantic_x, semantic_y = decode_action_for_board(transformed["actionId"], board_size)
            expected_semantic_x = _require_exact_int(case["expectedSemanticX"], f"{case['id']}.expectedSemanticX")
            expected_semantic_y = _require_exact_int(case["expectedSemanticY"], f"{case['id']}.expectedSemanticY")
            if semantic_x != expected_semantic_x or semantic_y != expected_semantic_y:
                _raise("vector-mismatch", f"D4 semantic coordinates differ for {case['id']}")
    expected_exhaustive_d4 = {
        "recordCountPerSymmetry": 1445,
        "inputOrder": "ACTION_ID_ASCENDING",
        "output": "TRANSFORMED_ACTION_ID_ARRAY",
        "perSymmetryCanonicalArraySha256": {
            str(symmetry_id): sha256_hex(canonicalize(_exhaustive_d4_action_ids(symmetry_id)))
            for symmetry_id in range(8)
        },
    }
    _require_json_equal(
        vectors["exhaustiveD4"],
        expected_exhaustive_d4,
        "vector-mismatch",
        "exhaustive D4 action permutation digests differ",
    )


def _assert_strictly_sorted_unique(values: Sequence[int], context: str) -> None:
    if list(values) != sorted(values) or len(values) != len(set(values)):
        _raise("semantic-invariant", f"{context} must be strictly sorted and unique")


def _validate_occupancy(occupancy: Any, board_size: int, context: str) -> None:
    max_point = board_size * board_size - 1
    black = occupancy["black"]
    white = occupancy["white"]
    _assert_strictly_sorted_unique(black, f"{context}.black")
    _assert_strictly_sorted_unique(white, f"{context}.white")
    if any(point > max_point for point in black + white):
        _raise("semantic-invariant", f"{context} contains a point outside {board_size}x{board_size}")
    if set(black) & set(white):
        _raise("semantic-invariant", f"{context} has overlapping black and white occupancy")


def _quota_keys() -> tuple[str, ...]:
    return ("IMMORTAL", "DOUBLE_START", "EIGHTWAY")


def _validate_projection(
    projection: Any,
    catalog: SchemaCatalog,
    identity_or_digest: str | Mapping[str, Any],
) -> None:
    catalog.validate("semantic-projection-v1", projection)
    _assert_ruleset_identity(projection["ruleset"], identity_or_digest, "semantic projection ruleset")
    if projection["pointEncoding"] != "BOARD_LOCAL_ROW_MAJOR":
        _raise("semantic-invariant", "semantic projection point encoding differs")
    state = projection["state"]
    board_size = state["boardSize"]
    max_board_point = board_size * board_size - 1
    if state["threshold"] != BOARD_THRESHOLDS[board_size]:
        _raise("semantic-invariant", "semantic projection threshold does not match board size")
    _validate_occupancy(state["occupancy"], board_size, "state.occupancy")
    for index, occupancy in enumerate(state["pskHistory"]):
        _validate_occupancy(occupancy, board_size, f"state.pskHistory/{index}")
    empty = {"black": [], "white": []}
    if state["pskHistory"][0] != empty:
        _raise("semantic-invariant", "PSK history entry zero must be the initial empty occupancy")
    if len(state["pskHistory"]) != state["logPosition"] + 1:
        _raise("semantic-invariant", "PSK history length must equal committed log position plus the initial seed")
    if state["pskHistory"][-1] != state["occupancy"]:
        _raise("semantic-invariant", "latest PSK history occupancy must equal the stable visible occupancy")
    occupied_by_color = {
        "BLACK": set(state["occupancy"]["black"]),
        "WHITE": set(state["occupancy"]["white"]),
    }
    stone_points: set[int] = set()
    source_ids: set[str] = set()
    ordered_stone_points = [stone["point"] for stone in state["stones"]]
    if ordered_stone_points != sorted(ordered_stone_points):
        _raise("semantic-invariant", "stable stones must be ordered by board-local point")
    for stone in state["stones"]:
        point = stone["point"]
        if point in stone_points:
            _raise("semantic-invariant", "multiple stable stones share one point")
        stone_points.add(point)
        if stone["sourceId"] in source_ids:
            _raise("semantic-invariant", "stable source IDs must be unique")
        source_ids.add(stone["sourceId"])
        if stone["sourceId"] != f"stone-{stone['originActionNumber']}":
            _raise("semantic-invariant", "stable stone source IDs must use canonical origin-action labels")
        if stone["originActionNumber"] > state["atomicActionCount"]:
            _raise("semantic-invariant", "stone origin action cannot be after the current atomic action count")
        if point not in occupied_by_color[stone["color"]]:
            _raise("semantic-invariant", "stable stone color/point differs from occupancy")
    if stone_points != occupied_by_color["BLACK"] | occupied_by_color["WHITE"]:
        _raise("semantic-invariant", "stable stones must cover every occupied point exactly once")
    stone_by_source = {stone["sourceId"]: stone for stone in state["stones"]}
    for color in ("BLACK", "WHITE"):
        for quota_kind in _quota_keys():
            initial = state["initialQuotas"][color][quota_kind]
            remaining = state["remainingQuotas"][color][quota_kind]
            used = state["usedQuotas"][color][quota_kind]
            expired = state["expiredQuotas"][color][quota_kind]
            if initial != remaining + used + expired:
                _raise("semantic-invariant", f"quota accounting differs for {color}/{quota_kind}")
    ledger_ids: set[str] = set()
    ledger_orders: list[int] = []
    ledger_counts = {
        "BLACK": {kind: 0 for kind in _quota_keys()},
        "WHITE": {kind: 0 for kind in _quota_keys()},
    }
    for entry in state["ledger"]:
        if entry["sourcePoint"] > max_board_point:
            _raise("semantic-invariant", "ledger sourcePoint lies outside the selected board")
        if entry["eventId"] in ledger_ids:
            _raise("semantic-invariant", "ledger event IDs must be unique")
        ledger_ids.add(entry["eventId"])
        ledger_orders.append(entry["logicalOrder"])
        origin_action_number = entry["logicalOrder"] + 1
        if entry["eventId"] != f"special-{origin_action_number}" or entry["sourceStoneId"] != f"stone-{origin_action_number}":
            _raise("semantic-invariant", "ledger IDs must use canonical origin-action labels")
        if origin_action_number > state["atomicActionCount"]:
            _raise("semantic-invariant", "ledger origin action cannot be after the current atomic action count")
        source_stone = stone_by_source.get(entry["sourceStoneId"])
        expected_stone_state = "ON_BOARD" if source_stone is not None else "CAPTURED"
        if entry["stoneState"] != expected_stone_state:
            _raise("semantic-invariant", "ledger stoneState must match source-stone presence")
        if source_stone is not None and (
            source_stone["specialEventId"] != entry["eventId"]
            or source_stone["originKind"] != entry["kind"]
            or source_stone["originActionNumber"] != origin_action_number
            or source_stone["point"] != entry["sourcePoint"]
            or source_stone["color"] != entry["owner"]
        ):
            _raise("semantic-invariant", "on-board ledger source stone differs from immutable event identity")
        if entry["settlementState"] == "SETTLED":
            if entry["abilityState"] != "INACTIVE" or not entry["tombstone"]:
                _raise("semantic-invariant", "settled ledger events must be inactive tombstones")
            if not state["settlementCompleted"]:
                _raise("semantic-invariant", "partial settlement ledger state cannot be exposed")
        elif entry["kind"] == "DOUBLE_START":
            if entry["abilityState"] != "CONSUMED" or not entry["tombstone"]:
                _raise("semantic-invariant", "pending Double ledger events must be consumed tombstones")
        elif source_stone is None:
            if entry["abilityState"] != "INACTIVE" or not entry["tombstone"]:
                _raise("semantic-invariant", "captured pending anchors must be inactive tombstones")
        elif entry["abilityState"] != "ARMED" or entry["tombstone"]:
            _raise("semantic-invariant", "on-board pending Immortal/Eightway events must be armed and non-tombstone")
        ledger_counts[entry["owner"]][entry["kind"]] += 1
    _assert_strictly_sorted_unique(ledger_orders, "ledger logical order")
    ledger_by_id = {entry["eventId"]: entry for entry in state["ledger"]}
    for stone in state["stones"]:
        event_id = stone["specialEventId"]
        if stone["originKind"] == "NORMAL":
            if event_id is not None:
                _raise("semantic-invariant", "normal stone cannot reference a special ledger event")
            continue
        if event_id is None or event_id not in ledger_by_id:
            _raise("semantic-invariant", "special-origin stone must reference its ledger event")
        entry = ledger_by_id[event_id]
        if (
            entry["kind"] != stone["originKind"]
            or entry["sourceStoneId"] != stone["sourceId"]
            or entry["logicalOrder"] + 1 != stone["originActionNumber"]
            or entry["sourcePoint"] != stone["point"]
            or entry["owner"] != stone["color"]
        ):
            _raise("semantic-invariant", "special stone source identity differs from its ledger entry")
    for color in ("BLACK", "WHITE"):
        for quota_kind in _quota_keys():
            if state["usedQuotas"][color][quota_kind] != ledger_counts[color][quota_kind]:
                _raise("semantic-invariant", f"used quota differs from ledger count for {color}/{quota_kind}")
            if not state["settlementCompleted"] and state["expiredQuotas"][color][quota_kind] != 0:
                _raise("semantic-invariant", "quotas cannot expire before settlement")
            if state["settlementCompleted"] and state["remainingQuotas"][color][quota_kind] != 0:
                _raise("semantic-invariant", "remaining special quotas must be zero after settlement")
    if state["settlementCompleted"]:
        for entry in state["ledger"]:
            if entry["settlementState"] != "SETTLED" or entry["abilityState"] != "INACTIVE":
                _raise("semantic-invariant", "all ledger events must be settled and inactive after settlement")
    pending = state["pendingDouble"]
    if pending is not None:
        if state["phase"] == "COLLAPSE_PLAY":
            if state["actor"] != pending["owner"]:
                _raise("semantic-invariant", "pending Double must retain its owner as current actor in collapse play")
        elif not (
            state["phase"] == "TERMINAL"
            and state["terminal"]["ended"]
            and state["terminal"]["reason"] in {"RESIGNATION", "TIMEOUT"}
        ):
            _raise("semantic-invariant", "pending Double may persist only in collapse play or an immediate terminal audit state")
        if pending["eventId"] not in ledger_ids:
            _raise("semantic-invariant", "pending Double event must exist in the ledger")
        pending_entry = ledger_by_id[pending["eventId"]]
        if (
            pending_entry["kind"] != "DOUBLE_START"
            or pending_entry["owner"] != pending["owner"]
            or pending_entry["logicalOrder"] + 1 != pending["startActionNumber"]
            or pending_entry["settlementState"] != "PENDING"
            or pending_entry["abilityState"] != "CONSUMED"
        ):
            _raise("semantic-invariant", "pending Double linkage must target its consumed start event")
    if state["phase"] == "COLLAPSE_PLAY":
        if state["settlementCompleted"]:
            _raise("semantic-invariant", "collapse-play state cannot have completed settlement")
        if state["atomicActionCount"] >= state["threshold"]:
            _raise("semantic-invariant", "exposed collapse-play state must satisfy A<T")
    if state["phase"] == "ORDINARY_PLAY" and not state["settlementCompleted"]:
        _raise("semantic-invariant", "ordinary-play state must follow completed settlement")
    if state["phase"] == "TERMINAL":
        if not state["terminal"]["ended"] or state["actor"] is not None:
            _raise("semantic-invariant", "terminal phase must have ended terminal state and null actor")
        terminal_state = state["terminal"]
        if terminal_state["winner"] == terminal_state["loser"]:
            _raise("semantic-invariant", "terminal winner and loser must differ")
        if terminal_state["reason"] == "SCORE":
            if terminal_state["score"] is None:
                _raise("semantic-invariant", "score termination must include exact rational scores")
            score = terminal_state["score"]
            black = score["black"]["numerator"]
            white = score["white"]["numerator"]
            if black % 2 != 0 or white % 2 != 1 or score["margin"]["numerator"] % 2 != 1:
                _raise("semantic-invariant", "official Chinese-area scores must preserve exact half-point komi parity")
            if black == white:
                _raise("semantic-invariant", "official half-point komi cannot produce a tied score")
            expected_winner = "BLACK" if black > white else "WHITE"
            expected_loser = "WHITE" if expected_winner == "BLACK" else "BLACK"
            expected_margin = abs(black - white)
            if terminal_state["winner"] != expected_winner or terminal_state["loser"] != expected_loser:
                _raise("semantic-invariant", "score winner/loser differs from exact rational scores")
            if score["margin"]["numerator"] != expected_margin:
                _raise("semantic-invariant", "score margin differs from exact rational scores")
        elif terminal_state["score"] is not None:
            _raise("semantic-invariant", "resignation and timeout must not include area scoring")
    else:
        if state["terminal"]["ended"] or state["actor"] is None:
            _raise("semantic-invariant", "nonterminal phase must have current actor and non-ended terminal state")
        if state["consecutivePasses"] > 1:
            _raise("semantic-invariant", "two consecutive passes cannot remain exposed in a nonterminal decision state")
    ranges = projection["derived"]["legalActionRanges"]
    previous_last = -1
    legal_action_ids: list[int] = []
    for action_range in ranges:
        first = action_range["first"]
        last = action_range["last"]
        if first > last or (previous_last >= 0 and first <= previous_last + 1):
            _raise("semantic-invariant", "legal action ranges must be sorted, maximally merged, nonempty, and nonoverlapping")
        previous_last = last
        legal_action_ids.extend(range(first, last + 1))
    for action_id in legal_action_ids:
        action, _, _ = decode_action_for_board(action_id, board_size)
        if (state["phase"] == "ORDINARY_PLAY" or state["pendingDouble"] is not None) and action["kind"] not in {"NORMAL", "PASS"}:
            _raise("semantic-invariant", "ordinary play and pending Double may expose only NORMAL/PASS actions")
    if state["phase"] == "TERMINAL":
        if ranges:
            _raise("semantic-invariant", "terminal state must have no legal actions")
    else:
        if not ranges or not any(item["first"] <= PASS_ACTION_ID <= item["last"] for item in ranges):
            _raise("semantic-invariant", "every nonterminal decision state must include PASS")
    debug_stones: set[int] = set()
    occupied = occupied_by_color["BLACK"] | occupied_by_color["WHITE"]
    armed_anchor_points = {
        "IMMORTAL": {"BLACK": set(), "WHITE": set()},
        "EIGHTWAY": {"BLACK": set(), "WHITE": set()},
    }
    for entry in state["ledger"]:
        if entry["kind"] in armed_anchor_points and entry["abilityState"] == "ARMED" and entry["stoneState"] == "ON_BOARD":
            armed_anchor_points[entry["kind"]][entry["owner"]].add(entry["sourcePoint"])
    group_order: list[int] = []
    for group in projection["debug"]["groups"]:
        _assert_strictly_sorted_unique(group["stones"], "debug group stones")
        if not group["stones"]:
            _raise("semantic-invariant", "debug groups cannot be empty")
        group_order.append(group["stones"][0])
        _assert_strictly_sorted_unique(group["liberties"], "debug group liberties")
        if any(point > max_board_point for point in group["liberties"]):
            _raise("semantic-invariant", "debug group liberty lies outside the selected board")
        _assert_strictly_sorted_unique(group["immortalAnchors"], "debug group immortal anchors")
        _assert_strictly_sorted_unique(group["eightwayAnchors"], "debug group eightway anchors")
        stones = set(group["stones"])
        if not stones.issubset(occupied_by_color[group["color"]]):
            _raise("semantic-invariant", "debug group color must match authoritative occupancy")
        if debug_stones & stones:
            _raise("semantic-invariant", "debug groups overlap")
        debug_stones |= stones
        expected_immortal_anchors = stones & armed_anchor_points["IMMORTAL"][group["color"]]
        expected_eightway_anchors = stones & armed_anchor_points["EIGHTWAY"][group["color"]]
        if set(group["immortalAnchors"]) != expected_immortal_anchors:
            _raise("semantic-invariant", "debug Immortal anchors must match armed ledger sources in the group")
        if set(group["eightwayAnchors"]) != expected_eightway_anchors:
            _raise("semantic-invariant", "debug Eightway anchors must match armed ledger sources in the group")
        if group["protected"] != bool(expected_immortal_anchors):
            _raise("semantic-invariant", "debug protection must match presence of an armed Immortal anchor")
        if set(group["liberties"]) & occupied:
            _raise("semantic-invariant", "debug liberties cannot be occupied")
    if group_order != sorted(group_order):
        _raise("semantic-invariant", "debug groups must be ordered by their least board-local point")
    if debug_stones != occupied:
        _raise("semantic-invariant", "debug groups must cover every stable stone")
    transition = projection["transition"]
    if transition is None:
        if projection["stepIndex"] != 0:
            _raise("semantic-invariant", "only initial step zero may omit a transition")
        return
    if transition["accepted"]:
        transition_kind = transition["transitionKind"]
        if transition_kind == "ATOMIC_ACTION":
            event = transition["atomicEvent"]
            validate_action_semantics(event["action"], catalog)
            if event["eventId"] != f"action-{event['actionNumber']}":
                _raise("semantic-invariant", "atomic event IDs must use canonical action-number labels")
            if event["actionNumber"] != state["atomicActionCount"]:
                _raise("semantic-invariant", "atomic event action number must equal the resulting atomic action count")
            _validate_occupancy(event["captured"], board_size, "transition.atomicEvent.captured")
            if event["action"]["kind"] == "PASS" and event["captured"] != {"black": [], "white": []}:
                _raise("semantic-invariant", "PASS atomic events cannot capture stones")
            _validate_occupancy(event["stableOccupancy"], board_size, "transition.atomicEvent.stableOccupancy")
            index = event["pskHistoryIndex"]
            if index >= len(state["pskHistory"]) or state["pskHistory"][index] != event["stableOccupancy"]:
                _raise("semantic-invariant", "atomic event PSK append does not match history")
            settlement = transition["settlement"]
            if settlement is None:
                expected_stable = event["stableOccupancy"]
            elif settlement["steps"]:
                expected_stable = settlement["steps"][-1]["stableOccupancy"]
            else:
                expected_stable = event["stableOccupancy"]
            if settlement is not None:
                expected_ledger_order = [
                    entry["eventId"]
                    for entry in sorted(state["ledger"], key=lambda item: item["logicalOrder"], reverse=True)
                ]
                actual_ledger_order = [step["ledgerEventId"] for step in settlement["steps"]]
                if actual_ledger_order != expected_ledger_order:
                    _raise("semantic-invariant", "settlement steps must cover the complete ledger newest-to-oldest")
                for step_index, step in enumerate(settlement["steps"]):
                    if step["stepIndex"] != step_index:
                        _raise("semantic-invariant", "settlement steps must use contiguous zero-based indexes")
                    _validate_occupancy(step["stableOccupancy"], board_size, "settlement step stable occupancy")
                    for batch in step["removalBatches"]:
                        _validate_occupancy(batch, board_size, "settlement removal batch")
                    history_index = step["pskHistoryIndex"]
                    if history_index >= len(state["pskHistory"]) or state["pskHistory"][history_index] != step["stableOccupancy"]:
                        _raise("semantic-invariant", "settlement step PSK append does not match history")
        elif transition_kind == "IMMEDIATE_TERMINAL":
            if transition["atomicEvent"] is not None or transition["settlement"] is not None:
                _raise("semantic-invariant", "immediate terminal transition cannot contain atomic or settlement events")
            if transition["terminalEvent"]["reason"] not in {"RESIGNATION", "TIMEOUT"}:
                _raise("semantic-invariant", "immediate terminal transition must be resignation or timeout")
            expected_stable = transition["terminalEvent"]["stableOccupancy"]
        else:
            _raise("semantic-invariant", f"unknown accepted transition kind: {transition_kind}")
        terminal_event = transition["terminalEvent"]
        if (state["phase"] == "TERMINAL") != (terminal_event is not None):
            _raise("semantic-invariant", "accepted transition terminal state and terminal event presence must agree")
        if terminal_event is not None:
            if terminal_event["eventId"] != f"terminal-{state['logPosition']}":
                _raise("semantic-invariant", "terminal event IDs must use canonical committed-log labels")
            if transition_kind == "ATOMIC_ACTION" and terminal_event["reason"] != "SCORE":
                _raise("semantic-invariant", "atomic terminal transition must terminate by scoring")
            _validate_occupancy(terminal_event["stableOccupancy"], board_size, "transition.terminalEvent.stableOccupancy")
            history_index = terminal_event["pskHistoryIndex"]
            if history_index >= len(state["pskHistory"]) or state["pskHistory"][history_index] != terminal_event["stableOccupancy"]:
                _raise("semantic-invariant", "terminal event PSK append does not match history")
            if terminal_event["winner"] == terminal_event["loser"]:
                _raise("semantic-invariant", "terminal event winner and loser must differ")
            terminal_state = state["terminal"]
            if not terminal_state["ended"]:
                _raise("semantic-invariant", "terminal event requires terminal resulting state")
            for key in ("reason", "winner", "loser"):
                if terminal_state[key] != terminal_event[key]:
                    _raise("semantic-invariant", f"terminal event {key} differs from terminal state")
            expected_stable = terminal_event["stableOccupancy"]
        if expected_stable != state["occupancy"]:
            _raise("semantic-invariant", "accepted transition stable occupancy differs from resulting state")
    else:
        if transition["transitionKind"] != "REJECTED":
            _raise("semantic-invariant", "rejected transition kind differs")
        if transition["atomicEvent"] is not None or transition["settlement"] is not None or transition["terminalEvent"] is not None:
            _raise("semantic-invariant", "rejected transition cannot emit semantic events")


def _transition_psk_appends(transition: Mapping[str, Any]) -> list[tuple[int, Any]]:
    if not transition["accepted"]:
        return []
    appends: list[tuple[int, Any]] = []
    atomic_event = transition["atomicEvent"]
    if atomic_event is not None:
        appends.append((atomic_event["pskHistoryIndex"], atomic_event["stableOccupancy"]))
    settlement = transition["settlement"]
    if settlement is not None:
        appends.extend((step["pskHistoryIndex"], step["stableOccupancy"]) for step in settlement["steps"])
    terminal_event = transition["terminalEvent"]
    if terminal_event is not None:
        appends.append((terminal_event["pskHistoryIndex"], terminal_event["stableOccupancy"]))
    return appends


def _ledger_immutable_identity(entry: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        entry["eventId"],
        entry["logicalOrder"],
        entry["owner"],
        entry["kind"],
        entry["sourcePoint"],
        entry["sourceStoneId"],
    )


def _expected_atomic_stones(
    previous_state: Mapping[str, Any],
    atomic_event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    captured_points = set(atomic_event["captured"]["black"]) | set(atomic_event["captured"]["white"])
    expected = [copy.deepcopy(stone) for stone in previous_state["stones"] if stone["point"] not in captured_points]
    action = atomic_event["action"]
    if action["kind"] != "PASS":
        _, semantic_x, semantic_y = decode_action_for_board(action["actionId"], previous_state["boardSize"])
        assert semantic_x is not None and semantic_y is not None
        point = previous_state["boardSize"] * semantic_y + semantic_x
        action_number = atomic_event["actionNumber"]
        kind = action["kind"]
        expected.append(
            {
                "point": point,
                "color": atomic_event["actor"],
                "sourceId": f"stone-{action_number}",
                "originKind": kind,
                "specialEventId": f"special-{action_number}" if kind in _quota_keys() else None,
                "originActionNumber": action_number,
            }
        )
    expected.sort(key=lambda stone: stone["point"])
    return expected


def _expected_ledger_after_atomic(
    previous_state: Mapping[str, Any],
    atomic_event: Mapping[str, Any],
) -> list[dict[str, Any]]:
    expected = copy.deepcopy(previous_state["ledger"])
    captured_by_owner = {
        "BLACK": set(atomic_event["captured"]["black"]),
        "WHITE": set(atomic_event["captured"]["white"]),
    }
    for entry in expected:
        if entry["stoneState"] == "ON_BOARD" and entry["sourcePoint"] in captured_by_owner[entry["owner"]]:
            entry["stoneState"] = "CAPTURED"
            if entry["kind"] in {"IMMORTAL", "EIGHTWAY"}:
                entry["abilityState"] = "INACTIVE"
                entry["tombstone"] = True
    action = atomic_event["action"]
    kind = action["kind"]
    if kind in _quota_keys():
        _, semantic_x, semantic_y = decode_action_for_board(action["actionId"], previous_state["boardSize"])
        assert semantic_x is not None and semantic_y is not None
        action_number = atomic_event["actionNumber"]
        expected.append(
            {
                "eventId": f"special-{action_number}",
                "logicalOrder": action_number - 1,
                "owner": atomic_event["actor"],
                "kind": kind,
                "sourcePoint": previous_state["boardSize"] * semantic_y + semantic_x,
                "sourceStoneId": f"stone-{action_number}",
                "abilityState": "CONSUMED" if kind == "DOUBLE_START" else "ARMED",
                "stoneState": "ON_BOARD",
                "settlementState": "PENDING",
                "tombstone": kind == "DOUBLE_START",
            }
        )
    return expected


def _validate_atomic_quota_transition(
    previous_state: Mapping[str, Any],
    current_state: Mapping[str, Any],
    atomic_event: Mapping[str, Any],
    settlement: Mapping[str, Any] | None,
) -> None:
    action_kind = atomic_event["action"]["kind"]
    actor = atomic_event["actor"]
    special_kind = action_kind if action_kind in _quota_keys() else None
    if special_kind is not None:
        if previous_state["phase"] != "COLLAPSE_PLAY" or previous_state["pendingDouble"] is not None:
            _raise("semantic-invariant", "special starts require collapse play without a pending Double")
        if previous_state["remainingQuotas"][actor][special_kind] < 1:
            _raise("semantic-invariant", "accepted special start requires a remaining quota")
        if action_kind == "DOUBLE_START":
            if previous_state["atomicActionCount"] + 2 > previous_state["threshold"]:
                _raise("semantic-invariant", "accepted Double start violates A+2<=T")
        elif previous_state["atomicActionCount"] + 1 > previous_state["threshold"]:
            _raise("semantic-invariant", "accepted special start is after the collapse threshold")
    for color in ("BLACK", "WHITE"):
        for quota_kind in _quota_keys():
            consumed = 1 if color == actor and quota_kind == special_kind else 0
            expected_used = previous_state["usedQuotas"][color][quota_kind] + consumed
            if current_state["usedQuotas"][color][quota_kind] != expected_used:
                _raise("semantic-invariant", f"used quota transition differs for {color}/{quota_kind}")
            if settlement is None:
                expected_remaining = previous_state["remainingQuotas"][color][quota_kind] - consumed
                expected_expired = previous_state["expiredQuotas"][color][quota_kind]
            else:
                expected_remaining = 0
                expected_expired = (
                    previous_state["expiredQuotas"][color][quota_kind]
                    + previous_state["remainingQuotas"][color][quota_kind]
                    - consumed
                )
            if current_state["remainingQuotas"][color][quota_kind] != expected_remaining:
                _raise("semantic-invariant", f"remaining quota transition differs for {color}/{quota_kind}")
            if current_state["expiredQuotas"][color][quota_kind] != expected_expired:
                _raise("semantic-invariant", f"expired quota transition differs for {color}/{quota_kind}")


def _occupancy_sets(occupancy: Mapping[str, Any]) -> dict[str, set[int]]:
    return {"BLACK": set(occupancy["black"]), "WHITE": set(occupancy["white"])}


def _occupancy_from_sets(occupancy: Mapping[str, set[int]]) -> dict[str, list[int]]:
    return {"black": sorted(occupancy["BLACK"]), "white": sorted(occupancy["WHITE"])}


def _validate_projection_from_previous(previous: Any, current: Any) -> None:
    transition = current["transition"]
    if transition is None:
        _raise("semantic-invariant", "noninitial projection must contain a transition")
    previous_state = previous["state"]
    current_state = current["state"]
    for field in ("boardSize", "threshold", "initialQuotas"):
        if current_state[field] != previous_state[field]:
            _raise("semantic-invariant", f"state.{field} is immutable across a game transition")
    previous_history = previous_state["pskHistory"]
    current_history = current_state["pskHistory"]
    if not transition["accepted"]:
        if current_state["revision"] != previous_state["revision"]:
            _raise("semantic-invariant", "rejected transition must preserve state revision")
        if current_state["logPosition"] != previous_state["logPosition"]:
            _raise("semantic-invariant", "rejected transition must preserve committed log position")
        if current_history != previous_history:
            _raise("semantic-invariant", "rejected transition must preserve PSK history exactly")
        return
    if current_state["revision"] != previous_state["revision"] + 1:
        _raise("semantic-invariant", "accepted transition must advance state revision exactly once")
    appends = _transition_psk_appends(transition)
    if current_state["logPosition"] != previous_state["logPosition"] + len(appends):
        _raise("semantic-invariant", "committed log position must advance by the emitted semantic event count")
    expected_history = copy.deepcopy(previous_history)
    for offset, (history_index, occupancy) in enumerate(appends):
        expected_index = len(previous_history) + offset
        if history_index != expected_index:
            _raise("semantic-invariant", "accepted transition PSK indexes must be consecutive appends")
        expected_history.append(occupancy)
    if current_history != expected_history:
        _raise("semantic-invariant", "accepted transition must preserve old PSK history as an exact prefix and append every stable event")

    pre_settlement_entries: list[dict[str, Any]] | None = None
    if transition["transitionKind"] == "ATOMIC_ACTION":
        atomic_event = transition["atomicEvent"]
        action = atomic_event["action"]
        action_kind = action["kind"]
        expected_action_count = previous_state["atomicActionCount"] + 1
        if current_state["atomicActionCount"] != expected_action_count or atomic_event["actionNumber"] != expected_action_count:
            _raise("semantic-invariant", "accepted atomic transition must increment A once and bind the event action number")
        action_id = action["actionId"]
        if not any(item["first"] <= action_id <= item["last"] for item in previous["derived"]["legalActionRanges"]):
            _raise("semantic-invariant", "accepted action must be present in the previous authoritative legal-action projection")
        decode_action_for_board(action_id, previous_state["boardSize"])
        if atomic_event["actor"] != previous_state["actor"]:
            _raise("semantic-invariant", "accepted atomic event actor must equal the previous authoritative actor")
        settlement = transition["settlement"]
        _validate_atomic_quota_transition(previous_state, current_state, atomic_event, settlement)
        expected_atomic_stones = _expected_atomic_stones(previous_state, atomic_event)
        pre_settlement_entries = _expected_ledger_after_atomic(previous_state, atomic_event)
        if settlement is None:
            if current_state["stones"] != expected_atomic_stones:
                _raise("semantic-invariant", "non-settling atomic transition must preserve stone provenance and add exactly its source stone")
            if current_state["ledger"] != pre_settlement_entries:
                _raise("semantic-invariant", "non-settling atomic transition ledger differs from captures and special-event creation")
        else:
            removed_points = {
                point
                for step in settlement["steps"]
                for batch in step["removalBatches"]
                for points in (batch["black"], batch["white"])
                for point in points
            }
            expected_final_stones = [stone for stone in expected_atomic_stones if stone["point"] not in removed_points]
            if current_state["stones"] != expected_final_stones:
                _raise("semantic-invariant", "settlement may only remove atomic-stable stones and must preserve surviving provenance")
        if action_kind == "PASS":
            empty = {"black": [], "white": []}
            if atomic_event["captured"] != empty:
                _raise("semantic-invariant", "PASS cannot capture stones")
            if atomic_event["stableOccupancy"] != previous_state["occupancy"]:
                _raise("semantic-invariant", "PASS atomic stable occupancy must equal the previous occupancy")
            if current_state["pendingDouble"] is not None:
                _raise("semantic-invariant", "PASS must leave no pending Double obligation")
            opponent = "WHITE" if atomic_event["actor"] == "BLACK" else "BLACK"
            settlement = transition["settlement"]
            terminal_event = transition["terminalEvent"]
            if settlement is not None:
                if settlement["handoffActor"] != opponent:
                    _raise("semantic-invariant", "PASS-triggered settlement must preserve opponent handoff")
                if current_state["consecutivePasses"] != 0:
                    _raise("semantic-invariant", "settlement entry must reset consecutive passes")
                if terminal_event is None and current_state["actor"] != opponent:
                    _raise("semantic-invariant", "settlement exit actor must equal the PASS handoff actor")
            elif terminal_event is not None:
                if terminal_event["reason"] != "SCORE" or previous_state["phase"] != "ORDINARY_PLAY":
                    _raise("semantic-invariant", "an atomic PASS may terminate only by ordinary-play scoring")
                if previous_state["consecutivePasses"] != 1 or current_state["consecutivePasses"] != 2:
                    _raise("semantic-invariant", "scoring PASS must be the second consecutive ordinary-play PASS")
            else:
                if current_state["occupancy"] != previous_state["occupancy"]:
                    _raise("semantic-invariant", "non-settling PASS must preserve visible occupancy")
                if current_state["actor"] != opponent:
                    _raise("semantic-invariant", "nonterminal PASS must hand play to the opponent")
                if current_state["consecutivePasses"] != previous_state["consecutivePasses"] + 1:
                    _raise("semantic-invariant", "nonterminal PASS must increment the consecutive-pass count once")
        else:
            _, semantic_x, semantic_y = decode_action_for_board(action_id, previous_state["boardSize"])
            assert semantic_x is not None and semantic_y is not None
            target = previous_state["boardSize"] * semantic_y + semantic_x
            previous_sets = _occupancy_sets(previous_state["occupancy"])
            actor = atomic_event["actor"]
            opponent = "WHITE" if actor == "BLACK" else "BLACK"
            if target in previous_sets["BLACK"] or target in previous_sets["WHITE"]:
                _raise("semantic-invariant", "accepted point action target must be empty in the previous state")
            captured_sets = _occupancy_sets(atomic_event["captured"])
            if captured_sets[actor]:
                _raise("semantic-invariant", "placement transaction cannot capture the acting player stones")
            if not captured_sets[opponent].issubset(previous_sets[opponent]):
                _raise("semantic-invariant", "captured opponent stones must exist in the previous occupancy")
            expected_sets = {
                "BLACK": set(previous_sets["BLACK"]),
                "WHITE": set(previous_sets["WHITE"]),
            }
            expected_sets[opponent] -= captured_sets[opponent]
            expected_sets[actor].add(target)
            expected_atomic_occupancy = _occupancy_from_sets(expected_sets)
            if atomic_event["stableOccupancy"] != expected_atomic_occupancy:
                _raise("semantic-invariant", "point action stable occupancy must equal placement minus declared captures")
            if atomic_event["stableOccupancy"] in previous_history:
                _raise("semantic-invariant", "accepted player point action must produce a PSK-novel occupancy")
            if current_state["consecutivePasses"] != 0:
                _raise("semantic-invariant", "accepted point action must reset consecutive passes")
            if transition["terminalEvent"] is not None:
                _raise("semantic-invariant", "point actions cannot directly emit a scoring terminal event")
            settlement = transition["settlement"]
            if settlement is None:
                if current_state["occupancy"] != atomic_event["stableOccupancy"]:
                    _raise("semantic-invariant", "non-settling point action result must equal its atomic stable occupancy")
                if action_kind == "DOUBLE_START":
                    pending = current_state["pendingDouble"]
                    expected_event_id = f"special-{atomic_event['actionNumber']}"
                    if (
                        pending is None
                        or pending["owner"] != actor
                        or pending["eventId"] != expected_event_id
                        or pending["startActionNumber"] != atomic_event["actionNumber"]
                    ):
                        _raise("semantic-invariant", "DOUBLE_START must bind its exact new event as the pending continuation")
                    if current_state["actor"] != actor:
                        _raise("semantic-invariant", "DOUBLE_START must not hand play to the opponent before continuation")
                else:
                    if current_state["pendingDouble"] is not None:
                        _raise("semantic-invariant", "non-Double-start point action must leave no pending continuation")
                    if current_state["actor"] != opponent:
                        _raise("semantic-invariant", "completed point action turn must hand play to the opponent")
            else:
                if settlement["handoffActor"] != opponent or current_state["actor"] != opponent:
                    _raise("semantic-invariant", "point-action settlement must preserve the completed-turn opponent handoff")
                if current_state["pendingDouble"] is not None:
                    _raise("semantic-invariant", "settlement cannot expose a pending Double continuation")

    if transition["transitionKind"] == "IMMEDIATE_TERMINAL":
        if previous_state["phase"] not in {"COLLAPSE_PLAY", "ORDINARY_PLAY"} or previous_state["terminal"]["ended"]:
            _raise("semantic-invariant", "resignation/timeout source must be an exposed nonterminal decision state")
        preserved_state_fields = (
            "boardSize",
            "threshold",
            "occupancy",
            "stones",
            "atomicActionCount",
            "consecutivePasses",
            "settlementCompleted",
            "pendingDouble",
            "initialQuotas",
            "remainingQuotas",
            "usedQuotas",
            "expiredQuotas",
            "ledger",
        )
        for field in preserved_state_fields:
            if current_state[field] != previous_state[field]:
                _raise("semantic-invariant", f"immediate terminal transition must preserve state.{field}")
        if current["debug"] != previous["debug"]:
            _raise("semantic-invariant", "immediate terminal transition must preserve board debug projection")
        if transition["terminalEvent"]["stableOccupancy"] != previous_state["occupancy"]:
            _raise("semantic-invariant", "resignation/timeout terminal event must append unchanged occupancy")
        return

    settlement = transition["settlement"]
    expected_trigger: str | None = None
    if previous_state["phase"] == "COLLAPSE_PLAY":
        if current_state["atomicActionCount"] == previous_state["threshold"]:
            expected_trigger = "THRESHOLD"
        elif (
            atomic_event["action"]["kind"] == "PASS"
            and current_state["atomicActionCount"] < previous_state["threshold"]
            and previous_state["consecutivePasses"] + 1 == 2
        ):
            expected_trigger = "PRE_THRESHOLD_TWO_PASSES"
    if expected_trigger is None:
        if settlement is not None:
            _raise("semantic-invariant", "settlement may occur only at the frozen threshold or pre-threshold two-PASS trigger")
        if previous_state["phase"] == "COLLAPSE_PLAY" and current_state["phase"] != "COLLAPSE_PLAY":
            _raise("semantic-invariant", "collapse play cannot exit before its settlement trigger")
        if previous_state["phase"] == "ORDINARY_PLAY" and current_state["phase"] not in {"ORDINARY_PLAY", "TERMINAL"}:
            _raise("semantic-invariant", "ordinary play cannot re-enter collapse or settlement")
        return
    if settlement is None:
        _raise("semantic-invariant", "the frozen settlement trigger must execute its complete transaction")
    if settlement["triggerReason"] != expected_trigger:
        _raise("semantic-invariant", "settlement trigger reason does not match frozen precedence")
    if previous_state["settlementCompleted"]:
        _raise("semantic-invariant", "settlement cannot run after it has already completed")
    if current_state["phase"] != "ORDINARY_PLAY" or not current_state["settlementCompleted"]:
        _raise("semantic-invariant", "settlement result must expose completed ordinary play")
    if pre_settlement_entries is None:
        _raise("semantic-invariant", "settlement requires an atomic pre-settlement ledger projection")
    current_ledger = current_state["ledger"]
    if len(current_ledger) != len(pre_settlement_entries):
        _raise("semantic-invariant", "settlement result ledger length differs from the atomic-stable ledger")
    for pre_entry, current_entry in zip(pre_settlement_entries, current_ledger):
        if _ledger_immutable_identity(pre_entry) != _ledger_immutable_identity(current_entry):
            _raise("semantic-invariant", "settlement must preserve immutable ledger event identity and order")
    expected_step_ids = [entry["eventId"] for entry in reversed(pre_settlement_entries)]
    if [step["ledgerEventId"] for step in settlement["steps"]] != expected_step_ids:
        _raise("semantic-invariant", "settlement queue must come from the pre-settlement ledger newest-to-oldest")
    entry_by_id = {entry["eventId"]: entry for entry in pre_settlement_entries}
    source_present_by_event = {
        entry["eventId"]: entry["stoneState"] == "ON_BOARD" for entry in pre_settlement_entries
    }
    working = _occupancy_sets(atomic_event["stableOccupancy"])
    for step in settlement["steps"]:
        entry = entry_by_id[step["ledgerEventId"]]
        source_present = source_present_by_event[entry["eventId"]]
        board_mechanical_no_op = (
            entry["tombstone"]
            or entry["abilityState"] != "ARMED"
            or not source_present
        )
        expected_deactivation = (
            not board_mechanical_no_op
            and entry["kind"] in {"IMMORTAL", "EIGHTWAY"}
        )
        if step["abilityDeactivated"] != expected_deactivation:
            _raise("semantic-invariant", "settlement abilityDeactivated differs from the pre-step ledger state")
        before = _occupancy_from_sets(working)
        if board_mechanical_no_op:
            if (
                step["abilityDeactivated"]
                or not step["noOp"]
                or step["removalBatches"]
                or step["stableOccupancy"] != before
            ):
                _raise(
                    "semantic-invariant",
                    "consumed or tombstone settlement pop must be a board-mechanical no-op",
                )
            continue
        removal_count = 0
        for batch in step["removalBatches"]:
            for json_color, color in (("black", "BLACK"), ("white", "WHITE")):
                for point in batch[json_color]:
                    if point not in working[color]:
                        _raise("semantic-invariant", "settlement removal batch contains an absent or duplicate stone")
                    working[color].remove(point)
                    for source_entry in pre_settlement_entries:
                        if (
                            source_present_by_event[source_entry["eventId"]]
                            and source_entry["owner"] == color
                            and source_entry["sourcePoint"] == point
                        ):
                            source_present_by_event[source_entry["eventId"]] = False
                    removal_count += 1
        computed_stable = _occupancy_from_sets(working)
        if computed_stable != step["stableOccupancy"]:
            _raise("semantic-invariant", "settlement removal batches do not produce the declared stable occupancy")
        if step["noOp"]:
            if step["abilityDeactivated"] or removal_count or step["stableOccupancy"] != before:
                _raise("semantic-invariant", "settlement no-op must have no deactivation, removals, or occupancy change")
        elif not step["abilityDeactivated"] and removal_count == 0:
            _raise("semantic-invariant", "non-no-op settlement step must deactivate an ability or remove stones")


def _validate_projection_with_predecessor(
    previous: Any,
    current: Any,
    catalog: SchemaCatalog,
    identity_or_digest: str | Mapping[str, Any],
) -> None:
    _validate_projection(previous, catalog, identity_or_digest)
    _validate_projection(current, catalog, identity_or_digest)
    if current["fixtureId"] != previous["fixtureId"]:
        _raise("semantic-invariant", "projection predecessor must share the current fixture ID")
    if current["stepIndex"] != previous["stepIndex"] + 1:
        _raise("semantic-invariant", "projection predecessor step must immediately precede the current step")
    _validate_projection_from_previous(previous, current)


def _configuration_from_descriptor(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    board_size = descriptor["boardPolicy"]["selectedBoardSize"]
    return {
        "boardSize": board_size,
        "threshold": BOARD_THRESHOLDS[board_size],
        "initialActor": descriptor["initialState"]["firstActor"],
        "initialPSKSeed": descriptor["initialState"]["initialPSKSeed"],
        "quotas": copy.deepcopy(descriptor["quotas"]["initialByPlayer"]),
        "scoring": descriptor["scoring"]["method"],
        "komi": copy.deepcopy(descriptor["scoring"]["komi"]),
        "deadStoneShortcut": descriptor["deadStoneHandling"]["mvpShortcutStatus"],
    }


def _official_configuration() -> dict[str, Any]:
    quota = {"IMMORTAL": 1, "DOUBLE_START": 1, "EIGHTWAY": 1}
    return {
        "boardSize": 19,
        "threshold": 150,
        "initialActor": "BLACK",
        "initialPSKSeed": True,
        "quotas": {"BLACK": copy.deepcopy(quota), "WHITE": copy.deepcopy(quota)},
        "scoring": "CHINESE_AREA",
        "komi": {"recipient": "WHITE", "numerator": 15, "denominator": 2},
        "deadStoneShortcut": "DEFERRED",
    }


def _validate_fixture(fixture: Any, catalog: SchemaCatalog, digest: str) -> None:
    catalog.validate("conformance-fixture-v1", fixture)
    descriptor_binding = fixture["descriptor"]
    if descriptor_binding is None:
        expected_identity = _public_identity(digest)
        expected_configuration = _official_configuration()
    else:
        bound_digest = validate_descriptor(descriptor_binding, catalog, require_public=False)
        expected_identity = _descriptor_identity(descriptor_binding, bound_digest)
        expected_configuration = _configuration_from_descriptor(descriptor_binding)
    fixture_identity = fixture["ruleset"]
    _assert_ruleset_identity(fixture_identity, expected_identity, "conformance fixture ruleset")
    if fixture["configuration"] != expected_configuration:
        _raise("semantic-invariant", "fixture configuration must equal its bound descriptor configuration")
    initial = fixture["initialProjection"]
    _validate_projection(initial, catalog, fixture_identity)
    if initial["fixtureId"] != fixture["fixtureId"] or initial["stepIndex"] != 0 or initial["transition"] is not None:
        _raise("semantic-invariant", "fixture initial projection identity/step differs")
    state = initial["state"]
    configuration = fixture["configuration"]
    board_size = configuration["boardSize"]
    if configuration["threshold"] != BOARD_THRESHOLDS[board_size]:
        _raise("semantic-invariant", "fixture threshold must match the selected board size")
    if state["boardSize"] != board_size or state["threshold"] != configuration["threshold"]:
        _raise("semantic-invariant", "fixture initial board configuration differs")
    if state["actor"] != configuration["initialActor"] or state["atomicActionCount"] != 0:
        _raise("semantic-invariant", "fixture initial actor/action count differs")
    if state["revision"] != 0 or state["logPosition"] != 0:
        _raise("semantic-invariant", "fixture genesis revision and committed log position must be zero")
    zero_quotas = {
        "BLACK": {kind: 0 for kind in _quota_keys()},
        "WHITE": {kind: 0 for kind in _quota_keys()},
    }
    if state["initialQuotas"] != configuration["quotas"] or state["remainingQuotas"] != configuration["quotas"]:
        _raise("semantic-invariant", "fixture initial quotas differ from configuration")
    if state["usedQuotas"] != zero_quotas or state["expiredQuotas"] != zero_quotas:
        _raise("semantic-invariant", "fixture initial used/expired quotas must be zero")
    if state["phase"] != "COLLAPSE_PLAY" or state["settlementCompleted"] or state["consecutivePasses"] != 0:
        _raise("semantic-invariant", "fixture initial phase/pass/settlement state differs")
    if state["occupancy"] != {"black": [], "white": []} or len(state["pskHistory"]) != 1:
        _raise("semantic-invariant", "fixture must start empty with exactly PSK history entry zero")
    previous_projection = initial
    for expected_index, step in enumerate(fixture["steps"], start=1):
        if step["stepIndex"] != expected_index:
            _raise("semantic-invariant", "fixture step indexes must be contiguous and one-based")
        candidate = step["candidate"]
        candidate_kind = candidate["kind"]
        if candidate_kind == "ACTION":
            validate_action_semantics(candidate["action"], catalog)
        projection = step["expectedProjection"]
        _validate_projection(projection, catalog, fixture_identity)
        _validate_projection_from_previous(previous_projection, projection)
        if projection["state"]["initialQuotas"] != configuration["quotas"]:
            _raise("semantic-invariant", "fixture projection initial quotas differ from configuration")
        if projection["fixtureId"] != fixture["fixtureId"] or projection["stepIndex"] != expected_index:
            _raise("semantic-invariant", "expected projection fixture identity/step differs")
        transition = projection["transition"]
        if transition["accepted"]:
            if candidate_kind == "ACTION" and step["candidateActor"] != previous_projection["state"]["actor"]:
                _raise("semantic-invariant", "accepted action candidate actor must equal the authoritative current actor")
            if candidate_kind == "ACTION":
                if transition["transitionKind"] != "ATOMIC_ACTION":
                    _raise("semantic-invariant", "accepted action candidate must produce an atomic transition")
                event = transition["atomicEvent"]
                if event["actor"] != step["candidateActor"] or event["action"] != candidate["action"]:
                    _raise("semantic-invariant", "accepted fixture event differs from candidate actor/action")
                expected_action_count = previous_projection["state"]["atomicActionCount"] + 1
                if projection["state"]["atomicActionCount"] != expected_action_count:
                    _raise("semantic-invariant", "accepted atomic fixture step must increment atomic action count once")
                if event["actionNumber"] != expected_action_count:
                    _raise("semantic-invariant", "atomic event action number must equal the resulting atomic action count")
            else:
                if previous_projection["state"]["phase"] not in {"COLLAPSE_PLAY", "ORDINARY_PLAY"}:
                    _raise("semantic-invariant", "resignation/timeout source must be an exposed nonterminal decision state")
                if transition["transitionKind"] != "IMMEDIATE_TERMINAL":
                    _raise("semantic-invariant", "accepted resignation/timeout must produce an immediate terminal transition")
                terminal_event = transition["terminalEvent"]
                if terminal_event["reason"] != candidate_kind or terminal_event["loser"] != step["candidateActor"]:
                    _raise("semantic-invariant", "immediate terminal event differs from candidate intent/actor")
                if projection["state"]["atomicActionCount"] != previous_projection["state"]["atomicActionCount"]:
                    _raise("semantic-invariant", "resignation and timeout must not increment atomic action count")
        else:
            _assert_rejection_precedence(
                previous_projection["state"],
                step["candidateActor"],
                candidate,
                transition["errorCode"],
                "fixture rejection",
            )
            if projection["state"] != previous_projection["state"]:
                _raise("semantic-invariant", "rejected fixture step must leave exact state unchanged")
            if projection["derived"] != previous_projection["derived"] or projection["debug"] != previous_projection["debug"]:
                _raise("semantic-invariant", "rejected fixture step must leave derived/debug projections unchanged")
        previous_projection = projection


def _json_value_type(value: Any) -> str:
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "BOOLEAN"
    if type(value) is int:
        return "INTEGER"
    if isinstance(value, str):
        return "STRING"
    if isinstance(value, list):
        return "ARRAY"
    if isinstance(value, dict):
        return "OBJECT"
    _raise("unsupported-json-type", f"unsupported mismatch value type: {type(value).__name__}")


def _classify_present_difference(cpp_value: Any, python_value: Any) -> str:
    cpp_type = _json_value_type(cpp_value)
    python_type = _json_value_type(python_value)
    if cpp_type != python_type:
        return "TYPE_MISMATCH"
    if cpp_type == "ARRAY":
        if len(cpp_value) != len(python_value):
            return "ARRAY_LENGTH_MISMATCH"
        cpp_elements = [canonicalize(item) for item in cpp_value]
        python_elements = [canonicalize(item) for item in python_value]
        if cpp_elements != python_elements and sorted(cpp_elements) == sorted(python_elements):
            return "ORDER_MISMATCH"
    return "VALUE_MISMATCH"


def _validate_mismatch_reproduction_segment(
    initial: Mapping[str, Any],
    prefix: Sequence[Mapping[str, Any]],
    pre_candidate: Mapping[str, Any],
    candidate: Mapping[str, Any],
    catalog: SchemaCatalog,
    identity: Mapping[str, Any],
) -> None:
    for expected_index, entry in enumerate(prefix, start=1):
        if entry["stepIndex"] != expected_index:
            _raise("semantic-invariant", "mismatch accepted prefix indexes must be contiguous")
        validate_action_semantics(entry["action"], catalog)
    _validate_projection(pre_candidate, catalog, identity)
    if pre_candidate["fixtureId"] != initial["fixtureId"]:
        _raise("semantic-invariant", "pre-candidate projection must share the reproduction fixture ID")
    if pre_candidate["stepIndex"] != len(prefix):
        _raise("semantic-invariant", "pre-candidate projection step must equal accepted prefix length")
    pre_candidate_state = pre_candidate["state"]
    if pre_candidate_state["revision"] != len(prefix) or pre_candidate_state["atomicActionCount"] != len(prefix):
        _raise("semantic-invariant", "accepted prefix length must equal pre-candidate revision and atomic action count")
    if pre_candidate_state["logPosition"] < len(prefix):
        _raise("semantic-invariant", "accepted prefix must emit at least one semantic event per atomic action")
    if not prefix:
        if pre_candidate != initial:
            _raise("semantic-invariant", "empty accepted prefix requires pre-candidate projection equal to the initial projection")
    else:
        transition = pre_candidate["transition"]
        last = prefix[-1]
        if transition is None or not transition["accepted"] or transition["transitionKind"] != "ATOMIC_ACTION":
            _raise("semantic-invariant", "nonempty accepted prefix requires an accepted atomic pre-candidate transition")
        event = transition["atomicEvent"]
        if event["actor"] != last["actor"] or event["action"] != last["action"]:
            _raise("semantic-invariant", "pre-candidate projection must end with the final accepted prefix action")
        if event["actionNumber"] != len(prefix):
            _raise("semantic-invariant", "pre-candidate final event action number must equal accepted prefix length")
    if candidate["stepIndex"] != len(prefix) + 1:
        _raise("semantic-invariant", "mismatch candidate step must follow accepted prefix")
    intent = candidate["intent"]
    if intent["kind"] == "ACTION":
        validate_action_semantics(intent["action"], catalog)


def _validate_mismatch_result_projection(
    projection: Any,
    previous: Mapping[str, Any],
    candidate: Mapping[str, Any],
    catalog: SchemaCatalog,
    identity: Mapping[str, Any],
) -> None:
    _validate_projection(projection, catalog, identity)
    _validate_projection_from_previous(previous, projection)
    if projection["fixtureId"] != previous["fixtureId"] or projection["stepIndex"] != candidate["stepIndex"]:
        _raise("semantic-invariant", "mismatch result projection fixture/step differs from the candidate")
    transition = projection["transition"]
    if transition is None:
        _raise("semantic-invariant", "mismatch result projection must contain the candidate transition")
    intent = candidate["intent"]
    if transition["accepted"]:
        if intent["kind"] == "ACTION" and candidate["actor"] != previous["state"]["actor"]:
            _raise("semantic-invariant", "accepted mismatch action actor must equal the authoritative actor")
        if intent["kind"] == "ACTION":
            if transition["transitionKind"] != "ATOMIC_ACTION":
                _raise("semantic-invariant", "accepted action mismatch candidate must produce an atomic transition")
            event = transition["atomicEvent"]
            if event["actor"] != candidate["actor"] or event["action"] != intent["action"]:
                _raise("semantic-invariant", "mismatch atomic event differs from candidate actor/action")
        else:
            if transition["transitionKind"] != "IMMEDIATE_TERMINAL":
                _raise("semantic-invariant", "accepted terminal mismatch candidate must be immediate")
            terminal_event = transition["terminalEvent"]
            if terminal_event["reason"] != intent["kind"] or terminal_event["loser"] != candidate["actor"]:
                _raise("semantic-invariant", "mismatch immediate terminal event differs from the candidate")
    else:
        _assert_rejection_precedence(
            previous["state"],
            candidate["actor"],
            intent,
            transition["errorCode"],
            "mismatch rejection",
        )
        if projection["state"] != previous["state"]:
            _raise("semantic-invariant", "rejected mismatch candidate must preserve exact state")
        if projection["derived"] != previous["derived"] or projection["debug"] != previous["debug"]:
            _raise("semantic-invariant", "rejected mismatch candidate must preserve derived/debug projections")


def _validate_mismatch_observation(
    observation: Mapping[str, Any],
    previous: Mapping[str, Any],
    candidate: Mapping[str, Any],
    catalog: SchemaCatalog,
    identity: Mapping[str, Any],
    side: str,
) -> None:
    status = observation["status"]
    if status == "VALID":
        try:
            _validate_mismatch_result_projection(observation["value"], previous, candidate, catalog, identity)
        except ContractError as error:
            raise ContractError(error.code, f"{side} VALID observation is invalid: {error}") from error
        return
    if status == "SEMANTIC_INVALID":
        try:
            _validate_mismatch_result_projection(observation["value"], previous, candidate, catalog, identity)
        except ContractError:
            return
        _raise("semantic-invariant", f"{side} SEMANTIC_INVALID observation unexpectedly satisfies semantic checks")
    if status == "SCHEMA_INVALID":
        try:
            catalog.validate("semantic-projection-v1", observation["value"])
        except ContractError as error:
            if error.code != "schema-validation":
                _raise("semantic-invariant", f"{side} SCHEMA_INVALID value fails before schema validation")
            return
        _raise("semantic-invariant", f"{side} SCHEMA_INVALID observation unexpectedly satisfies the schema")
    if status == "RAW_INVALID":
        bytes.fromhex(observation["rawUtf8Hex"])
        return
    _raise("semantic-invariant", f"unknown mismatch observation status: {status}")


def _validate_mismatch_differences(
    observations: Mapping[str, Mapping[str, Any]],
    differences: Sequence[Mapping[str, Any]],
) -> None:
    seen_difference_pointers: set[str] = set()
    for difference in differences:
        pointer = difference["jsonPointer"]
        if pointer in seen_difference_pointers:
            _raise("semantic-invariant", f"duplicate normalized mismatch pointer: {pointer}")
        seen_difference_pointers.add(pointer)
        resolved = {}
        values = {}
        for side, observation in observations.items():
            try:
                value = resolve_json_pointer(observation, pointer)
            except ContractError as error:
                if error.code != "json-pointer-missing":
                    raise
                actual_present = False
                actual_canonical = None
                value = None
            else:
                actual_present = True
                actual_canonical = canonicalize(value).decode("utf-8")
            declared = difference[side]
            if declared["present"] != actual_present or declared["canonicalJson"] != actual_canonical:
                _raise("semantic-invariant", f"mismatch {side} observation does not match pointer {pointer}")
            resolved[side] = (actual_present, actual_canonical)
            values[side] = value
        category = difference["category"]
        cpp_present, cpp_canonical = resolved["cpp"]
        python_present, python_canonical = resolved["python"]
        if category == "MISSING_IN_CPP":
            if cpp_present or not python_present:
                _raise("semantic-invariant", f"MISSING_IN_CPP presence differs at {pointer}")
        elif category == "MISSING_IN_PYTHON":
            if not cpp_present or python_present:
                _raise("semantic-invariant", f"MISSING_IN_PYTHON presence differs at {pointer}")
        else:
            if not cpp_present or not python_present or cpp_canonical == python_canonical:
                _raise("semantic-invariant", f"mismatch difference does not identify distinct present values at {pointer}")
            expected_category = _classify_present_difference(values["cpp"], values["python"])
            if category != expected_category:
                _raise("semantic-invariant", f"mismatch category at {pointer} must be {expected_category}, not {category}")

def _validate_mismatch_bundle(bundle: Any, catalog: SchemaCatalog, digest: str) -> None:
    catalog.validate("mismatch-bundle-v1", bundle)
    identity = bundle["ruleset"]
    descriptor_binding = bundle["descriptor"]
    if descriptor_binding is None:
        expected_identity = _public_identity(digest)
        expected_configuration = _official_configuration()
    else:
        bound_digest = validate_descriptor(descriptor_binding, catalog, require_public=False)
        expected_identity = _descriptor_identity(descriptor_binding, bound_digest)
        expected_configuration = _configuration_from_descriptor(descriptor_binding)
    _assert_ruleset_identity(identity, expected_identity, "mismatch bundle ruleset")
    configuration = bundle["configuration"]
    if configuration != expected_configuration:
        _raise("semantic-invariant", "mismatch configuration must equal its bound descriptor configuration")
    if configuration["threshold"] != BOARD_THRESHOLDS[configuration["boardSize"]]:
        _raise("semantic-invariant", "mismatch threshold must match board size")
    implementations = bundle["implementations"]
    if implementations["cpp"]["implementationId"] == implementations["python"]["implementationId"]:
        _raise("semantic-invariant", "C++ and Python mismatch implementations must have distinct identities")
    reproduction = bundle["reproduction"]
    initial = reproduction["initialProjection"]
    _validate_projection(initial, catalog, identity)
    if initial["stepIndex"] != 0 or initial["transition"] is not None:
        _raise("semantic-invariant", "mismatch reproduction must start from an initial step-zero projection")
    if initial["state"]["boardSize"] != configuration["boardSize"] or initial["state"]["threshold"] != configuration["threshold"]:
        _raise("semantic-invariant", "mismatch initial projection configuration differs")
    initial_state = initial["state"]
    zero_quotas = {
        "BLACK": {kind: 0 for kind in _quota_keys()},
        "WHITE": {kind: 0 for kind in _quota_keys()},
    }
    if initial_state["revision"] != 0 or initial_state["logPosition"] != 0:
        _raise("semantic-invariant", "mismatch genesis revision and log position must be zero")
    if initial_state["occupancy"] != {"black": [], "white": []} or initial_state["stones"] or initial_state["ledger"]:
        _raise("semantic-invariant", "mismatch reproduction must begin from the declared empty board")
    if (
        initial_state["actor"] != configuration["initialActor"]
        or initial_state["phase"] != "COLLAPSE_PLAY"
        or initial_state["atomicActionCount"] != 0
        or initial_state["consecutivePasses"] != 0
        or initial_state["settlementCompleted"]
        or initial_state["pendingDouble"] is not None
    ):
        _raise("semantic-invariant", "mismatch reproduction genesis control state differs from configuration")
    if (
        initial_state["initialQuotas"] != configuration["quotas"]
        or initial_state["remainingQuotas"] != configuration["quotas"]
        or initial_state["usedQuotas"] != zero_quotas
        or initial_state["expiredQuotas"] != zero_quotas
    ):
        _raise("semantic-invariant", "mismatch reproduction genesis quotas differ from configuration")
    if initial_state["pskHistory"] != [{"black": [], "white": []}] or initial_state["terminal"] != {"ended": False}:
        _raise("semantic-invariant", "mismatch reproduction genesis PSK/terminal state differs")
    _validate_mismatch_reproduction_segment(
        initial,
        reproduction["acceptedPrefix"],
        reproduction["preCandidateProjection"],
        reproduction["candidate"],
        catalog,
        identity,
    )
    previous = reproduction["preCandidateProjection"]
    candidate = reproduction["candidate"]
    observations = {
        "cpp": bundle["cppObservation"],
        "python": bundle["pythonObservation"],
    }
    for side, observation in observations.items():
        _validate_mismatch_observation(observation, previous, candidate, catalog, identity, side)
    _validate_mismatch_differences(observations, bundle["differences"])
    prefix = reproduction["acceptedPrefix"]
    minimization = bundle["minimization"]
    if minimization["originalPrefixLength"] != len(prefix):
        _raise("semantic-invariant", "mismatch original prefix length must equal the reproduction prefix length")
    if minimization["minimizedPrefixLength"] > minimization["originalPrefixLength"]:
        _raise("semantic-invariant", "minimized prefix cannot be longer than original prefix")
    if (
        minimization["status"] == "MINIMIZED"
        and minimization["minimizedPrefixLength"] >= minimization["originalPrefixLength"]
    ):
        _raise("semantic-invariant", "MINIMIZED status requires a strictly shorter reproducible prefix")
    result = minimization["result"]
    if minimization["status"] == "MINIMIZED":
        if not minimization["reproducible"] or result is None:
            _raise("semantic-invariant", "MINIMIZED status requires a reproducible minimized result")
        if minimization["minimizedPrefixLength"] != len(result["acceptedPrefix"]):
            _raise("semantic-invariant", "minimized prefix length must match the stored minimized result")
        if (
            result["candidate"]["actor"] != candidate["actor"]
            or result["candidate"]["intent"] != candidate["intent"]
        ):
            _raise("semantic-invariant", "minimization must preserve the original candidate actor and intent")
        original_signature = [
            (difference["jsonPointer"], difference["category"]) for difference in bundle["differences"]
        ]
        minimized_signature = [
            (difference["jsonPointer"], difference["category"]) for difference in result["differences"]
        ]
        if minimized_signature != original_signature:
            _raise("semantic-invariant", "minimization must preserve the normalized mismatch signature")
        _validate_mismatch_reproduction_segment(
            initial,
            result["acceptedPrefix"],
            result["preCandidateProjection"],
            result["candidate"],
            catalog,
            identity,
        )
        minimized_observations = {
            "cpp": result["cppObservation"],
            "python": result["pythonObservation"],
        }
        for side, observation in minimized_observations.items():
            _validate_mismatch_observation(
                observation,
                result["preCandidateProjection"],
                result["candidate"],
                catalog,
                identity,
                side,
            )
        _validate_mismatch_differences(minimized_observations, result["differences"])
    else:
        if result is not None:
            _raise("semantic-invariant", "only MINIMIZED status may contain a minimized result")
        if minimization["status"] == "NOT_REDUCIBLE":
            if not minimization["reproducible"] or minimization["minimizedPrefixLength"] != len(prefix):
                _raise("semantic-invariant", "NOT_REDUCIBLE must retain the reproducible original prefix")

def _walk_action_objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("schemaVersion") == "action-v1":
            yield value
        for item in value.values():
            yield from _walk_action_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_action_objects(item)


def verify_examples(catalog: SchemaCatalog, digest: str, example_dir: Path = EXAMPLE_DIR) -> None:
    example_schemas = {
        "action-v1.example.json": "action-v1",
        "semantic-projection-v1.example.json": "semantic-projection-v1",
        "conformance-fixture-v1.example.json": "conformance-fixture-v1",
        "conformance-fixture-double-settlement-v1.example.json": "conformance-fixture-v1",
        "mismatch-bundle-v1.example.json": "mismatch-bundle-v1",
    }
    actual_names = {path.name for path in example_dir.glob("*.json")}
    if actual_names != set(example_schemas):
        _raise("example-set-mismatch", f"example file set differs: {sorted(actual_names)}")
    for filename, schema_name in example_schemas.items():
        instance = load_json(example_dir / filename, enforce_profile=True)
        catalog.validate(schema_name, instance)
        if schema_name != "mismatch-bundle-v1":
            for action in _walk_action_objects(instance):
                validate_action_semantics(action, catalog)
        if schema_name == "semantic-projection-v1":
            _validate_projection(instance, catalog, digest)
        elif schema_name == "conformance-fixture-v1":
            _validate_fixture(instance, catalog, digest)
        elif schema_name == "mismatch-bundle-v1":
            _validate_mismatch_bundle(instance, catalog, digest)


def verify_public_identity_vector(digest: str, path: Path = VECTOR_DIR / "public-identity-v1.json") -> None:
    vector = load_json(path, enforce_profile=True)
    _require_exact_keys(
        vector,
        (
            "vectorVersion",
            "descriptorFile",
            "canonicalizationProfile",
            "canonicalUtf8ByteLength",
            "publicIdentity",
        ),
        "public identity vector",
    )
    if vector["vectorVersion"] != "public-identity-v1":
        _raise("invalid-vector", "public identity vector version differs")
    descriptor_file = _require_vector_string(vector["descriptorFile"], "public identity descriptorFile")
    descriptor_path = (path.parent / descriptor_file).resolve()
    if descriptor_path != DESCRIPTOR_PATH.resolve():
        _raise("invalid-vector", "public identity vector descriptor path differs")
    descriptor = load_json(descriptor_path, enforce_profile=True)
    canonical = canonicalize(descriptor)
    if vector["canonicalizationProfile"] != CANONICALIZATION_PROFILE:
        _raise("vector-mismatch", "public identity canonicalization profile differs")
    if _require_exact_int(vector["canonicalUtf8ByteLength"], "public identity canonicalUtf8ByteLength") != len(canonical):
        _raise("vector-mismatch", "public identity canonical byte length differs")
    _assert_public_identity(vector["publicIdentity"], digest, "public identity vector")


def run_check() -> str:
    expected_vector_files = {
        "action-v1.json",
        "canonicalization-v1.json",
        "descriptor-invalid-v1.json",
        "public-identity-v1.json",
    }
    actual_vector_files = {path.name for path in VECTOR_DIR.glob("*.json")}
    if actual_vector_files != expected_vector_files:
        _raise("vector-set-mismatch", f"vector file set differs: {sorted(actual_vector_files)}")
    catalog = SchemaCatalog()
    descriptor = load_json(DESCRIPTOR_PATH, enforce_profile=True)
    digest = validate_descriptor(descriptor, catalog)
    verify_canonicalization_vectors()
    verify_descriptor_invalid_vectors(catalog)
    verify_action_vectors(catalog)
    verify_public_identity_vector(digest)
    verify_examples(catalog, digest)
    return digest


def _schema_name_from_argument(argument: str) -> str:
    if argument in SCHEMA_FILES:
        return argument
    for schema_name, filename in SCHEMA_FILES.items():
        if argument == filename:
            return schema_name
    _raise("unknown-schema", f"unknown schema argument: {argument}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MutaGo executable contract utility")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="verify all schemas, refs, descriptor, vectors, and examples")
    canonical_parser = subparsers.add_parser("canonicalize", help="canonicalize one strict-profile JSON file")
    canonical_parser.add_argument("file", type=Path)
    hash_parser = subparsers.add_parser("hash", help="print lowercase SHA-256 of canonical JSON bytes")
    hash_parser.add_argument("file", type=Path)
    validate_parser = subparsers.add_parser("validate", help="validate one strict-profile JSON contract artifact")
    validate_parser.add_argument("schema")
    validate_parser.add_argument("file", type=Path)
    projection_mode = validate_parser.add_mutually_exclusive_group()
    projection_mode.add_argument(
        "--predecessor",
        type=Path,
        help="validate a semantic projection transition against its immediate predecessor",
    )
    projection_mode.add_argument(
        "--standalone",
        action="store_true",
        help="validate only intrinsic semantic-projection invariants, not transition validity",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "check":
            digest = run_check()
            print(f"rulesetId={PUBLIC_RULESET_ID}")
            print(f"semanticVersion={PUBLIC_SEMANTIC_VERSION}")
            print(f"publicDescriptorSha256={digest}")
        elif arguments.command == "canonicalize":
            value = load_json(arguments.file, enforce_profile=True)
            sys.stdout.buffer.write(canonicalize(value))
        elif arguments.command == "hash":
            value = load_json(arguments.file, enforce_profile=True)
            print(descriptor_digest(value))
        elif arguments.command == "validate":
            catalog = SchemaCatalog()
            schema_name = _schema_name_from_argument(arguments.schema)
            value = load_json(arguments.file, enforce_profile=True)
            catalog.validate(schema_name, value)
            predecessor_path = arguments.predecessor
            standalone = arguments.standalone
            if schema_name != "semantic-projection-v1" and (predecessor_path is not None or standalone):
                _raise("invalid-cli-mode", "--predecessor and --standalone apply only to semantic projections")
            if schema_name == "action-v1":
                validate_action_semantics(value, catalog)
                print("valid")
            elif schema_name == "ruleset-descriptor-v1":
                validate_descriptor(value, catalog)
                print("valid")
            else:
                descriptor = load_json(DESCRIPTOR_PATH, enforce_profile=True)
                digest = validate_descriptor(descriptor, catalog)
                if schema_name == "semantic-projection-v1":
                    if predecessor_path is not None:
                        previous = load_json(predecessor_path, enforce_profile=True)
                        _validate_projection_with_predecessor(previous, value, catalog, digest)
                        print("valid-transition")
                    else:
                        _validate_projection(value, catalog, digest)
                        if value["transition"] is not None and not standalone:
                            _raise(
                                "predecessor-required",
                                "noninitial semantic projections require --predecessor or explicit --standalone mode",
                            )
                        print("valid-standalone-projection" if standalone else "valid-initial-projection")
                elif schema_name == "conformance-fixture-v1":
                    _validate_fixture(value, catalog, digest)
                    print("valid")
                elif schema_name == "mismatch-bundle-v1":
                    _validate_mismatch_bundle(value, catalog, digest)
                    print("valid")
        else:
            parser.error(f"unknown command: {arguments.command}")
    except ContractError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
