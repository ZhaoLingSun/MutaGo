from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from mutago.collapse_go import (  # noqa: E402
    PASS_ACTION_ID,
    AbilityState,
    ActionKind,
    Board,
    Color,
    Occupancy,
    OracleConfig,
    Phase,
    PlayerQuotas,
    RejectionCode,
    SettlementState,
    SpecialEvent,
    SpecialQuotas,
    Stone,
    StoneState,
    apply_action,
    decode_action_v1,
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
            "kind": ActionKind.PASS.value,
        }
    if x is None or y is None:
        raise ValueError("point action requires board-local coordinates")
    offset = (19 - size) // 2
    return {
        "schemaVersion": "action-v1",
        "actionId": (
            361 * KIND_CODE[kind] + 19 * (y + offset) + x + offset
        ),
        "kind": kind.value,
    }


def accept(state, actor: Color, envelope: dict[str, object]):
    transition = apply_action(state, actor, envelope)
    if not transition.accepted:
        raise AssertionError(f"unexpected rejection: {transition.rejection_code}")
    return transition


def play_zero_liberty_immortal():
    state = new_game(OracleConfig(board_size=9))
    sequence = (
        (Color.BLACK, ActionKind.NORMAL, 0, 0),
        (Color.WHITE, ActionKind.NORMAL, 4, 3),
        (Color.BLACK, ActionKind.NORMAL, 1, 0),
        (Color.WHITE, ActionKind.NORMAL, 3, 4),
        (Color.BLACK, ActionKind.NORMAL, 2, 0),
        (Color.WHITE, ActionKind.NORMAL, 5, 4),
        (Color.BLACK, ActionKind.NORMAL, 7, 7),
        (Color.WHITE, ActionKind.NORMAL, 4, 5),
    )
    for actor, kind, x, y in sequence:
        state = accept(state, actor, action(kind, x=x, y=y)).state
    return state, accept(
        state,
        Color.BLACK,
        action(ActionKind.IMMORTAL, x=4, y=4),
    )


def protected_anchor_checkpoint(*, two_liberties: bool):
    size = 9
    if two_liberties:
        white_points = (
            point(size, 4, 3),
            point(size, 3, 4),
            point(size, 6, 4),
            point(size, 5, 3),
            point(size, 5, 5),
            point(size, 3, 5),
            point(size, 4, 6),
        )
    else:
        white_points = (
            point(size, 4, 3),
            point(size, 3, 4),
            point(size, 4, 5),
            point(size, 6, 4),
            point(size, 5, 3),
            point(size, 5, 5),
        )
    black_fillers = (
        (0, 0),
        (2, 0),
        (4, 0),
        (6, 0),
        (8, 0),
        (0, 8),
        (2, 8),
    )
    state = new_game(OracleConfig(board_size=size))
    for index, white_point in enumerate(white_points):
        black_x, black_y = black_fillers[index]
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=black_x, y=black_y),
        ).state
        state = accept(
            state,
            Color.WHITE,
            action(
                ActionKind.NORMAL,
                x=white_point % size,
                y=white_point // size,
            ),
        ).state
    state = accept(
        state,
        Color.BLACK,
        action(ActionKind.IMMORTAL, x=4, y=4),
    ).state
    state = accept(
        state,
        Color.WHITE,
        action(ActionKind.NORMAL, x=8, y=8),
    ).state
    return state


def legal_threshold_minus_one_state():
    size = 9
    config = OracleConfig(
        board_size=size,
        quotas=PlayerQuotas(
            black=SpecialQuotas.zero(),
            white=SpecialQuotas(immortal=1, double_start=0, eightway=0),
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
    if (
        state.atomic_action_count != 33
        or state.actor is not Color.WHITE
        or state.board.color_at(point(size, 4, 4)) is not None
    ):
        raise AssertionError("legal threshold prefix did not reach the intended state")
    return state


class ImmortalPlacementAndProtectionTests(unittest.TestCase):
    def test_zero_liberty_true_eye_placement_is_armed_and_protected(self) -> None:
        before, transition = play_zero_liberty_immortal()
        state = transition.state
        anchor = point(9, 4, 4)

        self.assertTrue(transition.accepted)
        self.assertEqual(ActionKind.IMMORTAL, transition.atomic_event.placed_stone.origin_kind)
        self.assertIn(anchor, state.occupancy.black)
        self.assertEqual(1, state.used_quotas.black.immortal)
        self.assertEqual(0, state.remaining_quotas.black.immortal)
        self.assertEqual(1, len(state.ledger))
        event = state.ledger[0]
        self.assertEqual(AbilityState.ARMED, event.ability_state)
        self.assertEqual(StoneState.ON_BOARD, event.stone_state)
        self.assertEqual(SettlementState.PENDING, event.settlement_state)
        self.assertFalse(event.tombstone)

        group = next(
            group
            for group in scan_n4_groups(state.board, state.ledger)
            if anchor in group.stones
        )
        self.assertEqual((), group.liberties)
        self.assertTrue(group.protected)
        self.assertEqual((anchor,), group.immortal_anchor_points)
        self.assertFalse(
            next(
                group
                for group in scan_n4_groups(state.board)
                if anchor in group.stones
            ).protected
        )
        self.assertEqual(before.psk_history + (state.occupancy,), state.psk_history)

    def test_official_19x19_true_eye_commits_then_settles_exactly(self) -> None:
        size = 19
        state = new_game(OracleConfig(board_size=size))
        setup = (
            (Color.BLACK, 18, 18),
            (Color.WHITE, 9, 8),
            (Color.BLACK, 18, 17),
            (Color.WHITE, 8, 9),
            (Color.BLACK, 17, 18),
            (Color.WHITE, 10, 9),
            (Color.BLACK, 17, 17),
            (Color.WHITE, 9, 10),
            (Color.BLACK, 16, 18),
            (Color.WHITE, 8, 8),
            (Color.BLACK, 18, 16),
            (Color.WHITE, 10, 8),
            (Color.BLACK, 16, 16),
            (Color.WHITE, 8, 10),
            (Color.BLACK, 16, 17),
            (Color.WHITE, 10, 10),
        )
        for actor, x, y in setup:
            state = accept(
                state,
                actor,
                action(ActionKind.NORMAL, size=size, x=x, y=y),
            ).state

        for kind in (ActionKind.NORMAL, ActionKind.DOUBLE_START):
            with self.subTest(kind=kind):
                rejected = apply_action(
                    state,
                    Color.BLACK,
                    action(kind, size=size, x=9, y=9),
                )
                self.assertEqual(RejectionCode.SUICIDE, rejected.rejection_code)
                self.assertIs(state, rejected.state)

        placed = accept(
            state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, size=size, x=9, y=9),
        )
        anchor = point(size, 9, 9)
        self.assertEqual(541, placed.action.action_id)
        self.assertEqual(17, placed.atomic_event.action_number)
        self.assertEqual(17, placed.atomic_event.psk_history_index)
        self.assertEqual(17, placed.state.revision)
        self.assertEqual(17, placed.state.log_position)
        self.assertEqual(anchor, placed.state.ledger[0].source_point)
        group = next(
            group
            for group in scan_n4_groups(placed.state.board, placed.state.ledger)
            if anchor in group.stones
        )
        self.assertEqual((anchor,), group.stones)
        self.assertEqual((), group.liberties)
        self.assertTrue(group.protected)
        self.assertEqual((anchor,), group.immortal_anchor_points)

        passed = accept(placed.state, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept(passed, Color.BLACK, action(ActionKind.PASS))
        self.assertEqual(19, settled.atomic_event.action_number)
        self.assertEqual(19, settled.atomic_event.psk_history_index)
        self.assertEqual(Phase.ORDINARY_PLAY, settled.state.phase)
        self.assertEqual(Color.WHITE, settled.state.actor)
        self.assertEqual(19, settled.state.atomic_action_count)
        self.assertEqual(19, settled.state.revision)
        self.assertEqual(20, settled.state.log_position)
        self.assertEqual(21, len(settled.state.psk_history))
        self.assertEqual(0, settled.state.consecutive_passes)
        step = settled.settlement.steps[0]
        self.assertTrue(step.ability_deactivated)
        self.assertFalse(step.no_op)
        self.assertEqual(
            (Occupancy(black=(anchor,)),),
            step.removal_batches,
        )
        self.assertEqual(20, step.psk_history_index)
        self.assertNotIn(anchor, settled.state.occupancy.black)
        event = settled.state.ledger[0]
        self.assertEqual(AbilityState.INACTIVE, event.ability_state)
        self.assertEqual(StoneState.CAPTURED, event.stone_state)
        self.assertEqual(SettlementState.SETTLED, event.settlement_state)
        self.assertTrue(event.tombstone)
        self.assertEqual(1, settled.state.used_quotas.black.immortal)
        self.assertEqual(PlayerQuotas.zero(), settled.state.remaining_quotas)

    def test_immortal_uses_the_same_simultaneous_opponent_capture_transaction(self) -> None:
        size = 9
        center = point(size, 2, 2)
        upper = point(size, 2, 1)
        lower = point(size, 2, 3)
        initial = new_game(OracleConfig(board_size=size))
        board = Board.from_points(
            size,
            black=(
                point(size, 2, 0),
                point(size, 1, 1),
                point(size, 3, 1),
                point(size, 1, 3),
                point(size, 3, 3),
                point(size, 2, 4),
            ),
            white=(upper, lower),
        )
        action_count = len(board.stones)
        state = replace(
            initial,
            board=board,
            atomic_action_count=action_count,
            psk_history=(Occupancy.empty(),) * action_count + (board.occupancy,),
            revision=action_count,
            log_position=action_count,
        )
        transition = accept(
            state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=2, y=2),
        )
        self.assertEqual((upper, lower), transition.atomic_event.captured.white)
        self.assertEqual((), transition.state.occupancy.white)
        self.assertIn(center, transition.state.occupancy.black)
        self.assertEqual(ActionKind.IMMORTAL, transition.state.ledger[-1].kind)

    def test_normal_and_double_attachments_can_fill_the_last_liberty(self) -> None:
        checkpoint = protected_anchor_checkpoint(two_liberties=False)
        last_liberty = point(9, 5, 4)

        normal = accept(
            checkpoint,
            Color.BLACK,
            action(ActionKind.NORMAL, x=5, y=4),
        )
        normal_group = next(
            group
            for group in scan_n4_groups(normal.state.board, normal.state.ledger)
            if last_liberty in group.stones
        )
        self.assertEqual((), normal_group.liberties)
        self.assertTrue(normal_group.protected)
        self.assertEqual(ActionKind.NORMAL, normal.atomic_event.placed_stone.origin_kind)

        double = accept(
            checkpoint,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=5, y=4),
        )
        double_group = next(
            group
            for group in scan_n4_groups(double.state.board, double.state.ledger)
            if last_liberty in group.stones
        )
        self.assertEqual((), double_group.liberties)
        self.assertTrue(double_group.protected)
        self.assertIsNotNone(double.state.pending_double)
        self.assertEqual(
            ActionKind.DOUBLE_START,
            double.atomic_event.placed_stone.origin_kind,
        )

    def test_double_normal_continuation_can_fill_final_group_liberty(self) -> None:
        checkpoint = protected_anchor_checkpoint(two_liberties=True)
        started = accept(
            checkpoint,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=5, y=4),
        )
        self.assertIsNotNone(started.state.pending_double)

        continued = accept(
            started.state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=5),
        )
        group = next(
            group
            for group in scan_n4_groups(continued.state.board, continued.state.ledger)
            if point(9, 4, 4) in group.stones
        )
        self.assertEqual((), group.liberties)
        self.assertTrue(group.protected)
        self.assertIsNone(continued.state.pending_double)
        self.assertEqual(Color.WHITE, continued.state.actor)

    def test_synthetic_n4_scan_split_is_topology_only_not_reachable_gameplay(self) -> None:
        # This directly probes dynamic full-board reconstruction. N4 Immortal-only
        # gameplay has no move that selectively removes the same-color bridge.
        anchor = Stone(0, Color.BLACK, 1, ActionKind.IMMORTAL, "special-1")
        bridge = Stone(1, Color.BLACK, 2, ActionKind.NORMAL)
        remote = Stone(2, Color.BLACK, 3, ActionKind.NORMAL)
        event = SpecialEvent(
            event_id="special-1",
            logical_order=0,
            owner=Color.BLACK,
            kind=ActionKind.IMMORTAL,
            source_point=0,
            source_stone_id="stone-1",
            ability_state=AbilityState.ARMED,
            stone_state=StoneState.ON_BOARD,
            settlement_state=SettlementState.PENDING,
            tombstone=False,
        )
        connected = scan_n4_groups(Board.from_stones(9, (anchor, bridge, remote)), (event,))
        self.assertEqual(1, len(connected))
        self.assertTrue(connected[0].protected)

        split = scan_n4_groups(Board.from_stones(9, (anchor, remote)), (event,))
        by_stones = {group.stones: group for group in split}
        self.assertTrue(by_stones[(0,)].protected)
        self.assertFalse(by_stones[(2,)].protected)

    def test_opponent_protected_group_is_not_captured_by_full_board_scan(self) -> None:
        _, immortal = play_zero_liberty_immortal()
        anchor = point(9, 4, 4)
        response = accept(
            immortal.state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=8, y=8),
        )
        self.assertEqual((), response.atomic_event.captured.black)
        self.assertIsNotNone(response.state.board.stone_at(anchor))
        self.assertTrue(
            next(
                group
                for group in scan_n4_groups(response.state.board, response.state.ledger)
                if anchor in group.stones
            ).protected
        )


class ImmortalRollbackAndSettlementTests(unittest.TestCase):
    def test_psk_occupied_quota_and_pending_double_reject_exact_state(self) -> None:
        before, trial = play_zero_liberty_immortal()
        repeated_state = replace(
            before,
            psk_history=(
                before.psk_history[:-2]
                + (trial.state.occupancy, before.occupancy)
            ),
        )
        repeated = apply_action(
            repeated_state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=4, y=4),
        )
        self.assertEqual(RejectionCode.POSITIONAL_SUPERKO, repeated.rejection_code)
        self.assertIs(repeated_state, repeated.state)

        occupied = apply_action(
            trial.state,
            Color.WHITE,
            action(ActionKind.IMMORTAL, x=4, y=4),
        )
        self.assertEqual(RejectionCode.POINT_OCCUPIED, occupied.rejection_code)
        self.assertIs(trial.state, occupied.state)

        zero_quota = new_game(
            OracleConfig(board_size=9, quotas=PlayerQuotas.zero())
        )
        exhausted = apply_action(
            zero_quota,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=0, y=0),
        )
        self.assertEqual(RejectionCode.QUOTA_EXHAUSTED, exhausted.rejection_code)
        self.assertIs(zero_quota, exhausted.state)

        pending = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=0, y=0),
        ).state
        forbidden = apply_action(
            pending,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=0, y=0),
        )
        self.assertEqual(
            RejectionCode.DOUBLE_CONTINUATION_KIND_FORBIDDEN,
            forbidden.rejection_code,
        )
        self.assertIs(pending, forbidden.state)

    def test_action_t_commits_then_settles_with_simultaneous_removal_batch(self) -> None:
        before = legal_threshold_minus_one_state()
        transition = accept(
            before,
            Color.WHITE,
            action(ActionKind.IMMORTAL, x=4, y=4),
        )
        anchor = point(9, 4, 4)
        placed = transition.atomic_event.placed_stone
        if placed is None:
            raise AssertionError("action-T Immortal source is missing")

        self.assertEqual(34, transition.atomic_event.action_number)
        self.assertEqual(34, placed.origin_action_number)
        self.assertEqual(ActionKind.IMMORTAL, placed.origin_kind)
        self.assertIn(anchor, transition.atomic_event.stable_occupancy.white)
        self.assertEqual(before.occupancy.black, transition.atomic_event.stable_occupancy.black)

        final_event = transition.state.ledger[0]
        pending_event = replace(
            final_event,
            ability_state=AbilityState.ARMED,
            stone_state=StoneState.ON_BOARD,
            settlement_state=SettlementState.PENDING,
            tombstone=False,
        )
        atomic_board = Board.from_stones(9, transition.atomic_event.stable_stones)
        atomic_group = next(
            group
            for group in scan_n4_groups(atomic_board, (pending_event,))
            if anchor in group.stones
        )
        self.assertEqual((anchor,), atomic_group.stones)
        self.assertEqual((), atomic_group.liberties)
        self.assertTrue(atomic_group.protected)
        self.assertEqual((anchor,), atomic_group.immortal_anchor_points)

        self.assertEqual(Phase.ORDINARY_PLAY, transition.state.phase)
        self.assertEqual(Color.BLACK, transition.state.actor)
        self.assertEqual(1, transition.settlement.ledger_entry_count)
        step = transition.settlement.steps[0]
        self.assertTrue(step.ability_deactivated)
        self.assertFalse(step.no_op)
        self.assertEqual(
            (Occupancy(white=(anchor,)),),
            step.removal_batches,
        )
        self.assertNotIn(anchor, transition.state.occupancy.white)
        self.assertEqual(before.occupancy, transition.state.occupancy)
        self.assertEqual(StoneState.CAPTURED, final_event.stone_state)
        self.assertEqual(AbilityState.INACTIVE, final_event.ability_state)
        self.assertEqual(SettlementState.SETTLED, final_event.settlement_state)
        self.assertTrue(final_event.tombstone)
        self.assertEqual(1, transition.state.used_quotas.white.immortal)
        self.assertEqual(34, transition.atomic_event.psk_history_index)
        self.assertEqual(35, step.psk_history_index)
        self.assertEqual(35, transition.state.log_position)
        self.assertEqual(36, len(transition.state.psk_history))
        self.assertEqual(
            transition.atomic_event.stable_occupancy,
            transition.state.psk_history[34],
        )
        self.assertEqual(step.stable_occupancy, transition.state.psk_history[35])

    def test_two_anchor_zero_liberty_group_unwinds_one_anchor_at_a_time(self) -> None:
        size = 9
        config = OracleConfig(
            board_size=size,
            quotas=PlayerQuotas(
                black=SpecialQuotas(immortal=2, double_start=0, eightway=0),
                white=SpecialQuotas.zero(),
            ),
        )
        state = new_game(config)
        white_ring = ((4, 3), (3, 4), (4, 5), (5, 3), (6, 4), (5, 5))
        black_fillers = ((0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (0, 8))
        for black_point, white_point in zip(black_fillers, white_ring):
            state = accept(
                state,
                Color.BLACK,
                action(ActionKind.NORMAL, x=black_point[0], y=black_point[1]),
            ).state
            state = accept(
                state,
                Color.WHITE,
                action(ActionKind.NORMAL, x=white_point[0], y=white_point[1]),
            ).state

        older = point(size, 4, 4)
        newer = point(size, 5, 4)
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=4, y=4),
        ).state
        state = accept(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=8, y=8),
        ).state
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=5, y=4),
        ).state
        protected = next(
            group
            for group in scan_n4_groups(state.board, state.ledger)
            if older in group.stones
        )
        self.assertEqual((older, newer), protected.stones)
        self.assertEqual((), protected.liberties)
        self.assertTrue(protected.protected)
        self.assertEqual((older, newer), protected.immortal_anchor_points)
        occupancy_with_both = state.occupancy

        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept(state, Color.BLACK, action(ActionKind.PASS))
        newest_step, older_step = settled.settlement.steps
        self.assertEqual(("special-15", "special-13"), (
            newest_step.event_id,
            older_step.event_id,
        ))
        self.assertTrue(newest_step.ability_deactivated)
        self.assertFalse(newest_step.no_op)
        self.assertEqual((), newest_step.removal_batches)
        self.assertEqual(occupancy_with_both, newest_step.stable_occupancy)
        self.assertTrue(older_step.ability_deactivated)
        self.assertFalse(older_step.no_op)
        self.assertEqual(
            (Occupancy(black=(older, newer)),),
            older_step.removal_batches,
        )
        self.assertNotIn(older, older_step.stable_occupancy.black)
        self.assertNotIn(newer, older_step.stable_occupancy.black)
        self.assertEqual(Color.WHITE, settled.state.actor)
        self.assertEqual(2, settled.state.used_quotas.black.immortal)
        self.assertEqual(17, settled.state.atomic_action_count)
        self.assertEqual(19, settled.state.log_position)
        self.assertEqual(
            (newest_step.stable_occupancy, older_step.stable_occupancy),
            settled.state.psk_history[-2:],
        )
        self.assertTrue(all(
            event.stone_state is StoneState.CAPTURED
            and event.ability_state is AbilityState.INACTIVE
            and event.settlement_state is SettlementState.SETTLED
            and event.tombstone
            for event in settled.state.ledger
        ))

    def test_live_immortal_settlement_deactivates_without_board_removal(self) -> None:
        state = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=4, y=4),
        ).state
        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept(state, Color.BLACK, action(ActionKind.PASS))

        step = settled.settlement.steps[0]
        self.assertTrue(step.ability_deactivated)
        self.assertFalse(step.no_op)
        self.assertEqual((), step.removal_batches)
        self.assertEqual(StoneState.ON_BOARD, settled.state.ledger[0].stone_state)
        self.assertEqual(AbilityState.INACTIVE, settled.state.ledger[0].ability_state)
        self.assertTrue(settled.state.ledger[0].tombstone)
        self.assertFalse(scan_n4_groups(settled.state.board, settled.state.ledger)[0].protected)

    def test_settled_immortal_source_can_be_captured_without_refund(self) -> None:
        state = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=0, y=0),
        ).state
        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        state = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        self.assertEqual(Phase.ORDINARY_PLAY, state.phase)

        state = accept(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=1, y=0),
        ).state
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        ).state
        captured = accept(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=0, y=1),
        )
        self.assertEqual((0,), captured.atomic_event.captured.black)
        event = captured.state.ledger[0]
        self.assertEqual(StoneState.CAPTURED, event.stone_state)
        self.assertEqual(AbilityState.INACTIVE, event.ability_state)
        self.assertEqual(SettlementState.SETTLED, event.settlement_state)
        self.assertTrue(event.tombstone)
        self.assertEqual(1, captured.state.used_quotas.black.immortal)
        self.assertEqual(0, captured.state.remaining_quotas.black.immortal)

    def test_newer_immortal_removes_older_double_before_double_no_op(self) -> None:
        size = 9
        state = new_game(OracleConfig(board_size=size))
        white_ring = ((4, 3), (3, 4), (4, 5), (5, 3), (6, 4), (5, 5))
        black_fillers = ((0, 0), (2, 0), (4, 0), (6, 0), (8, 0), (0, 8))
        for black_point, white_point in zip(black_fillers, white_ring):
            state = accept(
                state,
                Color.BLACK,
                action(ActionKind.NORMAL, x=black_point[0], y=black_point[1]),
            ).state
            state = accept(
                state,
                Color.WHITE,
                action(ActionKind.NORMAL, x=white_point[0], y=white_point[1]),
            ).state

        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=4, y=4),
        ).state
        self.assertEqual("special-13", state.ledger[-1].event_id)
        state = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        state = accept(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=8, y=8),
        ).state
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=5, y=4),
        ).state
        protected = next(
            group
            for group in scan_n4_groups(state.board, state.ledger)
            if point(size, 4, 4) in group.stones
        )
        self.assertEqual((), protected.liberties)
        self.assertTrue(protected.protected)

        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept(state, Color.BLACK, action(ActionKind.PASS))
        immortal_step, double_step = settled.settlement.steps
        removed = Occupancy(
            black=(point(size, 4, 4), point(size, 5, 4)),
        )
        self.assertEqual(("special-16", "special-13"), (
            immortal_step.event_id,
            double_step.event_id,
        ))
        self.assertTrue(immortal_step.ability_deactivated)
        self.assertFalse(immortal_step.no_op)
        self.assertEqual((removed,), immortal_step.removal_batches)
        split_step = replace(
            immortal_step,
            removal_batches=(
                Occupancy(black=(point(size, 4, 4),)),
                Occupancy(black=(point(size, 5, 4),)),
            ),
        )
        with self.assertRaisesRegex(ValueError, "deterministic closure"):
            replace(
                settled,
                settlement=replace(
                    settled.settlement,
                    steps=(split_step, double_step),
                ),
            )
        self.assertEqual(19, immortal_step.psk_history_index)
        self.assertEqual(19, immortal_step.log_position)
        self.assertFalse(double_step.ability_deactivated)
        self.assertTrue(double_step.no_op)
        self.assertEqual((), double_step.removal_batches)
        self.assertEqual(20, double_step.psk_history_index)
        self.assertEqual(20, double_step.log_position)
        self.assertEqual(immortal_step.stable_occupancy, double_step.stable_occupancy)
        self.assertEqual(
            (immortal_step.stable_occupancy, double_step.stable_occupancy),
            settled.state.psk_history[-2:],
        )
        double_event, immortal_event = settled.state.ledger
        self.assertEqual(StoneState.CAPTURED, double_event.stone_state)
        self.assertEqual(AbilityState.INACTIVE, double_event.ability_state)
        self.assertEqual(SettlementState.SETTLED, double_event.settlement_state)
        self.assertTrue(double_event.tombstone)
        self.assertEqual(StoneState.CAPTURED, immortal_event.stone_state)
        self.assertEqual(18, settled.state.atomic_action_count)
        self.assertEqual(18, settled.state.revision)
        self.assertEqual(20, settled.state.log_position)

    def test_mixed_ledger_settles_newest_to_oldest_with_double_no_op(self) -> None:
        config = OracleConfig(
            board_size=9,
            quotas=PlayerQuotas(
                black=SpecialQuotas(immortal=2, double_start=0, eightway=0),
                white=SpecialQuotas(immortal=0, double_start=1, eightway=0),
            ),
        )
        state = new_game(config)
        sequence = (
            (Color.BLACK, action(ActionKind.IMMORTAL, x=0, y=0)),
            (Color.WHITE, action(ActionKind.DOUBLE_START, x=8, y=8)),
            (Color.WHITE, action(ActionKind.PASS)),
            (Color.BLACK, action(ActionKind.IMMORTAL, x=1, y=0)),
            (Color.WHITE, action(ActionKind.PASS)),
        )
        for actor, envelope in sequence:
            state = accept(state, actor, envelope).state
        settled = accept(state, Color.BLACK, action(ActionKind.PASS))

        self.assertEqual(
            ("special-4", "special-2", "special-1"),
            tuple(step.event_id for step in settled.settlement.steps),
        )
        self.assertEqual(
            (ActionKind.IMMORTAL, ActionKind.DOUBLE_START, ActionKind.IMMORTAL),
            tuple(step.kind for step in settled.settlement.steps),
        )
        self.assertEqual(
            (True, False, True),
            tuple(step.ability_deactivated for step in settled.settlement.steps),
        )
        self.assertEqual(
            (False, True, False),
            tuple(step.no_op for step in settled.settlement.steps),
        )
        self.assertTrue(all(not step.removal_batches for step in settled.settlement.steps))
        self.assertEqual(3, settled.state.settled_ledger_count)
        self.assertTrue(all(
            event.ability_state is AbilityState.INACTIVE
            and event.settlement_state is SettlementState.SETTLED
            and event.tombstone
            for event in settled.state.ledger
        ))


class ImmortalDeterminismAndD4Tests(unittest.TestCase):
    @staticmethod
    def transform(size: int, x: int, y: int, symmetry: int) -> tuple[int, int]:
        if symmetry & 2:
            x = size - 1 - x
        if symmetry & 1:
            y = size - 1 - y
        if symmetry & 4:
            x, y = y, x
        return x, y

    @classmethod
    def transform_index(cls, size: int, board_index: int, symmetry: int) -> int:
        x, y = cls.transform(
            size,
            board_index % size,
            board_index // size,
            symmetry,
        )
        return point(size, x, y)

    @classmethod
    def transform_occupancy(
        cls,
        occupancy: Occupancy,
        size: int,
        symmetry: int,
    ) -> Occupancy:
        return Occupancy(
            black=tuple(sorted(
                cls.transform_index(size, value, symmetry)
                for value in occupancy.black
            )),
            white=tuple(sorted(
                cls.transform_index(size, value, symmetry)
                for value in occupancy.white
            )),
        )

    @classmethod
    def transform_stones(cls, stones, size: int, symmetry: int):
        return tuple(sorted(
            (
                replace(
                    stone,
                    point=cls.transform_index(size, stone.point, symmetry),
                )
                for stone in stones
            ),
            key=lambda stone: stone.point,
        ))

    @classmethod
    def transform_decoded_action(cls, decoded, size: int, symmetry: int):
        if decoded.kind is ActionKind.PASS:
            return decoded
        x, y = cls.transform(
            size,
            decoded.board_point.x,
            decoded.board_point.y,
            symmetry,
        )
        return decode_action_v1(
            action(decoded.kind, size=size, x=x, y=y),
            size,
        )

    @classmethod
    def transform_state(cls, state, symmetry: int):
        size = state.board.size
        board = Board.from_stones(
            size,
            cls.transform_stones(state.board.stones, size, symmetry),
        )
        ledger = tuple(
            replace(
                event,
                source_point=cls.transform_index(
                    size,
                    event.source_point,
                    symmetry,
                ),
            )
            for event in state.ledger
        )
        history = tuple(
            cls.transform_occupancy(occupancy, size, symmetry)
            for occupancy in state.psk_history
        )
        return replace(
            state,
            board=board,
            ledger=ledger,
            psk_history=history,
        )

    @classmethod
    def transform_atomic_event(cls, atomic_event, size: int, symmetry: int):
        if atomic_event is None:
            return None
        placed_stone = atomic_event.placed_stone
        if placed_stone is not None:
            placed_stone = replace(
                placed_stone,
                point=cls.transform_index(size, placed_stone.point, symmetry),
            )
        return replace(
            atomic_event,
            action=cls.transform_decoded_action(
                atomic_event.action,
                size,
                symmetry,
            ),
            captured=cls.transform_occupancy(
                atomic_event.captured,
                size,
                symmetry,
            ),
            captured_stones=cls.transform_stones(
                atomic_event.captured_stones,
                size,
                symmetry,
            ),
            placed_stone=placed_stone,
            stable_occupancy=cls.transform_occupancy(
                atomic_event.stable_occupancy,
                size,
                symmetry,
            ),
            stable_stones=cls.transform_stones(
                atomic_event.stable_stones,
                size,
                symmetry,
            ),
        )

    @classmethod
    def transform_settlement(cls, settlement, size: int, symmetry: int):
        if settlement is None:
            return None
        steps = tuple(
            replace(
                step,
                removal_batches=tuple(
                    cls.transform_occupancy(batch, size, symmetry)
                    for batch in step.removal_batches
                ),
                stable_occupancy=cls.transform_occupancy(
                    step.stable_occupancy,
                    size,
                    symmetry,
                ),
                stable_stones=cls.transform_stones(
                    step.stable_stones,
                    size,
                    symmetry,
                ),
            )
            for step in settlement.steps
        )
        return replace(settlement, steps=steps)

    @classmethod
    def transform_transition(cls, transition, symmetry: int):
        size = transition.state.board.size
        return replace(
            transition,
            action=cls.transform_decoded_action(
                transition.action,
                size,
                symmetry,
            ),
            state=cls.transform_state(transition.state, symmetry),
            atomic_event=cls.transform_atomic_event(
                transition.atomic_event,
                size,
                symmetry,
            ),
            settlement=cls.transform_settlement(
                transition.settlement,
                size,
                symmetry,
            ),
        )

    @classmethod
    def group_projection(cls, groups, size: int, symmetry: int):
        projected = []
        for group in groups:
            projected.append((
                group.color.value,
                tuple(sorted(
                    cls.transform_index(size, value, symmetry)
                    for value in group.stones
                )),
                tuple(sorted(
                    cls.transform_index(size, value, symmetry)
                    for value in group.liberties
                )),
                group.protected,
                tuple(sorted(
                    cls.transform_index(size, value, symmetry)
                    for value in group.immortal_anchor_points
                )),
                tuple(sorted(
                    cls.transform_index(size, value, symmetry)
                    for value in group.eightway_anchor_points
                )),
            ))
        return tuple(sorted(projected, key=repr))

    @classmethod
    def run_true_eye_episode(cls, symmetry: int):
        size = 9
        sequence = (
            (Color.BLACK, ActionKind.NORMAL, 0, 0),
            (Color.WHITE, ActionKind.NORMAL, 4, 3),
            (Color.BLACK, ActionKind.NORMAL, 1, 0),
            (Color.WHITE, ActionKind.NORMAL, 3, 4),
            (Color.BLACK, ActionKind.NORMAL, 2, 0),
            (Color.WHITE, ActionKind.NORMAL, 5, 4),
            (Color.BLACK, ActionKind.NORMAL, 7, 7),
            (Color.WHITE, ActionKind.NORMAL, 4, 5),
            (Color.BLACK, ActionKind.IMMORTAL, 4, 4),
            (Color.WHITE, ActionKind.PASS, None, None),
            (Color.BLACK, ActionKind.PASS, None, None),
        )
        state = new_game(OracleConfig(board_size=size))
        transitions = []
        for actor, kind, x, y in sequence:
            if kind is ActionKind.PASS:
                envelope = action(ActionKind.PASS)
            else:
                transformed_x, transformed_y = cls.transform(
                    size,
                    x,
                    y,
                    symmetry,
                )
                envelope = action(
                    kind,
                    size=size,
                    x=transformed_x,
                    y=transformed_y,
                )
            transition = accept(state, actor, envelope)
            transitions.append(transition)
            state = transition.state
        return tuple(transitions)

    def test_empty_board_point_mapping_on_all_supported_sizes(self) -> None:
        for size in (9, 13, 19):
            for symmetry in range(8):
                with self.subTest(size=size, symmetry=symmetry):
                    x, y = self.transform(size, 1, 2, symmetry)
                    transition = accept(
                        new_game(OracleConfig(board_size=size)),
                        Color.BLACK,
                        action(ActionKind.IMMORTAL, size=size, x=x, y=y),
                    )
                    expected = point(size, x, y)
                    self.assertEqual((expected,), transition.state.occupancy.black)
                    self.assertEqual(expected, transition.state.ledger[0].source_point)
                    group = scan_n4_groups(
                        transition.state.board,
                        transition.state.ledger,
                    )[0]
                    self.assertEqual((expected,), group.immortal_anchor_points)
                    self.assertTrue(group.protected)

    def test_rich_true_eye_settlement_is_d4_equivariant_on_9x9(self) -> None:
        size = 9
        inverse_ids = (0, 1, 2, 3, 4, 6, 5, 7)
        base = self.run_true_eye_episode(0)
        base_anchor_state = base[8].state
        base_groups = scan_n4_groups(
            base_anchor_state.board,
            base_anchor_state.ledger,
        )
        self.assertTrue(any(
            group.protected
            and not group.liberties
            and group.immortal_anchor_points
            for group in base_groups
        ))
        self.assertIsNotNone(base[-1].settlement)
        self.assertTrue(base[-1].settlement.steps[0].removal_batches)

        for symmetry in range(8):
            with self.subTest(symmetry=symmetry):
                actual = self.run_true_eye_episode(symmetry)
                self.assertEqual(len(base), len(actual))
                for base_transition, actual_transition in zip(base, actual):
                    expected = self.transform_transition(
                        base_transition,
                        symmetry,
                    )
                    self.assertEqual(expected, actual_transition)
                    restored = self.transform_transition(
                        actual_transition,
                        inverse_ids[symmetry],
                    )
                    self.assertEqual(base_transition, restored)

                actual_anchor_state = actual[8].state
                actual_groups = scan_n4_groups(
                    actual_anchor_state.board,
                    actual_anchor_state.ledger,
                )
                self.assertEqual(
                    self.group_projection(base_groups, size, symmetry),
                    self.group_projection(actual_groups, size, 0),
                )
                self.assertEqual(
                    self.group_projection(base_groups, size, 0),
                    self.group_projection(
                        actual_groups,
                        size,
                        inverse_ids[symmetry],
                    ),
                )

                self.assertEqual(
                    self.transform_settlement(
                        base[-1].settlement,
                        size,
                        symmetry,
                    ),
                    actual[-1].settlement,
                )
                self.assertEqual(
                    self.transform_state(base[-1].state, symmetry),
                    actual[-1].state,
                )
                self.assertEqual(
                    base[-1].state,
                    self.transform_state(
                        actual[-1].state,
                        inverse_ids[symmetry],
                    ),
                )

    def test_repeated_execution_and_checkpoint_copies_are_exact(self) -> None:
        initial = new_game(OracleConfig(board_size=9))
        first = accept(
            initial,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=2, y=3),
        ).state
        checkpoints = (first, replace(first), copy.deepcopy(first))
        suffix = (
            (Color.WHITE, action(ActionKind.NORMAL, x=8, y=8)),
            (Color.BLACK, action(ActionKind.NORMAL, x=3, y=3)),
            (Color.WHITE, action(ActionKind.PASS)),
            (Color.BLACK, action(ActionKind.PASS)),
        )
        results = []
        for checkpoint in checkpoints:
            state = checkpoint
            transitions = []
            for actor, envelope in suffix:
                transition = accept(state, actor, envelope)
                transitions.append(transition)
                state = transition.state
            results.append((state, tuple(transitions)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])
        self.assertEqual(first.psk_history, results[0][1][0].state.psk_history[:-1])


if __name__ == "__main__":
    unittest.main()
