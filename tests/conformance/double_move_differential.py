#!/usr/bin/env python3
"""Bounded test-only Double Increment 1 C++/Python differential carrier.

This explicitly UNFROZEN carrier is not a production protocol, is not the
``semantic-projection-v1`` wire format, and is not evidence for GATE-RULE-1M.
It independently executes the C++ reducer probe and the stdlib-only Python
oracle, then compares a closed normalized projection without sharing rule
transition code.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = (REPO_ROOT / "python").resolve()
FIXTURE_PATH = (
    REPO_ROOT
    / "tests"
    / "contracts"
    / "examples"
    / "conformance-fixture-double-settlement-v1.example.json"
)
while str(PYTHON_ROOT) in sys.path:
    sys.path.remove(str(PYTHON_ROOT))
sys.path.insert(0, str(PYTHON_ROOT))
while str(REPO_ROOT) in sys.path:
    sys.path.remove(str(REPO_ROOT))
sys.path.insert(1, str(REPO_ROOT))


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
    SpecialQuotas,
    UnsupportedSliceAction,
    apply_action,
    decode_action_v1,
    new_game,
    scan_n4_groups,
)

from tools.contract.contract import (  # noqa: E402
    DESCRIPTOR_PATH,
    ContractError,
    SchemaCatalog,
    _validate_fixture,
    load_json,
    parse_json_bytes,
    validate_descriptor,
)
import tools.contract.contract as _contract_module  # noqa: E402

_contract_path = Path(_contract_module.__file__).resolve()
try:
    _contract_path.relative_to(REPO_ROOT)
except ValueError as exc:
    raise ImportError(
        f"tools.contract.contract resolved outside this checkout: {_contract_path}"
    ) from exc

for _module_name in (
    "mutago",
    "mutago.collapse_go",
    "mutago.collapse_go.normal_pass_oracle",
):
    _require_repository_oracle_module(_module_name)
del _module_name

PROTOCOL_VERSION = "double-move-diff-v1-unfrozen"
GENERATOR_VERSION = "sha256-counter-double-v1-unfrozen"
DEFAULT_SEED = "mutago-double-increment-1"
DEFAULT_CANDIDATE_COUNT = 512
MIN_RANDOM_CANDIDATE_COUNT = 64
MAX_RANDOM_CANDIDATE_COUNT = 4096
MAX_EPISODE_STEPS = 160
MAX_TEST_QUOTA = 4
MAX_REQUEST_FRAME_BYTES = 1024 * 1024
MAX_RESPONSE_FRAME_BYTES = 32 * 1024 * 1024
MAX_PROBE_STDOUT_BYTES = 256 * 1024 * 1024
MAX_PROBE_STDERR_BYTES = 1024 * 1024
PROBE_TIMEOUT_SECONDS = 180
PROCESS_CLEANUP_RESERVE_SECONDS = 0.25
SAFE_INTEGER_MIN = -9_007_199_254_740_991
SAFE_INTEGER_MAX = 9_007_199_254_740_991
INVERSE_SYMMETRY_IDS = (0, 1, 2, 3, 4, 6, 5, 7)
POINT_KINDS = (
    ActionKind.NORMAL,
    ActionKind.IMMORTAL,
    ActionKind.DOUBLE_START,
    ActionKind.EIGHTWAY,
)
KIND_CODE = {kind: index for index, kind in enumerate(POINT_KINDS)}
SPECIAL_KINDS = frozenset(POINT_KINDS[1:])

REQUEST_FIELDS = frozenset(
    ("protocolVersion", "episodeId", "boardSize", "initialQuotas", "steps")
)
STEP_FIELDS = frozenset(("candidateActor", "action"))
RESPONSE_FIELDS = frozenset(
    ("protocolVersion", "episodeId", "initialState", "observations")
)
OBSERVATION_FIELDS = frozenset(("stepIndex", "transition", "state"))
STATE_FIELDS = frozenset(
    (
        "actor",
        "atomicActionCount",
        "boardSize",
        "consecutivePasses",
        "expiredQuotas",
        "groups",
        "initialQuotas",
        "ledger",
        "logPosition",
        "occupancy",
        "pendingDouble",
        "phase",
        "pskHistory",
        "remainingQuotas",
        "revision",
        "settledLedgerCount",
        "settlementCompleted",
        "stableTerminalEventCount",
        "stones",
        "terminal",
        "threshold",
        "usedQuotas",
    )
)
TRANSITION_FIELDS = frozenset(
    (
        "accepted",
        "action",
        "atomicEvent",
        "candidateActor",
        "errorCode",
        "positionalSuperkoAppends",
        "settlement",
        "status",
        "terminalEvent",
        "transitionKind",
    )
)
ATOMIC_EVENT_FIELDS = frozenset(
    (
        "action",
        "actionNumber",
        "actor",
        "captured",
        "eventId",
        "pskHistoryIndex",
        "stableOccupancy",
    )
)
SETTLEMENT_FIELDS = frozenset(("handoffActor", "steps", "triggerReason"))
SETTLEMENT_STEP_FIELDS = frozenset(
    (
        "abilityDeactivated",
        "ledgerEventId",
        "noOp",
        "pskHistoryIndex",
        "removalBatches",
        "stableOccupancy",
        "stepIndex",
    )
)
TERMINAL_EVENT_FIELDS = frozenset(
    (
        "eventId",
        "loser",
        "pskHistoryIndex",
        "reason",
        "stableOccupancy",
        "winner",
    )
)
OCCUPANCY_FIELDS = frozenset(("black", "white"))
PLAYER_QUOTA_FIELDS = frozenset(("BLACK", "WHITE"))
QUOTA_VECTOR_FIELDS = frozenset(("IMMORTAL", "DOUBLE_START", "EIGHTWAY"))
STONE_FIELDS = frozenset(
    (
        "color",
        "originActionNumber",
        "originKind",
        "point",
        "sourceId",
        "specialEventId",
    )
)
LEDGER_FIELDS = frozenset(
    (
        "abilityState",
        "eventId",
        "kind",
        "logicalOrder",
        "originActionNumber",
        "owner",
        "settlementState",
        "sourcePoint",
        "sourceStoneId",
        "stoneState",
        "tombstone",
    )
)
PENDING_FIELDS = frozenset(("eventId", "owner", "startActionNumber"))
GROUP_FIELDS = frozenset(
    (
        "color",
        "eightwayAnchors",
        "immortalAnchors",
        "liberties",
        "protected",
        "stones",
    )
)
TERMINAL_OPEN_FIELDS = frozenset(("ended",))
TERMINAL_SCORED_FIELDS = frozenset(
    ("ended", "reason", "winner", "loser", "score")
)
SCORE_FIELDS = frozenset(("black", "white", "margin"))
RATIONAL_FIELDS = frozenset(("numerator", "denominator"))
SUPPORTED_REJECTION_CODES = frozenset(
    (
        "WRONG_ACTOR",
        "INVALID_PHASE",
        "TERMINAL_STATE",
        "POINT_OFF_BOARD",
        "POINT_OCCUPIED",
        "QUOTA_EXHAUSTED",
        "DOUBLE_CONTINUATION_REQUIRED",
        "DOUBLE_CONTINUATION_KIND_FORBIDDEN",
        "DOUBLE_THRESHOLD",
        "SUICIDE",
        "POSITIONAL_SUPERKO",
        "INTERNAL_INVARIANT",
    )
)
PINNED_FIXTURE_LEGAL_ACTION_RANGES = (
    ((0, 1444),),
    ((0, 179), (181, 360), (1444, 1444)),
    ((0, 179), (181, 540), (542, 901), (903, 1262), (1264, 1444)),
    ((0, 179), (181, 360), (1444, 1444)),
)


class ProtocolError(ValueError):
    """A request or response violates the test-only carrier contract."""


class ProbeError(RuntimeError):
    """The standalone probe failed or violated process limits."""


class ProbeOutputDecodeError(ProbeError):
    """Probe bytes were not UTF-8; retain a response index for diagnostics."""

    def __init__(self, stream_name: str, byte_offset: int, response_index: int) -> None:
        self.stream_name = stream_name
        self.byte_offset = byte_offset
        self.response_index = response_index
        super().__init__(
            f"probe {stream_name} is not UTF-8 at byte {byte_offset}"
        )


class DifferentialMismatch(AssertionError):
    """The first exact C++/Python normalized projection mismatch."""


def _new_deadline(seconds: float = PROBE_TIMEOUT_SECONDS) -> float:
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds <= 0
    ):
        raise ValueError("deadline seconds must be a finite positive number")
    return time.monotonic() + seconds


def _remaining_budget(deadline: float | None, phase: str) -> float:
    if deadline is None:
        return PROBE_TIMEOUT_SECONDS
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProbeError(
            f"complete-corpus deadline exceeded during {phase}"
        )
    return remaining


def _check_deadline(deadline: float | None, phase: str) -> None:
    if deadline is not None:
        _remaining_budget(deadline, phase)


class Sha256CounterRng:
    """Deterministic SHA-256 counter byte stream with a versioned domain."""

    _DOMAIN = b"MutaGo Double Increment 1 differential v1 unfrozen\x00"

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
        self._buffer.extend(
            hashlib.sha256(
                self._DOMAIN
                + len(self._seed).to_bytes(8, "big")
                + self._seed
                + self._counter.to_bytes(16, "big")
            ).digest()
        )
        self._counter += 1

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
            raise ValueError("upper must be a positive integer")
        byte_count = max(1, (upper.bit_length() + 7) // 8)
        ceiling = 1 << (8 * byte_count)
        limit = ceiling - ceiling % upper
        while True:
            value = int.from_bytes(self.bytes(byte_count), "big")
            if value < limit:
                return value % upper

    def choice(self, values: Sequence[object]):
        if not values:
            raise ValueError("cannot choose from an empty sequence")
        return values[self.randbelow(len(values))]


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


def _valid_episode_id(value: object) -> bool:
    return type(value) is str and 1 <= len(value) <= 128 and all(
        character.isascii()
        and (character.isalnum() or character in "._-")
        for character in value
    )


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


def action_kind_for_id(action_id: int) -> ActionKind:
    if type(action_id) is not int or not 0 <= action_id <= PASS_ACTION_ID:
        raise ValueError("action_id must be an integer in 0..1444")
    if action_id == PASS_ACTION_ID:
        return ActionKind.PASS
    return POINT_KINDS[action_id // 361]


def action_v1(action_id: int) -> dict[str, object]:
    return {
        "schemaVersion": "action-v1",
        "actionId": action_id,
        "kind": action_kind_for_id(action_id).value,
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
        raise ValueError("point action requires a point kind")
    if type(x) is not int or type(y) is not int or not (
        0 <= x < board_size and 0 <= y < board_size
    ):
        raise ValueError("board-local point is outside the selected board")
    offset = (19 - board_size) // 2
    canvas_x = x + offset
    canvas_y = y + offset
    return action_v1(361 * KIND_CODE[kind] + 19 * canvas_y + canvas_x)


def quotas(
    *,
    black_double: int = 1,
    white_double: int = 1,
    immortal: int = 1,
    eightway: int = 1,
) -> dict[str, object]:
    return {
        "BLACK": {
            "IMMORTAL": immortal,
            "DOUBLE_START": black_double,
            "EIGHTWAY": eightway,
        },
        "WHITE": {
            "IMMORTAL": immortal,
            "DOUBLE_START": white_double,
            "EIGHTWAY": eightway,
        },
    }


def _validate_quota_vector(value: object, context: str) -> Mapping[str, object]:
    vector = _require_exact_fields(value, QUOTA_VECTOR_FIELDS, context)
    for ability in sorted(QUOTA_VECTOR_FIELDS):
        _require_int(
            vector[ability],
            f"{context}.{ability}",
            maximum=MAX_TEST_QUOTA,
        )
    return vector


def _validate_player_quotas(value: object, context: str) -> Mapping[str, object]:
    players = _require_exact_fields(value, PLAYER_QUOTA_FIELDS, context)
    for color in ("BLACK", "WHITE"):
        _validate_quota_vector(players[color], f"{context}.{color}")
    return players


def validate_episode_request(request: object) -> Mapping[str, object]:
    frame = _require_exact_fields(request, REQUEST_FIELDS, "episode request")
    if frame["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError(f"protocolVersion must be {PROTOCOL_VERSION}")
    if not _valid_episode_id(frame["episodeId"]):
        raise ProtocolError("episodeId has an invalid test identifier")
    board_size = frame["boardSize"]
    if type(board_size) is not int or board_size not in (9, 13, 19):
        raise ProtocolError("boardSize must be exactly 9, 13, or 19")
    _validate_player_quotas(frame["initialQuotas"], "initialQuotas")
    steps = frame["steps"]
    if type(steps) is not list or not 1 <= len(steps) <= MAX_EPISODE_STEPS:
        raise ProtocolError("steps must be a nonempty array within the resource limit")
    for index, step_value in enumerate(steps):
        step = _require_exact_fields(step_value, STEP_FIELDS, f"step {index}")
        if step["candidateActor"] not in ("BLACK", "WHITE"):
            raise ProtocolError(f"step {index} candidateActor must be BLACK or WHITE")
        try:
            decode_action_v1(step["action"], board_size)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"step {index} has invalid Action V1: {exc}") from exc
    if len(canonical_json(frame).encode("utf-8")) > MAX_REQUEST_FRAME_BYTES:
        raise ProtocolError("canonical request exceeds the 1 MiB request limit")
    return frame


def _oracle_config(initial_quotas: Mapping[str, object], board_size: int) -> OracleConfig:
    def vector(color: str) -> SpecialQuotas:
        source = initial_quotas[color]
        return SpecialQuotas(
            immortal=source["IMMORTAL"],
            double_start=source["DOUBLE_START"],
            eightway=source["EIGHTWAY"],
        )

    return OracleConfig(
        board_size=board_size,
        quotas=PlayerQuotas(black=vector("BLACK"), white=vector("WHITE")),
    )


def _occupancy_projection(occupancy) -> dict[str, object]:
    return {"black": list(occupancy.black), "white": list(occupancy.white)}


def _quota_projection(player_quotas: PlayerQuotas) -> dict[str, object]:
    def vector(value: SpecialQuotas) -> dict[str, object]:
        return {
            "IMMORTAL": value.immortal,
            "DOUBLE_START": value.double_start,
            "EIGHTWAY": value.eightway,
        }

    return {"BLACK": vector(player_quotas.black), "WHITE": vector(player_quotas.white)}


def _stone_projection(stone) -> dict[str, object]:
    return {
        "point": stone.point,
        "color": stone.color.value,
        "sourceId": stone.source_id,
        "originKind": stone.origin_kind.value,
        "specialEventId": stone.special_event_id,
        "originActionNumber": stone.origin_action_number,
    }


def _ledger_projection(event) -> dict[str, object]:
    return {
        "eventId": event.event_id,
        "logicalOrder": event.logical_order,
        "originActionNumber": event.origin_action_number,
        "owner": event.owner.value,
        "kind": event.kind.value,
        "sourcePoint": event.source_point,
        "sourceStoneId": event.source_stone_id,
        "abilityState": event.ability_state.value,
        "stoneState": event.stone_state.value,
        "settlementState": event.settlement_state.value,
        "tombstone": event.tombstone,
    }


def _groups_projection(state: OracleState) -> list[dict[str, object]]:
    return [
        {
            "color": group.color.value,
            "stones": list(group.stones),
            "liberties": list(group.liberties),
            "protected": group.protected,
            "immortalAnchors": list(group.immortal_anchor_points),
            "eightwayAnchors": list(group.eightway_anchor_points),
        }
        for group in scan_n4_groups(state.board)
    ]


def _score_projection(score) -> dict[str, object]:
    return {
        "black": {"numerator": score.black_score_numerator, "denominator": 2},
        "white": {"numerator": score.white_score_numerator, "denominator": 2},
        "margin": {"numerator": score.margin_numerator, "denominator": 2},
    }


def state_projection(state: OracleState) -> dict[str, object]:
    pending = None
    if state.pending_double is not None:
        pending = {
            "owner": state.pending_double.owner.value,
            "eventId": state.pending_double.event_id,
            "startActionNumber": state.pending_double.start_action_number,
        }
    terminal: dict[str, object]
    if state.terminal is None:
        terminal = {"ended": False}
    else:
        terminal = {
            "ended": True,
            "reason": state.terminal.reason.value,
            "winner": state.terminal.winner.value,
            "loser": state.terminal.loser.value,
            "score": _score_projection(state.terminal.score),
        }
    return {
        "revision": state.revision,
        "logPosition": state.log_position,
        "boardSize": state.config.board_size,
        "threshold": state.threshold,
        "occupancy": _occupancy_projection(state.occupancy),
        "stones": [_stone_projection(stone) for stone in state.stones],
        "groups": _groups_projection(state),
        "actor": state.actor.value if state.actor is not None else None,
        "phase": state.phase.value,
        "atomicActionCount": state.atomic_action_count,
        "consecutivePasses": state.consecutive_passes,
        "settlementCompleted": state.settlement_completed,
        "pendingDouble": pending,
        "initialQuotas": _quota_projection(state.initial_quotas),
        "remainingQuotas": _quota_projection(state.remaining_quotas),
        "usedQuotas": _quota_projection(state.used_quotas),
        "expiredQuotas": _quota_projection(state.expired_quotas),
        "ledger": [_ledger_projection(event) for event in state.ledger],
        "settledLedgerCount": state.settled_ledger_count,
        "stableTerminalEventCount": state.stable_terminal_event_count,
        "pskHistory": [_occupancy_projection(entry) for entry in state.psk_history],
        "terminal": terminal,
    }


def _atomic_event_projection(event, action: Mapping[str, object]) -> dict[str, object]:
    return {
        "eventId": f"action-{event.action_number}",
        "actionNumber": event.action_number,
        "actor": event.actor.value,
        "action": dict(action),
        "captured": _occupancy_projection(event.captured),
        "stableOccupancy": _occupancy_projection(event.stable_occupancy),
        "pskHistoryIndex": event.psk_history_index,
    }


def _settlement_projection(settlement, handoff_actor: Color) -> dict[str, object]:
    return {
        "triggerReason": settlement.reason.value,
        "handoffActor": handoff_actor.value,
        "steps": [
            {
                "stepIndex": index,
                "ledgerEventId": step.event_id,
                "abilityDeactivated": step.ability_deactivated,
                "noOp": step.no_op,
                "removalBatches": [],
                "stableOccupancy": _occupancy_projection(step.stable_occupancy),
                "pskHistoryIndex": step.psk_history_index,
            }
            for index, step in enumerate(settlement.steps)
        ],
    }


def _terminal_event_projection(event) -> dict[str, object]:
    return {
        "eventId": f"terminal-{event.log_position}",
        "reason": event.reason.value,
        "winner": event.winner.value,
        "loser": event.loser.value,
        "stableOccupancy": _occupancy_projection(event.stable_occupancy),
        "pskHistoryIndex": event.psk_history_index,
    }


def transition_projection(
    previous: OracleState,
    candidate_actor: Color,
    action: Mapping[str, object],
    transition,
    *,
    unsupported: bool = False,
) -> dict[str, object]:
    if unsupported:
        return {
            "accepted": False,
            "status": "UNSUPPORTED",
            "transitionKind": "UNSUPPORTED",
            "errorCode": "UNSUPPORTED_BY_SLICE",
            "candidateActor": candidate_actor.value,
            "action": dict(action),
            "atomicEvent": None,
            "settlement": None,
            "terminalEvent": None,
            "positionalSuperkoAppends": 0,
        }
    if not transition.accepted:
        return {
            "accepted": False,
            "status": "REJECTED",
            "transitionKind": "REJECTED",
            "errorCode": transition.rejection_code.value,
            "candidateActor": candidate_actor.value,
            "action": dict(action),
            "atomicEvent": None,
            "settlement": None,
            "terminalEvent": None,
            "positionalSuperkoAppends": 0,
        }
    return {
        "accepted": True,
        "status": "ACCEPTED",
        "transitionKind": "ATOMIC_ACTION",
        "errorCode": None,
        "candidateActor": candidate_actor.value,
        "action": dict(action),
        "atomicEvent": _atomic_event_projection(transition.atomic_event, action),
        "settlement": (
            _settlement_projection(transition.settlement, transition.state.actor)
            if transition.settlement is not None
            else None
        ),
        "terminalEvent": (
            _terminal_event_projection(transition.terminal_event)
            if transition.terminal_event is not None
            else None
        ),
        "positionalSuperkoAppends": (
            len(transition.state.psk_history) - len(previous.psk_history)
        ),
    }


def _apply_v1_adapter(
    state: OracleState,
    actor: Color,
    action: Mapping[str, object],
):
    """Keep Increment 1 mechanically closed when the shared oracle grows."""

    try:
        transition = apply_action(state, actor, action)
    except UnsupportedSliceAction:
        return None
    kind = decode_action_v1(action, state.config.board_size).kind
    armed_mechanics_reached = kind in (
        ActionKind.IMMORTAL,
        ActionKind.EIGHTWAY,
    ) and (
        transition.accepted
        or (
            transition.rejection_code is not None
            and transition.rejection_code.value in ("SUICIDE", "POSITIONAL_SUPERKO")
        )
    )
    if armed_mechanics_reached:
        return None
    return transition


def oracle_episode_response(
    request: object, *, deadline: float | None = None
) -> dict[str, object]:
    _check_deadline(deadline, "Python oracle request validation")
    frame = validate_episode_request(request)
    _check_deadline(deadline, "Python oracle initialization")
    state = new_game(_oracle_config(frame["initialQuotas"], frame["boardSize"]))
    initial = state_projection(state)
    observations: list[dict[str, object]] = []
    for step_index, step in enumerate(frame["steps"], start=1):
        _check_deadline(deadline, "Python oracle execution")
        previous = state
        actor = Color(step["candidateActor"])
        transition = _apply_v1_adapter(state, actor, step["action"])
        if transition is None:
            projected_transition = transition_projection(
                previous, actor, step["action"], None, unsupported=True
            )
        else:
            state = transition.state
            projected_transition = transition_projection(
                previous, actor, step["action"], transition
            )
        observations.append(
            {
                "stepIndex": step_index,
                "transition": projected_transition,
                "state": state_projection(state),
            }
        )
    _check_deadline(deadline, "Python oracle projection")
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "episodeId": frame["episodeId"],
        "initialState": initial,
        "observations": observations,
    }


def oracle_episode_transitions(
    request: object, *, deadline: float | None = None
) -> tuple[object | None, ...]:
    _check_deadline(deadline, "deterministic action re-execution validation")
    frame = validate_episode_request(request)
    state = new_game(_oracle_config(frame["initialQuotas"], frame["boardSize"]))
    transitions: list[object | None] = []
    for step in frame["steps"]:
        _check_deadline(deadline, "deterministic action re-execution")
        actor = Color(step["candidateActor"])
        transition = _apply_v1_adapter(state, actor, step["action"])
        if transition is None:
            transitions.append(None)
        else:
            transitions.append(transition)
            state = transition.state
    _check_deadline(deadline, "deterministic action re-execution projection")
    return tuple(transitions)


def _validate_point_list(value: object, context: str, point_count: int) -> tuple[int, ...]:
    if type(value) is not list:
        raise ProtocolError(f"{context} must be an array")
    result: list[int] = []
    previous = -1
    for index, point in enumerate(value):
        parsed = _require_int(
            point, f"{context}[{index}]", maximum=point_count - 1
        )
        if parsed <= previous:
            raise ProtocolError(f"{context} must be strictly increasing")
        result.append(parsed)
        previous = parsed
    return tuple(result)


def _validate_occupancy(value: object, context: str, point_count: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    occupancy = _require_exact_fields(value, OCCUPANCY_FIELDS, context)
    black = _validate_point_list(occupancy["black"], f"{context}.black", point_count)
    white = _validate_point_list(occupancy["white"], f"{context}.white", point_count)
    if set(black).intersection(white):
        raise ProtocolError(f"{context} colors overlap")
    return black, white


def _validate_rational(value: object, context: str) -> int:
    rational = _require_exact_fields(value, RATIONAL_FIELDS, context)
    if rational["denominator"] != 2 or type(rational["denominator"]) is not int:
        raise ProtocolError(f"{context}.denominator must be integer 2")
    return _require_int(rational["numerator"], f"{context}.numerator")


def _validate_terminal_state(
    value: object, context: str, phase: str
) -> Mapping[str, object]:
    if type(value) is not dict or type(value.get("ended")) is not bool:
        raise ProtocolError(f"{context} is invalid")
    if not value["ended"]:
        terminal = _require_exact_fields(value, TERMINAL_OPEN_FIELDS, context)
        if phase == "TERMINAL":
            raise ProtocolError(f"{context} disagrees with terminal phase")
        return terminal

    terminal = _require_exact_fields(value, TERMINAL_SCORED_FIELDS, context)
    if phase != "TERMINAL" or terminal["reason"] != "SCORE":
        raise ProtocolError(f"{context} scored terminal phase or reason differs")
    winner = terminal["winner"]
    loser = terminal["loser"]
    if winner not in ("BLACK", "WHITE") or loser not in ("BLACK", "WHITE") or winner == loser:
        raise ProtocolError(f"{context} winner/loser are invalid")
    score = _require_exact_fields(terminal["score"], SCORE_FIELDS, f"{context}.score")
    black_numerator = _validate_rational(score["black"], f"{context}.score.black")
    white_numerator = _validate_rational(score["white"], f"{context}.score.white")
    margin_numerator = _validate_rational(score["margin"], f"{context}.score.margin")
    if margin_numerator != abs(black_numerator - white_numerator):
        raise ProtocolError(f"{context}.score margin formula differs")
    expected_winner = "BLACK" if black_numerator > white_numerator else "WHITE"
    expected_loser = "WHITE" if expected_winner == "BLACK" else "BLACK"
    if winner != expected_winner or loser != expected_loser:
        raise ProtocolError(f"{context} winner/loser disagree with score")
    if black_numerator % 2 != 0 or white_numerator % 2 != 1 or margin_numerator % 2 != 1:
        raise ProtocolError(f"{context}.score parity disagrees with 7.5 komi")
    return terminal


def _scan_projected_n4_groups(
    occupancy: tuple[tuple[int, ...], tuple[int, ...]], board_size: int
) -> list[tuple[str, tuple[int, ...], tuple[int, ...]]]:
    black = set(occupancy[0])
    white = set(occupancy[1])
    occupied = black | white
    visited: set[int] = set()
    groups: list[tuple[str, tuple[int, ...], tuple[int, ...]]] = []
    for start in range(board_size * board_size):
        if start in visited or start not in occupied:
            continue
        color = "BLACK" if start in black else "WHITE"
        own = black if color == "BLACK" else white
        stones: set[int] = set()
        liberties: set[int] = set()
        stack = [start]
        visited.add(start)
        while stack:
            point = stack.pop()
            stones.add(point)
            x = point % board_size
            y = point // board_size
            neighbors = []
            if y > 0:
                neighbors.append(point - board_size)
            if x > 0:
                neighbors.append(point - 1)
            if x + 1 < board_size:
                neighbors.append(point + 1)
            if y + 1 < board_size:
                neighbors.append(point + board_size)
            for neighbor in neighbors:
                if neighbor in own:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
                elif neighbor not in occupied:
                    liberties.add(neighbor)
        groups.append((color, tuple(sorted(stones)), tuple(sorted(liberties))))
    return groups


def _validate_state(
    value: object,
    context: str,
    board_size: int,
    configured_quotas: Mapping[str, object],
) -> Mapping[str, object]:
    state = _require_exact_fields(value, STATE_FIELDS, context)
    if state["boardSize"] != board_size or type(state["boardSize"]) is not int:
        raise ProtocolError(f"{context}.boardSize differs from request")
    threshold = {9: 34, 13: 70, 19: 150}[board_size]
    if state["threshold"] != threshold or type(state["threshold"]) is not int:
        raise ProtocolError(f"{context}.threshold differs from frozen formula")
    for field in (
        "revision",
        "logPosition",
        "atomicActionCount",
        "settledLedgerCount",
        "stableTerminalEventCount",
    ):
        _require_int(state[field], f"{context}.{field}")
    _require_int(state["consecutivePasses"], f"{context}.consecutivePasses", maximum=2)
    if type(state["settlementCompleted"]) is not bool:
        raise ProtocolError(f"{context}.settlementCompleted must be bool")

    point_count = board_size * board_size
    occupancy = _validate_occupancy(state["occupancy"], f"{context}.occupancy", point_count)
    history = state["pskHistory"]
    if type(history) is not list or not history:
        raise ProtocolError(f"{context}.pskHistory must be nonempty")
    projected_history = [
        _validate_occupancy(item, f"{context}.pskHistory[{index}]", point_count)
        for index, item in enumerate(history)
    ]
    if projected_history[0] != ((), ()):
        raise ProtocolError(f"{context}.pskHistory entry zero must be empty")
    if projected_history[-1] != occupancy:
        raise ProtocolError(f"{context}.pskHistory must end at current occupancy")

    for bucket in (
        "initialQuotas",
        "remainingQuotas",
        "usedQuotas",
        "expiredQuotas",
    ):
        _validate_player_quotas(state[bucket], f"{context}.{bucket}")
    if state["initialQuotas"] != configured_quotas:
        raise ProtocolError(f"{context}.initialQuotas differ from request")
    for color in ("BLACK", "WHITE"):
        for ability in QUOTA_VECTOR_FIELDS:
            total = (
                state["remainingQuotas"][color][ability]
                + state["usedQuotas"][color][ability]
                + state["expiredQuotas"][color][ability]
            )
            if total != state["initialQuotas"][color][ability]:
                raise ProtocolError(f"{context} quota conservation failed")

    phase = state["phase"]
    actor = state["actor"]
    if phase not in ("COLLAPSE_PLAY", "ORDINARY_PLAY", "TERMINAL"):
        raise ProtocolError(f"{context}.phase is unknown")
    if phase == "TERMINAL":
        if actor is not None:
            raise ProtocolError(f"{context}.actor must be null in terminal state")
    elif actor not in ("BLACK", "WHITE"):
        raise ProtocolError(f"{context}.actor must be a player")
    if state["settlementCompleted"] != (phase != "COLLAPSE_PLAY"):
        raise ProtocolError(f"{context}.settlementCompleted disagrees with phase")
    for color in ("BLACK", "WHITE"):
        for ability in QUOTA_VECTOR_FIELDS:
            initial_value = state["initialQuotas"][color][ability]
            used_value = state["usedQuotas"][color][ability]
            remaining_value = state["remainingQuotas"][color][ability]
            expired_value = state["expiredQuotas"][color][ability]
            if phase == "COLLAPSE_PLAY":
                if expired_value != 0 or remaining_value != initial_value - used_value:
                    raise ProtocolError(f"{context} pre-settlement quota lifecycle differs")
            elif remaining_value != 0 or expired_value != initial_value - used_value:
                raise ProtocolError(f"{context} post-settlement quota lifecycle differs")

    stones = state["stones"]
    if type(stones) is not list:
        raise ProtocolError(f"{context}.stones must be an array")
    stone_points: list[int] = []
    source_ids: set[str] = set()
    stones_by_source: dict[str, Mapping[str, object]] = {}
    for index, item in enumerate(stones):
        stone = _require_exact_fields(item, STONE_FIELDS, f"{context}.stones[{index}]")
        point = _require_int(
            stone["point"], f"{context}.stones[{index}].point", maximum=point_count - 1
        )
        if stone_points and point <= stone_points[-1]:
            raise ProtocolError(f"{context}.stones must be ordered by point")
        stone_points.append(point)
        action_number = _require_int(
            stone["originActionNumber"],
            f"{context}.stones[{index}].originActionNumber",
            minimum=1,
        )
        expected_source = f"stone-{action_number}"
        if stone["sourceId"] != expected_source or expected_source in source_ids:
            raise ProtocolError(f"{context}.stones source identity is inconsistent")
        source_ids.add(expected_source)
        stones_by_source[expected_source] = stone
        if stone["color"] not in ("BLACK", "WHITE"):
            raise ProtocolError(f"{context}.stones color is invalid")
        if stone["originKind"] not in ("NORMAL", "DOUBLE_START"):
            raise ProtocolError(f"{context}.stones origin kind is outside Increment 1")
        expected_special = (
            f"special-{action_number}"
            if stone["originKind"] == "DOUBLE_START"
            else None
        )
        if stone["specialEventId"] != expected_special:
            raise ProtocolError(f"{context}.stones special linkage is inconsistent")
    if tuple(stone_points) != tuple(sorted((*occupancy[0], *occupancy[1]))):
        raise ProtocolError(f"{context}.stones do not exactly cover occupancy")

    ledger = state["ledger"]
    if type(ledger) is not list:
        raise ProtocolError(f"{context}.ledger must be an array")
    previous_order = -1
    ledger_ids: list[str] = []
    used_double_counts = {"BLACK": 0, "WHITE": 0}
    settled_entry_count = 0
    for index, item in enumerate(ledger):
        entry = _require_exact_fields(item, LEDGER_FIELDS, f"{context}.ledger[{index}]")
        order = _require_int(entry["logicalOrder"], f"{context}.ledger[{index}].logicalOrder")
        action_number = _require_int(
            entry["originActionNumber"],
            f"{context}.ledger[{index}].originActionNumber",
            minimum=1,
        )
        if order != action_number - 1 or order <= previous_order:
            raise ProtocolError(f"{context}.ledger order is inconsistent")
        if previous_order >= 0 and order - previous_order < 2:
            raise ProtocolError(f"{context}.ledger Double starts lack continuations")
        previous_order = order
        event_id = f"special-{action_number}"
        source_id = f"stone-{action_number}"
        if entry["eventId"] != event_id or entry["sourceStoneId"] != source_id:
            raise ProtocolError(f"{context}.ledger identity is inconsistent")
        if entry["kind"] != "DOUBLE_START" or type(entry["tombstone"]) is not bool or not entry["tombstone"]:
            raise ProtocolError(f"{context}.ledger must contain Double tombstones")
        owner = entry["owner"]
        if owner not in ("BLACK", "WHITE"):
            raise ProtocolError(f"{context}.ledger owner is invalid")
        source_point = _require_int(
            entry["sourcePoint"],
            f"{context}.ledger[{index}].sourcePoint",
            maximum=point_count - 1,
        )
        expected_ability = "CONSUMED" if phase == "COLLAPSE_PLAY" else "INACTIVE"
        expected_settlement = "PENDING" if phase == "COLLAPSE_PLAY" else "SETTLED"
        if entry["abilityState"] != expected_ability:
            raise ProtocolError(f"{context}.ledger ability lifecycle differs from phase")
        if entry["stoneState"] not in ("ON_BOARD", "CAPTURED"):
            raise ProtocolError(f"{context}.ledger stone state is invalid")
        if entry["settlementState"] != expected_settlement:
            raise ProtocolError(f"{context}.ledger settlement lifecycle differs from phase")
        if entry["settlementState"] == "SETTLED":
            settled_entry_count += 1

        source = stones_by_source.get(source_id)
        if entry["stoneState"] == "ON_BOARD":
            if source is None or (
                source["point"] != source_point
                or source["color"] != owner
                or source["originKind"] != "DOUBLE_START"
                or source["specialEventId"] != event_id
            ):
                raise ProtocolError(f"{context}.ledger on-board source linkage differs")
        elif source is not None:
            raise ProtocolError(f"{context}.ledger captured source remains on board")

        if action_number >= len(projected_history):
            raise ProtocolError(f"{context}.ledger source action is absent from PSK")
        before_points = set(
            projected_history[action_number - 1][0]
            + projected_history[action_number - 1][1]
        )
        owner_points = (
            projected_history[action_number][0]
            if owner == "BLACK"
            else projected_history[action_number][1]
        )
        if source_point in before_points or source_point not in owner_points:
            raise ProtocolError(f"{context}.ledger source provenance differs from PSK")
        used_double_counts[owner] += 1
        ledger_ids.append(event_id)

    if state["settledLedgerCount"] != settled_entry_count:
        raise ProtocolError(f"{context}.settledLedgerCount differs from ledger lifecycle")
    for color in ("BLACK", "WHITE"):
        if state["usedQuotas"][color]["DOUBLE_START"] != used_double_counts[color]:
            raise ProtocolError(f"{context}.used Double quotas differ from ledger")
        if state["usedQuotas"][color]["IMMORTAL"] != 0 or state["usedQuotas"][color]["EIGHTWAY"] != 0:
            raise ProtocolError(f"{context}.unimplemented ability used quota is nonzero")

    pending = state["pendingDouble"]
    if pending is not None:
        pending_value = _require_exact_fields(pending, PENDING_FIELDS, f"{context}.pendingDouble")
        start = _require_int(
            pending_value["startActionNumber"],
            f"{context}.pendingDouble.startActionNumber",
            minimum=1,
        )
        if pending_value["eventId"] != f"special-{start}":
            raise ProtocolError(f"{context}.pendingDouble linkage is inconsistent")
        if (
            phase != "COLLAPSE_PLAY"
            or pending_value["owner"] != actor
            or not ledger_ids
            or pending_value["eventId"] != ledger_ids[-1]
            or start != state["atomicActionCount"]
            or state["consecutivePasses"] != 0
        ):
            raise ProtocolError(f"{context}.pendingDouble control state is inconsistent")
    elif ledger and ledger[-1]["originActionNumber"] >= state["atomicActionCount"]:
        raise ProtocolError(f"{context}.latest Double start lacks its continuation")

    groups = state["groups"]
    if type(groups) is not list:
        raise ProtocolError(f"{context}.groups must be an array")
    covered: list[int] = []
    projected_groups: list[tuple[str, tuple[int, ...], tuple[int, ...]]] = []
    for index, item in enumerate(groups):
        group = _require_exact_fields(item, GROUP_FIELDS, f"{context}.groups[{index}]")
        group_stones = _validate_point_list(
            group["stones"], f"{context}.groups[{index}].stones", point_count
        )
        group_liberties = _validate_point_list(
            group["liberties"], f"{context}.groups[{index}].liberties", point_count
        )
        if group["color"] not in ("BLACK", "WHITE"):
            raise ProtocolError(f"{context}.groups color is invalid")
        if group["protected"] is not False:
            raise ProtocolError(f"{context}.groups cannot be protected in Increment 1")
        if group["immortalAnchors"] != [] or group["eightwayAnchors"] != []:
            raise ProtocolError(f"{context}.groups cannot expose unimplemented anchors")
        covered.extend(group_stones)
        projected_groups.append((group["color"], group_stones, group_liberties))
    if tuple(sorted(covered)) != tuple(stone_points):
        raise ProtocolError(f"{context}.groups do not exactly cover stones")
    if projected_groups != _scan_projected_n4_groups(occupancy, board_size):
        raise ProtocolError(f"{context}.groups or liberties differ from N4 occupancy")

    terminal = _validate_terminal_state(state["terminal"], f"{context}.terminal", phase)
    if state["stableTerminalEventCount"] != int(terminal["ended"]):
        raise ProtocolError(f"{context}.stableTerminalEventCount differs from terminal")

    emitted = (
        state["atomicActionCount"]
        + state["settledLedgerCount"]
        + state["stableTerminalEventCount"]
    )
    if state["revision"] != state["atomicActionCount"]:
        raise ProtocolError(f"{context}.revision formula failed")
    if state["logPosition"] != emitted:
        raise ProtocolError(f"{context}.logPosition formula failed")
    if len(history) != 1 + emitted:
        raise ProtocolError(f"{context}.pskHistory length formula failed")
    return state


def _validate_transition(
    value: object,
    context: str,
    step: Mapping[str, object],
    previous: Mapping[str, object],
    state: Mapping[str, object],
    board_size: int,
) -> None:
    transition = _require_exact_fields(value, TRANSITION_FIELDS, context)
    if transition["candidateActor"] != step["candidateActor"]:
        raise ProtocolError(f"{context}.candidateActor differs from request")
    if transition["action"] != step["action"]:
        raise ProtocolError(f"{context}.action differs from request")
    if type(transition["accepted"]) is not bool:
        raise ProtocolError(f"{context}.accepted must be bool")
    _require_int(
        transition["positionalSuperkoAppends"],
        f"{context}.positionalSuperkoAppends",
    )
    status = transition["status"]
    if status not in ("ACCEPTED", "REJECTED", "UNSUPPORTED"):
        raise ProtocolError(f"{context}.status is unknown")

    if not transition["accepted"]:
        error_code = transition["errorCode"]
        if status == "UNSUPPORTED":
            if (
                transition["transitionKind"] != "UNSUPPORTED"
                or error_code != "UNSUPPORTED_BY_SLICE"
            ):
                raise ProtocolError(f"{context} unsupported classification is contradictory")
        elif status == "REJECTED":
            if transition["transitionKind"] != "REJECTED":
                raise ProtocolError(f"{context} rejected transitionKind differs")
            if error_code not in SUPPORTED_REJECTION_CODES:
                raise ProtocolError(f"{context} rejected errorCode is unknown or unsupported")
        else:
            raise ProtocolError(f"{context} accepted=false cannot use ACCEPTED status")
        if any(
            transition[field] is not None
            for field in ("atomicEvent", "settlement", "terminalEvent")
        ):
            raise ProtocolError(f"{context} rejected transition emitted events")
        if transition["positionalSuperkoAppends"] != 0 or state != previous:
            raise ProtocolError(f"{context} rejected transition changed state")
        return

    if status != "ACCEPTED" or transition["transitionKind"] != "ATOMIC_ACTION":
        raise ProtocolError(f"{context} accepted status is inconsistent")
    if transition["errorCode"] is not None:
        raise ProtocolError(f"{context} accepted transition has an error")
    if state["revision"] != previous["revision"] + 1:
        raise ProtocolError(f"{context} accepted revision did not advance once")
    if state["atomicActionCount"] != previous["atomicActionCount"] + 1:
        raise ProtocolError(f"{context} accepted action count did not advance once")

    point_count = board_size * board_size
    atomic = _require_exact_fields(
        transition["atomicEvent"], ATOMIC_EVENT_FIELDS, f"{context}.atomicEvent"
    )
    action_number = state["atomicActionCount"]
    if atomic["eventId"] != f"action-{action_number}" or atomic["actionNumber"] != action_number:
        raise ProtocolError(f"{context}.atomicEvent identity is inconsistent")
    if atomic["actor"] != step["candidateActor"] or atomic["action"] != step["action"]:
        raise ProtocolError(f"{context}.atomicEvent request binding differs")
    _validate_occupancy(atomic["captured"], f"{context}.atomicEvent.captured", point_count)
    stable = _validate_occupancy(
        atomic["stableOccupancy"],
        f"{context}.atomicEvent.stableOccupancy",
        point_count,
    )
    if stable != _validate_occupancy(state["occupancy"], f"{context}.state.occupancy", point_count):
        raise ProtocolError(f"{context}.atomicEvent stable occupancy differs")
    if atomic["pskHistoryIndex"] != len(previous["pskHistory"]):
        raise ProtocolError(f"{context} action was not appended before later events")

    settlement = transition["settlement"]
    settlement_steps: list[Mapping[str, object]] = []
    if settlement is not None:
        trace = _require_exact_fields(settlement, SETTLEMENT_FIELDS, f"{context}.settlement")
        if trace["triggerReason"] not in ("THRESHOLD", "PRE_THRESHOLD_TWO_PASSES"):
            raise ProtocolError(f"{context}.settlement reason is invalid")
        if trace["handoffActor"] != state["actor"]:
            raise ProtocolError(f"{context}.settlement handoff actor differs")
        if type(trace["steps"]) is not list:
            raise ProtocolError(f"{context}.settlement.steps must be an array")
        expected_ids = [entry["eventId"] for entry in reversed(state["ledger"])]
        for index, item in enumerate(trace["steps"]):
            step_value = _require_exact_fields(
                item,
                SETTLEMENT_STEP_FIELDS,
                f"{context}.settlement.steps[{index}]",
            )
            if step_value["stepIndex"] != index or type(step_value["stepIndex"]) is not int:
                raise ProtocolError(f"{context}.settlement step index differs")
            if index >= len(expected_ids) or step_value["ledgerEventId"] != expected_ids[index]:
                raise ProtocolError(f"{context}.settlement is not global newest-to-oldest")
            if step_value["abilityDeactivated"] is not False or step_value["noOp"] is not True:
                raise ProtocolError(f"{context}.settlement Double pop is not a no-op")
            if step_value["removalBatches"] != []:
                raise ProtocolError(f"{context}.settlement Double pop removed stones")
            if _validate_occupancy(
                step_value["stableOccupancy"],
                f"{context}.settlement.steps[{index}].stableOccupancy",
                point_count,
            ) != stable:
                raise ProtocolError(f"{context}.settlement stable occupancy differs")
            expected_index = atomic["pskHistoryIndex"] + 1 + index
            if step_value["pskHistoryIndex"] != expected_index:
                raise ProtocolError(f"{context}.settlement PSK index is not consecutive")
            settlement_steps.append(step_value)
        if len(settlement_steps) != len(state["ledger"]):
            raise ProtocolError(f"{context}.settlement did not pop the complete ledger")

    terminal = transition["terminalEvent"]
    terminal_count = 0
    terminal_delta = (
        state["stableTerminalEventCount"] - previous["stableTerminalEventCount"]
    )
    if terminal_delta not in (0, 1) or (terminal is not None) != (terminal_delta == 1):
        raise ProtocolError(f"{context}.terminalEvent differs from terminal counter")
    if terminal is not None:
        event = _require_exact_fields(
            terminal, TERMINAL_EVENT_FIELDS, f"{context}.terminalEvent"
        )
        if event["reason"] != "SCORE" or event["winner"] not in ("BLACK", "WHITE"):
            raise ProtocolError(f"{context}.terminalEvent is invalid")
        if event["loser"] == event["winner"] or event["loser"] not in ("BLACK", "WHITE"):
            raise ProtocolError(f"{context}.terminalEvent loser is invalid")
        terminal_state = state["terminal"]
        if (
            terminal_state["ended"] is not True
            or terminal_state["reason"] != event["reason"]
            or terminal_state["winner"] != event["winner"]
            or terminal_state["loser"] != event["loser"]
        ):
            raise ProtocolError(f"{context}.terminalEvent differs from terminal state")
        if event["eventId"] != f"terminal-{state['logPosition']}":
            raise ProtocolError(f"{context}.terminalEvent identity differs")
        if event["pskHistoryIndex"] != len(state["pskHistory"]) - 1:
            raise ProtocolError(f"{context}.terminalEvent PSK index differs")
        if _validate_occupancy(
            event["stableOccupancy"],
            f"{context}.terminalEvent.stableOccupancy",
            point_count,
        ) != stable:
            raise ProtocolError(f"{context}.terminalEvent occupancy differs")
        terminal_count = 1

    expected_appends = 1 + len(settlement_steps) + terminal_count
    if transition["positionalSuperkoAppends"] != expected_appends:
        raise ProtocolError(f"{context}.positionalSuperkoAppends formula failed")
    if len(state["pskHistory"]) - len(previous["pskHistory"]) != expected_appends:
        raise ProtocolError(f"{context}.pskHistory append count differs")
    suffix = state["pskHistory"][atomic["pskHistoryIndex"] :]
    if settlement_steps and any(item != state["occupancy"] for item in suffix):
        raise ProtocolError(f"{context}.settlement did not preserve duplicate no-op PSK entries")


def validate_episode_response(
    response: object,
    request: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> Mapping[str, object]:
    _check_deadline(deadline, "response validation")
    frame = _require_exact_fields(response, RESPONSE_FIELDS, "episode response")
    if frame["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError("response protocolVersion differs")
    if frame["episodeId"] != request["episodeId"]:
        raise ProtocolError("response episodeId differs")
    previous = _validate_state(
        frame["initialState"],
        "initialState",
        request["boardSize"],
        request["initialQuotas"],
    )
    if previous["atomicActionCount"] != 0 or previous["pskHistory"] != [
        {"black": [], "white": []}
    ]:
        raise ProtocolError("initial state is not the frozen empty PSK seed")
    observations = frame["observations"]
    if type(observations) is not list or len(observations) != len(request["steps"]):
        raise ProtocolError("response observation count differs from request")
    for index, (item, step) in enumerate(zip(observations, request["steps"]), start=1):
        _check_deadline(deadline, "response validation")
        observation = _require_exact_fields(
            item, OBSERVATION_FIELDS, f"observation {index}"
        )
        if observation["stepIndex"] != index or type(observation["stepIndex"]) is not int:
            raise ProtocolError(f"observation {index} has the wrong stepIndex")
        state = _validate_state(
            observation["state"],
            f"observation {index}.state",
            request["boardSize"],
            request["initialQuotas"],
        )
        _validate_transition(
            observation["transition"],
            f"observation {index}.transition",
            step,
            previous,
            state,
            request["boardSize"],
        )
        previous = state
    _check_deadline(deadline, "response validation")
    return frame


def parse_canonical_response_line(
    line: str,
    request: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> Mapping[str, object]:
    _check_deadline(deadline, "response parsing")
    if not line:
        raise ProtocolError("probe returned an empty response line")
    try:
        encoded = line.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ProtocolError(f"probe response contains invalid Unicode: {exc}") from exc
    if len(encoded) > MAX_RESPONSE_FRAME_BYTES:
        raise ProtocolError("probe response exceeds the 32 MiB response limit")
    try:
        parsed = parse_json_bytes(encoded)
    except ContractError as exc:
        raise ProtocolError(f"probe returned invalid restricted-profile JSON: {exc}") from exc
    _check_deadline(deadline, "response parsing")
    if canonical_json(parsed) != line:
        raise ProtocolError("probe response is not canonical restricted-profile JSON")
    response = validate_episode_response(parsed, request, deadline=deadline)
    _check_deadline(deadline, "response parsing")
    return response


def _first_difference(
    expected: object,
    actual: object,
    path: str = "$",
    *,
    deadline: float | None = None,
) -> str | None:
    _check_deadline(deadline, "exact response comparison")
    if type(expected) is not type(actual):
        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"
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
                expected[key], actual[key], f"{path}.{key}", deadline=deadline
            )
            if difference is not None:
                return difference
        return None
    if type(expected) is list:
        if len(expected) != len(actual):
            return f"{path}: length {len(expected)} != {len(actual)}"
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            difference = _first_difference(
                expected_item,
                actual_item,
                f"{path}[{index}]",
                deadline=deadline,
            )
            if difference is not None:
                return difference
        return None
    if expected != actual:
        return f"{path}: expected {expected!r}, actual {actual!r}"
    return None


def compare_exact(
    expected: object,
    actual: object,
    *,
    episode_id: str,
    deadline: float | None = None,
) -> None:
    difference = _first_difference(expected, actual, deadline=deadline)
    _check_deadline(deadline, "exact response comparison")
    if difference is not None:
        raise DifferentialMismatch(f"episode {episode_id}: {difference}")


def load_contract_fixture(
    path: Path = FIXTURE_PATH,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "fixture loading")
    fixture = parse_json_bytes(path.read_bytes())
    if type(fixture) is not dict:
        raise ProtocolError("contract fixture must be a JSON object")
    _check_deadline(deadline, "fixture loading")
    return fixture


def _validate_pinned_fixture_legal_ranges(
    fixture: Mapping[str, object],
) -> None:
    projections = [fixture["initialProjection"]] + [
        step["expectedProjection"] for step in fixture["steps"]
    ]
    actual: list[tuple[tuple[int, int], ...]] = []
    for projection_index, projection in enumerate(projections):
        ranges = projection["derived"]["legalActionRanges"]
        if type(ranges) is not list:
            raise ProtocolError(
                f"fixture legalActionRanges[{projection_index}] must be an array"
            )
        normalized: list[tuple[int, int]] = []
        for range_index, value in enumerate(ranges):
            fields = _require_exact_fields(
                value,
                frozenset(("first", "last")),
                f"fixture legalActionRanges[{projection_index}][{range_index}]",
            )
            first = _require_int(
                fields["first"],
                f"fixture legalActionRanges[{projection_index}][{range_index}].first",
                maximum=PASS_ACTION_ID,
            )
            last = _require_int(
                fields["last"],
                f"fixture legalActionRanges[{projection_index}][{range_index}].last",
                maximum=PASS_ACTION_ID,
            )
            if first > last:
                raise ProtocolError("fixture legalActionRange is reversed")
            normalized.append((first, last))
        actual.append(tuple(normalized))
    if tuple(actual) != PINNED_FIXTURE_LEGAL_ACTION_RANGES:
        raise ProtocolError(
            "checked-in Double fixture legalActionRanges differ from the pinned contract binding"
        )


def validate_contract_fixture(
    fixture: Mapping[str, object], *, deadline: float | None = None
) -> None:
    """Run the repository's frozen fixture Schema and semantic invariants."""

    _check_deadline(deadline, "contract fixture validation")
    catalog = SchemaCatalog()
    digest = validate_descriptor(load_json(DESCRIPTOR_PATH), catalog)
    _validate_fixture(fixture, catalog, digest)
    _validate_pinned_fixture_legal_ranges(fixture)
    _check_deadline(deadline, "contract fixture validation")


def fixture_request(
    fixture: Mapping[str, object] | None = None,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "fixture request generation")
    if fixture is None:
        fixture = load_contract_fixture(deadline=deadline)
    request = validate_episode_request(
        {
            "protocolVersion": PROTOCOL_VERSION,
            "episodeId": fixture["fixtureId"],
            "boardSize": fixture["configuration"]["boardSize"],
            "initialQuotas": copy.deepcopy(fixture["configuration"]["quotas"]),
            "steps": [
                {
                    "candidateActor": step["candidateActor"],
                    "action": copy.deepcopy(step["candidate"]["action"]),
                }
                for step in fixture["steps"]
            ],
        }
    )
    _check_deadline(deadline, "fixture request generation")
    return dict(request)


def fixture_reexecution_requests(
    fixture: Mapping[str, object] | None = None,
    *,
    deadline: float | None = None,
) -> list[dict[str, object]]:
    _check_deadline(deadline, "fixture deterministic re-execution generation")
    full = fixture_request(fixture, deadline=deadline)
    pending = copy.deepcopy(full)
    pending["episodeId"] = "fixture-gate-pending-prefix"
    pending["steps"] = pending["steps"][:1]
    before_settlement = copy.deepcopy(full)
    before_settlement["episodeId"] = "fixture-gate-before-settlement-prefix"
    before_settlement["steps"] = before_settlement["steps"][:2]
    reexecution = copy.deepcopy(full)
    reexecution["episodeId"] = "fixture-gate-full-reexecution"
    post_settlement = copy.deepcopy(full)
    post_settlement["episodeId"] = "fixture-gate-post-settlement-suffix"
    post_settlement["steps"].append(
        {
            "candidateActor": "BLACK",
            "action": board_action_v1(19, 0, 0),
        }
    )
    requests = []
    for request in (pending, before_settlement, reexecution, post_settlement):
        _check_deadline(deadline, "fixture deterministic re-execution generation")
        requests.append(dict(validate_episode_request(request)))
    return requests


def _normalize_contract_state(projection: Mapping[str, object]) -> dict[str, object]:
    source = projection["state"]
    ledger = []
    for entry in source["ledger"]:
        normalized = copy.deepcopy(entry)
        normalized["originActionNumber"] = normalized["logicalOrder"] + 1
        ledger.append(normalized)
    return {
        "revision": source["revision"],
        "logPosition": source["logPosition"],
        "boardSize": source["boardSize"],
        "threshold": source["threshold"],
        "occupancy": copy.deepcopy(source["occupancy"]),
        "stones": copy.deepcopy(source["stones"]),
        "groups": copy.deepcopy(projection["debug"]["groups"]),
        "actor": source["actor"],
        "phase": source["phase"],
        "atomicActionCount": source["atomicActionCount"],
        "consecutivePasses": source["consecutivePasses"],
        "settlementCompleted": source["settlementCompleted"],
        "pendingDouble": copy.deepcopy(source["pendingDouble"]),
        "initialQuotas": copy.deepcopy(source["initialQuotas"]),
        "remainingQuotas": copy.deepcopy(source["remainingQuotas"]),
        "usedQuotas": copy.deepcopy(source["usedQuotas"]),
        "expiredQuotas": copy.deepcopy(source["expiredQuotas"]),
        "ledger": ledger,
        "settledLedgerCount": sum(
            entry["settlementState"] == "SETTLED" for entry in source["ledger"]
        ),
        "stableTerminalEventCount": int(source["terminal"]["ended"]),
        "pskHistory": copy.deepcopy(source["pskHistory"]),
        "terminal": copy.deepcopy(source["terminal"]),
    }


def _normalize_contract_transition(
    step: Mapping[str, object], projection: Mapping[str, object]
) -> dict[str, object]:
    transition = projection["transition"]
    if transition is None:
        raise ValueError("fixture step requires a transition")
    settlement_count = (
        len(transition["settlement"]["steps"])
        if transition["settlement"] is not None
        else 0
    )
    terminal_count = int(transition["terminalEvent"] is not None)
    return {
        "accepted": transition["accepted"],
        "status": "ACCEPTED" if transition["accepted"] else "REJECTED",
        "transitionKind": transition["transitionKind"],
        "errorCode": transition["errorCode"],
        "candidateActor": step["candidateActor"],
        "action": copy.deepcopy(step["candidate"]["action"]),
        "atomicEvent": copy.deepcopy(transition["atomicEvent"]),
        "settlement": copy.deepcopy(transition["settlement"]),
        "terminalEvent": copy.deepcopy(transition["terminalEvent"]),
        "positionalSuperkoAppends": int(transition["accepted"])
        + settlement_count
        + terminal_count,
    }


def normalize_contract_fixture(
    fixture: Mapping[str, object] | None = None,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "fixture normalization")
    if fixture is None:
        fixture = load_contract_fixture(deadline=deadline)
    _validate_pinned_fixture_legal_ranges(fixture)
    response = {
        "protocolVersion": PROTOCOL_VERSION,
        "episodeId": fixture["fixtureId"],
        "initialState": _normalize_contract_state(fixture["initialProjection"]),
        "observations": [],
    }
    for step in fixture["steps"]:
        _check_deadline(deadline, "fixture normalization")
        projection = step["expectedProjection"]
        response["observations"].append(
            {
                "stepIndex": step["stepIndex"],
                "transition": _normalize_contract_transition(step, projection),
                "state": _normalize_contract_state(projection),
            }
        )
    validate_episode_response(
        response,
        fixture_request(fixture, deadline=deadline),
        deadline=deadline,
    )
    _check_deadline(deadline, "fixture normalization")
    return response


@dataclass
class EpisodeBuilder:
    episode_id: str
    board_size: int
    initial_quotas: dict[str, object]
    state: OracleState
    steps: list[dict[str, object]]
    deadline: float | None = None

    @classmethod
    def create(
        cls,
        episode_id: str,
        board_size: int,
        initial_quotas: Mapping[str, object] | None = None,
        *,
        deadline: float | None = None,
    ) -> "EpisodeBuilder":
        _check_deadline(deadline, "corpus generation")
        if initial_quotas is None:
            initial_quotas = quotas()
        copied = copy.deepcopy(initial_quotas)
        config = _oracle_config(copied, board_size)
        return cls(
            episode_id,
            board_size,
            copied,
            new_game(config),
            [],
            deadline,
        )

    def add(self, actor: Color, action: Mapping[str, object]) -> object | None:
        _check_deadline(self.deadline, "corpus generation")
        step = {"candidateActor": actor.value, "action": dict(action)}
        decode_action_v1(step["action"], self.board_size)
        self.steps.append(step)
        transition = _apply_v1_adapter(self.state, actor, step["action"])
        if transition is None:
            _check_deadline(self.deadline, "corpus generation")
            return None
        self.state = transition.state
        _check_deadline(self.deadline, "corpus generation")
        return transition

    def request(self) -> dict[str, object]:
        _check_deadline(self.deadline, "corpus generation")
        request = dict(
            validate_episode_request(
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "episodeId": self.episode_id,
                    "boardSize": self.board_size,
                    "initialQuotas": copy.deepcopy(self.initial_quotas),
                    "steps": copy.deepcopy(self.steps),
                }
            )
        )
        _check_deadline(self.deadline, "corpus generation")
        return request


def _first_accepted_point_action(
    state: OracleState,
    kind: ActionKind,
    start: int = 0,
    *,
    deadline: float | None = None,
) -> dict[str, object] | None:
    point_count = state.config.board_size * state.config.board_size
    for offset in range(point_count):
        _check_deadline(deadline, "corpus legal-candidate generation")
        point = (start + offset) % point_count
        action = board_action_v1(
            state.config.board_size,
            point % state.config.board_size,
            point // state.config.board_size,
            kind,
        )
        transition = _apply_v1_adapter(state, state.actor, action)
        if transition is None:
            continue
        if transition.accepted:
            return action
    return None


def capture_settlement_request(
    board_size: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    builder = EpisodeBuilder.create(
        episode_id, board_size, deadline=deadline
    )
    far = (
        (board_size - 1, board_size - 1),
        (board_size - 1, board_size - 2),
        (board_size - 2, board_size - 1),
        (board_size - 2, board_size - 2),
    )
    sequence = (
        (Color.BLACK, board_action_v1(board_size, 1, 1, ActionKind.DOUBLE_START)),
        (Color.BLACK, board_action_v1(board_size, *far[0])),
        (Color.WHITE, board_action_v1(board_size, 1, 0)),
        (Color.BLACK, board_action_v1(board_size, *far[1])),
        (Color.WHITE, board_action_v1(board_size, 0, 1)),
        (Color.BLACK, board_action_v1(board_size, *far[2])),
        (Color.WHITE, board_action_v1(board_size, 2, 1)),
        (Color.BLACK, board_action_v1(board_size, *far[3])),
        (Color.WHITE, board_action_v1(board_size, 1, 2)),
        (Color.BLACK, action_v1(PASS_ACTION_ID)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
        (Color.BLACK, board_action_v1(board_size, 3, 3, ActionKind.IMMORTAL)),
        (Color.BLACK, action_v1(PASS_ACTION_ID)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
        (Color.BLACK, board_action_v1(board_size, 4, 4)),
    )
    for actor, action in sequence:
        builder.add(actor, action)
    if builder.state.phase is not Phase.TERMINAL:
        raise AssertionError("capture/settlement episode did not reach terminal state")
    return builder.request()


def transform_board_point(board_size: int, point: int, symmetry: int) -> int:
    if type(symmetry) is not int or not 0 <= symmetry < 8:
        raise ValueError("symmetry must be in 0..7")
    x = point % board_size
    y = point // board_size
    if symmetry & 2:
        x = board_size - 1 - x
    if symmetry & 1:
        y = board_size - 1 - y
    if symmetry & 4:
        x, y = y, x
    return board_size * y + x


def transform_action(
    action: Mapping[str, object], board_size: int, symmetry: int
) -> dict[str, object]:
    decoded = decode_action_v1(action, board_size)
    if decoded.kind is ActionKind.PASS:
        return dict(action)
    transformed = transform_board_point(board_size, decoded.board_index, symmetry)
    return board_action_v1(
        board_size,
        transformed % board_size,
        transformed // board_size,
        decoded.kind,
    )


def transform_request(
    request: Mapping[str, object],
    symmetry: int,
    episode_id: str | None = None,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "D4 request transformation")
    transformed = copy.deepcopy(request)
    transformed["episodeId"] = episode_id or f"{request['episodeId']}-d4-{symmetry}"
    transformed_steps = []
    for step in request["steps"]:
        _check_deadline(deadline, "D4 request transformation")
        transformed_steps.append(
            {
                "candidateActor": step["candidateActor"],
                "action": transform_action(
                    step["action"], request["boardSize"], symmetry
                ),
            }
        )
    transformed["steps"] = transformed_steps
    result = dict(validate_episode_request(transformed))
    _check_deadline(deadline, "D4 request transformation")
    return result


def _transform_point_list(points: list[int], board_size: int, symmetry: int) -> list[int]:
    return sorted(transform_board_point(board_size, point, symmetry) for point in points)


def _transform_occupancy(value: dict[str, object], board_size: int, symmetry: int) -> None:
    value["black"] = _transform_point_list(value["black"], board_size, symmetry)
    value["white"] = _transform_point_list(value["white"], board_size, symmetry)


def _transform_state(value: dict[str, object], board_size: int, symmetry: int) -> None:
    _transform_occupancy(value["occupancy"], board_size, symmetry)
    for history in value["pskHistory"]:
        _transform_occupancy(history, board_size, symmetry)
    for stone in value["stones"]:
        stone["point"] = transform_board_point(board_size, stone["point"], symmetry)
    value["stones"].sort(key=lambda stone: stone["point"])
    for entry in value["ledger"]:
        entry["sourcePoint"] = transform_board_point(
            board_size, entry["sourcePoint"], symmetry
        )
    for group in value["groups"]:
        group["stones"] = _transform_point_list(group["stones"], board_size, symmetry)
        group["liberties"] = _transform_point_list(
            group["liberties"], board_size, symmetry
        )
        group["immortalAnchors"] = _transform_point_list(
            group["immortalAnchors"], board_size, symmetry
        )
        group["eightwayAnchors"] = _transform_point_list(
            group["eightwayAnchors"], board_size, symmetry
        )
    value["groups"].sort(key=lambda group: group["stones"][0])


def _transform_transition(
    value: dict[str, object], board_size: int, symmetry: int
) -> None:
    value["action"] = transform_action(value["action"], board_size, symmetry)
    atomic = value["atomicEvent"]
    if atomic is not None:
        atomic["action"] = transform_action(atomic["action"], board_size, symmetry)
        _transform_occupancy(atomic["captured"], board_size, symmetry)
        _transform_occupancy(atomic["stableOccupancy"], board_size, symmetry)
    settlement = value["settlement"]
    if settlement is not None:
        for step in settlement["steps"]:
            _transform_occupancy(step["stableOccupancy"], board_size, symmetry)
            for batch in step["removalBatches"]:
                _transform_occupancy(batch, board_size, symmetry)
    terminal = value["terminalEvent"]
    if terminal is not None:
        _transform_occupancy(terminal["stableOccupancy"], board_size, symmetry)


def transform_response(
    response: Mapping[str, object],
    board_size: int,
    symmetry: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "D4 response transformation")
    transformed = copy.deepcopy(response)
    transformed["episodeId"] = episode_id
    _transform_state(transformed["initialState"], board_size, symmetry)
    for observation in transformed["observations"]:
        _check_deadline(deadline, "D4 response transformation")
        _transform_transition(observation["transition"], board_size, symmetry)
        _transform_state(observation["state"], board_size, symmetry)
    _check_deadline(deadline, "D4 response transformation")
    return transformed


def _threshold_episode(
    *, legal_start: bool, deadline: float | None = None
) -> dict[str, object]:
    suffix = "legal" if legal_start else "too-late"
    builder = EpisodeBuilder.create(
        f"curated-threshold-{suffix}-9", 9, deadline=deadline
    )
    target = builder.state.threshold - (2 if legal_start else 1)
    start = 0
    while builder.state.atomic_action_count < target:
        action = _first_accepted_point_action(
            builder.state,
            ActionKind.NORMAL,
            start,
            deadline=deadline,
        )
        if action is None:
            raise AssertionError("could not build threshold prefix")
        transition = builder.add(builder.state.actor, action)
        if transition is None or not transition.accepted:
            raise AssertionError("threshold prefix action was not accepted")
        start = (action["actionId"] + 7) % 81
    double_action = _first_accepted_point_action(
        builder.state,
        ActionKind.DOUBLE_START,
        start,
        deadline=deadline,
    )
    if legal_start:
        if double_action is None:
            raise AssertionError("could not find legal T-1 Double start")
        started = builder.add(builder.state.actor, double_action)
        if started is None or not started.accepted:
            raise AssertionError("T-1 Double start was not accepted")
        completed = builder.add(builder.state.actor, action_v1(PASS_ACTION_ID))
        if completed is None or completed.settlement is None:
            raise AssertionError("T Double continuation did not settle")
    else:
        if double_action is not None:
            raise AssertionError("Double start unexpectedly legal at A=T-1")
        candidate = board_action_v1(9, 8, 8, ActionKind.DOUBLE_START)
        rejected = builder.add(builder.state.actor, candidate)
        if rejected is None or rejected.accepted:
            raise AssertionError("late Double start was not rejected")
    return builder.request()


def _multiple_ledger_episode(
    *, deadline: float | None = None
) -> dict[str, object]:
    builder = EpisodeBuilder.create(
        "curated-multiple-double-ledger-9",
        9,
        quotas(black_double=2, white_double=2, immortal=0, eightway=0),
        deadline=deadline,
    )
    sequence = (
        (Color.BLACK, board_action_v1(9, 0, 0, ActionKind.DOUBLE_START)),
        (Color.BLACK, board_action_v1(9, 1, 0)),
        (Color.WHITE, board_action_v1(9, 8, 8, ActionKind.DOUBLE_START)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
        (Color.BLACK, board_action_v1(9, 4, 4)),
        (Color.WHITE, board_action_v1(9, 7, 8, ActionKind.DOUBLE_START)),
        (Color.WHITE, board_action_v1(9, 6, 8)),
        (Color.BLACK, board_action_v1(9, 0, 1, ActionKind.DOUBLE_START)),
        (Color.BLACK, board_action_v1(9, 1, 1)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
        (Color.BLACK, action_v1(PASS_ACTION_ID)),
    )
    for actor, action in sequence:
        builder.add(actor, action)
    return builder.request()


def _control_and_quota_episode(
    *, deadline: float | None = None
) -> dict[str, object]:
    builder = EpisodeBuilder.create(
        "curated-control-quota-9", 9, deadline=deadline
    )
    builder.add(Color.BLACK, board_action_v1(9, 0, 0, ActionKind.IMMORTAL))
    builder.add(Color.BLACK, board_action_v1(9, 0, 0, ActionKind.EIGHTWAY))
    builder.add(Color.BLACK, board_action_v1(9, 4, 4, ActionKind.DOUBLE_START))
    builder.add(Color.WHITE, action_v1(PASS_ACTION_ID))
    for kind in (ActionKind.IMMORTAL, ActionKind.DOUBLE_START, ActionKind.EIGHTWAY):
        builder.add(Color.BLACK, board_action_v1(9, 0, 0, kind))
    builder.add(Color.BLACK, board_action_v1(9, 4, 4))
    builder.add(Color.BLACK, board_action_v1(9, 5, 4))
    builder.add(Color.WHITE, board_action_v1(9, 0, 0))
    builder.add(Color.BLACK, board_action_v1(9, 1, 0, ActionKind.DOUBLE_START))
    return builder.request()


def _suicide_episode(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder.create(
        "curated-pending-suicide-9", 9, deadline=deadline
    )
    for actor, x, y in (
        (Color.BLACK, 8, 8),
        (Color.WHITE, 1, 2),
        (Color.BLACK, 8, 7),
        (Color.WHITE, 3, 2),
        (Color.BLACK, 7, 8),
        (Color.WHITE, 2, 1),
        (Color.BLACK, 7, 7),
        (Color.WHITE, 2, 3),
    ):
        builder.add(actor, board_action_v1(9, x, y))
    builder.add(Color.BLACK, board_action_v1(9, 0, 0, ActionKind.DOUBLE_START))
    builder.add(Color.BLACK, board_action_v1(9, 2, 2))
    builder.add(Color.BLACK, action_v1(PASS_ACTION_ID))
    return builder.request()


def _psk_episode(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder.create(
        "curated-double-psk-9", 9, deadline=deadline
    )
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
    ):
        builder.add(actor, board_action_v1(9, x, y))
    builder.add(Color.WHITE, board_action_v1(9, 2, 2, ActionKind.DOUBLE_START))
    return builder.request()


def generate_curated_episodes(
    *, deadline: float | None = None
) -> list[dict[str, object]]:
    _check_deadline(deadline, "curated corpus generation")
    episodes = [fixture_request(deadline=deadline)]
    episodes.extend(fixture_reexecution_requests(deadline=deadline))
    for board_size in (9, 13, 19):
        _check_deadline(deadline, "curated D4 corpus generation")
        base = capture_settlement_request(
            board_size,
            f"curated-d4-capture-{board_size}-base",
            deadline=deadline,
        )
        for symmetry in range(8):
            _check_deadline(deadline, "curated D4 corpus generation")
            episodes.append(
                transform_request(
                    base,
                    symmetry,
                    f"curated-d4-capture-{board_size}-{symmetry}",
                    deadline=deadline,
                )
            )
    episodes.extend(
        (
            _multiple_ledger_episode(deadline=deadline),
            _control_and_quota_episode(deadline=deadline),
            _suicide_episode(deadline=deadline),
            _psk_episode(deadline=deadline),
            _threshold_episode(legal_start=True, deadline=deadline),
            _threshold_episode(legal_start=False, deadline=deadline),
        )
    )
    _check_deadline(deadline, "curated corpus generation")
    return episodes


def _random_actor(rng: Sha256CounterRng) -> Color:
    return (Color.BLACK, Color.WHITE)[rng.randbelow(2)]


def _opponent(actor: Color) -> Color:
    return Color.WHITE if actor is Color.BLACK else Color.BLACK


def _random_board_action(
    board_size: int, rng: Sha256CounterRng, kind: ActionKind
) -> dict[str, object]:
    point = rng.randbelow(board_size * board_size)
    return board_action_v1(
        board_size, point % board_size, point // board_size, kind
    )


def _random_episode(
    rng: Sha256CounterRng,
    seed_tag: str,
    sequence: int,
    maximum_steps: int,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "random corpus generation")
    board_size = (9, 13, 19)[rng.randbelow(3)]
    initial = quotas(
        black_double=1 + rng.randbelow(2),
        white_double=1 + rng.randbelow(2),
        immortal=rng.randbelow(2),
        eightway=rng.randbelow(2),
    )
    builder = EpisodeBuilder.create(
        f"random-double-{seed_tag}-{sequence:06d}",
        board_size,
        initial,
        deadline=deadline,
    )
    while len(builder.steps) < maximum_steps:
        if builder.state.phase is Phase.TERMINAL:
            builder.add(_random_actor(rng), action_v1(rng.randbelow(1445)))
            continue
        actor = builder.state.actor
        mode = rng.randbelow(9)
        if builder.state.pending_double is not None:
            if mode == 0:
                action = action_v1(PASS_ACTION_ID)
                candidate = actor
            elif mode == 1:
                action = _first_accepted_point_action(
                    builder.state,
                    ActionKind.NORMAL,
                    rng.randbelow(board_size**2),
                    deadline=deadline,
                ) or action_v1(PASS_ACTION_ID)
                candidate = actor
            elif mode == 2:
                action = action_v1(PASS_ACTION_ID)
                candidate = _opponent(actor)
            elif mode in (3, 4, 5):
                action = _random_board_action(
                    board_size,
                    rng,
                    (ActionKind.IMMORTAL, ActionKind.DOUBLE_START, ActionKind.EIGHTWAY)[
                        mode - 3
                    ],
                )
                candidate = actor
            else:
                action = action_v1(rng.randbelow(1445))
                candidate = actor if rng.randbelow(3) else _opponent(actor)
        else:
            if mode == 0:
                action = _first_accepted_point_action(
                    builder.state,
                    ActionKind.NORMAL,
                    rng.randbelow(board_size**2),
                    deadline=deadline,
                ) or action_v1(PASS_ACTION_ID)
                candidate = actor
            elif mode == 1:
                action = action_v1(PASS_ACTION_ID)
                candidate = actor
            elif mode == 2:
                action = _first_accepted_point_action(
                    builder.state,
                    ActionKind.DOUBLE_START,
                    rng.randbelow(board_size**2),
                    deadline=deadline,
                ) or _random_board_action(
                    board_size, rng, ActionKind.DOUBLE_START
                )
                candidate = actor
            elif mode == 3:
                action = action_v1(PASS_ACTION_ID)
                candidate = _opponent(actor)
            elif mode == 4 and builder.state.stones:
                point = builder.state.stones[rng.randbelow(len(builder.state.stones))].point
                action = board_action_v1(
                    board_size, point % board_size, point // board_size
                )
                candidate = actor
            elif mode in (5, 6):
                action = _random_board_action(
                    board_size,
                    rng,
                    (ActionKind.IMMORTAL, ActionKind.EIGHTWAY)[mode - 5],
                )
                candidate = actor
            else:
                action = action_v1(rng.randbelow(1445))
                candidate = actor if rng.randbelow(3) else _opponent(actor)
        builder.add(candidate, action)
    return builder.request()


def generate_random_episodes(
    seed: str,
    candidate_count: int,
    *,
    deadline: float | None = None,
) -> list[dict[str, object]]:
    _check_deadline(deadline, "random corpus generation")
    if type(candidate_count) is not int or not (
        MIN_RANDOM_CANDIDATE_COUNT
        <= candidate_count
        <= MAX_RANDOM_CANDIDATE_COUNT
    ):
        raise ValueError(
            f"candidate_count must be in {MIN_RANDOM_CANDIDATE_COUNT}.."
            f"{MAX_RANDOM_CANDIDATE_COUNT}"
        )
    rng = Sha256CounterRng(seed)
    seed_tag = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    episodes: list[dict[str, object]] = []
    generated = 0
    sequence = 0
    while generated < candidate_count:
        _check_deadline(deadline, "random corpus generation")
        maximum_steps = min(32, candidate_count - generated)
        episode = _random_episode(
            rng,
            seed_tag,
            sequence,
            maximum_steps,
            deadline=deadline,
        )
        episodes.append(episode)
        generated += len(episode["steps"])
        sequence += 1
    _check_deadline(deadline, "random corpus generation")
    return episodes


@dataclass(frozen=True)
class _ProbeProcessResult:
    returncode: int
    stdout: str
    stderr: str


def _run_probe_process(
    command: Sequence[str], probe_input: str, deadline: float
) -> _ProbeProcessResult:
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, (int, float))
        or not math.isfinite(deadline)
        or deadline <= 0
    ):
        raise ProbeError("probe deadline must be a finite positive monotonic timestamp")
    remaining_at_entry = _remaining_budget(deadline, "probe pre-launch")
    cleanup_reserve = min(
        PROCESS_CLEANUP_RESERVE_SECONDS,
        remaining_at_entry * 0.1,
    )
    operation_deadline = deadline - cleanup_reserve
    popen_kwargs: dict[str, object] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    _check_deadline(deadline, "probe pre-launch")
    try:
        process = subprocess.Popen(
            list(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_kwargs,
        )
    except OSError as exc:
        raise ProbeError(f"could not launch probe {command[0]}: {exc}") from exc
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    def signal_process_tree(*, force: bool) -> None:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError:
                if process.poll() is None:
                    try:
                        process.kill() if force else process.terminate()
                    except OSError:
                        pass
        elif process.poll() is None:
            try:
                process.kill() if force else process.terminate()
            except OSError:
                pass

    def close_pipe_fd(stream) -> None:
        try:
            os.close(stream.fileno())
        except (OSError, ValueError):
            pass

    overflow = threading.Event()
    overflow_streams: list[str] = []
    stream_errors: list[tuple[str, BaseException]] = []
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    def read_bounded(stream, limit: int, chunks: list[bytes], name: str) -> None:
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
                if total > limit and name not in overflow_streams:
                    overflow_streams.append(name)
                    overflow.set()
        except BaseException as exc:  # pragma: no cover - defensive pipe failure
            stream_errors.append((name, exc))
            overflow.set()
        finally:
            try:
                stream.close()
            except OSError:
                pass

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
    threads = (writer_thread, stdout_thread, stderr_thread)
    for thread in threads:
        thread.start()

    timed_out = False
    while True:
        readers_done = not stdout_thread.is_alive() and not stderr_thread.is_alive()
        writer_done = not writer_thread.is_alive()
        if overflow.is_set():
            break
        remaining = operation_deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            break
        if process.poll() is not None and readers_done and writer_done:
            break
        overflow.wait(timeout=min(0.05, remaining))

    forced_cleanup = timed_out or bool(overflow_streams) or any(
        thread.is_alive() for thread in threads
    )
    if forced_cleanup:
        signal_process_tree(force=False)
        grace = max(0.0, min(0.05, deadline - time.monotonic()))
        if grace:
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
        signal_process_tree(force=True)
        for stream in (process.stdin, process.stdout, process.stderr):
            close_pipe_fd(stream)

    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in threads):
        timed_out = True
        signal_process_tree(force=True)
        for stream in (process.stdin, process.stdout, process.stderr):
            close_pipe_fd(stream)

    remaining = max(0.0, deadline - time.monotonic())
    if process.poll() is None and remaining:
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            signal_process_tree(force=True)
    returncode = process.poll()
    if returncode is None:
        timed_out = True
        returncode = -1

    stdout_bytes = b"".join(stdout_chunks)
    stderr_bytes = b"".join(stderr_chunks)
    if timed_out:
        raise ProbeError("probe exceeded the absolute corpus deadline")
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
    except UnicodeDecodeError as exc:
        raise ProbeOutputDecodeError(
            "stdout",
            exc.start,
            stdout_bytes[: exc.start].count(b"\n"),
        ) from exc
    try:
        stderr = stderr_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProbeOutputDecodeError("stderr", exc.start, 0) from exc
    return _ProbeProcessResult(returncode, stdout, stderr)


def _digest_record(digest, data: str) -> None:
    encoded = data.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _reproduction_context(
    manifest: Mapping[str, object],
    request: Mapping[str, object],
    request_line: str,
    prefix_length: int,
) -> str:
    return (
        f"manifest={canonical_json(manifest)}; "
        f"canonicalRequest={request_line}; "
        f"actionPrefix={canonical_json(request['steps'][:prefix_length])}"
    )


def _mismatch_prefix_length(
    expected: Mapping[str, object],
    actual: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> int:
    for index, (left, right) in enumerate(
        zip(expected["observations"], actual["observations"]), start=1
    ):
        if _first_difference(left, right, deadline=deadline) is not None:
            return index
    return len(expected["observations"])


def _response_failure_context(
    manifest: Mapping[str, object] | None,
    requests: Sequence[Mapping[str, object]],
    request_lines: Sequence[str],
    response_index: int,
) -> str:
    diagnostic_manifest = manifest or {
        "protocolVersion": PROTOCOL_VERSION,
        "requestCount": len(requests),
    }
    if not requests:
        return (
            f"responseIndex={response_index}; "
            f"manifest={canonical_json(diagnostic_manifest)}"
        )
    request_index = min(max(response_index, 0), len(requests) - 1)
    return (
        f"responseIndex={response_index}; "
        + _reproduction_context(
            diagnostic_manifest,
            requests[request_index],
            request_lines[request_index],
            len(requests[request_index]["steps"]),
        )
    )


def run_probe_requests(
    probe_path: Path | str,
    requests: Sequence[Mapping[str, object]],
    *,
    manifest: Mapping[str, object] | None = None,
    deadline: float | None = None,
) -> tuple[list[Mapping[str, object]], str]:
    if deadline is None:
        deadline = _new_deadline()
    _check_deadline(deadline, "probe setup")
    probe = Path(probe_path).expanduser().resolve()
    if not probe.is_file():
        raise ProbeError(f"probe executable does not exist: {probe}")
    request_lines: list[str] = []
    for request in requests:
        _check_deadline(deadline, "probe request serialization")
        request_lines.append(canonical_json(validate_episode_request(request)))
    try:
        completed = _run_probe_process(
            [str(probe)],
            "".join(line + "\n" for line in request_lines),
            deadline,
        )
    except ProbeOutputDecodeError as exc:
        response_index = exc.response_index if exc.stream_name == "stdout" else 0
        context = _response_failure_context(
            manifest, requests, request_lines, response_index
        )
        raise ProbeError(f"{exc}; {context}") from exc
    _check_deadline(deadline, "probe supervision")
    if completed.returncode != 0:
        raise ProbeError(
            f"probe exited with {completed.returncode}; stderr={completed.stderr!r}"
        )
    if completed.stderr:
        raise ProbeError(f"probe emitted successful-run diagnostics: {completed.stderr!r}")
    if not completed.stdout.endswith("\n"):
        response_index = min(completed.stdout.count("\n"), len(requests))
        context = _response_failure_context(
            manifest, requests, request_lines, response_index
        )
        raise ProbeError(f"probe output is not newline-terminated; {context}")
    response_lines = completed.stdout[:-1].split("\n")
    if len(response_lines) != len(requests):
        response_index = min(len(response_lines), len(requests))
        context = _response_failure_context(
            manifest, requests, request_lines, response_index
        )
        raise ProbeError(
            "probe response line count differs from request count: "
            f"{len(response_lines)} != {len(requests)}; {context}"
        )
    digest = hashlib.sha256()
    if manifest is not None:
        _digest_record(digest, canonical_json(manifest))
    responses: list[Mapping[str, object]] = []
    for response_index, (request, request_line, response_line) in enumerate(
        zip(requests, request_lines, response_lines)
    ):
        _check_deadline(deadline, "response parsing and digesting")
        try:
            response = parse_canonical_response_line(
                response_line, request, deadline=deadline
            )
        except ProtocolError as exc:
            context = _response_failure_context(
                manifest, requests, request_lines, response_index
            )
            raise ProtocolError(f"{exc}; {context}") from exc
        responses.append(response)
        _digest_record(digest, request_line)
        _digest_record(digest, response_line)
    _check_deadline(deadline, "response parsing and digesting")
    return responses, digest.hexdigest()


def _assert_fixture_d4_reexecution_and_prefixes(
    expected_by_id: Mapping[str, Mapping[str, object]],
    actual_by_id: Mapping[str, Mapping[str, object]],
    fixture: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> None:
    _check_deadline(deadline, "fixture normalization comparison")
    fixture_id = fixture["fixtureId"]
    normalized_fixture = normalize_contract_fixture(fixture, deadline=deadline)
    compare_exact(
        normalized_fixture,
        expected_by_id[fixture_id],
        episode_id=f"{fixture_id}-python-vs-contract",
        deadline=deadline,
    )
    compare_exact(
        normalized_fixture,
        actual_by_id[fixture_id],
        episode_id=f"{fixture_id}-cpp-vs-contract",
        deadline=deadline,
    )

    pending_id = "fixture-gate-pending-prefix"
    before_id = "fixture-gate-before-settlement-prefix"
    reexecution_id = "fixture-gate-full-reexecution"
    post_id = "fixture-gate-post-settlement-suffix"
    for side, responses in (("python", expected_by_id), ("cpp", actual_by_id)):
        _check_deadline(deadline, "deterministic action re-execution and prefix checks")
        full = responses[fixture_id]
        if responses[pending_id]["observations"] != full["observations"][:1]:
            raise DifferentialMismatch(f"{side} pending immutable prefix differs")
        if responses[before_id]["observations"] != full["observations"][:2]:
            raise DifferentialMismatch(f"{side} pre-settlement immutable prefix differs")
        reexecuted = copy.deepcopy(responses[reexecution_id])
        reexecuted["episodeId"] = fixture_id
        compare_exact(
            full,
            reexecuted,
            episode_id=f"{side}-fixture-action-reexecution",
            deadline=deadline,
        )
        if responses[post_id]["observations"][:3] != full["observations"]:
            raise DifferentialMismatch(f"{side} post-settlement suffix rewrote prefix")

    for board_size in (9, 13, 19):
        base_id = f"curated-d4-capture-{board_size}-0"
        for symmetry in range(8):
            _check_deadline(deadline, "D4 metamorphic comparison")
            target_id = f"curated-d4-capture-{board_size}-{symmetry}"
            inverse = INVERSE_SYMMETRY_IDS[symmetry]
            for side, responses in (("python", expected_by_id), ("cpp", actual_by_id)):
                transformed = transform_response(
                    responses[base_id],
                    board_size,
                    symmetry,
                    target_id,
                    deadline=deadline,
                )
                compare_exact(
                    transformed,
                    responses[target_id],
                    episode_id=f"{side}-d4-{board_size}-{symmetry}",
                    deadline=deadline,
                )
                restored = transform_response(
                    responses[target_id],
                    board_size,
                    inverse,
                    base_id,
                    deadline=deadline,
                )
                compare_exact(
                    responses[base_id],
                    restored,
                    episode_id=f"{side}-d4-inverse-{board_size}-{symmetry}",
                    deadline=deadline,
                )
    _check_deadline(deadline, "D4 and deterministic action re-execution checks")


def run_differential(
    probe_path: Path | str,
    *,
    seed: str = DEFAULT_SEED,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    deadline = _new_deadline(timeout_seconds)
    _check_deadline(deadline, "differential entry")
    fixture = load_contract_fixture(deadline=deadline)
    validate_contract_fixture(fixture, deadline=deadline)
    curated = generate_curated_episodes(deadline=deadline)
    random_episodes = generate_random_episodes(
        seed, candidate_count, deadline=deadline
    )
    episodes = curated + random_episodes
    manifest = {
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": candidate_count,
        "seed": seed,
    }
    expected: list[dict[str, object]] = []
    for request in episodes:
        _check_deadline(deadline, "Python oracle corpus execution")
        expected.append(oracle_episode_response(request, deadline=deadline))
    actual, digest = run_probe_requests(
        probe_path,
        episodes,
        manifest=manifest,
        deadline=deadline,
    )

    accepted = rejected = unsupported = 0
    error_counts: dict[str, int] = {}
    settlement_counts: dict[str, int] = {}
    for request, expected_response, actual_response in zip(
        episodes,
        expected,
        actual,
    ):
        _check_deadline(deadline, "exact corpus comparison")
        request_line_expected = canonical_json(request)
        try:
            compare_exact(
                expected_response,
                actual_response,
                episode_id=request["episodeId"],
                deadline=deadline,
            )
        except DifferentialMismatch as exc:
            context = _reproduction_context(
                manifest,
                request,
                request_line_expected,
                _mismatch_prefix_length(
                    expected_response, actual_response, deadline=deadline
                ),
            )
            raise DifferentialMismatch(f"{exc}; {context}") from exc
        for observation in expected_response["observations"]:
            _check_deadline(deadline, "summary projection")
            transition = observation["transition"]
            if transition["status"] == "ACCEPTED":
                accepted += 1
            elif transition["status"] == "REJECTED":
                rejected += 1
            else:
                unsupported += 1
            error = transition["errorCode"] or "NONE"
            error_counts[error] = error_counts.get(error, 0) + 1
            reason = (
                transition["settlement"]["triggerReason"]
                if transition["settlement"] is not None
                else "NONE"
            )
            settlement_counts[reason] = settlement_counts.get(reason, 0) + 1

    _check_deadline(deadline, "deterministic action re-execution setup")
    expected_by_id = {response["episodeId"]: response for response in expected}
    actual_by_id = {response["episodeId"]: response for response in actual}
    _assert_fixture_d4_reexecution_and_prefixes(
        expected_by_id,
        actual_by_id,
        fixture,
        deadline=deadline,
    )

    _check_deadline(deadline, "summary validation")
    curated_count = sum(len(request["steps"]) for request in curated)
    total_count = curated_count + candidate_count
    if accepted + rejected + unsupported != total_count:
        raise AssertionError("summary status counts do not match compared candidates")
    summary = {
        "accepted": accepted,
        "candidateCount": total_count,
        "contractFixtureValidated": True,
        "curatedCandidateCount": curated_count,
        "d4Metamorphic": True,
        "deterministicActionReexecutionAndPrefixesExact": True,
        "episodeCount": len(episodes),
        "errorCounts": error_counts,
        "fixtureId": fixture["fixtureId"],
        "fixtureNormalized": True,
        "gateRule1MClaimed": False,
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": candidate_count,
        "rejected": rejected,
        "scope": "DOUBLE_INCREMENT_1_UNFROZEN_TEST_ONLY",
        "seed": seed,
        "settlementReasonCounts": settlement_counts,
        "sha256": digest,
        "unsupported": unsupported,
    }
    _check_deadline(deadline, "summary serialization readiness")
    return summary


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the bounded test-only UNFROZEN Double Increment 1 differential. "
            "This is not a production protocol or GATE-RULE-1M."
        )
    )
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument(
        "--candidate-count", type=int, default=DEFAULT_CANDIDATE_COUNT
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
    except (
        ContractError,
        ProtocolError,
        ProbeError,
        DifferentialMismatch,
        ValueError,
    ) as exc:
        invocation = {
            "requestedRandomCandidateCount": args.candidate_count,
            "generatorVersion": GENERATOR_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "seed": args.seed,
        }
        print(
            f"Double Increment 1 differential failed: {exc}; "
            f"invocation={canonical_json(invocation)}",
            file=sys.stderr,
        )
        return 1
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
