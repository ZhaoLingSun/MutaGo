#!/usr/bin/env python3
"""Bounded test-only administrative-termination differential carrier.

The ``administrative-termination-diff-v5-unfrozen`` protocol, its projection,
and its corpus are explicitly UNFROZEN. C++ executes the real production
``CollapseGoReducer::apply`` or ``CollapseGoReducer::terminate`` entry point;
expected results come only from the independent stdlib Python oracle APIs.
This is not a production protocol, persistence format, timeout policy, or
evidence that either project gate passed.
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

import full_rule_differential as v4  # noqa: E402

if Path(v4.__file__).resolve() != CONFORMANCE_DIR / "full_rule_differential.py":
    raise ImportError(
        f"full_rule_differential resolved outside this checkout: {v4.__file__}"
    )

import mutago.collapse_go.normal_pass_oracle as _oracle_module  # noqa: E402

_oracle_path = Path(_oracle_module.__file__).resolve()
try:
    _oracle_path.relative_to(v4.v3.hardened.PYTHON_ROOT)
except ValueError as exc:
    raise ImportError(
        "mutago.collapse_go.normal_pass_oracle resolved outside this checkout: "
        f"{_oracle_path}"
    ) from exc

from mutago.collapse_go import (  # noqa: E402
    PASS_ACTION_ID,
    AdministrativeTerminationReason,
    ActionKind,
    Color,
    Phase,
    RejectionCode,
    TerminalReason,
    apply_action,
    apply_administrative_termination,
    decode_action_v1,
    new_game,
)

PROTOCOL_VERSION = "administrative-termination-diff-v5-unfrozen"
GENERATOR_VERSION = "sha256-counter-administrative-termination-v5-unfrozen"
GENERATOR_DOMAIN = b"MutaGo administrative termination differential v5 UNFROZEN\x00"
DEFAULT_SEED = "mutago-administrative-termination-increment-5"
DEFAULT_CANDIDATE_COUNT = 64
MIN_RANDOM_CANDIDATE_COUNT = 0
MAX_RANDOM_CANDIDATE_COUNT = 4096
MAX_SEED_BYTES = 256
JSON_SAFE_INTEGER_MAX = 9007199254740991
MAX_EPISODE_STEPS = v4.MAX_EPISODE_STEPS
MAX_TEST_QUOTA = v4.MAX_TEST_QUOTA
MAX_REQUEST_FRAME_BYTES = v4.MAX_REQUEST_FRAME_BYTES
MAX_RESPONSE_FRAME_BYTES = v4.MAX_RESPONSE_FRAME_BYTES
MAX_PROBE_STDOUT_BYTES = v4.MAX_PROBE_STDOUT_BYTES
MAX_PROBE_STDERR_BYTES = v4.MAX_PROBE_STDERR_BYTES
PROBE_TIMEOUT_SECONDS = v4.PROBE_TIMEOUT_SECONDS
ACTION_COUNT = v4.ACTION_COUNT
INVERSE_SYMMETRY_IDS = v4.INVERSE_SYMMETRY_IDS

ProtocolError = v4.ProtocolError
ProbeError = v4.ProbeError
DifferentialMismatch = v4.DifferentialMismatch
ContractError = v4.ContractError
Sha256CounterRng = v4.Sha256CounterRng
canonical_json = v4.canonical_json
action_v1 = v4.action_v1
board_action_v1 = v4.board_action_v1
transform_board_point = v4.transform_board_point
transform_action = v4.transform_action
quotas = v4.quotas
hardened = v4.hardened

_REQUEST_FIELDS = frozenset(
    ("protocolVersion", "episodeId", "boardSize", "initialQuotas", "steps")
)
_ACTION_CANDIDATE_FIELDS = frozenset(("kind", "action"))
_ADMIN_CANDIDATE_FIELDS = frozenset(("kind",))
_STATE_FIELDS = frozenset(
    (
        "actor",
        "atomicActionCount",
        "boardSize",
        "consecutivePasses",
        "eventLogLength",
        "expiredQuotas",
        "groups",
        "eightwayAnchors",
        "immortalAnchors",
        "initialQuotas",
        "ledger",
        "legalActionRanges",
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
_TERMINAL_FIELDS = frozenset(("ended", "loser", "reason", "score", "winner"))
_ACTION_TRANSITION_FIELDS = frozenset(
    (
        "accepted",
        "action",
        "atomicEvent",
        "atomicSnapshot",
        "candidateActor",
        "errorCode",
        "positionalSuperkoAppends",
        "settlement",
        "status",
        "terminalEvent",
        "transitionKind",
    )
)
_ADMIN_TRANSITION_FIELDS = frozenset(
    (
        "accepted",
        "candidate",
        "candidateActor",
        "errorCode",
        "positionalSuperkoAppends",
        "status",
        "terminalEvent",
        "transitionKind",
    )
)
_IMMEDIATE_TERMINAL_EVENT_FIELDS = frozenset(
    (
        "eventId",
        "logPosition",
        "loser",
        "pskHistoryIndex",
        "reason",
        "revision",
        "settlementCompleted",
        "stableOccupancy",
        "stableStones",
        "winner",
    )
)


def _check_deadline(deadline: float | None, phase: str) -> None:
    v4._check_deadline(deadline, phase)


def _validate_seed(seed: object) -> tuple[str, bytes]:
    if type(seed) is not str:
        raise ValueError("seed must be a string")
    try:
        encoded = seed.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("seed must contain printable ASCII only") from exc
    if not 1 <= len(encoded) <= MAX_SEED_BYTES:
        raise ValueError(f"seed must contain 1..{MAX_SEED_BYTES} ASCII bytes")
    if any(byte < 0x20 or byte > 0x7E for byte in encoded):
        raise ValueError("seed must contain printable ASCII only")
    return seed, encoded


def _require_fields(value: object, fields: frozenset[str], context: str):
    return hardened._require_exact_fields(value, fields, context)


def validate_episode_request(request: object) -> Mapping[str, object]:
    """Validate the closed v5 request and its closed candidate union."""

    frame = _require_fields(request, _REQUEST_FIELDS, "Administrative episode request")
    if frame["protocolVersion"] != PROTOCOL_VERSION:
        raise ProtocolError(f"protocolVersion must be {PROTOCOL_VERSION}")
    if not hardened._valid_episode_id(frame["episodeId"]):
        raise ProtocolError("episodeId has an invalid test identifier")
    board_size = frame["boardSize"]
    if type(board_size) is not int or board_size not in (9, 13, 19):
        raise ProtocolError("boardSize must be exactly 9, 13, or 19")

    players = _require_fields(
        frame["initialQuotas"], frozenset(("BLACK", "WHITE")), "initialQuotas"
    )
    for color in ("BLACK", "WHITE"):
        vector = _require_fields(
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
        step = _require_fields(
            item, frozenset(("candidateActor", "candidate")), f"step {index}"
        )
        if step["candidateActor"] not in ("BLACK", "WHITE"):
            raise ProtocolError(f"step {index} candidateActor must be BLACK or WHITE")
        candidate = step["candidate"]
        if type(candidate) is not dict or "kind" not in candidate:
            raise ProtocolError(f"step {index} candidate must be a closed object")
        kind = candidate["kind"]
        if kind == "ACTION":
            action_candidate = _require_fields(
                candidate, _ACTION_CANDIDATE_FIELDS, f"step {index} ACTION candidate"
            )
            try:
                decode_action_v1(action_candidate["action"], board_size)
            except (TypeError, ValueError) as exc:
                raise ProtocolError(
                    f"step {index} has invalid nested Action V1: "
                    f"{_safe_exception_text(exc)}"
                ) from exc
        elif kind in ("RESIGNATION", "TIMEOUT"):
            _require_fields(
                candidate, _ADMIN_CANDIDATE_FIELDS, f"step {index} admin candidate"
            )
        else:
            raise ProtocolError(
                f"step {index} candidate.kind must be ACTION, RESIGNATION, or TIMEOUT"
            )

    if len(canonical_json(frame).encode("utf-8")) > MAX_REQUEST_FRAME_BYTES:
        raise ProtocolError("canonical request exceeds the 1 MiB request limit")
    return frame


def action_candidate(actor: Color | str, action: Mapping[str, object]) -> dict[str, object]:
    color = actor.value if isinstance(actor, Color) else actor
    return {
        "candidateActor": color,
        "candidate": {"kind": "ACTION", "action": copy.deepcopy(action)},
    }


def administrative_candidate(
    loser: Color | str, reason: AdministrativeTerminationReason | str
) -> dict[str, object]:
    color = loser.value if isinstance(loser, Color) else loser
    kind = reason.value if isinstance(reason, AdministrativeTerminationReason) else reason
    return {"candidateActor": color, "candidate": {"kind": kind}}


def _terminal_projection(state: object) -> dict[str, object]:
    terminal = state.terminal
    if terminal is None:
        return {
            "ended": False,
            "loser": None,
            "reason": None,
            "score": None,
            "winner": None,
        }
    return {
        "ended": True,
        "loser": terminal.loser.value,
        "reason": terminal.reason.value,
        "score": v4.v3._score(terminal.score) if terminal.score is not None else None,
        "winner": terminal.winner.value,
    }


def state_projection(
    state: object, *, deadline: float | None = None
) -> dict[str, object]:
    """Project one exposed stable state without changing any historical projection."""

    _check_deadline(deadline, "Administrative stable-state projection")
    pending = None
    if state.pending_double is not None:
        pending = {
            "eventId": state.pending_double.event_id,
            "owner": state.pending_double.owner.value,
            "startActionNumber": state.pending_double.start_action_number,
        }
    groups = v4.v3._groups(state.board, state.ledger)
    immortal_anchors = sorted(
        point for group in groups for point in group["immortalAnchors"]
    )
    eightway_anchors = sorted(
        point for group in groups for point in group["eightwayAnchors"]
    )
    projected = {
        "actor": state.actor.value if state.actor is not None else None,
        "atomicActionCount": state.atomic_action_count,
        "boardSize": state.config.board_size,
        "consecutivePasses": state.consecutive_passes,
        "eventLogLength": state.log_position,
        "expiredQuotas": v4.v3._quota_projection(state.expired_quotas),
        "groups": groups,
        "eightwayAnchors": eightway_anchors,
        "immortalAnchors": immortal_anchors,
        "initialQuotas": v4.v3._quota_projection(state.initial_quotas),
        "ledger": [v4.v3._ledger(event) for event in state.ledger],
        "legalActionRanges": v4.python_legal_action_ranges(
            state, deadline=deadline
        ),
        "logPosition": state.log_position,
        "occupancy": v4.v3._occupancy(state.occupancy),
        "pendingDouble": pending,
        "phase": state.phase.value,
        "pskHistory": [v4.v3._occupancy(item) for item in state.psk_history],
        "remainingQuotas": v4.v3._quota_projection(state.remaining_quotas),
        "revision": state.revision,
        "settledLedgerCount": state.settled_ledger_count,
        "settlementCompleted": state.settlement_completed,
        "stableTerminalEventCount": state.stable_terminal_event_count,
        "stones": [v4.v3._stone(stone) for stone in state.stones],
        "terminal": _terminal_projection(state),
        "threshold": state.threshold,
        "usedQuotas": v4.v3._quota_projection(state.used_quotas),
    }
    if frozenset(projected) != _STATE_FIELDS:
        raise AssertionError("administrative state projection fields drifted")
    return projected


def _immediate_terminal_event(event: object) -> dict[str, object]:
    return {
        "eventId": f"terminal-{event.log_position}",
        "logPosition": event.log_position,
        "loser": event.loser.value,
        "pskHistoryIndex": event.psk_history_index,
        "reason": event.reason.value,
        "revision": event.revision,
        "settlementCompleted": event.settlement_completed,
        "stableOccupancy": v4.v3._occupancy(event.stable_occupancy),
        "stableStones": [v4.v3._stone(stone) for stone in event.stable_stones],
        "winner": event.winner.value,
    }


def _administrative_transition_projection(
    actor: Color,
    candidate: Mapping[str, object],
    transition: object,
) -> dict[str, object]:
    if not transition.accepted:
        return {
            "accepted": False,
            "candidate": copy.deepcopy(candidate),
            "candidateActor": actor.value,
            "errorCode": transition.rejection_code.value,
            "positionalSuperkoAppends": 0,
            "status": "REJECTED",
            "terminalEvent": None,
            "transitionKind": "REJECTED",
        }
    return {
        "accepted": True,
        "candidate": copy.deepcopy(candidate),
        "candidateActor": actor.value,
        "errorCode": None,
        "positionalSuperkoAppends": 1,
        "status": "ACCEPTED",
        "terminalEvent": _immediate_terminal_event(transition.terminal_event),
        "transitionKind": "IMMEDIATE_TERMINAL",
    }


def oracle_episode_response(
    request: object, *, deadline: float | None = None
) -> dict[str, object]:
    """Execute ordered candidates only through the independent oracle APIs."""

    _check_deadline(deadline, "Administrative Python oracle request validation")
    frame = validate_episode_request(request)
    try:
        state = new_game(
            v4.v3._oracle_config(frame["initialQuotas"], frame["boardSize"])
        )
        initial_state = state_projection(state, deadline=deadline)
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        setattr(exc, "_administrative_candidate_prefix_length", 0)
        raise
    observations: list[dict[str, object]] = []
    for step_index, step in enumerate(frame["steps"], start=1):
        _check_deadline(deadline, "Administrative Python oracle execution")
        previous = state
        actor = Color(step["candidateActor"])
        candidate = step["candidate"]
        try:
            if candidate["kind"] == "ACTION":
                transition = apply_action(state, actor, candidate["action"])
                state = transition.state
                projected_transition = v4.v3.transition_projection(
                    previous, actor, candidate["action"], transition
                )
            else:
                reason = AdministrativeTerminationReason(candidate["kind"])
                transition = apply_administrative_termination(state, actor, reason)
                state = transition.state
                projected_transition = _administrative_transition_projection(
                    actor, candidate, transition
                )
            observations.append(
                {
                    "state": state_projection(state, deadline=deadline),
                    "stepIndex": step_index,
                    "transition": projected_transition,
                }
            )
        except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
            setattr(exc, "_administrative_candidate_prefix_length", step_index)
            raise
    return {
        "episodeId": frame["episodeId"],
        "initialState": initial_state,
        "observations": observations,
        "protocolVersion": PROTOCOL_VERSION,
    }


def _response_header(response: object, label: str) -> Mapping[str, object]:
    return _require_fields(
        response,
        frozenset(("episodeId", "initialState", "observations", "protocolVersion")),
        label,
    )


def _state_without_stable_legality(
    state: Mapping[str, object],
) -> dict[str, object]:
    stripped = copy.deepcopy(state)
    del stripped["legalActionRanges"]
    if not stripped["terminal"]["ended"]:
        stripped["terminal"] = {"ended": False}
    return stripped


def _state_for_v3_invariants(
    state: Mapping[str, object],
) -> dict[str, object]:
    adapted = _state_without_stable_legality(state)
    terminal = state["terminal"]
    if terminal["ended"] and terminal["reason"] in ("RESIGNATION", "TIMEOUT"):
        adapted["actor"] = "BLACK"
        adapted["phase"] = (
            "ORDINARY_PLAY" if state["settlementCompleted"] else "COLLAPSE_PLAY"
        )
        adapted["revision"] = adapted["atomicActionCount"]
        adapted["terminal"] = {"ended": False}
    return adapted


def _validate_state_shape(
    state: object,
    context: str,
    *,
    expected_template: object | None = None,
) -> Mapping[str, object]:
    projected = _require_fields(state, _STATE_FIELDS, context)
    if expected_template is not None:
        v4.v3._validate_shape(projected, expected_template, context)
    terminal = _require_fields(projected["terminal"], _TERMINAL_FIELDS, f"{context}.terminal")
    if type(terminal["ended"]) is not bool:
        raise ProtocolError(f"{context}.terminal.ended must be bool")
    if terminal["ended"]:
        if terminal["reason"] not in ("SCORE", "RESIGNATION", "TIMEOUT"):
            raise ProtocolError(f"{context}.terminal.reason is invalid")
        if terminal["winner"] not in ("BLACK", "WHITE") or terminal["loser"] not in (
            "BLACK",
            "WHITE",
        ):
            raise ProtocolError(f"{context}.terminal players are invalid")
        if terminal["winner"] == terminal["loser"]:
            raise ProtocolError(f"{context}.terminal players must be opponents")
        if terminal["reason"] == "SCORE" and type(terminal["score"]) is not dict:
            raise ProtocolError(f"{context}.terminal SCORE requires a score")
        if terminal["reason"] != "SCORE" and terminal["score"] is not None:
            raise ProtocolError(f"{context}.terminal admin reason forbids score")
        if projected["phase"] != "TERMINAL" or projected["actor"] is not None:
            raise ProtocolError(f"{context} terminal control state differs")
        if projected["stableTerminalEventCount"] != 1:
            raise ProtocolError(f"{context} terminal event count must be exactly one")
        history = projected["pskHistory"]
        if type(history) is not list or len(history) < 2 or history[-2] != history[-1]:
            raise ProtocolError(f"{context} terminal PSK append changed occupancy")
        if terminal["reason"] == "SCORE":
            if (
                projected["revision"] != projected["atomicActionCount"]
                or not projected["settlementCompleted"]
                or projected["pendingDouble"] is not None
            ):
                raise ProtocolError(f"{context} scored terminal provenance differs")
        elif (
            projected["revision"] != projected["atomicActionCount"] + 1
            or (projected["settlementCompleted"] and projected["pendingDouble"] is not None)
        ):
            raise ProtocolError(f"{context} administrative terminal provenance differs")
    else:
        if any(
            terminal[field] is not None
            for field in ("reason", "winner", "loser", "score")
        ):
            raise ProtocolError(f"{context}.terminal nonterminal fields must be null")
        if (
            projected["phase"] == "TERMINAL"
            or projected["actor"] not in ("BLACK", "WHITE")
            or projected["stableTerminalEventCount"] != 0
            or projected["revision"] != projected["atomicActionCount"]
        ):
            raise ProtocolError(f"{context} nonterminal control state differs")
    v4.validate_legal_action_ranges(
        projected["legalActionRanges"], f"{context}.legalActionRanges"
    )
    if terminal["ended"] and projected["legalActionRanges"] != []:
        raise ProtocolError(f"{context} terminal legal mask must be empty")
    try:
        v4.v3._validate_state_invariants(
            _state_for_v3_invariants(projected), context
        )
    except ProtocolError:
        raise
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"{context} contains malformed nested state data") from exc
    return projected


def _validate_transition_shape(
    transition: object,
    step: Mapping[str, object],
    context: str,
    *,
    expected_template: object | None = None,
) -> Mapping[str, object]:
    candidate = step["candidate"]
    if candidate["kind"] == "ACTION":
        value = _require_fields(transition, _ACTION_TRANSITION_FIELDS, context)
        if expected_template is not None:
            v4.v3._validate_shape(value, expected_template, context)
        if value["action"] != candidate["action"]:
            raise ProtocolError(f"{context}.action differs from the candidate Action V1")
        if value["candidateActor"] != step["candidateActor"]:
            raise ProtocolError(f"{context}.candidateActor differs")
        if type(value["accepted"]) is not bool:
            raise ProtocolError(f"{context}.accepted must be bool")
        if value["accepted"]:
            if (
                value["status"] != "ACCEPTED"
                or value["transitionKind"] != "ATOMIC_ACTION"
                or value["errorCode"] is not None
                or value["atomicEvent"] is None
                or value["atomicSnapshot"] is None
            ):
                raise ProtocolError(f"{context} accepted ACTION transition is inconsistent")
        elif (
            value["status"] != "REJECTED"
            or value["transitionKind"] != "REJECTED"
            or value["errorCode"] not in v4.v3.SUPPORTED_REJECTION_CODES
            or value["positionalSuperkoAppends"] != 0
            or any(
                value[field] is not None
                for field in (
                    "atomicEvent",
                    "atomicSnapshot",
                    "settlement",
                    "terminalEvent",
                )
            )
        ):
            raise ProtocolError(f"{context} rejected ACTION transition is inconsistent")
        return value

    value = _require_fields(transition, _ADMIN_TRANSITION_FIELDS, context)
    if expected_template is not None:
        v4.v3._validate_shape(value, expected_template, context)
    if value["candidate"] != candidate:
        raise ProtocolError(f"{context}.candidate differs from the admin candidate")
    if value["candidateActor"] != step["candidateActor"]:
        raise ProtocolError(f"{context}.candidateActor differs")
    if type(value["accepted"]) is not bool:
        raise ProtocolError(f"{context}.accepted must be bool")
    if value["accepted"]:
        if (
            value["status"] != "ACCEPTED"
            or value["transitionKind"] != "IMMEDIATE_TERMINAL"
            or value["errorCode"] is not None
            or value["positionalSuperkoAppends"] != 1
        ):
            raise ProtocolError(f"{context} accepted admin transition is inconsistent")
        _require_fields(
            value["terminalEvent"],
            _IMMEDIATE_TERMINAL_EVENT_FIELDS,
            f"{context}.terminalEvent",
        )
    elif (
        value["status"] != "REJECTED"
        or value["transitionKind"] != "REJECTED"
        or type(value["errorCode"]) is not str
        or value["positionalSuperkoAppends"] != 0
        or value["terminalEvent"] is not None
    ):
        raise ProtocolError(f"{context} rejected admin transition is inconsistent")
    return value


def _first_observation_difference_prefix(
    expected: object,
    actual: object,
    *,
    deadline: float | None = None,
) -> int:
    if type(expected) is not dict or type(actual) is not dict:
        return 0
    if set(expected) != set(actual):
        return 0
    for field in ("protocolVersion", "episodeId"):
        if hardened._first_difference(
            expected.get(field), actual.get(field), deadline=deadline
        ) is not None:
            return 0
    if hardened._first_difference(
        expected.get("initialState"), actual.get("initialState"), deadline=deadline
    ):
        return 0
    expected_observations = expected.get("observations")
    actual_observations = actual.get("observations")
    if type(expected_observations) is not list or type(actual_observations) is not list:
        return 0
    for index, (left, right) in enumerate(
        zip(expected_observations, actual_observations), start=1
    ):
        if hardened._first_difference(left, right, deadline=deadline) is not None:
            return index
    if len(expected_observations) != len(actual_observations):
        return min(len(expected_observations), len(actual_observations)) + 1
    return len(expected_observations)


def _trusted_context(
    manifest: Mapping[str, object],
    request: Mapping[str, object],
    request_line: str,
    prefix_length: int,
    expected_response: Mapping[str, object] | None,
) -> str:
    bounded_prefix = min(max(prefix_length, 0), len(request["steps"]))
    candidate = request["steps"][bounded_prefix - 1] if bounded_prefix else None
    pre_state: object = None
    if type(expected_response) is dict:
        if bounded_prefix <= 1:
            pre_state = expected_response.get("initialState")
        else:
            observations = expected_response.get("observations")
            if type(observations) is list and bounded_prefix - 2 < len(observations):
                observation = observations[bounded_prefix - 2]
                if type(observation) is dict:
                    pre_state = observation.get("state")
    try:
        pre_state_json = canonical_json(pre_state)
    except (ContractError, RecursionError, TypeError, ValueError):
        pre_state_json = "null"
    return (
        f"manifest={canonical_json(manifest)}; canonicalRequest={request_line}; "
        f"candidatePrefix={canonical_json(request['steps'][:bounded_prefix])}; "
        f"preCandidateState={pre_state_json}; "
        f"candidate={canonical_json(candidate)}"
    )


def _probe_failure_context(
    manifest: Mapping[str, object],
    requests: Sequence[Mapping[str, object]],
    request_lines: Sequence[str],
    expected: Sequence[Mapping[str, object]] = (),
    *,
    response_index: int = 0,
    completed_response_count: int = 0,
    prefix_length: int | None = None,
) -> str:
    if not requests:
        return (
            f"responseIndex={response_index}; completedResponseCount={completed_response_count}; "
            f"manifest={canonical_json(manifest)}; canonicalRequest=null; "
            "candidatePrefix=[]; preCandidateState=null; candidate=null"
        )
    index = min(max(response_index, 0), len(requests) - 1)
    if index >= len(request_lines):
        return (
            f"responseIndex={response_index}; completedResponseCount={completed_response_count}; "
            f"manifest={canonical_json(manifest)}; canonicalRequest=null; "
            "candidatePrefix=[]; preCandidateState=null; candidate=null"
        )
    request = requests[index]
    request_line = request_lines[index]
    expected_response = expected[index] if index < len(expected) else None
    active_prefix = len(request["steps"]) if prefix_length is None else prefix_length
    return (
        f"responseIndex={response_index}; completedResponseCount={completed_response_count}; "
        + _trusted_context(
            manifest, request, request_line, active_prefix, expected_response
        )
    )


def _compare_all_stable_legality(
    actual: Mapping[str, object],
    expected: Mapping[str, object],
    request: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
    request_line: str,
    deadline: float | None = None,
) -> None:
    actual_entries = v4._stable_legality_entries(
        actual,
        expected_observation_count=len(request["steps"]),
        label="actual administrative response",
    )
    expected_entries = v4._stable_legality_entries(
        expected,
        expected_observation_count=len(request["steps"]),
        label="expected administrative response",
    )
    for (label, prefix, actual_ranges), (
        expected_label,
        expected_prefix,
        expected_ranges,
    ) in zip(actual_entries, expected_entries):
        _check_deadline(deadline, "Administrative stable legality comparison")
        trusted_label = (
            "initialState" if prefix == 0 else f"observations[{prefix - 1}].state"
        )
        if (
            prefix != expected_prefix
            or label != trusted_label
            or expected_label != trusted_label
        ):
            raise ProtocolError("stable legality path ordering differs")
        actual_bits = v4.validate_legal_action_ranges(
            actual_ranges, f"actual {trusted_label}.legalActionRanges"
        )
        expected_bits = v4.validate_legal_action_ranges(
            expected_ranges, f"expected {trusted_label}.legalActionRanges"
        )
        if actual_bits != expected_bits:
            first = next(
                action_id
                for action_id, (left, right) in enumerate(
                    zip(expected_bits, actual_bits)
                )
                if left != right
            )
            trusted = _trusted_context(
                manifest, request, request_line, prefix, expected
            )
            error = DifferentialMismatch(
                f"{trusted}; episode={request['episodeId']}; "
                f"legalActionRangesPath={trusted_label}; first differing actionId={first}; "
                f"pythonExpected={str(expected_bits[first]).lower()}; "
                f"cppActual={str(actual_bits[first]).lower()}"
            )
            setattr(error, "_administrative_context_attached", True)
            setattr(error, "_administrative_candidate_prefix_length", prefix)
            raise error


def _canonical_fresh_state_without_legality(
    request: Mapping[str, object],
) -> dict[str, object]:
    fresh = v4.v3._fresh_state_projection(request)
    fresh["terminal"] = {
        "ended": False,
        "loser": None,
        "reason": None,
        "score": None,
        "winner": None,
    }
    return fresh


def _validate_reference_reexecution(
    response: Mapping[str, object],
    request: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> None:
    """Bind a claimed Python response to a fresh genesis execution.

    The structural validators below deliberately do not trust a correlated
    expected/actual pair. Reexecuting the ordered candidates catches coherent
    projection mutations, while the recursive shape comparison also keeps JSON
    scalar types exact (in particular, ``bool`` never aliases ``int``).
    """

    reference = oracle_episode_response(request, deadline=deadline)

    def compare_exact(
        actual: object,
        expected: object,
        context: str,
        prefix_length: int,
    ) -> None:
        try:
            v4.v3._validate_shape(
                actual,
                expected,
                context,
                deadline=deadline,
            )
            difference = hardened._first_difference(
                expected, actual, deadline=deadline
            )
            if difference is not None:
                raise ProtocolError(
                    f"{context} differs from fresh genesis reexecution: {difference}"
                )
        except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
            setattr(exc, "_administrative_candidate_prefix_length", prefix_length)
            raise

    compare_exact(
        response["initialState"],
        reference["initialState"],
        "expected administrative response.initialState",
        0,
    )
    for index, (actual, expected) in enumerate(
        zip(response["observations"], reference["observations"]), start=1
    ):
        _check_deadline(deadline, "Administrative reference reexecution comparison")
        compare_exact(
            actual,
            expected,
            f"expected administrative response.observations[{index - 1}]",
            index,
        )


def _validate_accepted_action_transition(
    previous: Mapping[str, object],
    state: Mapping[str, object],
    transition: Mapping[str, object],
    step: Mapping[str, object],
    context: str,
) -> None:
    previous_v3 = _state_without_stable_legality(previous)
    state_v3 = _state_without_stable_legality(state)
    snapshot = transition["atomicSnapshot"]
    atomic = transition["atomicEvent"]
    try:
        v4.v3._validate_state_invariants(snapshot, f"{context}.atomicSnapshot")
        if (
            atomic["eventId"] != f"action-{atomic['actionNumber']}"
            or atomic["actionNumber"] != snapshot["atomicActionCount"]
            or atomic["actor"] != step["candidateActor"]
            or atomic["action"] != step["candidate"]["action"]
            or atomic["stableOccupancy"] != snapshot["occupancy"]
            or atomic["stableStones"] != snapshot["stones"]
            or atomic["pskHistoryIndex"] != len(previous_v3["pskHistory"])
            or snapshot["pskHistory"][-1] != atomic["stableOccupancy"]
        ):
            raise ProtocolError(f"{context} atomic snapshot binding differs")
        expected_appends = len(state_v3["pskHistory"]) - len(
            previous_v3["pskHistory"]
        )
        if transition["positionalSuperkoAppends"] != expected_appends:
            raise ProtocolError(f"{context} PSK append count differs")
        settlement = transition["settlement"]
        if settlement is not None:
            if settlement["triggerReason"] not in (
                "THRESHOLD",
                "PRE_THRESHOLD_TWO_PASSES",
            ):
                raise ProtocolError(f"{context} settlement reason differs")
            if settlement["handoffActor"] != state_v3["actor"]:
                raise ProtocolError(f"{context} settlement handoff differs")
            for step_offset, settlement_step in enumerate(settlement["steps"]):
                if (
                    settlement_step["stepIndex"] != step_offset
                    or settlement_step["pskHistoryIndex"]
                    != atomic["pskHistoryIndex"] + step_offset + 1
                ):
                    raise ProtocolError(f"{context} settlement step indexing differs")
                has_removal = bool(settlement_step["removalBatches"])
                if settlement_step["noOp"] == (
                    settlement_step["abilityDeactivated"] or has_removal
                ):
                    raise ProtocolError(f"{context} settlement noOp classification differs")
            if settlement["steps"]:
                if settlement["steps"][-1]["stableOccupancy"] != state_v3["occupancy"]:
                    raise ProtocolError(f"{context} settlement suffix occupancy differs")
            elif atomic["stableOccupancy"] != state_v3["occupancy"]:
                raise ProtocolError(f"{context} empty settlement changed occupancy")
        v4.v3._validate_accepted_state_lineage(
            previous_v3,
            snapshot,
            state_v3,
            atomic,
            step["candidate"]["action"],
            settlement,
            context,
        )
        v4.v3._validate_complete_accepted_progression(
            previous_v3,
            snapshot,
            state_v3,
            atomic,
            step["candidate"]["action"],
            settlement,
            transition["terminalEvent"],
            context,
        )
    except ProtocolError:
        raise
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"{context} contains malformed ACTION transition data") from exc


def _validate_administrative_transition(
    previous: Mapping[str, object],
    state: Mapping[str, object],
    transition: Mapping[str, object],
    step: Mapping[str, object],
    context: str,
    *,
    deadline: float | None = None,
) -> None:
    if not transition["accepted"]:
        if (
            not previous["terminal"]["ended"]
            or transition["errorCode"] != "TERMINAL_STATE"
        ):
            raise ProtocolError(
                f"{context} administrative rejection precedence differs"
            )
        difference = hardened._first_difference(previous, state, deadline=deadline)
        if difference is not None:
            raise ProtocolError(
                f"{context} rejected candidate changed exact state: {difference}"
            )
        return

    candidate = step["candidate"]
    loser = step["candidateActor"]
    winner = "WHITE" if loser == "BLACK" else "BLACK"
    if (
        previous["phase"] not in ("COLLAPSE_PLAY", "ORDINARY_PLAY")
        or previous["terminal"]["ended"]
    ):
        raise ProtocolError(f"{context} accepted administration outside a stable boundary")
    expected_state = copy.deepcopy(previous)
    expected_state["actor"] = None
    expected_state["eventLogLength"] += 1
    expected_state["legalActionRanges"] = []
    expected_state["logPosition"] += 1
    expected_state["phase"] = "TERMINAL"
    expected_state["pskHistory"].append(copy.deepcopy(previous["occupancy"]))
    expected_state["revision"] += 1
    expected_state["stableTerminalEventCount"] += 1
    expected_state["terminal"] = {
        "ended": True,
        "loser": loser,
        "reason": candidate["kind"],
        "score": None,
        "winner": winner,
    }
    if state != expected_state:
        difference = hardened._first_difference(
            expected_state, state, deadline=deadline
        )
        raise ProtocolError(
            f"{context} administrative terminal state progression differs: {difference}"
        )

    expected_event = {
        "eventId": f"terminal-{state['logPosition']}",
        "logPosition": state["logPosition"],
        "loser": loser,
        "pskHistoryIndex": len(state["pskHistory"]) - 1,
        "reason": candidate["kind"],
        "revision": state["revision"],
        "settlementCompleted": state["settlementCompleted"],
        "stableOccupancy": copy.deepcopy(state["occupancy"]),
        "stableStones": copy.deepcopy(state["stones"]),
        "winner": winner,
    }
    if transition["terminalEvent"] != expected_event:
        difference = hardened._first_difference(
            expected_event, transition["terminalEvent"], deadline=deadline
        )
        raise ProtocolError(
            f"{context} administrative terminal event binding differs: {difference}"
        )


def _validate_transition_state_invariants(
    response: Mapping[str, object],
    request: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> None:
    previous = response["initialState"]
    for index, (step, observation) in enumerate(
        zip(request["steps"], response["observations"]), start=1
    ):
        _check_deadline(deadline, "Administrative transition invariant validation")
        transition = observation["transition"]
        state = observation["state"]
        context = f"observation {index}"
        if step["candidate"]["kind"] == "ACTION":
            if transition["accepted"]:
                _validate_accepted_action_transition(
                    previous, state, transition, step, context
                )
            else:
                if previous["terminal"]["ended"]:
                    decoded = decode_action_v1(
                        step["candidate"]["action"], previous["boardSize"]
                    )
                    expected_error = (
                        "POINT_OFF_BOARD"
                        if decoded.kind is not ActionKind.PASS
                        and decoded.board_index is None
                        else "TERMINAL_STATE"
                    )
                    if transition["errorCode"] != expected_error:
                        raise ProtocolError(
                            f"{context} terminal ACTION rejection precedence differs"
                        )
                difference = hardened._first_difference(previous, state, deadline=deadline)
                if difference is not None:
                    raise ProtocolError(
                        f"{context} rejected ACTION changed exact state: {difference}"
                    )
        else:
            _validate_administrative_transition(
                previous, state, transition, step, context, deadline=deadline
            )
        previous = state


def _validate_response_semantics(
    response: Mapping[str, object],
    request: Mapping[str, object],
    *,
    label: str,
    expected_template: Mapping[str, object] | None = None,
    deadline: float | None = None,
) -> None:
    initial_template = (
        expected_template["initialState"] if expected_template is not None else None
    )
    initial = _validate_state_shape(
        response["initialState"],
        f"{label}.initialState",
        expected_template=initial_template,
    )
    initial_without_legality = copy.deepcopy(initial)
    del initial_without_legality["legalActionRanges"]
    canonical_fresh = _canonical_fresh_state_without_legality(request)
    if initial_without_legality != canonical_fresh:
        difference = hardened._first_difference(
            canonical_fresh, initial_without_legality, deadline=deadline
        )
        raise ProtocolError(f"{label}.initialState is not canonical: {difference}")

    for index, (step, observation) in enumerate(
        zip(request["steps"], response["observations"])
    ):
        _check_deadline(deadline, "Administrative response semantic validation")
        item = _require_fields(
            observation,
            frozenset(("state", "stepIndex", "transition")),
            f"{label}.observations[{index}]",
        )
        if item["stepIndex"] != index + 1:
            raise ProtocolError(f"{label}.observations[{index}].stepIndex differs")
        observation_template = (
            expected_template["observations"][index]
            if expected_template is not None
            else None
        )
        _validate_state_shape(
            item["state"],
            f"{label}.observations[{index}].state",
            expected_template=(
                observation_template["state"]
                if observation_template is not None
                else None
            ),
        )
        _validate_transition_shape(
            item["transition"],
            step,
            f"{label}.observations[{index}].transition",
            expected_template=(
                observation_template["transition"]
                if observation_template is not None
                else None
            ),
        )
    v4._assert_stable_only_legality_placement(
        response, request, label=label, deadline=deadline
    )
    _validate_transition_state_invariants(
        response, request, deadline=deadline
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
    _check_deadline(deadline, "Administrative response validation")
    frame = validate_episode_request(request)
    try:
        actual = _response_header(response, "administrative response")
        expected = _response_header(expected_shape, "expected administrative response")
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        setattr(exc, "_administrative_candidate_prefix_length", 0)
        raise
    for label, candidate_response in (
        ("administrative response", actual),
        ("expected administrative response", expected),
    ):
        if candidate_response["protocolVersion"] != PROTOCOL_VERSION:
            error = ProtocolError(f"{label} protocolVersion differs")
            setattr(error, "_administrative_candidate_prefix_length", 0)
            raise error
        if candidate_response["episodeId"] != frame["episodeId"]:
            error = ProtocolError(f"{label} episodeId differs")
            setattr(error, "_administrative_candidate_prefix_length", 0)
            raise error
        observations = candidate_response["observations"]
        if type(observations) is not list:
            error = ProtocolError(f"{label} observations must be an array")
            setattr(error, "_administrative_candidate_prefix_length", 0)
            raise error
        if len(observations) != len(frame["steps"]):
            error = ProtocolError(f"{label} observation count differs")
            prefix = (
                0
                if not frame["steps"]
                else min(len(observations) + 1, len(frame["steps"]))
            )
            setattr(error, "_administrative_candidate_prefix_length", prefix)
            raise error
    _validate_reference_reexecution(expected, frame, deadline=deadline)
    _validate_response_semantics(
        expected,
        frame,
        label="expected administrative response",
        deadline=deadline,
    )
    _validate_response_semantics(
        actual,
        frame,
        label="administrative response",
        expected_template=expected,
        deadline=deadline,
    )
    active_manifest = manifest or {
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": 0,
        "seed": "direct-response-validation",
    }
    active_request_line = request_line or canonical_json(frame)
    _compare_all_stable_legality(
        actual,
        expected,
        frame,
        manifest=active_manifest,
        request_line=active_request_line,
        deadline=deadline,
    )
    difference = hardened._first_difference(expected, actual, deadline=deadline)
    if difference is not None:
        prefix = _first_observation_difference_prefix(
            expected, actual, deadline=deadline
        )
        trusted = _trusted_context(
            active_manifest, frame, active_request_line, prefix, expected
        )
        error = DifferentialMismatch(
            f"{trusted}; episode={frame['episodeId']}; firstDifference={difference}"
        )
        setattr(error, "_administrative_context_attached", True)
        setattr(error, "_administrative_candidate_prefix_length", prefix)
        raise error
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
    _check_deadline(deadline, "Administrative response parsing")
    if not line:
        raise ProtocolError("probe returned an empty response line")
    try:
        encoded = line.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ProtocolError(
            "probe response contains invalid Unicode: "
            + _safe_exception_text(exc)
        ) from exc
    if len(encoded) > MAX_RESPONSE_FRAME_BYTES:
        raise ProtocolError("probe response exceeds the 96 MiB response limit")
    try:
        parsed = v4.v3.parse_json_bytes(encoded)
        _check_deadline(deadline, "Administrative response parsing")
        canonical = canonical_json(parsed)
        _check_deadline(deadline, "Administrative response canonicalization")
    except RecursionError as exc:
        raise ProtocolError("probe response exceeds the supported nesting depth") from exc
    except ContractError as exc:
        raise ProtocolError(
            "probe returned invalid restricted-profile JSON: "
            + _safe_exception_text(exc)
        ) from exc
    if canonical != line:
        raise ProtocolError("probe response is not canonical restricted-profile JSON")
    try:
        return validate_episode_response(
            parsed,
            request,
            expected_shape,
            deadline=deadline,
            manifest=manifest,
            request_line=request_line,
        )
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        if not hasattr(exc, "_administrative_candidate_prefix_length"):
            prefix = _first_observation_difference_prefix(
                expected_shape, parsed, deadline=deadline
            )
            setattr(exc, "_administrative_candidate_prefix_length", prefix)
        raise
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        error = ProtocolError("probe response contains malformed nested structure")
        setattr(
            error,
            "_administrative_candidate_prefix_length",
            _first_observation_difference_prefix(
                expected_shape, parsed, deadline=deadline
            ),
        )
        raise error from exc


def _digest_record(digest: object, data: str) -> None:
    v4._digest_record(digest, data)


def _safe_exception_text(exc: BaseException) -> str:
    try:
        args = BaseException.args.__get__(exc, BaseException)
    except BaseException:
        return "unrenderable snapshot failure"
    if type(args) is not tuple:
        return "unrenderable snapshot failure"

    rendered = ""
    for arg in args:
        if type(arg) is not str:
            continue
        separator = "; " if rendered else ""
        remaining = 4096 - len(rendered) - len(separator)
        if remaining <= 0:
            break
        if len(arg) > remaining:
            if remaining >= 3:
                rendered += separator + arg[: remaining - 3] + "..."
            else:
                rendered += separator + arg[:remaining]
            break
        rendered += separator + arg
    return rendered or "unrenderable snapshot failure"


def _trusted_failure_exception(
    exc: BaseException,
    context: str,
) -> ProbeError | ProtocolError | DifferentialMismatch:
    message = f"{context}; failure={_safe_exception_text(exc)}"
    if isinstance(exc, DifferentialMismatch):
        return DifferentialMismatch(message)
    if isinstance(exc, ProtocolError):
        return ProtocolError(message)
    return ProbeError(message)


def _snapshot_sequence(
    values: Sequence[Mapping[str, object]],
    label: str,
    *,
    deadline: float,
) -> tuple[Mapping[str, object], ...]:
    snapshot: list[Mapping[str, object]] = []
    try:
        _check_deadline(deadline, f"Administrative {label} snapshot")
        iterator = iter(values)
        while True:
            _check_deadline(deadline, f"Administrative {label} snapshot")
            try:
                item = next(iterator)
            except StopIteration:
                break
            _check_deadline(deadline, f"Administrative {label} snapshot")
            if len(snapshot) >= MAX_RANDOM_CANDIDATE_COUNT + 4096:
                raise ProbeError(f"{label} sequence exceeds the bounded request count")
            snapshot.append(copy.deepcopy(item))
            _check_deadline(deadline, f"Administrative {label} snapshot")
    except (ProbeError, ProtocolError, DifferentialMismatch):
        raise
    except BaseException as exc:
        raise ProbeError(
            f"{label} sequence snapshot failed: {_safe_exception_text(exc)}"
        ) from exc
    return tuple(snapshot)


def _iter_complete_response_lines(
    stdout: str,
    *,
    deadline: float,
):
    start = 0
    while start < len(stdout):
        _check_deadline(deadline, "Administrative response line scan")
        end = stdout.find("\n", start)
        if end < 0:
            return
        yield stdout[start:end]
        start = end + 1


def _validated_response_prefix_count(
    stdout: str,
    requests: Sequence[Mapping[str, object]],
    expected: Sequence[Mapping[str, object]],
    request_lines: Sequence[str],
    manifest: Mapping[str, object],
    *,
    deadline: float,
) -> int:
    count = 0
    for index, response_line in enumerate(
        _iter_complete_response_lines(stdout, deadline=deadline)
    ):
        if index >= len(requests) or index >= len(expected):
            break
        try:
            parse_canonical_response_line(
                response_line,
                requests[index],
                expected[index],
                deadline=deadline,
                manifest=manifest,
                request_line=(
                    request_lines[index]
                    if index < len(request_lines)
                    else canonical_json(requests[index])
                ),
            )
        except (ProbeError, ProtocolError, DifferentialMismatch):
            break
        count += 1
    return count


def run_probe_requests(
    probe_path: Path | str,
    requests: Sequence[Mapping[str, object]],
    expected: Sequence[Mapping[str, object]],
    *,
    manifest: Mapping[str, object],
    deadline: float,
) -> tuple[list[Mapping[str, object]], str]:
    """Run v5 JSONL through the checkout-pinned hardened process supervisor."""

    request_snapshot: tuple[Mapping[str, object], ...] = ()
    expected_snapshot: tuple[Mapping[str, object], ...] = ()
    request_lines: list[str] = []

    def setup_failure_response_index() -> int:
        if len(request_lines) < len(request_snapshot):
            return len(request_lines)
        return 0

    try:
        _check_deadline(deadline, "Administrative probe setup")
        request_snapshot = _snapshot_sequence(
            requests, "request", deadline=deadline
        )
        expected_snapshot = _snapshot_sequence(
            expected, "expected response", deadline=deadline
        )
        requests = request_snapshot
        expected = expected_snapshot
        if len(expected) != len(requests):
            raise ProbeError(
                f"expected response count differs: {len(expected)} != {len(requests)}"
            )
        probe = Path(probe_path).expanduser().resolve()
        if not probe.is_file():
            raise ProbeError(f"probe executable does not exist: {probe}")
        request_lines = []
        for item in requests:
            _check_deadline(deadline, "Administrative probe request serialization")
            request_lines.append(canonical_json(validate_episode_request(item)))
        if len(request_lines) != len(requests):
            raise ProbeError(
                f"request sequence iteration count differs: "
                f"{len(request_lines)} != {len(requests)}"
            )
        completed = hardened._run_probe_process(
            [str(probe)], "".join(line + "\n" for line in request_lines), deadline
        )
    except hardened.ProbeOutputDecodeError as exc:
        context = _probe_failure_context(
            manifest,
            request_snapshot,
            request_lines,
            expected_snapshot,
            response_index=setup_failure_response_index(),
            completed_response_count=0,
        )
        raise ProbeError(
            f"{context}; failure={_safe_exception_text(exc)}"
        ) from exc
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        context = _probe_failure_context(
            manifest,
            request_snapshot,
            request_lines,
            expected_snapshot,
            response_index=setup_failure_response_index(),
            completed_response_count=0,
        )
        raise ProbeError(
            f"{context}; failure={_safe_exception_text(exc)}"
        ) from exc
    except BaseException as exc:
        context = _probe_failure_context(
            manifest,
            request_snapshot,
            request_lines,
            expected_snapshot,
            response_index=setup_failure_response_index(),
            completed_response_count=0,
        )
        raise ProbeError(
            f"{context}; failure={_safe_exception_text(exc)}"
        ) from exc

    def completed_prefix_count() -> int:
        return _validated_response_prefix_count(
            completed.stdout,
            requests,
            expected,
            request_lines,
            manifest,
            deadline=deadline,
        )

    if completed.returncode != 0:
        completed_count = completed_prefix_count()
        index = min(completed_count, max(0, len(requests) - 1))
        context = _probe_failure_context(
            manifest,
            request_snapshot,
            request_lines,
            expected_snapshot,
            response_index=index,
            completed_response_count=completed_count,
        )
        raise ProbeError(
            f"{context}; failure=probe exited with {completed.returncode}; "
            f"stderr={completed.stderr!r}"
        )
    if completed.stderr:
        completed_count = completed_prefix_count()
        index = min(completed_count, max(0, len(requests) - 1))
        context = _probe_failure_context(
            manifest,
            request_snapshot,
            request_lines,
            expected_snapshot,
            response_index=index,
            completed_response_count=completed_count,
        )
        raise ProbeError(
            f"{context}; failure=probe emitted successful-run diagnostics; "
            f"stderr={completed.stderr!r}"
        )
    if not completed.stdout.endswith("\n"):
        completed_count = completed_prefix_count()
        index = min(completed_count, max(0, len(requests) - 1))
        context = _probe_failure_context(
            manifest,
            request_snapshot,
            request_lines,
            expected_snapshot,
            response_index=index,
            completed_response_count=completed_count,
        )
        raise ProbeError(f"{context}; failure=probe output is not newline-terminated")
    _check_deadline(deadline, "Administrative response line counting")
    response_line_count = completed.stdout.count("\n")
    _check_deadline(deadline, "Administrative response line counting")
    if response_line_count != len(requests):
        completed_count = completed_prefix_count()
        index = min(completed_count, max(0, len(requests) - 1))
        context = _probe_failure_context(
            manifest,
            request_snapshot,
            request_lines,
            expected_snapshot,
            response_index=index,
            completed_response_count=completed_count,
        )
        raise ProbeError(
            f"{context}; failure=probe response line count differs: "
            f"{response_line_count} != {len(requests)}"
        )

    digest = hashlib.sha256()
    _digest_record(digest, canonical_json(manifest))
    responses: list[Mapping[str, object]] = []
    response_lines = _iter_complete_response_lines(
        completed.stdout, deadline=deadline
    )
    for index, (request, expected_response, request_line, response_line) in enumerate(
        zip(requests, expected, request_lines, response_lines)
    ):
        try:
            parsed = parse_canonical_response_line(
                response_line,
                request,
                expected_response,
                deadline=deadline,
                manifest=manifest,
                request_line=request_line,
            )
        except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
            prefix = getattr(
                exc,
                "_administrative_candidate_prefix_length",
                0,
            )
            context = (
                f"responseIndex={index}; completedResponseCount={index}; "
                + _trusted_context(
                    manifest, request, request_line, prefix, expected_response
                )
            )
            raise _trusted_failure_exception(exc, context) from exc
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
                expected,
                response_index=len(responses),
                completed_response_count=len(responses),
            )
        )
    try:
        _check_deadline(deadline, "Administrative transcript digest completion")
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        context = _probe_failure_context(
            manifest,
            request_snapshot,
            request_lines,
            expected_snapshot,
            response_index=max(0, len(responses) - 1),
            completed_response_count=len(responses),
        )
        raise _trusted_failure_exception(exc, context) from exc
    return responses, digest.hexdigest()


def transform_request(
    request: Mapping[str, object],
    symmetry: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "Administrative D4 request transformation")
    transformed = copy.deepcopy(request)
    transformed["episodeId"] = episode_id
    transformed["steps"] = []
    for step in request["steps"]:
        candidate = step["candidate"]
        if candidate["kind"] == "ACTION":
            next_candidate = {
                "kind": "ACTION",
                "action": transform_action(
                    candidate["action"], request["boardSize"], symmetry
                ),
            }
        else:
            next_candidate = copy.deepcopy(candidate)
        transformed["steps"].append(
            {
                "candidateActor": step["candidateActor"],
                "candidate": next_candidate,
            }
        )
    return dict(validate_episode_request(transformed))


def _transform_administrative_transition(
    transition: dict[str, object], board_size: int, symmetry: int
) -> None:
    event = transition["terminalEvent"]
    if event is None:
        return
    hardened._transform_occupancy(event["stableOccupancy"], board_size, symmetry)
    for stone in event["stableStones"]:
        stone["point"] = transform_board_point(board_size, stone["point"], symmetry)
    event["stableStones"].sort(key=lambda stone: stone["point"])


def transform_response(
    response: Mapping[str, object],
    request: Mapping[str, object],
    symmetry: int,
    episode_id: str,
    *,
    deadline: float | None = None,
) -> dict[str, object]:
    _check_deadline(deadline, "Administrative D4 response transformation")
    transformed = copy.deepcopy(response)
    transformed["episodeId"] = episode_id
    board_size = request["boardSize"]

    def state(value: dict[str, object]) -> None:
        ranges = value.pop("legalActionRanges")
        v4.v3._transform_state(value, board_size, symmetry)
        value["legalActionRanges"] = v4.transform_legal_action_ranges(
            ranges, symmetry, deadline=deadline
        )

    state(transformed["initialState"])
    for step, observation in zip(request["steps"], transformed["observations"]):
        if step["candidate"]["kind"] == "ACTION":
            v4.v3._transform_transition(
                observation["transition"], board_size, symmetry
            )
        else:
            _transform_administrative_transition(
                observation["transition"], board_size, symmetry
            )
        state(observation["state"])
    return transformed


def _request(
    episode_id: str,
    steps: Sequence[Mapping[str, object]],
    *,
    board_size: int = 9,
    initial_quotas: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return dict(
        validate_episode_request(
            {
                "boardSize": board_size,
                "episodeId": episode_id,
                "initialQuotas": copy.deepcopy(initial_quotas or quotas()),
                "protocolVersion": PROTOCOL_VERSION,
                "steps": copy.deepcopy(list(steps)),
            }
        )
    )


def _normal(board_size: int, x: int, y: int) -> dict[str, object]:
    return board_action_v1(board_size, x, y, ActionKind.NORMAL)


def _checkerboard_points(board_size: int) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(board_size)
        for x in range(board_size)
        if (x + y) % 2 == 0
    ]


def _threshold_steps(*, continuation: str | None = None) -> list[dict[str, object]]:
    board_size = 9
    threshold = (150 * board_size * board_size + 180) // 361
    points = _checkerboard_points(board_size)
    steps: list[dict[str, object]] = []
    if continuation is None:
        for index in range(threshold):
            actor = Color.BLACK if index % 2 == 0 else Color.WHITE
            steps.append(action_candidate(actor, _normal(board_size, *points[index])))
        return steps

    for index in range(threshold - 2):
        actor = Color.BLACK if index % 2 == 0 else Color.WHITE
        steps.append(action_candidate(actor, _normal(board_size, *points[index])))
    owner = Color.BLACK if (threshold - 2) % 2 == 0 else Color.WHITE
    steps.append(
        action_candidate(
            owner,
            board_action_v1(
                board_size, *points[threshold - 2], ActionKind.DOUBLE_START
            ),
        )
    )
    if continuation == "NORMAL":
        action = _normal(board_size, *points[threshold - 1])
    elif continuation == "PASS":
        action = action_v1(PASS_ACTION_ID)
    else:
        raise ValueError("continuation must be NORMAL, PASS, or None")
    steps.append(action_candidate(owner, action))
    return steps


def _genesis_reexecution_base_steps() -> list[dict[str, object]]:
    return [
        action_candidate(Color.BLACK, _normal(9, 0, 0)),
        action_candidate(
            Color.WHITE, board_action_v1(9, 2, 1, ActionKind.DOUBLE_START)
        ),
        action_candidate(Color.WHITE, _normal(9, 3, 1)),
        action_candidate(
            Color.BLACK, board_action_v1(9, 5, 4, ActionKind.EIGHTWAY)
        ),
        action_candidate(Color.WHITE, action_v1(PASS_ACTION_ID)),
        action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
        action_candidate(Color.WHITE, action_v1(PASS_ACTION_ID)),
        administrative_candidate(Color.BLACK, "RESIGNATION"),
    ]


def genesis_reexecution_requests() -> list[dict[str, object]]:
    steps = _genesis_reexecution_base_steps()
    specifications = (
        ("genesis-collapse-prefix", 1),
        ("genesis-pending-double-prefix", 2),
        ("genesis-ordinary-prefix", 6),
        ("genesis-one-pass-ordinary-prefix", 7),
        ("genesis-terminal-prefix", 8),
    )
    requests = [
        _request("genesis-administrative-base", steps),
        *(_request(episode_id, steps[:length]) for episode_id, length in specifications),
        _request("genesis-full-reexecution", steps),
        _request(
            "genesis-extended-reexecution",
            steps
            + [
                administrative_candidate(Color.WHITE, "TIMEOUT"),
                action_candidate(Color.BLACK, _normal(9, 8, 8)),
            ],
        ),
    ]
    return requests


def administrative_d4_base_request(board_size: int) -> dict[str, object]:
    steps = [
        action_candidate(
            Color.BLACK, board_action_v1(board_size, 1, 2, ActionKind.IMMORTAL)
        ),
        action_candidate(Color.WHITE, _normal(board_size, board_size - 2, board_size - 3)),
        action_candidate(
            Color.BLACK, board_action_v1(board_size, 3, 1, ActionKind.DOUBLE_START)
        ),
        action_candidate(Color.BLACK, _normal(board_size, 4, 1)),
        action_candidate(
            Color.WHITE,
            board_action_v1(board_size, 2, board_size - 2, ActionKind.EIGHTWAY),
        ),
        action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
        action_candidate(Color.WHITE, action_v1(PASS_ACTION_ID)),
        action_candidate(Color.BLACK, _normal(board_size, board_size - 3, 2)),
        administrative_candidate(Color.BLACK, "TIMEOUT"),
    ]
    return _request(
        f"curated-admin-d4-{board_size}-base", steps, board_size=board_size
    )


def generate_curated_episodes(
    *, deadline: float | None = None
) -> list[dict[str, object]]:
    """Generate bounded boundary, ordering, re-execution, and D4 episodes."""

    _check_deadline(deadline, "Administrative curated corpus generation")
    threshold_steps = _threshold_steps()
    pending_threshold_steps = _threshold_steps(continuation="NORMAL")
    episodes = [
        _request(
            "admin-initial-resignation-black",
            [
                administrative_candidate(Color.BLACK, "RESIGNATION"),
                administrative_candidate(Color.WHITE, "TIMEOUT"),
                action_candidate(Color.BLACK, _normal(9, 0, 0)),
            ],
        ),
        _request(
            "admin-initial-timeout-noncurrent-white",
            [administrative_candidate(Color.WHITE, "TIMEOUT")],
        ),
        _request(
            "admin-after-normal-noncurrent-loser",
            [
                action_candidate(Color.BLACK, _normal(9, 0, 0)),
                administrative_candidate(Color.BLACK, "RESIGNATION"),
                action_candidate(Color.WHITE, _normal(9, 1, 0)),
            ],
        ),
        _request(
            "admin-before-normal",
            [
                administrative_candidate(Color.WHITE, "RESIGNATION"),
                action_candidate(Color.BLACK, _normal(9, 0, 0)),
            ],
        ),
        _request(
            "admin-after-special",
            [
                action_candidate(
                    Color.BLACK, board_action_v1(9, 2, 2, ActionKind.IMMORTAL)
                ),
                administrative_candidate(Color.WHITE, "TIMEOUT"),
            ],
        ),
        _request(
            "admin-before-special",
            [
                administrative_candidate(Color.BLACK, "TIMEOUT"),
                action_candidate(
                    Color.BLACK, board_action_v1(9, 2, 2, ActionKind.EIGHTWAY)
                ),
            ],
        ),
        _request(
            "admin-after-one-collapse-pass",
            [
                action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
                administrative_candidate(Color.BLACK, "RESIGNATION"),
            ],
        ),
        _request(
            "admin-before-pass",
            [
                administrative_candidate(Color.WHITE, "TIMEOUT"),
                action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
            ],
        ),
        _request(
            "admin-pending-double-noncurrent-loser",
            [
                action_candidate(
                    Color.BLACK, board_action_v1(9, 4, 4, ActionKind.DOUBLE_START)
                ),
                administrative_candidate(Color.WHITE, "RESIGNATION"),
                action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
            ],
        ),
        _request(
            "admin-ordinary-boundary-after-early-second-pass",
            [
                action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
                action_candidate(Color.WHITE, action_v1(PASS_ACTION_ID)),
                administrative_candidate(Color.WHITE, "TIMEOUT"),
            ],
        ),
        _request(
            "admin-one-pass-ordinary-boundary",
            [
                action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
                action_candidate(Color.WHITE, action_v1(PASS_ACTION_ID)),
                action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
                administrative_candidate(Color.BLACK, "RESIGNATION"),
            ],
        ),
        _request(
            "admin-after-threshold-action",
            threshold_steps
            + [administrative_candidate(Color.WHITE, "TIMEOUT")],
        ),
        _request(
            "admin-before-final-threshold-action-at-a-t-minus-1",
            threshold_steps[:-1]
            + [
                administrative_candidate(
                    threshold_steps[-1]["candidateActor"], "RESIGNATION"
                ),
                threshold_steps[-1],
            ],
        ),
        _request(
            "admin-pending-double-current-loser-timeout-at-a-t-minus-1",
            pending_threshold_steps[:-1]
            + [
                administrative_candidate(
                    pending_threshold_steps[-1]["candidateActor"], "TIMEOUT"
                ),
                pending_threshold_steps[-1],
            ],
        ),
        _request(
            "admin-after-pending-normal-continuation-at-threshold",
            pending_threshold_steps
            + [administrative_candidate(Color.BLACK, "RESIGNATION")],
        ),
        _request(
            "admin-after-pending-pass-continuation-at-threshold",
            _threshold_steps(continuation="PASS")
            + [administrative_candidate(Color.BLACK, "TIMEOUT")],
        ),
        _request(
            "score-second-ordinary-pass-then-admin-and-action-reject",
            [
                action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
                action_candidate(Color.WHITE, action_v1(PASS_ACTION_ID)),
                action_candidate(Color.BLACK, action_v1(PASS_ACTION_ID)),
                action_candidate(Color.WHITE, action_v1(PASS_ACTION_ID)),
                administrative_candidate(Color.BLACK, "RESIGNATION"),
                administrative_candidate(Color.WHITE, "TIMEOUT"),
                action_candidate(Color.BLACK, _normal(9, 0, 0)),
            ],
        ),
    ]
    episodes.extend(genesis_reexecution_requests())
    for board_size in (9, 13, 19):
        base = administrative_d4_base_request(board_size)
        for symmetry in range(8):
            episodes.append(
                transform_request(
                    base,
                    symmetry,
                    f"curated-admin-d4-{board_size}-{symmetry}",
                    deadline=deadline,
                )
            )
    return episodes


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
            f"candidate_count must be in {MIN_RANDOM_CANDIDATE_COUNT}.."
            f"{MAX_RANDOM_CANDIDATE_COUNT}"
        )
    _, encoded_seed = _validate_seed(seed)
    rng = Sha256CounterRng(GENERATOR_DOMAIN + encoded_seed)
    seed_tag = hashlib.sha256(encoded_seed).hexdigest()[:12]
    episodes: list[dict[str, object]] = []
    generated = 0
    sequence = 0
    while generated < candidate_count:
        _check_deadline(deadline, "Administrative random corpus generation")
        count = min(16, candidate_count - generated)
        board_size = (9, 13, 19)[rng.randbelow(3)]
        initial = quotas(
            black_immortal=rng.randbelow(3),
            white_immortal=rng.randbelow(3),
            black_double=rng.randbelow(3),
            white_double=rng.randbelow(3),
            black_eightway=rng.randbelow(3),
            white_eightway=rng.randbelow(3),
        )
        steps = []
        for _ in range(count):
            actor = (Color.BLACK, Color.WHITE)[rng.randbelow(2)]
            mode = rng.randbelow(8)
            if mode == 0:
                steps.append(administrative_candidate(actor, "RESIGNATION"))
            elif mode == 1:
                steps.append(administrative_candidate(actor, "TIMEOUT"))
            else:
                steps.append(action_candidate(actor, action_v1(rng.randbelow(ACTION_COUNT))))
        episodes.append(
            _request(
                f"random-admin-{seed_tag}-{sequence:06d}",
                steps,
                board_size=board_size,
                initial_quotas=initial,
            )
        )
        generated += count
        sequence += 1
    return episodes


def _validate_d4_reachability_anchor(
    response: Mapping[str, object], board_size: int, side: str
) -> None:
    observations = response["observations"]
    if len(observations) != 9 or any(
        not observation["transition"]["accepted"] for observation in observations
    ):
        raise ProtocolError(
            f"{side} administrative D4 {board_size} base is not fully reachable"
        )
    for index, kind in ((0, "IMMORTAL"), (2, "DOUBLE_START"), (4, "EIGHTWAY")):
        transition = observations[index]["transition"]
        if (
            transition["transitionKind"] != "ATOMIC_ACTION"
            or transition["action"]["kind"] != kind
        ):
            raise ProtocolError(
                f"{side} administrative D4 {board_size} lacks accepted {kind} anchor"
            )
    settlement = observations[6]["transition"]["settlement"]
    if (
        settlement is None
        or settlement["triggerReason"] != "PRE_THRESHOLD_TWO_PASSES"
        or observations[6]["state"]["phase"] != "ORDINARY_PLAY"
    ):
        raise ProtocolError(
            f"{side} administrative D4 {board_size} lacks reachable settlement"
        )
    if (
        observations[8]["transition"]["transitionKind"] != "IMMEDIATE_TERMINAL"
        or observations[8]["state"]["terminal"]["reason"] != "TIMEOUT"
    ):
        raise ProtocolError(
            f"{side} administrative D4 {board_size} lacks reachable timeout terminal"
        )


def _compare_reexecution_and_d4(
    expected_by_id: Mapping[str, Mapping[str, object]],
    actual_by_id: Mapping[str, Mapping[str, object]],
    requests_by_id: Mapping[str, Mapping[str, object]],
    manifest: Mapping[str, object],
    *,
    deadline: float | None = None,
) -> None:
    base_id = "genesis-administrative-base"
    prefix_specs = (
        ("genesis-collapse-prefix", 1),
        ("genesis-pending-double-prefix", 2),
        ("genesis-ordinary-prefix", 6),
        ("genesis-one-pass-ordinary-prefix", 7),
        ("genesis-terminal-prefix", 8),
    )
    active_id = base_id
    try:
        for side, responses in (("python", expected_by_id), ("cpp", actual_by_id)):
            base = responses[base_id]
            for prefix_id, length in prefix_specs:
                active_id = prefix_id
                difference = hardened._first_difference(
                    base["observations"][:length],
                    responses[prefix_id]["observations"],
                    deadline=deadline,
                )
                if difference is not None:
                    raise DifferentialMismatch(
                        f"{side} genesis candidate prefix differs: {difference}"
                    )
            active_id = "genesis-full-reexecution"
            reexecuted = copy.deepcopy(responses[active_id])
            reexecuted["episodeId"] = base_id
            difference = hardened._first_difference(base, reexecuted, deadline=deadline)
            if difference is not None:
                raise DifferentialMismatch(
                    f"{side} full candidate reexecution differs: {difference}"
                )
            active_id = "genesis-extended-reexecution"
            suffix = responses[active_id]
            difference = hardened._first_difference(
                base["observations"], suffix["observations"][:8], deadline=deadline
            )
            if difference is not None:
                raise DifferentialMismatch(
                    f"{side} extended genesis reexecution rewrote its prefix: {difference}"
                )

        for board_size in (9, 13, 19):
            base_id = f"curated-admin-d4-{board_size}-0"
            base_request = requests_by_id[base_id]
            for side, responses in (("python", expected_by_id), ("cpp", actual_by_id)):
                _validate_d4_reachability_anchor(
                    responses[base_id], board_size, side
                )
            for symmetry in range(8):
                target_id = f"curated-admin-d4-{board_size}-{symmetry}"
                inverse = INVERSE_SYMMETRY_IDS[symmetry]
                for side, responses in (("python", expected_by_id), ("cpp", actual_by_id)):
                    active_id = target_id
                    transformed = transform_response(
                        responses[base_id],
                        base_request,
                        symmetry,
                        target_id,
                        deadline=deadline,
                    )
                    difference = hardened._first_difference(
                        transformed, responses[target_id], deadline=deadline
                    )
                    if difference is not None:
                        raise DifferentialMismatch(
                            f"{side} administrative D4 {board_size}/{symmetry} differs: "
                            f"{difference}"
                        )
                    restored = transform_response(
                        responses[target_id],
                        requests_by_id[target_id],
                        inverse,
                        base_id,
                        deadline=deadline,
                    )
                    difference = hardened._first_difference(
                        responses[base_id], restored, deadline=deadline
                    )
                    if difference is not None:
                        raise DifferentialMismatch(
                            f"{side} administrative D4 inverse {board_size}/{symmetry} "
                            f"differs: {difference}"
                        )
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        request = requests_by_id[active_id]
        response = expected_by_id.get(active_id)
        trusted = _trusted_context(
            manifest,
            request,
            canonical_json(request),
            len(request["steps"]),
            response,
        )
        raise _trusted_failure_exception(exc, trusted) from exc


def run_differential(
    probe_path: Path | str,
    *,
    seed: str = DEFAULT_SEED,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, object]:
    deadline = hardened._new_deadline(timeout_seconds)
    seed, _ = _validate_seed(seed)
    manifest = {
        "generatorDomainSha256": hashlib.sha256(GENERATOR_DOMAIN).hexdigest(),
        "generatorVersion": GENERATOR_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": candidate_count,
        "seed": seed,
    }
    curated = generate_curated_episodes(deadline=deadline)
    random_episodes = generate_random_episodes(
        seed, candidate_count, deadline=deadline
    )
    episodes = curated + random_episodes
    request_lines = [canonical_json(request) for request in episodes]
    expected: list[dict[str, object]] = []
    context_index = 0
    try:
        for context_index, request in enumerate(episodes):
            expected.append(oracle_episode_response(request, deadline=deadline))
    except (ProbeError, ProtocolError, DifferentialMismatch) as exc:
        request = episodes[context_index]
        prefix = getattr(
            exc,
            "_administrative_candidate_prefix_length",
            0,
        )
        expected_response = expected[context_index] if context_index < len(expected) else None
        trusted = (
            f"responseIndex={context_index}; completedResponseCount=0; "
            + _trusted_context(
                manifest,
                request,
                request_lines[context_index],
                prefix,
                expected_response,
            )
        )
        raise _trusted_failure_exception(exc, trusted) from exc

    actual, digest = run_probe_requests(
        probe_path,
        episodes,
        expected,
        manifest=manifest,
        deadline=deadline,
    )

    action_accepted = action_rejected = 0
    administrative_accepted = administrative_rejected = 0
    terminal_reasons: dict[str, int] = {}
    errors: dict[str, int] = {}
    for context_index, (request, left, right) in enumerate(
        zip(episodes, expected, actual)
    ):
        difference = hardened._first_difference(left, right, deadline=deadline)
        if difference is not None:
            prefix = _first_observation_difference_prefix(
                left, right, deadline=deadline
            )
            trusted = (
                f"responseIndex={context_index}; completedResponseCount={len(actual)}; "
                + _trusted_context(
                    manifest,
                    request,
                    request_lines[context_index],
                    prefix,
                    left,
                )
            )
            raise DifferentialMismatch(
                f"{trusted}; episode={request['episodeId']}; firstDifference={difference}"
            )
        for step, observation in zip(request["steps"], left["observations"]):
            transition = observation["transition"]
            if step["candidate"]["kind"] == "ACTION":
                if transition["accepted"]:
                    action_accepted += 1
                else:
                    action_rejected += 1
            else:
                if transition["accepted"]:
                    administrative_accepted += 1
                    reason = step["candidate"]["kind"]
                    terminal_reasons[reason] = terminal_reasons.get(reason, 0) + 1
                else:
                    administrative_rejected += 1
            error = transition["errorCode"] or "NONE"
            errors[error] = errors.get(error, 0) + 1

    expected_by_id = {response["episodeId"]: response for response in expected}
    actual_by_id = {response["episodeId"]: response for response in actual}
    requests_by_id = {request["episodeId"]: request for request in episodes}
    _compare_reexecution_and_d4(
        expected_by_id,
        actual_by_id,
        requests_by_id,
        manifest,
        deadline=deadline,
    )

    curated_count = sum(len(request["steps"]) for request in curated)
    total_count = curated_count + candidate_count
    classified = (
        action_accepted
        + action_rejected
        + administrative_accepted
        + administrative_rejected
    )
    if classified != total_count:
        raise AssertionError("administrative summary candidate counts are ambiguous")
    stable_state_count = total_count + len(episodes)
    _check_deadline(deadline, "Administrative summary projection")
    return {
        "actionAccepted": action_accepted,
        "actionRejected": action_rejected,
        "administrativeAccepted": administrative_accepted,
        "administrativeRejected": administrative_rejected,
        "candidateCount": total_count,
        "candidateOrderingModel": "ORDERED_SEQUENCE_ONLY",
        "genesisPrefixFullExtendedReexecutionExact": True,
        "curatedCandidateCount": curated_count,
        "d4BoardSizes": [9, 13, 19],
        "d4MetamorphicAndInverses": True,
        "episodeCount": len(episodes),
        "errorCounts": errors,
        "fullLegalMaskComparedAtEveryStableState": True,
        "gateProdClaimed": False,
        "gateRule1MClaimed": False,
        "generatorDomainSha256": manifest["generatorDomainSha256"],
        "generatorVersion": GENERATOR_VERSION,
        "legalBitComparisons": stable_state_count * ACTION_COUNT,
        "operationalFailureSynthesizesSemanticTimeout": False,
        "protocolVersion": PROTOCOL_VERSION,
        "randomCandidateCount": candidate_count,
        "scope": "ADMINISTRATIVE_TERMINATION_DIFF_V5_UNFROZEN_TEST_ONLY",
        "seed": seed,
        "sha256": digest,
        "stableStateLegalityComparisons": stable_state_count,
        "terminalReasonCounts": terminal_reasons,
        "unfrozenTestOnly": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the bounded test-only UNFROZEN administrative-termination v5 "
            "differential"
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
        try:
            diagnostic_seed, _ = _validate_seed(args.seed)
        except ValueError:
            diagnostic_seed = None
        seed_ascii_repr = ascii(args.seed)
        if len(seed_ascii_repr) > 2 * MAX_SEED_BYTES:
            seed_ascii_repr = seed_ascii_repr[: 2 * MAX_SEED_BYTES - 3] + "..."
        candidate_count = (
            args.candidate_count
            if -JSON_SAFE_INTEGER_MAX
            <= args.candidate_count
            <= JSON_SAFE_INTEGER_MAX
            else None
        )
        candidate_count_ascii_repr = ascii(args.candidate_count)
        if len(candidate_count_ascii_repr) > 64:
            candidate_count_ascii_repr = candidate_count_ascii_repr[:61] + "..."
        invocation = {
            "generatorDomainSha256": hashlib.sha256(GENERATOR_DOMAIN).hexdigest(),
            "generatorVersion": GENERATOR_VERSION,
            "protocolVersion": PROTOCOL_VERSION,
            "requestedRandomCandidateCount": candidate_count,
            "requestedRandomCandidateCountAsciiRepr": candidate_count_ascii_repr,
            "seed": diagnostic_seed,
            "seedInputAsciiRepr": seed_ascii_repr,
        }
        print(
            "Administrative-termination v5 differential failed: "
            f"{_safe_exception_text(exc)}; invocation={canonical_json(invocation)}",
            file=sys.stderr,
        )
        return 1
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
