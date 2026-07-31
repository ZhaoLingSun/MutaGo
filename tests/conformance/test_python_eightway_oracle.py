from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from mutago.collapse_go import (  # noqa: E402
    JSON_SAFE_INTEGER_MAX,
    PASS_ACTION_ID,
    AbilityState,
    ActionKind,
    Board,
    Color,
    Occupancy,
    OracleConfig,
    OracleState,
    Phase,
    PlayerQuotas,
    RejectionCode,
    SettlementReason,
    SettlementState,
    SettlementStepEvent,
    SpecialEvent,
    SpecialQuotas,
    Stone,
    StoneState,
    apply_action,
    new_game,
    scan_mixed_groups,
)
from mutago.collapse_go import normal_pass_oracle as oracle_module  # noqa: E402


KIND_CODE = {
    ActionKind.NORMAL: 0,
    ActionKind.IMMORTAL: 1,
    ActionKind.DOUBLE_START: 2,
    ActionKind.EIGHTWAY: 3,
}
INVERSE_SYMMETRY = (0, 1, 2, 3, 4, 6, 5, 7)


def point(size: int, x: int, y: int) -> int:
    return size * y + x


def action(
    kind: ActionKind,
    *,
    size: int = 9,
    x: int | None = None,
    y: int | None = None,
) -> dict[str, object]:
    if kind is ActionKind.PASS:
        return {
            "schemaVersion": "action-v1",
            "actionId": PASS_ACTION_ID,
            "kind": ActionKind.PASS.value,
        }
    if x is None or y is None:
        raise ValueError("point action requires board-local coordinates")
    offset = (19 - size) // 2
    return {
        "schemaVersion": "action-v1",
        "actionId": 361 * KIND_CODE[kind] + 19 * (y + offset) + x + offset,
        "kind": kind.value,
    }


def accept(state, actor: Color, envelope: dict[str, object]):
    transition = apply_action(state, actor, envelope)
    if not transition.accepted:
        raise AssertionError(f"unexpected rejection: {transition.rejection_code}")
    return transition


def special_event(
    action_number: int,
    owner: Color,
    kind: ActionKind,
    source_point: int,
    *,
    stone_state: StoneState = StoneState.ON_BOARD,
    settlement_state: SettlementState = SettlementState.PENDING,
) -> SpecialEvent:
    if kind is ActionKind.DOUBLE_START:
        ability_state = (
            AbilityState.CONSUMED
            if settlement_state is SettlementState.PENDING
            else AbilityState.INACTIVE
        )
        tombstone = True
    else:
        live = (
            stone_state is StoneState.ON_BOARD
            and settlement_state is SettlementState.PENDING
        )
        ability_state = AbilityState.ARMED if live else AbilityState.INACTIVE
        tombstone = not live
    return SpecialEvent(
        event_id=f"special-{action_number}",
        logical_order=action_number - 1,
        owner=owner,
        kind=kind,
        source_point=source_point,
        source_stone_id=f"stone-{action_number}",
        ability_state=ability_state,
        stone_state=stone_state,
        settlement_state=settlement_state,
        tombstone=tombstone,
    )


def transform_point(size: int, board_point: int, symmetry: int) -> int:
    x = board_point % size
    y = board_point // size
    if symmetry & 2:
        x = size - 1 - x
    if symmetry & 1:
        y = size - 1 - y
    if symmetry & 4:
        x, y = y, x
    return point(size, x, y)


def transform_occupancy(
    occupancy: Occupancy,
    size: int,
    symmetry: int,
) -> Occupancy:
    return Occupancy(
        black=tuple(
            sorted(transform_point(size, value, symmetry) for value in occupancy.black)
        ),
        white=tuple(
            sorted(transform_point(size, value, symmetry) for value in occupancy.white)
        ),
    )


def transform_stone(stone: Stone, size: int, symmetry: int) -> Stone:
    return replace(stone, point=transform_point(size, stone.point, symmetry))


def transform_state(state: OracleState, symmetry: int) -> OracleState:
    size = state.board.size
    return replace(
        state,
        board=Board.from_stones(
            size,
            (transform_stone(stone, size, symmetry) for stone in state.board.stones),
        ),
        ledger=tuple(
            replace(
                event,
                source_point=transform_point(size, event.source_point, symmetry),
            )
            for event in state.ledger
        ),
        psk_history=tuple(
            transform_occupancy(entry, size, symmetry) for entry in state.psk_history
        ),
    )


def group_projection(state: OracleState) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            group.color,
            group.stones,
            group.liberties,
            group.protected,
            group.immortal_anchor_points,
            group.eightway_anchor_points,
        )
        for group in scan_mixed_groups(state.board, state.ledger)
    )


def transform_group_projection(
    projection: tuple[tuple[object, ...], ...],
    size: int,
    symmetry: int,
) -> tuple[tuple[object, ...], ...]:
    transformed = []
    for color, stones, liberties, protected, immortal, eightway in projection:
        transformed.append(
            (
                color,
                tuple(sorted(transform_point(size, value, symmetry) for value in stones)),
                tuple(
                    sorted(transform_point(size, value, symmetry) for value in liberties)
                ),
                protected,
                tuple(
                    sorted(transform_point(size, value, symmetry) for value in immortal)
                ),
                tuple(
                    sorted(transform_point(size, value, symmetry) for value in eightway)
                ),
            )
        )
    return tuple(sorted(transformed, key=lambda value: value[1][0]))


def transform_action(
    envelope: dict[str, object],
    size: int,
    symmetry: int,
) -> dict[str, object]:
    if envelope["kind"] == ActionKind.PASS.value:
        return dict(envelope)
    action_id = envelope["actionId"]
    if type(action_id) is not int:
        raise TypeError("test action ID must be int")
    offset = (19 - size) // 2
    canvas_point = action_id % 361
    local = point(
        size,
        canvas_point % 19 - offset,
        canvas_point // 19 - offset,
    )
    transformed = transform_point(size, local, symmetry)
    return action(
        ActionKind(envelope["kind"]),
        size=size,
        x=transformed % size,
        y=transformed // size,
    )


def mixed_witness() -> tuple[Board, tuple[SpecialEvent, ...]]:
    stones = (
        Stone(0, Color.BLACK, 1, ActionKind.NORMAL),
        Stone(10, Color.BLACK, 2, ActionKind.NORMAL),
        Stone(30, Color.BLACK, 3, ActionKind.NORMAL),
        Stone(29, Color.BLACK, 4, ActionKind.IMMORTAL, "special-4"),
        Stone(40, Color.BLACK, 5, ActionKind.EIGHTWAY, "special-5"),
    )
    return Board.from_stones(9, stones), (
        special_event(4, Color.BLACK, ActionKind.IMMORTAL, 29),
        special_event(5, Color.BLACK, ActionKind.EIGHTWAY, 40),
    )


def zero_liberty_immortal_checkpoint() -> OracleState:
    """Reach the protected checkpoint through legal alternating actions."""

    size = 9
    immortal = (3, 3)
    target = (4, 4)
    white_points = sorted(
        (
            {
                (x, y)
                for y in range(3, 6)
                for x in range(3, 6)
            }
            - {immortal, target}
        )
        | {(3, 2), (2, 3)}
    )
    black_fillers = (
        (0, 0),
        (2, 0),
        (4, 0),
        (6, 0),
        (8, 0),
        (0, 8),
        (2, 8),
        (4, 8),
    )
    state = accept(
        new_game(OracleConfig(board_size=size)),
        Color.BLACK,
        action(ActionKind.IMMORTAL, x=immortal[0], y=immortal[1]),
    ).state
    for index, white_point in enumerate(white_points):
        state = accept(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=white_point[0], y=white_point[1]),
        ).state
        if index < len(black_fillers):
            black_point = black_fillers[index]
            state = accept(
                state,
                Color.BLACK,
                action(ActionKind.NORMAL, x=black_point[0], y=black_point[1]),
            ).state
    if state.actor is not Color.BLACK:
        raise AssertionError("legal mixed-protection prefix must hand play to Black")
    protected = next(
        group
        for group in scan_mixed_groups(state.board, state.ledger)
        if point(size, *immortal) in group.stones
    )
    if protected.liberties or not protected.protected:
        raise AssertionError("legal prefix did not reach the protected zero-liberty state")
    return state


def threshold_minus_one_state() -> OracleState:
    size = 9
    config = OracleConfig(
        board_size=size,
        quotas=PlayerQuotas(
            black=SpecialQuotas.zero(),
            white=SpecialQuotas(immortal=0, double_start=0, eightway=1),
        ),
    )
    black_points = (
        (0, 0),
        (2, 0),
        (4, 0),
        (6, 0),
        (8, 0),
        (0, 8),
        (2, 8),
        (4, 8),
        (6, 8),
        (8, 8),
        (0, 2),
        (0, 4),
        (0, 6),
        (4, 3),
        (3, 4),
        (5, 4),
        (4, 5),
    )
    white_points = (
        (1, 1),
        (3, 1),
        (5, 1),
        (7, 1),
        (1, 7),
        (3, 7),
        (5, 7),
        (7, 7),
        (2, 3),
        (6, 3),
        (2, 5),
        (6, 5),
        (1, 3),
        (7, 3),
        (1, 5),
        (7, 5),
    )
    state = new_game(config)
    for index, black_point in enumerate(black_points):
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=black_point[0], y=black_point[1]),
        ).state
        if index < len(white_points):
            white_point = white_points[index]
            state = accept(
                state,
                Color.WHITE,
                action(ActionKind.NORMAL, x=white_point[0], y=white_point[1]),
            ).state
    if state.atomic_action_count != state.threshold - 1:
        raise AssertionError("threshold prefix did not reach action T-1")
    return state


def global_settlement_checkpoint() -> OracleState:
    """Fabricated stable state used only to probe integrated settlement order."""

    size = 9
    immortal = point(size, 2, 2)
    eightway = point(size, 3, 3)
    old_double = point(size, 4, 4)
    black_points = {
        point(size, 2, 1),
        point(size, 1, 2),
        point(size, 3, 2),
        point(size, 2, 3),
        *(point(size, x, y) for y in range(2, 5) for x in range(2, 5)),
        point(size, 4, 3),
        point(size, 3, 4),
        point(size, 5, 4),
        point(size, 4, 5),
    } - {immortal, eightway, old_double}
    stones = [
        Stone(
            old_double,
            Color.WHITE,
            1,
            ActionKind.DOUBLE_START,
            "special-1",
        ),
        Stone(
            immortal,
            Color.WHITE,
            3,
            ActionKind.IMMORTAL,
            "special-3",
        ),
        Stone(
            eightway,
            Color.WHITE,
            4,
            ActionKind.EIGHTWAY,
            "special-4",
        ),
    ]
    stones.extend(
        Stone(value, Color.BLACK, action_number, ActionKind.NORMAL)
        for action_number, value in enumerate(sorted(black_points), start=6)
    )
    board = Board.from_stones(size, stones)
    action_count = max(stone.origin_action_number for stone in board.stones)
    ledger = (
        special_event(1, Color.WHITE, ActionKind.DOUBLE_START, old_double),
        special_event(3, Color.WHITE, ActionKind.IMMORTAL, immortal),
        special_event(4, Color.WHITE, ActionKind.EIGHTWAY, eightway),
        special_event(
            5,
            Color.BLACK,
            ActionKind.DOUBLE_START,
            point(size, 8, 8),
            stone_state=StoneState.CAPTURED,
        ),
    )
    config = OracleConfig(board_size=size)
    history = [Occupancy.empty()]
    black_history: set[int] = set()
    white_history: set[int] = set()
    stones_by_action = {
        stone.origin_action_number: stone for stone in board.stones
    }
    captured_double = point(size, 8, 8)
    for action_number in range(1, action_count + 1):
        if action_number == 1:
            white_history.add(old_double)
        elif action_number == 3:
            white_history.add(immortal)
        elif action_number == 4:
            white_history.add(eightway)
        elif action_number == 5:
            black_history.add(captured_double)
        else:
            stone = stones_by_action.get(action_number)
            if stone is not None:
                if action_number == 6:
                    black_history.discard(captured_double)
                target = (
                    black_history
                    if stone.color is Color.BLACK
                    else white_history
                )
                target.add(stone.point)
        history.append(
            Occupancy(
                black=tuple(sorted(black_history)),
                white=tuple(sorted(white_history)),
            )
        )
    return replace(
        new_game(config),
        board=board,
        actor=Color.BLACK,
        atomic_action_count=action_count,
        remaining_quotas=PlayerQuotas(
            black=SpecialQuotas(immortal=1, double_start=0, eightway=1),
            white=SpecialQuotas.zero(),
        ),
        used_quotas=PlayerQuotas(
            black=SpecialQuotas(immortal=0, double_start=1, eightway=0),
            white=SpecialQuotas(immortal=1, double_start=1, eightway=1),
        ),
        ledger=ledger,
        psk_history=tuple(history),
        revision=action_count,
        log_position=action_count,
    )


def fabricated_settled_captured_event_state(
    size: int,
    kind: ActionKind,
    origin_action_number: int,
) -> OracleState:
    """Build a constructor probe for special-event threshold timing."""

    config = OracleConfig(board_size=size)
    used_black = (
        SpecialQuotas(immortal=1, double_start=0, eightway=0)
        if kind is ActionKind.IMMORTAL
        else SpecialQuotas(immortal=0, double_start=0, eightway=1)
    )
    expired_black = (
        SpecialQuotas(immortal=0, double_start=1, eightway=1)
        if kind is ActionKind.IMMORTAL
        else SpecialQuotas(immortal=1, double_start=1, eightway=0)
    )
    history = [Occupancy.empty()]
    history.extend(
        Occupancy(black=(action_number,))
        for action_number in range(1, origin_action_number)
    )
    history.append(Occupancy(black=(0,)))
    history.append(Occupancy.empty())
    return replace(
        new_game(config),
        board=Board.empty(size),
        actor=Color.WHITE,
        phase=Phase.ORDINARY_PLAY,
        settlement_completed=True,
        atomic_action_count=origin_action_number,
        remaining_quotas=PlayerQuotas.zero(),
        used_quotas=PlayerQuotas(
            black=used_black,
            white=SpecialQuotas.zero(),
        ),
        expired_quotas=PlayerQuotas(
            black=expired_black,
            white=SpecialQuotas(),
        ),
        ledger=(
            special_event(
                origin_action_number,
                Color.BLACK,
                kind,
                0,
                stone_state=StoneState.CAPTURED,
                settlement_state=SettlementState.SETTLED,
            ),
        ),
        settled_ledger_count=1,
        psk_history=tuple(history),
        revision=origin_action_number,
        log_position=origin_action_number + 1,
    )


def rich_episode(size: int) -> tuple[tuple[Color, dict[str, object]], ...]:
    """Reachable asymmetric episode whose Eightway pop removes its source."""

    center = size // 2
    return (
        (
            Color.BLACK,
            action(
                ActionKind.IMMORTAL,
                size=size,
                x=center - 1,
                y=center - 1,
            ),
        ),
        (
            Color.WHITE,
            action(ActionKind.NORMAL, size=size, x=center, y=center - 1),
        ),
        (
            Color.BLACK,
            action(ActionKind.NORMAL, size=size, x=0, y=size - 1),
        ),
        (
            Color.WHITE,
            action(ActionKind.NORMAL, size=size, x=center - 1, y=center),
        ),
        (
            Color.BLACK,
            action(ActionKind.EIGHTWAY, size=size, x=center, y=center),
        ),
        (
            Color.WHITE,
            action(ActionKind.NORMAL, size=size, x=center + 1, y=center),
        ),
        (
            Color.BLACK,
            action(
                ActionKind.NORMAL,
                size=size,
                x=size - 1,
                y=size - 1,
            ),
        ),
        (
            Color.WHITE,
            action(ActionKind.NORMAL, size=size, x=center, y=center + 1),
        ),
        (Color.BLACK, action(ActionKind.PASS, size=size)),
        (Color.WHITE, action(ActionKind.PASS, size=size)),
    )


def execute_episode(
    size: int,
    episode: tuple[tuple[Color, dict[str, object]], ...],
):
    state = new_game(OracleConfig(board_size=size))
    transitions = []
    for actor, envelope in episode:
        transition = accept(state, actor, envelope)
        transitions.append(transition)
        state = transition.state
    return state, tuple(transitions)


class SyntheticMixedTopologyTests(unittest.TestCase):
    def test_synthetic_diagonal_edge_is_undirected_and_shoulders_do_not_cut(self) -> None:
        # Synthetic topology probes are direct scanner tests, not gameplay episodes.
        for anchor_point, normal_point in ((0, 10), (10, 0)):
            with self.subTest(anchor=anchor_point):
                board = Board.from_stones(
                    9,
                    (
                        Stone(
                            anchor_point,
                            Color.BLACK,
                            1,
                            ActionKind.EIGHTWAY,
                            "special-1",
                        ),
                        Stone(normal_point, Color.BLACK, 2, ActionKind.NORMAL),
                        Stone(1, Color.WHITE, 3, ActionKind.NORMAL),
                        Stone(9, Color.WHITE, 4, ActionKind.NORMAL),
                    ),
                )
                groups = scan_mixed_groups(
                    board,
                    (
                        special_event(
                            1,
                            Color.BLACK,
                            ActionKind.EIGHTWAY,
                            anchor_point,
                        ),
                    ),
                )
                black_group = next(group for group in groups if group.color is Color.BLACK)
                self.assertEqual((0, 10), black_group.stones)
                self.assertEqual((anchor_point,), black_group.eightway_anchor_points)

    def test_synthetic_ordinary_and_enemy_diagonals_never_connect(self) -> None:
        ordinary = scan_mixed_groups(
            Board.from_stones(
                9,
                (
                    Stone(0, Color.BLACK, 1, ActionKind.NORMAL),
                    Stone(10, Color.BLACK, 2, ActionKind.NORMAL),
                ),
            )
        )
        self.assertEqual(((0,), (10,)), tuple(group.stones for group in ordinary))

        enemy_board = Board.from_stones(
            9,
            (
                Stone(0, Color.BLACK, 1, ActionKind.EIGHTWAY, "special-1"),
                Stone(10, Color.WHITE, 2, ActionKind.NORMAL),
            ),
        )
        enemy = scan_mixed_groups(
            enemy_board,
            (special_event(1, Color.BLACK, ActionKind.EIGHTWAY, 0),),
        )
        self.assertEqual(2, len(enemy))
        self.assertEqual({Color.BLACK, Color.WHITE}, {group.color for group in enemy})

    def test_synthetic_n8_only_liberties_are_deduplicated_and_sorted(self) -> None:
        board, ledger = mixed_witness()
        group = next(
            group for group in scan_mixed_groups(board, ledger) if 40 in group.stones
        )
        self.assertEqual((29, 30, 40), group.stones)
        self.assertEqual(
            (20, 21, 28, 31, 32, 38, 39, 41, 48, 49, 50),
            group.liberties,
        )
        self.assertIn(32, group.liberties)
        self.assertNotIn(22, group.liberties)
        self.assertEqual(len(group.liberties), len(set(group.liberties)))
        self.assertEqual((29,), group.immortal_anchor_points)
        self.assertEqual((40,), group.eightway_anchor_points)
        self.assertTrue(group.protected)

    def test_synthetic_protection_splits_when_eightway_deactivates(self) -> None:
        board, ledger = mixed_witness()
        connected = next(
            group for group in scan_mixed_groups(board, ledger) if 40 in group.stones
        )
        self.assertTrue(connected.protected)
        deactivated = replace(
            ledger[1],
            ability_state=AbilityState.INACTIVE,
            settlement_state=SettlementState.SETTLED,
            tombstone=True,
        )
        split = {
            group.stones: group
            for group in scan_mixed_groups(board, (ledger[0], deactivated))
        }
        self.assertTrue(split[(29, 30)].protected)
        self.assertEqual((29,), split[(29, 30)].immortal_anchor_points)
        self.assertFalse(split[(40,)].protected)
        self.assertEqual((), split[(40,)].eightway_anchor_points)

    def test_synthetic_unstable_full_board_removes_both_colors_together(self) -> None:
        # No reachable stable episode is claimed here. This deliberately unstable
        # full board probes the frozen simultaneous both-color doomed union.
        black = tuple(value for value in range(81) if value % 2 == 0)
        white = tuple(value for value in range(81) if value % 2 == 1)
        board = Board.from_points(9, black=black, white=white)
        final_board, ledger, batches = oracle_module._run_settlement_closure(board, ())
        self.assertEqual((), ledger)
        self.assertEqual((board.occupancy,), batches)
        self.assertEqual(Occupancy.empty(), final_board.occupancy)


class SyntheticRestoredHistoryTests(unittest.TestCase):
    def test_synthetic_restored_history_psk_rejects_tentative_capture(self) -> None:
        # The legal prefix only establishes the candidate capture. Replacing a
        # historical PSK entry below is an explicit SYNTHETIC restored-history
        # probe, not a claim that gameplay reached that repetition history.
        state = new_game(OracleConfig(board_size=9))
        sequence = (
            (Color.BLACK, ActionKind.EIGHTWAY, 0, 0),
            (Color.WHITE, ActionKind.NORMAL, 1, 0),
            (Color.BLACK, ActionKind.NORMAL, 8, 8),
            (Color.WHITE, ActionKind.NORMAL, 0, 1),
            (Color.BLACK, ActionKind.NORMAL, 7, 8),
        )
        for actor, kind, x, y in sequence:
            state = accept(state, actor, action(kind, x=x, y=y)).state
        envelope = action(ActionKind.NORMAL, x=1, y=1)
        probe = accept(state, Color.WHITE, envelope)
        self.assertEqual(Occupancy(black=(0,)), probe.atomic_event.captured)
        history = list(state.psk_history)
        history[2] = probe.atomic_event.stable_occupancy
        repeated = replace(state, psk_history=tuple(history))
        snapshot = copy.deepcopy(repeated)

        rejected = apply_action(repeated, Color.WHITE, envelope)
        self.assertEqual(RejectionCode.POSITIONAL_SUPERKO, rejected.rejection_code)
        self.assertIs(repeated, rejected.state)
        self.assertEqual(snapshot, rejected.state)
        event = repeated.ledger[0]
        self.assertEqual(AbilityState.ARMED, event.ability_state)
        self.assertEqual(StoneState.ON_BOARD, event.stone_state)
        self.assertEqual(SettlementState.PENDING, event.settlement_state)
        self.assertFalse(event.tombstone)
        self.assertIsNotNone(repeated.board.stone_at(0))
        self.assertEqual(0, repeated.remaining_quotas.black.eightway)
        self.assertEqual(1, repeated.used_quotas.black.eightway)


class ReachableEightwayGameplayTests(unittest.TestCase):
    def test_zero_liberty_eightway_requires_mixed_immortal_protection(self) -> None:
        checkpoint = zero_liberty_immortal_checkpoint()
        target = point(9, 4, 4)
        normal = apply_action(
            checkpoint,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        )
        self.assertEqual(RejectionCode.SUICIDE, normal.rejection_code)
        self.assertIs(checkpoint, normal.state)

        placed = accept(
            checkpoint,
            Color.BLACK,
            action(ActionKind.EIGHTWAY, x=4, y=4),
        )
        group = next(
            group
            for group in scan_mixed_groups(placed.state.board, placed.state.ledger)
            if target in group.stones
        )
        self.assertEqual((point(9, 3, 3), target), group.stones)
        self.assertEqual((), group.liberties)
        self.assertTrue(group.protected)
        self.assertEqual((target,), group.eightway_anchor_points)

    def test_reachable_unprotected_n8_suicide_rolls_back_everything(self) -> None:
        size = 9
        white_ring = tuple(
            (x, y)
            for y in range(3, 6)
            for x in range(3, 6)
            if (x, y) != (4, 4)
        )
        black_fillers = (
            (0, 0),
            (2, 0),
            (4, 0),
            (6, 0),
            (8, 0),
            (0, 8),
            (2, 8),
            (4, 8),
        )
        state = new_game(OracleConfig(board_size=size))
        for black_point, white_point in zip(black_fillers, white_ring):
            state = accept(
                state,
                Color.BLACK,
                action(
                    ActionKind.NORMAL,
                    x=black_point[0],
                    y=black_point[1],
                ),
            ).state
            state = accept(
                state,
                Color.WHITE,
                action(
                    ActionKind.NORMAL,
                    x=white_point[0],
                    y=white_point[1],
                ),
            ).state
        snapshot = copy.deepcopy(state)
        rejected = apply_action(
            state,
            Color.BLACK,
            action(ActionKind.EIGHTWAY, x=4, y=4),
        )
        self.assertEqual(RejectionCode.SUICIDE, rejected.rejection_code)
        self.assertIs(state, rejected.state)
        self.assertEqual(snapshot, rejected.state)
        self.assertEqual(1, state.remaining_quotas.black.eightway)
        self.assertEqual(0, state.used_quotas.black.eightway)
        self.assertEqual((), state.ledger)

    def test_reachable_captured_eightway_is_pending_inert_then_no_op_settled(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        sequence = (
            (Color.BLACK, ActionKind.EIGHTWAY, 0, 0),
            (Color.WHITE, ActionKind.NORMAL, 1, 0),
            (Color.BLACK, ActionKind.NORMAL, 8, 8),
            (Color.WHITE, ActionKind.NORMAL, 0, 1),
            (Color.BLACK, ActionKind.NORMAL, 7, 8),
            (Color.WHITE, ActionKind.NORMAL, 1, 1),
        )
        for actor, kind, x, y in sequence:
            transition = accept(state, actor, action(kind, x=x, y=y))
            state = transition.state
        self.assertEqual(Occupancy(black=(0,)), transition.atomic_event.captured)
        event = state.ledger[0]
        self.assertEqual(AbilityState.INACTIVE, event.ability_state)
        self.assertEqual(StoneState.CAPTURED, event.stone_state)
        self.assertEqual(SettlementState.PENDING, event.settlement_state)
        self.assertTrue(event.tombstone)
        self.assertEqual(0, state.remaining_quotas.black.eightway)
        self.assertEqual(1, state.used_quotas.black.eightway)

        first_pass = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        settled = accept(first_pass, Color.WHITE, action(ActionKind.PASS))
        step = settled.settlement.steps[0]
        self.assertFalse(step.ability_deactivated)
        self.assertTrue(step.no_op)
        self.assertEqual((), step.removal_batches)
        self.assertEqual(
            settled.atomic_event.stable_occupancy,
            step.stable_occupancy,
        )
        self.assertEqual(SettlementState.SETTLED, settled.state.ledger[0].settlement_state)

    def test_pending_double_eightway_rejection_precedence_is_frozen(self) -> None:
        config = OracleConfig(
            board_size=9,
            quotas=PlayerQuotas(
                black=SpecialQuotas(immortal=0, double_start=1, eightway=0),
                white=SpecialQuotas.zero(),
            ),
        )
        pending = accept(
            new_game(config),
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=4, y=4),
        ).state
        snapshot = copy.deepcopy(pending)

        forbidden = apply_action(
            pending,
            Color.BLACK,
            action(ActionKind.EIGHTWAY, x=4, y=4),
        )
        self.assertEqual(
            RejectionCode.DOUBLE_CONTINUATION_KIND_FORBIDDEN,
            forbidden.rejection_code,
        )
        self.assertIs(pending, forbidden.state)
        self.assertEqual(snapshot, forbidden.state)

        wrong_actor = apply_action(
            pending,
            Color.WHITE,
            action(ActionKind.EIGHTWAY, x=4, y=4),
        )
        self.assertEqual(RejectionCode.WRONG_ACTOR, wrong_actor.rejection_code)
        self.assertIs(pending, wrong_actor.state)

        off_board = apply_action(
            pending,
            Color.BLACK,
            action(ActionKind.EIGHTWAY, size=19, x=0, y=0),
        )
        self.assertEqual(RejectionCode.POINT_OFF_BOARD, off_board.rejection_code)
        self.assertIs(pending, off_board.state)

    def test_action_t_eightway_commits_before_becoming_newest_settlement_pop(self) -> None:
        state = threshold_minus_one_state()
        transition = accept(
            state,
            Color.WHITE,
            action(ActionKind.EIGHTWAY, x=4, y=4),
        )
        self.assertEqual(state.threshold, transition.atomic_event.action_number)
        self.assertEqual(SettlementReason.THRESHOLD, transition.settlement.reason)
        self.assertEqual(
            transition.atomic_event.action_number,
            transition.atomic_event.psk_history_index,
        )
        self.assertIn(point(9, 4, 4), transition.atomic_event.stable_occupancy.white)
        self.assertEqual(1, len(transition.settlement.steps))
        step = transition.settlement.steps[0]
        self.assertEqual("special-34", step.event_id)
        self.assertEqual(ActionKind.EIGHTWAY, step.kind)
        self.assertTrue(step.ability_deactivated)
        self.assertEqual(
            (Occupancy(white=(point(9, 4, 4),)),),
            step.removal_batches,
        )
        self.assertEqual(Phase.ORDINARY_PLAY, transition.state.phase)
        self.assertEqual(Color.BLACK, transition.state.actor)
        self.assertEqual(0, transition.state.consecutive_passes)
        self.assertEqual(StoneState.CAPTURED, transition.state.ledger[0].stone_state)
        self.assertEqual(
            1 + transition.state.atomic_action_count + len(transition.state.ledger),
            len(transition.state.psk_history),
        )


class IntegratedSettlementTests(unittest.TestCase):
    def test_global_reverse_order_and_newer_pop_captures_older_source(self) -> None:
        # This starts from a fabricated but constructor-valid stable state. The
        # settlement transition itself is executed through the independent
        # reference-oracle apply_action path.
        checkpoint = global_settlement_checkpoint()
        groups = scan_mixed_groups(checkpoint.board, checkpoint.ledger)
        protected = next(group for group in groups if point(9, 3, 3) in group.stones)
        self.assertEqual((20, 30, 40), protected.stones)
        self.assertEqual((), protected.liberties)
        self.assertTrue(protected.protected)

        first_pass = accept(checkpoint, Color.BLACK, action(ActionKind.PASS)).state
        transition = accept(first_pass, Color.WHITE, action(ActionKind.PASS))
        steps = transition.settlement.steps
        self.assertEqual(
            (
                ActionKind.DOUBLE_START,
                ActionKind.EIGHTWAY,
                ActionKind.IMMORTAL,
                ActionKind.DOUBLE_START,
            ),
            tuple(step.kind for step in steps),
        )
        self.assertEqual((4, 3, 2, 0), tuple(step.logical_order for step in steps))
        self.assertEqual(
            (Color.BLACK, Color.WHITE, Color.WHITE, Color.WHITE),
            tuple(step.owner for step in steps),
        )
        self.assertTrue(steps[0].no_op)
        self.assertEqual(
            (Occupancy(white=(30, 40)),),
            steps[1].removal_batches,
        )
        self.assertTrue(steps[1].ability_deactivated)
        self.assertEqual(
            (Occupancy(white=(20,)),),
            steps[2].removal_batches,
        )
        self.assertTrue(steps[3].no_op)
        self.assertFalse(steps[3].ability_deactivated)
        self.assertEqual((), steps[3].removal_batches)
        self.assertEqual(
            steps[0].stable_occupancy,
            transition.atomic_event.stable_occupancy,
        )
        self.assertEqual(steps[2].stable_occupancy, steps[3].stable_occupancy)
        self.assertEqual(
            tuple(range(steps[0].log_position, steps[0].log_position + len(steps))),
            tuple(step.log_position for step in steps),
        )

        old_double = transition.state.ledger[0]
        self.assertEqual(StoneState.CAPTURED, old_double.stone_state)
        self.assertEqual(AbilityState.INACTIVE, old_double.ability_state)
        self.assertEqual(SettlementState.SETTLED, old_double.settlement_state)
        self.assertTrue(old_double.tombstone)
        self.assertEqual(Phase.ORDINARY_PLAY, transition.state.phase)
        self.assertEqual(Color.BLACK, transition.state.actor)
        self.assertEqual(0, transition.state.consecutive_passes)
        self.assertEqual(PlayerQuotas.zero(), transition.state.remaining_quotas)
        self.assertEqual((), transition.state.board.occupancy.white)
        self.assertEqual(
            checkpoint.board.occupancy.black,
            transition.state.board.occupancy.black,
        )


class DeterminismD4AndConstructorTests(unittest.TestCase):
    def test_rich_eightway_episode_is_d4_equivariant_on_9_13_19(self) -> None:
        for size in (9, 13, 19):
            episode = rich_episode(size)
            base_state, base_transitions = execute_episode(size, episode)
            center = point(size, size // 2, size // 2)
            pre_settlement = base_transitions[-3].state
            protected_group = next(
                group
                for group in scan_mixed_groups(
                    pre_settlement.board,
                    pre_settlement.ledger,
                )
                if center in group.stones
            )
            self.assertTrue(protected_group.protected)
            self.assertEqual((center,), protected_group.eightway_anchor_points)
            self.assertEqual(Phase.ORDINARY_PLAY, base_state.phase)
            base_steps = base_transitions[-1].settlement.steps
            self.assertEqual(
                (ActionKind.EIGHTWAY, ActionKind.IMMORTAL),
                tuple(step.kind for step in base_steps),
            )
            self.assertEqual(
                (Occupancy(black=(center,)),),
                base_steps[0].removal_batches,
            )
            self.assertEqual(
                episode,
                tuple(
                    (actor, transform_action(envelope, size, 0))
                    for actor, envelope in episode
                ),
            )
            self.assertEqual(base_state, transform_state(base_state, 0))
            base_group_projection = group_projection(pre_settlement)
            for symmetry in range(1, 8):
                with self.subTest(size=size, symmetry=symmetry):
                    transformed_episode = tuple(
                        (actor, transform_action(envelope, size, symmetry))
                        for actor, envelope in episode
                    )
                    transformed_state, transformed_transitions = execute_episode(
                        size,
                        transformed_episode,
                    )
                    for base_transition, transformed_transition in zip(
                        base_transitions,
                        transformed_transitions,
                    ):
                        self.assertEqual(
                            transform_state(base_transition.state, symmetry),
                            transformed_transition.state,
                        )
                        self.assertEqual(
                            transform_occupancy(
                                base_transition.atomic_event.captured,
                                size,
                                symmetry,
                            ),
                            transformed_transition.atomic_event.captured,
                        )
                    self.assertEqual(
                        transform_group_projection(
                            base_group_projection,
                            size,
                            symmetry,
                        ),
                        group_projection(transformed_transitions[-3].state),
                    )
                    transformed_steps = transformed_transitions[-1].settlement.steps
                    self.assertEqual(
                        tuple(step.kind for step in base_steps),
                        tuple(step.kind for step in transformed_steps),
                    )
                    self.assertEqual(
                        tuple(step.ability_deactivated for step in base_steps),
                        tuple(
                            step.ability_deactivated for step in transformed_steps
                        ),
                    )
                    self.assertEqual(
                        tuple(
                            tuple(
                                transform_occupancy(batch, size, symmetry)
                                for batch in step.removal_batches
                            )
                            for step in base_steps
                        ),
                        tuple(step.removal_batches for step in transformed_steps),
                    )
                    self.assertEqual(
                        base_state,
                        transform_state(
                            transformed_state,
                            INVERSE_SYMMETRY[symmetry],
                        ),
                    )

    def test_deterministic_suffix_execution_from_prefix_copies(self) -> None:
        episode = rich_episode(9)
        full_state, full_transitions = execute_episode(9, episode)

        state = new_game(OracleConfig(board_size=9))
        prefix_length = 3
        for actor, envelope in episode[:prefix_length]:
            state = accept(state, actor, envelope).state
        checkpoint_snapshot = copy.deepcopy(state)
        self.assertEqual(full_transitions[prefix_length - 1].state, state)

        checkpoints = (state, replace(state), copy.deepcopy(state))
        outcomes = []
        for checkpoint in checkpoints:
            current = checkpoint
            transitions = []
            for actor, envelope in episode[prefix_length:]:
                transition = accept(current, actor, envelope)
                transitions.append(transition)
                current = transition.state
            outcomes.append((current, tuple(transitions)))

        expected = (full_state, full_transitions[prefix_length:])
        for outcome in outcomes:
            self.assertEqual(expected, outcome)
        for checkpoint in checkpoints:
            self.assertEqual(checkpoint_snapshot, checkpoint)

    def test_fabricated_eightway_lifecycle_source_and_suffix_errors_reject(self) -> None:
        live = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.EIGHTWAY, x=4, y=4),
        ).state
        event = live.ledger[0]
        invalid_changes = (
            {"ability_state": AbilityState.INACTIVE},
            {"tombstone": True},
            {"stone_state": StoneState.CAPTURED, "tombstone": False},
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes), self.assertRaisesRegex(
                ValueError,
                "Eightway",
            ):
                replace(event, **changes)

        with self.assertRaisesRegex(ValueError, "source identity|source linkage"):
            replace(
                live,
                ledger=(replace(event, source_point=0),),
            )
        with self.assertRaisesRegex(ValueError, "special stone source"):
            replace(live, ledger=())

        second = accept(
            live,
            Color.WHITE,
            action(ActionKind.IMMORTAL, x=8, y=8),
        ).state
        invalid_first = replace(
            second.ledger[0],
            ability_state=AbilityState.INACTIVE,
            settlement_state=SettlementState.SETTLED,
            tombstone=True,
        )
        with self.assertRaisesRegex(ValueError, "settled ledger entries.*suffix"):
            replace(
                second,
                ledger=(invalid_first, second.ledger[1]),
                settled_ledger_count=1,
            )

    def test_immortal_and_eightway_origins_allow_t_but_reject_t_plus_one(self) -> None:
        for size in (9, 13, 19):
            threshold = OracleConfig(board_size=size).threshold
            for kind in (ActionKind.IMMORTAL, ActionKind.EIGHTWAY):
                with self.subTest(size=size, kind=kind, boundary="T"):
                    state = fabricated_settled_captured_event_state(
                        size,
                        kind,
                        threshold,
                    )
                    self.assertEqual(threshold, state.ledger[0].origin_action_number)
                with self.subTest(size=size, kind=kind, boundary="T+1"):
                    with self.assertRaisesRegex(ValueError, "after the threshold"):
                        fabricated_settled_captured_event_state(
                            size,
                            kind,
                            threshold + 1,
                        )

    def test_eightway_safe_integer_bounds_and_step_order_are_exact(self) -> None:
        event = SpecialEvent(
            event_id=f"special-{JSON_SAFE_INTEGER_MAX}",
            logical_order=JSON_SAFE_INTEGER_MAX - 1,
            owner=Color.BLACK,
            kind=ActionKind.EIGHTWAY,
            source_point=0,
            source_stone_id=f"stone-{JSON_SAFE_INTEGER_MAX}",
            ability_state=AbilityState.ARMED,
            stone_state=StoneState.ON_BOARD,
            settlement_state=SettlementState.PENDING,
            tombstone=False,
        )
        step = SettlementStepEvent(
            event_id=event.event_id,
            logical_order=event.logical_order,
            owner=event.owner,
            kind=event.kind,
            ability_deactivated=True,
            no_op=False,
            stable_occupancy=Occupancy.empty(),
            stable_stones=(),
            psk_history_index=JSON_SAFE_INTEGER_MAX,
            revision=JSON_SAFE_INTEGER_MAX,
            log_position=JSON_SAFE_INTEGER_MAX,
        )
        self.assertEqual(ActionKind.EIGHTWAY, step.kind)
        with self.assertRaises(ValueError):
            replace(event, logical_order=True)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
