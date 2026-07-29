from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import replace as dataclass_replace
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
    SettlementReason,
    SettlementState,
    SpecialQuotas,
    StoneState,
    apply_action,
    new_game,
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
        raise ValueError("point action needs board-local coordinates")
    offset = (19 - size) // 2
    action_id = (
        361 * KIND_CODE[kind]
        + 19 * (y + offset)
        + x
        + offset
    )
    return {
        "schemaVersion": "action-v1",
        "actionId": action_id,
        "kind": kind.value,
    }


def off_footprint_action(kind: ActionKind) -> dict[str, object]:
    return {
        "schemaVersion": "action-v1",
        "actionId": 361 * KIND_CODE[kind],
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
    state = new_game(OracleConfig(board_size=9))
    board = Board.from_points(9, black=black, white=white)
    action_count = len(board.stones)
    history = (Occupancy.empty(),) * action_count + (board.occupancy,)
    return dataclass_replace(
        state,
        board=board,
        actor=actor,
        atomic_action_count=action_count,
        psk_history=history,
        revision=action_count,
        log_position=action_count,
    )


def state_at_action_32():
    state = new_game(OracleConfig(board_size=9))
    for board_point in range(15):
        state = accept(
            state,
            Color.BLACK,
            action(
                ActionKind.NORMAL,
                x=board_point % 9,
                y=board_point // 9,
            ),
        ).state
        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
    state = accept(
        state,
        Color.BLACK,
        action(ActionKind.NORMAL, x=6, y=1),
    ).state
    state = accept(
        state,
        Color.WHITE,
        action(ActionKind.NORMAL, x=8, y=8),
    ).state
    if state.atomic_action_count != 32 or state.actor is not Color.BLACK:
        raise AssertionError("threshold fixture did not reach A=T-2")
    return state


class DoubleStartAndContinuationTests(unittest.TestCase):
    def assert_rejected_unchanged(
        self,
        state,
        actor: Color,
        envelope: dict[str, object],
        code: RejectionCode,
    ):
        snapshot = copy.deepcopy(state)
        transition = apply_action(state, actor, envelope)
        self.assertFalse(transition.accepted)
        self.assertEqual(code, transition.rejection_code)
        self.assertIs(state, transition.state)
        self.assertEqual(snapshot, transition.state)
        return transition

    def test_start_and_normal_continuation_commit_independent_sources(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        started = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=4, y=4),
        )
        pending = started.state
        source = pending.board.stone_at(point(9, 4, 4))
        event = pending.ledger[0]

        self.assertEqual(1, pending.atomic_action_count)
        self.assertEqual(1, pending.revision)
        self.assertEqual(1, pending.log_position)
        self.assertEqual(Color.BLACK, pending.actor)
        self.assertEqual(0, pending.consecutive_passes)
        self.assertEqual(1, len(pending.psk_history) - 1)
        self.assertIs(source, started.atomic_event.placed_stone)
        self.assertEqual(ActionKind.DOUBLE_START, source.origin_kind)
        self.assertEqual("stone-1", source.source_id)
        self.assertEqual("special-1", source.special_event_id)
        self.assertEqual("special-1", event.event_id)
        self.assertEqual(0, event.logical_order)
        self.assertEqual(source.point, event.source_point)
        self.assertEqual(source.source_id, event.source_stone_id)
        self.assertEqual(AbilityState.CONSUMED, event.ability_state)
        self.assertEqual(StoneState.ON_BOARD, event.stone_state)
        self.assertEqual(SettlementState.PENDING, event.settlement_state)
        self.assertTrue(event.tombstone)
        self.assertEqual("special-1", pending.pending_double.event_id)
        self.assertEqual(Color.BLACK, pending.pending_double.owner)
        self.assertEqual(1, pending.pending_double.start_action_number)
        self.assertEqual(0, pending.remaining_quotas.black.double_start)
        self.assertEqual(1, pending.used_quotas.black.double_start)
        self.assertEqual(state.remaining_quotas.white, pending.remaining_quotas.white)

        continued = accept(
            pending,
            Color.BLACK,
            action(ActionKind.NORMAL, x=5, y=4),
        )
        ordinary_source = continued.state.board.stone_at(point(9, 5, 4))
        self.assertEqual(2, continued.state.atomic_action_count)
        self.assertEqual(2, continued.state.revision)
        self.assertEqual(2, continued.state.log_position)
        self.assertEqual(Color.WHITE, continued.state.actor)
        self.assertIsNone(continued.state.pending_double)
        self.assertEqual(ActionKind.NORMAL, ordinary_source.origin_kind)
        self.assertIsNone(ordinary_source.special_event_id)
        self.assertIs(ordinary_source, continued.atomic_event.placed_stone)
        self.assertEqual(1, continued.state.used_quotas.black.double_start)
        self.assertEqual(0, continued.state.remaining_quotas.black.double_start)
        self.assertEqual(AbilityState.CONSUMED, continued.state.ledger[0].ability_state)
        self.assertEqual(SettlementState.PENDING, continued.state.ledger[0].settlement_state)
        self.assertEqual(3, len(continued.state.psk_history))

    def test_pass_continuation_and_singleton_settlement_fixture(self) -> None:
        state = new_game(OracleConfig(board_size=19))
        started = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, size=19, x=9, y=9),
        )
        self.assertEqual(902, started.action.action_id)
        occupied = Occupancy(black=(180,), white=())
        self.assertEqual(occupied, started.state.occupancy)

        continued = accept(started.state, Color.BLACK, action(ActionKind.PASS))
        self.assertIs(started.state.board, continued.state.board)
        self.assertIsNone(continued.atomic_event.placed_stone)
        self.assertEqual((), continued.atomic_event.captured_stones)
        self.assertEqual(2, continued.state.atomic_action_count)
        self.assertEqual(1, continued.state.consecutive_passes)
        self.assertEqual(Color.WHITE, continued.state.actor)
        self.assertIsNone(continued.state.pending_double)
        self.assertEqual(continued.state.psk_history[-2], continued.state.psk_history[-1])

        settled = accept(continued.state, Color.WHITE, action(ActionKind.PASS))
        final = settled.state
        self.assertEqual(SettlementReason.PRE_THRESHOLD_TWO_PASSES, settled.settlement.reason)
        self.assertEqual(1, settled.settlement.ledger_entry_count)
        self.assertEqual(1, settled.settlement.psk_appends)
        self.assertEqual(1, len(settled.settlement.steps))
        step = settled.settlement.steps[0]
        self.assertEqual("special-1", step.event_id)
        self.assertTrue(step.no_op)
        self.assertFalse(step.ability_deactivated)
        self.assertEqual(4, step.psk_history_index)
        self.assertEqual(3, step.revision)
        self.assertEqual(4, step.log_position)
        self.assertEqual(3, final.atomic_action_count)
        self.assertEqual(3, final.revision)
        self.assertEqual(4, final.log_position)
        self.assertEqual(Phase.ORDINARY_PLAY, final.phase)
        self.assertEqual(Color.BLACK, final.actor)
        self.assertEqual(0, final.consecutive_passes)
        self.assertEqual(1, final.settled_ledger_count)
        self.assertEqual(
            (Occupancy.empty(), occupied, occupied, occupied, occupied),
            final.psk_history,
        )
        event = final.ledger[0]
        self.assertEqual(AbilityState.INACTIVE, event.ability_state)
        self.assertEqual(StoneState.ON_BOARD, event.stone_state)
        self.assertEqual(SettlementState.SETTLED, event.settlement_state)
        self.assertTrue(event.tombstone)
        self.assertEqual(PlayerQuotas.zero(), final.remaining_quotas)
        self.assertEqual(1, final.used_quotas.black.double_start)
        self.assertEqual(0, final.expired_quotas.black.double_start)
        self.assertEqual(1, final.expired_quotas.white.double_start)

    def test_pending_rejection_precedence_and_retry_preserve_exact_state(self) -> None:
        pending = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=4, y=4),
        ).state

        self.assert_rejected_unchanged(
            pending,
            Color.WHITE,
            off_footprint_action(ActionKind.DOUBLE_START),
            RejectionCode.POINT_OFF_BOARD,
        )
        self.assert_rejected_unchanged(
            pending,
            Color.WHITE,
            action(ActionKind.DOUBLE_START, x=3, y=3),
            RejectionCode.WRONG_ACTOR,
        )
        for kind in (
            ActionKind.IMMORTAL,
            ActionKind.DOUBLE_START,
            ActionKind.EIGHTWAY,
        ):
            with self.subTest(kind=kind):
                self.assert_rejected_unchanged(
                    pending,
                    Color.BLACK,
                    action(kind, x=4, y=4),
                    RejectionCode.DOUBLE_CONTINUATION_KIND_FORBIDDEN,
                )
        self.assert_rejected_unchanged(
            pending,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
            RejectionCode.POINT_OCCUPIED,
        )

        completed = accept(pending, Color.BLACK, action(ActionKind.PASS))
        self.assertIsNone(completed.state.pending_double)
        self.assertEqual(Color.WHITE, completed.state.actor)

    def test_suicide_and_psk_continuation_rejections_keep_pending(self) -> None:
        suicide_base = positioned_state(
            white=(
                point(9, 2, 1),
                point(9, 1, 2),
                point(9, 3, 2),
                point(9, 2, 3),
            )
        )
        suicide_pending = accept(
            suicide_base,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=0, y=0),
        ).state
        self.assert_rejected_unchanged(
            suicide_pending,
            Color.BLACK,
            action(ActionKind.NORMAL, x=2, y=2),
            RejectionCode.SUICIDE,
        )

        capture_base = positioned_state(
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
        psk_pending = accept(
            capture_base,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=8, y=8),
        ).state
        continuation = action(ActionKind.NORMAL, x=2, y=2)
        candidate = accept(psk_pending, Color.BLACK, continuation).state.occupancy
        history = list(psk_pending.psk_history)
        history[-3] = candidate
        repeated_state = dataclass_replace(
            psk_pending,
            psk_history=tuple(history),
        )
        self.assert_rejected_unchanged(
            repeated_state,
            Color.BLACK,
            continuation,
            RejectionCode.POSITIONAL_SUPERKO,
        )

    def test_threshold_acceptance_at_t_minus_2_and_rejection_after(self) -> None:
        at_t_minus_2 = state_at_action_32()
        started = accept(
            at_t_minus_2,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=7, y=8),
        )
        self.assertEqual(33, started.state.atomic_action_count)
        self.assertEqual(Color.BLACK, started.state.actor)
        self.assertIsNotNone(started.state.pending_double)

        final = accept(started.state, Color.BLACK, action(ActionKind.PASS))
        self.assertEqual(SettlementReason.THRESHOLD, final.settlement.reason)
        self.assertEqual(34, final.state.atomic_action_count)
        self.assertEqual(Phase.ORDINARY_PLAY, final.state.phase)
        self.assertEqual(Color.WHITE, final.state.actor)
        self.assertEqual(1, final.settlement.psk_appends)
        self.assertEqual(34, final.atomic_event.action_number)

        at_t_minus_1 = accept(
            at_t_minus_2,
            Color.BLACK,
            action(ActionKind.NORMAL, x=7, y=1),
        ).state
        self.assertEqual(33, at_t_minus_1.atomic_action_count)
        self.assert_rejected_unchanged(
            at_t_minus_1,
            Color.WHITE,
            action(ActionKind.DOUBLE_START, x=6, y=8),
            RejectionCode.DOUBLE_THRESHOLD,
        )
        self.assert_rejected_unchanged(
            final.state,
            final.state.actor,
            action(ActionKind.DOUBLE_START, x=6, y=8),
            RejectionCode.INVALID_PHASE,
        )


class DoubleLedgerSettlementTests(unittest.TestCase):
    def test_captured_source_is_not_refunded_and_settles_as_no_op(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=0, y=0),
        ).state
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=8, y=8),
        ).state
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
        state = captured.state
        self.assertEqual(("stone-1",), tuple(
            stone.source_id for stone in captured.atomic_event.captured_stones
        ))
        self.assertIsNone(state.board.stone_at(0))
        self.assertEqual(StoneState.CAPTURED, state.ledger[0].stone_state)
        self.assertEqual(AbilityState.CONSUMED, state.ledger[0].ability_state)
        self.assertEqual(1, state.used_quotas.black.double_start)
        self.assertEqual(0, state.remaining_quotas.black.double_start)

        state = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        settled = accept(state, Color.WHITE, action(ActionKind.PASS))
        self.assertEqual(1, settled.settlement.ledger_entry_count)
        self.assertEqual(1, settled.settlement.psk_appends)
        self.assertEqual(StoneState.CAPTURED, settled.state.ledger[0].stone_state)
        self.assertEqual(AbilityState.INACTIVE, settled.state.ledger[0].ability_state)
        self.assertEqual(SettlementState.SETTLED, settled.state.ledger[0].settlement_state)
        self.assertEqual(settled.state.psk_history[-2], settled.state.psk_history[-1])
        self.assertEqual(1, settled.state.used_quotas.black.double_start)

    def test_surviving_source_can_be_captured_after_settlement_and_replayed(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=0, y=0),
        ).state
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=8, y=8),
        ).state
        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        self.assertEqual(Phase.ORDINARY_PLAY, settled.phase)
        self.assertEqual(Color.WHITE, settled.actor)
        self.assertEqual(StoneState.ON_BOARD, settled.ledger[0].stone_state)
        self.assertEqual(AbilityState.INACTIVE, settled.ledger[0].ability_state)
        self.assertEqual(SettlementState.SETTLED, settled.ledger[0].settlement_state)

        suffix = (
            (Color.WHITE, action(ActionKind.NORMAL, x=1, y=0)),
            (Color.BLACK, action(ActionKind.NORMAL, x=4, y=4)),
            (Color.WHITE, action(ActionKind.NORMAL, x=0, y=1)),
        )
        results = []
        for checkpoint in (
            settled,
            dataclass_replace(settled),
            copy.deepcopy(settled),
        ):
            current = checkpoint
            last_transition = None
            for actor, envelope in suffix:
                last_transition = accept(current, actor, envelope)
                current = last_transition.state
            results.append((current, last_transition))

        final, capture = results[0]
        self.assertTrue(all(result[0] == final for result in results[1:]))
        self.assertTrue(all(result[1] == capture for result in results[1:]))
        self.assertEqual(
            ("stone-1",),
            tuple(stone.source_id for stone in capture.atomic_event.captured_stones),
        )
        self.assertIsNone(final.board.stone_at(0))
        self.assertEqual(StoneState.CAPTURED, final.ledger[0].stone_state)
        self.assertEqual(AbilityState.INACTIVE, final.ledger[0].ability_state)
        self.assertEqual(SettlementState.SETTLED, final.ledger[0].settlement_state)
        self.assertTrue(final.ledger[0].tombstone)
        self.assertEqual(1, final.used_quotas.black.double_start)
        self.assertEqual(PlayerQuotas.zero(), final.remaining_quotas)
        self.assertEqual(7, final.atomic_action_count)
        self.assertEqual(7, final.revision)
        self.assertEqual(8, final.log_position)
        self.assertEqual(8, capture.atomic_event.psk_history_index)
        self.assertEqual(9, len(final.psk_history))

    def test_multiple_events_pop_reverse_but_ledger_remains_append_only(self) -> None:
        config = OracleConfig(
            board_size=9,
            quotas=PlayerQuotas(
                black=SpecialQuotas(immortal=0, double_start=2, eightway=0),
                white=SpecialQuotas(immortal=0, double_start=1, eightway=0),
            ),
        )
        state = new_game(config)
        sequence = (
            (Color.BLACK, action(ActionKind.DOUBLE_START, x=0, y=0)),
            (Color.BLACK, action(ActionKind.NORMAL, x=0, y=1)),
            (Color.WHITE, action(ActionKind.DOUBLE_START, x=8, y=8)),
            (Color.WHITE, action(ActionKind.NORMAL, x=8, y=7)),
            (Color.BLACK, action(ActionKind.DOUBLE_START, x=4, y=4)),
            (Color.BLACK, action(ActionKind.PASS)),
        )
        for actor, envelope in sequence:
            state = accept(state, actor, envelope).state

        self.assertEqual(
            ("special-1", "special-3", "special-5"),
            tuple(event.event_id for event in state.ledger),
        )
        self.assertEqual((0, 2, 4), tuple(event.logical_order for event in state.ledger))
        self.assertEqual(2, state.used_quotas.black.double_start)
        self.assertEqual(1, state.used_quotas.white.double_start)
        self.assertEqual(PlayerQuotas.zero(), state.remaining_quotas)
        board_before = state.board
        settled = accept(state, Color.WHITE, action(ActionKind.PASS))

        self.assertEqual(
            ("special-5", "special-3", "special-1"),
            tuple(step.event_id for step in settled.settlement.steps),
        )
        self.assertEqual(
            (4, 2, 0),
            tuple(step.logical_order for step in settled.settlement.steps),
        )
        self.assertTrue(all(
            step.no_op
            and not step.ability_deactivated
            and step.stable_occupancy == settled.state.occupancy
            and step.stable_stones == settled.state.stones
            for step in settled.settlement.steps
        ))
        self.assertEqual(
            (8, 9, 10),
            tuple(step.psk_history_index for step in settled.settlement.steps),
        )
        self.assertEqual(
            (8, 9, 10),
            tuple(step.log_position for step in settled.settlement.steps),
        )
        self.assertEqual(
            ("special-1", "special-3", "special-5"),
            tuple(event.event_id for event in settled.state.ledger),
        )
        self.assertTrue(all(
            event.ability_state is AbilityState.INACTIVE
            and event.settlement_state is SettlementState.SETTLED
            and event.tombstone
            for event in settled.state.ledger
        ))
        self.assertIs(board_before, settled.state.board)
        self.assertEqual(3, settled.settlement.ledger_entry_count)
        self.assertEqual(3, settled.settlement.psk_appends)
        self.assertEqual(7, settled.state.atomic_action_count)
        self.assertEqual(7, settled.state.revision)
        self.assertEqual(10, settled.state.log_position)
        self.assertEqual(3, settled.state.settled_ledger_count)
        self.assertEqual(11, len(settled.state.psk_history))
        self.assertEqual(
            1
            + settled.state.atomic_action_count
            + settled.state.settled_ledger_count
            + settled.state.stable_terminal_event_count,
            len(settled.state.psk_history),
        )
        self.assertEqual(
            (settled.state.occupancy,) * 5,
            settled.state.psk_history[-5:],
        )

    def test_quota_greater_than_one_is_consumed_only_on_each_start(self) -> None:
        config = OracleConfig(
            board_size=9,
            quotas=PlayerQuotas(
                black=SpecialQuotas(immortal=0, double_start=2, eightway=0),
                white=SpecialQuotas.zero(),
            ),
        )
        state = new_game(config)
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=0, y=0),
        ).state
        self.assertEqual(1, state.remaining_quotas.black.double_start)
        self.assertEqual(1, state.used_quotas.black.double_start)
        state = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        self.assertEqual(1, state.used_quotas.black.double_start)
        state = accept(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=8, y=8),
        ).state
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=4, y=4),
        ).state
        self.assertEqual(0, state.remaining_quotas.black.double_start)
        self.assertEqual(2, state.used_quotas.black.double_start)
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=5, y=4),
        ).state
        state = accept(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=7, y=8),
        ).state
        transition = apply_action(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=2, y=2),
        )
        self.assertEqual(RejectionCode.QUOTA_EXHAUSTED, transition.rejection_code)
        self.assertIs(state, transition.state)


class DoubleReplayCheckpointTests(unittest.TestCase):
    def test_pending_and_settlement_checkpoints_replay_exactly(self) -> None:
        initial = new_game(OracleConfig(board_size=9))
        pending = accept(
            initial,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=4, y=4),
        ).state
        checkpoints = (pending, dataclass_replace(pending), copy.deepcopy(pending))

        for continuation in (
            action(ActionKind.NORMAL, x=5, y=4),
            action(ActionKind.PASS),
        ):
            with self.subTest(continuation=continuation["kind"]):
                transitions = tuple(
                    accept(checkpoint, Color.BLACK, continuation)
                    for checkpoint in checkpoints
                )
                self.assertEqual(transitions[0], transitions[1])
                self.assertEqual(transitions[0], transitions[2])

        sequence = (
            (Color.BLACK, action(ActionKind.DOUBLE_START, x=4, y=4)),
            (Color.BLACK, action(ActionKind.NORMAL, x=5, y=4)),
            (Color.WHITE, action(ActionKind.NORMAL, x=0, y=0)),
            (Color.BLACK, action(ActionKind.PASS)),
            (Color.WHITE, action(ActionKind.PASS)),
        )
        full = initial
        for actor, envelope in sequence:
            full = accept(full, actor, envelope).state

        replayed_states = []
        for checkpoint in checkpoints:
            state = checkpoint
            for actor, envelope in sequence[1:]:
                state = accept(state, actor, envelope).state
            replayed_states.append(state)
        self.assertTrue(all(state == full for state in replayed_states))
        self.assertEqual(Phase.ORDINARY_PLAY, full.phase)
        self.assertEqual(1, full.settled_ledger_count)
        self.assertEqual(AbilityState.INACTIVE, full.ledger[0].ability_state)
        self.assertEqual(SettlementState.SETTLED, full.ledger[0].settlement_state)
        self.assertEqual(full, dataclass_replace(full))
        self.assertEqual(full, copy.deepcopy(full))

    def test_constructor_rejects_broken_pending_quota_and_source_invariants(self) -> None:
        pending = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=4, y=4),
        ).state
        with self.assertRaisesRegex(ValueError, "owner|linkage"):
            dataclass_replace(
                pending,
                pending_double=dataclass_replace(
                    pending.pending_double,
                    owner=Color.WHITE,
                ),
            )
        with self.assertRaisesRegex(ValueError, "used Double quotas"):
            dataclass_replace(
                pending,
                remaining_quotas=pending.initial_quotas,
                used_quotas=PlayerQuotas.zero(),
            )
        with self.assertRaisesRegex(ValueError, "source (identity|linkage)"):
            dataclass_replace(
                pending,
                ledger=(dataclass_replace(pending.ledger[0], source_point=0),),
            )
    def test_constructor_rejects_impossible_event_timing_and_captured_identity(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=0, y=0),
        ).state
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=1),
        ).state
        pending = accept(
            state,
            Color.WHITE,
            action(ActionKind.DOUBLE_START, x=8, y=8),
        ).state
        impossible_second = dataclass_replace(
            pending.ledger[1],
            event_id="special-2",
            logical_order=1,
            source_stone_id="stone-2",
        )
        with self.assertRaisesRegex(ValueError, "intervening continuation"):
            dataclass_replace(
                pending,
                ledger=(pending.ledger[0], impossible_second),
            )

        captured = new_game(OracleConfig(board_size=9))
        capture_sequence = (
            (Color.BLACK, action(ActionKind.NORMAL, x=4, y=4)),
            (Color.WHITE, action(ActionKind.NORMAL, x=8, y=8)),
            (Color.BLACK, action(ActionKind.DOUBLE_START, x=0, y=0)),
            (Color.BLACK, action(ActionKind.NORMAL, x=4, y=5)),
            (Color.WHITE, action(ActionKind.NORMAL, x=1, y=0)),
            (Color.BLACK, action(ActionKind.NORMAL, x=5, y=5)),
            (Color.WHITE, action(ActionKind.NORMAL, x=0, y=1)),
        )
        for actor, envelope in capture_sequence:
            captured = accept(captured, actor, envelope).state
        self.assertEqual(StoneState.CAPTURED, captured.ledger[0].stone_state)
        with self.assertRaisesRegex(ValueError, "occupied before its action"):
            dataclass_replace(
                captured,
                ledger=(
                    dataclass_replace(
                        captured.ledger[0],
                        source_point=point(9, 4, 4),
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
