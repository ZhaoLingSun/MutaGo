"""Independent stdlib-only Collapse Go NORMAL/PASS reference slice.

This module deliberately implements only the semantic slice needed to execute
NORMAL and PASS actions through empty-ledger settlement and ordinary-play
scoring.  It does not import KataGo's Python game helpers, the executable
contract implementation, C++, or numerical frameworks.

Special actions receive all rejections that can be decided before their
ability mechanics are needed.  A special action that remains potentially
legal raises :class:`UnsupportedSliceAction`; it is never assigned a made-up
semantic rejection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

ACTION_SCHEMA_VERSION = "action-v1"
CANVAS_SIZE = 19
CANVAS_POINT_COUNT = CANVAS_SIZE * CANVAS_SIZE
PASS_ACTION_ID = 1444
SUPPORTED_BOARD_SIZES = (9, 13, 19)
KOMI_NUMERATOR = 15
SCORE_DENOMINATOR = 2


class Color(str, Enum):
    BLACK = "BLACK"
    WHITE = "WHITE"

    def opponent(self) -> "Color":
        return Color.WHITE if self is Color.BLACK else Color.BLACK


class ActionKind(str, Enum):
    NORMAL = "NORMAL"
    IMMORTAL = "IMMORTAL"
    DOUBLE_START = "DOUBLE_START"
    EIGHTWAY = "EIGHTWAY"
    PASS = "PASS"


class Phase(str, Enum):
    COLLAPSE_PLAY = "COLLAPSE_PLAY"
    ORDINARY_PLAY = "ORDINARY_PLAY"
    TERMINAL = "TERMINAL"


class RejectionCode(str, Enum):
    POINT_OFF_BOARD = "POINT_OFF_BOARD"
    TERMINAL_STATE = "TERMINAL_STATE"
    INVALID_PHASE = "INVALID_PHASE"
    WRONG_ACTOR = "WRONG_ACTOR"
    DOUBLE_CONTINUATION_KIND_FORBIDDEN = "DOUBLE_CONTINUATION_KIND_FORBIDDEN"
    DOUBLE_CONTINUATION_REQUIRED = "DOUBLE_CONTINUATION_REQUIRED"
    DOUBLE_THRESHOLD = "DOUBLE_THRESHOLD"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    POINT_OCCUPIED = "POINT_OCCUPIED"
    SUICIDE = "SUICIDE"
    POSITIONAL_SUPERKO = "POSITIONAL_SUPERKO"
    INTERNAL_INVARIANT = "INTERNAL_INVARIANT"


class SettlementReason(str, Enum):
    THRESHOLD = "THRESHOLD"
    PRE_THRESHOLD_TWO_PASSES = "PRE_THRESHOLD_TWO_PASSES"


class TerminalReason(str, Enum):
    SCORE = "SCORE"


class ActionV1DecodeError(ValueError):
    """Raised when a value is not the closed canonical Action V1 envelope."""


class UnsupportedSliceAction(RuntimeError):
    """A potentially legal special action outside this oracle slice."""

    def __init__(self, action: "DecodedAction", actor: Color) -> None:
        self.action = action
        self.actor = actor
        super().__init__(
            f"{action.kind.value} action {action.action_id} for {actor.value} "
            "requires special-ability semantics outside the NORMAL/PASS slice"
        )


@dataclass(frozen=True, slots=True, order=True)
class Point:
    x: int
    y: int

    def __post_init__(self) -> None:
        if type(self.x) is not int or type(self.y) is not int:
            raise TypeError("point coordinates must be integers")


@dataclass(frozen=True, slots=True)
class Occupancy:
    """Occupancy-only PSK projection using board-local row-major points."""

    black: tuple[int, ...] = ()
    white: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _validate_point_tuple("black", self.black)
        _validate_point_tuple("white", self.white)
        if set(self.black).intersection(self.white):
            raise ValueError("black and white occupancy must be disjoint")

    @classmethod
    def empty(cls) -> "Occupancy":
        return cls()


@dataclass(frozen=True, slots=True)
class Board:
    size: int
    occupancy: Occupancy

    def __post_init__(self) -> None:
        _validate_board_size(self.size)
        point_count = self.size * self.size
        for point in self.occupancy.black + self.occupancy.white:
            if point >= point_count:
                raise ValueError(f"board point {point} is outside {self.size}x{self.size}")

    @classmethod
    def empty(cls, size: int) -> "Board":
        return cls(size=size, occupancy=Occupancy.empty())

    @classmethod
    def from_points(
        cls,
        size: int,
        *,
        black: Iterable[int] = (),
        white: Iterable[int] = (),
    ) -> "Board":
        return cls(
            size=size,
            occupancy=Occupancy(
                black=tuple(sorted(black)),
                white=tuple(sorted(white)),
            ),
        )

    def color_at(self, point: int) -> Color | None:
        if point in self.occupancy.black:
            return Color.BLACK
        if point in self.occupancy.white:
            return Color.WHITE
        return None

    def point(self, x: int, y: int) -> int:
        if type(x) is not int or type(y) is not int:
            raise TypeError("board coordinates must be integers")
        if not (0 <= x < self.size and 0 <= y < self.size):
            raise ValueError(f"coordinate ({x},{y}) is outside {self.size}x{self.size}")
        return self.size * y + x

    def coordinates(self, point: int) -> Point:
        if type(point) is not int or not (0 <= point < self.size * self.size):
            raise ValueError(f"invalid board point {point!r}")
        return Point(x=point % self.size, y=point // self.size)


@dataclass(frozen=True, slots=True)
class Group:
    color: Color
    stones: tuple[int, ...]
    liberties: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SpecialQuotas:
    immortal: int = 1
    double_start: int = 1
    eightway: int = 1

    def __post_init__(self) -> None:
        for name, value in (
            ("immortal", self.immortal),
            ("double_start", self.double_start),
            ("eightway", self.eightway),
        ):
            if type(value) is not int or value not in (0, 1):
                raise ValueError(f"{name} quota must be exactly 0 or 1")

    @classmethod
    def zero(cls) -> "SpecialQuotas":
        return cls(immortal=0, double_start=0, eightway=0)

    def for_kind(self, kind: ActionKind) -> int:
        if kind is ActionKind.IMMORTAL:
            return self.immortal
        if kind is ActionKind.DOUBLE_START:
            return self.double_start
        if kind is ActionKind.EIGHTWAY:
            return self.eightway
        raise ValueError(f"{kind.value} does not have a special quota")


@dataclass(frozen=True, slots=True)
class PlayerQuotas:
    black: SpecialQuotas = field(default_factory=SpecialQuotas)
    white: SpecialQuotas = field(default_factory=SpecialQuotas)

    def __post_init__(self) -> None:
        if not isinstance(self.black, SpecialQuotas) or not isinstance(
            self.white, SpecialQuotas
        ):
            raise TypeError("player quotas must contain SpecialQuotas values")

    @classmethod
    def zero(cls) -> "PlayerQuotas":
        return cls(black=SpecialQuotas.zero(), white=SpecialQuotas.zero())

    def for_player(self, player: Color) -> SpecialQuotas:
        return self.black if player is Color.BLACK else self.white


@dataclass(frozen=True, slots=True)
class OracleConfig:
    board_size: int = 19
    quotas: PlayerQuotas = field(default_factory=PlayerQuotas)

    def __post_init__(self) -> None:
        _validate_board_size(self.board_size)
        if not isinstance(self.quotas, PlayerQuotas):
            raise TypeError("quotas must be PlayerQuotas")

    @property
    def threshold(self) -> int:
        return settlement_threshold(self.board_size)

    @property
    def canvas_offset(self) -> int:
        return (CANVAS_SIZE - self.board_size) // 2


@dataclass(frozen=True, slots=True)
class DecodedAction:
    schema_version: str
    action_id: int
    kind: ActionKind
    canvas_point: Point | None
    board_point: Point | None
    board_index: int | None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    black_stones: int
    white_stones: int
    black_empty_area: int
    white_empty_area: int
    black_score_numerator: int
    white_score_numerator: int
    margin_numerator: int
    denominator: int
    winner: Color


@dataclass(frozen=True, slots=True)
class TerminalResult:
    reason: TerminalReason
    winner: Color
    loser: Color
    score: ScoreResult


@dataclass(frozen=True, slots=True)
class AtomicActionEvent:
    action_number: int
    actor: Color
    action: DecodedAction
    captured: Occupancy
    stable_occupancy: Occupancy
    psk_history_index: int


@dataclass(frozen=True, slots=True)
class SettlementResult:
    reason: SettlementReason
    ledger_entry_count: int = 0
    psk_appends: int = 0


@dataclass(frozen=True, slots=True)
class TerminalEvent:
    reason: TerminalReason
    winner: Color
    loser: Color
    score: ScoreResult
    stable_occupancy: Occupancy
    psk_history_index: int


@dataclass(frozen=True, slots=True)
class OracleState:
    config: OracleConfig
    board: Board
    actor: Color | None
    phase: Phase
    atomic_action_count: int
    consecutive_passes: int
    remaining_quotas: PlayerQuotas
    expired_quotas: PlayerQuotas
    psk_history: tuple[Occupancy, ...]
    terminal: TerminalResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.config, OracleConfig):
            raise TypeError("config must be OracleConfig")
        if not isinstance(self.board, Board):
            raise TypeError("board must be Board")
        if self.actor is not None and not isinstance(self.actor, Color):
            raise TypeError("actor must be Color or None")
        if not isinstance(self.phase, Phase):
            raise TypeError("phase must be Phase")
        if not isinstance(self.remaining_quotas, PlayerQuotas) or not isinstance(
            self.expired_quotas, PlayerQuotas
        ):
            raise TypeError("state quotas must be PlayerQuotas")
        if self.terminal is not None and not isinstance(self.terminal, TerminalResult):
            raise TypeError("terminal must be TerminalResult or None")
        if self.board.size != self.config.board_size:
            raise ValueError("board size does not match oracle configuration")
        if type(self.atomic_action_count) is not int or self.atomic_action_count < 0:
            raise ValueError("atomic_action_count must be a nonnegative integer")
        if type(self.consecutive_passes) is not int or not (
            0 <= self.consecutive_passes <= 2
        ):
            raise ValueError("consecutive_passes must be in 0..2")
        if not isinstance(self.psk_history, tuple) or not self.psk_history:
            raise ValueError("psk_history must be a nonempty tuple")
        empty = Occupancy.empty()
        if self.psk_history[0] != empty:
            raise ValueError("PSK history entry zero must be the empty occupancy")
        if self.psk_history[-1] != self.board.occupancy:
            raise ValueError("the latest PSK entry must equal the stable board occupancy")
        for occupancy in self.psk_history:
            if not isinstance(occupancy, Occupancy):
                raise TypeError("PSK history entries must be Occupancy values")
            for point in occupancy.black + occupancy.white:
                if point >= self.board.size * self.board.size:
                    raise ValueError("PSK history contains an off-board point")

        if self.phase is Phase.COLLAPSE_PLAY:
            if self.actor is None or self.terminal is not None:
                raise ValueError("collapse play requires an actor and no terminal result")
            if self.atomic_action_count >= self.config.threshold:
                raise ValueError("an exposed collapse state must be before the threshold")
            if self.consecutive_passes > 1:
                raise ValueError("two collapse passes must already have triggered settlement")
            if self.remaining_quotas != self.config.quotas:
                raise ValueError("the empty-ledger slice cannot consume special quotas")
            if self.expired_quotas != PlayerQuotas.zero():
                raise ValueError("quotas cannot expire before settlement")
        elif self.phase is Phase.ORDINARY_PLAY:
            if self.actor is None or self.terminal is not None:
                raise ValueError("ordinary play requires an actor and no terminal result")
            if self.consecutive_passes > 1:
                raise ValueError("two ordinary passes must already have ended the game")
            self._validate_post_settlement_quotas()
        elif self.phase is Phase.TERMINAL:
            if self.actor is not None or self.terminal is None:
                raise ValueError("terminal state requires no actor and a terminal result")
            self._validate_post_settlement_quotas()
        else:
            raise ValueError(f"unsupported phase {self.phase!r}")

        expected_psk_length = self.atomic_action_count + 1
        if self.phase is Phase.TERMINAL and self.terminal.reason is TerminalReason.SCORE:
            expected_psk_length += 1
        if len(self.psk_history) != expected_psk_length:
            raise ValueError(
                "PSK history length must equal the empty seed plus every atomic "
                "action append and, for scored terminal states, the terminal-event "
                "append"
            )

    def _validate_post_settlement_quotas(self) -> None:
        if self.remaining_quotas != PlayerQuotas.zero():
            raise ValueError("all remaining quotas expire at empty-ledger settlement")
        if self.expired_quotas != self.config.quotas:
            raise ValueError("expired quotas must preserve the configured unused quotas")

    @property
    def threshold(self) -> int:
        return self.config.threshold

    @property
    def settlement_completed(self) -> bool:
        return self.phase is not Phase.COLLAPSE_PLAY


@dataclass(frozen=True, slots=True)
class Transition:
    accepted: bool
    action: DecodedAction
    candidate_actor: Color
    state: OracleState
    rejection_code: RejectionCode | None
    atomic_event: AtomicActionEvent | None
    settlement: SettlementResult | None
    terminal_event: TerminalEvent | None

    def __post_init__(self) -> None:
        if self.accepted:
            if self.rejection_code is not None or self.atomic_event is None:
                raise ValueError("accepted transition requires an event and no rejection")
        elif (
            self.rejection_code is None
            or self.atomic_event is not None
            or self.settlement is not None
            or self.terminal_event is not None
        ):
            raise ValueError("rejected transition must have exactly one rejection code")


_POINT_KIND_RANGES = (
    (0, 360, ActionKind.NORMAL),
    (361, 721, ActionKind.IMMORTAL),
    (722, 1082, ActionKind.DOUBLE_START),
    (1083, 1443, ActionKind.EIGHTWAY),
)
_SPECIAL_KINDS = frozenset(
    (ActionKind.IMMORTAL, ActionKind.DOUBLE_START, ActionKind.EIGHTWAY)
)


def settlement_threshold(board_size: int) -> int:
    _validate_board_size(board_size)
    return (150 * board_size * board_size + 180) // 361


def new_game(config: OracleConfig | None = None) -> OracleState:
    if config is None:
        config = OracleConfig()
    if not isinstance(config, OracleConfig):
        raise TypeError("config must be OracleConfig")
    board = Board.empty(config.board_size)
    return OracleState(
        config=config,
        board=board,
        actor=Color.BLACK,
        phase=Phase.COLLAPSE_PLAY,
        atomic_action_count=0,
        consecutive_passes=0,
        remaining_quotas=config.quotas,
        expired_quotas=PlayerQuotas.zero(),
        psk_history=(board.occupancy,),
    )


def decode_action_v1(
    envelope: Mapping[str, object], board_size: int
) -> DecodedAction:
    """Strictly decode the closed Action V1 envelope for a selected board."""

    _validate_board_size(board_size)
    if not isinstance(envelope, Mapping):
        raise ActionV1DecodeError("Action V1 must be an object")
    required = {"schemaVersion", "actionId", "kind"}
    actual = set(envelope.keys())
    if actual != required:
        missing = sorted(required - actual)
        unknown = sorted(actual - required, key=repr)
        raise ActionV1DecodeError(
            f"Action V1 fields must be exactly {sorted(required)}; "
            f"missing={missing}, unknown={unknown}"
        )

    schema_version = envelope["schemaVersion"]
    action_id = envelope["actionId"]
    kind_value = envelope["kind"]
    if type(schema_version) is not str or schema_version != ACTION_SCHEMA_VERSION:
        raise ActionV1DecodeError("unknown Action V1 schemaVersion")
    if type(action_id) is not int or not (0 <= action_id <= PASS_ACTION_ID):
        raise ActionV1DecodeError("actionId must be an integer in 0..1444")
    if type(kind_value) is not str:
        raise ActionV1DecodeError("kind must be a canonical string")

    if action_id == PASS_ACTION_ID:
        expected_kind = ActionKind.PASS
        canvas_point = None
        board_point = None
        board_index = None
    else:
        expected_kind = _kind_for_action_id(action_id)
        point_index = action_id % CANVAS_POINT_COUNT
        canvas_point = Point(
            x=point_index % CANVAS_SIZE,
            y=point_index // CANVAS_SIZE,
        )
        offset = (CANVAS_SIZE - board_size) // 2
        if (
            offset <= canvas_point.x < offset + board_size
            and offset <= canvas_point.y < offset + board_size
        ):
            board_point = Point(
                x=canvas_point.x - offset,
                y=canvas_point.y - offset,
            )
            board_index = board_size * board_point.y + board_point.x
        else:
            board_point = None
            board_index = None

    if kind_value != expected_kind.value:
        raise ActionV1DecodeError(
            f"actionId {action_id} belongs to {expected_kind.value}, not {kind_value!r}"
        )
    return DecodedAction(
        schema_version=ACTION_SCHEMA_VERSION,
        action_id=action_id,
        kind=expected_kind,
        canvas_point=canvas_point,
        board_point=board_point,
        board_index=board_index,
    )


def scan_n4_groups(board: Board) -> tuple[Group, ...]:
    """Rebuild every N4 group and deduplicated liberty set from scratch."""

    black = set(board.occupancy.black)
    white = set(board.occupancy.white)
    occupied = black | white
    visited: set[int] = set()
    groups: list[Group] = []

    for start in range(board.size * board.size):
        if start in visited or start not in occupied:
            continue
        color = Color.BLACK if start in black else Color.WHITE
        own = black if color is Color.BLACK else white
        stones: set[int] = set()
        liberties: set[int] = set()
        stack = [start]
        visited.add(start)
        while stack:
            point = stack.pop()
            stones.add(point)
            for neighbor in _n4_neighbors(board.size, point):
                if neighbor in own:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        stack.append(neighbor)
                elif neighbor not in occupied:
                    liberties.add(neighbor)
        groups.append(
            Group(
                color=color,
                stones=tuple(sorted(stones)),
                liberties=tuple(sorted(liberties)),
            )
        )
    return tuple(groups)


def score_chinese_area(board: Board) -> ScoreResult:
    """Score the stable board exactly in half-point integer units."""

    black = set(board.occupancy.black)
    white = set(board.occupancy.white)
    occupied = black | white
    visited: set[int] = set()
    black_empty_area = 0
    white_empty_area = 0

    for start in range(board.size * board.size):
        if start in occupied or start in visited:
            continue
        region: set[int] = set()
        adjacent_colors: set[Color] = set()
        stack = [start]
        visited.add(start)
        while stack:
            point = stack.pop()
            region.add(point)
            for neighbor in _n4_neighbors(board.size, point):
                if neighbor in black:
                    adjacent_colors.add(Color.BLACK)
                elif neighbor in white:
                    adjacent_colors.add(Color.WHITE)
                elif neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        if adjacent_colors == {Color.BLACK}:
            black_empty_area += len(region)
        elif adjacent_colors == {Color.WHITE}:
            white_empty_area += len(region)

    black_score_numerator = 2 * (len(black) + black_empty_area)
    white_score_numerator = 2 * (len(white) + white_empty_area) + KOMI_NUMERATOR
    if black_score_numerator > white_score_numerator:
        winner = Color.BLACK
    else:
        winner = Color.WHITE
    return ScoreResult(
        black_stones=len(black),
        white_stones=len(white),
        black_empty_area=black_empty_area,
        white_empty_area=white_empty_area,
        black_score_numerator=black_score_numerator,
        white_score_numerator=white_score_numerator,
        margin_numerator=abs(black_score_numerator - white_score_numerator),
        denominator=SCORE_DENOMINATOR,
        winner=winner,
    )


def apply_action(
    state: OracleState,
    candidate_actor: Color | str,
    envelope: Mapping[str, object],
) -> Transition:
    """Apply one canonical Action V1 candidate without mutating ``state``."""

    if not isinstance(state, OracleState):
        raise TypeError("state must be OracleState")
    actor = _coerce_color(candidate_actor)
    action = decode_action_v1(envelope, state.config.board_size)

    # Frozen precedence begins with centered-footprint validation, even before
    # terminal, phase, or actor checks.
    if action.kind is not ActionKind.PASS and action.board_point is None:
        return _rejected(state, actor, action, RejectionCode.POINT_OFF_BOARD)
    if state.phase is Phase.TERMINAL:
        return _rejected(state, actor, action, RejectionCode.TERMINAL_STATE)
    if state.phase is Phase.ORDINARY_PLAY and action.kind in _SPECIAL_KINDS:
        return _rejected(state, actor, action, RejectionCode.INVALID_PHASE)
    if state.actor is not actor:
        return _rejected(state, actor, action, RejectionCode.WRONG_ACTOR)

    if action.kind in _SPECIAL_KINDS:
        if (
            action.kind is ActionKind.DOUBLE_START
            and state.atomic_action_count + 2 > state.threshold
        ):
            return _rejected(state, actor, action, RejectionCode.DOUBLE_THRESHOLD)
        if state.remaining_quotas.for_player(actor).for_kind(action.kind) == 0:
            return _rejected(state, actor, action, RejectionCode.QUOTA_EXHAUSTED)
        point = _board_index(state.board.size, action)
        if state.board.color_at(point) is not None:
            return _rejected(state, actor, action, RejectionCode.POINT_OCCUPIED)
        if action.kind is ActionKind.DOUBLE_START:
            board_after, _, own_survives = _simulate_normal_placement(
                state.board, actor, point
            )
            if not own_survives:
                return _rejected(state, actor, action, RejectionCode.SUICIDE)
            if board_after.occupancy in state.psk_history:
                return _rejected(
                    state, actor, action, RejectionCode.POSITIONAL_SUPERKO
                )
        raise UnsupportedSliceAction(action, actor)

    if action.kind is ActionKind.PASS:
        return _commit_pass(state, actor, action)
    if action.kind is not ActionKind.NORMAL:
        raise AssertionError(f"unhandled action kind {action.kind.value}")

    point = _board_index(state.board.size, action)
    if state.board.color_at(point) is not None:
        return _rejected(state, actor, action, RejectionCode.POINT_OCCUPIED)

    board_after, captured, own_survives = _simulate_normal_placement(
        state.board, actor, point
    )
    if not own_survives:
        return _rejected(state, actor, action, RejectionCode.SUICIDE)
    if board_after.occupancy in state.psk_history:
        return _rejected(state, actor, action, RejectionCode.POSITIONAL_SUPERKO)
    return _commit_normal(state, actor, action, board_after, captured)


def _commit_normal(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
    board_after: Board,
    captured: Occupancy,
) -> Transition:
    action_number = state.atomic_action_count + 1
    history = state.psk_history + (board_after.occupancy,)
    event = AtomicActionEvent(
        action_number=action_number,
        actor=actor,
        action=action,
        captured=captured,
        stable_occupancy=board_after.occupancy,
        psk_history_index=len(history) - 1,
    )
    settlement_reason = _settlement_reason(
        state.phase, action_number, state.threshold, consecutive_passes=0
    )
    if settlement_reason is not None:
        next_state = OracleState(
            config=state.config,
            board=board_after,
            actor=actor.opponent(),
            phase=Phase.ORDINARY_PLAY,
            atomic_action_count=action_number,
            consecutive_passes=0,
            remaining_quotas=PlayerQuotas.zero(),
            expired_quotas=state.config.quotas,
            psk_history=history,
        )
        settlement = SettlementResult(reason=settlement_reason)
    else:
        next_state = OracleState(
            config=state.config,
            board=board_after,
            actor=actor.opponent(),
            phase=state.phase,
            atomic_action_count=action_number,
            consecutive_passes=0,
            remaining_quotas=state.remaining_quotas,
            expired_quotas=state.expired_quotas,
            psk_history=history,
        )
        settlement = None
    return Transition(
        accepted=True,
        action=action,
        candidate_actor=actor,
        state=next_state,
        rejection_code=None,
        atomic_event=event,
        settlement=settlement,
        terminal_event=None,
    )


def _commit_pass(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
) -> Transition:
    action_number = state.atomic_action_count + 1
    consecutive_passes = state.consecutive_passes + 1
    history_after_action = state.psk_history + (state.board.occupancy,)
    event = AtomicActionEvent(
        action_number=action_number,
        actor=actor,
        action=action,
        captured=Occupancy.empty(),
        stable_occupancy=state.board.occupancy,
        psk_history_index=len(history_after_action) - 1,
    )

    settlement_reason = _settlement_reason(
        state.phase, action_number, state.threshold, consecutive_passes
    )
    if settlement_reason is not None:
        next_state = OracleState(
            config=state.config,
            board=state.board,
            actor=actor.opponent(),
            phase=Phase.ORDINARY_PLAY,
            atomic_action_count=action_number,
            consecutive_passes=0,
            remaining_quotas=PlayerQuotas.zero(),
            expired_quotas=state.config.quotas,
            psk_history=history_after_action,
        )
        return Transition(
            accepted=True,
            action=action,
            candidate_actor=actor,
            state=next_state,
            rejection_code=None,
            atomic_event=event,
            settlement=SettlementResult(reason=settlement_reason),
            terminal_event=None,
        )

    if state.phase is Phase.ORDINARY_PLAY and consecutive_passes == 2:
        score = score_chinese_area(state.board)
        terminal = TerminalResult(
            reason=TerminalReason.SCORE,
            winner=score.winner,
            loser=score.winner.opponent(),
            score=score,
        )
        terminal_history = history_after_action + (state.board.occupancy,)
        terminal_event = TerminalEvent(
            reason=TerminalReason.SCORE,
            winner=score.winner,
            loser=score.winner.opponent(),
            score=score,
            stable_occupancy=state.board.occupancy,
            psk_history_index=len(terminal_history) - 1,
        )
        next_state = OracleState(
            config=state.config,
            board=state.board,
            actor=None,
            phase=Phase.TERMINAL,
            atomic_action_count=action_number,
            consecutive_passes=2,
            remaining_quotas=state.remaining_quotas,
            expired_quotas=state.expired_quotas,
            psk_history=terminal_history,
            terminal=terminal,
        )
        return Transition(
            accepted=True,
            action=action,
            candidate_actor=actor,
            state=next_state,
            rejection_code=None,
            atomic_event=event,
            settlement=None,
            terminal_event=terminal_event,
        )

    next_state = OracleState(
        config=state.config,
        board=state.board,
        actor=actor.opponent(),
        phase=state.phase,
        atomic_action_count=action_number,
        consecutive_passes=consecutive_passes,
        remaining_quotas=state.remaining_quotas,
        expired_quotas=state.expired_quotas,
        psk_history=history_after_action,
    )
    return Transition(
        accepted=True,
        action=action,
        candidate_actor=actor,
        state=next_state,
        rejection_code=None,
        atomic_event=event,
        settlement=None,
        terminal_event=None,
    )


def _simulate_normal_placement(
    board: Board, actor: Color, point: int
) -> tuple[Board, Occupancy, bool]:
    black = set(board.occupancy.black)
    white = set(board.occupancy.white)
    own = black if actor is Color.BLACK else white
    own.add(point)
    tentative = _board_from_sets(board.size, black, white)

    first_scan = scan_n4_groups(tentative)
    opponent = actor.opponent()
    doomed: set[int] = set()
    for group in first_scan:
        if group.color is opponent and not group.liberties:
            doomed.update(group.stones)

    captured_black: set[int] = set()
    captured_white: set[int] = set()
    if opponent is Color.BLACK:
        captured_black = doomed
        black.difference_update(doomed)
    else:
        captured_white = doomed
        white.difference_update(doomed)
    after_capture = _board_from_sets(board.size, black, white)

    second_scan = scan_n4_groups(after_capture)
    own_group = next(
        (
            group
            for group in second_scan
            if group.color is actor and point in group.stones
        ),
        None,
    )
    own_survives = own_group is not None and bool(own_group.liberties)
    return (
        after_capture,
        Occupancy(
            black=tuple(sorted(captured_black)),
            white=tuple(sorted(captured_white)),
        ),
        own_survives,
    )


def _settlement_reason(
    phase: Phase,
    action_count: int,
    threshold: int,
    consecutive_passes: int,
) -> SettlementReason | None:
    if phase is not Phase.COLLAPSE_PLAY:
        return None
    if action_count == threshold:
        return SettlementReason.THRESHOLD
    if action_count < threshold and consecutive_passes == 2:
        return SettlementReason.PRE_THRESHOLD_TWO_PASSES
    return None


def _rejected(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
    code: RejectionCode,
) -> Transition:
    return Transition(
        accepted=False,
        action=action,
        candidate_actor=actor,
        state=state,
        rejection_code=code,
        atomic_event=None,
        settlement=None,
        terminal_event=None,
    )


def _kind_for_action_id(action_id: int) -> ActionKind:
    for first, last, kind in _POINT_KIND_RANGES:
        if first <= action_id <= last:
            return kind
    raise ActionV1DecodeError(f"invalid point actionId {action_id}")


def _board_index(board_size: int, action: DecodedAction) -> int:
    if action.board_index is None:
        raise AssertionError("point action has no semantic board point")
    if not (0 <= action.board_index < board_size * board_size):
        raise AssertionError("decoded board point is outside the selected board")
    return action.board_index


def _board_from_sets(size: int, black: set[int], white: set[int]) -> Board:
    return Board.from_points(size, black=black, white=white)


def _n4_neighbors(size: int, point: int) -> tuple[int, ...]:
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


def _coerce_color(value: Color | str) -> Color:
    if isinstance(value, Color):
        return value
    if type(value) is str:
        try:
            return Color(value)
        except ValueError as exc:
            raise ValueError(f"unknown candidate actor {value!r}") from exc
    raise TypeError("candidate_actor must be Color or its canonical string")


def _validate_board_size(board_size: int) -> None:
    if type(board_size) is not int or board_size not in SUPPORTED_BOARD_SIZES:
        raise ValueError("board_size must be exactly one of 9, 13, or 19")


def _validate_point_tuple(name: str, points: tuple[int, ...]) -> None:
    if not isinstance(points, tuple):
        raise TypeError(f"{name} occupancy must be a tuple")
    previous = -1
    for point in points:
        if type(point) is not int or point < 0:
            raise ValueError(f"{name} occupancy points must be nonnegative integers")
        if point <= previous:
            raise ValueError(f"{name} occupancy points must be strictly increasing")
        previous = point


__all__ = [
    "ACTION_SCHEMA_VERSION",
    "CANVAS_SIZE",
    "KOMI_NUMERATOR",
    "PASS_ACTION_ID",
    "SCORE_DENOMINATOR",
    "SUPPORTED_BOARD_SIZES",
    "ActionKind",
    "ActionV1DecodeError",
    "AtomicActionEvent",
    "Board",
    "Color",
    "DecodedAction",
    "Group",
    "Occupancy",
    "OracleConfig",
    "OracleState",
    "Phase",
    "PlayerQuotas",
    "Point",
    "RejectionCode",
    "ScoreResult",
    "SettlementReason",
    "SettlementResult",
    "SpecialQuotas",
    "TerminalEvent",
    "TerminalReason",
    "TerminalResult",
    "Transition",
    "UnsupportedSliceAction",
    "apply_action",
    "decode_action_v1",
    "new_game",
    "scan_n4_groups",
    "score_chinese_area",
    "settlement_threshold",
]
