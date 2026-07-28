#!/usr/bin/env python3
"""Test-only UNFROZEN v0 differential rehearsal for the NORMAL/PASS slice.

This driver is deliberately not semantic-projection-v1, a production protocol,
a full Collapse Go oracle, or evidence for GATE-RULE-1M.  It keeps the
independent oracle package subprocess-free; only this external test harness
launches the standalone C++ probe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = (REPO_ROOT / "python").resolve()
while str(PYTHON_ROOT) in sys.path:
    sys.path.remove(str(PYTHON_ROOT))
sys.path.insert(0, str(PYTHON_ROOT))


def _require_repository_oracle_module(module_name: str) -> None:
    module = sys.modules.get(module_name)
    module_file = getattr(module, "__file__", None)
    if module is None or module_file is None:
        raise ImportError(f"{module_name} is not a file-backed repository module")
    resolved = Path(module_file).resolve()
    try:
        resolved.relative_to(PYTHON_ROOT)
    except ValueError as exc:
        raise ImportError(
            f"{module_name} resolved outside this checkout: {resolved}"
        ) from exc


for _module_name in tuple(sys.modules):
    if _module_name == "mutago" or _module_name.startswith("mutago."):
        _require_repository_oracle_module(_module_name)

from mutago.collapse_go import (  # noqa: E402
    PASS_ACTION_ID,
    ActionKind,
    Color,
    OracleConfig,
    OracleState,
    Phase,
    PlayerQuotas,
    RejectionCode,
    SpecialQuotas,
    UnsupportedSliceAction,
    apply_action,
    decode_action_v1,
    new_game,
)

for _module_name in (
    "mutago",
    "mutago.collapse_go",
    "mutago.collapse_go.normal_pass_oracle",
):
    _require_repository_oracle_module(_module_name)
del _module_name

PROTOCOL_VERSION = "normal-pass-diff-v0-unfrozen"
GENERATOR_VERSION = "sha256-counter-v0-unfrozen"
DEFAULT_SEED = "mutago-normal-pass-rehearsal"
DEFAULT_CANDIDATE_COUNT = 10000
MIN_RANDOM_CANDIDATE_COUNT = 1478
MAX_RANDOM_CANDIDATE_COUNT = 10000
MAX_EPISODE_STEPS = 160
MAX_REQUEST_FRAME_BYTES = 1024 * 1024
MAX_RESPONSE_FRAME_BYTES = 16 * 1024 * 1024
MAX_PROBE_STDOUT_BYTES = 64 * 1024 * 1024
MAX_PROBE_STDERR_BYTES = 1024 * 1024
PROBE_TIMEOUT_SECONDS = 180
SAFE_INTEGER_MIN = -9007199254740991
SAFE_INTEGER_MAX = 9007199254740991
REQUEST_FIELDS = frozenset(
    ("protocolVersion", "episodeId", "boardSize", "quotaMode", "steps")
)
STEP_FIELDS = frozenset(("candidateActor", "action"))
RESPONSE_FIELDS = frozenset(("protocolVersion", "episodeId", "observations"))
OBSERVATION_FIELDS = frozenset(
    (
        "A",
        "actor",
        "blackOccupancy",
        "captures",
        "consecutivePasses",
        "errorCode",
        "phase",
        "pskHistory",
        "remainingQuotas",
        "score",
        "settlementReason",
        "status",
        "stepIndex",
        "terminalScoring",
        "whiteOccupancy",
    )
)
OCCUPANCY_FIELDS = frozenset(("black", "white"))
QUOTAS_FIELDS = frozenset(("black", "white"))
QUOTA_VECTOR_FIELDS = frozenset(("doubleStart", "eightway", "immortal"))
SCORE_FIELDS = frozenset(
    (
        "blackEmptyArea",
        "blackScoreNumerator",
        "blackStones",
        "denominator",
        "isScored",
        "marginNumerator",
        "whiteEmptyArea",
        "whiteScoreNumerator",
        "whiteStones",
        "winner",
    )
)
STATUS_VALUES = frozenset(("ACCEPTED", "REJECTED", "UNSUPPORTED"))
ERROR_CODE_VALUES = frozenset(
    (
        "NONE",
        "POINT_OFF_BOARD",
        "TERMINAL_STATE",
        "INVALID_PHASE",
        "WRONG_ACTOR",
        "DOUBLE_THRESHOLD",
        "QUOTA_EXHAUSTED",
        "POINT_OCCUPIED",
        "SUICIDE",
        "POSITIONAL_SUPERKO",
        "INTERNAL_INVARIANT",
        "UNSUPPORTED_BY_SLICE",
    )
)
PHASE_VALUES = frozenset(("COLLAPSE_PLAY", "ORDINARY_PLAY", "TERMINAL"))
SETTLEMENT_REASON_VALUES = frozenset(
    ("NONE", "THRESHOLD", "PRE_THRESHOLD_TWO_PASSES")
)
POINT_KINDS = (
    ActionKind.NORMAL,
    ActionKind.IMMORTAL,
    ActionKind.DOUBLE_START,
    ActionKind.EIGHTWAY,
)
KIND_CODE = {kind: index for index, kind in enumerate(POINT_KINDS)}


class ProtocolError(ValueError):
    """A request or response violates this test-only v0 frame contract."""


class ProbeError(RuntimeError):
    """The standalone probe failed or violated its process contract."""


class DifferentialMismatch(AssertionError):
    """The first exact C++/Python projection mismatch."""


class Sha256CounterRng:
    """Deterministic byte stream made only from SHA-256 counter blocks."""

    _DOMAIN = b"MutaGo normal-pass differential v0 unfrozen\x00"

    def __init__(self, seed: str | bytes) -> None:
        if isinstance(seed, str):
            seed_bytes = seed.encode("utf-8")
        elif isinstance(seed, bytes):
            seed_bytes = seed
        else:
            raise TypeError("seed must be str or bytes")
        self._seed = seed_bytes
        self._counter = 0
        self._buffer = bytearray()

    def _refill(self) -> None:
        block = hashlib.sha256(
            self._DOMAIN
            + len(self._seed).to_bytes(8, "big")
            + self._seed
            + self._counter.to_bytes(16, "big")
        ).digest()
        self._counter += 1
        self._buffer.extend(block)

    def bytes(self, count: int) -> bytes:
        if type(count) is not int or count < 0:
            raise ValueError("byte count must be a nonnegative integer")
        while len(self._buffer) < count:
            self._refill()
        result = bytes(self._buffer[:count])
        del self._buffer[:count]
        return result

    def randbelow(self, upper: int) -> int:
        if type(upper) is not int or upper <= 0:
            raise ValueError("upper bound must be a positive integer")
        byte_count = max(1, (upper.bit_length() + 7) // 8)
        ceiling = 1 << (8 * byte_count)
        limit = ceiling - (ceiling % upper)
        while True:
            value = int.from_bytes(self.bytes(byte_count), "big")
            if value < limit:
                return value % upper

    def choice(self, values: Sequence[object]):
        if not values:
            raise ValueError("cannot choose from an empty sequence")
        return values[self.randbelow(len(values))]


@dataclass
class _EpisodeBuilder:
    episode_id: str
    board_size: int
    quota_mode: str
    state: OracleState
    steps: list[dict[str, object]]

    @classmethod
    def create(cls, episode_id: str, board_size: int, quota_mode: str):
        request_stub = {
            "protocolVersion": PROTOCOL_VERSION,
            "episodeId": episode_id,
            "boardSize": board_size,
            "quotaMode": quota_mode,
            "steps": [{"candidateActor": "BLACK", "action": action_v1(1444)}],
        }
        validate_episode_request(request_stub)
        config = _oracle_config(board_size, quota_mode)
        return cls(episode_id, board_size, quota_mode, new_game(config), [])

    def current_actor(self, rng: Sha256CounterRng | None = None) -> Color:
        if self.state.actor is not None:
            return self.state.actor
        if rng is None:
            return Color.BLACK
        return (Color.BLACK, Color.WHITE)[rng.randbelow(2)]

    def add(self, candidate_actor: Color, action: Mapping[str, object]) -> None:
        step = {
            "candidateActor": candidate_actor.value,
            "action": dict(action),
        }
        decode_action_v1(step["action"], self.board_size)
        self.steps.append(step)
        try:
            transition = apply_action(self.state, candidate_actor, step["action"])
        except UnsupportedSliceAction:
            return
        self.state = transition.state

    def request(self) -> dict[str, object]:
        request = {
            "protocolVersion": PROTOCOL_VERSION,
            "episodeId": self.episode_id,
            "boardSize": self.board_size,
            "quotaMode": self.quota_mode,
            "steps": self.steps,
        }
        validate_episode_request(request)
        return request


def action_kind_for_id(action_id: int) -> ActionKind:
    if type(action_id) is not int or not (0 <= action_id <= PASS_ACTION_ID):
        raise ValueError("action_id must be an integer in 0..1444")
    if action_id == PASS_ACTION_ID:
        return ActionKind.PASS
    return POINT_KINDS[action_id // 361]


def action_v1(action_id: int) -> dict[str, object]:
    kind = action_kind_for_id(action_id)
    return {
        "schemaVersion": "action-v1",
        "actionId": action_id,
        "kind": kind.value,
    }


def board_action_v1(
    board_size: int,
    x: int,
    y: int,
    kind: ActionKind = ActionKind.NORMAL,
) -> dict[str, object]:
    if board_size not in (9, 13, 19):
        raise ValueError("board_size must be 9, 13, or 19")
    if kind not in KIND_CODE:
        raise ValueError("board point actions require a point action kind")
    if type(x) is not int or type(y) is not int or not (
        0 <= x < board_size and 0 <= y < board_size
    ):
        raise ValueError("board-local point is outside the selected board")
    offset = (19 - board_size) // 2
    canvas_x = x + offset
    canvas_y = y + offset
    return action_v1(361 * KIND_CODE[kind] + 19 * canvas_y + canvas_x)


def _require_exact_fields(
    value: object, fields: frozenset[str], context: str
) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ProtocolError(f"{context} must be a JSON object")
    actual = frozenset(value)
    if actual != fields:
        raise ProtocolError(
            f"{context} fields differ: missing={sorted(fields - actual)}, "
            f"unknown={sorted(actual - fields, key=repr)}"
        )
    return value


def _valid_episode_id(episode_id: str) -> bool:
    return 1 <= len(episode_id) <= 128 and all(
        character.isascii()
        and (character.isalnum() or character in "._-")
        for character in episode_id
    )


def validate_episode_request(request: object) -> Mapping[str, object]:
    frame = _require_exact_fields(request, REQUEST_FIELDS, "episode request")
    if frame["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError(f"protocolVersion must be {PROTOCOL_VERSION}")
    episode_id = frame["episodeId"]
    if type(episode_id) is not str or not _valid_episode_id(episode_id):
        raise ProtocolError(
            "episodeId must contain 1..128 ASCII letters, digits, '.', '_', or '-'"
        )
    board_size = frame["boardSize"]
    if type(board_size) is not int or board_size not in (9, 13, 19):
        raise ProtocolError("boardSize must be exactly 9, 13, or 19")
    if frame["quotaMode"] not in ("ZERO", "ONE"):
        raise ProtocolError("quotaMode must be ZERO or ONE")
    steps = frame["steps"]
    if type(steps) is not list or not (1 <= len(steps) <= MAX_EPISODE_STEPS):
        raise ProtocolError("steps must be a nonempty array within the resource limit")
    for index, step_value in enumerate(steps):
        step = _require_exact_fields(step_value, STEP_FIELDS, f"step {index}")
        if step["candidateActor"] not in ("BLACK", "WHITE"):
            raise ProtocolError(f"step {index} candidateActor must be BLACK or WHITE")
        try:
            decode_action_v1(step["action"], board_size)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"step {index} has invalid Action V1: {exc}") from exc
    canonical_size = len(canonical_json(frame).encode("utf-8"))
    if canonical_size > MAX_REQUEST_FRAME_BYTES:
        raise ProtocolError("canonical request exceeds the 1 MiB request limit")
    return frame


def _require_int(
    value: object,
    context: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum or (
        maximum is not None and value > maximum
    ):
        bounds = f"{minimum}..{maximum}" if maximum is not None else f">={minimum}"
        raise ProtocolError(f"{context} must be an integer in {bounds}")
    return value


def _validate_point_list(
    value: object, context: str, point_count: int
) -> tuple[int, ...]:
    if type(value) is not list:
        raise ProtocolError(f"{context} must be an array")
    points: list[int] = []
    previous = -1
    for index, point in enumerate(value):
        point_value = _require_int(
            point,
            f"{context}[{index}]",
            maximum=point_count - 1,
        )
        if point_value <= previous:
            raise ProtocolError(f"{context} must be strictly increasing")
        points.append(point_value)
        previous = point_value
    return tuple(points)


def _validate_occupancy_object(
    value: object, context: str, point_count: int
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    occupancy = _require_exact_fields(value, OCCUPANCY_FIELDS, context)
    black = _validate_point_list(occupancy["black"], f"{context}.black", point_count)
    white = _validate_point_list(occupancy["white"], f"{context}.white", point_count)
    if set(black).intersection(white):
        raise ProtocolError(f"{context} black and white points must be disjoint")
    return black, white


def _validate_remaining_quotas(value: object, context: str) -> None:
    quotas = _require_exact_fields(value, QUOTAS_FIELDS, context)
    for color in ("black", "white"):
        vector = _require_exact_fields(
            quotas[color], QUOTA_VECTOR_FIELDS, f"{context}.{color}"
        )
        for ability in sorted(QUOTA_VECTOR_FIELDS):
            _require_int(
                vector[ability],
                f"{context}.{color}.{ability}",
                maximum=1,
            )


def _validate_score(value: object, context: str) -> bool:
    score = _require_exact_fields(value, SCORE_FIELDS, context)
    if type(score["isScored"]) is not bool:
        raise ProtocolError(f"{context}.isScored must be a boolean")
    for field in (
        "blackEmptyArea",
        "blackScoreNumerator",
        "blackStones",
        "marginNumerator",
        "whiteEmptyArea",
        "whiteScoreNumerator",
        "whiteStones",
    ):
        _require_int(score[field], f"{context}.{field}")
    if score["denominator"] != 2 or type(score["denominator"]) is not int:
        raise ProtocolError(f"{context}.denominator must be integer 2")
    winner = score["winner"]
    if winner is not None and winner not in ("BLACK", "WHITE"):
        raise ProtocolError(f"{context}.winner must be BLACK, WHITE, or null")
    if score["isScored"]:
        if winner is None:
            raise ProtocolError(f"{context}.winner is required when scored")
    else:
        if winner is not None:
            raise ProtocolError(f"{context}.winner must be null when unscored")
        for field in SCORE_FIELDS - frozenset(("denominator", "isScored", "winner")):
            if score[field] != 0:
                raise ProtocolError(f"{context}.{field} must be zero when unscored")
    return score["isScored"]


def _validate_observation(
    observation: object,
    index: int,
    board_size: int,
) -> None:
    context = f"observation {index}"
    fields = _require_exact_fields(observation, OBSERVATION_FIELDS, context)
    if type(fields["stepIndex"]) is not int or fields["stepIndex"] != index:
        raise ProtocolError(f"{context} has the wrong integer stepIndex")
    _require_int(fields["A"], f"{context}.A")
    _require_int(
        fields["consecutivePasses"],
        f"{context}.consecutivePasses",
        maximum=2,
    )

    phase = fields["phase"]
    if type(phase) is not str or phase not in PHASE_VALUES:
        raise ProtocolError(f"{context}.phase has an unknown value")
    actor = fields["actor"]
    if phase == "TERMINAL":
        if actor is not None:
            raise ProtocolError(f"{context}.actor must be null in TERMINAL")
    elif actor not in ("BLACK", "WHITE"):
        raise ProtocolError(f"{context}.actor must be BLACK or WHITE")

    point_count = board_size * board_size
    black = _validate_point_list(
        fields["blackOccupancy"], f"{context}.blackOccupancy", point_count
    )
    white = _validate_point_list(
        fields["whiteOccupancy"], f"{context}.whiteOccupancy", point_count
    )
    if set(black).intersection(white):
        raise ProtocolError(f"{context} visible black and white occupancy overlaps")
    _validate_occupancy_object(fields["captures"], f"{context}.captures", point_count)

    history = fields["pskHistory"]
    if type(history) is not list or not history:
        raise ProtocolError(f"{context}.pskHistory must be a nonempty array")
    projected_history = [
        _validate_occupancy_object(entry, f"{context}.pskHistory[{history_index}]", point_count)
        for history_index, entry in enumerate(history)
    ]
    if projected_history[-1] != (black, white):
        raise ProtocolError(f"{context}.pskHistory must end at visible occupancy")

    _validate_remaining_quotas(fields["remainingQuotas"], f"{context}.remainingQuotas")
    is_scored = _validate_score(fields["score"], f"{context}.score")
    if (phase == "TERMINAL") != is_scored:
        raise ProtocolError(f"{context} phase and score state disagree")

    status = fields["status"]
    error_code = fields["errorCode"]
    if type(status) is not str or status not in STATUS_VALUES:
        raise ProtocolError(f"{context}.status has an unknown value")
    if type(error_code) is not str or error_code not in ERROR_CODE_VALUES:
        raise ProtocolError(f"{context}.errorCode has an unknown value")
    if status == "ACCEPTED" and error_code != "NONE":
        raise ProtocolError(f"{context} accepted status requires errorCode NONE")
    if status == "UNSUPPORTED" and error_code != "UNSUPPORTED_BY_SLICE":
        raise ProtocolError(
            f"{context} unsupported status requires UNSUPPORTED_BY_SLICE"
        )
    if status == "REJECTED" and error_code in ("NONE", "UNSUPPORTED_BY_SLICE"):
        raise ProtocolError(f"{context} rejected status has an invalid errorCode")

    settlement_reason = fields["settlementReason"]
    if type(settlement_reason) is not str or settlement_reason not in SETTLEMENT_REASON_VALUES:
        raise ProtocolError(f"{context}.settlementReason has an unknown value")
    if type(fields["terminalScoring"]) is not bool:
        raise ProtocolError(f"{context}.terminalScoring must be a boolean")


def validate_episode_response(
    response: object, request: Mapping[str, object]
) -> Mapping[str, object]:
    frame = _require_exact_fields(response, RESPONSE_FIELDS, "episode response")
    if frame["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError("response protocolVersion differs")
    if frame["episodeId"] != request["episodeId"]:
        raise ProtocolError("response episodeId differs")
    observations = frame["observations"]
    expected_count = len(request["steps"])
    if type(observations) is not list or len(observations) != expected_count:
        raise ProtocolError(
            f"response observations must contain exactly {expected_count} entries"
        )
    for index, observation in enumerate(observations):
        _validate_observation(observation, index, request["boardSize"])
    return frame


def _validate_restricted_json(value: object, path: str = "$") -> None:
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not SAFE_INTEGER_MIN <= value <= SAFE_INTEGER_MAX:
            raise ProtocolError(f"unsafe integer at {path}")
        return
    if type(value) is str:
        if any(ord(character) > 0x7F for character in value):
            raise ProtocolError(f"non-ASCII string at {path}")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_restricted_json(item, f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or any(ord(character) > 0x7F for character in key):
                raise ProtocolError(f"non-ASCII or non-string key at {path}")
            _validate_restricted_json(item, f"{path}.{key}")
        return
    raise ProtocolError(f"unsupported JSON value at {path}: {type(value).__name__}")


def canonical_json(value: object) -> str:
    _validate_restricted_json(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _reject_float(raw: str):
    raise ProtocolError(f"floating-point JSON is forbidden: {raw}")


def _reject_constant(raw: str):
    raise ProtocolError(f"non-JSON numeric constant is forbidden: {raw}")


def _reject_duplicate_pairs(pairs: Iterable[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def parse_canonical_response_line(
    line: str, request: Mapping[str, object]
) -> Mapping[str, object]:
    if not line:
        raise ProtocolError("probe returned an empty response line")
    if len(line.encode("utf-8")) > MAX_RESPONSE_FRAME_BYTES:
        raise ProtocolError("probe response exceeds the 16 MiB response limit")
    try:
        parsed = json.loads(
            line,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"probe returned invalid JSON: {exc}") from exc
    canonical = canonical_json(parsed)
    if line != canonical:
        raise ProtocolError("probe response is not canonical restricted-profile JSON")
    return validate_episode_response(parsed, request)


def _oracle_config(board_size: int, quota_mode: str) -> OracleConfig:
    if quota_mode == "ZERO":
        quotas = PlayerQuotas.zero()
    elif quota_mode == "ONE":
        quotas = PlayerQuotas(
            black=SpecialQuotas(),
            white=SpecialQuotas(),
        )
    else:
        raise ProtocolError("unknown quota mode")
    return OracleConfig(board_size=board_size, quotas=quotas)


def _occupancy_projection(occupancy) -> dict[str, object]:
    return {"black": list(occupancy.black), "white": list(occupancy.white)}


def _quota_projection(state: OracleState) -> dict[str, object]:
    def vector(quotas: SpecialQuotas) -> dict[str, object]:
        return {
            "doubleStart": quotas.double_start,
            "eightway": quotas.eightway,
            "immortal": quotas.immortal,
        }

    return {
        "black": vector(state.remaining_quotas.black),
        "white": vector(state.remaining_quotas.white),
    }


def _score_projection(state: OracleState) -> dict[str, object]:
    if state.terminal is None:
        return {
            "blackEmptyArea": 0,
            "blackScoreNumerator": 0,
            "blackStones": 0,
            "denominator": 2,
            "isScored": False,
            "marginNumerator": 0,
            "whiteEmptyArea": 0,
            "whiteScoreNumerator": 0,
            "whiteStones": 0,
            "winner": None,
        }
    score = state.terminal.score
    return {
        "blackEmptyArea": score.black_empty_area,
        "blackScoreNumerator": score.black_score_numerator,
        "blackStones": score.black_stones,
        "denominator": score.denominator,
        "isScored": True,
        "marginNumerator": score.margin_numerator,
        "whiteEmptyArea": score.white_empty_area,
        "whiteScoreNumerator": score.white_score_numerator,
        "whiteStones": score.white_stones,
        "winner": score.winner.value,
    }


def oracle_episode_response(request: object) -> dict[str, object]:
    frame = validate_episode_request(request)
    board_size = frame["boardSize"]
    state = new_game(_oracle_config(board_size, frame["quotaMode"]))
    observations: list[dict[str, object]] = []

    for step_index, step in enumerate(frame["steps"]):
        candidate_actor = Color(step["candidateActor"])
        try:
            transition = apply_action(state, candidate_actor, step["action"])
        except UnsupportedSliceAction:
            status = "UNSUPPORTED"
            error_code = "UNSUPPORTED_BY_SLICE"
            captured = {"black": [], "white": []}
            settlement_reason = "NONE"
            terminal_scoring = False
        else:
            state = transition.state
            if transition.accepted:
                status = "ACCEPTED"
                error_code = "NONE"
                captured = _occupancy_projection(transition.atomic_event.captured)
            else:
                status = "REJECTED"
                error_code = transition.rejection_code.value
                captured = {"black": [], "white": []}
            settlement_reason = (
                transition.settlement.reason.value
                if transition.settlement is not None
                else "NONE"
            )
            terminal_scoring = transition.terminal_event is not None

        occupancy = _occupancy_projection(state.board.occupancy)
        observations.append(
            {
                "A": state.atomic_action_count,
                "actor": state.actor.value if state.actor is not None else None,
                "blackOccupancy": occupancy["black"],
                "captures": captured,
                "consecutivePasses": state.consecutive_passes,
                "errorCode": error_code,
                "phase": state.phase.value,
                "pskHistory": [
                    _occupancy_projection(entry) for entry in state.psk_history
                ],
                "remainingQuotas": _quota_projection(state),
                "score": _score_projection(state),
                "settlementReason": settlement_reason,
                "status": status,
                "stepIndex": step_index,
                "terminalScoring": terminal_scoring,
                "whiteOccupancy": occupancy["white"],
            }
        )

    return {
        "episodeId": frame["episodeId"],
        "observations": observations,
        "protocolVersion": PROTOCOL_VERSION,
    }


def _first_difference(expected: object, actual: object, path: str = "$") -> str | None:
    if type(expected) is not type(actual):
        return (
            f"{path}: type {type(expected).__name__} != "
            f"{type(actual).__name__}"
        )
    if type(expected) is dict:
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            return (
                f"{path}: keys differ; missing={sorted(expected_keys - actual_keys)}, "
                f"extra={sorted(actual_keys - expected_keys)}"
            )
        for key in sorted(expected_keys):
            difference = _first_difference(
                expected[key], actual[key], f"{path}.{key}"
            )
            if difference is not None:
                return difference
        return None
    if type(expected) is list:
        if len(expected) != len(actual):
            return f"{path}: length {len(expected)} != {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = _first_difference(
                expected_item, actual_item, f"{path}[{index}]"
            )
            if difference is not None:
                return difference
        return None
    if expected != actual:
        return f"{path}: expected {expected!r}, actual {actual!r}"
    return None


def compare_exact(expected: object, actual: object, *, episode_id: str) -> None:
    difference = _first_difference(expected, actual)
    if difference is not None:
        raise DifferentialMismatch(f"episode {episode_id}: {difference}")


def _mismatch_prefix_length(
    expected: Mapping[str, object],
    actual: Mapping[str, object],
    request: Mapping[str, object],
) -> int:
    expected_observations = expected.get("observations")
    actual_observations = actual.get("observations")
    if type(expected_observations) is list and type(actual_observations) is list:
        for index, (expected_observation, actual_observation) in enumerate(
            zip(expected_observations, actual_observations)
        ):
            if _first_difference(expected_observation, actual_observation) is not None:
                return index + 1
    return len(request["steps"])


def _reproduction_context(
    manifest: Mapping[str, object],
    request: Mapping[str, object],
    request_line: str,
    prefix_length: int,
) -> str:
    action_prefix = request["steps"][:prefix_length]
    return (
        f"manifest={canonical_json(manifest)}; "
        f"canonicalRequest={request_line}; "
        f"actionPrefix={canonical_json(action_prefix)}"
    )


def _opponent(actor: Color) -> Color:
    return Color.WHITE if actor is Color.BLACK else Color.BLACK


def _random_actor(rng: Sha256CounterRng) -> Color:
    return (Color.BLACK, Color.WHITE)[rng.randbelow(2)]


def _random_board_point_action(
    board_size: int,
    rng: Sha256CounterRng,
    kind: ActionKind = ActionKind.NORMAL,
) -> dict[str, object]:
    point = rng.randbelow(board_size * board_size)
    return board_action_v1(board_size, point % board_size, point // board_size, kind)


def _legal_current_action(
    state: OracleState, rng: Sha256CounterRng
) -> dict[str, object]:
    if state.actor is None:
        return _random_board_point_action(state.config.board_size, rng)
    point_count = state.config.board_size * state.config.board_size
    start = rng.randbelow(point_count)
    stride = 1 + 2 * rng.randbelow((point_count + 1) // 2)
    while math.gcd(stride, point_count) != 1:
        stride = (stride + 2) % point_count
        if stride == 0:
            stride = 1
    for offset in range(point_count):
        point = (start + offset * stride) % point_count
        action = board_action_v1(
            state.config.board_size,
            point % state.config.board_size,
            point // state.config.board_size,
        )
        transition = apply_action(state, state.actor, action)
        if transition.accepted:
            return action
    return action_v1(PASS_ACTION_ID)


def _occupied_action(
    state: OracleState, rng: Sha256CounterRng
) -> dict[str, object] | None:
    occupied = state.board.occupancy.black + state.board.occupancy.white
    if not occupied:
        return None
    point = occupied[rng.randbelow(len(occupied))]
    return board_action_v1(
        state.config.board_size,
        point % state.config.board_size,
        point // state.config.board_size,
    )


def _off_footprint_action(
    board_size: int, rng: Sha256CounterRng
) -> dict[str, object] | None:
    if board_size == 19:
        return None
    offset = (19 - board_size) // 2
    outside = [
        point
        for point in range(361)
        if not (
            offset <= point % 19 < offset + board_size
            and offset <= point // 19 < offset + board_size
        )
    ]
    canvas_point = outside[rng.randbelow(len(outside))]
    kind = POINT_KINDS[rng.randbelow(len(POINT_KINDS))]
    return action_v1(361 * KIND_CODE[kind] + canvas_point)


def generate_curated_episodes() -> list[dict[str, object]]:
    episodes: list[dict[str, object]] = []

    basic = _EpisodeBuilder.create("curated-basic-terminal-9-zero", 9, "ZERO")
    basic.add(Color.BLACK, board_action_v1(9, 4, 4))
    basic.add(Color.BLACK, action_v1(PASS_ACTION_ID))
    basic.add(Color.WHITE, board_action_v1(9, 4, 4))
    basic.add(Color.WHITE, action_v1(PASS_ACTION_ID))
    basic.add(Color.BLACK, action_v1(PASS_ACTION_ID))
    basic.add(Color.WHITE, board_action_v1(9, 0, 0, ActionKind.IMMORTAL))
    basic.add(Color.WHITE, board_action_v1(9, 0, 0))
    basic.add(Color.BLACK, action_v1(PASS_ACTION_ID))
    basic.add(Color.WHITE, action_v1(PASS_ACTION_ID))
    basic.add(Color.BLACK, board_action_v1(9, 1, 0))
    basic.add(Color.WHITE, action_v1(0))
    episodes.append(basic.request())

    capture = _EpisodeBuilder.create("curated-capture-9-zero", 9, "ZERO")
    for actor, x, y in (
        (Color.BLACK, 0, 2),
        (Color.WHITE, 1, 2),
        (Color.BLACK, 1, 1),
        (Color.WHITE, 3, 2),
        (Color.BLACK, 1, 3),
        (Color.WHITE, 8, 8),
        (Color.BLACK, 4, 2),
        (Color.WHITE, 8, 7),
        (Color.BLACK, 3, 1),
        (Color.WHITE, 7, 8),
        (Color.BLACK, 3, 3),
        (Color.WHITE, 7, 7),
        (Color.BLACK, 2, 2),
    ):
        capture.add(actor, board_action_v1(9, x, y))
    capture.add(Color.WHITE, board_action_v1(9, 2, 2))
    episodes.append(capture.request())

    suicide = _EpisodeBuilder.create("curated-suicide-9-zero", 9, "ZERO")
    for actor, x, y in (
        (Color.BLACK, 8, 8),
        (Color.WHITE, 1, 2),
        (Color.BLACK, 8, 7),
        (Color.WHITE, 3, 2),
        (Color.BLACK, 7, 8),
        (Color.WHITE, 2, 1),
        (Color.BLACK, 7, 7),
        (Color.WHITE, 2, 3),
        (Color.BLACK, 2, 2),
    ):
        suicide.add(actor, board_action_v1(9, x, y))
    episodes.append(suicide.request())

    psk = _EpisodeBuilder.create("curated-psk-9-zero", 9, "ZERO")
    for actor, x, y in (
        (Color.BLACK, 1, 2),
        (Color.WHITE, 1, 1),
        (Color.BLACK, 3, 2),
        (Color.WHITE, 3, 1),
        (Color.BLACK, 2, 3),
        (Color.WHITE, 2, 0),
        (Color.BLACK, 8, 8),
        (Color.WHITE, 2, 2),
        (Color.BLACK, 2, 1),
        (Color.WHITE, 2, 2),
    ):
        psk.add(actor, board_action_v1(9, x, y))
    episodes.append(psk.request())

    unsupported = _EpisodeBuilder.create("curated-unsupported-9-one", 9, "ONE")
    unsupported.add(Color.BLACK, board_action_v1(9, 0, 0, ActionKind.IMMORTAL))
    unsupported.add(Color.BLACK, board_action_v1(9, 1, 0, ActionKind.DOUBLE_START))
    unsupported.add(Color.BLACK, board_action_v1(9, 2, 0, ActionKind.EIGHTWAY))
    unsupported.add(Color.BLACK, board_action_v1(9, 4, 4))
    unsupported.add(Color.WHITE, board_action_v1(9, 4, 4, ActionKind.IMMORTAL))
    unsupported.add(Color.WHITE, action_v1(PASS_ACTION_ID))
    unsupported.add(Color.BLACK, action_v1(PASS_ACTION_ID))
    unsupported.add(Color.WHITE, board_action_v1(9, 0, 0, ActionKind.IMMORTAL))
    unsupported.add(Color.WHITE, action_v1(PASS_ACTION_ID))
    unsupported.add(Color.BLACK, action_v1(PASS_ACTION_ID))
    unsupported.add(Color.WHITE, action_v1(361))
    episodes.append(unsupported.request())

    threshold_rng = Sha256CounterRng("curated-threshold-v0")
    for board_size in (9, 13, 19):
        threshold = _EpisodeBuilder.create(
            f"curated-threshold-{board_size}-zero", board_size, "ZERO"
        )
        while threshold.state.phase is Phase.COLLAPSE_PLAY:
            action = _legal_current_action(threshold.state, threshold_rng)
            if action["kind"] == ActionKind.PASS.value:
                raise AssertionError(
                    f"could not construct NORMAL threshold prefix for {board_size}x{board_size}"
                )
            threshold.add(threshold.current_actor(), action)
        if threshold.state.atomic_action_count != threshold.state.threshold:
            raise AssertionError("curated threshold episode settled at the wrong action")
        episodes.append(threshold.request())

    return episodes


def _structured_random_episodes(
    rng: Sha256CounterRng, seed_tag: str
) -> list[dict[str, object]]:
    episodes: list[dict[str, object]] = []
    for board_size in (9, 13, 19):
        builder = _EpisodeBuilder.create(
            f"random-{seed_tag}-structured-{board_size}", board_size, "ZERO"
        )
        builder.add(_opponent(builder.current_actor()), action_v1(PASS_ACTION_ID))
        first_action = _legal_current_action(builder.state, rng)
        builder.add(builder.current_actor(), first_action)
        builder.add(builder.current_actor(), first_action)
        builder.add(builder.current_actor(), action_v1(PASS_ACTION_ID))
        builder.add(builder.current_actor(), action_v1(PASS_ACTION_ID))
        special = POINT_KINDS[1 + rng.randbelow(3)]
        builder.add(
            builder.current_actor(),
            _random_board_point_action(board_size, rng, special),
        )
        builder.add(builder.current_actor(), _legal_current_action(builder.state, rng))
        builder.add(builder.current_actor(), action_v1(PASS_ACTION_ID))
        builder.add(builder.current_actor(), action_v1(PASS_ACTION_ID))
        builder.add(_random_actor(rng), _random_board_point_action(board_size, rng))
        off_footprint = _off_footprint_action(board_size, rng)
        builder.add(
            _random_actor(rng),
            off_footprint if off_footprint is not None else action_v1(PASS_ACTION_ID),
        )
        episodes.append(builder.request())
    return episodes


def _all_id_coverage_episodes(
    rng: Sha256CounterRng, seed_tag: str
) -> list[dict[str, object]]:
    episodes: list[dict[str, object]] = []
    for board_index, board_size in enumerate((9, 13, 19)):
        action_ids = list(range(board_index, PASS_ACTION_ID + 1, 3))
        for chunk_index, start in enumerate(range(0, len(action_ids), MAX_EPISODE_STEPS)):
            builder = _EpisodeBuilder.create(
                f"random-{seed_tag}-all-ids-{board_size}-{chunk_index}",
                board_size,
                "ZERO",
            )
            for action_id in action_ids[start : start + MAX_EPISODE_STEPS]:
                current = builder.current_actor(rng)
                actor = _opponent(current) if rng.randbelow(5) == 0 else current
                builder.add(actor, action_v1(action_id))
            episodes.append(builder.request())
    return episodes


def _random_episode(
    rng: Sha256CounterRng,
    seed_tag: str,
    sequence: int,
    maximum_steps: int,
) -> dict[str, object]:
    board_size = (9, 13, 19)[rng.randbelow(3)]
    builder = _EpisodeBuilder.create(
        f"random-{seed_tag}-sha-{sequence:06d}", board_size, "ZERO"
    )
    while len(builder.steps) < maximum_steps:
        if builder.state.phase is Phase.TERMINAL:
            builder.add(_random_actor(rng), action_v1(rng.randbelow(1445)))
            break

        mode = rng.randbelow(8)
        current = builder.current_actor(rng)
        if mode == 0:
            builder.add(current, _legal_current_action(builder.state, rng))
        elif mode == 1:
            builder.add(current, action_v1(PASS_ACTION_ID))
        elif mode == 2:
            builder.add(_opponent(current), action_v1(rng.randbelow(1445)))
        elif mode == 3:
            off_footprint = _off_footprint_action(board_size, rng)
            if off_footprint is None:
                builder.add(_opponent(current), action_v1(rng.randbelow(1445)))
            else:
                builder.add(current, off_footprint)
        elif mode == 4:
            occupied = _occupied_action(builder.state, rng)
            builder.add(
                current,
                occupied
                if occupied is not None
                else _legal_current_action(builder.state, rng),
            )
        elif mode == 5:
            builder.add(current, action_v1(rng.randbelow(1445)))
        elif mode == 6:
            special = POINT_KINDS[1 + rng.randbelow(3)]
            builder.add(
                current, _random_board_point_action(board_size, rng, special)
            )
        else:
            if builder.state.phase is Phase.COLLAPSE_PLAY and rng.randbelow(3) == 0:
                builder.add(current, action_v1(PASS_ACTION_ID))
            else:
                builder.add(current, _legal_current_action(builder.state, rng))
    return builder.request()


def generate_random_episodes(
    seed: str, candidate_count: int
) -> list[dict[str, object]]:
    if type(candidate_count) is not int or not (
        MIN_RANDOM_CANDIDATE_COUNT
        <= candidate_count
        <= MAX_RANDOM_CANDIDATE_COUNT
    ):
        raise ValueError(
            f"candidate_count must be in {MIN_RANDOM_CANDIDATE_COUNT}.."
            f"{MAX_RANDOM_CANDIDATE_COUNT} to retain structured states, all "
            "1445 Action V1 IDs, and bounded complete-corpus transport"
        )
    rng = Sha256CounterRng(seed)
    seed_tag = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    episodes = _structured_random_episodes(rng, seed_tag)
    episodes.extend(_all_id_coverage_episodes(rng, seed_tag))
    generated = sum(len(request["steps"]) for request in episodes)
    if generated != MIN_RANDOM_CANDIDATE_COUNT:
        raise AssertionError(
            f"mandatory random corpus changed size: {generated} != "
            f"{MIN_RANDOM_CANDIDATE_COUNT}"
        )

    sequence = 0
    while generated < candidate_count:
        maximum_steps = min(64, candidate_count - generated)
        request = _random_episode(rng, seed_tag, sequence, maximum_steps)
        episodes.append(request)
        generated += len(request["steps"])
        sequence += 1
    if generated != candidate_count:
        raise AssertionError("random generator did not produce the requested count")
    return episodes


def _digest_record(digest, data: str) -> None:
    encoded = data.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


@dataclass(frozen=True)
class _ProbeProcessResult:
    returncode: int
    stdout: str
    stderr: str


def _run_probe_process(
    command: Sequence[str], probe_input: str, timeout_seconds: float
) -> _ProbeProcessResult:
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise ProbeError(f"could not launch probe {command[0]}: {exc}") from exc

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    overflow = threading.Event()
    overflow_streams: list[str] = []
    stream_errors: list[tuple[str, BaseException]] = []
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    def read_bounded(
        stream,
        limit: int,
        chunks: list[bytes],
        stream_name: str,
    ) -> None:
        total = 0
        try:
            while True:
                chunk = stream.read(64 * 1024)
                if not chunk:
                    break
                remaining = max(0, limit - total)
                if remaining:
                    chunks.append(chunk[:remaining])
                total += len(chunk)
                if total > limit and stream_name not in overflow_streams:
                    overflow_streams.append(stream_name)
                    overflow.set()
        except BaseException as exc:  # pragma: no cover - defensive pipe failure
            stream_errors.append((stream_name, exc))
            overflow.set()
        finally:
            stream.close()

    writer_errors: list[BaseException] = []

    def write_input() -> None:
        try:
            process.stdin.write(probe_input.encode("utf-8"))
            process.stdin.close()
        except BrokenPipeError:
            pass
        except BaseException as exc:  # pragma: no cover - defensive pipe failure
            writer_errors.append(exc)
            try:
                process.stdin.close()
            except OSError:
                pass

    stdout_thread = threading.Thread(
        target=read_bounded,
        args=(process.stdout, MAX_PROBE_STDOUT_BYTES, stdout_chunks, "stdout"),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=read_bounded,
        args=(process.stderr, MAX_PROBE_STDERR_BYTES, stderr_chunks, "stderr"),
        daemon=True,
    )
    writer_thread = threading.Thread(target=write_input, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    writer_thread.start()

    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    while process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            process.kill()
            break
        if overflow.wait(timeout=min(0.05, remaining)):
            if process.poll() is None:
                process.kill()
            break

    try:
        returncode = process.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - kill should terminate
        process.kill()
        process.wait()
        raise ProbeError("probe did not terminate after kill") from exc

    writer_thread.join()
    stdout_thread.join()
    stderr_thread.join()

    stdout_bytes = b"".join(stdout_chunks)
    stderr_bytes = b"".join(stderr_chunks)
    if timed_out:
        raise ProbeError(
            f"probe exceeded the {timeout_seconds}-second corpus deadline; "
            f"stderr={_timeout_text(stderr_bytes)!r}"
        )
    if overflow_streams:
        limits = {
            "stdout": MAX_PROBE_STDOUT_BYTES,
            "stderr": MAX_PROBE_STDERR_BYTES,
        }
        details = ", ".join(
            f"{name}>{limits[name]} bytes" for name in sorted(overflow_streams)
        )
        raise ProbeError(f"probe exceeded bounded process output: {details}")
    if stream_errors:
        name, exc = stream_errors[0]
        raise ProbeError(f"could not read probe {name}: {exc}") from exc
    if writer_errors and returncode == 0:
        raise ProbeError(f"could not write probe input: {writer_errors[0]}")
    try:
        stdout = stdout_bytes.decode("utf-8", errors="strict")
        stderr = stderr_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProbeError(f"probe output is not UTF-8: {exc}") from exc
    return _ProbeProcessResult(returncode, stdout, stderr)


def run_differential(
    probe_path: Path | str,
    *,
    seed: str = DEFAULT_SEED,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
) -> dict[str, object]:
    probe = Path(probe_path).expanduser().resolve()
    if not probe.is_file():
        raise ProbeError(f"probe executable does not exist: {probe}")

    curated = generate_curated_episodes()
    random_episodes = generate_random_episodes(seed, candidate_count)
    episodes = curated + random_episodes
    manifest = {
        "candidateCount": candidate_count,
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "seed": seed,
    }
    transcript_digest = hashlib.sha256()
    _digest_record(transcript_digest, canonical_json(manifest))

    request_lines: list[str] = []
    expected_responses: list[dict[str, object]] = []
    for request in episodes:
        request_line = canonical_json(request)
        if len(request_line.encode("utf-8")) > MAX_REQUEST_FRAME_BYTES:
            raise ProtocolError(
                f"episode {request['episodeId']} exceeds the 1 MiB request limit"
            )
        request_lines.append(request_line)
        expected_responses.append(oracle_episode_response(request))
    probe_input = "".join(request_line + "\n" for request_line in request_lines)

    completed = _run_probe_process(
        [str(probe)], probe_input, PROBE_TIMEOUT_SECONDS
    )

    if completed.returncode != 0:
        raise ProbeError(
            f"probe exited with {completed.returncode}; stderr={completed.stderr!r}"
        )
    if completed.stderr:
        raise ProbeError(
            f"probe emitted diagnostics on a successful run: {completed.stderr!r}"
        )
    if not completed.stdout.endswith("\n"):
        raise ProbeError("probe output is not newline-terminated")
    response_lines = completed.stdout[:-1].split("\n")
    if len(response_lines) != len(episodes):
        raise ProbeError(
            f"probe emitted {len(response_lines)} response lines for "
            f"{len(episodes)} episode requests"
        )

    accepted = 0
    rejected = 0
    unsupported = 0
    error_counts: dict[str, int] = {}
    settlement_reason_counts: dict[str, int] = {}
    threshold_board_sizes: set[int] = set()
    board_candidate_counts = {"9": 0, "13": 0, "19": 0}
    random_action_ids: set[int] = set()

    for request, request_line, expected, response_line in zip(
        episodes, request_lines, expected_responses, response_lines
    ):
        try:
            actual = parse_canonical_response_line(response_line, request)
        except ProtocolError as exc:
            context = _reproduction_context(
                manifest, request, request_line, len(request["steps"])
            )
            raise ProtocolError(f"{exc}; {context}") from exc
        try:
            compare_exact(expected, actual, episode_id=request["episodeId"])
        except DifferentialMismatch as exc:
            context = _reproduction_context(
                manifest,
                request,
                request_line,
                _mismatch_prefix_length(expected, actual, request),
            )
            raise DifferentialMismatch(f"{exc}; {context}") from exc
        _digest_record(transcript_digest, request_line)
        _digest_record(transcript_digest, response_line)
        board_candidate_counts[str(request["boardSize"])] += len(request["steps"])
        if request["episodeId"].startswith("random-"):
            random_action_ids.update(
                step["action"]["actionId"] for step in request["steps"]
            )
        for observation in expected["observations"]:
            status = observation["status"]
            if status == "ACCEPTED":
                accepted += 1
            elif status == "REJECTED":
                rejected += 1
            else:
                unsupported += 1
            error_code = observation["errorCode"]
            error_counts[error_code] = error_counts.get(error_code, 0) + 1
            settlement_reason = observation["settlementReason"]
            settlement_reason_counts[settlement_reason] = (
                settlement_reason_counts.get(settlement_reason, 0) + 1
            )
            if settlement_reason == "THRESHOLD":
                threshold_board_sizes.add(request["boardSize"])

    curated_count = sum(len(request["steps"]) for request in curated)
    total_count = curated_count + candidate_count
    if accepted + rejected + unsupported != total_count:
        raise AssertionError("summary status counts do not match the compared candidates")
    if len(random_action_ids) != 1445:
        raise AssertionError("random corpus did not retain all 1445 Action V1 IDs")
    if threshold_board_sizes != {9, 13, 19}:
        raise AssertionError(
            "complete rehearsal did not compare threshold settlement on every board size"
        )

    return {
        "accepted": accepted,
        "boardCandidateCounts": board_candidate_counts,
        "candidateCount": total_count,
        "curatedCandidateCount": curated_count,
        "episodeCount": len(episodes),
        "errorCounts": error_counts,
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": candidate_count,
        "randomUniqueActionIds": len(random_action_ids),
        "rehearsalOnly": True,
        "rejected": rejected,
        "scope": "NORMAL_PASS_SLICE_UNFROZEN_V0",
        "seed": seed,
        "settlementReasonCounts": settlement_reason_counts,
        "sha256": transcript_digest.hexdigest(),
        "thresholdBoardSizes": sorted(threshold_board_sizes),
        "unsupported": unsupported,
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the test-only UNFROZEN v0 NORMAL/PASS differential rehearsal. "
            "This is not semantic-projection-v1 or GATE-RULE-1M."
        )
    )
    parser.add_argument(
        "--probe",
        type=Path,
        required=True,
        help=(
            "explicit path to the standalone mutago-collapse-slice-probe executable; "
            "multi-config builds may place it below a configuration directory"
        ),
    )
    parser.add_argument(
        "--seed",
        default=DEFAULT_SEED,
        help="deterministic seed string for the SHA-256 counter corpus",
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=DEFAULT_CANDIDATE_COUNT,
        help=(
            "number of zero-quota random-corpus candidates; must be in "
            f"{MIN_RANDOM_CANDIDATE_COUNT}..{MAX_RANDOM_CANDIDATE_COUNT}"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = run_differential(
            args.probe,
            seed=args.seed,
            candidate_count=args.candidate_count,
        )
    except (ProtocolError, ProbeError, DifferentialMismatch, ValueError) as exc:
        failure_manifest = {
            "candidateCount": args.candidate_count,
            "generatorVersion": GENERATOR_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "seed": args.seed,
        }
        print(
            "normal-pass differential rehearsal failed: "
            f"{exc}; invocation={canonical_json(failure_manifest)}",
            file=sys.stderr,
        )
        return 1
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
