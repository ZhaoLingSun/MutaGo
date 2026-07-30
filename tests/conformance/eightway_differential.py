#!/usr/bin/env python3
"""Bounded test-only Eightway Increment 3 C++/Python differential carrier.

The protocol literal and every carrier field are explicitly UNFROZEN.  C++
executes the production reducer; expectations come only from the independent
stdlib Python oracle.  This is not a production protocol, persistence format,
public replay/undo API, or evidence for either project gate.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence

CONFORMANCE_DIR = Path(__file__).resolve().parent
if str(CONFORMANCE_DIR) not in sys.path:
    sys.path.insert(0, str(CONFORMANCE_DIR))

import double_move_differential as hardened  # noqa: E402

if Path(hardened.__file__).resolve() != CONFORMANCE_DIR / "double_move_differential.py":
    raise ImportError(
        f"double_move_differential resolved outside this checkout: {hardened.__file__}"
    )

from mutago.collapse_go import (  # noqa: E402
    PASS_ACTION_ID,
    AbilityState,
    ActionKind,
    Color,
    OracleConfig,
    Phase,
    PlayerQuotas,
    SettlementState,
    SpecialQuotas,
    StoneState,
    apply_action,
    decode_action_v1,
    new_game,
    scan_mixed_groups,
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

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPO_ROOT
    / "tests"
    / "contracts"
    / "examples"
    / "conformance-fixture-eightway-immortal-split-v1.example.json"
)
PROTOCOL_VERSION = "eightway-diff-v3-unfrozen"
GENERATOR_VERSION = "sha256-counter-eightway-v3-unfrozen"
DEFAULT_SEED = "mutago-eightway-increment-3"
DEFAULT_CANDIDATE_COUNT = 256
MIN_RANDOM_CANDIDATE_COUNT = 64
MAX_RANDOM_CANDIDATE_COUNT = 4096
MAX_EPISODE_STEPS = 160
MAX_TEST_QUOTA = 4
MAX_REQUEST_FRAME_BYTES = 1024 * 1024
MAX_RESPONSE_FRAME_BYTES = 96 * 1024 * 1024
MAX_PROBE_STDOUT_BYTES = 256 * 1024 * 1024
MAX_PROBE_STDERR_BYTES = 1024 * 1024
PROBE_TIMEOUT_SECONDS = 180
INVERSE_SYMMETRY_IDS = (0, 1, 2, 3, 4, 6, 5, 7)
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

ProtocolError = hardened.ProtocolError
ProbeError = hardened.ProbeError
DifferentialMismatch = hardened.DifferentialMismatch
Sha256CounterRng = hardened.Sha256CounterRng
canonical_json = hardened.canonical_json
action_v1 = hardened.action_v1
board_action_v1 = hardened.board_action_v1
transform_board_point = hardened.transform_board_point
transform_action = hardened.transform_action


def _check_deadline(deadline: float | None, phase: str) -> None:
    hardened._check_deadline(deadline, phase)


def quotas(
    *,
    black_immortal: int = 1,
    white_immortal: int = 1,
    black_double: int = 1,
    white_double: int = 1,
    eightway: int = 1,
    black_eightway: int | None = None,
    white_eightway: int | None = None,
) -> dict[str, object]:
    if black_eightway is None:
        black_eightway = eightway
    if white_eightway is None:
        white_eightway = eightway
    return {
        "BLACK": {
            "IMMORTAL": black_immortal,
            "DOUBLE_START": black_double,
            "EIGHTWAY": black_eightway,
        },
        "WHITE": {
            "IMMORTAL": white_immortal,
            "DOUBLE_START": white_double,
            "EIGHTWAY": white_eightway,
        },
    }


def _oracle_config(initial: Mapping[str, object], board_size: int) -> OracleConfig:
    def vector(color: str) -> SpecialQuotas:
        source = initial[color]
        return SpecialQuotas(
            immortal=source["IMMORTAL"],
            double_start=source["DOUBLE_START"],
            eightway=source["EIGHTWAY"],
        )

    return OracleConfig(
        board_size=board_size,
        quotas=PlayerQuotas(black=vector("BLACK"), white=vector("WHITE")),
    )


def validate_episode_request(request: object) -> Mapping[str, object]:
    frame = hardened._require_exact_fields(
        request,
        frozenset(("protocolVersion", "episodeId", "boardSize", "initialQuotas", "steps")),
        "Eightway episode request",
    )
    if frame["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError(f"protocolVersion must be {PROTOCOL_VERSION}")
    if not hardened._valid_episode_id(frame["episodeId"]):
        raise ProtocolError("episodeId has an invalid test identifier")
    board_size = frame["boardSize"]
    if type(board_size) is not int or board_size not in (9, 13, 19):
        raise ProtocolError("boardSize must be exactly 9, 13, or 19")
    players = hardened._require_exact_fields(
        frame["initialQuotas"], frozenset(("BLACK", "WHITE")), "initialQuotas"
    )
    for color in ("BLACK", "WHITE"):
        vector = hardened._require_exact_fields(
            players[color],
            frozenset(("IMMORTAL", "DOUBLE_START", "EIGHTWAY")),
            f"initialQuotas.{color}",
        )
        for kind, value in vector.items():
            hardened._require_int(
                value, f"initialQuotas.{color}.{kind}", maximum=MAX_TEST_QUOTA
            )
    steps = frame["steps"]
    if type(steps) is not list or not 1 <= len(steps) <= MAX_EPISODE_STEPS:
        raise ProtocolError("steps must be a nonempty array within the resource limit")
    for index, item in enumerate(steps):
        step = hardened._require_exact_fields(
            item, frozenset(("candidateActor", "action")), f"step {index}"
        )
        if step["candidateActor"] not in ("BLACK", "WHITE"):
            raise ProtocolError(f"step {index} candidateActor must be BLACK or WHITE")
        try:
            decode_action_v1(step["action"], board_size)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"step {index} has invalid Action V1: {exc}") from exc
    if len(canonical_json(frame).encode("utf-8")) > MAX_REQUEST_FRAME_BYTES:
        raise ProtocolError("canonical request exceeds the 1 MiB request limit")
    return frame


def _apply_v3_adapter(state, actor: Color, action: Mapping[str, object]):
    """Apply every action kind through the independent Python oracle."""

    return apply_action(state, actor, action)


def _occupancy(value) -> dict[str, object]:
    return {"black": list(value.black), "white": list(value.white)}


def _quota_projection(value: PlayerQuotas) -> dict[str, object]:
    def vector(item: SpecialQuotas) -> dict[str, object]:
        return {
            "IMMORTAL": item.immortal,
            "DOUBLE_START": item.double_start,
            "EIGHTWAY": item.eightway,
        }

    return {"BLACK": vector(value.black), "WHITE": vector(value.white)}


def _stone(stone) -> dict[str, object]:
    return {
        "color": stone.color.value,
        "originActionNumber": stone.origin_action_number,
        "originKind": stone.origin_kind.value,
        "point": stone.point,
        "sourceId": stone.source_id,
        "specialEventId": stone.special_event_id,
    }


def _ledger(event) -> dict[str, object]:
    return {
        "abilityState": event.ability_state.value,
        "eventId": event.event_id,
        "kind": event.kind.value,
        "logicalOrder": event.logical_order,
        "originActionNumber": event.origin_action_number,
        "owner": event.owner.value,
        "settlementState": event.settlement_state.value,
        "sourcePoint": event.source_point,
        "sourceStoneId": event.source_stone_id,
        "stoneState": event.stone_state.value,
        "tombstone": event.tombstone,
    }


def _groups(board, ledger) -> list[dict[str, object]]:
    return [
        {
            "color": group.color.value,
            "eightwayAnchors": list(group.eightway_anchor_points),
            "immortalAnchors": list(group.immortal_anchor_points),
            "liberties": list(group.liberties),
            "protected": group.protected,
            "stones": list(group.stones),
        }
        for group in scan_mixed_groups(board, ledger)
    ]


def _score(score) -> dict[str, object]:
    return {
        "black": {"denominator": 2, "numerator": score.black_score_numerator},
        "margin": {"denominator": 2, "numerator": score.margin_numerator},
        "white": {"denominator": 2, "numerator": score.white_score_numerator},
    }


def _terminal(state) -> dict[str, object]:
    if state.terminal is None:
        return {"ended": False}
    return {
        "ended": True,
        "loser": state.terminal.loser.value,
        "reason": state.terminal.reason.value,
        "score": _score(state.terminal.score),
        "winner": state.terminal.winner.value,
    }


def state_projection(state) -> dict[str, object]:
    pending = None
    if state.pending_double is not None:
        pending = {
            "eventId": state.pending_double.event_id,
            "owner": state.pending_double.owner.value,
            "startActionNumber": state.pending_double.start_action_number,
        }
    groups = _groups(state.board, state.ledger)
    anchors = sorted(
        point
        for group in groups
        for point in group["immortalAnchors"]
    )
    eightway_anchors = sorted(
        point
        for group in groups
        for point in group["eightwayAnchors"]
    )
    return {
        "actor": state.actor.value if state.actor is not None else None,
        "atomicActionCount": state.atomic_action_count,
        "boardSize": state.config.board_size,
        "consecutivePasses": state.consecutive_passes,
        "eventLogLength": state.log_position,
        "expiredQuotas": _quota_projection(state.expired_quotas),
        "groups": groups,
        "eightwayAnchors": eightway_anchors,
        "immortalAnchors": anchors,
        "initialQuotas": _quota_projection(state.initial_quotas),
        "ledger": [_ledger(event) for event in state.ledger],
        "logPosition": state.log_position,
        "occupancy": _occupancy(state.occupancy),
        "pendingDouble": pending,
        "phase": state.phase.value,
        "pskHistory": [_occupancy(item) for item in state.psk_history],
        "remainingQuotas": _quota_projection(state.remaining_quotas),
        "revision": state.revision,
        "settledLedgerCount": state.settled_ledger_count,
        "settlementCompleted": state.phase is not Phase.COLLAPSE_PLAY,
        "stableTerminalEventCount": state.stable_terminal_event_count,
        "stones": [_stone(stone) for stone in state.stones],
        "terminal": _terminal(state),
        "threshold": state.threshold,
        "usedQuotas": _quota_projection(state.used_quotas),
    }


def _atomic_ledger(previous, transition):
    if transition.settlement is None:
        return transition.state.ledger
    event = transition.atomic_event
    sources = {stone.source_id: stone for stone in event.stable_stones}
    result = []
    for final in transition.state.ledger:
        source = sources.get(final.source_stone_id)
        if source is None:
            result.append(
                replace(
                    final,
                    ability_state=(
                        AbilityState.INACTIVE
                        if final.kind in (ActionKind.IMMORTAL, ActionKind.EIGHTWAY)
                        else AbilityState.CONSUMED
                    ),
                    stone_state=StoneState.CAPTURED,
                    settlement_state=SettlementState.PENDING,
                    tombstone=True,
                )
            )
        else:
            result.append(
                replace(
                    final,
                    ability_state=(
                        AbilityState.ARMED
                        if final.kind in (ActionKind.IMMORTAL, ActionKind.EIGHTWAY)
                        else AbilityState.CONSUMED
                    ),
                    stone_state=StoneState.ON_BOARD,
                    settlement_state=SettlementState.PENDING,
                    tombstone=final.kind is ActionKind.DOUBLE_START,
                )
            )
    return tuple(result)


def _atomic_snapshot(previous, transition) -> dict[str, object]:
    event = transition.atomic_event
    action_kind = event.action.kind
    ledger = _atomic_ledger(previous, transition)
    board = type(previous.board).from_stones(previous.board.size, event.stable_stones)
    remaining = _quota_projection(previous.remaining_quotas)
    used = _quota_projection(previous.used_quotas)
    if action_kind in (
        ActionKind.IMMORTAL,
        ActionKind.DOUBLE_START,
        ActionKind.EIGHTWAY,
    ):
        owner = event.actor.value
        remaining[owner][action_kind.value] -= 1
        used[owner][action_kind.value] += 1

    if action_kind is ActionKind.DOUBLE_START:
        pending = {
            "eventId": f"special-{event.action_number}",
            "owner": event.actor.value,
            "startActionNumber": event.action_number,
        }
    elif previous.pending_double is not None:
        pending = None
    else:
        pending = None
    groups = _groups(board, ledger)
    anchors = sorted(
        point
        for group in groups
        for point in group["immortalAnchors"]
    )
    eightway_anchors = sorted(
        point
        for group in groups
        for point in group["eightwayAnchors"]
    )
    atomic_actor = (
        event.actor if action_kind is ActionKind.DOUBLE_START else event.actor.opponent()
    )
    return {
        "actor": atomic_actor.value,
        "atomicActionCount": event.action_number,
        "boardSize": previous.config.board_size,
        "consecutivePasses": (
            previous.consecutive_passes + 1
            if action_kind is ActionKind.PASS
            else 0
        ),
        "eventLogLength": event.log_position,
        "expiredQuotas": _quota_projection(previous.expired_quotas),
        "groups": groups,
        "eightwayAnchors": eightway_anchors,
        "immortalAnchors": anchors,
        "initialQuotas": _quota_projection(previous.initial_quotas),
        "ledger": [_ledger(item) for item in ledger],
        "logPosition": event.log_position,
        "occupancy": _occupancy(event.stable_occupancy),
        "pendingDouble": pending,
        "phase": previous.phase.value,
        "pskHistory": [
            _occupancy(item)
            for item in transition.state.psk_history[: event.psk_history_index + 1]
        ],
        "remainingQuotas": remaining,
        "revision": event.revision,
        "settledLedgerCount": previous.settled_ledger_count,
        "settlementCompleted": previous.phase is not Phase.COLLAPSE_PLAY,
        "stableTerminalEventCount": previous.stable_terminal_event_count,
        "stones": [_stone(item) for item in event.stable_stones],
        "terminal": _terminal(previous),
        "threshold": previous.threshold,
        "usedQuotas": used,
    }


def _atomic_event(event, action: Mapping[str, object]) -> dict[str, object]:
    return {
        "action": dict(action),
        "actionNumber": event.action_number,
        "actor": event.actor.value,
        "captured": _occupancy(event.captured),
        "eventId": f"action-{event.action_number}",
        "pskHistoryIndex": event.psk_history_index,
        "stableOccupancy": _occupancy(event.stable_occupancy),
        "stableStones": [_stone(item) for item in event.stable_stones],
    }


def _settlement(transition) -> dict[str, object] | None:
    if transition.settlement is None:
        return None
    ledger_by_id = {event.event_id: event for event in transition.state.ledger}
    return {
        "handoffActor": transition.state.actor.value,
        "steps": [
            {
                "abilityDeactivated": step.ability_deactivated,
                "kind": step.kind.value,
                "ledgerEventId": step.event_id,
                "noOp": step.no_op,
                "originActionNumber": step.logical_order + 1,
                "owner": step.owner.value,
                "pskHistoryIndex": step.psk_history_index,
                "removalBatches": [_occupancy(batch) for batch in step.removal_batches],
                "sourcePoint": ledger_by_id[step.event_id].source_point,
                "stableOccupancy": _occupancy(step.stable_occupancy),
                "stepIndex": index,
            }
            for index, step in enumerate(transition.settlement.steps)
        ],
        "triggerReason": transition.settlement.reason.value,
    }


def _terminal_event(event) -> dict[str, object]:
    return {
        "eventId": f"terminal-{event.log_position}",
        "loser": event.loser.value,
        "pskHistoryIndex": event.psk_history_index,
        "reason": event.reason.value,
        "stableOccupancy": _occupancy(event.stable_occupancy),
        "winner": event.winner.value,
    }


def transition_projection(
    previous,
    actor: Color,
    action: Mapping[str, object],
    transition,
) -> dict[str, object]:
    if not transition.accepted:
        return {
            "accepted": False,
            "action": dict(action),
            "atomicEvent": None,
            "atomicSnapshot": None,
            "candidateActor": actor.value,
            "errorCode": transition.rejection_code.value,
            "positionalSuperkoAppends": 0,
            "settlement": None,
            "status": "REJECTED",
            "terminalEvent": None,
            "transitionKind": "REJECTED",
        }
    return {
        "accepted": True,
        "action": dict(action),
        "atomicEvent": _atomic_event(transition.atomic_event, action),
        "atomicSnapshot": _atomic_snapshot(previous, transition),
        "candidateActor": actor.value,
        "errorCode": None,
        "positionalSuperkoAppends": (
            len(transition.state.psk_history) - len(previous.psk_history)
        ),
        "settlement": _settlement(transition),
        "status": "ACCEPTED",
        "terminalEvent": (
            _terminal_event(transition.terminal_event)
            if transition.terminal_event is not None
            else None
        ),
        "transitionKind": "ATOMIC_ACTION",
    }


def oracle_episode_response(
    request: object, *, deadline: float | None = None
) -> dict[str, object]:
    _check_deadline(deadline, "Python Eightway oracle request validation")
    frame = validate_episode_request(request)
    state = new_game(_oracle_config(frame["initialQuotas"], frame["boardSize"]))
    observations = []
    for step_index, step in enumerate(frame["steps"], start=1):
        _check_deadline(deadline, "Python Eightway oracle execution")
        previous = state
        actor = Color(step["candidateActor"])
        transition = _apply_v3_adapter(state, actor, step["action"])
        state = transition.state
        projected = transition_projection(previous, actor, step["action"], transition)
        observations.append(
            {"state": state_projection(state), "stepIndex": step_index, "transition": projected}
        )
    return {
        "episodeId": frame["episodeId"],
        "initialState": state_projection(
            new_game(_oracle_config(frame["initialQuotas"], frame["boardSize"]))
        ),
        "observations": observations,
        "protocolVersion": PROTOCOL_VERSION,
    }


def _validate_shape(
    value: object,
    template: object,
    context: str,
    *,
    deadline: float | None = None,
) -> None:
    _check_deadline(deadline, "Eightway response shape validation")
    if template is None:
        if value is not None:
            raise ProtocolError(f"{context} must be null")
        return
    if type(value) is not type(template):
        raise ProtocolError(
            f"{context} type differs: {type(value).__name__} != {type(template).__name__}"
        )
    if type(template) is dict:
        expected = set(template)
        actual = set(value)
        if actual != expected:
            raise ProtocolError(
                f"{context} fields differ: missing={sorted(expected - actual)}, "
                f"unknown={sorted(actual - expected, key=repr)}"
            )
        for key in template:
            _validate_shape(
                value[key], template[key], f"{context}.{key}", deadline=deadline
            )
    elif type(template) is list:
        if len(value) != len(template):
            raise ProtocolError(
                f"{context} length differs: {len(value)} != {len(template)}"
            )
        for index, (item, item_template) in enumerate(zip(value, template)):
            _validate_shape(
                item, item_template, f"{context}[{index}]", deadline=deadline
            )


def _derive_v3_groups(
    state: Mapping[str, object],
    context: str,
    *,
    allow_zero_liberty: bool = False,
) -> list[dict[str, object]]:
    board_size = state["boardSize"]
    point_count = board_size * board_size
    occupied_by_color = {
        "BLACK": list(state["occupancy"]["black"]),
        "WHITE": list(state["occupancy"]["white"]),
    }
    for color, points in occupied_by_color.items():
        if points != sorted(points) or len(points) != len(set(points)):
            raise ProtocolError(f"{context} {color} occupancy is not sorted and unique")
        if any(point < 0 or point >= point_count for point in points):
            raise ProtocolError(f"{context} {color} occupancy is out of range")
    if set(occupied_by_color["BLACK"]) & set(occupied_by_color["WHITE"]):
        raise ProtocolError(f"{context} occupancy colors overlap")
    occupied_sets = {
        color: set(points) for color, points in occupied_by_color.items()
    }
    occupied = occupied_sets["BLACK"] | occupied_sets["WHITE"]
    immortal_by_color = {"BLACK": set(), "WHITE": set()}
    eightway_by_color = {"BLACK": set(), "WHITE": set()}
    for entry in state["ledger"]:
        if (
            entry["kind"] in ("IMMORTAL", "EIGHTWAY")
            and entry["abilityState"] == "ARMED"
            and entry["stoneState"] == "ON_BOARD"
            and not entry["tombstone"]
            and entry["sourcePoint"] in occupied_sets[entry["owner"]]
        ):
            target = (
                immortal_by_color
                if entry["kind"] == "IMMORTAL"
                else eightway_by_color
            )
            target[entry["owner"]].add(entry["sourcePoint"])

    def neighbors(point: int, include_diagonal: bool = False) -> set[int]:
        x = point % board_size
        y = point // board_size
        result = set()
        offsets = [(0, -1), (-1, 0), (1, 0), (0, 1)]
        if include_diagonal:
            offsets.extend(((-1, -1), (1, -1), (-1, 1), (1, 1)))
        for dx, dy in offsets:
            nx = x + dx
            ny = y + dy
            if 0 <= nx < board_size and 0 <= ny < board_size:
                result.add(ny * board_size + nx)
        return result

    groups = []
    for color in ("BLACK", "WHITE"):
        remaining = set(occupied_sets[color])
        while remaining:
            start = min(remaining)
            component = set()
            frontier = [start]
            while frontier:
                point = frontier.pop()
                if point in component:
                    continue
                component.add(point)
                for other in sorted(occupied_sets[color] - component):
                    delta_x = abs((point % board_size) - (other % board_size))
                    delta_y = abs((point // board_size) - (other // board_size))
                    orthogonal = delta_x + delta_y == 1
                    diagonal = delta_x == 1 and delta_y == 1
                    if orthogonal or (
                        diagonal
                        and (
                            point in eightway_by_color[color]
                            or other in eightway_by_color[color]
                        )
                    ):
                        frontier.append(other)
            remaining -= component
            liberties = set()
            for point in component:
                liberties.update(
                    neighbors(
                        point,
                        include_diagonal=point in eightway_by_color[color],
                    )
                    - occupied
                )
            immortal_anchors = sorted(component & immortal_by_color[color])
            eightway_anchors = sorted(component & eightway_by_color[color])
            protected = bool(immortal_anchors)
            if not liberties and not protected and not allow_zero_liberty:
                raise ProtocolError(f"{context} contains an unprotected zero-liberty group")
            groups.append(
                {
                    "color": color,
                    "eightwayAnchors": eightway_anchors,
                    "immortalAnchors": immortal_anchors,
                    "liberties": sorted(liberties),
                    "protected": protected,
                    "stones": sorted(component),
                }
            )
    groups.sort(key=lambda group: group["stones"][0])
    return groups


def _derive_terminal_score(state: Mapping[str, object], context: str) -> dict[str, object]:
    board_size = state["boardSize"]
    black = set(state["occupancy"]["black"])
    white = set(state["occupancy"]["white"])
    occupied = black | white

    def neighbors(point: int) -> set[int]:
        x = point % board_size
        y = point // board_size
        result = set()
        for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
            nx = x + dx
            ny = y + dy
            if 0 <= nx < board_size and 0 <= ny < board_size:
                result.add(ny * board_size + nx)
        return result

    black_area = len(black)
    white_area = len(white)
    remaining = set(range(board_size * board_size)) - occupied
    while remaining:
        start = min(remaining)
        region = set()
        border_colors = set()
        frontier = [start]
        while frontier:
            point = frontier.pop()
            if point in region:
                continue
            region.add(point)
            for neighbor in neighbors(point):
                if neighbor in black:
                    border_colors.add("BLACK")
                elif neighbor in white:
                    border_colors.add("WHITE")
                elif neighbor not in region:
                    frontier.append(neighbor)
        remaining -= region
        if border_colors == {"BLACK"}:
            black_area += len(region)
        elif border_colors == {"WHITE"}:
            white_area += len(region)
    black_numerator = 2 * black_area
    white_numerator = 2 * white_area + 15
    margin = abs(black_numerator - white_numerator)
    if black_numerator == white_numerator:
        raise ProtocolError(f"{context} official half-point komi produced a tie")
    return {
        "black": {"denominator": 2, "numerator": black_numerator},
        "margin": {"denominator": 2, "numerator": margin},
        "white": {"denominator": 2, "numerator": white_numerator},
    }


def _validate_state_invariants(state: Mapping[str, object], context: str) -> None:
    if state["eventLogLength"] != state["logPosition"]:
        raise ProtocolError(f"{context} eventLogLength differs from logPosition")
    if state["revision"] != state["atomicActionCount"]:
        raise ProtocolError(f"{context} revision differs from atomicActionCount")
    expected_log = (
        state["atomicActionCount"]
        + state["settledLedgerCount"]
        + state["stableTerminalEventCount"]
    )
    if state["logPosition"] != expected_log:
        raise ProtocolError(f"{context} event counter formula differs")
    history = state["pskHistory"]
    if not history or history[0] != {"black": [], "white": []}:
        raise ProtocolError(f"{context} lacks the frozen empty PSK entry zero")
    if len(history) != state["eventLogLength"] + 1:
        raise ProtocolError(f"{context} PSK length formula differs")
    if history[-1] != state["occupancy"]:
        raise ProtocolError(f"{context} current occupancy differs from the PSK suffix")
    if state["phase"] == "TERMINAL":
        if state["actor"] is not None or not state["terminal"]["ended"]:
            raise ProtocolError(f"{context} terminal control state differs")
    elif state["actor"] not in ("BLACK", "WHITE") or state["terminal"]["ended"]:
        raise ProtocolError(f"{context} nonterminal control state differs")
    if state["settlementCompleted"] != (state["phase"] != "COLLAPSE_PLAY"):
        raise ProtocolError(f"{context} settlementCompleted differs from phase")
    ledger = state["ledger"]
    ledger_ids: set[str] = set()
    ledger_by_id: dict[str, Mapping[str, object]] = {}
    used_from_ledger = {
        color: {kind: 0 for kind in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY")}
        for color in ("BLACK", "WHITE")
    }
    previous_logical_order = -1
    for entry_index, entry in enumerate(ledger):
        event_id = entry["eventId"]
        origin = entry["originActionNumber"]
        logical_order = entry["logicalOrder"]
        source_id = entry["sourceStoneId"]
        kind = entry["kind"]
        if event_id in ledger_ids:
            raise ProtocolError(f"{context} duplicates ledger eventId {event_id}")
        if event_id != f"special-{origin}":
            raise ProtocolError(f"{context} ledger eventId is not canonical")
        if logical_order + 1 != origin or logical_order <= previous_logical_order:
            raise ProtocolError(f"{context} ledger logical order differs from action origin")
        if not 1 <= origin <= state["atomicActionCount"]:
            raise ProtocolError(f"{context} ledger origin action is out of range")
        if source_id != f"stone-{origin}":
            raise ProtocolError(f"{context} ledger sourceStoneId is not canonical")
        if kind not in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY"):
            raise ProtocolError(f"{context} ledger kind is not a special action")
        pending = entry["settlementState"] == "PENDING"
        settled = entry["settlementState"] == "SETTLED"
        if not pending and not settled:
            raise ProtocolError(f"{context} ledger settlement lifecycle is unknown")
        if kind == "DOUBLE_START":
            expected_ability = "CONSUMED" if pending else "INACTIVE"
            if entry["abilityState"] != expected_ability or not entry["tombstone"]:
                raise ProtocolError(f"{context} Double ledger lifecycle differs")
        else:
            if pending:
                on_board = entry["stoneState"] == "ON_BOARD"
                expected_ability = "ARMED" if on_board else "INACTIVE"
                if entry["abilityState"] != expected_ability or entry["tombstone"] == on_board:
                    raise ProtocolError(f"{context} pending anchor lifecycle differs")
            elif entry["abilityState"] != "INACTIVE" or not entry["tombstone"]:
                raise ProtocolError(f"{context} settled anchor lifecycle differs")
        if state["settlementCompleted"] != settled:
            raise ProtocolError(f"{context} ledger settlement state differs from phase")
        ledger_ids.add(event_id)
        ledger_by_id[event_id] = entry
        used_from_ledger[entry["owner"]][kind] += 1
        previous_logical_order = logical_order

    for color in ("BLACK", "WHITE"):
        for kind in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY"):
            if state["usedQuotas"][color][kind] != used_from_ledger[color][kind]:
                raise ProtocolError(f"{context} used quota differs from ledger count")
            if (
                state["initialQuotas"][color][kind]
                != state["remainingQuotas"][color][kind]
                + state["usedQuotas"][color][kind]
                + state["expiredQuotas"][color][kind]
            ):
                raise ProtocolError(f"{context} quota buckets do not conserve")

    stones_by_source: dict[str, Mapping[str, object]] = {}
    occupied_by_color = {
        "BLACK": set(state["occupancy"]["black"]),
        "WHITE": set(state["occupancy"]["white"]),
    }
    occupied_points: set[int] = set()
    for stone in state["stones"]:
        point = stone["point"]
        origin = stone["originActionNumber"]
        source_id = stone["sourceId"]
        if point in occupied_points:
            raise ProtocolError(f"{context} duplicates a stone point")
        if source_id in stones_by_source:
            raise ProtocolError(f"{context} duplicates a stone sourceId")
        if source_id != f"stone-{origin}" or not 1 <= origin <= state["atomicActionCount"]:
            raise ProtocolError(f"{context} stone source identity is not canonical")
        if point not in occupied_by_color[stone["color"]]:
            raise ProtocolError(f"{context} stone source differs from occupancy")
        special_event_id = stone["specialEventId"]
        if special_event_id is None:
            if stone["originKind"] != "NORMAL":
                raise ProtocolError(f"{context} ordinary stone origin kind differs")
        else:
            entry = ledger_by_id.get(special_event_id)
            if entry is None:
                raise ProtocolError(f"{context} stone references an unknown special event")
            if (
                entry["sourceStoneId"] != source_id
                or entry["sourcePoint"] != point
                or entry["owner"] != stone["color"]
                or entry["kind"] != stone["originKind"]
                or entry["originActionNumber"] != origin
                or entry["stoneState"] != "ON_BOARD"
            ):
                raise ProtocolError(f"{context} stone and ledger source linkage differs")
        occupied_points.add(point)
        stones_by_source[source_id] = stone
    stone_points = [stone["point"] for stone in state["stones"]]
    if stone_points != sorted(stone_points):
        raise ProtocolError(f"{context} source-aware stones are not point ordered")
    if occupied_points != occupied_by_color["BLACK"] | occupied_by_color["WHITE"]:
        raise ProtocolError(f"{context} source-aware stones do not exactly cover occupancy")
    for entry in ledger:
        source = stones_by_source.get(entry["sourceStoneId"])
        if entry["stoneState"] == "ON_BOARD":
            if source is None:
                raise ProtocolError(f"{context} on-board ledger source stone is missing")
        elif source is not None:
            raise ProtocolError(f"{context} captured ledger source remains on board")

    pending_double = state["pendingDouble"]
    if pending_double is not None:
        entry = ledger_by_id.get(pending_double["eventId"])
        if (
            entry is None
            or entry["kind"] != "DOUBLE_START"
            or entry["owner"] != pending_double["owner"]
            or entry["originActionNumber"] != pending_double["startActionNumber"]
            or entry["settlementState"] != "PENDING"
        ):
            raise ProtocolError(f"{context} pending Double linkage differs")

    expected_groups = _derive_v3_groups(state, context)
    expected_armed = sorted(
        anchor
        for group in expected_groups
        for anchor in group["immortalAnchors"]
    )
    if state["immortalAnchors"] != expected_armed:
        raise ProtocolError(f"{context} global Immortal anchors differ from topology")
    expected_eightway = sorted(
        anchor
        for group in expected_groups
        for anchor in group["eightwayAnchors"]
    )
    if state["eightwayAnchors"] != expected_eightway:
        raise ProtocolError(f"{context} global Eightway anchors differ from topology")
    if state["groups"] != expected_groups:
        raise ProtocolError(
            f"{context} group color, connectivity, liberties, anchors, protection, or order differs"
        )
    if state["phase"] == "TERMINAL" and state["terminal"]["reason"] == "SCORE":
        expected_score = _derive_terminal_score(state, context)
        if state["terminal"]["score"] != expected_score:
            raise ProtocolError(f"{context} terminal Chinese-area score differs")
        black = expected_score["black"]["numerator"]
        white = expected_score["white"]["numerator"]
        expected_winner = "BLACK" if black > white else "WHITE"
        expected_loser = "WHITE" if expected_winner == "BLACK" else "BLACK"
        if (
            state["terminal"]["winner"] != expected_winner
            or state["terminal"]["loser"] != expected_loser
        ):
            raise ProtocolError(f"{context} terminal winner/loser differs from score")


_LEDGER_IDENTITY_FIELDS = (
    "eventId",
    "kind",
    "logicalOrder",
    "originActionNumber",
    "owner",
    "sourcePoint",
    "sourceStoneId",
)


def _ledger_identity(entry: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(entry[field] for field in _LEDGER_IDENTITY_FIELDS)


def _validate_accepted_state_lineage(
    previous: Mapping[str, object],
    snapshot: Mapping[str, object],
    state: Mapping[str, object],
    atomic: Mapping[str, object],
    candidate: Mapping[str, object],
    settlement: Mapping[str, object] | None,
    context: str,
) -> None:
    previous_ledger = previous["ledger"]
    snapshot_ledger = snapshot["ledger"]
    state_ledger = state["ledger"]
    previous_identities = [_ledger_identity(entry) for entry in previous_ledger]
    snapshot_identities = [_ledger_identity(entry) for entry in snapshot_ledger]
    state_identities = [_ledger_identity(entry) for entry in state_ledger]
    if snapshot_identities[: len(previous_identities)] != previous_identities:
        raise ProtocolError(f"{context} atomic ledger rewrote its predecessor prefix")
    action_number = atomic["actionNumber"]
    decoded = decode_action_v1(candidate, snapshot["boardSize"])
    previous_stones = {stone["sourceId"]: stone for stone in previous["stones"]}
    for stone in snapshot["stones"]:
        if stone["originActionNumber"] < action_number:
            predecessor = previous_stones.get(stone["sourceId"])
            if predecessor != stone:
                raise ProtocolError(f"{context} atomic snapshot rewrote or invented an old stone source")
    new_stones = [
        stone
        for stone in snapshot["stones"]
        if stone["originActionNumber"] == action_number
    ]
    if candidate["kind"] == "PASS":
        if new_stones:
            raise ProtocolError(f"{context} PASS invented a stone source")
    else:
        expected_special_id = (
            f"special-{action_number}"
            if candidate["kind"] in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY")
            else None
        )
        if len(new_stones) != 1:
            raise ProtocolError(f"{context} point action lacks one canonical new stone source")
        new_stone = new_stones[0]
        if (
            new_stone["point"] != decoded.board_index
            or new_stone["color"] != atomic["actor"]
            or new_stone["originKind"] != candidate["kind"]
            or new_stone["sourceId"] != f"stone-{action_number}"
            or new_stone["specialEventId"] != expected_special_id
        ):
            raise ProtocolError(f"{context} new stone source differs from the submitted action")

    special = candidate["kind"] in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY")
    expected_length = len(previous_ledger) + (1 if special else 0)
    if len(snapshot_ledger) != expected_length:
        raise ProtocolError(f"{context} atomic ledger append count differs")
    if special:
        appended = snapshot_ledger[-1]
        if (
            appended["originActionNumber"] != atomic["actionNumber"]
            or appended["kind"] != candidate["kind"]
            or appended["owner"] != atomic["actor"]
        ):
            raise ProtocolError(f"{context} appended special ledger identity differs")
    if state_identities != snapshot_identities:
        raise ProtocolError(f"{context} settlement or terminal state rewrote ledger identity")

    if settlement is None:
        return
    expected_event_ids = [entry["eventId"] for entry in reversed(snapshot_ledger)]
    actual_event_ids = [step["ledgerEventId"] for step in settlement["steps"]]
    if actual_event_ids != expected_event_ids:
        raise ProtocolError(f"{context} settlement steps do not bind the ledger in reverse order")
    working_ledger = copy.deepcopy(snapshot_ledger)
    ledger_by_id = {entry["eventId"]: entry for entry in working_ledger}
    for settlement_step in settlement["steps"]:
        entry = ledger_by_id[settlement_step["ledgerEventId"]]
        if (
            settlement_step["kind"] != entry["kind"]
            or settlement_step["originActionNumber"] != entry["originActionNumber"]
            or settlement_step["owner"] != entry["owner"]
            or settlement_step["sourcePoint"] != entry["sourcePoint"]
        ):
            raise ProtocolError(f"{context} settlement source provenance differs from ledger")
        expected_deactivation = (
            entry["kind"] in ("IMMORTAL", "EIGHTWAY")
            and entry["abilityState"] == "ARMED"
            and entry["stoneState"] == "ON_BOARD"
        )
        if settlement_step["abilityDeactivated"] != expected_deactivation:
            raise ProtocolError(f"{context} settlement ability disposition differs from ledger")
        entry["abilityState"] = "INACTIVE"
        entry["settlementState"] = "SETTLED"
        entry["tombstone"] = True
        removed = {
            ("BLACK" if key == "black" else "WHITE", point)
            for batch in settlement_step["removalBatches"]
            for key in ("black", "white")
            for point in batch[key]
        }
        for source in working_ledger:
            if (
                source["stoneState"] == "ON_BOARD"
                and (source["owner"], source["sourcePoint"]) in removed
            ):
                source["stoneState"] = "CAPTURED"
                if source["kind"] in ("IMMORTAL", "EIGHTWAY"):
                    source["abilityState"] = "INACTIVE"
                    source["tombstone"] = True


def _validate_complete_accepted_progression(
    previous: Mapping[str, object],
    snapshot: Mapping[str, object],
    state: Mapping[str, object],
    atomic: Mapping[str, object],
    candidate: Mapping[str, object],
    settlement: Mapping[str, object] | None,
    terminal_event: Mapping[str, object] | None,
    context: str,
) -> None:
    actor = previous["actor"]
    if actor not in ("BLACK", "WHITE") or atomic["actor"] != actor:
        raise ProtocolError(f"{context} accepted actor differs from previous control state")
    opponent = "WHITE" if actor == "BLACK" else "BLACK"
    action_number = previous["atomicActionCount"] + 1
    if atomic["actionNumber"] != action_number:
        raise ProtocolError(f"{context} atomic action number does not advance by one")
    for field in ("boardSize", "threshold", "initialQuotas"):
        if snapshot[field] != previous[field] or state[field] != previous[field]:
            raise ProtocolError(f"{context} immutable configuration changed")

    decoded = decode_action_v1(candidate, previous["boardSize"])
    previous_occupancy = {
        "BLACK": set(previous["occupancy"]["black"]),
        "WHITE": set(previous["occupancy"]["white"]),
    }
    captured = {
        "BLACK": set(atomic["captured"]["black"]),
        "WHITE": set(atomic["captured"]["white"]),
    }
    if captured[actor] or not captured[opponent].issubset(previous_occupancy[opponent]):
        raise ProtocolError(f"{context} atomic captures differ from previous occupancy")
    expected_atomic_occupancy = {
        "BLACK": set(previous_occupancy["BLACK"]),
        "WHITE": set(previous_occupancy["WHITE"]),
    }
    expected_atomic_occupancy[opponent] -= captured[opponent]
    if candidate["kind"] == "PASS":
        if captured["BLACK"] or captured["WHITE"]:
            raise ProtocolError(f"{context} PASS captured stones")
    else:
        target = decoded.board_index
        if target in previous_occupancy["BLACK"] or target in previous_occupancy["WHITE"]:
            raise ProtocolError(f"{context} accepted point action targeted occupancy")
        expected_atomic_occupancy[actor].add(target)
    expected_atomic_json = {
        "black": sorted(expected_atomic_occupancy["BLACK"]),
        "white": sorted(expected_atomic_occupancy["WHITE"]),
    }
    if atomic["stableOccupancy"] != expected_atomic_json or snapshot["occupancy"] != expected_atomic_json:
        raise ProtocolError(f"{context} atomic occupancy progression differs")

    captured_points = captured["BLACK"] | captured["WHITE"]
    expected_stones = [
        copy.deepcopy(stone)
        for stone in previous["stones"]
        if stone["point"] not in captured_points
    ]
    if candidate["kind"] != "PASS":
        expected_stones.append(
            {
                "color": actor,
                "originActionNumber": action_number,
                "originKind": candidate["kind"],
                "point": decoded.board_index,
                "sourceId": f"stone-{action_number}",
                "specialEventId": (
                    f"special-{action_number}"
                    if candidate["kind"] in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY")
                    else None
                ),
            }
        )
    expected_stones.sort(key=lambda stone: stone["point"])
    if snapshot["stones"] != expected_stones:
        raise ProtocolError(f"{context} atomic source-aware stones differ")

    expected_ledger = copy.deepcopy(previous["ledger"])
    for entry in expected_ledger:
        owner_key = "black" if entry["owner"] == "BLACK" else "white"
        if entry["stoneState"] == "ON_BOARD" and entry["sourcePoint"] in atomic["captured"][owner_key]:
            entry["stoneState"] = "CAPTURED"
            if entry["kind"] in ("IMMORTAL", "EIGHTWAY"):
                entry["abilityState"] = "INACTIVE"
                entry["tombstone"] = True
    if candidate["kind"] in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY"):
        expected_ledger.append(
            {
                "abilityState": (
                    "CONSUMED" if candidate["kind"] == "DOUBLE_START" else "ARMED"
                ),
                "eventId": f"special-{action_number}",
                "kind": candidate["kind"],
                "logicalOrder": action_number - 1,
                "originActionNumber": action_number,
                "owner": actor,
                "settlementState": "PENDING",
                "sourcePoint": decoded.board_index,
                "sourceStoneId": f"stone-{action_number}",
                "stoneState": "ON_BOARD",
                "tombstone": candidate["kind"] == "DOUBLE_START",
            }
        )
    if snapshot["ledger"] != expected_ledger:
        raise ProtocolError(f"{context} atomic ledger lifecycle progression differs")

    expected_atomic_history = list(previous["pskHistory"]) + [
        copy.deepcopy(atomic["stableOccupancy"])
    ]
    if snapshot["pskHistory"] != expected_atomic_history:
        raise ProtocolError(f"{context} atomic PSK history is not one exact append")
    if (
        snapshot["atomicActionCount"] != action_number
        or snapshot["revision"] != previous["revision"] + 1
        or snapshot["logPosition"] != previous["logPosition"] + 1
        or snapshot["eventLogLength"] != previous["eventLogLength"] + 1
        or snapshot["settledLedgerCount"] != previous["settledLedgerCount"]
        or snapshot["stableTerminalEventCount"] != previous["stableTerminalEventCount"]
    ):
        raise ProtocolError(f"{context} atomic counters do not advance exactly once")
    if (
        snapshot["phase"] != previous["phase"]
        or snapshot["settlementCompleted"] != previous["settlementCompleted"]
        or snapshot["terminal"] != previous["terminal"]
        or snapshot["expiredQuotas"] != previous["expiredQuotas"]
    ):
        raise ProtocolError(f"{context} atomic control metadata changed unexpectedly")

    expected_remaining = copy.deepcopy(previous["remainingQuotas"])
    expected_used = copy.deepcopy(previous["usedQuotas"])
    if candidate["kind"] in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY"):
        expected_remaining[actor][candidate["kind"]] -= 1
        expected_used[actor][candidate["kind"]] += 1
    if snapshot["remainingQuotas"] != expected_remaining or snapshot["usedQuotas"] != expected_used:
        raise ProtocolError(f"{context} atomic quota progression differs")

    expected_passes = previous["consecutivePasses"] + 1 if candidate["kind"] == "PASS" else 0
    if candidate["kind"] == "DOUBLE_START":
        expected_atomic_actor = actor
        expected_pending = {
            "eventId": f"special-{action_number}",
            "owner": actor,
            "startActionNumber": action_number,
        }
    else:
        expected_atomic_actor = opponent
        expected_pending = None
    if (
        snapshot["actor"] != expected_atomic_actor
        or snapshot["pendingDouble"] != expected_pending
        or snapshot["consecutivePasses"] != expected_passes
    ):
        raise ProtocolError(f"{context} atomic actor/pass/pending progression differs")
    if previous["pendingDouble"] is not None and candidate["kind"] not in ("NORMAL", "PASS"):
        raise ProtocolError(f"{context} accepted forbidden pending-Double continuation")

    expected_settlement_reason = None
    if previous["phase"] == "COLLAPSE_PLAY":
        if action_number == previous["threshold"]:
            expected_settlement_reason = "THRESHOLD"
        elif action_number < previous["threshold"] and expected_passes == 2:
            expected_settlement_reason = "PRE_THRESHOLD_TWO_PASSES"
    if expected_settlement_reason is None:
        if settlement is not None:
            raise ProtocolError(f"{context} emitted settlement without a frozen trigger")
    else:
        if settlement is None or settlement["triggerReason"] != expected_settlement_reason:
            raise ProtocolError(f"{context} settlement trigger reason differs")
        if (
            settlement["handoffActor"] != expected_atomic_actor
            or settlement["handoffActor"] != snapshot["actor"]
        ):
            raise ProtocolError(f"{context} settlement handoff differs from atomic control")
    expected_scoring_terminal = (
        previous["phase"] == "ORDINARY_PLAY"
        and candidate["kind"] == "PASS"
        and expected_passes == 2
    )
    if (terminal_event is not None) != expected_scoring_terminal:
        raise ProtocolError(f"{context} scoring terminal trigger differs")
    if settlement is not None and terminal_event is not None:
        raise ProtocolError(f"{context} cannot settle and score terminally in one action")

    expected_history = list(previous["pskHistory"]) + [
        copy.deepcopy(atomic["stableOccupancy"])
    ]
    if settlement is not None:
        expected_history.extend(
            copy.deepcopy(step["stableOccupancy"])
            for step in settlement["steps"]
        )
    if terminal_event is not None:
        expected_history.append(copy.deepcopy(terminal_event["stableOccupancy"]))
    if state["pskHistory"] != expected_history:
        raise ProtocolError(f"{context} resulting PSK history rewrote or omitted an append")
    append_count = 1 + (
        len(settlement["steps"]) if settlement is not None else 0
    ) + (1 if terminal_event is not None else 0)
    if (
        state["atomicActionCount"] != action_number
        or state["revision"] != previous["revision"] + 1
        or state["logPosition"] != previous["logPosition"] + append_count
        or state["eventLogLength"] != previous["eventLogLength"] + append_count
        or state["settledLedgerCount"]
        != previous["settledLedgerCount"]
        + (len(settlement["steps"]) if settlement is not None else 0)
        or state["stableTerminalEventCount"]
        != previous["stableTerminalEventCount"] + (1 if terminal_event is not None else 0)
    ):
        raise ProtocolError(f"{context} resulting counters differ from emitted appends")

    if settlement is not None:
        expected_final_ledger = copy.deepcopy(snapshot["ledger"])
        ledger_by_id = {entry["eventId"]: entry for entry in expected_final_ledger}
        working_occupancy = {
            "BLACK": set(snapshot["occupancy"]["black"]),
            "WHITE": set(snapshot["occupancy"]["white"]),
        }
        removed_points: set[int] = set()
        for settlement_step in settlement["steps"]:
            entry = ledger_by_id[settlement_step["ledgerEventId"]]
            expected_deactivation = (
                entry["kind"] in ("IMMORTAL", "EIGHTWAY")
                and entry["abilityState"] == "ARMED"
                and entry["stoneState"] == "ON_BOARD"
            )
            entry["abilityState"] = "INACTIVE"
            entry["settlementState"] = "SETTLED"
            entry["tombstone"] = True
            expected_batches = []
            while True:
                closure_projection = dict(snapshot)
                closure_projection["occupancy"] = {
                    "black": sorted(working_occupancy["BLACK"]),
                    "white": sorted(working_occupancy["WHITE"]),
                }
                closure_projection["ledger"] = expected_final_ledger
                closure_groups = _derive_v3_groups(
                    closure_projection,
                    f"{context} settlement closure",
                    allow_zero_liberty=True,
                )
                batch = {"black": [], "white": []}
                for group in closure_groups:
                    if not group["liberties"] and not group["protected"]:
                        key = "black" if group["color"] == "BLACK" else "white"
                        batch[key].extend(group["stones"])
                batch["black"].sort()
                batch["white"].sort()
                if not batch["black"] and not batch["white"]:
                    break
                expected_batches.append(batch)
                for color, key in (("BLACK", "black"), ("WHITE", "white")):
                    batch_points = set(batch[key])
                    working_occupancy[color] -= batch_points
                    removed_points |= batch_points
                    for source in expected_final_ledger:
                        if (
                            source["owner"] == color
                            and source["stoneState"] == "ON_BOARD"
                            and source["sourcePoint"] in batch_points
                        ):
                            source["stoneState"] = "CAPTURED"
                            if source["kind"] in ("IMMORTAL", "EIGHTWAY"):
                                source["abilityState"] = "INACTIVE"
                                source["tombstone"] = True
            if settlement_step["abilityDeactivated"] != expected_deactivation:
                raise ProtocolError(f"{context} settlement deactivation differs")
            if settlement_step["removalBatches"] != expected_batches:
                raise ProtocolError(f"{context} settlement fixed-point closure differs")
            if settlement_step["noOp"] != (
                not expected_deactivation and not expected_batches
            ):
                raise ProtocolError(f"{context} settlement no-op classification differs")
            expected_step_occupancy = {
                "black": sorted(working_occupancy["BLACK"]),
                "white": sorted(working_occupancy["WHITE"]),
            }
            if settlement_step["stableOccupancy"] != expected_step_occupancy:
                raise ProtocolError(f"{context} settlement batch progression differs")
        expected_final_stones = [
            stone for stone in snapshot["stones"] if stone["point"] not in removed_points
        ]
        expected_final_occupancy = {
            "black": sorted(working_occupancy["BLACK"]),
            "white": sorted(working_occupancy["WHITE"]),
        }
        zero = {"IMMORTAL": 0, "DOUBLE_START": 0, "EIGHTWAY": 0}
        expected_expired = copy.deepcopy(snapshot["expiredQuotas"])
        for color in ("BLACK", "WHITE"):
            for kind in ("IMMORTAL", "DOUBLE_START", "EIGHTWAY"):
                expected_expired[color][kind] += snapshot["remainingQuotas"][color][kind]
        if (
            state["phase"] != "ORDINARY_PLAY"
            or not state["settlementCompleted"]
            or state["actor"] != settlement["handoffActor"]
            or state["pendingDouble"] is not None
            or state["consecutivePasses"] != 0
            or state["terminal"] != previous["terminal"]
            or state["remainingQuotas"] != {"BLACK": zero, "WHITE": zero}
            or state["usedQuotas"] != snapshot["usedQuotas"]
            or state["expiredQuotas"] != expected_expired
            or state["ledger"] != expected_final_ledger
            or state["stones"] != expected_final_stones
            or state["occupancy"] != expected_final_occupancy
        ):
            raise ProtocolError(f"{context} settlement result control/quota progression differs")
    elif terminal_event is not None:
        score = _derive_terminal_score(snapshot, context)
        black_numerator = score["black"]["numerator"]
        white_numerator = score["white"]["numerator"]
        winner = "BLACK" if black_numerator > white_numerator else "WHITE"
        loser = "WHITE" if winner == "BLACK" else "BLACK"
        expected_terminal_state = copy.deepcopy(snapshot)
        expected_terminal_state["actor"] = None
        expected_terminal_state["phase"] = "TERMINAL"
        expected_terminal_state["logPosition"] += 1
        expected_terminal_state["eventLogLength"] += 1
        expected_terminal_state["stableTerminalEventCount"] += 1
        expected_terminal_state["pskHistory"].append(
            copy.deepcopy(snapshot["occupancy"])
        )
        expected_terminal_state["terminal"] = {
            "ended": True,
            "loser": loser,
            "reason": "SCORE",
            "score": score,
            "winner": winner,
        }
        expected_terminal_event = {
            "eventId": f"terminal-{expected_terminal_state['logPosition']}",
            "loser": loser,
            "pskHistoryIndex": len(expected_terminal_state["pskHistory"]) - 1,
            "reason": "SCORE",
            "stableOccupancy": copy.deepcopy(snapshot["occupancy"]),
            "winner": winner,
        }
        if terminal_event != expected_terminal_event:
            raise ProtocolError(f"{context} terminal event or score progression differs")
        if state != expected_terminal_state:
            raise ProtocolError(
                f"{context} terminal result changed fields outside frozen terminal progression"
            )
    else:
        if state != snapshot:
            raise ProtocolError(
                f"{context} non-settling nonterminal result must equal atomicSnapshot exactly"
            )


def _fresh_state_projection(request: Mapping[str, object]) -> dict[str, object]:
    board_size = request["boardSize"]
    initial_quotas = copy.deepcopy(request["initialQuotas"])
    zero = {"IMMORTAL": 0, "DOUBLE_START": 0, "EIGHTWAY": 0}
    empty = {"black": [], "white": []}
    return {
        "actor": "BLACK",
        "atomicActionCount": 0,
        "boardSize": board_size,
        "consecutivePasses": 0,
        "eventLogLength": 0,
        "expiredQuotas": {
            "BLACK": copy.deepcopy(zero),
            "WHITE": copy.deepcopy(zero),
        },
        "groups": [],
        "eightwayAnchors": [],
        "immortalAnchors": [],
        "initialQuotas": initial_quotas,
        "ledger": [],
        "logPosition": 0,
        "occupancy": copy.deepcopy(empty),
        "pendingDouble": None,
        "phase": "COLLAPSE_PLAY",
        "pskHistory": [copy.deepcopy(empty)],
        "remainingQuotas": copy.deepcopy(initial_quotas),
        "revision": 0,
        "settledLedgerCount": 0,
        "settlementCompleted": False,
        "stableTerminalEventCount": 0,
        "stones": [],
        "terminal": {"ended": False},
        "threshold": (150 * board_size * board_size + 180) // 361,
        "usedQuotas": {
            "BLACK": copy.deepcopy(zero),
            "WHITE": copy.deepcopy(zero),
        },
    }


def validate_episode_response(
    response: object,
    request: Mapping[str, object],
    expected_shape: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> Mapping[str, object]:
    _check_deadline(deadline, "Eightway response validation")
    _validate_shape(response, expected_shape, "episode response", deadline=deadline)
    if response["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError("response protocolVersion differs")
    if response["episodeId"] != request["episodeId"]:
        raise ProtocolError("response episodeId differs")
    if len(response["observations"]) != len(request["steps"]):
        raise ProtocolError("response observation count differs")
    expected_initial = _fresh_state_projection(request)
    if response["initialState"] != expected_initial:
        raise ProtocolError("initialState differs from the canonical request-derived fresh state")
    _validate_state_invariants(response["initialState"], "initialState")
    previous_state = response["initialState"]
    for index, (observation, step) in enumerate(
        zip(response["observations"], request["steps"]), start=1
    ):
        _check_deadline(deadline, "Eightway response validation")
        if observation["stepIndex"] != index:
            raise ProtocolError(f"observation {index} stepIndex differs")
        transition = observation["transition"]
        state = observation["state"]
        _validate_state_invariants(state, f"observation {index}.state")
        if transition["action"] != step["action"] or transition["candidateActor"] != step["candidateActor"]:
            raise ProtocolError(f"observation {index} candidate echo differs")
        status = transition["status"]
        if status == "ACCEPTED":
            if (
                not transition["accepted"]
                or transition["transitionKind"] != "ATOMIC_ACTION"
                or transition["errorCode"] is not None
                or transition["atomicEvent"] is None
                or transition["atomicSnapshot"] is None
            ):
                raise ProtocolError(f"observation {index} accepted classification differs")
            snapshot = transition["atomicSnapshot"]
            _validate_state_invariants(snapshot, f"observation {index}.atomicSnapshot")
            atomic = transition["atomicEvent"]
            if (
                atomic["eventId"] != f"action-{atomic['actionNumber']}"
                or atomic["actionNumber"] != snapshot["atomicActionCount"]
                or atomic["actor"] != step["candidateActor"]
                or atomic["action"] != step["action"]
                or atomic["stableOccupancy"] != snapshot["occupancy"]
                or atomic["stableStones"] != snapshot["stones"]
                or atomic["pskHistoryIndex"] != len(previous_state["pskHistory"])
                or snapshot["pskHistory"][-1] != atomic["stableOccupancy"]
            ):
                raise ProtocolError(f"observation {index} atomic snapshot binding differs")
            expected_appends = len(state["pskHistory"]) - len(previous_state["pskHistory"])
            if transition["positionalSuperkoAppends"] != expected_appends:
                raise ProtocolError(f"observation {index} PSK append count differs")
            settlement = transition["settlement"]
            if settlement is not None:
                if settlement["triggerReason"] not in (
                    "THRESHOLD",
                    "PRE_THRESHOLD_TWO_PASSES",
                ):
                    raise ProtocolError(f"observation {index} settlement reason differs")
                if settlement["handoffActor"] != state["actor"]:
                    raise ProtocolError(f"observation {index} settlement handoff differs")
                for step_offset, settlement_step in enumerate(settlement["steps"]):
                    if (
                        settlement_step["stepIndex"] != step_offset
                        or settlement_step["pskHistoryIndex"]
                        != atomic["pskHistoryIndex"] + step_offset + 1
                    ):
                        raise ProtocolError(
                            f"observation {index} settlement step indexing differs"
                        )
                    has_removal = bool(settlement_step["removalBatches"])
                    if settlement_step["noOp"] == (
                        settlement_step["abilityDeactivated"] or has_removal
                    ):
                        raise ProtocolError(
                            f"observation {index} settlement noOp classification differs"
                        )
                if settlement["steps"]:
                    if settlement["steps"][-1]["stableOccupancy"] != state["occupancy"]:
                        raise ProtocolError(
                            f"observation {index} settlement suffix occupancy differs"
                        )
                elif atomic["stableOccupancy"] != state["occupancy"]:
                    raise ProtocolError(
                        f"observation {index} empty settlement changed occupancy"
                    )
            _validate_accepted_state_lineage(
                previous_state,
                snapshot,
                state,
                atomic,
                step["action"],
                settlement,
                f"observation {index}",
            )
            _validate_complete_accepted_progression(
                previous_state,
                snapshot,
                state,
                atomic,
                step["action"],
                settlement,
                transition["terminalEvent"],
                f"observation {index}",
            )
        elif status == "REJECTED":
            if (
                transition["accepted"]
                or transition["transitionKind"] != "REJECTED"
                or transition["errorCode"] not in SUPPORTED_REJECTION_CODES
            ):
                raise ProtocolError(f"observation {index} rejection vocabulary differs")
            if state != previous_state:
                raise ProtocolError(f"observation {index} rejected candidate mutated state")
        else:
            raise ProtocolError(f"observation {index} status is unknown")
        if status != "ACCEPTED" and any(
            transition[field] is not None
            for field in ("atomicEvent", "atomicSnapshot", "settlement", "terminalEvent")
        ):
            raise ProtocolError(f"observation {index} nonaccepted candidate emitted events")
        if status != "ACCEPTED" and transition["positionalSuperkoAppends"] != 0:
            raise ProtocolError(f"observation {index} nonaccepted candidate appended PSK")
        previous_state = state
    return response


def parse_canonical_response_line(
    line: str,
    request: Mapping[str, object],
    expected_shape: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> Mapping[str, object]:
    _check_deadline(deadline, "Eightway response parsing")
    if not line:
        raise ProtocolError("probe returned an empty response line")
    encoded = line.encode("utf-8", errors="strict")
    if len(encoded) > MAX_RESPONSE_FRAME_BYTES:
        raise ProtocolError("probe response exceeds the 96 MiB response limit")
    try:
        parsed = parse_json_bytes(encoded)
    except ContractError as exc:
        raise ProtocolError(f"probe returned invalid restricted-profile JSON: {exc}") from exc
    _check_deadline(deadline, "Eightway response parsing")
    canonical = canonical_json(parsed)
    _check_deadline(deadline, "Eightway response canonicalization")
    if canonical != line:
        raise ProtocolError("probe response is not canonical restricted-profile JSON")
    return validate_episode_response(
        parsed, request, expected_shape, deadline=deadline
    )


def _digest_record(digest, data: str) -> None:
    encoded = data.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _context(
    manifest: Mapping[str, object],
    request: Mapping[str, object],
    request_line: str,
    prefix_length: int,
) -> str:
    return (
        f"manifest={canonical_json(manifest)}; canonicalRequest={request_line}; "
        f"actionPrefix={canonical_json(request['steps'][:prefix_length])}"
    )


def _probe_failure_context(
    manifest: Mapping[str, object],
    requests: Sequence[Mapping[str, object]],
    request_lines: Sequence[str],
    *,
    response_index: int = 0,
    completed_response_count: int = 0,
) -> str:
    if not requests:
        return (
            f"responseIndex={response_index}; "
            f"completedResponseCount={completed_response_count}; "
            f"manifest={canonical_json(manifest)}; canonicalRequest=null; actionPrefix=[]"
        )
    index = min(max(response_index, 0), len(requests) - 1)
    request = requests[index]
    request_line = (
        request_lines[index]
        if index < len(request_lines)
        else canonical_json(request)
    )
    return (
        f"responseIndex={response_index}; "
        f"completedResponseCount={completed_response_count}; "
        + _context(manifest, request, request_line, len(request["steps"]))
    )


def run_probe_requests(
    probe_path: Path | str,
    requests: Sequence[Mapping[str, object]],
    expected: Sequence[Mapping[str, object]],
    *,
    manifest: Mapping[str, object],
    deadline: float,
) -> tuple[list[Mapping[str, object]], str]:
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
        _check_deadline(deadline, "Eightway probe setup")
        probe = Path(probe_path).expanduser().resolve()
        if not probe.is_file():
            raise ProbeError(f"probe executable does not exist: {probe}")
        for item in requests:
            _check_deadline(deadline, "Eightway probe request serialization")
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
    for index, (request, expected_response, request_line, response_line) in enumerate(
        zip(requests, expected, request_lines, lines)
    ):
        try:
            parsed = parse_canonical_response_line(
                response_line, request, expected_response, deadline=deadline
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
        except (ProtocolError, UnicodeError) as exc:
            raise ProtocolError(
                f"{exc}; responseIndex={index}; "
                + _context(manifest, request, request_line, len(request["steps"]))
            ) from exc
        responses.append(parsed)
        _digest_record(digest, request_line)
        _digest_record(digest, response_line)
    if len(responses) != len(requests):
        raise ProbeError(
            f"validated response count differs: {len(responses)} != {len(requests)}; "
            + _probe_failure_context(
                manifest,
                requests,
                request_lines,
                response_index=len(responses),
                completed_response_count=len(responses),
            )
        )
    return responses, digest.hexdigest()


class EpisodeBuilder:
    def __init__(
        self,
        episode_id: str,
        board_size: int,
        initial_quotas: Mapping[str, object] | None = None,
        *,
        deadline: float | None = None,
    ) -> None:
        self.episode_id = episode_id
        self.board_size = board_size
        self.initial_quotas = copy.deepcopy(initial_quotas or quotas())
        self.state = new_game(_oracle_config(self.initial_quotas, board_size))
        self.steps: list[dict[str, object]] = []
        self.deadline = deadline

    def add(self, actor: Color, action: Mapping[str, object]):
        _check_deadline(self.deadline, "Eightway corpus generation")
        step = {"candidateActor": actor.value, "action": dict(action)}
        decode_action_v1(step["action"], self.board_size)
        self.steps.append(step)
        transition = _apply_v3_adapter(self.state, actor, step["action"])
        if transition is not None:
            self.state = transition.state
        return transition

    def accepted(self, actor: Color, action: Mapping[str, object]):
        transition = self.add(actor, action)
        if transition is None or not transition.accepted:
            raise AssertionError(
                f"curated action was not accepted in {self.episode_id}: {action}"
            )
        return transition

    def request(self) -> dict[str, object]:
        return dict(
            validate_episode_request(
                {
                    "boardSize": self.board_size,
                    "episodeId": self.episode_id,
                    "initialQuotas": copy.deepcopy(self.initial_quotas),
                    "protocolVersion": PROTOCOL_VERSION,
                    "steps": copy.deepcopy(self.steps),
                }
            )
        )


def eightway_immortal_split_request(
    board_size: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    """Reach a protected mixed group whose newest E pop splits and removes E."""

    builder = EpisodeBuilder(episode_id, board_size, deadline=deadline)
    center = board_size // 2
    sequence = (
        (Color.BLACK, ActionKind.IMMORTAL, center - 1, center - 1),
        (Color.WHITE, ActionKind.NORMAL, center, center - 1),
        (Color.BLACK, ActionKind.NORMAL, 0, board_size - 1),
        (Color.WHITE, ActionKind.NORMAL, center - 1, center),
        (Color.BLACK, ActionKind.EIGHTWAY, center, center),
        (Color.WHITE, ActionKind.NORMAL, center + 1, center),
        (Color.BLACK, ActionKind.NORMAL, board_size - 1, board_size - 1),
        (Color.WHITE, ActionKind.NORMAL, center, center + 1),
    )
    for actor, kind, x, y in sequence:
        builder.accepted(actor, board_action_v1(board_size, x, y, kind))
    builder.accepted(Color.BLACK, action_v1(PASS_ACTION_ID))
    settled = builder.accepted(Color.WHITE, action_v1(PASS_ACTION_ID))
    if settled.settlement is None:
        raise AssertionError("Eightway/Immortal split episode did not settle")
    return builder.request()


def _attachment_request(
    *, double_attachment: bool, deadline: float | None = None
) -> dict[str, object]:
    suffix = "double" if double_attachment else "normal"
    builder = EpisodeBuilder(f"curated-protected-{suffix}-attachment-9", 9, deadline=deadline)
    white_points = ((4, 3), (3, 4), (4, 5), (6, 4), (5, 3), (5, 5))
    black_fillers = ((0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (0, 8))
    for black_point, white_point in zip(black_fillers, white_points):
        builder.accepted(Color.BLACK, board_action_v1(9, *black_point))
        builder.accepted(Color.WHITE, board_action_v1(9, *white_point))
    builder.accepted(
        Color.BLACK, board_action_v1(9, 4, 4, ActionKind.IMMORTAL)
    )
    builder.accepted(Color.WHITE, board_action_v1(9, 8, 8))
    kind = ActionKind.DOUBLE_START if double_attachment else ActionKind.NORMAL
    builder.accepted(Color.BLACK, board_action_v1(9, 5, 4, kind))
    if double_attachment:
        builder.accepted(Color.BLACK, action_v1(PASS_ACTION_ID))
    # This opponent point action runs the full capture scan only after the
    # connected Black group is already protected and has zero liberties.
    builder.accepted(Color.WHITE, board_action_v1(9, 7, 8))
    return builder.request()


def _two_anchor_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder(
        "curated-two-anchor-reverse-pop-9",
        9,
        quotas(
            black_immortal=2,
            white_immortal=0,
            black_double=0,
            white_double=0,
            eightway=0,
        ),
        deadline=deadline,
    )
    white_ring = ((4, 3), (3, 4), (4, 5), (5, 3), (6, 4), (5, 5))
    black_fillers = ((0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (0, 8))
    for black_point, white_point in zip(black_fillers, white_ring):
        builder.accepted(Color.BLACK, board_action_v1(9, *black_point))
        builder.accepted(Color.WHITE, board_action_v1(9, *white_point))
    builder.accepted(Color.BLACK, board_action_v1(9, 4, 4, ActionKind.IMMORTAL))
    builder.accepted(Color.WHITE, board_action_v1(9, 8, 8))
    builder.accepted(Color.BLACK, board_action_v1(9, 5, 4, ActionKind.IMMORTAL))
    builder.accepted(Color.WHITE, action_v1(PASS_ACTION_ID))
    builder.accepted(Color.BLACK, action_v1(PASS_ACTION_ID))
    return builder.request()


def _mixed_ledger_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder(
        "curated-mixed-double-immortal-reverse-order-9",
        9,
        quotas(
            black_immortal=2,
            white_immortal=0,
            black_double=0,
            white_double=1,
            eightway=0,
        ),
        deadline=deadline,
    )
    for actor, action in (
        (Color.BLACK, board_action_v1(9, 0, 0, ActionKind.IMMORTAL)),
        (Color.WHITE, board_action_v1(9, 8, 8, ActionKind.DOUBLE_START)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
        (Color.BLACK, board_action_v1(9, 1, 0, ActionKind.IMMORTAL)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
        (Color.BLACK, action_v1(PASS_ACTION_ID)),
    ):
        builder.accepted(actor, action)
    return builder.request()


def _post_settlement_capture_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder("curated-settled-source-capture-no-refund-9", 9, deadline=deadline)
    for actor, action in (
        (Color.BLACK, board_action_v1(9, 0, 0, ActionKind.IMMORTAL)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
        (Color.BLACK, action_v1(PASS_ACTION_ID)),
        (Color.WHITE, board_action_v1(9, 1, 0)),
        (Color.BLACK, board_action_v1(9, 4, 4)),
        (Color.WHITE, board_action_v1(9, 0, 1)),
    ):
        builder.accepted(actor, action)
    return builder.request()


def _occupied_quota_precedence_request(
    *, deadline: float | None = None
) -> dict[str, object]:
    builder = EpisodeBuilder(
        "curated-occupied-before-quota-precedence-9",
        9,
        quotas(
            black_immortal=1,
            white_immortal=0,
            black_double=0,
            white_double=0,
            eightway=0,
        ),
        deadline=deadline,
    )
    builder.accepted(Color.BLACK, board_action_v1(9, 0, 0))
    builder.accepted(Color.WHITE, board_action_v1(9, 8, 8))
    builder.add(Color.BLACK, board_action_v1(9, 0, 0, ActionKind.IMMORTAL))
    builder.accepted(Color.BLACK, board_action_v1(9, 1, 0, ActionKind.IMMORTAL))
    builder.accepted(Color.WHITE, board_action_v1(9, 7, 8))
    builder.add(Color.BLACK, board_action_v1(9, 2, 0, ActionKind.IMMORTAL))
    # Quota exhaustion precedes occupancy once both conditions hold.
    builder.add(Color.BLACK, board_action_v1(9, 0, 0, ActionKind.IMMORTAL))
    return builder.request()


def _psk_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder("curated-occupancy-only-psk-immortal-9", 9, deadline=deadline)
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
        builder.accepted(actor, board_action_v1(9, x, y))
    builder.add(Color.WHITE, board_action_v1(9, 2, 2, ActionKind.IMMORTAL))
    return builder.request()


def _action_t_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder(
        "curated-action-t-eightway-9",
        9,
        quotas(
            black_immortal=0,
            white_immortal=0,
            black_double=0,
            white_double=0,
            eightway=0,
            white_eightway=1,
        ),
        deadline=deadline,
    )
    black = (
        (0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (0, 8), (2, 8), (4, 8),
        (6, 8), (8, 8), (0, 2), (0, 4), (0, 6), (4, 3), (3, 4), (5, 4), (4, 5),
    )
    white = (
        (1, 1), (3, 1), (5, 1), (7, 1), (1, 7), (3, 7), (5, 7), (7, 7),
        (2, 3), (6, 3), (2, 5), (6, 5), (1, 3), (7, 3), (1, 5), (7, 5),
    )
    for index, point in enumerate(black):
        builder.accepted(Color.BLACK, board_action_v1(9, *point))
        if index < len(white):
            builder.accepted(Color.WHITE, board_action_v1(9, *white[index]))
    builder.accepted(Color.WHITE, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY))
    return builder.request()


def _n8_liberty_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder("curated-n8-liberty-versus-normal-suicide-9", 9, deadline=deadline)
    black_fillers = ((0, 0), (2, 0), (6, 0), (8, 0))
    white_cross = ((4, 3), (3, 4), (5, 4), (4, 5))
    for black_point, white_point in zip(black_fillers, white_cross):
        builder.accepted(Color.BLACK, board_action_v1(9, *black_point))
        builder.accepted(Color.WHITE, board_action_v1(9, *white_point))
    rejected = builder.add(Color.BLACK, board_action_v1(9, 4, 4))
    if rejected.accepted or rejected.rejection_code.value != "SUICIDE":
        raise AssertionError("NORMAL surrounded-center control stopped being suicide")
    builder.accepted(Color.BLACK, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY))
    return builder.request()


def _surrounded_eightway_suicide_request(
    *, deadline: float | None = None
) -> dict[str, object]:
    builder = EpisodeBuilder("curated-eightway-surrounded-center-suicide-9", 9, deadline=deadline)
    black_fillers = ((0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (0, 2), (2, 2), (8, 2))
    white_ring = ((3, 3), (4, 3), (5, 3), (3, 4), (5, 4), (3, 5), (4, 5), (5, 5))
    for black_point, white_point in zip(black_fillers, white_ring):
        builder.accepted(Color.BLACK, board_action_v1(9, *black_point))
        builder.accepted(Color.WHITE, board_action_v1(9, *white_point))
    rejected = builder.add(
        Color.BLACK,
        board_action_v1(9, 4, 4, ActionKind.EIGHTWAY),
    )
    if rejected.accepted or rejected.rejection_code.value != "SUICIDE":
        raise AssertionError("fully surrounded Eightway control stopped being suicide")
    return builder.request()


def _topology_edges_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder("curated-eightway-endpoints-shoulders-separation-9", 9, deadline=deadline)
    for actor, action in (
        (Color.BLACK, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY)),
        (Color.WHITE, board_action_v1(9, 4, 3)),
        (Color.BLACK, board_action_v1(9, 3, 3)),
        (Color.WHITE, board_action_v1(9, 3, 4)),
        (Color.BLACK, board_action_v1(9, 1, 1)),
        (Color.WHITE, board_action_v1(9, 8, 8)),
        (Color.BLACK, board_action_v1(9, 2, 2)),
        (Color.WHITE, board_action_v1(9, 6, 6, ActionKind.EIGHTWAY)),
        (Color.BLACK, board_action_v1(9, 0, 8)),
        (Color.WHITE, board_action_v1(9, 5, 5)),
    ):
        builder.accepted(actor, action)
    return builder.request()


def _captured_eightway_noop_request(
    *, deadline: float | None = None
) -> dict[str, object]:
    builder = EpisodeBuilder("curated-captured-pending-eightway-noop-9", 9, deadline=deadline)
    for actor, action in (
        (Color.BLACK, board_action_v1(9, 0, 0, ActionKind.EIGHTWAY)),
        (Color.WHITE, board_action_v1(9, 1, 0)),
        (Color.BLACK, board_action_v1(9, 8, 8)),
        (Color.WHITE, board_action_v1(9, 0, 1)),
        (Color.BLACK, board_action_v1(9, 7, 8)),
        (Color.WHITE, board_action_v1(9, 1, 1)),
        (Color.BLACK, action_v1(PASS_ACTION_ID)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
    ):
        builder.accepted(actor, action)
    return builder.request()


def _eightway_psk_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder("curated-eightway-placement-capture-psk-rollback-9", 9, deadline=deadline)
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
        builder.accepted(actor, board_action_v1(9, x, y))
    rejected = builder.add(
        Color.WHITE,
        board_action_v1(9, 2, 2, ActionKind.EIGHTWAY),
    )
    if rejected.accepted or rejected.rejection_code.value != "POSITIONAL_SUPERKO":
        raise AssertionError("Eightway ko control stopped being positional superko")
    return builder.request()


def _quota_two_request(*, deadline: float | None = None) -> dict[str, object]:
    builder = EpisodeBuilder(
        "curated-eightway-quotas-above-one-9",
        9,
        quotas(
            black_immortal=0,
            white_immortal=0,
            black_double=0,
            white_double=0,
            black_eightway=2,
            white_eightway=2,
        ),
        deadline=deadline,
    )
    for actor, x, y in (
        (Color.BLACK, 0, 0),
        (Color.WHITE, 8, 8),
        (Color.BLACK, 2, 0),
        (Color.WHITE, 6, 8),
    ):
        builder.accepted(actor, board_action_v1(9, x, y, ActionKind.EIGHTWAY))
    exhausted = builder.add(
        Color.BLACK,
        board_action_v1(9, 4, 0, ActionKind.EIGHTWAY),
    )
    if exhausted.accepted or exhausted.rejection_code.value != "QUOTA_EXHAUSTED":
        raise AssertionError("Eightway quota-above-one control lost exact exhaustion")
    return builder.request()


def _global_special_order_request(
    *, deadline: float | None = None
) -> dict[str, object]:
    builder = EpisodeBuilder("curated-global-interleaved-i-d-e-order-9", 9, deadline=deadline)
    for actor, action in (
        (Color.BLACK, board_action_v1(9, 0, 0, ActionKind.EIGHTWAY)),
        (Color.WHITE, board_action_v1(9, 8, 8, ActionKind.IMMORTAL)),
        (Color.BLACK, board_action_v1(9, 1, 0, ActionKind.DOUBLE_START)),
        (Color.BLACK, board_action_v1(9, 2, 0)),
        (Color.WHITE, board_action_v1(9, 7, 8, ActionKind.EIGHTWAY)),
        (Color.BLACK, action_v1(PASS_ACTION_ID)),
        (Color.WHITE, action_v1(PASS_ACTION_ID)),
    ):
        builder.accepted(actor, action)
    return builder.request()


def _newer_immortal_captures_eightway_request(
    *, deadline: float | None = None
) -> dict[str, object]:
    builder = EpisodeBuilder(
        "curated-newer-immortal-captures-older-eightway-noop-9",
        9,
        quotas(
            black_immortal=1,
            white_immortal=0,
            black_double=0,
            white_double=0,
            black_eightway=1,
            white_eightway=0,
        ),
        deadline=deadline,
    )
    builder.accepted(Color.BLACK, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY))
    surround = ((3, 3), (4, 3), (5, 3), (3, 4), (5, 4), (3, 5), (5, 5), (4, 6))
    for index, point in enumerate(surround):
        builder.accepted(Color.WHITE, board_action_v1(9, *point))
        if index < 7:
            builder.accepted(Color.BLACK, board_action_v1(9, index, 8))
    builder.accepted(Color.BLACK, board_action_v1(9, 4, 5, ActionKind.IMMORTAL))
    builder.accepted(Color.WHITE, action_v1(PASS_ACTION_ID))
    builder.accepted(Color.BLACK, action_v1(PASS_ACTION_ID))
    return builder.request()


def _eightway_precedence_request(
    *, deadline: float | None = None
) -> dict[str, object]:
    builder = EpisodeBuilder(
        "curated-eightway-rejection-precedence-9",
        9,
        quotas(
            black_immortal=0,
            white_immortal=0,
            black_double=1,
            white_double=0,
            eightway=0,
        ),
        deadline=deadline,
    )
    builder.add(Color.BLACK, action_v1(1083))
    builder.add(Color.WHITE, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY))
    builder.add(Color.BLACK, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY))
    builder.accepted(Color.BLACK, board_action_v1(9, 0, 0, ActionKind.DOUBLE_START))
    builder.add(Color.BLACK, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY))
    builder.accepted(Color.BLACK, board_action_v1(9, 1, 0))
    builder.accepted(Color.WHITE, action_v1(PASS_ACTION_ID))
    builder.accepted(Color.BLACK, action_v1(PASS_ACTION_ID))
    builder.add(Color.WHITE, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY))
    builder.accepted(Color.WHITE, action_v1(PASS_ACTION_ID))
    builder.accepted(Color.BLACK, action_v1(PASS_ACTION_ID))
    builder.add(Color.BLACK, board_action_v1(9, 4, 4, ActionKind.EIGHTWAY))
    return builder.request()


def transform_request(
    request: Mapping[str, object],
    symmetry: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "Eightway D4 request transformation")
    transformed = copy.deepcopy(request)
    transformed["episodeId"] = episode_id
    transformed["steps"] = [
        {
            "candidateActor": step["candidateActor"],
            "action": transform_action(step["action"], request["boardSize"], symmetry),
        }
        for step in request["steps"]
    ]
    return dict(validate_episode_request(transformed))


def _transform_points(points: list[int], board_size: int, symmetry: int) -> list[int]:
    return sorted(transform_board_point(board_size, point, symmetry) for point in points)


def _transform_state(state: dict[str, object], board_size: int, symmetry: int) -> None:
    hardened._transform_state(state, board_size, symmetry)
    state["eightwayAnchors"] = _transform_points(
        state["eightwayAnchors"], board_size, symmetry
    )
    state["immortalAnchors"] = _transform_points(
        state["immortalAnchors"], board_size, symmetry
    )


def _transform_transition(
    transition: dict[str, object], board_size: int, symmetry: int
) -> None:
    hardened._transform_transition(transition, board_size, symmetry)
    atomic = transition["atomicEvent"]
    if atomic is not None:
        for stone in atomic["stableStones"]:
            stone["point"] = transform_board_point(board_size, stone["point"], symmetry)
        atomic["stableStones"].sort(key=lambda stone: stone["point"])
    snapshot = transition["atomicSnapshot"]
    if snapshot is not None:
        _transform_state(snapshot, board_size, symmetry)
    settlement = transition["settlement"]
    if settlement is not None:
        for step in settlement["steps"]:
            step["sourcePoint"] = transform_board_point(
                board_size, step["sourcePoint"], symmetry
            )


def transform_response(
    response: Mapping[str, object],
    board_size: int,
    symmetry: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "Eightway D4 response transformation")
    transformed = copy.deepcopy(response)
    transformed["episodeId"] = episode_id
    _transform_state(transformed["initialState"], board_size, symmetry)
    for observation in transformed["observations"]:
        _transform_transition(observation["transition"], board_size, symmetry)
        _transform_state(observation["state"], board_size, symmetry)
    return transformed


def load_contract_fixture(
    path: Path = FIXTURE_PATH, *, deadline: float | None = None
) -> dict[str, object]:
    _check_deadline(deadline, "Eightway contract fixture loading")
    fixture = parse_json_bytes(path.read_bytes())
    if type(fixture) is not dict:
        raise ProtocolError("Eightway contract fixture must be a JSON object")
    return fixture


PINNED_FIXTURE_LEGAL_RANGES_SHA256 = (
    "c644dd9c6fb65cc3472f1f6764b168d4d0aaac5f8af37691a2cc7e5b90929182"
)


def _fixture_legal_ranges_digest(fixture: Mapping[str, object]) -> str:
    literal = [fixture["initialProjection"]["derived"]["legalActionRanges"]]
    literal.extend(
        step["expectedProjection"]["derived"]["legalActionRanges"]
        for step in fixture["steps"]
    )
    return hashlib.sha256(canonical_json(literal).encode("ascii")).hexdigest()


def _merge_action_ids(action_ids: Sequence[int]) -> list[dict[str, int]]:
    ordered = sorted(set(action_ids))
    if not ordered:
        return []
    result = []
    first = last = ordered[0]
    for action_id in ordered[1:]:
        if action_id == last + 1:
            last = action_id
        else:
            result.append({"first": first, "last": last})
            first = last = action_id
    result.append({"first": first, "last": last})
    return result


def _fixture_legal_action_ranges(state) -> list[dict[str, int]]:
    if state.phase is Phase.TERMINAL:
        return []
    legal = [PASS_ACTION_ID]
    for kind in (
        ActionKind.NORMAL,
        ActionKind.IMMORTAL,
        ActionKind.DOUBLE_START,
        ActionKind.EIGHTWAY,
    ):
        for point in range(state.config.board_size**2):
            action = board_action_v1(
                state.config.board_size,
                point % state.config.board_size,
                point // state.config.board_size,
                kind,
            )
            transition = _apply_v3_adapter(state, state.actor, action)
            if transition.accepted:
                legal.append(action["actionId"])
    return _merge_action_ids(legal)


def _contract_state(
    projected: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    state = copy.deepcopy(projected)
    groups = state.pop("groups")
    state.pop("eventLogLength")
    state.pop("eightwayAnchors")
    state.pop("immortalAnchors")
    state.pop("settledLedgerCount")
    state.pop("stableTerminalEventCount")
    for entry in state["ledger"]:
        entry.pop("originActionNumber")
    return state, {"groups": groups}


def _contract_transition(projected: Mapping[str, object]) -> dict[str, object]:
    transition = copy.deepcopy(projected)
    for field in (
        "action",
        "atomicSnapshot",
        "candidateActor",
        "positionalSuperkoAppends",
        "status",
    ):
        transition.pop(field)
    if transition["atomicEvent"] is not None:
        transition["atomicEvent"].pop("stableStones")
    if transition["settlement"] is not None:
        for step in transition["settlement"]["steps"]:
            for field in ("kind", "originActionNumber", "owner", "sourcePoint"):
                step.pop(field)
    return transition


def build_official_contract_fixture() -> dict[str, object]:
    request = eightway_immortal_split_request(
        19, "contract-eightway-immortal-split"
    )
    response = oracle_episode_response(request)
    initial_state = new_game(_oracle_config(request["initialQuotas"], 19))
    states = [initial_state]
    state = initial_state
    for step in request["steps"]:
        transition = _apply_v3_adapter(
            state, Color(step["candidateActor"]), step["action"]
        )
        if not transition.accepted:
            raise AssertionError("official Eightway fixture sequence stopped being legal")
        state = transition.state
        states.append(state)

    identity = {
        "descriptorSha256": "a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899",
        "rulesetId": "mutago.collapse-go",
        "semanticVersion": "0.1.0-draft",
    }

    def projection(
        step_index: int,
        projected_state: Mapping[str, object],
        transition: Mapping[str, object] | None,
        semantic_state,
    ) -> dict[str, object]:
        state_value, debug = _contract_state(projected_state)
        return {
            "debug": debug,
            "derived": {
                "legalActionRanges": _fixture_legal_action_ranges(semantic_state)
            },
            "fixtureId": request["episodeId"],
            "pointEncoding": "BOARD_LOCAL_ROW_MAJOR",
            "ruleset": copy.deepcopy(identity),
            "schemaVersion": "semantic-projection-v1",
            "state": state_value,
            "stepIndex": step_index,
            "transition": (
                _contract_transition(transition) if transition is not None else None
            ),
        }

    initial_projection = projection(
        0, response["initialState"], None, states[0]
    )
    steps = []
    for index, (request_step, observation, semantic_state) in enumerate(
        zip(request["steps"], response["observations"], states[1:]), start=1
    ):
        steps.append(
            {
                "candidate": {
                    "action": copy.deepcopy(request_step["action"]),
                    "kind": "ACTION",
                },
                "candidateActor": request_step["candidateActor"],
                "expectedProjection": projection(
                    index,
                    observation["state"],
                    observation["transition"],
                    semantic_state,
                ),
                "stepIndex": index,
            }
        )
    return {
        "configuration": {
            "boardSize": 19,
            "deadStoneShortcut": "DEFERRED",
            "initialActor": "BLACK",
            "initialPSKSeed": True,
            "komi": {"denominator": 2, "numerator": 15, "recipient": "WHITE"},
            "quotas": quotas(),
            "scoring": "CHINESE_AREA",
            "threshold": 150,
        },
        "descriptor": None,
        "fixtureClass": "CONTRACT_EXAMPLE",
        "fixtureId": request["episodeId"],
        "initialProjection": initial_projection,
        "provenance": {
            "generator": "contract-owner",
            "generatorVersion": "3",
            "kind": "HAND_AUTHORED",
            "seed": None,
        },
        "ruleset": copy.deepcopy(identity),
        "schemaVersion": "conformance-fixture-v1",
        "steps": steps,
        "tags": [
            "eightway",
            "immortal",
            "mixed-topology",
            "protection-propagation",
            "settlement-split",
            "settlement-removal",
            "psk-append",
        ],
    }


def validate_contract_fixture(
    fixture: Mapping[str, object], *, deadline: float | None = None
) -> None:
    _check_deadline(deadline, "Eightway contract fixture validation")
    catalog = SchemaCatalog()
    digest = validate_descriptor(load_json(DESCRIPTOR_PATH), catalog)
    _validate_fixture(fixture, catalog, digest)
    actual = _fixture_legal_ranges_digest(fixture)
    if actual != PINNED_FIXTURE_LEGAL_RANGES_SHA256:
        raise ProtocolError(
            "checked-in Eightway fixture legalActionRanges literal differs from its pinned digest"
        )


def fixture_request(
    fixture: Mapping[str, object] | None = None,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    if fixture is None:
        fixture = load_contract_fixture(deadline=deadline)
    return dict(
        validate_episode_request(
            {
                "boardSize": fixture["configuration"]["boardSize"],
                "episodeId": fixture["fixtureId"],
                "initialQuotas": copy.deepcopy(fixture["configuration"]["quotas"]),
                "protocolVersion": PROTOCOL_VERSION,
                "steps": [
                    {
                        "candidateActor": step["candidateActor"],
                        "action": copy.deepcopy(step["candidate"]["action"]),
                    }
                    for step in fixture["steps"]
                ],
            }
        )
    )


def fixture_reexecution_requests(
    fixture: Mapping[str, object], *, deadline: float | None = None
) -> list[dict[str, object]]:
    full = fixture_request(fixture, deadline=deadline)
    eightway_placement = copy.deepcopy(full)
    eightway_placement["episodeId"] = "fixture-eightway-placement-prefix"
    eightway_placement["steps"] = eightway_placement["steps"][:5]
    protected = copy.deepcopy(full)
    protected["episodeId"] = "fixture-eightway-mixed-protection-prefix"
    protected["steps"] = protected["steps"][:8]
    pre_trigger = copy.deepcopy(full)
    pre_trigger["episodeId"] = "fixture-eightway-pre-trigger-prefix"
    pre_trigger["steps"] = pre_trigger["steps"][:9]
    reexecution = copy.deepcopy(full)
    reexecution["episodeId"] = "fixture-eightway-full-reexecution"
    suffix = copy.deepcopy(full)
    suffix["episodeId"] = "fixture-eightway-post-settlement-suffix"
    suffix["steps"].append(
        {"candidateActor": "BLACK", "action": board_action_v1(19, 1, 18)}
    )
    return [
        dict(validate_episode_request(item))
        for item in (
            eightway_placement,
            protected,
            pre_trigger,
            reexecution,
            suffix,
        )
    ]


def _strip_v3_state(state: Mapping[str, object]) -> dict[str, object]:
    stripped = copy.deepcopy(state)
    del stripped["eventLogLength"]
    del stripped["eightwayAnchors"]
    del stripped["immortalAnchors"]
    return stripped


def _strip_v3_transition(transition: Mapping[str, object]) -> dict[str, object]:
    stripped = copy.deepcopy(transition)
    del stripped["atomicSnapshot"]
    if stripped["atomicEvent"] is not None:
        del stripped["atomicEvent"]["stableStones"]
    if stripped["settlement"] is not None:
        for step in stripped["settlement"]["steps"]:
            for field in ("kind", "originActionNumber", "owner", "sourcePoint"):
                del step[field]
    return stripped


def normalized_contract_fixture(fixture: Mapping[str, object]) -> dict[str, object]:
    response = {
        "episodeId": fixture["fixtureId"],
        "initialState": hardened._normalize_contract_state(fixture["initialProjection"]),
        "observations": [],
        "protocolVersion": PROTOCOL_VERSION,
    }
    for step in fixture["steps"]:
        projection = step["expectedProjection"]
        response["observations"].append(
            {
                "state": hardened._normalize_contract_state(projection),
                "stepIndex": step["stepIndex"],
                "transition": hardened._normalize_contract_transition(step, projection),
            }
        )
    return response


def strip_v3_response(response: Mapping[str, object]) -> dict[str, object]:
    stripped = {
        "episodeId": response["episodeId"],
        "initialState": _strip_v3_state(response["initialState"]),
        "observations": [],
        "protocolVersion": response["protocolVersion"],
    }
    for observation in response["observations"]:
        stripped["observations"].append(
            {
                "state": _strip_v3_state(observation["state"]),
                "stepIndex": observation["stepIndex"],
                "transition": _strip_v3_transition(observation["transition"]),
            }
        )
    return stripped


def generate_curated_episodes(
    fixture: Mapping[str, object], *, deadline: float | None = None
) -> list[dict[str, object]]:
    _check_deadline(deadline, "Eightway curated corpus generation")
    episodes = [fixture_request(fixture, deadline=deadline)]
    episodes.extend(fixture_reexecution_requests(fixture, deadline=deadline))
    for board_size in (9, 13, 19):
        _check_deadline(deadline, "Eightway curated D4 corpus generation")
        base = eightway_immortal_split_request(
            board_size,
            f"curated-d4-eightway-{board_size}-base",
            deadline=deadline,
        )
        for symmetry in range(8):
            _check_deadline(deadline, "Eightway curated D4 corpus generation")
            episodes.append(
                transform_request(
                    base,
                    symmetry,
                    f"curated-d4-eightway-{board_size}-{symmetry}",
                    deadline=deadline,
                )
            )
    episodes.extend(
        (
            _attachment_request(double_attachment=False, deadline=deadline),
            _attachment_request(double_attachment=True, deadline=deadline),
            _two_anchor_request(deadline=deadline),
            _mixed_ledger_request(deadline=deadline),
            _post_settlement_capture_request(deadline=deadline),
            _occupied_quota_precedence_request(deadline=deadline),
            _psk_request(deadline=deadline),
            _action_t_request(deadline=deadline),
            _n8_liberty_request(deadline=deadline),
            _surrounded_eightway_suicide_request(deadline=deadline),
            _topology_edges_request(deadline=deadline),
            _captured_eightway_noop_request(deadline=deadline),
            _eightway_psk_request(deadline=deadline),
            _quota_two_request(deadline=deadline),
            _global_special_order_request(deadline=deadline),
            _newer_immortal_captures_eightway_request(deadline=deadline),
            _eightway_precedence_request(deadline=deadline),
        )
    )
    return episodes


def _opponent(actor: Color) -> Color:
    return Color.WHITE if actor is Color.BLACK else Color.BLACK


def _first_accepted(
    state, kind: ActionKind, start: int, *, deadline: float | None = None
) -> dict[str, object] | None:
    point_count = state.config.board_size**2
    for offset in range(point_count):
        _check_deadline(deadline, "Eightway legal candidate generation")
        point = (start + offset) % point_count
        action = board_action_v1(
            state.config.board_size,
            point % state.config.board_size,
            point // state.config.board_size,
            kind,
        )
        transition = _apply_v3_adapter(state, state.actor, action)
        if transition is not None and transition.accepted:
            return action
    return None


def _random_episode(
    rng: Sha256CounterRng,
    seed_tag: str,
    sequence: int,
    step_count: int,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    board_size = (9, 13, 19)[rng.randbelow(3)]
    initial = quotas(
        black_immortal=rng.randbelow(3),
        white_immortal=rng.randbelow(3),
        black_double=rng.randbelow(3),
        white_double=rng.randbelow(3),
        black_eightway=rng.randbelow(3),
        white_eightway=rng.randbelow(3),
    )
    builder = EpisodeBuilder(
        f"random-eightway-{seed_tag}-{sequence:06d}",
        board_size,
        initial,
        deadline=deadline,
    )
    while len(builder.steps) < step_count:
        _check_deadline(deadline, "Eightway random corpus generation")
        if builder.state.phase is Phase.TERMINAL:
            builder.add(
                (Color.BLACK, Color.WHITE)[rng.randbelow(2)],
                action_v1(rng.randbelow(1445)),
            )
            continue
        actor = builder.state.actor
        mode = rng.randbelow(12)
        if builder.state.pending_double is not None:
            if mode < 3:
                action = action_v1(PASS_ACTION_ID)
                candidate = actor
            elif mode < 6:
                action = _first_accepted(
                    builder.state,
                    ActionKind.NORMAL,
                    rng.randbelow(board_size**2),
                    deadline=deadline,
                ) or action_v1(PASS_ACTION_ID)
                candidate = actor
            elif mode < 9:
                kind = (ActionKind.IMMORTAL, ActionKind.DOUBLE_START, ActionKind.EIGHTWAY)[mode - 6]
                point = rng.randbelow(board_size**2)
                action = board_action_v1(board_size, point % board_size, point // board_size, kind)
                candidate = actor
            else:
                action = action_v1(rng.randbelow(1445))
                candidate = actor if rng.randbelow(2) else _opponent(actor)
        else:
            if mode == 0:
                action = action_v1(PASS_ACTION_ID)
                candidate = actor
            elif mode in (1, 2, 3, 4):
                kind = (
                    ActionKind.NORMAL,
                    ActionKind.IMMORTAL,
                    ActionKind.DOUBLE_START,
                    ActionKind.EIGHTWAY,
                )[mode - 1]
                action = _first_accepted(
                    builder.state,
                    kind,
                    rng.randbelow(board_size**2),
                    deadline=deadline,
                ) or action_v1(PASS_ACTION_ID)
                candidate = actor
            elif mode == 5 and builder.state.stones:
                point = builder.state.stones[rng.randbelow(len(builder.state.stones))].point
                action = board_action_v1(board_size, point % board_size, point // board_size, ActionKind.IMMORTAL)
                candidate = actor
            elif mode == 6:
                point = rng.randbelow(board_size**2)
                action = board_action_v1(board_size, point % board_size, point // board_size, ActionKind.EIGHTWAY)
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
    if type(candidate_count) is not int or not (
        MIN_RANDOM_CANDIDATE_COUNT <= candidate_count <= MAX_RANDOM_CANDIDATE_COUNT
    ):
        raise ValueError(
            f"candidate_count must be in {MIN_RANDOM_CANDIDATE_COUNT}..{MAX_RANDOM_CANDIDATE_COUNT}"
        )
    rng = Sha256CounterRng(
        b"MutaGo Eightway Increment 3 v3\x00" + seed.encode("utf-8")
    )
    seed_tag = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    episodes = []
    generated = 0
    sequence = 0
    while generated < candidate_count:
        count = min(32, candidate_count - generated)
        episodes.append(
            _random_episode(
                rng, seed_tag, sequence, count, deadline=deadline
            )
        )
        generated += count
        sequence += 1
    return episodes


def _compare_fixture_d4_and_prefixes(
    fixture: Mapping[str, object],
    expected_by_id: Mapping[str, Mapping[str, object]],
    actual_by_id: Mapping[str, Mapping[str, object]],
    requests_by_id: Mapping[str, Mapping[str, object]],
    manifest: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> None:
    normalized = normalized_contract_fixture(fixture)
    fixture_id = fixture["fixtureId"]
    active_request_id = fixture_id
    try:
        for side, responses in (("python", expected_by_id), ("cpp", actual_by_id)):
            active_request_id = fixture_id
            hardened.compare_exact(
                normalized,
                strip_v3_response(responses[fixture_id]),
                episode_id=f"{side}-eightway-contract-binding",
                deadline=deadline,
            )
            full = responses[fixture_id]
            for prefix_id, prefix_length, label in (
                ("fixture-eightway-placement-prefix", 5, "Eightway-placement"),
                ("fixture-eightway-mixed-protection-prefix", 8, "mixed-protection"),
                ("fixture-eightway-pre-trigger-prefix", 9, "pre-trigger"),
            ):
                active_request_id = prefix_id
                hardened.compare_exact(
                    full["observations"][:prefix_length],
                    responses[prefix_id]["observations"],
                    episode_id=f"{side}-{label}-immutable-prefix",
                    deadline=deadline,
                )
            active_request_id = "fixture-eightway-full-reexecution"
            reexecuted = copy.deepcopy(responses[active_request_id])
            reexecuted["episodeId"] = fixture_id
            hardened.compare_exact(
                full,
                reexecuted,
                episode_id=f"{side}-eightway-action-reexecution",
                deadline=deadline,
            )
            active_request_id = "fixture-eightway-post-settlement-suffix"
            suffix = responses[active_request_id]
            hardened.compare_exact(
                full["observations"],
                suffix["observations"][:10],
                episode_id=f"{side}-post-settlement-immutable-prefix",
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
                        episode_id=f"{side}-eightway-d4-{board_size}-{symmetry}",
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
                        episode_id=f"{side}-eightway-d4-inverse-{board_size}-{symmetry}",
                        deadline=deadline,
                    )
    except (ProbeError, DifferentialMismatch) as exc:
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
        random_episodes = generate_random_episodes(seed, candidate_count, deadline=deadline)
        episodes = curated + random_episodes
        request_lines = [canonical_json(request) for request in episodes]
        expected = []
        for context_index, request in enumerate(episodes):
            _check_deadline(deadline, "Eightway Python oracle corpus execution")
            expected.append(oracle_episode_response(request, deadline=deadline))
    except ProbeError as exc:
        raise ProbeError(
            f"{exc}; "
            + _probe_failure_context(
                manifest,
                episodes,
                request_lines,
                response_index=context_index,
                completed_response_count=0,
            )
        ) from exc

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
            _check_deadline(deadline, "Eightway exact corpus comparison")
            difference = hardened._first_difference(left, right, deadline=deadline)
            if difference is not None:
                mismatch_index = next(
                    (
                        index
                        for index, (a, b) in enumerate(
                            zip(left["observations"], right["observations"]), start=1
                        )
                        if hardened._first_difference(a, b, deadline=deadline) is not None
                    ),
                    len(request["steps"]),
                )
                raise DifferentialMismatch(
                    f"episode {request['episodeId']}: {difference}; "
                    + _context(manifest, request, request_lines[context_index], mismatch_index)
                )
            for observation in left["observations"]:
                _check_deadline(deadline, "Eightway summary projection")
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
        raise AssertionError("Eightway summary candidate counts are ambiguous")
    if unsupported != 0:
        raise AssertionError("Eightway v3 emitted a forbidden unsupported classification")
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
        "gateProdClaimed": False,
        "gateRule1MClaimed": False,
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": candidate_count,
        "rejected": rejected,
        "scope": "EIGHTWAY_FULL_SPECIAL_INCREMENT_3_UNFROZEN_TEST_ONLY",
        "seed": seed,
        "settlementReasonCounts": settlements,
        "sha256": digest,
        "unsupported": unsupported,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bounded test-only UNFROZEN Eightway Increment 3 differential"
    )
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--candidate-count", type=int, default=DEFAULT_CANDIDATE_COUNT)
    args = parser.parse_args(argv)
    try:
        summary = run_differential(
            args.probe, seed=args.seed, candidate_count=args.candidate_count
        )
    except (ContractError, ProtocolError, ProbeError, DifferentialMismatch, ValueError) as exc:
        invocation = {
            "generatorVersion": GENERATOR_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "requestedRandomCandidateCount": args.candidate_count,
            "seed": args.seed,
        }
        print(
            f"Eightway Increment 3 differential failed: {exc}; "
            f"invocation={canonical_json(invocation)}",
            file=sys.stderr,
        )
        return 1
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
