#!/usr/bin/env python3
"""Bounded test-only full-rule legality differential carrier.

The ``full-rule-diff-v4-unfrozen`` protocol and every carrier field are
explicitly UNFROZEN.  This driver adds a complete stable-state legality read
model to the checkout-pinned Eightway Increment 3 projection without changing
that historical v3 module or any production schema.  C++ remains the sole
production authority; expected legality and transitions come from the
independent stdlib-only Python oracle.  This is not gate evidence.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import sys
from pathlib import Path
from typing import Mapping, Sequence

CONFORMANCE_DIR = Path(__file__).resolve().parent
if str(CONFORMANCE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFORMANCE_DIR))

import eightway_differential as v3  # noqa: E402

if Path(v3.__file__).resolve() != CONFORMANCE_DIR / "eightway_differential.py":
    raise ImportError(
        f"eightway_differential resolved outside this checkout: {v3.__file__}"
    )

import mutago.collapse_go.action_legality as _legality_module  # noqa: E402

_legality_path = Path(_legality_module.__file__).resolve()
try:
    _legality_path.relative_to(v3.hardened.PYTHON_ROOT)
except ValueError as exc:
    raise ImportError(
        f"mutago.collapse_go.action_legality resolved outside this checkout: "
        f"{_legality_path}"
    ) from exc

enumerate_action_legality = _legality_module.enumerate_action_legality
derive_legal_mask = _legality_module.derive_legal_mask

PROTOCOL_VERSION = "full-rule-diff-v4-unfrozen"
GENERATOR_VERSION = "sha256-counter-full-rule-v4-unfrozen"
DEFAULT_SEED = v3.DEFAULT_SEED
# Both public legality views are evaluated for every initial and post-candidate
# stable state. Keep the opt-in default bounded while retaining the v3 stream.
DEFAULT_CANDIDATE_COUNT = v3.MIN_RANDOM_CANDIDATE_COUNT
MIN_RANDOM_CANDIDATE_COUNT = v3.MIN_RANDOM_CANDIDATE_COUNT
MAX_RANDOM_CANDIDATE_COUNT = v3.MAX_RANDOM_CANDIDATE_COUNT
MAX_EPISODE_STEPS = v3.MAX_EPISODE_STEPS
MAX_TEST_QUOTA = v3.MAX_TEST_QUOTA
MAX_REQUEST_FRAME_BYTES = v3.MAX_REQUEST_FRAME_BYTES
MAX_RESPONSE_FRAME_BYTES = v3.MAX_RESPONSE_FRAME_BYTES
MAX_PROBE_STDOUT_BYTES = v3.MAX_PROBE_STDOUT_BYTES
MAX_PROBE_STDERR_BYTES = v3.MAX_PROBE_STDERR_BYTES
PROBE_TIMEOUT_SECONDS = v3.PROBE_TIMEOUT_SECONDS
INVERSE_SYMMETRY_IDS = v3.INVERSE_SYMMETRY_IDS
ACTION_COUNT = v3.PASS_ACTION_ID + 1
CANVAS_POINT_COUNT = 19 * 19
POINT_FAMILY_COUNT = 4

ProtocolError = v3.ProtocolError
ProbeError = v3.ProbeError
DifferentialMismatch = v3.DifferentialMismatch
ContractError = v3.ContractError
Sha256CounterRng = v3.Sha256CounterRng
Color = v3.Color
ActionKind = v3.ActionKind
Phase = v3.Phase
PASS_ACTION_ID = v3.PASS_ACTION_ID
canonical_json = v3.canonical_json
action_v1 = v3.action_v1
board_action_v1 = v3.board_action_v1
transform_board_point = v3.transform_board_point
transform_action = v3.transform_action
quotas = v3.quotas
hardened = v3.hardened
FIXTURE_PATH = v3.FIXTURE_PATH
PINNED_FIXTURE_LEGAL_RANGES_SHA256 = v3.PINNED_FIXTURE_LEGAL_RANGES_SHA256

_REQUEST_FIELDS = frozenset(
    ("protocolVersion", "episodeId", "boardSize", "initialQuotas", "steps")
)


def _check_deadline(deadline: float | None, phase: str) -> None:
    v3._check_deadline(deadline, phase)


def validate_episode_request(request: object) -> Mapping[str, object]:
    """Validate the v4 request while delegating every non-version rule to v3."""

    frame = hardened._require_exact_fields(
        request, _REQUEST_FIELDS, "Full-rule episode request"
    )
    if frame["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError(f"protocolVersion must be {PROTOCOL_VERSION}")
    translated = copy.deepcopy(frame)
    translated["protocolVersion"] = v3.PROTOCOL_VERSION
    v3.validate_episode_request(translated)
    return frame


def _to_v3_request(request: object) -> dict[str, object]:
    frame = validate_episode_request(request)
    translated = copy.deepcopy(frame)
    translated["protocolVersion"] = v3.PROTOCOL_VERSION
    return dict(v3.validate_episode_request(translated))


def _from_v3_request(request: object) -> dict[str, object]:
    frame = v3.validate_episode_request(request)
    translated = copy.deepcopy(frame)
    translated["protocolVersion"] = PROTOCOL_VERSION
    return dict(validate_episode_request(translated))


def compress_legal_bits(bits: Sequence[bool]) -> list[dict[str, int]]:
    """Maximally compress an exact 1,445-bit bool vector into closed ranges."""

    if len(bits) != ACTION_COUNT:
        raise ProtocolError(
            f"legal bits must contain exactly {ACTION_COUNT} entries, got {len(bits)}"
        )
    if any(type(bit) is not bool for bit in bits):
        raise ProtocolError("legal bits must contain bool values only")
    ranges: list[dict[str, int]] = []
    first: int | None = None
    for action_id, bit in enumerate(bits):
        if bit and first is None:
            first = action_id
        elif not bit and first is not None:
            ranges.append({"first": first, "last": action_id - 1})
            first = None
    if first is not None:
        ranges.append({"first": first, "last": PASS_ACTION_ID})
    return ranges


def validate_legal_action_ranges(
    ranges: object, context: str = "legalActionRanges"
) -> tuple[bool, ...]:
    """Validate canonical exact ranges and expand all 1,445 action bits."""

    if type(ranges) is not list:
        raise ProtocolError(f"{context} must be an array")
    bits = [False] * ACTION_COUNT
    previous_last: int | None = None
    for index, item in enumerate(ranges):
        entry = hardened._require_exact_fields(
            item, frozenset(("first", "last")), f"{context}[{index}]"
        )
        first = entry["first"]
        last = entry["last"]
        if type(first) is not int or type(last) is not int:
            raise ProtocolError(
                f"{context}[{index}] first and last must be integers; bool is forbidden"
            )
        if not 0 <= first <= PASS_ACTION_ID or not 0 <= last <= PASS_ACTION_ID:
            raise ProtocolError(f"{context}[{index}] is outside 0..{PASS_ACTION_ID}")
        if first > last:
            raise ProtocolError(f"{context}[{index}] has first greater than last")
        if previous_last is not None:
            if first <= previous_last:
                raise ProtocolError(f"{context} ranges overlap or are out of order")
            if first == previous_last + 1:
                raise ProtocolError(
                    f"{context} ranges are adjacent and therefore not maximally compressed"
                )
        for action_id in range(first, last + 1):
            bits[action_id] = True
        previous_last = last
    expanded = tuple(bits)
    if compress_legal_bits(expanded) != ranges:
        raise ProtocolError(f"{context} is not the unique maximal range encoding")
    return expanded


def python_legal_action_ranges(
    state: object, *, deadline: float | None = None
) -> list[dict[str, int]]:
    """Derive expected legality through both Python legality entry points."""

    _check_deadline(deadline, "Full-rule Python legality enumeration")
    rejection_codes = enumerate_action_legality(state)
    _check_deadline(deadline, "Full-rule Python legal-mask derivation")
    mask = derive_legal_mask(state)
    if type(rejection_codes) is not tuple or len(rejection_codes) != ACTION_COUNT:
        raise ProtocolError(
            "enumerate_action_legality must return exactly 1,445 tuple entries"
        )
    if type(mask) is not tuple or len(mask) != ACTION_COUNT:
        raise ProtocolError("derive_legal_mask must return exactly 1,445 tuple entries")
    if any(type(bit) is not bool for bit in mask):
        raise ProtocolError("derive_legal_mask returned a non-bool entry")
    enumerated_mask = tuple(code is None for code in rejection_codes)
    if enumerated_mask != mask:
        first = next(
            action_id
            for action_id, (left, right) in enumerate(zip(enumerated_mask, mask))
            if left != right
        )
        raise ProtocolError(
            "Python legality APIs disagree across 1,445 entries; "
            f"first differing actionId={first}; "
            f"enumerate_action_legality={str(enumerated_mask[first]).lower()}; "
            f"derive_legal_mask={str(mask[first]).lower()}"
        )
    return compress_legal_bits(mask)


def _annotate_action_prefix(
    error: Exception,
    prefix_length: int,
    *,
    context_attached: bool = False,
) -> Exception:
    setattr(error, "_full_rule_action_prefix_length", prefix_length)
    if context_attached:
        setattr(error, "_full_rule_context_attached", True)
    return error


def _state_projection_with_legality(
    state: object, *, deadline: float | None = None
) -> dict[str, object]:
    projected = v3.state_projection(state)
    projected["legalActionRanges"] = python_legal_action_ranges(
        state, deadline=deadline
    )
    return projected


def oracle_episode_response(
    request: object, *, deadline: float | None = None
) -> dict[str, object]:
    """Execute one v4 episode without enumerating actions through the reducer."""

    try:
        _check_deadline(deadline, "Full-rule Python oracle request validation")
        frame = validate_episode_request(request)
        state = v3.new_game(
            v3._oracle_config(frame["initialQuotas"], frame["boardSize"])
        )
        initial_state = _state_projection_with_legality(state, deadline=deadline)
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        _annotate_action_prefix(exc, 0)
        raise

    observations = []
    for step_index, step in enumerate(frame["steps"], start=1):
        try:
            _check_deadline(deadline, "Full-rule Python oracle execution")
            previous = state
            actor = Color(step["candidateActor"])
            transition = v3._apply_v3_adapter(state, actor, step["action"])
            state = transition.state
            observations.append(
                {
                    "state": _state_projection_with_legality(
                        state, deadline=deadline
                    ),
                    "stepIndex": step_index,
                    "transition": v3.transition_projection(
                        previous, actor, step["action"], transition
                    ),
                }
            )
        except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
            _annotate_action_prefix(exc, step_index)
            raise
    return {
        "episodeId": frame["episodeId"],
        "initialState": initial_state,
        "observations": observations,
        "protocolVersion": PROTOCOL_VERSION,
    }


def _walk_legality_paths(
    value: object,
    path: tuple[object, ...] = (),
    *,
    deadline: float | None = None,
):
    stack = [("value", value, path)]
    visited = 0
    while stack:
        kind, payload, current_path = stack.pop()
        visited += 1
        if visited % 1024 == 0:
            _check_deadline(deadline, "Full-rule legality placement validation")
        if kind == "value":
            if type(payload) is dict:
                stack.append(("dict", iter(payload.items()), current_path))
            elif type(payload) is list:
                stack.append(("list", iter(enumerate(payload)), current_path))
            continue

        iterator = payload
        try:
            component, child = next(iterator)
        except StopIteration:
            continue
        stack.append((kind, iterator, current_path))
        child_path = current_path + (component,)
        if kind == "dict" and component == "legalActionRanges":
            yield child_path
        stack.append(("value", child, child_path))


def _format_path(path: tuple[object, ...]) -> str:
    result = "response"
    for component in path:
        if type(component) is int:
            result += f"[{component}]"
        else:
            result += f".{component}"
    return result


def _required_legality_paths(request: Mapping[str, object]) -> set[tuple[object, ...]]:
    paths = {("initialState", "legalActionRanges")}
    paths.update(
        ("observations", index, "state", "legalActionRanges")
        for index in range(len(request["steps"]))
    )
    return paths


def _assert_stable_only_legality_placement(
    response: object,
    request: Mapping[str, object],
    *,
    label: str,
    deadline: float | None = None,
) -> None:
    actual = set(_walk_legality_paths(response, deadline=deadline))
    required = _required_legality_paths(request)
    missing = sorted(required - actual, key=repr)
    forbidden = sorted(actual - required, key=repr)
    if missing or forbidden:
        missing_text = [_format_path(path) for path in missing]
        forbidden_text = [_format_path(path) for path in forbidden]
        raise ProtocolError(
            f"{label} legalActionRanges placement differs: "
            f"missing={missing_text}, forbidden={forbidden_text}"
        )


def _stable_legality_entries(
    response: Mapping[str, object],
    *,
    expected_observation_count: int | None = None,
    label: str = "response",
) -> list[tuple[str, int, object]]:
    initial_state = response.get("initialState")
    observations = response.get("observations")
    if type(initial_state) is not dict:
        raise ProtocolError(f"{label}.initialState must be an object")
    if type(observations) is not list:
        raise ProtocolError(f"{label}.observations must be an array")
    if (
        expected_observation_count is not None
        and len(observations) != expected_observation_count
    ):
        raise ProtocolError(
            f"{label} observation count differs: "
            f"{len(observations)} != {expected_observation_count}"
        )
    if "legalActionRanges" not in initial_state:
        raise ProtocolError(f"{label}.initialState is missing legalActionRanges")

    result = [
        (
            "initialState",
            0,
            initial_state["legalActionRanges"],
        )
    ]
    for index, observation in enumerate(observations):
        if type(observation) is not dict or type(observation.get("state")) is not dict:
            raise ProtocolError(f"{label}.observations[{index}].state must be an object")
        state = observation["state"]
        if "legalActionRanges" not in state:
            raise ProtocolError(
                f"{label}.observations[{index}].state is missing legalActionRanges"
            )
        result.append(
            (
                f"observations[{index}].state",
                index + 1,
                state["legalActionRanges"],
            )
        )
    return result


def _validate_response_header(response: object, label: str) -> Mapping[str, object]:
    if type(response) is not dict:
        raise ProtocolError(f"{label} must be an object")
    expected_fields = {"episodeId", "initialState", "observations", "protocolVersion"}
    actual_fields = set(response)
    if actual_fields != expected_fields:
        raise ProtocolError(
            f"{label} fields differ: "
            f"missing={sorted(expected_fields - actual_fields)}, "
            f"unknown={sorted(actual_fields - expected_fields, key=repr)}"
        )
    if response.get("protocolVersion") != PROTOCOL_VERSION:
        raise ProtocolError(f"{label} protocolVersion differs")
    return response


def _strip_legality_to_v3(
    response: object,
    request: Mapping[str, object],
    *,
    label: str,
    deadline: float | None = None,
) -> dict[str, object]:
    frame = _validate_response_header(response, label)
    _assert_stable_only_legality_placement(
        frame, request, label=label, deadline=deadline
    )
    _stable_legality_entries(
        frame,
        expected_observation_count=len(request["steps"]),
        label=label,
    )
    stripped = dict(frame)
    initial_state = dict(frame["initialState"])
    del initial_state["legalActionRanges"]
    stripped["initialState"] = initial_state
    observations = []
    for source_observation in frame["observations"]:
        observation = dict(source_observation)
        state = dict(source_observation["state"])
        del state["legalActionRanges"]
        observation["state"] = state
        observations.append(observation)
    stripped["observations"] = observations
    stripped["protocolVersion"] = v3.PROTOCOL_VERSION
    return stripped


def _default_validation_manifest() -> dict[str, object]:
    return {
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": 0,
        "seed": "direct-response-validation",
    }


def _compare_stable_legality(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
    request: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
    request_line: str,
) -> None:
    expected_count = len(request["steps"])
    actual_entries = _stable_legality_entries(
        actual,
        expected_observation_count=expected_count,
        label="actual response",
    )
    expected_entries = _stable_legality_entries(
        expected,
        expected_observation_count=expected_count,
        label="expected response",
    )
    if len(actual_entries) != len(expected_entries):
        raise ProtocolError("stable legality entry count differs")
    for (actual_label, prefix_length, actual_ranges), (
        expected_label,
        expected_prefix,
        expected_ranges,
    ) in zip(actual_entries, expected_entries):
        if actual_label != expected_label or prefix_length != expected_prefix:
            raise ProtocolError("stable legality path ordering differs")
        try:
            actual_bits = validate_legal_action_ranges(
                actual_ranges, f"actual {actual_label}.legalActionRanges"
            )
            expected_bits = validate_legal_action_ranges(
                expected_ranges, f"expected {expected_label}.legalActionRanges"
            )
        except ProtocolError as exc:
            raise _annotate_action_prefix(
                ProtocolError(
                    f"{exc}; "
                    + v3._context(
                        manifest, request, request_line, prefix_length
                    )
                ),
                prefix_length,
                context_attached=True,
            ) from exc
        # Equality consumes the complete 1,445-entry tuples before locating the
        # first diagnostic bit.  Generic response comparison happens later.
        if actual_bits != expected_bits:
            first = next(
                action_id
                for action_id, (left, right) in enumerate(
                    zip(expected_bits, actual_bits)
                )
                if left != right
            )
            raise _annotate_action_prefix(
                DifferentialMismatch(
                    f"episode {request['episodeId']}: legalActionRanges mismatch at "
                    f"{actual_label}; first differing actionId={first}; "
                    f"pythonExpected={str(expected_bits[first]).lower()}; "
                    f"cppActual={str(actual_bits[first]).lower()}; "
                    + v3._context(
                        manifest, request, request_line, prefix_length
                    )
                ),
                prefix_length,
                context_attached=True,
            )


def validate_episode_response(
    response: object,
    request: Mapping[str, object],
    expected_shape: Mapping[str, object],
    *,
    deadline: float | None = None,
    manifest: Mapping[str, object] | None = None,
    request_line: str | None = None,
) -> Mapping[str, object]:
    """Validate v4 legality first, then delegate the stripped response to v3."""

    _check_deadline(deadline, "Full-rule response validation")
    validated_request = validate_episode_request(request)
    actual = _validate_response_header(response, "episode response")
    expected = _validate_response_header(expected_shape, "expected episode response")
    _assert_stable_only_legality_placement(
        actual,
        validated_request,
        label="episode response",
        deadline=deadline,
    )
    _assert_stable_only_legality_placement(
        expected,
        validated_request,
        label="expected episode response",
        deadline=deadline,
    )
    active_manifest = manifest or _default_validation_manifest()
    active_request_line = request_line or canonical_json(validated_request)
    _compare_stable_legality(
        actual,
        expected,
        validated_request,
        manifest=active_manifest,
        request_line=active_request_line,
    )
    _check_deadline(deadline, "Full-rule v3 response adapter validation")
    actual_v3 = _strip_legality_to_v3(
        actual,
        validated_request,
        label="episode response",
        deadline=deadline,
    )
    expected_v3 = _strip_legality_to_v3(
        expected,
        validated_request,
        label="expected episode response",
        deadline=deadline,
    )
    v3.validate_episode_response(
        actual_v3,
        _to_v3_request(validated_request),
        expected_v3,
        deadline=deadline,
    )
    return actual


def parse_canonical_response_line(
    line: str,
    request: Mapping[str, object],
    expected_shape: Mapping[str, object],
    *,
    deadline: float | None = None,
    manifest: Mapping[str, object] | None = None,
    request_line: str | None = None,
) -> Mapping[str, object]:
    _check_deadline(deadline, "Full-rule response parsing")
    if not line:
        raise ProtocolError("probe returned an empty response line")
    encoded = line.encode("utf-8", errors="strict")
    if len(encoded) > MAX_RESPONSE_FRAME_BYTES:
        raise ProtocolError("probe response exceeds the 96 MiB response limit")
    try:
        parsed = v3.parse_json_bytes(encoded)
        _check_deadline(deadline, "Full-rule response parsing")
        canonical = canonical_json(parsed)
    except RecursionError as exc:
        raise ProtocolError("probe response exceeds the supported nesting depth") from exc
    except ContractError as exc:
        raise ProtocolError(
            f"probe returned invalid restricted-profile JSON: {exc}"
        ) from exc
    _check_deadline(deadline, "Full-rule response canonicalization")
    if canonical != line:
        raise ProtocolError("probe response is not canonical restricted-profile JSON")
    return validate_episode_response(
        parsed,
        request,
        expected_shape,
        deadline=deadline,
        manifest=manifest,
        request_line=request_line,
    )


def _digest_record(digest: object, data: str) -> None:
    # Preserve the historical v3 transcript framing exactly.
    v3._digest_record(digest, data)


def _context(
    manifest: Mapping[str, object],
    request: Mapping[str, object],
    request_line: str,
    prefix_length: int,
) -> str:
    return v3._context(manifest, request, request_line, prefix_length)


def _probe_failure_context(
    manifest: Mapping[str, object],
    requests: Sequence[Mapping[str, object]],
    request_lines: Sequence[str],
    *,
    response_index: int = 0,
    completed_response_count: int = 0,
) -> str:
    return v3._probe_failure_context(
        manifest,
        requests,
        request_lines,
        response_index=response_index,
        completed_response_count=completed_response_count,
    )


def run_probe_requests(
    probe_path: Path | str,
    requests: Sequence[Mapping[str, object]],
    expected: Sequence[Mapping[str, object]],
    *,
    manifest: Mapping[str, object],
    deadline: float,
) -> tuple[list[Mapping[str, object]], str]:
    """Run v4 JSONL through the checkout-pinned v3 process supervisor."""

    if len(expected) != len(requests):
        raise ProbeError(
            f"expected response count differs: {len(expected)} != {len(requests)}; "
            + _probe_failure_context(
                manifest,
                requests,
                [],
                response_index=0,
                completed_response_count=0,
            )
        )
    request_lines: list[str] = []
    try:
        _check_deadline(deadline, "Full-rule probe setup")
        probe = Path(probe_path).expanduser().resolve()
        if not probe.is_file():
            raise ProbeError(f"probe executable does not exist: {probe}")
        for item in requests:
            _check_deadline(deadline, "Full-rule probe request serialization")
            request_lines.append(canonical_json(validate_episode_request(item)))
        completed = hardened._run_probe_process(
            [str(probe)], "".join(line + "\n" for line in request_lines), deadline
        )
    except hardened.ProbeOutputDecodeError as exc:
        raise ProbeError(
            f"{exc}; "
            + _probe_failure_context(
                manifest,
                requests,
                request_lines,
                response_index=exc.response_index,
                completed_response_count=exc.response_index,
            )
        ) from exc
    except ProbeError as exc:
        raise ProbeError(
            f"{exc}; "
            + _probe_failure_context(
                manifest,
                requests,
                request_lines,
                response_index=0,
                completed_response_count=0,
            )
        ) from exc
    completed_count = completed.stdout.count("\n")
    if completed.returncode != 0:
        index = min(completed_count, max(0, len(requests) - 1))
        raise ProbeError(
            f"probe exited with {completed.returncode}; stderr={completed.stderr!r}; "
            + _probe_failure_context(
                manifest,
                requests,
                request_lines,
                response_index=index,
                completed_response_count=completed_count,
            )
        )
    if completed.stderr:
        index = min(completed_count, max(0, len(requests) - 1))
        raise ProbeError(
            f"probe emitted successful-run diagnostics: {completed.stderr!r}; "
            + _probe_failure_context(
                manifest,
                requests,
                request_lines,
                response_index=index,
                completed_response_count=completed_count,
            )
        )
    if not completed.stdout.endswith("\n"):
        index = min(completed_count, max(0, len(requests) - 1))
        raise ProbeError(
            "probe output is not newline-terminated; "
            + _probe_failure_context(
                manifest,
                requests,
                request_lines,
                response_index=index,
                completed_response_count=completed_count,
            )
        )
    lines = completed.stdout[:-1].split("\n")
    if len(lines) != len(requests):
        index = min(len(lines), max(0, len(requests) - 1))
        raise ProbeError(
            f"probe response line count differs: {len(lines)} != {len(requests)}; "
            + _probe_failure_context(
                manifest,
                requests,
                request_lines,
                response_index=index,
                completed_response_count=len(lines),
            )
        )
    digest = hashlib.sha256()
    _digest_record(digest, canonical_json(manifest))
    responses = []
    for index, (request, expected_response, request_line_value, response_line) in enumerate(
        zip(requests, expected, request_lines, lines)
    ):
        try:
            parsed = parse_canonical_response_line(
                response_line,
                request,
                expected_response,
                deadline=deadline,
                manifest=manifest,
                request_line=request_line_value,
            )
        except ProbeError as exc:
            raise ProbeError(
                f"{exc}; "
                + _probe_failure_context(
                    manifest,
                    requests,
                    request_lines,
                    response_index=index,
                    completed_response_count=index,
                )
            ) from exc
        except (ProtocolError, DifferentialMismatch, UnicodeError) as exc:
            if getattr(exc, "_full_rule_context_attached", False):
                message = (
                    f"{exc}; responseIndex={index}; "
                    f"completedResponseCount={index}"
                )
            else:
                prefix_length = getattr(
                    exc,
                    "_full_rule_action_prefix_length",
                    len(request["steps"]),
                )
                message = (
                    f"{exc}; responseIndex={index}; "
                    f"completedResponseCount={index}; "
                    + _context(
                        manifest,
                        request,
                        request_line_value,
                        prefix_length,
                    )
                )
            raise type(exc)(message) from exc
        responses.append(parsed)
        _digest_record(digest, request_line_value)
        _digest_record(digest, response_line)
    return responses, digest.hexdigest()


def load_contract_fixture(
    path: Path = FIXTURE_PATH, *, deadline: float | None = None
) -> dict[str, object]:
    return v3.load_contract_fixture(path, deadline=deadline)


def validate_contract_fixture(
    fixture: Mapping[str, object], *, deadline: float | None = None
) -> None:
    v3.validate_contract_fixture(fixture, deadline=deadline)


def _fixture_legal_ranges_digest(fixture: Mapping[str, object]) -> str:
    return v3._fixture_legal_ranges_digest(fixture)


def fixture_request(
    fixture: Mapping[str, object] | None = None,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    return _from_v3_request(v3.fixture_request(fixture, deadline=deadline))


def fixture_reexecution_requests(
    fixture: Mapping[str, object], *, deadline: float | None = None
) -> list[dict[str, object]]:
    return [
        _from_v3_request(request)
        for request in v3.fixture_reexecution_requests(fixture, deadline=deadline)
    ]


def eightway_immortal_split_request(
    board_size: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    return _from_v3_request(
        v3.eightway_immortal_split_request(
            board_size, episode_id, deadline=deadline
        )
    )


def transform_request(
    request: Mapping[str, object],
    symmetry: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    transformed = v3.transform_request(
        _to_v3_request(request),
        symmetry,
        episode_id,
        deadline=deadline,
    )
    return _from_v3_request(transformed)


def transform_legal_action_ranges(
    ranges: object,
    symmetry: int,
    *,
    deadline: float | None = None,
) -> list[dict[str, int]]:
    """Transform four 361-action families on the full canvas; keep PASS fixed."""

    _check_deadline(deadline, "Full-rule D4 legality transformation")
    source = validate_legal_action_ranges(ranges)
    target = [False] * ACTION_COUNT
    for family in range(POINT_FAMILY_COUNT):
        block = family * CANVAS_POINT_COUNT
        for canvas_point in range(CANVAS_POINT_COUNT):
            transformed_point = transform_board_point(19, canvas_point, symmetry)
            target[block + transformed_point] = source[block + canvas_point]
    target[PASS_ACTION_ID] = source[PASS_ACTION_ID]
    return compress_legal_bits(target)


def transform_response(
    response: Mapping[str, object],
    board_size: int,
    symmetry: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "Full-rule D4 response transformation")
    synthetic_request = {
        "boardSize": board_size,
        "episodeId": response["episodeId"],
        "initialQuotas": copy.deepcopy(response["initialState"]["initialQuotas"]),
        "protocolVersion": PROTOCOL_VERSION,
        "steps": [
            {
                "candidateActor": observation["transition"]["candidateActor"],
                "action": copy.deepcopy(observation["transition"]["action"]),
            }
            for observation in response["observations"]
        ],
    }
    validate_episode_request(synthetic_request)
    initial_ranges = response["initialState"]["legalActionRanges"]
    observation_ranges = [
        observation["state"]["legalActionRanges"]
        for observation in response["observations"]
    ]
    stripped = _strip_legality_to_v3(
        response,
        synthetic_request,
        label="D4 source response",
        deadline=deadline,
    )
    transformed = v3.transform_response(
        stripped,
        board_size,
        symmetry,
        episode_id,
        deadline=deadline,
    )
    transformed["protocolVersion"] = PROTOCOL_VERSION
    transformed["initialState"]["legalActionRanges"] = (
        transform_legal_action_ranges(initial_ranges, symmetry, deadline=deadline)
    )
    for observation, ranges in zip(transformed["observations"], observation_ranges):
        observation["state"]["legalActionRanges"] = transform_legal_action_ranges(
            ranges, symmetry, deadline=deadline
        )
    return transformed


def generate_curated_episodes(
    fixture: Mapping[str, object], *, deadline: float | None = None
) -> list[dict[str, object]]:
    return [
        _from_v3_request(request)
        for request in v3.generate_curated_episodes(fixture, deadline=deadline)
    ]


def generate_random_episodes(
    seed: str,
    candidate_count: int,
    *,
    deadline: float | None = None,
) -> list[dict[str, object]]:
    return [
        _from_v3_request(request)
        for request in v3.generate_random_episodes(
            seed, candidate_count, deadline=deadline
        )
    ]


def _fixture_ranges(fixture: Mapping[str, object]) -> list[object]:
    result = [fixture["initialProjection"]["derived"]["legalActionRanges"]]
    result.extend(
        step["expectedProjection"]["derived"]["legalActionRanges"]
        for step in fixture["steps"]
    )
    return result


def _compare_fixture_ranges(
    fixture: Mapping[str, object],
    response: Mapping[str, object],
    *,
    side: str,
    request: Mapping[str, object],
    manifest: Mapping[str, object],
    deadline: float | None = None,
) -> None:
    literal = _fixture_ranges(fixture)
    actual = [entry[2] for entry in _stable_legality_entries(response)]
    if len(literal) != len(actual):
        raise DifferentialMismatch(f"{side} fixture legality state count differs")
    request_line = canonical_json(request)
    for prefix_length, (expected_ranges, actual_ranges) in enumerate(
        zip(literal, actual)
    ):
        _check_deadline(deadline, "Full-rule fixture legality binding")
        expected_bits = validate_legal_action_ranges(
            expected_ranges, f"fixture projection {prefix_length}.legalActionRanges"
        )
        actual_bits = validate_legal_action_ranges(
            actual_ranges, f"{side} fixture state {prefix_length}.legalActionRanges"
        )
        if expected_bits != actual_bits:
            first = next(
                action_id
                for action_id, (left, right) in enumerate(
                    zip(expected_bits, actual_bits)
                )
                if left != right
            )
            raise DifferentialMismatch(
                f"{side} fixture legalActionRanges differs; "
                f"first differing actionId={first}; "
                + _context(
                    manifest, request, request_line, prefix_length
                )
            )


def _compare_fixture_d4_and_prefixes(
    fixture: Mapping[str, object],
    expected_by_id: Mapping[str, Mapping[str, object]],
    actual_by_id: Mapping[str, Mapping[str, object]],
    requests_by_id: Mapping[str, Mapping[str, object]],
    manifest: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> None:
    normalized = v3.normalized_contract_fixture(fixture)
    fixture_id = fixture["fixtureId"]
    active_request_id = fixture_id
    try:
        for side, responses in (("python", expected_by_id), ("cpp", actual_by_id)):
            active_request_id = fixture_id
            request = requests_by_id[fixture_id]
            v3_response = _strip_legality_to_v3(
                responses[fixture_id],
                request,
                label=f"{side} fixture response",
                deadline=deadline,
            )
            hardened.compare_exact(
                normalized,
                v3.strip_v3_response(v3_response),
                episode_id=f"{side}-full-rule-contract-binding",
                deadline=deadline,
            )
            _compare_fixture_ranges(
                fixture,
                responses[fixture_id],
                side=side,
                request=request,
                manifest=manifest,
                deadline=deadline,
            )
            full = responses[fixture_id]
            for prefix_id, prefix_length, label in (
                ("fixture-eightway-placement-prefix", 5, "Eightway-placement"),
                (
                    "fixture-eightway-mixed-protection-prefix",
                    8,
                    "mixed-protection",
                ),
                ("fixture-eightway-pre-trigger-prefix", 9, "pre-trigger"),
            ):
                active_request_id = prefix_id
                hardened.compare_exact(
                    full["observations"][:prefix_length],
                    responses[prefix_id]["observations"],
                    episode_id=f"{side}-{label}-full-rule-immutable-prefix",
                    deadline=deadline,
                )
            active_request_id = "fixture-eightway-full-reexecution"
            reexecuted = copy.deepcopy(responses[active_request_id])
            reexecuted["episodeId"] = fixture_id
            hardened.compare_exact(
                full,
                reexecuted,
                episode_id=f"{side}-full-rule-action-reexecution",
                deadline=deadline,
            )
            active_request_id = "fixture-eightway-post-settlement-suffix"
            suffix = responses[active_request_id]
            hardened.compare_exact(
                full["observations"],
                suffix["observations"][:10],
                episode_id=f"{side}-full-rule-post-settlement-immutable-prefix",
                deadline=deadline,
            )

        for board_size in (9, 13, 19):
            base_id = f"curated-d4-eightway-{board_size}-0"
            for symmetry in range(8):
                target_id = f"curated-d4-eightway-{board_size}-{symmetry}"
                inverse = INVERSE_SYMMETRY_IDS[symmetry]
                for side, responses in (("python", expected_by_id), ("cpp", actual_by_id)):
                    active_request_id = target_id
                    transformed = transform_response(
                        responses[base_id],
                        board_size,
                        symmetry,
                        target_id,
                        deadline=deadline,
                    )
                    hardened.compare_exact(
                        transformed,
                        responses[target_id],
                        episode_id=f"{side}-full-rule-d4-{board_size}-{symmetry}",
                        deadline=deadline,
                    )
                    restored = transform_response(
                        responses[target_id],
                        board_size,
                        inverse,
                        base_id,
                        deadline=deadline,
                    )
                    hardened.compare_exact(
                        responses[base_id],
                        restored,
                        episode_id=(
                            f"{side}-full-rule-d4-inverse-{board_size}-{symmetry}"
                        ),
                        deadline=deadline,
                    )
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        request = requests_by_id[active_request_id]
        raise type(exc)(
            f"{exc}; "
            + _context(
                manifest,
                request,
                canonical_json(request),
                len(request["steps"]),
            )
        ) from exc


def run_differential(
    probe_path: Path | str,
    *,
    seed: str = DEFAULT_SEED,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    deadline = hardened._new_deadline(timeout_seconds)
    manifest = {
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": candidate_count,
        "seed": seed,
    }
    episodes: list[dict[str, object]] = []
    request_lines: list[str] = []
    context_index = 0
    try:
        fixture = load_contract_fixture(deadline=deadline)
        validate_contract_fixture(fixture, deadline=deadline)
        curated = generate_curated_episodes(fixture, deadline=deadline)
        random_episodes = generate_random_episodes(
            seed, candidate_count, deadline=deadline
        )
        episodes = curated + random_episodes
        request_lines = [canonical_json(request) for request in episodes]
        expected = []
        for context_index, request in enumerate(episodes):
            _check_deadline(deadline, "Full-rule Python oracle corpus execution")
            expected.append(oracle_episode_response(request, deadline=deadline))
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        if episodes and context_index < len(episodes):
            request = episodes[context_index]
            request_line = (
                request_lines[context_index]
                if context_index < len(request_lines)
                else canonical_json(request)
            )
            prefix_length = getattr(
                exc,
                "_full_rule_action_prefix_length",
                len(request["steps"]),
            )
            context = (
                f"responseIndex={context_index}; completedResponseCount=0; "
                + _context(
                    manifest,
                    request,
                    request_line,
                    prefix_length,
                )
            )
        else:
            context = _probe_failure_context(
                manifest,
                episodes,
                request_lines,
                response_index=context_index,
                completed_response_count=0,
            )
        raise type(exc)(f"{exc}; {context}") from exc

    actual, digest = run_probe_requests(
        probe_path,
        episodes,
        expected,
        manifest=manifest,
        deadline=deadline,
    )

    accepted = rejected = unsupported = 0
    errors: dict[str, int] = {}
    settlements: dict[str, int] = {}
    try:
        for context_index, (request, left, right) in enumerate(
            zip(episodes, expected, actual)
        ):
            _check_deadline(deadline, "Full-rule generic corpus comparison")
            difference = hardened._first_difference(left, right, deadline=deadline)
            if difference is not None:
                mismatch_index = next(
                    (
                        index
                        for index, (a, b) in enumerate(
                            zip(left["observations"], right["observations"]), start=1
                        )
                        if hardened._first_difference(a, b, deadline=deadline)
                        is not None
                    ),
                    len(request["steps"]),
                )
                raise DifferentialMismatch(
                    f"episode {request['episodeId']}: {difference}; "
                    + _context(
                        manifest,
                        request,
                        request_lines[context_index],
                        mismatch_index,
                    )
                )
            for observation in left["observations"]:
                _check_deadline(deadline, "Full-rule summary projection")
                transition = observation["transition"]
                if transition["status"] == "ACCEPTED":
                    accepted += 1
                elif transition["status"] == "REJECTED":
                    rejected += 1
                else:
                    unsupported += 1
                error = transition["errorCode"] or "NONE"
                errors[error] = errors.get(error, 0) + 1
                reason = (
                    transition["settlement"]["triggerReason"]
                    if transition["settlement"] is not None
                    else "NONE"
                )
                settlements[reason] = settlements.get(reason, 0) + 1

        expected_by_id = {response["episodeId"]: response for response in expected}
        actual_by_id = {response["episodeId"]: response for response in actual}
        requests_by_id = {request["episodeId"]: request for request in episodes}
        context_index = -1
        _compare_fixture_d4_and_prefixes(
            fixture,
            expected_by_id,
            actual_by_id,
            requests_by_id,
            manifest,
            deadline=deadline,
        )
    except ProbeError as exc:
        if context_index < 0:
            raise
        raise ProbeError(
            f"{exc}; "
            + _probe_failure_context(
                manifest,
                episodes,
                request_lines,
                response_index=context_index,
                completed_response_count=len(actual),
            )
        ) from exc

    curated_count = sum(len(request["steps"]) for request in curated)
    total_count = curated_count + candidate_count
    if accepted + rejected + unsupported != total_count:
        raise AssertionError("Full-rule summary candidate counts are ambiguous")
    if unsupported != 0:
        raise AssertionError("Full-rule v4 emitted a forbidden unsupported classification")
    stable_state_count = total_count + len(episodes)
    return {
        "accepted": accepted,
        "candidateCount": total_count,
        "contractFixtureValidated": True,
        "curatedCandidateCount": curated_count,
        "d4BoardSizes": [9, 13, 19],
        "d4Metamorphic": True,
        "deterministicActionReexecutionAndPrefixesExact": True,
        "episodeCount": len(episodes),
        "errorCounts": errors,
        "fixtureId": fixture["fixtureId"],
        "fixtureNormalized": True,
        "fullLegalMaskComparedAtEveryStableState": True,
        "gateProdClaimed": False,
        "gateRule1MClaimed": False,
        "generatorVersion": GENERATOR_VERSION,
        "legalBitComparisons": stable_state_count * ACTION_COUNT,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": candidate_count,
        "rejected": rejected,
        "scope": "FULL_RULE_DIFF_V4_UNFROZEN_TEST_ONLY",
        "seed": seed,
        "settlementReasonCounts": settlements,
        "sha256": digest,
        "stableStateLegalityComparisons": stable_state_count,
        "unfrozenTestOnly": True,
        "unsupported": unsupported,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the bounded test-only UNFROZEN full-rule v4 legality differential"
        )
    )
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument(
        "--candidate-count", type=int, default=DEFAULT_CANDIDATE_COUNT
    )
    args = parser.parse_args(argv)
    try:
        summary = run_differential(
            args.probe, seed=args.seed, candidate_count=args.candidate_count
        )
    except (
        ContractError,
        ProtocolError,
        ProbeError,
        DifferentialMismatch,
        ValueError,
    ) as exc:
        invocation = {
            "generatorVersion": GENERATOR_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "requestedRandomCandidateCount": args.candidate_count,
            "seed": args.seed,
        }
        print(
            f"Full-rule v4 differential failed: {exc}; "
            f"invocation={canonical_json(invocation)}",
            file=sys.stderr,
        )
        return 1
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
