from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from mutago.collapse_go import (  # noqa: E402
    PASS_ACTION_ID,
    AbilityState,
    ActionKind,
    Board,
    Color,
    Group,
    Occupancy,
    OracleConfig,
    PendingDouble,
    PlayerQuotas,
    SettlementState,
    SpecialEvent,
    SpecialQuotas,
    Stone,
    StoneState,
    apply_action,
    new_game,
    scan_n4_groups,
)


KIND_CODE = {
    ActionKind.NORMAL: 0,
    ActionKind.IMMORTAL: 1,
    ActionKind.DOUBLE_START: 2,
    ActionKind.EIGHTWAY: 3,
}


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
            "kind": "PASS",
        }
    if x is None or y is None:
        raise ValueError("point action needs board-local coordinates")
    offset = (19 - size) // 2
    action_id = 361 * KIND_CODE[kind] + 19 * (y + offset) + x + offset
    return {
        "schemaVersion": "action-v1",
        "actionId": action_id,
        "kind": kind.value,
    }


def accept(state, actor: Color, envelope: dict[str, object]):
    transition = apply_action(state, actor, envelope)
    if not transition.accepted:
        raise AssertionError(f"unexpected rejection: {transition.rejection_code}")
    return transition


def positioned_state(
    *,
    black: tuple[int, ...] = (),
    white: tuple[int, ...] = (),
    actor: Color = Color.BLACK,
):
    config = OracleConfig(board_size=9)
    initial = new_game(config)
    board = Board.from_points(9, black=black, white=white)
    action_count = max(
        (stone.origin_action_number for stone in board.stones),
        default=0,
    )
    history = (Occupancy.empty(),) * action_count + (board.occupancy,)
    return replace(
        initial,
        board=board,
        actor=actor,
        atomic_action_count=action_count,
        psk_history=history,
        revision=action_count,
        log_position=action_count,
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
    return size * y + x


def transform_occupancy(
    occupancy: Occupancy, size: int, symmetry: int
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
    return Stone(
        point=transform_point(size, stone.point, symmetry),
        color=stone.color,
        origin_action_number=stone.origin_action_number,
        origin_kind=stone.origin_kind,
        special_event_id=stone.special_event_id,
    )


def transform_state(state, symmetry: int):
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
            transform_occupancy(entry, size, symmetry)
            for entry in state.psk_history
        ),
    )


def transform_action(
    envelope: dict[str, object], size: int, symmetry: int
) -> dict[str, object]:
    if envelope["kind"] == ActionKind.PASS.value:
        return dict(envelope)
    action_id = envelope["actionId"]
    if type(action_id) is not int:
        raise TypeError("test action id must be int")
    canvas_point = action_id % 361
    offset = (19 - size) // 2
    local_x = canvas_point % 19 - offset
    local_y = canvas_point // 19 - offset
    transformed = transform_point(size, point(size, local_x, local_y), symmetry)
    kind = ActionKind(envelope["kind"])
    return action(
        kind,
        size=size,
        x=transformed % size,
        y=transformed // size,
    )


class SourceAwareStateTests(unittest.TestCase):
    def test_normal_sources_pass_stability_capture_and_point_reuse(self) -> None:
        state = positioned_state(
            black=(
                point(9, 1, 0),
                point(9, 2, 0),
                point(9, 0, 1),
                point(9, 3, 1),
                point(9, 2, 2),
            ),
            white=(point(9, 1, 1), point(9, 2, 1)),
        )
        old_sources = {
            stone.point: stone for stone in state.board.stones
        }
        old_reused_source = old_sources[point(9, 2, 1)]

        capture = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=1, y=2),
        )
        capture_number = state.atomic_action_count + 1
        placed = capture.atomic_event.placed_stone
        self.assertIsNotNone(placed)
        self.assertEqual(capture_number, placed.origin_action_number)
        self.assertEqual(f"stone-{capture_number}", placed.source_id)
        self.assertEqual(ActionKind.NORMAL, placed.origin_kind)
        self.assertIsNone(placed.special_event_id)
        self.assertEqual(
            (point(9, 1, 1), point(9, 2, 1)),
            tuple(stone.point for stone in capture.atomic_event.captured_stones),
        )
        self.assertEqual(
            tuple(old_sources[value] for value in (point(9, 1, 1), point(9, 2, 1))),
            capture.atomic_event.captured_stones,
        )
        self.assertIsNone(capture.state.board.stone_at(point(9, 2, 1)))
        for survivor_point in state.board.occupancy.black:
            self.assertIs(
                old_sources[survivor_point],
                capture.state.board.stone_at(survivor_point),
            )
        self.assertEqual(
            capture.state.board.stones,
            capture.atomic_event.stable_stones,
        )

        reused = accept(
            capture.state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=2, y=1),
        )
        new_source = reused.state.board.stone_at(point(9, 2, 1))
        self.assertIsNotNone(new_source)
        self.assertEqual(capture_number + 1, new_source.origin_action_number)
        self.assertEqual(f"stone-{capture_number + 1}", new_source.source_id)
        self.assertNotEqual(old_reused_source.source_id, new_source.source_id)
        self.assertNotIn(old_reused_source, reused.state.board.stones)

        passed = accept(reused.state, Color.BLACK, action(ActionKind.PASS))
        self.assertIs(reused.state.board, passed.state.board)
        self.assertEqual(reused.state.board.stones, passed.state.board.stones)
        self.assertIsNone(passed.atomic_event.placed_stone)
        self.assertEqual((), passed.atomic_event.captured_stones)

    def test_board_derives_exact_occupancy_and_rejects_duplicate_sources(self) -> None:
        stones = (
            Stone(0, Color.BLACK, 1, ActionKind.NORMAL),
            Stone(8, Color.WHITE, 3, ActionKind.NORMAL),
        )
        board = Board.from_stones(9, reversed(stones))
        self.assertEqual(stones, board.stones)
        self.assertEqual(Occupancy(black=(0,), white=(8,)), board.occupancy)
        self.assertEqual("stone-1", board.stones[0].source_id)
        with self.assertRaisesRegex(ValueError, "source IDs"):
            Board.from_stones(
                9,
                (
                    Stone(0, Color.BLACK, 1, ActionKind.NORMAL),
                    Stone(1, Color.BLACK, 1, ActionKind.NORMAL),
                ),
            )
        with self.assertRaisesRegex(ValueError, "strictly ordered|share"):
            Board(
                9,
                (
                    Stone(0, Color.BLACK, 1, ActionKind.NORMAL),
                    Stone(0, Color.WHITE, 2, ActionKind.NORMAL),
                ),
            )

    def test_lifecycle_shell_is_immutable_and_double_start_is_reachable(self) -> None:
        event = SpecialEvent(
            event_id="special-1",
            logical_order=0,
            owner=Color.BLACK,
            kind=ActionKind.DOUBLE_START,
            source_point=0,
            source_stone_id="stone-1",
            ability_state=AbilityState.CONSUMED,
            stone_state=StoneState.ON_BOARD,
            settlement_state=SettlementState.PENDING,
            tombstone=True,
        )
        pending = PendingDouble(
            owner=Color.BLACK,
            event_id="special-1",
            start_action_number=1,
        )
        with self.assertRaises(FrozenInstanceError):
            event.tombstone = False  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            pending.start_action_number = 2  # type: ignore[misc]

        state = new_game(OracleConfig(board_size=9))
        self.assertEqual((), state.ledger)
        self.assertIsNone(state.pending_double)
        self.assertEqual(PlayerQuotas.zero(), state.used_quotas)

        started = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=0, y=0),
        )
        self.assertEqual(1, len(started.state.ledger))
        self.assertEqual(event, started.state.ledger[0])
        self.assertEqual(pending, started.state.pending_double)
        self.assertEqual(1, started.state.used_quotas.black.double_start)
        self.assertEqual(0, state.atomic_action_count)
        self.assertEqual((), state.ledger)
        self.assertIsNone(state.pending_double)


class QuotaAndEventCountTests(unittest.TestCase):
    def test_arbitrary_nonnegative_quotas_conserve_through_empty_settlement(self) -> None:
        initial_quotas = PlayerQuotas(
            black=SpecialQuotas(immortal=3, double_start=2, eightway=4),
            white=SpecialQuotas(immortal=5, double_start=0, eightway=6),
        )
        state = new_game(OracleConfig(board_size=9, quotas=initial_quotas))
        self.assertEqual(initial_quotas, state.initial_quotas)
        self.assertEqual(initial_quotas, state.remaining_quotas)
        self.assertEqual(PlayerQuotas.zero(), state.used_quotas)
        self.assertEqual(PlayerQuotas.zero(), state.expired_quotas)

        first = accept(state, Color.BLACK, action(ActionKind.PASS))
        settled = accept(first.state, Color.WHITE, action(ActionKind.PASS)).state
        self.assertEqual(PlayerQuotas.zero(), settled.remaining_quotas)
        self.assertEqual(PlayerQuotas.zero(), settled.used_quotas)
        self.assertEqual(initial_quotas, settled.expired_quotas)
        for color_name in ("black", "white"):
            initial = getattr(settled.initial_quotas, color_name)
            remaining = getattr(settled.remaining_quotas, color_name)
            used = getattr(settled.used_quotas, color_name)
            expired = getattr(settled.expired_quotas, color_name)
            for ability in ("immortal", "double_start", "eightway"):
                self.assertEqual(
                    getattr(initial, ability),
                    getattr(remaining, ability)
                    + getattr(used, ability)
                    + getattr(expired, ability),
                )

        with self.assertRaisesRegex(ValueError, "quota conservation"):
            replace(
                state,
                remaining_quotas=PlayerQuotas.zero(),
            )
        for invalid in (-1, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                SpecialQuotas(eightway=invalid)  # type: ignore[arg-type]

    def test_revision_log_position_and_psk_event_formula(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        first = accept(state, Color.BLACK, action(ActionKind.PASS))
        ordinary = accept(first.state, Color.WHITE, action(ActionKind.PASS)).state
        placed = accept(
            ordinary,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        )
        first_end_pass = accept(
            placed.state,
            Color.WHITE,
            action(ActionKind.PASS),
        )
        final = accept(
            first_end_pass.state,
            Color.BLACK,
            action(ActionKind.PASS),
        )

        self.assertEqual(5, final.state.atomic_action_count)
        self.assertEqual(5, final.state.revision)
        self.assertEqual(6, final.state.log_position)
        self.assertEqual(0, final.state.settled_ledger_count)
        self.assertEqual(1, final.state.stable_terminal_event_count)
        self.assertEqual(
            1
            + final.state.atomic_action_count
            + final.state.settled_ledger_count
            + final.state.stable_terminal_event_count,
            len(final.state.psk_history),
        )
        self.assertEqual(5, final.atomic_event.revision)
        self.assertEqual(5, final.atomic_event.log_position)
        self.assertEqual(5, final.atomic_event.psk_history_index)
        self.assertEqual(5, final.terminal_event.revision)
        self.assertEqual(6, final.terminal_event.log_position)
        self.assertEqual(6, final.terminal_event.psk_history_index)


class DeterministicTopologyAndD4Tests(unittest.TestCase):
    def test_group_and_liberty_order_is_direct_deterministic_and_source_aware(self) -> None:
        board = Board.from_points(
            9,
            black=(0, 1, 10, 80),
            white=(4, 13),
        )
        first = scan_n4_groups(board)
        second = scan_n4_groups(board)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertEqual(
            (
                (Color.BLACK, (0, 1, 10), (2, 9, 11, 19)),
                (Color.WHITE, (4, 13), (3, 5, 12, 14, 22)),
                (Color.BLACK, (80,), (71, 79)),
            ),
            tuple(
                (group.color, group.stones, group.liberties) for group in first
            ),
        )
        for group in first:
            self.assertEqual(
                group.stones,
                tuple(stone.point for stone in group.source_stones),
            )
            self.assertFalse(group.protected)
            self.assertEqual((), group.immortal_anchor_points)
            self.assertEqual((), group.eightway_anchor_points)
            self.assertEqual((), group.anchor_points)
        with self.assertRaisesRegex(TypeError, "Stone values"):
            Group(
                color=Color.BLACK,
                stones=(0,),
                liberties=(1,),
                source_stones=(object(),),  # type: ignore[arg-type]
            )
        self.assertFalse(hasattr(board, "groups"))

    def test_stable_state_rejects_unprotected_zero_liberty_group(self) -> None:
        initial = new_game(OracleConfig(board_size=9))
        board = Board.from_points(
            9,
            black=(point(9, 4, 4),),
            white=(
                point(9, 4, 3),
                point(9, 3, 4),
                point(9, 5, 4),
                point(9, 4, 5),
            ),
        )
        action_count = len(board.stones)
        history = (Occupancy.empty(),) * action_count + (board.occupancy,)
        with self.assertRaisesRegex(ValueError, "unprotected zero-liberty"):
            replace(
                initial,
                board=board,
                atomic_action_count=action_count,
                psk_history=history,
                revision=action_count,
                log_position=action_count,
            )

        valid = positioned_state(
            black=(
                point(9, 2, 0),
                point(9, 1, 1),
                point(9, 3, 1),
                point(9, 1, 3),
                point(9, 3, 3),
                point(9, 2, 4),
            ),
            white=(point(9, 2, 1), point(9, 2, 3)),
        )
        captured = accept(
            valid,
            Color.BLACK,
            action(ActionKind.NORMAL, x=2, y=2),
        ).state
        checkpoint = replace(captured)
        self.assertEqual(captured, checkpoint)
        self.assertEqual(
            accept(captured, Color.WHITE, action(ActionKind.PASS)),
            accept(checkpoint, Color.WHITE, action(ActionKind.PASS)),
        )

    def test_all_eight_d4_transforms_preserve_n4_topology_and_normal_transition(self) -> None:
        state = positioned_state(
            black=(
                point(9, 2, 0),
                point(9, 1, 1),
                point(9, 3, 1),
                point(9, 1, 3),
                point(9, 3, 3),
                point(9, 2, 4),
            ),
            white=(point(9, 2, 1), point(9, 2, 3)),
        )
        base_action = action(ActionKind.NORMAL, x=2, y=2)
        base_groups = scan_n4_groups(state.board)
        base = accept(state, Color.BLACK, base_action)

        for symmetry in range(8):
            with self.subTest(symmetry=symmetry):
                transformed_state = transform_state(state, symmetry)
                transformed_groups = scan_n4_groups(transformed_state.board)
                expected_groups = sorted(
                    [
                        (
                            group.color,
                            tuple(
                                sorted(
                                    transform_point(9, value, symmetry)
                                    for value in group.stones
                                )
                            ),
                            tuple(
                                sorted(
                                    transform_point(9, value, symmetry)
                                    for value in group.liberties
                                )
                            ),
                        )
                        for group in base_groups
                    ],
                    key=lambda item: item[1][0],
                )
                self.assertEqual(
                    tuple(expected_groups),
                    tuple(
                        (group.color, group.stones, group.liberties)
                        for group in transformed_groups
                    ),
                )

                transformed = accept(
                    transformed_state,
                    Color.BLACK,
                    transform_action(base_action, 9, symmetry),
                )
                self.assertEqual(
                    transform_occupancy(base.state.board.occupancy, 9, symmetry),
                    transformed.state.board.occupancy,
                )
                self.assertEqual(
                    tuple(
                        sorted(
                            (
                                transform_stone(stone, 9, symmetry)
                                for stone in base.state.board.stones
                            ),
                            key=lambda stone: stone.point,
                        )
                    ),
                    transformed.state.board.stones,
                )
                self.assertEqual(
                    transform_occupancy(base.atomic_event.captured, 9, symmetry),
                    transformed.atomic_event.captured,
                )
                self.assertEqual(
                    tuple(
                        sorted(
                            transform_point(9, stone.point, symmetry)
                            for stone in base.atomic_event.captured_stones
                        )
                    ),
                    tuple(
                        stone.point
                        for stone in transformed.atomic_event.captured_stones
                    ),
                )
                self.assertEqual(
                    tuple(
                        transform_occupancy(entry, 9, symmetry)
                        for entry in base.state.psk_history
                    ),
                    transformed.state.psk_history,
                )
                self.assertEqual(base.state.actor, transformed.state.actor)
                self.assertEqual(base.state.revision, transformed.state.revision)
                self.assertEqual(base.state.log_position, transformed.state.log_position)


    def test_all_eight_d4_transforms_preserve_double_start_and_continuation(self) -> None:
        initial = new_game(OracleConfig(board_size=9))
        start_action = action(ActionKind.DOUBLE_START, x=1, y=2)
        continuation_action = action(ActionKind.NORMAL, x=3, y=4)
        started = accept(initial, Color.BLACK, start_action)
        continued = accept(started.state, Color.BLACK, continuation_action)

        for symmetry in range(8):
            with self.subTest(symmetry=symmetry):
                expected_started = transform_state(started.state, symmetry)
                transformed_start = accept(
                    transform_state(initial, symmetry),
                    Color.BLACK,
                    transform_action(start_action, 9, symmetry),
                )
                self.assertEqual(expected_started, transformed_start.state)

                expected_continued = transform_state(continued.state, symmetry)
                transformed_continuation = accept(
                    transformed_start.state,
                    Color.BLACK,
                    transform_action(continuation_action, 9, symmetry),
                )
                self.assertEqual(expected_continued, transformed_continuation.state)


class ReplayAndRejectionTests(unittest.TestCase):
    def test_rejected_transition_returns_the_exact_original_shell(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        ).state
        snapshot = copy.deepcopy(state)
        rejected = apply_action(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=4, y=4),
        )
        self.assertFalse(rejected.accepted)
        self.assertIs(state, rejected.state)
        self.assertEqual(snapshot, rejected.state)
        self.assertIs(state.board, rejected.state.board)
        self.assertIs(state.ledger, rejected.state.ledger)
        self.assertEqual(state.revision, rejected.state.revision)
        self.assertEqual(state.log_position, rejected.state.log_position)
        self.assertEqual(state.psk_history, rejected.state.psk_history)
        self.assertEqual(state.board.stones, rejected.state.board.stones)

    def test_replay_from_prefix_and_checkpoint_copies_is_exact(self) -> None:
        sequence = (
            (Color.BLACK, action(ActionKind.NORMAL, x=4, y=4)),
            (Color.WHITE, action(ActionKind.NORMAL, x=3, y=4)),
            (Color.BLACK, action(ActionKind.PASS)),
            (Color.WHITE, action(ActionKind.NORMAL, x=5, y=4)),
            (Color.BLACK, action(ActionKind.NORMAL, x=4, y=3)),
            (Color.WHITE, action(ActionKind.PASS)),
        )

        full = new_game(OracleConfig(board_size=9))
        full_transitions = []
        for actor, envelope in sequence:
            transition = accept(full, actor, envelope)
            full_transitions.append(transition)
            full = transition.state

        prefix = new_game(OracleConfig(board_size=9))
        for actor, envelope in sequence[:3]:
            prefix = accept(prefix, actor, envelope).state
        shallow_checkpoint = replace(prefix)
        deep_checkpoint = copy.deepcopy(prefix)
        self.assertEqual(prefix, shallow_checkpoint)
        self.assertEqual(prefix, deep_checkpoint)

        replay_states = []
        for checkpoint in (prefix, shallow_checkpoint, deep_checkpoint):
            current = checkpoint
            replayed = []
            for actor, envelope in sequence[3:]:
                transition = accept(current, actor, envelope)
                replayed.append(transition)
                current = transition.state
            replay_states.append((current, tuple(replayed)))

        for replayed_state, replayed_transitions in replay_states:
            self.assertEqual(full, replayed_state)
            self.assertEqual(
                tuple(full_transitions[3:]),
                replayed_transitions,
            )
        self.assertEqual(
            full.psk_history,
            replay_states[0][0].psk_history,
        )
        self.assertEqual(full.board.stones, replay_states[0][0].board.stones)
        self.assertEqual(full.revision, replay_states[0][0].revision)
        self.assertEqual(full.log_position, replay_states[0][0].log_position)


if __name__ == "__main__":
    unittest.main()
