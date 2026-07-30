"""Pure stdlib-only derivation of Collapse Go action legality.

The implementation intentionally rebuilds action geometry, mixed N4/N8
connectivity, liberties, Immortal protection, simultaneous captures, suicide,
and occupancy-only positional superko without using the transition reducer or
its decoding and group-scan helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

from .normal_pass_oracle import (
    CANVAS_SIZE,
    PASS_ACTION_ID,
    AbilityState,
    ActionKind,
    Color,
    OracleState,
    Phase,
    RejectionCode,
    SettlementState,
    StoneState,
)

_CANVAS_POINT_COUNT = CANVAS_SIZE * CANVAS_SIZE
_POINT_KINDS = (
    ActionKind.NORMAL,
    ActionKind.IMMORTAL,
    ActionKind.DOUBLE_START,
    ActionKind.EIGHTWAY,
)
_SPECIAL_KINDS = frozenset(
    (ActionKind.IMMORTAL, ActionKind.DOUBLE_START, ActionKind.EIGHTWAY)
)


@dataclass(frozen=True, slots=True)
class _Position:
    size: int
    black: frozenset[int]
    white: frozenset[int]
    immortal: frozenset[int]
    eightway: frozenset[int]
    history: frozenset[tuple[tuple[int, ...], tuple[int, ...]]]
    n4: tuple[tuple[int, ...], ...]
    n8: tuple[tuple[int, ...], ...]


def enumerate_action_legality(
    state: OracleState,
) -> tuple[RejectionCode | None, ...]:
    """Return the exact current-actor rejection code for all 1,445 actions.

    ``None`` denotes acceptance. Point actions outside the selected centered
    footprint retain ``POINT_OFF_BOARD`` precedence over every state-level
    rejection, including terminal states.
    """

    if not isinstance(state, OracleState):
        raise TypeError("state must be OracleState")
    if _is_action_before_automatic_transition(state):
        return (RejectionCode.INTERNAL_INVARIANT,) * (PASS_ACTION_ID + 1)

    result: list[RejectionCode | None] = [None] * (PASS_ACTION_ID + 1)
    offset = (CANVAS_SIZE - state.board.size) // 2
    position: _Position | None = None
    mechanics_cache: dict[tuple[ActionKind, int], RejectionCode | None] = {}

    for family, kind in enumerate(_POINT_KINDS):
        state_rejection = _state_rejection(state, kind)
        block_start = family * _CANVAS_POINT_COUNT
        mechanics_kind = (
            ActionKind.NORMAL if kind is ActionKind.DOUBLE_START else kind
        )
        for canvas_index in range(_CANVAS_POINT_COUNT):
            canvas_x = canvas_index % CANVAS_SIZE
            canvas_y = canvas_index // CANVAS_SIZE
            action_id = block_start + canvas_index
            if not (
                offset <= canvas_x < offset + state.board.size
                and offset <= canvas_y < offset + state.board.size
            ):
                result[action_id] = RejectionCode.POINT_OFF_BOARD
                continue
            if state_rejection is not None:
                result[action_id] = state_rejection
                continue

            board_point = (
                state.board.size * (canvas_y - offset) + canvas_x - offset
            )
            cache_key = (mechanics_kind, board_point)
            if cache_key not in mechanics_cache:
                if position is None:
                    position = _position_from_state(state)
                mechanics_cache[cache_key] = _point_rejection(
                    position,
                    state.actor,
                    mechanics_kind,
                    board_point,
                )
            result[action_id] = mechanics_cache[cache_key]

    result[PASS_ACTION_ID] = _state_rejection(state, ActionKind.PASS)
    legality = tuple(result)
    if len(legality) != PASS_ACTION_ID + 1:
        raise AssertionError("action legality must contain exactly 1,445 entries")
    return legality


def derive_legal_mask(state: OracleState) -> tuple[bool, ...]:
    """Return the exact current-actor 1,445-bit legality mask."""

    return tuple(code is None for code in enumerate_action_legality(state))


def _is_action_before_automatic_transition(state: OracleState) -> bool:
    if state.phase is Phase.COLLAPSE_PLAY:
        threshold = _settlement_threshold(state.board.size)
        if state.atomic_action_count == threshold:
            return True
        return (
            state.atomic_action_count < threshold
            and state.consecutive_passes == 2
        )
    return (
        state.phase is Phase.ORDINARY_PLAY
        and state.consecutive_passes == 2
    )


def _state_rejection(
    state: OracleState,
    kind: ActionKind,
) -> RejectionCode | None:
    if state.phase is Phase.TERMINAL:
        return RejectionCode.TERMINAL_STATE
    if state.phase is Phase.ORDINARY_PLAY and kind in _SPECIAL_KINDS:
        return RejectionCode.INVALID_PHASE
    if state.pending_double is not None and kind not in (
        ActionKind.NORMAL,
        ActionKind.PASS,
    ):
        return RejectionCode.DOUBLE_CONTINUATION_KIND_FORBIDDEN
    if kind in _SPECIAL_KINDS:
        if (
            kind is ActionKind.DOUBLE_START
            and state.atomic_action_count + 2 > _settlement_threshold(state.board.size)
        ):
            return RejectionCode.DOUBLE_THRESHOLD
        actor = state.actor
        if actor is None:
            raise AssertionError("nonterminal action legality requires a current actor")
        quotas = (
            state.remaining_quotas.black
            if actor is Color.BLACK
            else state.remaining_quotas.white
        )
        if kind is ActionKind.IMMORTAL:
            remaining = quotas.immortal
        elif kind is ActionKind.DOUBLE_START:
            remaining = quotas.double_start
        else:
            remaining = quotas.eightway
        if remaining == 0:
            return RejectionCode.QUOTA_EXHAUSTED
    return None


def _position_from_state(state: OracleState) -> _Position:
    size = state.board.size
    stone_by_point = {stone.point: stone for stone in state.board.stones}
    immortal: set[int] = set()
    eightway: set[int] = set()
    for event in state.ledger:
        if event.kind not in (ActionKind.IMMORTAL, ActionKind.EIGHTWAY):
            continue
        if (
            event.ability_state is not AbilityState.ARMED
            or event.stone_state is not StoneState.ON_BOARD
            or event.settlement_state is not SettlementState.PENDING
            or event.tombstone
        ):
            continue
        source = stone_by_point.get(event.source_point)
        if (
            source is None
            or source.source_id != event.source_stone_id
            or source.color is not event.owner
            or source.origin_kind is not event.kind
            or source.special_event_id != event.event_id
        ):
            continue
        if event.kind is ActionKind.IMMORTAL:
            immortal.add(source.point)
        else:
            eightway.add(source.point)

    return _Position(
        size=size,
        black=frozenset(state.board.occupancy.black),
        white=frozenset(state.board.occupancy.white),
        immortal=frozenset(immortal),
        eightway=frozenset(eightway),
        history=frozenset((entry.black, entry.white) for entry in state.psk_history),
        n4=tuple(_orthogonal_neighbors(size, point) for point in range(size * size)),
        n8=tuple(_surrounding_neighbors(size, point) for point in range(size * size)),
    )


def _point_rejection(
    position: _Position,
    actor: Color | None,
    kind: ActionKind,
    point: int,
) -> RejectionCode | None:
    if point in position.black or point in position.white:
        return RejectionCode.POINT_OCCUPIED
    if actor is None:
        raise AssertionError("point mechanics require a current actor")

    black = set(position.black)
    white = set(position.white)
    actor_is_black = actor is Color.BLACK
    own = black if actor_is_black else white
    opponent = white if actor_is_black else black
    own.add(point)

    immortal = set(position.immortal)
    eightway = set(position.eightway)
    if kind is ActionKind.IMMORTAL:
        immortal.add(point)
    elif kind is ActionKind.EIGHTWAY:
        eightway.add(point)

    doomed: set[int] = set()
    for is_black, stones, liberties, protected in _groups(
        position,
        black,
        white,
        immortal,
        eightway,
    ):
        if is_black != actor_is_black and not liberties and not protected:
            doomed.update(stones)
    opponent.difference_update(doomed)

    own_survives = False
    for is_black, stones, liberties, protected in _groups(
        position,
        black,
        white,
        immortal,
        eightway,
    ):
        if is_black == actor_is_black and point in stones:
            own_survives = bool(liberties or protected)
            break
    if not own_survives:
        return RejectionCode.SUICIDE

    occupancy = (tuple(sorted(black)), tuple(sorted(white)))
    if occupancy in position.history:
        return RejectionCode.POSITIONAL_SUPERKO
    return None


def _groups(
    position: _Position,
    black: set[int],
    white: set[int],
    immortal: set[int],
    eightway: set[int],
):
    occupied = black | white
    visited: set[int] = set()
    for start in range(position.size * position.size):
        if start in visited or start not in occupied:
            continue
        is_black = start in black
        own = black if is_black else white
        stones: set[int] = set()
        liberties: set[int] = set()
        stack = [start]
        visited.add(start)
        while stack:
            current = stack.pop()
            stones.add(current)
            interface = (
                position.n8[current]
                if current in eightway
                else position.n4[current]
            )
            liberties.update(
                neighbor for neighbor in interface if neighbor not in occupied
            )
            orthogonal = position.n4[current]
            for neighbor in position.n8[current]:
                if neighbor not in own or neighbor in visited:
                    continue
                if (
                    neighbor in orthogonal
                    or current in eightway
                    or neighbor in eightway
                ):
                    visited.add(neighbor)
                    stack.append(neighbor)
        yield is_black, stones, liberties, bool(stones.intersection(immortal))


def _settlement_threshold(size: int) -> int:
    return (150 * size * size + 180) // 361


def _orthogonal_neighbors(size: int, point: int) -> tuple[int, ...]:
    x = point % size
    y = point // size
    neighbors: list[int] = []
    if x > 0:
        neighbors.append(point - 1)
    if x + 1 < size:
        neighbors.append(point + 1)
    if y > 0:
        neighbors.append(point - size)
    if y + 1 < size:
        neighbors.append(point + size)
    return tuple(neighbors)


def _surrounding_neighbors(size: int, point: int) -> tuple[int, ...]:
    x = point % size
    y = point // size
    return tuple(
        size * neighbor_y + neighbor_x
        for neighbor_y in range(max(0, y - 1), min(size, y + 2))
        for neighbor_x in range(max(0, x - 1), min(size, x + 2))
        if neighbor_x != x or neighbor_y != y
    )


__all__ = ["derive_legal_mask", "enumerate_action_legality"]
