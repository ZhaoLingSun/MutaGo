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
    PendingDouble,
    Phase,
    PlayerQuotas,
    SettlementState,
    SpecialEvent,
    SpecialQuotas,
    Stone,
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
    offset = 5
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


def immortal_state(*, x: int = 4, y: int = 4):
    return accept(
        new_game(OracleConfig(board_size=9)),
        Color.BLACK,
        action(ActionKind.IMMORTAL, x=x, y=y),
    ).state


def fabricate_pending_captured_immortal_state():
    config = OracleConfig(
        board_size=9,
        quotas=PlayerQuotas(
            black=SpecialQuotas(immortal=1, double_start=0, eightway=0),
            white=SpecialQuotas.zero(),
        ),
    )
    initial = new_game(config)
    source_occupancy = Occupancy(black=(point(9, 4, 4),))
    event = SpecialEvent(
        event_id="special-1",
        logical_order=0,
        owner=Color.BLACK,
        kind=ActionKind.IMMORTAL,
        source_point=point(9, 4, 4),
        source_stone_id="stone-1",
        ability_state=AbilityState.INACTIVE,
        stone_state=StoneState.CAPTURED,
        settlement_state=SettlementState.PENDING,
        tombstone=True,
    )
    return replace(
        initial,
        board=Board.empty(9),
        actor=Color.WHITE,
        atomic_action_count=3,
        consecutive_passes=1,
        remaining_quotas=PlayerQuotas.zero(),
        used_quotas=PlayerQuotas(
            black=SpecialQuotas(immortal=1, double_start=0, eightway=0),
            white=SpecialQuotas.zero(),
        ),
        ledger=(event,),
        psk_history=(
            Occupancy.empty(),
            source_occupancy,
            source_occupancy,
            Occupancy.empty(),
        ),
        revision=3,
        log_position=3,
    )


class ImmortalExactLifecycleTests(unittest.TestCase):
    def test_pending_captured_immortal_state_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "pending Immortal must be armed, on board, and non-tombstone",
        ):
            fabricate_pending_captured_immortal_state()

    def test_invalid_live_captured_and_settled_lifecycles_are_rejected(self) -> None:
        live = immortal_state()
        event = live.ledger[0]
        invalid_live_events = (
            replace(event, ability_state=AbilityState.CONSUMED),
            replace(event, ability_state=AbilityState.INACTIVE),
            replace(event, tombstone=True),
            replace(event, stone_state=StoneState.CAPTURED, tombstone=False),
        )
        for invalid in invalid_live_events:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError,
                "Immortal",
            ):
                replace(live, ledger=(invalid,))

        passed = accept(live, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept(passed, Color.BLACK, action(ActionKind.PASS)).state
        with self.assertRaisesRegex(ValueError, "settled Immortal"):
            replace(
                settled,
                ledger=(
                    replace(
                        settled.ledger[0],
                        ability_state=AbilityState.ARMED,
                    ),
                ),
            )

    def test_special_source_board_and_history_linkage_is_exact(self) -> None:
        live = immortal_state()
        passed = accept(live, Color.WHITE, action(ActionKind.PASS)).state
        with self.assertRaisesRegex(ValueError, "on-board special event source"):
            replace(
                passed,
                board=Board.empty(9),
                psk_history=passed.psk_history[:-1] + (Occupancy.empty(),),
            )

        state = new_game(OracleConfig(board_size=9))
        state = accept(
            state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=0),
        ).state
        state = accept(
            state,
            Color.WHITE,
            action(ActionKind.IMMORTAL, x=1, y=0),
        ).state
        with self.assertRaisesRegex(ValueError, "occupied before its action"):
            replace(
                state,
                ledger=(replace(state.ledger[0], source_point=point(9, 0, 0)),),
            )

        with self.assertRaisesRegex(ValueError, "source identity|source linkage"):
            replace(
                live,
                ledger=(replace(live.ledger[0], source_point=0),),
            )

    def test_settled_entries_are_an_exact_suffix_and_count_matches(self) -> None:
        state = immortal_state(x=0, y=0)
        state = accept(
            state,
            Color.WHITE,
            action(ActionKind.IMMORTAL, x=8, y=8),
        ).state
        invalid_first = replace(
            state.ledger[0],
            ability_state=AbilityState.INACTIVE,
            settlement_state=SettlementState.SETTLED,
            tombstone=True,
        )
        with self.assertRaisesRegex(ValueError, "settled ledger entries.*suffix"):
            replace(
                state,
                ledger=(invalid_first, state.ledger[1]),
                settled_ledger_count=1,
            )

        state = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        settled = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        self.assertEqual(2, settled.settled_ledger_count)
        with self.assertRaisesRegex(ValueError, "settled_ledger_count"):
            replace(settled, settled_ledger_count=1)

    def test_consecutive_immortals_are_valid_but_double_requires_continuation(self) -> None:
        state = immortal_state(x=0, y=0)
        consecutive = accept(
            state,
            Color.WHITE,
            action(ActionKind.IMMORTAL, x=8, y=8),
        ).state
        self.assertEqual((0, 1), tuple(event.logical_order for event in consecutive.ledger))

        first_stone = consecutive.board.stone_at(0)
        if first_stone is None:
            raise AssertionError("expected first source")
        fabricated_board = Board.from_stones(
            9,
            (
                replace(first_stone, origin_kind=ActionKind.DOUBLE_START),
                *(stone for stone in consecutive.board.stones if stone.point != 0),
            ),
        )
        fabricated_first = replace(
            consecutive.ledger[0],
            kind=ActionKind.DOUBLE_START,
            ability_state=AbilityState.CONSUMED,
            tombstone=True,
        )
        with self.assertRaisesRegex(ValueError, "intervening continuation"):
            replace(
                consecutive,
                board=fabricated_board,
                ledger=(fabricated_first, consecutive.ledger[1]),
            )

    def test_used_quota_and_eightway_exclusion_are_exact(self) -> None:
        live = immortal_state()
        with self.assertRaisesRegex(ValueError, "Immortal quotas"):
            replace(
                live,
                remaining_quotas=live.initial_quotas,
                used_quotas=PlayerQuotas.zero(),
            )

        source = live.board.stones[0]
        eightway_board = Board.from_stones(
            9,
            (replace(source, origin_kind=ActionKind.EIGHTWAY),),
        )
        with self.assertRaisesRegex(ValueError, "Increment 2 board stones"):
            replace(live, board=eightway_board)

    def test_raw_string_kinds_and_impossible_double_steps_are_rejected(self) -> None:
        live = immortal_state()
        with self.assertRaisesRegex(TypeError, "kind must be ActionKind"):
            replace(live, ledger=(replace(live.ledger[0], kind="IMMORTAL"),))  # type: ignore[arg-type]

        state = accept(live, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept(state, Color.BLACK, action(ActionKind.PASS))
        immortal_step = settled.settlement.steps[0]
        with self.assertRaisesRegex(TypeError, "kind must be ActionKind"):
            replace(immortal_step, kind="IMMORTAL")  # type: ignore[arg-type]

        double = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.DOUBLE_START, x=0, y=0),
        ).state
        double = accept(double, Color.BLACK, action(ActionKind.PASS)).state
        double_step = accept(
            double,
            Color.WHITE,
            action(ActionKind.PASS),
        ).settlement.steps[0]
        with self.assertRaisesRegex(ValueError, "Double settlement steps"):
            replace(
                double_step,
                no_op=False,
                removal_batches=(Occupancy(black=(0,)),),
            )

    def test_settlement_trace_is_bound_to_the_committed_state(self) -> None:
        empty = new_game(OracleConfig(board_size=9))
        empty = accept(empty, Color.BLACK, action(ActionKind.PASS)).state
        empty_settled = accept(empty, Color.WHITE, action(ActionKind.PASS))
        with self.assertRaisesRegex(ValueError, "control state"):
            replace(empty_settled, settlement=None)

        state = immortal_state()
        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        settled = accept(state, Color.BLACK, action(ActionKind.PASS))
        if settled.settlement is None:
            raise AssertionError("expected Immortal settlement trace")

        with self.assertRaisesRegex(ValueError, "complete settlement trace"):
            replace(settled, settlement=None)
        with self.assertRaisesRegex(ValueError, "log delta"):
            replace(
                settled,
                settlement=replace(
                    settled.settlement,
                    ledger_entry_count=0,
                    psk_appends=0,
                    steps=(),
                ),
            )

        false_step = replace(
            settled.settlement.steps[0],
            ability_deactivated=False,
            no_op=True,
        )
        with self.assertRaisesRegex(ValueError, "deterministic closure"):
            replace(
                settled,
                settlement=replace(settled.settlement, steps=(false_step,)),
            )

        false_step = replace(
            settled.settlement.steps[0],
            stable_occupancy=Occupancy.empty(),
            stable_stones=(),
        )
        with self.assertRaisesRegex(ValueError, "deterministic closure"):
            replace(
                settled,
                settlement=replace(settled.settlement, steps=(false_step,)),
            )

    def test_atomic_event_snapshot_relations_are_exact(self) -> None:
        placed = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=0),
        )
        event = placed.atomic_event
        if event.placed_stone is None:
            raise AssertionError("expected placed source")

        with self.assertRaises((TypeError, ValueError)):
            replace(event.action, kind="NORMAL")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "schema_version"):
            replace(event.action, schema_version="action-v2")
        with self.assertRaisesRegex(ValueError, "canvas point"):
            replace(
                event.action,
                canvas_point=replace(
                    event.action.canvas_point,
                    x=event.action.canvas_point.x + 1,
                ),
            )
        with self.assertRaisesRegex(ValueError, "canvas point"):
            replace(event.action, action_id=event.action.action_id + 1)
        with self.assertRaisesRegex(ValueError, "board point and index"):
            replace(event.action, board_index=event.action.board_index + 1)

        cross_footprint_action = replace(
            event.action,
            action_id=0,
            canvas_point=replace(event.action.canvas_point, x=0, y=0),
            board_point=replace(event.action.board_point, x=0, y=0),
            board_index=0,
        )
        cross_footprint_event = replace(event, action=cross_footprint_action)
        with self.assertRaisesRegex(ValueError, "selected board-size"):
            replace(
                placed,
                action=cross_footprint_action,
                atomic_event=cross_footprint_event,
            )
        with self.assertRaisesRegex(ValueError, "match its atomic event"):
            replace(placed, candidate_actor=Color.WHITE)
        with self.assertRaisesRegex(ValueError, "control state"):
            replace(placed, state=replace(placed.state, actor=Color.BLACK))
        with self.assertRaisesRegex(ValueError, "control state"):
            replace(placed, state=replace(placed.state, consecutive_passes=1))

        with self.assertRaisesRegex(ValueError, "only opponent stones"):
            same_color_capture = Stone(1, Color.BLACK, 1, ActionKind.NORMAL)
            replace(
                event,
                captured=Occupancy(black=(1,)),
                captured_stones=(same_color_capture,),
            )

        capture_state = new_game(OracleConfig(board_size=9))
        capture_state = accept(
            capture_state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=0),
        ).state
        capture_state = accept(
            capture_state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=1, y=0),
        ).state
        capture_state = accept(
            capture_state,
            Color.BLACK,
            action(ActionKind.NORMAL, x=8, y=8),
        ).state
        captured = accept(
            capture_state,
            Color.WHITE,
            action(ActionKind.NORMAL, x=0, y=1),
        )
        moved_capture = replace(captured.atomic_event.captured_stones[0], point=2)
        false_capture_event = replace(
            captured.atomic_event,
            captured=Occupancy(black=(2,)),
            captured_stones=(moved_capture,),
        )
        with self.assertRaisesRegex(ValueError, "immediately prior occupancy"):
            replace(captured, atomic_event=false_capture_event)

        malformed = (
            {"placed_stone": replace(event.placed_stone, color=Color.WHITE)},
            {"placed_stone": replace(event.placed_stone, origin_action_number=2)},
            {"psk_history_index": event.psk_history_index + 1},
        )
        for changes in malformed:
            with self.subTest(changes=changes), self.assertRaises((TypeError, ValueError)):
                replace(event, **changes)

        passed = accept(
            placed.state,
            Color.WHITE,
            action(ActionKind.PASS),
        ).atomic_event
        with self.assertRaisesRegex(ValueError, "decoded PASS"):
            replace(passed.action, board_index=0)
        with self.assertRaisesRegex(ValueError, "PASS events"):
            replace(passed, placed_stone=event.placed_stone)

    def test_terminal_results_and_event_indices_are_exact(self) -> None:
        state = new_game(OracleConfig(board_size=9))
        state = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        state = accept(state, Color.WHITE, action(ActionKind.PASS)).state
        state = accept(state, Color.BLACK, action(ActionKind.PASS)).state
        terminal = accept(state, Color.WHITE, action(ActionKind.PASS))
        if terminal.state.terminal is None or terminal.terminal_event is None:
            raise AssertionError("expected scoring terminal")
        score = terminal.state.terminal.score

        with self.assertRaises(ValueError):
            replace(score, black_stones=True)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "cannot exceed the canvas"):
            replace(
                score,
                black_stones=361,
                black_empty_area=361,
                black_score_numerator=1444,
                margin_numerator=1429,
                winner=Color.BLACK,
            )
        with self.assertRaisesRegex(ValueError, "score winner"):
            replace(score, winner=score.winner.opponent())
        with self.assertRaisesRegex(ValueError, "terminal winner"):
            replace(
                terminal.state.terminal,
                winner=score.winner.opponent(),
                loser=score.winner,
            )
        wrong_score = replace(
            score,
            black_stones=1,
            black_score_numerator=2,
            margin_numerator=13,
        )
        with self.assertRaisesRegex(ValueError, "stable board"):
            replace(
                terminal.state,
                terminal=replace(terminal.state.terminal, score=wrong_score),
            )
        with self.assertRaisesRegex(ValueError, "stone counts"):
            replace(
                terminal.terminal_event,
                stable_occupancy=Occupancy(black=(0,)),
                stable_stones=(Stone(0, Color.BLACK, 1, ActionKind.NORMAL),),
            )
        with self.assertRaisesRegex(ValueError, "PSK history index"):
            replace(
                terminal.terminal_event,
                psk_history_index=terminal.terminal_event.psk_history_index - 1,
            )
        with self.assertRaisesRegex(ValueError, "exactly two consecutive passes"):
            replace(terminal.state, consecutive_passes=1)
        with self.assertRaisesRegex(ValueError, "second ordinary PASS"):
            replace(
                terminal,
                atomic_event=replace(
                    terminal.atomic_event,
                    psk_history_index=terminal.atomic_event.psk_history_index - 1,
                    log_position=terminal.atomic_event.log_position - 1,
                ),
            )
        with self.assertRaisesRegex(ValueError, "committed terminal state"):
            replace(
                terminal,
                terminal_event=replace(
                    terminal.terminal_event,
                    revision=terminal.terminal_event.revision - 1,
                ),
            )

    def test_zero_liberty_stability_depends_on_armed_ledger_protection(self) -> None:
        size = 9
        state = new_game(OracleConfig(board_size=size))
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
        protected = accept(
            state,
            Color.BLACK,
            action(ActionKind.IMMORTAL, x=4, y=4),
        ).state
        with self.assertRaisesRegex(ValueError, "unprotected zero-liberty"):
            replace(
                protected,
                ledger=(
                    replace(
                        protected.ledger[0],
                        ability_state=AbilityState.INACTIVE,
                        tombstone=True,
                    ),
                ),
            )


class ImmortalSafeIntegerTests(unittest.TestCase):
    def test_source_event_and_pending_counters_reject_bool_and_unsafe_values(self) -> None:
        for value in (False, True, JSON_SAFE_INTEGER_MAX + 1):
            with self.subTest(kind="stone", value=value), self.assertRaises(ValueError):
                Stone(0, Color.BLACK, value, ActionKind.NORMAL)  # type: ignore[arg-type]

        for value in (False, True, JSON_SAFE_INTEGER_MAX, JSON_SAFE_INTEGER_MAX + 1):
            event_id = f"special-{value + 1}" if type(value) is int else "special-1"
            source_id = f"stone-{value + 1}" if type(value) is int else "stone-1"
            with self.subTest(kind="event", value=value), self.assertRaises(ValueError):
                SpecialEvent(
                    event_id=event_id,
                    logical_order=value,  # type: ignore[arg-type]
                    owner=Color.BLACK,
                    kind=ActionKind.IMMORTAL,
                    source_point=0,
                    source_stone_id=source_id,
                    ability_state=AbilityState.ARMED,
                    stone_state=StoneState.ON_BOARD,
                    settlement_state=SettlementState.PENDING,
                    tombstone=False,
                )

        for value in (False, True, JSON_SAFE_INTEGER_MAX + 1):
            with self.subTest(kind="pending", value=value), self.assertRaises(ValueError):
                PendingDouble(
                    owner=Color.BLACK,
                    event_id="special-1",
                    start_action_number=value,  # type: ignore[arg-type]
                )

    def test_state_and_atomic_event_counters_reject_bool_and_unsafe_values(self) -> None:
        state = immortal_state()
        for field_name in (
            "atomic_action_count",
            "settled_ledger_count",
            "stable_terminal_event_count",
            "revision",
            "log_position",
        ):
            for value in (False, True, JSON_SAFE_INTEGER_MAX + 1):
                with self.subTest(field=field_name, value=value), self.assertRaisesRegex(
                    ValueError,
                    field_name,
                ):
                    replace(state, **{field_name: value})

        event = accept(
            new_game(OracleConfig(board_size=9)),
            Color.BLACK,
            action(ActionKind.NORMAL, x=0, y=0),
        ).atomic_event
        for field_name in (
            "action_number",
            "psk_history_index",
            "revision",
            "log_position",
        ):
            for value in (False, True, JSON_SAFE_INTEGER_MAX + 1):
                with self.subTest(field=field_name, value=value), self.assertRaises(
                    ValueError
                ):
                    replace(event, **{field_name: value})

    def test_safe_maximum_source_and_event_order_are_accepted(self) -> None:
        stone = Stone(
            0,
            Color.BLACK,
            JSON_SAFE_INTEGER_MAX,
            ActionKind.IMMORTAL,
            f"special-{JSON_SAFE_INTEGER_MAX}",
        )
        event = SpecialEvent(
            event_id=f"special-{JSON_SAFE_INTEGER_MAX}",
            logical_order=JSON_SAFE_INTEGER_MAX - 1,
            owner=Color.BLACK,
            kind=ActionKind.IMMORTAL,
            source_point=0,
            source_stone_id=f"stone-{JSON_SAFE_INTEGER_MAX}",
            ability_state=AbilityState.ARMED,
            stone_state=StoneState.ON_BOARD,
            settlement_state=SettlementState.PENDING,
            tombstone=False,
        )
        self.assertEqual(JSON_SAFE_INTEGER_MAX, stone.origin_action_number)
        self.assertEqual(JSON_SAFE_INTEGER_MAX - 1, event.logical_order)


if __name__ == "__main__":
    unittest.main()
