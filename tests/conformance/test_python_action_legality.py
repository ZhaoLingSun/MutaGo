from __future__ import annotations

import ast
import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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
    SettlementState,
    SpecialEvent,
    SpecialQuotas,
    Stone,
    StoneState,
    apply_action,
    derive_legal_mask,
    enumerate_action_legality,
    new_game,
)
from mutago.collapse_go import normal_pass_oracle as oracle_module  # noqa: E402

KIND_CODE = {
    ActionKind.NORMAL: 0,
    ActionKind.IMMORTAL: 1,
    ActionKind.DOUBLE_START: 2,
    ActionKind.EIGHTWAY: 3,
}
POINT_KINDS = (
    ActionKind.NORMAL,
    ActionKind.IMMORTAL,
    ActionKind.DOUBLE_START,
    ActionKind.EIGHTWAY,
)
INVERSE_SYMMETRY = (0, 1, 2, 3, 4, 6, 5, 7)


def point(size: int, x: int, y: int) -> int:
    return size * y + x


def points(
    *coordinates: tuple[int, int],
    size: int = 9,
) -> tuple[int, ...]:
    return tuple(sorted(point(size, x, y) for x, y in coordinates))


def envelope_for_id(action_id: int) -> dict[str, object]:
    kind = (
        ActionKind.PASS
        if action_id == PASS_ACTION_ID
        else POINT_KINDS[action_id // 361]
    )
    return {
        "schemaVersion": "action-v1",
        "actionId": action_id,
        "kind": kind.value,
    }


def action(
    kind: ActionKind,
    *,
    size: int = 9,
    x: int | None = None,
    y: int | None = None,
) -> dict[str, object]:
    if kind is ActionKind.PASS:
        return envelope_for_id(PASS_ACTION_ID)
    if x is None or y is None:
        raise ValueError("point action requires board-local coordinates")
    offset = (19 - size) // 2
    return envelope_for_id(
        361 * KIND_CODE[kind] + 19 * (y + offset) + x + offset
    )


def action_id(
    kind: ActionKind,
    *,
    size: int = 9,
    x: int,
    y: int,
) -> int:
    value = action(kind, size=size, x=x, y=y)["actionId"]
    if type(value) is not int:
        raise AssertionError("test action ID must be int")
    return value


def golden_state(
    *,
    black: tuple[int, ...] = (),
    white: tuple[int, ...] = (),
    actor: Color = Color.BLACK,
    phase: Phase = Phase.COLLAPSE_PLAY,
    special_sources: tuple[tuple[int, ActionKind, bool], ...] = (),
    psk_history: tuple[Occupancy, ...] | None = None,
    size: int = 9,
) -> OracleState:
    """Build only the frozen state fields consumed by legality derivation."""

    source_specs = {
        board_point: (kind, active)
        for board_point, kind, active in special_sources
    }
    occupied = set(black) | set(white)
    if (
        set(black).intersection(white)
        or len(source_specs) != len(special_sources)
        or not set(source_specs).issubset(occupied)
    ):
        raise AssertionError("invalid hand-authored golden occupancy")

    stones: list[Stone] = []
    ledger: list[SpecialEvent] = []
    colored_points = sorted(
        (
            *((board_point, Color.BLACK) for board_point in black),
            *((board_point, Color.WHITE) for board_point in white),
        )
    )
    for action_number, (board_point, color) in enumerate(colored_points, start=1):
        kind, active = source_specs.get(board_point, (ActionKind.NORMAL, False))
        stone = Stone(
            point=board_point,
            color=color,
            origin_action_number=action_number,
            origin_kind=kind,
            special_event_id=(
                None if kind is ActionKind.NORMAL else f"special-{action_number}"
            ),
        )
        stones.append(stone)
        if kind is ActionKind.NORMAL:
            continue
        ledger.append(
            SpecialEvent(
                event_id=f"special-{action_number}",
                logical_order=action_number - 1,
                owner=color,
                kind=kind,
                source_point=board_point,
                source_stone_id=stone.source_id,
                ability_state=(
                    AbilityState.ARMED if active else AbilityState.INACTIVE
                ),
                stone_state=StoneState.ON_BOARD,
                settlement_state=(
                    SettlementState.PENDING
                    if active
                    else SettlementState.SETTLED
                ),
                tombstone=not active,
            )
        )

    quotas = SpecialQuotas(immortal=2, double_start=2, eightway=2)
    state = copy.copy(
        new_game(
            OracleConfig(
                board_size=size,
                quotas=PlayerQuotas(black=quotas, white=quotas),
            )
        )
    )
    board = Board.from_stones(size, stones)
    history = psk_history or (Occupancy.empty(), board.occupancy)
    # Avoid OracleState.__post_init__: it calls the oracle group scanner whose
    # answer these independent golden fixtures are intended to challenge.
    for name, value in (
        ("board", board),
        ("actor", actor),
        ("phase", phase),
        ("atomic_action_count", len(stones)),
        ("ledger", tuple(ledger)),
        ("settled_ledger_count", int(phase is Phase.ORDINARY_PLAY) * len(ledger)),
        ("psk_history", history),
    ):
        object.__setattr__(state, name, value)
    return state


def accept(state: OracleState, envelope: dict[str, object]) -> OracleState:
    if state.actor is None:
        raise AssertionError("cannot play from a terminal state")
    transition = apply_action(state, state.actor, envelope)
    if not transition.accepted:
        raise AssertionError(f"unexpected rejection: {transition.rejection_code}")
    return transition.state


def enter_ordinary(size: int = 9) -> OracleState:
    state = new_game(OracleConfig(board_size=size))
    state = accept(state, action(ActionKind.PASS, size=size))
    return accept(state, action(ActionKind.PASS, size=size))


def enter_terminal(size: int = 9) -> OracleState:
    state = enter_ordinary(size)
    state = accept(state, action(ActionKind.PASS, size=size))
    return accept(state, action(ActionKind.PASS, size=size))


def settled_surviving_sources_state() -> OracleState:
    state = new_game(OracleConfig(board_size=9))
    state = accept(state, action(ActionKind.IMMORTAL, x=0, y=0))
    state = accept(state, action(ActionKind.EIGHTWAY, x=8, y=8))
    state = accept(state, action(ActionKind.PASS))
    state = accept(state, action(ActionKind.PASS))
    if state.phase is not Phase.ORDINARY_PLAY:
        raise AssertionError("special-source checkpoint must be post-settlement")
    if len(state.board.stones) != 2:
        raise AssertionError("settled special sources must survive on board")
    return state


def pending_double_state() -> OracleState:
    state = new_game(OracleConfig(board_size=9))
    return accept(state, action(ActionKind.DOUBLE_START, x=4, y=4))


def threshold_minus_two_state(
    quotas: PlayerQuotas | None = None,
) -> OracleState:
    size = 9
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
    state = new_game(
        OracleConfig(
            board_size=size,
            quotas=PlayerQuotas.zero() if quotas is None else quotas,
        )
    )
    for black_point, white_point in zip(black_points, white_points):
        state = accept(
            state,
            action(ActionKind.NORMAL, x=black_point[0], y=black_point[1]),
        )
        state = accept(
            state,
            action(ActionKind.NORMAL, x=white_point[0], y=white_point[1]),
        )
    if state.atomic_action_count != state.threshold - 2:
        raise AssertionError("threshold prefix did not reach A=T-2")
    return state


def threshold_minus_one_state() -> OracleState:
    state = threshold_minus_two_state()
    state = accept(state, action(ActionKind.NORMAL, x=4, y=5))
    if state.atomic_action_count != state.threshold - 1:
        raise AssertionError("threshold prefix did not reach A=T-1")
    return state


def funded_threshold_minus_two_state() -> OracleState:
    return threshold_minus_two_state(
        PlayerQuotas(
            black=SpecialQuotas(immortal=0, double_start=1, eightway=0),
            white=SpecialQuotas.zero(),
        )
    )


def pending_double_before_threshold_state() -> OracleState:
    state = funded_threshold_minus_two_state()
    state = accept(state, action(ActionKind.DOUBLE_START, x=4, y=5))
    if (
        state.atomic_action_count != state.threshold - 1
        or state.pending_double is None
        or state.actor is not Color.BLACK
    ):
        raise AssertionError("funded Double start did not reach pending A=T-1")
    return state


def simultaneous_capture_state() -> OracleState:
    state = new_game(OracleConfig(board_size=9))
    sequence = (
        (2, 0),
        (2, 1),
        (1, 1),
        (2, 3),
        (3, 1),
        (8, 8),
        (1, 3),
        (8, 7),
        (3, 3),
        (7, 8),
        (2, 4),
        (6, 8),
    )
    for x, y in sequence:
        state = accept(state, action(ActionKind.NORMAL, x=x, y=y))
    if state.actor is not Color.BLACK:
        raise AssertionError("capture checkpoint must hand play to Black")
    return state


def mixed_protection_state() -> OracleState:
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
    state = new_game(
        OracleConfig(
            board_size=size,
            quotas=PlayerQuotas(
                black=SpecialQuotas(immortal=2, double_start=1, eightway=1),
                white=SpecialQuotas(),
            ),
        )
    )
    state = accept(
        state,
        action(ActionKind.IMMORTAL, x=immortal[0], y=immortal[1]),
    )
    for index, white_point in enumerate(white_points):
        state = accept(
            state,
            action(ActionKind.NORMAL, x=white_point[0], y=white_point[1]),
        )
        if index < len(black_fillers):
            black_point = black_fillers[index]
            state = accept(
                state,
                action(ActionKind.NORMAL, x=black_point[0], y=black_point[1]),
            )
    if state.actor is not Color.BLACK:
        raise AssertionError("mixed checkpoint must hand play to Black")
    return state


def reversed_eightway_endpoint_state() -> OracleState:
    immortal = (4, 4)
    white_points = tuple(
        sorted(
            {
                (2, 2),
                (2, 3),
                (2, 4),
                (3, 2),
                (3, 4),
                (4, 2),
                (4, 3),
                (4, 5),
                (5, 4),
            }
        )
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
    state = new_game(
        OracleConfig(
            board_size=9,
            quotas=PlayerQuotas(
                black=SpecialQuotas(immortal=2, double_start=1, eightway=1),
                white=SpecialQuotas(),
            ),
        )
    )
    state = accept(
        state,
        action(ActionKind.IMMORTAL, x=immortal[0], y=immortal[1]),
    )
    for index, white_point in enumerate(white_points):
        state = accept(
            state,
            action(ActionKind.NORMAL, x=white_point[0], y=white_point[1]),
        )
        if index < len(black_fillers):
            black_point = black_fillers[index]
            state = accept(
                state,
                action(ActionKind.NORMAL, x=black_point[0], y=black_point[1]),
            )
    if state.actor is not Color.BLACK:
        raise AssertionError("reversed endpoint checkpoint must hand play to Black")
    return state


def captured_eightway_source_state() -> OracleState:
    state = new_game(OracleConfig(board_size=9))
    for action_id_value in (1183, 101, 260, 119, 259):
        state = accept(state, envelope_for_id(action_id_value))
    if state.actor is not Color.WHITE:
        raise AssertionError("captured-anchor checkpoint must hand play to White")
    return state


def n8_suicide_state() -> OracleState:
    ring = tuple(
        (x, y)
        for y in range(3, 6)
        for x in range(3, 6)
        if (x, y) != (4, 4)
    )
    fillers = (
        (0, 0),
        (2, 0),
        (4, 0),
        (6, 0),
        (8, 0),
        (0, 8),
        (2, 8),
        (4, 8),
    )
    state = new_game(OracleConfig(board_size=9))
    for black_point, white_point in zip(fillers, ring):
        state = accept(
            state,
            action(ActionKind.NORMAL, x=black_point[0], y=black_point[1]),
        )
        state = accept(
            state,
            action(ActionKind.NORMAL, x=white_point[0], y=white_point[1]),
        )
    return state


def rich_mixed_state(size: int = 9) -> OracleState:
    center = size // 2
    sequence = (
        (ActionKind.IMMORTAL, center - 1, center - 1),
        (ActionKind.NORMAL, center, center - 1),
        (ActionKind.NORMAL, 0, size - 1),
        (ActionKind.NORMAL, center - 1, center),
        (ActionKind.EIGHTWAY, center, center),
        (ActionKind.NORMAL, center + 1, center),
        (ActionKind.NORMAL, size - 1, size - 1),
        (ActionKind.NORMAL, center, center + 1),
    )
    state = new_game(
        OracleConfig(
            board_size=size,
            quotas=PlayerQuotas(
                black=SpecialQuotas(immortal=2, double_start=1, eightway=2),
                white=SpecialQuotas(),
            ),
        )
    )
    for kind, x, y in sequence:
        state = accept(state, action(kind, size=size, x=x, y=y))
    return state


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


def transform_state(state: OracleState, symmetry: int) -> OracleState:
    size = state.board.size
    return replace(
        state,
        board=Board.from_stones(
            size,
            (
                replace(
                    stone,
                    point=transform_point(size, stone.point, symmetry),
                )
                for stone in state.board.stones
            ),
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


def transform_action_id(action_id_value: int, symmetry: int) -> int:
    if action_id_value == PASS_ACTION_ID:
        return PASS_ACTION_ID
    family = action_id_value // 361
    canvas_point = action_id_value % 361
    x = canvas_point % 19
    y = canvas_point // 19
    if symmetry & 2:
        x = 18 - x
    if symmetry & 1:
        y = 18 - y
    if symmetry & 4:
        x, y = y, x
    return family * 361 + 19 * y + x


class ActionLegalityIndependenceTests(unittest.TestCase):
    def test_ast_imports_only_frozen_data_types_and_stdlib(self) -> None:
        source_path = (
            REPO_ROOT / "python/mutago/collapse_go/action_legality.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        allowed_oracle_names = {
            "CANVAS_SIZE",
            "PASS_ACTION_ID",
            "AbilityState",
            "ActionKind",
            "Color",
            "OracleState",
            "Phase",
            "RejectionCode",
            "SettlementState",
            "StoneState",
        }
        forbidden_helpers = {
            "apply_action",
            "decode_action_v1",
            "scan_mixed_groups",
            "scan_n4_groups",
            "_prepare_placement",
            "_simulate_placement",
            "settlement_threshold",
        }
        allowed_imports = {
            (0, "__future__"): {"annotations"},
            (0, "dataclasses"): {"dataclass"},
            (1, "normal_pass_oracle"): allowed_oracle_names,
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.fail(f"implementation must not use import statements: {node.names!r}")
            elif isinstance(node, ast.ImportFrom):
                key = (node.level, node.module or "")
                self.assertIn(key, allowed_imports)
                self.assertEqual(
                    set(alias.name for alias in node.names),
                    allowed_imports[key],
                )
                self.assertTrue(all(alias.asname is None for alias in node.names))
            elif isinstance(node, ast.Name):
                self.assertNotIn(node.id, forbidden_helpers)
                self.assertNotIn(node.id, {"__import__", "import_module"})
            elif isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, forbidden_helpers)
                self.assertNotIn(node.attr, {"__import__", "import_module"})

    def test_monkeypatched_reducer_and_scanners_are_never_observed(self) -> None:
        state = rich_mixed_state()
        expected = enumerate_action_legality(state)

        def forbidden(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("shared rule helper was called")

        with patch.multiple(
            oracle_module,
            apply_action=forbidden,
            decode_action_v1=forbidden,
            scan_mixed_groups=forbidden,
            scan_n4_groups=forbidden,
            _prepare_placement=forbidden,
            _simulate_placement=forbidden,
            settlement_threshold=forbidden,
        ):
            self.assertEqual(expected, enumerate_action_legality(state))
            self.assertEqual(
                tuple(code is None for code in expected),
                derive_legal_mask(state),
            )


class ActionLegalityExhaustiveEquivalenceTests(unittest.TestCase):
    def assert_all_ids_match_reducer(self, state: OracleState) -> None:
        codes = enumerate_action_legality(state)
        mask = derive_legal_mask(state)
        self.assertIsInstance(codes, tuple)
        self.assertIsInstance(mask, tuple)
        self.assertEqual(1445, len(codes))
        self.assertEqual(1445, len(mask))
        self.assertTrue(all(type(value) is bool for value in mask))
        self.assertEqual(tuple(code is None for code in codes), mask)

        candidate_actor = state.actor if state.actor is not None else Color.BLACK
        for action_id_value, actual in enumerate(codes):
            transition = apply_action(
                state,
                candidate_actor,
                envelope_for_id(action_id_value),
            )
            expected = None if transition.accepted else transition.rejection_code
            self.assertIs(
                expected,
                actual,
                msg=(
                    f"action {action_id_value} on {state.board.size}x{state.board.size} "
                    f"{state.phase.value}: expected {expected}, got {actual}"
                ),
            )

    def test_all_ids_match_on_reviewed_reachable_states(self) -> None:
        safe = SpecialQuotas(
            immortal=JSON_SAFE_INTEGER_MAX,
            double_start=JSON_SAFE_INTEGER_MAX,
            eightway=JSON_SAFE_INTEGER_MAX,
        )
        collapse_one_pass = accept(
            new_game(OracleConfig(board_size=9)),
            action(ActionKind.PASS),
        )
        ordinary_one_pass = accept(
            enter_ordinary(),
            action(ActionKind.PASS),
        )
        reviewed = (
            *(new_game(OracleConfig(board_size=size)) for size in (9, 13, 19)),
            pending_double_state(),
            collapse_one_pass,
            enter_ordinary(),
            ordinary_one_pass,
            settled_surviving_sources_state(),
            enter_terminal(),
            simultaneous_capture_state(),
            captured_eightway_source_state(),
            reversed_eightway_endpoint_state(),
            rich_mixed_state(),
            funded_threshold_minus_two_state(),
            pending_double_before_threshold_state(),
            threshold_minus_one_state(),
            new_game(
                OracleConfig(
                    board_size=9,
                    quotas=PlayerQuotas(black=safe, white=safe),
                )
            ),
        )
        for index, state in enumerate(reviewed):
            with self.subTest(
                index=index,
                size=state.board.size,
                phase=state.phase,
                pending=state.pending_double is not None,
                action_count=state.atomic_action_count,
            ):
                self.assert_all_ids_match_reducer(state)


class ActionLegalityRuleCoverageTests(unittest.TestCase):
    def test_centered_footprints_have_exact_size_and_mask(self) -> None:
        for size in (9, 13, 19):
            with self.subTest(size=size):
                state = new_game(OracleConfig(board_size=size))
                codes = enumerate_action_legality(state)
                mask = derive_legal_mask(state)
                self.assertEqual(4 * size * size + 1, sum(mask))
                offset = (19 - size) // 2
                for family in range(4):
                    for canvas_point in range(361):
                        x = canvas_point % 19
                        y = canvas_point // 19
                        inside = (
                            offset <= x < offset + size
                            and offset <= y < offset + size
                        )
                        code = codes[family * 361 + canvas_point]
                        self.assertIs(
                            None if inside else RejectionCode.POINT_OFF_BOARD,
                            code,
                        )
                self.assertIsNone(codes[PASS_ACTION_ID])

    def test_automatic_transition_snapshots_fail_closed_before_footprint(self) -> None:
        def pass_snapshot(state: OracleState) -> OracleState:
            if state.actor is None:
                raise AssertionError("automatic-transition fixture requires an actor")
            snapshot = copy.copy(state)
            for name, value in (
                ("actor", state.actor.opponent()),
                ("atomic_action_count", state.atomic_action_count + 1),
                ("consecutive_passes", state.consecutive_passes + 1),
                ("psk_history", state.psk_history + (state.board.occupancy,)),
                ("revision", state.revision + 1),
                ("log_position", state.log_position + 1),
            ):
                object.__setattr__(snapshot, name, value)
            return snapshot

        threshold_snapshot = pass_snapshot(threshold_minus_one_state())
        early_snapshot = pass_snapshot(
            accept(new_game(OracleConfig(board_size=9)), action(ActionKind.PASS))
        )
        scoring_snapshot = pass_snapshot(
            accept(enter_ordinary(), action(ActionKind.PASS))
        )
        self.assertEqual(
            threshold_snapshot.threshold,
            threshold_snapshot.atomic_action_count,
        )
        self.assertLess(
            early_snapshot.atomic_action_count,
            early_snapshot.threshold,
        )
        self.assertEqual(2, early_snapshot.consecutive_passes)
        self.assertIs(Phase.ORDINARY_PLAY, scoring_snapshot.phase)
        self.assertEqual(2, scoring_snapshot.consecutive_passes)

        expected = (RejectionCode.INTERNAL_INVARIANT,) * (PASS_ACTION_ID + 1)
        for name, snapshot in (
            ("threshold", threshold_snapshot),
            ("early settlement", early_snapshot),
            ("scoring", scoring_snapshot),
        ):
            with self.subTest(snapshot=name):
                self.assertEqual(expected, enumerate_action_legality(snapshot))
                self.assertEqual((False,) * (PASS_ACTION_ID + 1), derive_legal_mask(snapshot))

    def test_precedence_phase_pending_threshold_quota_and_occupancy(self) -> None:
        terminal = enter_terminal()
        terminal_codes = enumerate_action_legality(terminal)
        self.assertIs(
            RejectionCode.POINT_OFF_BOARD,
            terminal_codes[0],
        )
        self.assertIs(
            RejectionCode.TERMINAL_STATE,
            terminal_codes[action_id(ActionKind.NORMAL, x=0, y=0)],
        )
        self.assertIs(
            RejectionCode.TERMINAL_STATE,
            terminal_codes[PASS_ACTION_ID],
        )

        ordinary = enter_ordinary()
        ordinary = accept(ordinary, action(ActionKind.NORMAL, x=4, y=4))
        ordinary_codes = enumerate_action_legality(ordinary)
        self.assertIs(
            RejectionCode.POINT_OCCUPIED,
            ordinary_codes[action_id(ActionKind.NORMAL, x=4, y=4)],
        )
        for kind in (
            ActionKind.IMMORTAL,
            ActionKind.DOUBLE_START,
            ActionKind.EIGHTWAY,
        ):
            self.assertIs(
                RejectionCode.INVALID_PHASE,
                ordinary_codes[action_id(kind, x=4, y=4)],
            )
        self.assertIsNone(ordinary_codes[PASS_ACTION_ID])

        pending = pending_double_state()
        pending_codes = enumerate_action_legality(pending)
        self.assertIs(
            RejectionCode.POINT_OCCUPIED,
            pending_codes[action_id(ActionKind.NORMAL, x=4, y=4)],
        )
        for kind in (
            ActionKind.IMMORTAL,
            ActionKind.DOUBLE_START,
            ActionKind.EIGHTWAY,
        ):
            self.assertIs(
                RejectionCode.DOUBLE_CONTINUATION_KIND_FORBIDDEN,
                pending_codes[action_id(kind, x=4, y=4)],
            )
            self.assertIs(
                RejectionCode.POINT_OFF_BOARD,
                pending_codes[361 * KIND_CODE[kind]],
            )
        self.assertIsNone(pending_codes[PASS_ACTION_ID])

        threshold = threshold_minus_one_state()
        threshold_codes = enumerate_action_legality(threshold)
        occupied = threshold.board.occupancy.black[0]
        x = occupied % 9
        y = occupied // 9
        self.assertIs(
            RejectionCode.DOUBLE_THRESHOLD,
            threshold_codes[action_id(ActionKind.DOUBLE_START, x=x, y=y)],
        )
        self.assertIs(
            RejectionCode.QUOTA_EXHAUSTED,
            threshold_codes[action_id(ActionKind.IMMORTAL, x=x, y=y)],
        )
        self.assertIs(
            RejectionCode.QUOTA_EXHAUSTED,
            threshold_codes[action_id(ActionKind.EIGHTWAY, x=x, y=y)],
        )

        zero = new_game(
            OracleConfig(board_size=9, quotas=PlayerQuotas.zero())
        )
        zero = accept(zero, action(ActionKind.NORMAL, x=4, y=4))
        zero_codes = enumerate_action_legality(zero)
        for kind in (
            ActionKind.IMMORTAL,
            ActionKind.DOUBLE_START,
            ActionKind.EIGHTWAY,
        ):
            self.assertIs(
                RejectionCode.QUOTA_EXHAUSTED,
                zero_codes[action_id(kind, x=4, y=4)],
            )

    def test_simultaneous_capture_and_occupancy_only_psk(self) -> None:
        state = simultaneous_capture_state()
        center_ids = tuple(
            action_id(kind, x=2, y=2) for kind in POINT_KINDS
        )
        codes = enumerate_action_legality(state)
        self.assertTrue(all(codes[value] is None for value in center_ids))

        transition = apply_action(
            state,
            state.actor,
            action(ActionKind.NORMAL, x=2, y=2),
        )
        self.assertTrue(transition.accepted)
        self.assertEqual(
            (point(9, 2, 1), point(9, 2, 3)),
            transition.atomic_event.captured.white,
        )
        history = list(state.psk_history)
        history[1] = transition.atomic_event.stable_occupancy
        repeated = replace(state, psk_history=tuple(history))
        repeated_codes = enumerate_action_legality(repeated)
        self.assertTrue(
            all(
                repeated_codes[value] is RejectionCode.POSITIONAL_SUPERKO
                for value in center_ids
            )
        )

    def test_immortal_and_eightway_candidate_interfaces_are_distinct(self) -> None:
        surrounded = n8_suicide_state()
        surrounded_codes = enumerate_action_legality(surrounded)
        self.assertIsNone(
            surrounded_codes[action_id(ActionKind.IMMORTAL, x=4, y=4)]
        )
        for kind in (
            ActionKind.NORMAL,
            ActionKind.DOUBLE_START,
            ActionKind.EIGHTWAY,
        ):
            self.assertIs(
                RejectionCode.SUICIDE,
                surrounded_codes[action_id(kind, x=4, y=4)],
            )

        mixed = mixed_protection_state()
        mixed_codes = enumerate_action_legality(mixed)
        self.assertIsNone(mixed_codes[action_id(ActionKind.IMMORTAL, x=4, y=4)])
        self.assertIsNone(mixed_codes[action_id(ActionKind.EIGHTWAY, x=4, y=4)])
        self.assertIs(
            RejectionCode.SUICIDE,
            mixed_codes[action_id(ActionKind.NORMAL, x=4, y=4)],
        )
        self.assertIs(
            RejectionCode.SUICIDE,
            mixed_codes[action_id(ActionKind.DOUBLE_START, x=4, y=4)],
        )

    def test_eightway_interfaces_are_anchor_local(self) -> None:
        target = point(9, 4, 4)
        diagonal_liberty = point(9, 5, 5)
        white_ring = tuple(
            sorted(
                point(9, x, y)
                for y in range(3, 6)
                for x in range(3, 6)
                if (x, y) not in ((4, 4), (5, 5))
            )
        )
        diagonal_state = golden_state(white=white_ring)
        self.assertNotIn(target, diagonal_state.board.occupancy.white)
        self.assertNotIn(diagonal_liberty, diagonal_state.board.occupancy.white)
        diagonal_codes = enumerate_action_legality(diagonal_state)
        self.assertIsNone(
            diagonal_codes[action_id(ActionKind.EIGHTWAY, x=4, y=4)]
        )
        for kind in (ActionKind.NORMAL, ActionKind.DOUBLE_START):
            self.assertIs(
                RejectionCode.SUICIDE,
                diagonal_codes[action_id(kind, x=4, y=4)],
            )

        anchor = point(9, 3, 3)
        ordinary_member = point(9, 4, 4)
        member_only_diagonal = point(9, 3, 5)
        member_target = point(9, 5, 4)
        blockers = points(
            (2, 2),
            (3, 2),
            (4, 2),
            (2, 3),
            (4, 3),
            (2, 4),
            (3, 4),
            (4, 5),
            (5, 3),
            (5, 5),
            (6, 3),
            (6, 4),
            (6, 5),
        )
        member_state = golden_state(
            black=(anchor, ordinary_member),
            white=blockers,
            special_sources=((anchor, ActionKind.EIGHTWAY, True),),
        )
        self.assertNotIn(member_only_diagonal, member_state.board.occupancy.white)
        self.assertNotIn(member_target, member_state.board.occupancy.white)
        member_codes = enumerate_action_legality(member_state)
        for kind in (ActionKind.NORMAL, ActionKind.DOUBLE_START):
            self.assertIs(
                RejectionCode.SUICIDE,
                member_codes[action_id(kind, x=5, y=4)],
            )

    def test_reversed_endpoint_eightway_diagonal_is_undirected(self) -> None:
        state = reversed_eightway_endpoint_state()
        target_id = action_id(ActionKind.EIGHTWAY, x=3, y=3)
        self.assertLess(point(9, 3, 3), point(9, 4, 4))
        codes = enumerate_action_legality(state)
        self.assertIsNone(codes[target_id])
        for kind in (ActionKind.NORMAL, ActionKind.DOUBLE_START):
            self.assertIs(
                RejectionCode.SUICIDE,
                codes[action_id(kind, x=3, y=3)],
            )
        for symmetry in range(8):
            transformed = transform_state(state, symmetry)
            self.assertIsNone(
                enumerate_action_legality(transformed)[
                    transform_action_id(target_id, symmetry)
                ]
            )

    def test_protected_opponent_is_excluded_from_capture(self) -> None:
        target = point(9, 4, 4)
        protected_ring = tuple(
            sorted(
                point(9, x, y)
                for y in range(3, 6)
                for x in range(3, 6)
                if (x, y) != (4, 4)
            )
        )
        outer_blockers = points(
            (3, 2),
            (4, 2),
            (5, 2),
            (2, 3),
            (6, 3),
            (2, 4),
            (6, 4),
            (2, 5),
            (6, 5),
            (3, 6),
            (4, 6),
            (5, 6),
        )
        state = golden_state(
            black=outer_blockers,
            white=protected_ring,
            special_sources=(
                (point(9, 3, 3), ActionKind.IMMORTAL, True),
            ),
        )
        self.assertNotIn(target, state.occupancy.black)
        self.assertNotIn(target, state.occupancy.white)
        codes = enumerate_action_legality(state)
        for kind in (ActionKind.NORMAL, ActionKind.DOUBLE_START):
            self.assertIs(
                RejectionCode.SUICIDE,
                codes[action_id(kind, x=4, y=4)],
            )

    def test_captured_eightway_source_is_absent_from_second_scan(self) -> None:
        state = captured_eightway_source_state()
        self.assertEqual(
            (point(9, 0, 0), point(9, 7, 8), point(9, 8, 8)),
            state.occupancy.black,
        )
        self.assertEqual(
            (point(9, 1, 0), point(9, 0, 1)),
            state.occupancy.white,
        )
        self.assertEqual(1, len(state.ledger))
        self.assertIs(ActionKind.EIGHTWAY, state.ledger[0].kind)
        self.assertIs(AbilityState.ARMED, state.ledger[0].ability_state)
        self.assertEqual(point(9, 0, 0), state.ledger[0].source_point)
        self.assertIsNone(
            enumerate_action_legality(state)[
                action_id(ActionKind.NORMAL, x=1, y=1)
            ]
        )

        discriminating = golden_state(
            black=(0, 2, 11, 18, 19),
            white=(1, 9),
            actor=Color.WHITE,
            special_sources=((0, ActionKind.EIGHTWAY, True),),
        )
        self.assertIsNone(
            enumerate_action_legality(discriminating)[
                action_id(ActionKind.NORMAL, x=1, y=1)
            ]
        )

    def test_settled_sources_have_no_remaining_abilities(self) -> None:
        immortal_source = point(9, 1, 1)
        immortal_state = golden_state(
            black=(immortal_source,),
            white=points(
                (1, 0),
                (0, 1),
                (2, 1),
                (0, 2),
                (2, 2),
                (1, 3),
            ),
            phase=Phase.ORDINARY_PLAY,
            special_sources=(
                (immortal_source, ActionKind.IMMORTAL, False),
            ),
        )
        immortal_event = immortal_state.ledger[0]
        self.assertIs(AbilityState.INACTIVE, immortal_event.ability_state)
        self.assertIs(SettlementState.SETTLED, immortal_event.settlement_state)
        self.assertTrue(immortal_event.tombstone)
        self.assertIs(
            RejectionCode.SUICIDE,
            enumerate_action_legality(immortal_state)[
                action_id(ActionKind.NORMAL, x=1, y=2)
            ],
        )

        eightway_source = point(9, 0, 2)
        eightway_state = golden_state(
            black=(eightway_source,),
            white=points((0, 1), (1, 0), (2, 1), (1, 2)),
            phase=Phase.ORDINARY_PLAY,
            special_sources=(
                (eightway_source, ActionKind.EIGHTWAY, False),
            ),
        )
        eightway_event = eightway_state.ledger[0]
        self.assertIs(AbilityState.INACTIVE, eightway_event.ability_state)
        self.assertIs(SettlementState.SETTLED, eightway_event.settlement_state)
        self.assertTrue(eightway_event.tombstone)
        self.assertIs(
            RejectionCode.SUICIDE,
            enumerate_action_legality(eightway_state)[
                action_id(ActionKind.NORMAL, x=1, y=1)
            ],
        )

    def test_psk_uses_complete_two_color_occupancy(self) -> None:
        current = Occupancy(
            black=(point(9, 0, 0),),
            white=(point(9, 8, 8),),
        )
        candidate = Occupancy(
            black=(point(9, 0, 0), point(9, 1, 0)),
            white=current.white,
        )
        exact_repeat = golden_state(
            black=current.black,
            white=current.white,
            psk_history=(Occupancy.empty(), candidate, current),
        )
        self.assertIs(
            RejectionCode.POSITIONAL_SUPERKO,
            enumerate_action_legality(exact_repeat)[
                action_id(ActionKind.NORMAL, x=1, y=0)
            ],
        )

        actor_only_match = Occupancy(
            black=candidate.black,
            white=(point(9, 7, 8),),
        )
        two_color_control = golden_state(
            black=current.black,
            white=current.white,
            psk_history=(Occupancy.empty(), actor_only_match, current),
        )
        self.assertIsNone(
            enumerate_action_legality(two_color_control)[
                action_id(ActionKind.NORMAL, x=1, y=0)
            ]
        )

    def test_white_actor_uses_white_quota_buckets(self) -> None:
        state = new_game(
            OracleConfig(
                board_size=9,
                quotas=PlayerQuotas(
                    black=SpecialQuotas(
                        immortal=0,
                        double_start=2,
                        eightway=0,
                    ),
                    white=SpecialQuotas(
                        immortal=1,
                        double_start=0,
                        eightway=2,
                    ),
                ),
            )
        )
        state = accept(state, action(ActionKind.NORMAL, x=0, y=0))
        self.assertIs(Color.WHITE, state.actor)
        codes = enumerate_action_legality(state)
        self.assertIsNone(codes[action_id(ActionKind.IMMORTAL, x=8, y=8)])
        self.assertIs(
            RejectionCode.QUOTA_EXHAUSTED,
            codes[action_id(ActionKind.DOUBLE_START, x=8, y=8)],
        )
        self.assertIsNone(codes[action_id(ActionKind.EIGHTWAY, x=8, y=8)])

    def test_pass_is_legal_at_both_second_pass_boundaries(self) -> None:
        collapse = accept(
            new_game(OracleConfig(board_size=9)),
            action(ActionKind.PASS),
        )
        self.assertIs(Phase.COLLAPSE_PLAY, collapse.phase)
        self.assertEqual(1, collapse.consecutive_passes)
        self.assertIsNone(enumerate_action_legality(collapse)[PASS_ACTION_ID])

        ordinary = accept(enter_ordinary(), action(ActionKind.PASS))
        self.assertIs(Phase.ORDINARY_PLAY, ordinary.phase)
        self.assertEqual(1, ordinary.consecutive_passes)
        self.assertIsNone(enumerate_action_legality(ordinary)[PASS_ACTION_ID])

    def test_pending_and_suicide_precede_later_rejections(self) -> None:
        pending = pending_double_before_threshold_state()
        self.assertEqual(pending.threshold - 1, pending.atomic_action_count)
        self.assertIsNotNone(pending.pending_double)
        self.assertIs(
            RejectionCode.DOUBLE_CONTINUATION_KIND_FORBIDDEN,
            enumerate_action_legality(pending)[
                action_id(ActionKind.DOUBLE_START, x=8, y=4)
            ],
        )

        target = point(9, 4, 4)
        white = points((4, 3), (3, 4), (5, 4), (4, 5))
        repeated_suicide = Occupancy(black=(target,), white=white)
        suicide = golden_state(
            white=white,
            psk_history=(
                Occupancy.empty(),
                repeated_suicide,
                Occupancy(white=white),
            ),
        )
        self.assertIs(
            RejectionCode.SUICIDE,
            enumerate_action_legality(suicide)[
                action_id(ActionKind.NORMAL, x=4, y=4)
            ],
        )

    def test_funded_threshold_minus_two_double_start_is_legal(self) -> None:
        state = funded_threshold_minus_two_state()
        self.assertEqual(state.threshold - 2, state.atomic_action_count)
        self.assertIs(Color.BLACK, state.actor)
        self.assertEqual(1, state.remaining_quotas.black.double_start)
        self.assertIsNone(
            enumerate_action_legality(state)[
                action_id(ActionKind.DOUBLE_START, x=4, y=5)
            ]
        )

    def test_safe_integer_quota_maximums_do_not_narrow_special_masks(self) -> None:
        safe = SpecialQuotas(
            immortal=JSON_SAFE_INTEGER_MAX,
            double_start=JSON_SAFE_INTEGER_MAX,
            eightway=JSON_SAFE_INTEGER_MAX,
        )
        state = new_game(
            OracleConfig(
                board_size=9,
                quotas=PlayerQuotas(black=safe, white=safe),
            )
        )
        codes = enumerate_action_legality(state)
        self.assertEqual(4 * 81 + 1, sum(code is None for code in codes))
        for kind in POINT_KINDS:
            self.assertIsNone(codes[action_id(kind, x=4, y=4)])

    def test_derivation_is_pure_repeatable_and_state_preserving(self) -> None:
        state = rich_mixed_state()
        snapshot = copy.deepcopy(state)
        first = enumerate_action_legality(state)
        second = enumerate_action_legality(state)
        self.assertEqual(first, second)
        self.assertEqual(snapshot, state)
        self.assertEqual(
            tuple(code is None for code in first),
            derive_legal_mask(state),
        )
        self.assertEqual(snapshot, state)

    def test_d4_equivariance_and_inverse_round_trip(self) -> None:
        state = rich_mixed_state()
        base = enumerate_action_legality(state)
        for symmetry in range(8):
            with self.subTest(symmetry=symmetry):
                transformed_state = transform_state(state, symmetry)
                transformed = enumerate_action_legality(transformed_state)
                for action_id_value, code in enumerate(base):
                    self.assertIs(
                        code,
                        transformed[
                            transform_action_id(action_id_value, symmetry)
                        ],
                    )
                restored_state = transform_state(
                    transformed_state,
                    INVERSE_SYMMETRY[symmetry],
                )
                self.assertEqual(state, restored_state)
                self.assertEqual(
                    base,
                    enumerate_action_legality(restored_state),
                )


if __name__ == "__main__":
    unittest.main()
