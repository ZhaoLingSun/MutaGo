from __future__ import annotations

import ast
import copy
import sys
import unittest
from dataclasses import fields, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from mutago import collapse_go as collapse_go_module  # noqa: E402
from mutago.collapse_go import normal_pass_oracle as oracle_module  # noqa: E402
from mutago.collapse_go import (  # noqa: E402
    PASS_ACTION_ID,
    AdministrativeTerminationReason,
    AdministrativeTerminationTransition,
    ActionKind,
    Color,
    ImmediateTerminalEvent,
    Occupancy,
    OracleConfig,
    OracleState,
    Phase,
    RejectionCode,
    TerminalReason,
    TerminalResult,
    Transition,
    apply_action,
    apply_administrative_termination,
    derive_legal_mask,
    enumerate_action_legality,
    new_game,
    score_chinese_area,
)

KIND_CODE = {
    ActionKind.NORMAL: 0,
    ActionKind.IMMORTAL: 1,
    ActionKind.DOUBLE_START: 2,
    ActionKind.EIGHTWAY: 3,
}


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
    return {
        "schemaVersion": "action-v1",
        "actionId": 361 * KIND_CODE[kind] + 19 * (y + offset) + x + offset,
        "kind": kind.value,
    }


def accept_action(
    state: OracleState,
    actor: Color,
    envelope: dict[str, object],
) -> Transition:
    transition = apply_action(state, actor, envelope)
    if not transition.accepted:
        raise AssertionError(f"unexpected rejection: {transition.rejection_code}")
    return transition


def enter_ordinary(*, with_special: bool = False) -> OracleState:
    state = new_game(OracleConfig(board_size=9))
    if with_special:
        state = accept_action(
            state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=1, y=2),
        ).state
        state = accept_action(state, Color.WHITE, action(ActionKind.PASS)).state
        transition = accept_action(state, Color.BLACK, action(ActionKind.PASS))
        if transition.settlement is None or len(transition.settlement.steps) != 1:
            raise AssertionError("special boundary did not complete its settlement")
        return transition.state
    state = accept_action(state, Color.BLACK, action(ActionKind.PASS)).state
    return accept_action(state, Color.WHITE, action(ActionKind.PASS)).state


def enter_pending_double() -> OracleState:
    state = new_game(OracleConfig(board_size=9))
    return accept_action(
        state,
        Color.BLACK,
        action(ActionKind.DOUBLE_START, x=4, y=4),
    ).state


def enter_score_terminal() -> OracleState:
    state = enter_ordinary()
    state = accept_action(state, Color.BLACK, action(ActionKind.PASS)).state
    return accept_action(state, Color.WHITE, action(ActionKind.PASS)).state


def transform_point(size: int, point: int, symmetry: int) -> int:
    x = point % size
    y = point // size
    if symmetry & 2:
        x = size - 1 - x
    if symmetry & 1:
        y = size - 1 - y
    if symmetry & 4:
        x, y = y, x
    return size * y + x


def transform_occupancy(
    occupancy: Occupancy,
    size: int,
    symmetry: int,
) -> Occupancy:
    return Occupancy(
        black=tuple(
            sorted(transform_point(size, point, symmetry) for point in occupancy.black)
        ),
        white=tuple(
            sorted(transform_point(size, point, symmetry) for point in occupancy.white)
        ),
    )


def transform_state(state: OracleState, symmetry: int) -> OracleState:
    size = state.board.size
    transformed_stones = tuple(
        replace(stone, point=transform_point(size, stone.point, symmetry))
        for stone in state.board.stones
    )
    return replace(
        state,
        board=type(state.board).from_stones(size, transformed_stones),
        ledger=tuple(
            replace(
                event,
                source_point=transform_point(size, event.source_point, symmetry),
            )
            for event in state.ledger
        ),
        psk_history=tuple(
            transform_occupancy(occupancy, size, symmetry)
            for occupancy in state.psk_history
        ),
    )


class AdministrativeReasonAndBoundaryTests(unittest.TestCase):
    def assert_exact_commit(
        self,
        before: OracleState,
        reason: AdministrativeTerminationReason,
        loser: Color,
    ) -> AdministrativeTerminationTransition:
        transition = apply_administrative_termination(before, loser, reason)
        self.assertTrue(transition.accepted)
        self.assertIsNone(transition.rejection_code)
        self.assertIsInstance(transition, AdministrativeTerminationTransition)
        self.assertIsInstance(transition.terminal_event, ImmediateTerminalEvent)

        after = transition.state
        event = transition.terminal_event
        self.assertIsNot(before, after)
        self.assertEqual(Phase.TERMINAL, after.phase)
        self.assertIsNone(after.actor)
        self.assertEqual(TerminalReason(reason.value), after.terminal.reason)
        self.assertIs(loser, after.terminal.loser)
        self.assertIs(loser.opponent(), after.terminal.winner)
        self.assertIsNone(after.terminal.score)

        self.assertEqual(before.atomic_action_count, after.atomic_action_count)
        self.assertEqual(before.consecutive_passes, after.consecutive_passes)
        self.assertEqual(before.settlement_completed, after.settlement_completed)
        self.assertEqual(
            before.stable_terminal_event_count + 1,
            after.stable_terminal_event_count,
        )
        self.assertEqual(before.revision + 1, after.revision)
        self.assertEqual(before.log_position + 1, after.log_position)
        self.assertEqual(
            before.psk_history + (before.board.occupancy,),
            after.psk_history,
        )
        self.assertEqual(after.log_position, len(after.psk_history) - 1)
        self.assertEqual(
            1
            + after.atomic_action_count
            + after.settled_ledger_count
            + after.stable_terminal_event_count,
            len(after.psk_history),
        )
        self.assertEqual(
            after.atomic_action_count + 1,
            after.revision,
        )
        self.assertEqual(
            after.atomic_action_count
            + after.settled_ledger_count
            + after.stable_terminal_event_count,
            after.log_position,
        )

        self.assertIs(reason, event.reason)
        self.assertIs(loser, event.loser)
        self.assertIs(loser.opponent(), event.winner)
        self.assertEqual(before.settlement_completed, event.settlement_completed)
        self.assertEqual(before.board.occupancy, event.stable_occupancy)
        self.assertEqual(before.board.stones, event.stable_stones)
        self.assertEqual(after.revision, event.revision)
        self.assertEqual(after.log_position, event.log_position)
        self.assertEqual(len(after.psk_history) - 1, event.psk_history_index)

        changed_fields = {
            "actor",
            "phase",
            "stable_terminal_event_count",
            "psk_history",
            "revision",
            "log_position",
            "terminal",
        }
        for state_field in fields(OracleState):
            if state_field.name not in changed_fields:
                self.assertEqual(
                    getattr(before, state_field.name),
                    getattr(after, state_field.name),
                    state_field.name,
                )
        for preserved_reference in (
            "config",
            "board",
            "initial_quotas",
            "remaining_quotas",
            "used_quotas",
            "expired_quotas",
            "ledger",
            "pending_double",
        ):
            self.assertIs(
                getattr(before, preserved_reference),
                getattr(after, preserved_reference),
                preserved_reference,
            )
        return transition

    def test_both_reasons_and_real_color_losers_ignore_current_actor(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        self.assertIs(Color.BLACK, state.actor)
        for reason in AdministrativeTerminationReason:
            for loser in Color:
                with self.subTest(reason=reason, loser=loser):
                    transition = self.assert_exact_commit(state, reason, loser)
                    self.assertIs(loser.opponent(), transition.state.terminal.winner)
                    if loser is Color.WHITE:
                        self.assertIsNot(loser, state.actor)

        canonical_string = apply_administrative_termination(
            state,
            "WHITE",
            AdministrativeTerminationReason.RESIGNATION,
        )
        self.assertTrue(canonical_string.accepted)
        self.assertIs(Color.WHITE, canonical_string.state.terminal.loser)

    def test_collapse_ordinary_and_pending_double_audit_boundaries(self) -> None:
        collapse = new_game(OracleConfig(board_size=9))
        collapse_result = self.assert_exact_commit(
            collapse,
            AdministrativeTerminationReason.RESIGNATION,
            Color.BLACK,
        )
        self.assertFalse(collapse_result.state.settlement_completed)
        self.assertFalse(collapse_result.terminal_event.settlement_completed)

        ordinary = enter_ordinary(with_special=True)
        ordinary_result = self.assert_exact_commit(
            ordinary,
            AdministrativeTerminationReason.TIMEOUT,
            Color.WHITE,
        )
        self.assertTrue(ordinary_result.state.settlement_completed)
        self.assertTrue(ordinary_result.terminal_event.settlement_completed)
        self.assertTrue(all(event.tombstone for event in ordinary_result.state.ledger))

        pending = enter_pending_double()
        pending_result = self.assert_exact_commit(
            pending,
            AdministrativeTerminationReason.TIMEOUT,
            Color.WHITE,
        )
        self.assertFalse(pending_result.state.settlement_completed)
        self.assertFalse(pending_result.terminal_event.settlement_completed)
        self.assertIs(pending.pending_double, pending_result.state.pending_double)
        self.assertIs(pending.ledger, pending_result.state.ledger)
        self.assertEqual(Color.BLACK, pending.pending_double.owner)
        self.assertIs(Color.WHITE, pending_result.state.terminal.loser)

    def test_settlement_completed_is_explicit_and_phase_consistent(self) -> None:
        collapse = new_game(OracleConfig(board_size=9))
        ordinary = enter_ordinary()
        score_terminal = enter_score_terminal()
        self.assertFalse(collapse.settlement_completed)
        self.assertTrue(ordinary.settlement_completed)
        self.assertTrue(score_terminal.settlement_completed)
        self.assertIn(
            "settlement_completed",
            {field.name for field in fields(OracleState)},
        )
        with self.assertRaisesRegex(ValueError, "collapse play cannot"):
            replace(collapse, settlement_completed=True)
        with self.assertRaisesRegex(ValueError, "ordinary play requires"):
            replace(ordinary, settlement_completed=False)

        settled_terminal = apply_administrative_termination(
            ordinary,
            Color.WHITE,
            AdministrativeTerminationReason.TIMEOUT,
        ).state
        with self.assertRaisesRegex(ValueError, "committed settlement trigger"):
            replace(settled_terminal, settlement_completed=False)

    def test_settlement_and_score_require_committed_action_provenance(self) -> None:
        zero_state = new_game(
            OracleConfig(
                board_size=9,
                quotas=oracle_module.PlayerQuotas.zero(),
            )
        )
        administrative = apply_administrative_termination(
            zero_state,
            Color.BLACK,
            AdministrativeTerminationReason.TIMEOUT,
        ).state
        with self.assertRaisesRegex(ValueError, "committed.*trigger"):
            replace(administrative, settlement_completed=True)

        two_normals = accept_action(
            zero_state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=0),
        ).state
        two_normals = accept_action(
            two_normals,
            Color.WHITE,
            action(ActionKind.NORMAL, x=8, y=8),
        ).state
        with self.assertRaisesRegex(ValueError, "committed settlement trigger"):
            replace(
                two_normals,
                phase=Phase.ORDINARY_PLAY,
                settlement_completed=True,
            )
        two_normal_terminal = apply_administrative_termination(
            two_normals,
            Color.BLACK,
            AdministrativeTerminationReason.TIMEOUT,
        ).state
        with self.assertRaisesRegex(ValueError, "committed settlement trigger"):
            replace(two_normal_terminal, settlement_completed=True)

        score_terminal = enter_score_terminal()
        relabeled_terminal = TerminalResult(
            reason=TerminalReason.TIMEOUT,
            winner=score_terminal.terminal.winner,
            loser=score_terminal.terminal.loser,
            score=None,
        )
        with self.assertRaisesRegex(ValueError, "committed action suffix"):
            replace(
                score_terminal,
                terminal=relabeled_terminal,
                consecutive_passes=1,
                revision=score_terminal.atomic_action_count + 1,
            )

        nonempty_score = zero_state
        for color, candidate in (
            (Color.BLACK, action(ActionKind.PASS)),
            (Color.WHITE, action(ActionKind.PASS)),
            (Color.BLACK, action(ActionKind.NORMAL, x=0, y=0)),
            (Color.WHITE, action(ActionKind.PASS)),
            (Color.BLACK, action(ActionKind.PASS)),
        ):
            nonempty_score = accept_action(
                nonempty_score,
                color,
                candidate,
            ).state
        forged_nonempty_history = list(nonempty_score.psk_history)
        forged_nonempty_history[4] = Occupancy.empty()
        forged_nonempty_stones = tuple(
            replace(stone, origin_action_number=5)
            if stone.point == 0
            else stone
            for stone in nonempty_score.board.stones
        )
        forged_nonempty_terminal = TerminalResult(
            reason=TerminalReason.TIMEOUT,
            winner=nonempty_score.terminal.winner,
            loser=nonempty_score.terminal.loser,
            score=None,
        )
        with self.assertRaisesRegex(ValueError, "PSK"):
            replace(
                nonempty_score,
                board=type(nonempty_score.board).from_stones(
                    9, forged_nonempty_stones
                ),
                terminal=forged_nonempty_terminal,
                consecutive_passes=0,
                revision=nonempty_score.atomic_action_count + 1,
                psk_history=tuple(forged_nonempty_history),
            )

        forged_earlier_score_history = list(nonempty_score.psk_history)
        forged_earlier_score_history[3] = Occupancy.empty()
        forged_earlier_score_history[4] = Occupancy.empty()
        with self.assertRaisesRegex(ValueError, "earlier scoring boundary"):
            replace(
                nonempty_score,
                board=type(nonempty_score.board).from_stones(
                    9, forged_nonempty_stones
                ),
                terminal=forged_nonempty_terminal,
                consecutive_passes=0,
                revision=nonempty_score.atomic_action_count + 1,
                psk_history=tuple(forged_earlier_score_history),
            )

        threshold_checkpoint = zero_state
        threshold_checkpoint = accept_action(
            threshold_checkpoint,
            Color.BLACK,
            action(ActionKind.PASS),
        ).state
        threshold_checkpoint = accept_action(
            threshold_checkpoint,
            Color.WHITE,
            action(ActionKind.PASS),
        ).state
        placed = 0
        for point in range(9 * 9):
            x = point % 9
            y = point // 9
            if (x + y) % 2 != 0:
                continue
            self.assertIsNotNone(threshold_checkpoint.actor)
            threshold_checkpoint = accept_action(
                threshold_checkpoint,
                threshold_checkpoint.actor,
                action(ActionKind.NORMAL, x=x, y=y),
            ).state
            placed += 1
            if placed == 32:
                break
        self.assertEqual(threshold_checkpoint.config.threshold, 34)
        self.assertEqual(threshold_checkpoint.atomic_action_count, 34)
        relabeled_checkpoint_stones = tuple(
            replace(stone, origin_action_number=2)
            if stone.point == 0
            else stone
            for stone in threshold_checkpoint.board.stones
        )
        with self.assertRaisesRegex(ValueError, "live stone source"):
            replace(
                threshold_checkpoint,
                board=type(threshold_checkpoint.board).from_stones(
                    9, relabeled_checkpoint_stones
                ),
            )

        extra_pass_history = list(score_terminal.psk_history)
        extra_pass_history.insert(-1, score_terminal.psk_history[-1])
        with self.assertRaisesRegex(ValueError, "more than two passes"):
            replace(
                score_terminal,
                atomic_action_count=score_terminal.atomic_action_count + 1,
                revision=score_terminal.revision + 1,
                log_position=score_terminal.log_position + 1,
                psk_history=tuple(extra_pass_history),
            )

        empty = Occupancy.empty()
        with self.assertRaisesRegex(ValueError, "settlement trigger.*ordinary passes"):
            replace(
                score_terminal,
                atomic_action_count=2,
                revision=2,
                log_position=3,
                psk_history=(empty, empty, empty, empty),
            )

        forged_history = list(score_terminal.psk_history)
        forged_history[-3] = Occupancy(black=(0,))
        with self.assertRaisesRegex(ValueError, "live stone source"):
            replace(score_terminal, psk_history=tuple(forged_history))

        with self.assertRaisesRegex(ValueError, "live stone source"):
            replace(
                score_terminal,
                terminal=relabeled_terminal,
                consecutive_passes=0,
                revision=score_terminal.atomic_action_count + 1,
                psk_history=tuple(forged_history),
            )

    def test_immediate_terminal_positions_are_strictly_positive(self) -> None:
        transition = apply_administrative_termination(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            AdministrativeTerminationReason.RESIGNATION,
        )
        event = transition.terminal_event
        self.assertIsInstance(event, ImmediateTerminalEvent)
        self.assertEqual(event, replace(event))
        self.assertGreater(event.psk_history_index, 0)
        self.assertGreater(event.revision, 0)
        self.assertGreater(event.log_position, 0)

        for field_name in (
            "psk_history_index",
            "revision",
            "log_position",
        ):
            for invalid_value in (0, -1):
                with self.subTest(
                    field=field_name,
                    invalid_value=invalid_value,
                ):
                    with self.assertRaisesRegex(ValueError, "integer in 1"):
                        replace(event, **{field_name: invalid_value})

    def test_rejected_transition_binds_terminal_first_rejection_precedence(self) -> None:
        active = new_game(OracleConfig(board_size=9))
        invalid_loser = apply_administrative_termination(
            active,
            "EMPTY",
            AdministrativeTerminationReason.TIMEOUT,
        )
        self.assertFalse(invalid_loser.accepted)
        self.assertIs(RejectionCode.INVALID_LOSER, invalid_loser.rejection_code)
        self.assertEqual(invalid_loser, replace(invalid_loser))
        with self.assertRaisesRegex(ValueError, "terminal-first precedence"):
            replace(
                invalid_loser,
                rejection_code=RejectionCode.TERMINAL_STATE,
            )

        terminal = apply_administrative_termination(
            active,
            Color.BLACK,
            AdministrativeTerminationReason.RESIGNATION,
        ).state
        terminal_first = apply_administrative_termination(
            terminal,
            "EMPTY",
            AdministrativeTerminationReason.TIMEOUT,
        )
        self.assertFalse(terminal_first.accepted)
        self.assertIs(RejectionCode.TERMINAL_STATE, terminal_first.rejection_code)
        self.assertEqual(terminal_first, replace(terminal_first))
        with self.assertRaisesRegex(ValueError, "terminal-first precedence"):
            replace(
                terminal_first,
                rejection_code=RejectionCode.INVALID_LOSER,
            )

    def test_terminal_state_rejects_correlated_normal_source_relabeling(self) -> None:
        state = new_game(
            OracleConfig(
                board_size=9,
                quotas=oracle_module.PlayerQuotas.zero(),
            )
        )
        state = accept_action(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=0),
        ).state
        state = accept_action(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=8, y=8),
        ).state
        terminal = apply_administrative_termination(
            state,
            Color.BLACK,
            AdministrativeTerminationReason.RESIGNATION,
        ).state
        swapped = tuple(
            replace(stone, origin_action_number=3 - stone.origin_action_number)
            for stone in terminal.board.stones
        )
        with self.assertRaisesRegex(ValueError, "live stone source"):
            replace(
                terminal,
                board=type(terminal.board).from_stones(9, swapped),
            )

        relabeled_special = new_game(OracleConfig(board_size=9))
        relabeled_special = accept_action(
            relabeled_special,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=4, y=4),
        ).state
        relabeled_special = accept_action(
            relabeled_special,
            Color.BLACK,
            action(ActionKind.PASS),
        ).state
        relabeled_special = apply_administrative_termination(
            relabeled_special,
            Color.BLACK,
            AdministrativeTerminationReason.RESIGNATION,
        ).state
        relabeled_special_stones = tuple(
            replace(
                stone,
                origin_kind=ActionKind.NORMAL,
                special_event_id=None,
            )
            if stone.point == 4 + 4 * 9
            else stone
            for stone in relabeled_special.board.stones
        )
        relabeled_special_ledger = (
            replace(
                relabeled_special.ledger[0],
                stone_state=oracle_module.StoneState.CAPTURED,
            ),
        )
        with self.assertRaisesRegex(ValueError, "captured special event source"):
            replace(
                relabeled_special,
                board=type(relabeled_special.board).from_stones(
                    9, relabeled_special_stones
                ),
                ledger=relabeled_special_ledger,
            )

    def test_terminal_state_rejects_same_point_source_replay_relabeling(self) -> None:
        state = new_game(
            OracleConfig(
                board_size=9,
                quotas=oracle_module.PlayerQuotas.zero(),
            )
        )
        for color, x, y in (
            (Color.BLACK, 0, 0),
            (Color.WHITE, 1, 0),
            (Color.BLACK, 2, 0),
            (Color.WHITE, 0, 1),
            (Color.BLACK, 1, 1),
            (Color.WHITE, 8, 8),
            (Color.BLACK, 0, 0),
        ):
            state = accept_action(
                state,
                color,
                action(ActionKind.NORMAL, x=x, y=y),
            ).state
        terminal = apply_administrative_termination(
            state,
            Color.WHITE,
            AdministrativeTerminationReason.RESIGNATION,
        ).state
        relabeled = tuple(
            replace(stone, origin_action_number=1)
            if stone.point == 0
            else stone
            for stone in terminal.board.stones
        )
        with self.assertRaisesRegex(ValueError, "live stone source"):
            replace(
                terminal,
                board=type(terminal.board).from_stones(9, relabeled),
            )

    def test_transition_rejects_each_forged_event_state_binding_mismatch(
        self,
    ) -> None:
        pending_double = enter_pending_double()
        post_settlement = enter_ordinary(with_special=True)
        self.assertIsNotNone(pending_double.pending_double)
        self.assertFalse(pending_double.settlement_completed)
        self.assertIsNone(post_settlement.pending_double)
        self.assertTrue(post_settlement.settlement_completed)

        alternate_snapshot = accept_action(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=0),
        ).state
        boundaries = (
            ("pending_double", pending_double),
            ("post_settlement", post_settlement),
        )
        for boundary, source in boundaries:
            for reason in AdministrativeTerminationReason:
                transition = apply_administrative_termination(
                    source,
                    Color.WHITE,
                    reason,
                )
                self.assertTrue(transition.accepted)
                self.assertEqual(transition, replace(transition))
                event = transition.terminal_event
                if not isinstance(event, ImmediateTerminalEvent):
                    raise AssertionError("expected an immediate terminal event")
                self.assertNotEqual(
                    event.stable_occupancy,
                    alternate_snapshot.occupancy,
                )
                self.assertNotEqual(event.stable_stones, alternate_snapshot.stones)

                other_reason = (
                    AdministrativeTerminationReason.TIMEOUT
                    if reason is AdministrativeTerminationReason.RESIGNATION
                    else AdministrativeTerminationReason.RESIGNATION
                )
                mismatches = (
                    ("reason", other_reason),
                    ("winner", event.loser),
                    ("loser", event.winner),
                    ("settlement_completed", not event.settlement_completed),
                    ("stable_occupancy", alternate_snapshot.occupancy),
                    ("stable_stones", alternate_snapshot.stones),
                    ("psk_history_index", event.psk_history_index + 1),
                    ("revision", event.revision + 1),
                    ("log_position", event.log_position + 1),
                )
                for field_name, forged_value in mismatches:
                    with self.subTest(
                        boundary=boundary,
                        reason=reason,
                        field=field_name,
                    ):
                        forged_event = copy.copy(event)
                        object.__setattr__(
                            forged_event,
                            field_name,
                            forged_value,
                        )
                        changed_fields = {
                            event_field.name
                            for event_field in fields(ImmediateTerminalEvent)
                            if getattr(forged_event, event_field.name)
                            != getattr(event, event_field.name)
                        }
                        self.assertEqual({field_name}, changed_fields)
                        with self.assertRaisesRegex(
                            ValueError,
                            "immediate terminal event must exactly match",
                        ):
                            replace(
                                transition,
                                terminal_event=forged_event,
                            )


class OrderingAndRollbackTests(unittest.TestCase):
    def test_termination_first_prevents_candidate_action_and_settlement(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        terminated = apply_administrative_termination(
            state,
            Color.WHITE,
            AdministrativeTerminationReason.RESIGNATION,
        )
        self.assertTrue(terminated.accepted)
        rejected_action = apply_action(
            terminated.state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=1, y=2),
        )
        self.assertFalse(rejected_action.accepted)
        self.assertEqual(RejectionCode.TERMINAL_STATE, rejected_action.rejection_code)
        self.assertIs(terminated.state, rejected_action.state)
        self.assertEqual(0, rejected_action.state.atomic_action_count)
        self.assertEqual((), rejected_action.state.ledger)
        self.assertFalse(rejected_action.state.settlement_completed)
        self.assertIsNone(rejected_action.atomic_event)
        self.assertIsNone(rejected_action.settlement)
        self.assertIsNone(rejected_action.terminal_event)

    def test_action_first_completes_full_settlement_before_termination(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        state = accept_action(
            state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=1, y=2),
        ).state
        state = accept_action(state, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept_action(state, Color.BLACK, action(ActionKind.PASS))
        self.assertIsNotNone(settled.settlement)
        self.assertEqual(1, len(settled.settlement.steps))
        self.assertEqual(Phase.ORDINARY_PLAY, settled.state.phase)
        self.assertTrue(settled.state.settlement_completed)
        self.assertEqual(1, settled.state.settled_ledger_count)
        self.assertIs(Color.WHITE, settled.state.actor)

        terminated = apply_administrative_termination(
            settled.state,
            Color.BLACK,
            AdministrativeTerminationReason.TIMEOUT,
        )
        self.assertTrue(terminated.accepted)
        self.assertTrue(terminated.terminal_event.settlement_completed)
        self.assertEqual(settled.state.board, terminated.state.board)
        self.assertEqual(settled.state.ledger, terminated.state.ledger)
        self.assertEqual(
            settled.state.settled_ledger_count,
            terminated.state.settled_ledger_count,
        )
        self.assertEqual(
            settled.state.log_position + 1,
            terminated.state.log_position,
        )
        self.assertEqual(
            settled.state.psk_history + (settled.state.occupancy,),
            terminated.state.psk_history,
        )
        self.assertIs(Color.BLACK, terminated.state.terminal.loser)
        self.assertIsNot(Color.BLACK, settled.state.actor)

    def test_invalid_loser_rejects_with_original_object_identity(self) -> None:
        state = enter_pending_double()
        snapshot = copy.deepcopy(state)
        for invalid_loser in ("EMPTY", "black", None, True, 7, object()):
            with self.subTest(invalid_loser=invalid_loser):
                transition = apply_administrative_termination(
                    state,
                    invalid_loser,  # type: ignore[arg-type]
                    AdministrativeTerminationReason.RESIGNATION,
                )
                self.assertFalse(transition.accepted)
                self.assertEqual(
                    RejectionCode.INVALID_LOSER,
                    transition.rejection_code,
                )
                self.assertIs(state, transition.state)
                self.assertEqual(snapshot, transition.state)
                self.assertIsNone(transition.terminal_event)

    def test_terminal_state_precedes_invalid_loser(self) -> None:
        state = enter_score_terminal()
        rejected = apply_administrative_termination(
            state,
            "EMPTY",
            AdministrativeTerminationReason.RESIGNATION,
        )
        self.assertFalse(rejected.accepted)
        self.assertEqual(RejectionCode.TERMINAL_STATE, rejected.rejection_code)
        self.assertIs(state, rejected.state)
        self.assertIsNone(rejected.terminal_event)

    def test_terminal_rejection_preserves_score_and_administrative_results(
        self,
    ) -> None:
        score_state = enter_score_terminal()
        score_result = score_state.terminal
        score_value = score_result.score
        for reason in AdministrativeTerminationReason:
            with self.subTest(source="score", reason=reason):
                rejected = apply_administrative_termination(
                    score_state,
                    Color.BLACK,
                    reason,
                )
                self.assertFalse(rejected.accepted)
                self.assertEqual(RejectionCode.TERMINAL_STATE, rejected.rejection_code)
                self.assertIs(score_state, rejected.state)
                self.assertIs(score_result, rejected.state.terminal)
                self.assertIs(score_value, rejected.state.terminal.score)
                self.assertIsNone(rejected.terminal_event)

        administrative_state = apply_administrative_termination(
            new_game(OracleConfig(board_size=9)),
            Color.WHITE,
            AdministrativeTerminationReason.TIMEOUT,
        ).state
        rejected = apply_administrative_termination(
            administrative_state,
            Color.BLACK,
            AdministrativeTerminationReason.RESIGNATION,
        )
        self.assertFalse(rejected.accepted)
        self.assertEqual(RejectionCode.TERMINAL_STATE, rejected.rejection_code)
        self.assertIs(administrative_state, rejected.state)
        self.assertIsNone(rejected.terminal_event)


class TerminalModelAndSymmetryTests(unittest.TestCase):
    def test_score_is_required_only_for_score_terminal_results(self) -> None:
        score = score_chinese_area(new_game(OracleConfig(board_size=9)).board)
        scored = TerminalResult(
            reason=TerminalReason.SCORE,
            winner=score.winner,
            loser=score.winner.opponent(),
            score=score,
        )
        self.assertIs(score, scored.score)
        with self.assertRaisesRegex(TypeError, "requires ScoreResult"):
            TerminalResult(
                reason=TerminalReason.SCORE,
                winner=Color.WHITE,
                loser=Color.BLACK,
                score=None,
            )

        for reason in (TerminalReason.RESIGNATION, TerminalReason.TIMEOUT):
            with self.subTest(reason=reason):
                result = TerminalResult(
                    reason=reason,
                    winner=Color.BLACK,
                    loser=Color.WHITE,
                )
                self.assertIsNone(result.score)
                with self.assertRaisesRegex(ValueError, "cannot contain a score"):
                    TerminalResult(
                        reason=reason,
                        winner=score.winner,
                        loser=score.winner.opponent(),
                        score=score,
                    )

        score_terminal = enter_score_terminal()
        self.assertEqual(TerminalReason.SCORE, score_terminal.terminal.reason)
        self.assertIsNotNone(score_terminal.terminal.score)
        self.assertEqual(score_terminal.atomic_action_count, score_terminal.revision)
        self.assertEqual(
            score_terminal.atomic_action_count
            + score_terminal.settled_ledger_count
            + score_terminal.stable_terminal_event_count,
            score_terminal.log_position,
        )

    def test_terminal_states_reject_forged_changed_psk_appends(self) -> None:
        score_terminal = enter_score_terminal()
        score_history = list(score_terminal.psk_history)
        score_history[-2] = Occupancy(black=(0,))
        self.assertNotEqual(score_history[-2], score_history[-1])
        with self.assertRaisesRegex(ValueError, "preserve unchanged occupancy"):
            replace(score_terminal, psk_history=tuple(score_history))

        administrative_source = new_game(OracleConfig(board_size=9))
        administrative_source = accept_action(
            administrative_source,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        ).state
        administrative_terminal = apply_administrative_termination(
            administrative_source,
            Color.WHITE,
            AdministrativeTerminationReason.TIMEOUT,
        ).state
        administrative_history = list(administrative_terminal.psk_history)
        administrative_history[-2] = Occupancy.empty()
        self.assertNotEqual(
            administrative_history[-2],
            administrative_history[-1],
        )
        with self.assertRaisesRegex(ValueError, "preserve unchanged occupancy"):
            replace(
                administrative_terminal,
                psk_history=tuple(administrative_history),
            )

    def test_all_eight_d4_transforms_preserve_administrative_semantics(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        state = accept_action(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=1, y=2),
        ).state
        state = accept_action(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=7, y=6),
        ).state
        state = accept_action(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=3, y=4),
        ).state
        self.assertIs(Color.WHITE, state.actor)

        for reason in AdministrativeTerminationReason:
            for loser in Color:
                base = apply_administrative_termination(state, loser, reason)
                for symmetry in range(8):
                    with self.subTest(
                        reason=reason,
                        loser=loser,
                        symmetry=symmetry,
                    ):
                        transformed_state = transform_state(state, symmetry)
                        transformed = apply_administrative_termination(
                            transformed_state,
                            loser,
                            reason,
                        )
                        self.assertEqual(base.accepted, transformed.accepted)
                        self.assertEqual(
                            base.state.terminal,
                            transformed.state.terminal,
                        )
                        self.assertEqual(
                            base.state.revision,
                            transformed.state.revision,
                        )
                        self.assertEqual(
                            base.state.log_position,
                            transformed.state.log_position,
                        )
                        self.assertEqual(
                            transform_occupancy(
                                base.terminal_event.stable_occupancy,
                                state.board.size,
                                symmetry,
                            ),
                            transformed.terminal_event.stable_occupancy,
                        )
                        self.assertEqual(
                            transform_occupancy(
                                base.state.psk_history[-1],
                                state.board.size,
                                symmetry,
                            ),
                            transformed.state.psk_history[-1],
                        )
                        expected_stones = tuple(
                            sorted(
                                (
                                    replace(
                                        stone,
                                        point=transform_point(
                                            state.board.size,
                                            stone.point,
                                            symmetry,
                                        ),
                                    )
                                    for stone in base.terminal_event.stable_stones
                                ),
                                key=lambda stone: stone.point,
                            )
                        )
                        self.assertEqual(
                            expected_stones,
                            transformed.terminal_event.stable_stones,
                        )

    def test_administrative_terminals_have_empty_unchanged_action_space(self) -> None:
        self.assertEqual(
            (
                "NORMAL",
                "IMMORTAL",
                "DOUBLE_START",
                "EIGHTWAY",
                "PASS",
            ),
            tuple(kind.value for kind in ActionKind),
        )
        self.assertEqual(1444, PASS_ACTION_ID)

        sources = (new_game(OracleConfig(board_size=9)), enter_ordinary())
        for source in sources:
            for reason in AdministrativeTerminationReason:
                with self.subTest(phase=source.phase, reason=reason):
                    terminal = apply_administrative_termination(
                        source,
                        Color.BLACK,
                        reason,
                    ).state
                    mask = derive_legal_mask(terminal)
                    legality = enumerate_action_legality(terminal)
                    self.assertEqual(PASS_ACTION_ID + 1, len(mask))
                    self.assertEqual(PASS_ACTION_ID + 1, len(legality))
                    self.assertFalse(any(mask))
                    self.assertTrue(all(code is not None for code in legality))
                    self.assertEqual(
                        RejectionCode.TERMINAL_STATE,
                        legality[PASS_ACTION_ID],
                    )
                    self.assertEqual(
                        {RejectionCode.POINT_OFF_BOARD, RejectionCode.TERMINAL_STATE},
                        set(legality),
                    )


class PublicSurfaceAndIndependenceTests(unittest.TestCase):
    def test_new_names_are_exported_once_and_action_transition_stays_action_only(
        self,
    ) -> None:
        expected_exports = {
            "AdministrativeTerminationReason": AdministrativeTerminationReason,
            "ImmediateTerminalEvent": ImmediateTerminalEvent,
            "AdministrativeTerminationTransition": AdministrativeTerminationTransition,
            "apply_administrative_termination": apply_administrative_termination,
        }
        for name, value in expected_exports.items():
            for module in (oracle_module, collapse_go_module):
                with self.subTest(name=name, module=module.__name__):
                    self.assertIs(value, getattr(module, name))
                    self.assertIn(name, module.__all__)
                    self.assertEqual(1, module.__all__.count(name))

        self.assertEqual(
            (
                "accepted",
                "action",
                "candidate_actor",
                "state",
                "rejection_code",
                "atomic_event",
                "settlement",
                "terminal_event",
            ),
            tuple(field.name for field in fields(Transition)),
        )

    def test_oracle_ast_remains_stdlib_only_and_administration_is_independent(
        self,
    ) -> None:
        oracle_path = (
            REPO_ROOT
            / "python"
            / "mutago"
            / "collapse_go"
            / "normal_pass_oracle.py"
        )
        tree = ast.parse(oracle_path.read_text(encoding="utf-8"))
        import_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                import_roots.add(node.module.split(".", 1)[0])
        self.assertEqual(
            {"__future__", "dataclasses", "enum", "typing"},
            import_roots,
        )

        class_names = [
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        ]
        for name in (
            "AdministrativeTerminationReason",
            "ImmediateTerminalEvent",
            "AdministrativeTerminationTransition",
        ):
            self.assertEqual(1, class_names.count(name), name)

        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "apply_administrative_termination"
        )
        called_names = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("apply_action", called_names)
        self.assertNotIn("score_chinese_area", called_names)
        self.assertNotIn("_settle_after_action", called_names)

        action_transition = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "Transition"
        )
        action_transition_source = ast.unparse(action_transition)
        self.assertNotIn("AdministrativeTermination", action_transition_source)
        self.assertNotIn("ImmediateTerminalEvent", action_transition_source)


if __name__ == "__main__":
    unittest.main()
