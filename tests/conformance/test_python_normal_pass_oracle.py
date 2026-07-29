from __future__ import annotations

import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from mutago.collapse_go import (  # noqa: E402
    PASS_ACTION_ID,
    ActionKind,
    ActionV1DecodeError,
    Board,
    Color,
    Occupancy,
    OracleConfig,
    Phase,
    PlayerQuotas,
    Point,
    RejectionCode,
    SettlementReason,
    SpecialQuotas,
    UnsupportedSliceAction,
    apply_action,
    decode_action_v1,
    new_game,
    scan_n4_groups,
    score_chinese_area,
    settlement_threshold,
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
        raise ValueError("point action needs board-local x and y")
    offset = (19 - size) // 2
    canvas_x = x + offset
    canvas_y = y + offset
    action_id = 361 * KIND_CODE[kind] + 19 * canvas_y + canvas_x
    return {
        "schemaVersion": "action-v1",
        "actionId": action_id,
        "kind": kind.value,
    }


def off_footprint_action(kind: ActionKind = ActionKind.NORMAL) -> dict[str, object]:
    return {
        "schemaVersion": "action-v1",
        "actionId": 361 * KIND_CODE[kind],
        "kind": kind.value,
    }


def positioned_state(
    *,
    black: tuple[int, ...] = (),
    white: tuple[int, ...] = (),
    config: OracleConfig | None = None,
    actor: Color = Color.BLACK,
):
    if config is None:
        config = OracleConfig(board_size=9)
    state = new_game(config)
    board = Board.from_points(config.board_size, black=black, white=white)
    action_count = len(board.stones)
    history = (Occupancy.empty(),) * action_count + (board.occupancy,)
    return replace(
        state,
        board=board,
        actor=actor,
        atomic_action_count=action_count,
        psk_history=history,
        revision=action_count,
        log_position=action_count,
    )


def accept(state, actor: Color, envelope: dict[str, object]):
    transition = apply_action(state, actor, envelope)
    if not transition.accepted:
        raise AssertionError(f"unexpected rejection: {transition.rejection_code}")
    return transition


def enter_empty_ledger_ordinary(config: OracleConfig | None = None):
    if config is None:
        config = OracleConfig(board_size=9)
    state = new_game(config)
    state = accept(state, Color.BLACK, action(ActionKind.PASS)).state
    return accept(state, Color.WHITE, action(ActionKind.PASS))


class InitializationAndActionV1Tests(unittest.TestCase):
    def test_initialization_thresholds_psk_and_per_player_quotas(self) -> None:
        expected = {9: 34, 13: 70, 19: 150}
        for size, threshold in expected.items():
            with self.subTest(size=size):
                black = SpecialQuotas(immortal=0, double_start=1, eightway=0)
                white = SpecialQuotas(immortal=1, double_start=0, eightway=1)
                config = OracleConfig(
                    board_size=size,
                    quotas=PlayerQuotas(black=black, white=white),
                )
                state = new_game(config)
                self.assertEqual(threshold, settlement_threshold(size))
                self.assertEqual(threshold, state.threshold)
                self.assertEqual(Phase.COLLAPSE_PLAY, state.phase)
                self.assertEqual(Color.BLACK, state.actor)
                self.assertEqual(0, state.atomic_action_count)
                self.assertEqual(0, state.consecutive_passes)
                self.assertEqual(config.quotas, state.initial_quotas)
                self.assertEqual(config.quotas, state.remaining_quotas)
                self.assertEqual(PlayerQuotas.zero(), state.used_quotas)
                self.assertEqual(PlayerQuotas.zero(), state.expired_quotas)
                self.assertEqual((), state.ledger)
                self.assertIsNone(state.pending_double)
                self.assertEqual(0, state.settled_ledger_count)
                self.assertEqual(0, state.stable_terminal_event_count)
                self.assertEqual(0, state.revision)
                self.assertEqual(0, state.log_position)
                self.assertEqual((Occupancy.empty(),), state.psk_history)
                self.assertEqual(Occupancy.empty(), state.board.occupancy)

    def test_configuration_is_frozen_and_rejects_out_of_slice_values(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        with self.assertRaises(FrozenInstanceError):
            state.atomic_action_count = 1  # type: ignore[misc]
        for size in (8, 10, 20, True):
            with self.subTest(size=size), self.assertRaises(ValueError):
                OracleConfig(board_size=size)  # type: ignore[arg-type]
        for value in (-1, True):
            with self.subTest(quota=value), self.assertRaises(ValueError):
                SpecialQuotas(immortal=value)  # type: ignore[arg-type]
        self.assertEqual(2, SpecialQuotas(immortal=2).immortal)

    def test_all_action_v1_ids_decode_for_each_supported_board(self) -> None:
        for size in (9, 13, 19):
            offset = (19 - size) // 2
            for action_id in range(1445):
                if action_id == 1444:
                    kind = ActionKind.PASS
                else:
                    kind = (
                        ActionKind.NORMAL,
                        ActionKind.IMMORTAL,
                        ActionKind.DOUBLE_START,
                        ActionKind.EIGHTWAY,
                    )[action_id // 361]
                decoded = decode_action_v1(
                    {
                        "schemaVersion": "action-v1",
                        "actionId": action_id,
                        "kind": kind.value,
                    },
                    size,
                )
                self.assertEqual(kind, decoded.kind)
                if kind is ActionKind.PASS:
                    self.assertIsNone(decoded.canvas_point)
                    self.assertIsNone(decoded.board_point)
                    self.assertIsNone(decoded.board_index)
                    continue
                canvas_index = action_id % 361
                canvas = Point(canvas_index % 19, canvas_index // 19)
                self.assertEqual(canvas, decoded.canvas_point)
                inside = (
                    offset <= canvas.x < offset + size
                    and offset <= canvas.y < offset + size
                )
                if inside:
                    local = Point(canvas.x - offset, canvas.y - offset)
                    self.assertEqual(local, decoded.board_point)
                    self.assertEqual(size * local.y + local.x, decoded.board_index)
                else:
                    self.assertIsNone(decoded.board_point)
                    self.assertIsNone(decoded.board_index)

    def test_strict_action_v1_decoding_and_centered_coordinates(self) -> None:
        decoded = decode_action_v1(
            action(ActionKind.NORMAL, size=9, x=0, y=0), 9
        )
        self.assertEqual(ActionKind.NORMAL, decoded.kind)
        self.assertEqual(Point(5, 5), decoded.canvas_point)
        self.assertEqual(Point(0, 0), decoded.board_point)
        self.assertEqual(0, decoded.board_index)

        family_boundaries = (
            (0, "NORMAL"),
            (360, "NORMAL"),
            (361, "IMMORTAL"),
            (721, "IMMORTAL"),
            (722, "DOUBLE_START"),
            (1082, "DOUBLE_START"),
            (1083, "EIGHTWAY"),
            (1443, "EIGHTWAY"),
            (1444, "PASS"),
        )
        for action_id, kind in family_boundaries:
            with self.subTest(action_id=action_id):
                decoded = decode_action_v1(
                    {
                        "schemaVersion": "action-v1",
                        "actionId": action_id,
                        "kind": kind,
                    },
                    19,
                )
                self.assertEqual(kind, decoded.kind.value)

        malformed = (
            {"schemaVersion": "action-v1", "actionId": 1444},
            {
                "schemaVersion": "action-v1",
                "actionId": 1444,
                "kind": "PASS",
                "x": 0,
            },
            {"schemaVersion": "action-v2", "actionId": 1444, "kind": "PASS"},
            {"schemaVersion": 1, "actionId": 1444, "kind": "PASS"},
            {"schemaVersion": "action-v1", "actionId": True, "kind": "NORMAL"},
            {"schemaVersion": "action-v1", "actionId": 1445, "kind": "PASS"},
            {"schemaVersion": "action-v1", "actionId": 0, "kind": "IMMORTAL"},
            {"schemaVersion": "action-v1", "actionId": 1444, "kind": 5},
        )
        for envelope in malformed:
            with self.subTest(envelope=envelope), self.assertRaises(
                ActionV1DecodeError
            ):
                decode_action_v1(envelope, 9)
        with self.assertRaises(ActionV1DecodeError):
            decode_action_v1(["action-v1", 1444, "PASS"], 9)  # type: ignore[arg-type]


class PlacementAndPSKTests(unittest.TestCase):
    def test_full_scan_and_simultaneous_opponent_capture(self) -> None:
        size = 9
        center = point(size, 2, 2)
        upper = point(size, 2, 1)
        lower = point(size, 2, 3)
        state = positioned_state(
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
        white_groups = [
            group
            for group in scan_n4_groups(state.board)
            if group.color is Color.WHITE
        ]
        self.assertEqual(2, len(white_groups))
        self.assertEqual({(center,)}, {group.liberties for group in white_groups})

        transition = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=2, y=2),
        )
        self.assertEqual((upper, lower), transition.atomic_event.captured.white)
        self.assertEqual((), transition.atomic_event.captured.black)
        self.assertEqual((), transition.state.board.occupancy.white)
        self.assertIn(center, transition.state.board.occupancy.black)
        self.assertEqual(state.atomic_action_count + 1, transition.state.atomic_action_count)
        self.assertEqual(state.psk_history + (transition.state.board.occupancy,), transition.state.psk_history)

    def test_suicide_rejects_without_side_effects(self) -> None:
        size = 9
        state = positioned_state(
            white=(
                point(size, 2, 1),
                point(size, 1, 2),
                point(size, 3, 2),
                point(size, 2, 3),
            )
        )
        transition = apply_action(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=2, y=2),
        )
        self.assertFalse(transition.accepted)
        self.assertEqual(RejectionCode.SUICIDE, transition.rejection_code)
        self.assertIs(state, transition.state)
        self.assertIsNone(transition.atomic_event)

    def test_occupied_and_off_footprint_rejections_are_atomic(self) -> None:
        size = 9
        occupied = point(size, 4, 4)
        state = positioned_state(black=(occupied,))
        before = state
        transition = apply_action(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        )
        self.assertEqual(RejectionCode.POINT_OCCUPIED, transition.rejection_code)
        self.assertIs(before, transition.state)

        off_board = apply_action(state, Color.WHITE, off_footprint_action())
        self.assertEqual(RejectionCode.POINT_OFF_BOARD, off_board.rejection_code)
        self.assertIs(before, off_board.state)

    def test_capture_repetition_is_rejected_by_occupancy_only_psk(self) -> None:
        size = 9
        center = point(size, 2, 2)
        state = positioned_state(
            black=(
                point(size, 2, 0),
                point(size, 1, 1),
                point(size, 3, 1),
                point(size, 1, 3),
                point(size, 3, 3),
                point(size, 2, 4),
            ),
            white=(point(size, 2, 1), point(size, 2, 3)),
        )
        trial = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=2, y=2),
        )
        repeated = trial.state.board.occupancy
        state_with_prior_repeat = replace(
            state,
            psk_history=state.psk_history[:-2]
            + (repeated, state.board.occupancy),
        )
        transition = apply_action(
            state_with_prior_repeat,
            Color.BLACK,
            action(ActionKind.NORMAL, x=2, y=2),
        )
        self.assertEqual(RejectionCode.POSITIONAL_SUPERKO, transition.rejection_code)
        self.assertIs(state_with_prior_repeat, transition.state)
        self.assertIn(center, repeated.black)
        self.assertEqual(state.board, transition.state.board)
        self.assertEqual(state_with_prior_repeat.psk_history, transition.state.psk_history)

    def test_pruned_ordered_psk_history_is_rejected_at_state_construction(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        ).state
        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        self.assertEqual(2, state.atomic_action_count)
        self.assertEqual(3, len(state.psk_history))
        with self.assertRaisesRegex(ValueError, "PSK history length"):
            replace(
                state,
                psk_history=(Occupancy.empty(), state.board.occupancy),
            )

    def test_pass_is_psk_exempt_and_preserves_ordered_duplicates(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        first = accept(state, Color.BLACK, action(ActionKind.PASS))
        self.assertEqual(
            (Occupancy.empty(), Occupancy.empty()), first.state.psk_history
        )
        self.assertEqual(1, first.atomic_event.psk_history_index)

        second = accept(first.state, Color.WHITE, action(ActionKind.PASS))
        self.assertEqual(
            (Occupancy.empty(), Occupancy.empty(), Occupancy.empty()),
            second.state.psk_history,
        )
        self.assertEqual(2, second.atomic_event.psk_history_index)
        self.assertEqual(Phase.ORDINARY_PLAY, second.state.phase)


class SettlementAndScoringTests(unittest.TestCase):
    def test_pre_threshold_two_pass_empty_ledger_settlement(self) -> None:
        black = SpecialQuotas(immortal=1, double_start=0, eightway=1)
        white = SpecialQuotas(immortal=0, double_start=1, eightway=0)
        config = OracleConfig(
            board_size=9,
            quotas=PlayerQuotas(black=black, white=white),
        )
        transition = enter_empty_ledger_ordinary(config)
        state = transition.state
        self.assertEqual(
            SettlementReason.PRE_THRESHOLD_TWO_PASSES,
            transition.settlement.reason,
        )
        self.assertEqual(0, transition.settlement.ledger_entry_count)
        self.assertEqual(0, transition.settlement.psk_appends)
        self.assertEqual(Phase.ORDINARY_PLAY, state.phase)
        self.assertEqual(Color.BLACK, state.actor)
        self.assertEqual(2, state.atomic_action_count)
        self.assertEqual(0, state.consecutive_passes)
        self.assertEqual(PlayerQuotas.zero(), state.remaining_quotas)
        self.assertEqual(config.quotas, state.expired_quotas)
        self.assertEqual(3, len(state.psk_history))

    def test_threshold_wins_when_action_t_is_second_pass(self) -> None:
        state = new_game(
            OracleConfig(board_size=9, quotas=PlayerQuotas.zero())
        )
        for board_point in range(15):
            x = board_point % 9
            y = board_point // 9
            state = accept(
                state,
                Color.BLACK,
                action(ActionKind.NORMAL, x=x, y=y),
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
        first_pass = accept(state, Color.BLACK, action(ActionKind.PASS))
        self.assertEqual(33, first_pass.state.atomic_action_count)
        self.assertEqual(1, first_pass.state.consecutive_passes)

        double_at_t = apply_action(
            first_pass.state,
            Color.WHITE,
            action(ActionKind.DOUBLE_START, x=7, y=8),
        )
        self.assertEqual(RejectionCode.DOUBLE_THRESHOLD, double_at_t.rejection_code)
        self.assertIs(first_pass.state, double_at_t.state)

        final = accept(first_pass.state, Color.WHITE, action(ActionKind.PASS))
        self.assertEqual(SettlementReason.THRESHOLD, final.settlement.reason)
        self.assertEqual(34, final.state.atomic_action_count)
        self.assertEqual(Phase.ORDINARY_PLAY, final.state.phase)
        self.assertEqual(0, final.state.consecutive_passes)
        self.assertEqual(35, len(final.state.psk_history))
        self.assertEqual(0, final.settlement.psk_appends)

    def test_ordinary_two_pass_scoring_and_terminal_psk_append(self) -> None:
        ordinary = enter_empty_ledger_ordinary().state
        placed = accept(
            ordinary,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        )
        first_pass = accept(placed.state, Color.WHITE, action(ActionKind.PASS))
        final = accept(first_pass.state, Color.BLACK, action(ActionKind.PASS))

        self.assertEqual(Phase.TERMINAL, final.state.phase)
        self.assertIsNone(final.state.actor)
        self.assertIsNotNone(final.terminal_event)
        score = final.state.terminal.score
        self.assertEqual(1, score.black_stones)
        self.assertEqual(80, score.black_empty_area)
        self.assertEqual(0, score.white_stones)
        self.assertEqual(0, score.white_empty_area)
        self.assertEqual(162, score.black_score_numerator)
        self.assertEqual(15, score.white_score_numerator)
        self.assertEqual(147, score.margin_numerator)
        self.assertEqual(2, score.denominator)
        self.assertEqual(Color.BLACK, score.winner)
        self.assertEqual(Color.BLACK, final.terminal_event.winner)
        self.assertEqual(Color.WHITE, final.terminal_event.loser)

        self.assertEqual(
            len(final.state.psk_history) - 2,
            final.atomic_event.psk_history_index,
        )
        self.assertEqual(
            len(final.state.psk_history) - 1,
            final.terminal_event.psk_history_index,
        )
        self.assertEqual(
            final.state.psk_history[-2], final.state.psk_history[-1]
        )
        self.assertEqual(5, final.state.atomic_action_count)

    def test_chinese_area_neutral_region_and_komi_are_exact(self) -> None:
        board = Board.from_points(9, black=(0,), white=(80,))
        score = score_chinese_area(board)
        self.assertEqual(1, score.black_stones)
        self.assertEqual(1, score.white_stones)
        self.assertEqual(0, score.black_empty_area)
        self.assertEqual(0, score.white_empty_area)
        self.assertEqual(2, score.black_score_numerator)
        self.assertEqual(17, score.white_score_numerator)
        self.assertEqual(15, score.margin_numerator)
        self.assertEqual(Color.WHITE, score.winner)


class PrecedenceAndSpecialSliceTests(unittest.TestCase):
    def test_frozen_rejection_precedence_before_phase_and_actor(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        off_board_wrong_actor = apply_action(
            state, Color.WHITE, off_footprint_action()
        )
        self.assertEqual(
            RejectionCode.POINT_OFF_BOARD,
            off_board_wrong_actor.rejection_code,
        )

        wrong_actor = apply_action(
            state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=0, y=0),
        )
        self.assertEqual(RejectionCode.WRONG_ACTOR, wrong_actor.rejection_code)

        ordinary = enter_empty_ledger_ordinary().state
        off_board_ordinary_special = apply_action(
            ordinary,
            Color.WHITE,
            off_footprint_action(ActionKind.IMMORTAL),
        )
        self.assertEqual(
            RejectionCode.POINT_OFF_BOARD,
            off_board_ordinary_special.rejection_code,
        )
        invalid_phase_before_actor = apply_action(
            ordinary,
            Color.WHITE,
            action(ActionKind.IMMORTAL, x=0, y=0),
        )
        self.assertEqual(
            RejectionCode.INVALID_PHASE,
            invalid_phase_before_actor.rejection_code,
        )

    def test_terminal_precedence_follows_point_off_board(self) -> None:
        ordinary = enter_empty_ledger_ordinary().state
        first = accept(ordinary, Color.BLACK, action(ActionKind.PASS))
        final = accept(first.state, Color.WHITE, action(ActionKind.PASS))
        terminal = final.state

        off_board = apply_action(terminal, Color.BLACK, off_footprint_action())
        self.assertEqual(RejectionCode.POINT_OFF_BOARD, off_board.rejection_code)
        in_board = apply_action(
            terminal,
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=0),
        )
        self.assertEqual(RejectionCode.TERMINAL_STATE, in_board.rejection_code)
        self.assertIs(terminal, in_board.state)

    def test_zero_quota_specials_reject_quota_exhausted(self) -> None:
        config = OracleConfig(board_size=9, quotas=PlayerQuotas.zero())
        state = new_game(config)
        wrong_actor_before_quota = apply_action(
            state,
            Color.WHITE,
            action(ActionKind.IMMORTAL, x=0, y=0),
        )
        self.assertEqual(
            RejectionCode.WRONG_ACTOR,
            wrong_actor_before_quota.rejection_code,
        )
        for kind, x in (
            (ActionKind.IMMORTAL, 0),
            (ActionKind.DOUBLE_START, 1),
            (ActionKind.EIGHTWAY, 2),
        ):
            with self.subTest(kind=kind):
                transition = apply_action(
                    state,
                    Color.BLACK,
                    action(kind, x=x, y=0),
                )
                self.assertEqual(
                    RejectionCode.QUOTA_EXHAUSTED,
                    transition.rejection_code,
                )
                self.assertIs(state, transition.state)

        occupied = positioned_state(
            black=(point(9, 4, 4),),
            config=config,
        )
        quota_before_occupied = apply_action(
            occupied,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=4, y=4),
        )
        self.assertEqual(
            RejectionCode.QUOTA_EXHAUSTED,
            quota_before_occupied.rejection_code,
        )

    def test_nonzero_double_start_reports_deterministic_suicide(self) -> None:
        size = 9
        state = positioned_state(
            white=(
                point(size, 2, 1),
                point(size, 1, 2),
                point(size, 3, 2),
                point(size, 2, 3),
            )
        )
        transition = apply_action(
            state,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=2, y=2),
        )
        self.assertEqual(RejectionCode.SUICIDE, transition.rejection_code)
        self.assertIs(state, transition.state)

    def test_nonzero_double_start_reports_deterministic_psk(self) -> None:
        size = 9
        state = positioned_state(
            black=(
                point(size, 2, 0),
                point(size, 1, 1),
                point(size, 3, 1),
                point(size, 1, 3),
                point(size, 3, 3),
                point(size, 2, 4),
            ),
            white=(point(size, 2, 1), point(size, 2, 3)),
        )
        normal_result = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=2, y=2),
        ).state.board.occupancy
        state_with_prior_repeat = replace(
            state,
            psk_history=state.psk_history[:-2]
            + (normal_result, state.board.occupancy),
        )
        transition = apply_action(
            state_with_prior_repeat,
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=2, y=2),
        )
        self.assertEqual(
            RejectionCode.POSITIONAL_SUPERKO,
            transition.rejection_code,
        )
        self.assertIs(state_with_prior_repeat, transition.state)

    def test_nonzero_potentially_legal_specials_are_explicitly_unsupported(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        for kind, x in (
            (ActionKind.IMMORTAL, 0),
            (ActionKind.DOUBLE_START, 1),
            (ActionKind.EIGHTWAY, 2),
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(UnsupportedSliceAction) as caught:
                    apply_action(
                        state,
                        Color.BLACK,
                        action(kind, x=x, y=0),
                    )
                self.assertEqual(kind, caught.exception.action.kind)
                self.assertEqual(Color.BLACK, caught.exception.actor)
                self.assertEqual(0, state.atomic_action_count)
                self.assertEqual((Occupancy.empty(),), state.psk_history)

    def test_per_player_nonzero_quota_and_ordinary_special_phase(self) -> None:
        config = OracleConfig(
            board_size=9,
            quotas=PlayerQuotas(
                black=SpecialQuotas.zero(),
                white=SpecialQuotas(immortal=1, double_start=0, eightway=0),
            ),
        )
        state = new_game(config)
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=4, y=4),
        ).state
        with self.assertRaises(UnsupportedSliceAction):
            apply_action(
                state,
                Color.WHITE,
                action(ActionKind.IMMORTAL, x=0, y=0),
            )

        ordinary = enter_empty_ledger_ordinary(config).state
        for kind, x in (
            (ActionKind.IMMORTAL, 0),
            (ActionKind.DOUBLE_START, 1),
            (ActionKind.EIGHTWAY, 2),
        ):
            with self.subTest(kind=kind):
                transition = apply_action(
                    ordinary,
                    ordinary.actor,
                    action(kind, x=x, y=0),
                )
                self.assertEqual(
                    RejectionCode.INVALID_PHASE,
                    transition.rejection_code,
                )
                self.assertIs(ordinary, transition.state)


if __name__ == "__main__":
    unittest.main()
