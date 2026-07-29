"""Independent stdlib-only Collapse Go NORMAL/PASS reference slice.

This module exposes the source-aware immutable state shell, quota accounting,
future ledger/pending-Double shapes, and deterministic full-board N4 topology,
while deliberately implementing only the semantic transitions needed to execute
NORMAL and PASS through empty-ledger settlement and ordinary-play scoring.  It
does not import KataGo's Python game helpers, the executable contract
implementation, C++, or numerical frameworks.

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
JSON_SAFE_INTEGER_MAX = 9_007_199_254_740_991


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


class AbilityState(str, Enum):
    ARMED = "ARMED"
    CONSUMED = "CONSUMED"
    INACTIVE = "INACTIVE"


class StoneState(str, Enum):
    ON_BOARD = "ON_BOARD"
    CAPTURED = "CAPTURED"


class SettlementState(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"


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
class Stone:
    """One canonical on-board source identity."""

    point: int
    color: Color
    origin_action_number: int
    origin_kind: ActionKind
    special_event_id: str | None = None
    source_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.point) is not int or self.point < 0:
            raise ValueError("stone point must be a nonnegative integer")
        if not isinstance(self.color, Color):
            raise TypeError("stone color must be Color")
        if (
            type(self.origin_action_number) is not int
            or self.origin_action_number <= 0
        ):
            raise ValueError("stone origin_action_number must be a positive integer")
        if not isinstance(self.origin_kind, ActionKind):
            raise TypeError("stone origin_kind must be ActionKind")
        if self.origin_kind is ActionKind.PASS:
            raise ValueError("PASS cannot be the origin kind of an occupied stone")
        object.__setattr__(self, "source_id", f"stone-{self.origin_action_number}")
        if self.origin_kind is ActionKind.NORMAL:
            if self.special_event_id is not None:
                raise ValueError("NORMAL stones cannot link to a special event")
        elif self.special_event_id != f"special-{self.origin_action_number}":
            raise ValueError("special-origin stones require their canonical event linkage")


@dataclass(frozen=True, slots=True)
class Board:
    """Canonical source-aware board with occupancy derived from its stones."""

    size: int
    stones: tuple[Stone, ...] = ()
    occupancy: Occupancy = field(init=False)

    def __post_init__(self) -> None:
        _validate_board_size(self.size)
        if not isinstance(self.stones, tuple):
            raise TypeError("board stones must be a tuple")
        point_count = self.size * self.size
        previous = -1
        source_ids: set[str] = set()
        black: list[int] = []
        white: list[int] = []
        for stone in self.stones:
            if not isinstance(stone, Stone):
                raise TypeError("board stones must contain Stone values")
            if stone.point >= point_count:
                raise ValueError(
                    f"board point {stone.point} is outside {self.size}x{self.size}"
                )
            if stone.point <= previous:
                raise ValueError("board stones must be strictly ordered by point")
            if stone.source_id in source_ids:
                raise ValueError("board stone source IDs must be unique")
            previous = stone.point
            source_ids.add(stone.source_id)
            if stone.color is Color.BLACK:
                black.append(stone.point)
            else:
                white.append(stone.point)
        object.__setattr__(
            self,
            "occupancy",
            Occupancy(black=tuple(black), white=tuple(white)),
        )

    @classmethod
    def empty(cls, size: int) -> "Board":
        return cls(size=size)

    @classmethod
    def from_stones(cls, size: int, stones: Iterable[Stone]) -> "Board":
        if isinstance(stones, (str, bytes)):
            raise TypeError("stones must be an iterable of Stone values")
        source_stones = tuple(stones)
        if any(not isinstance(stone, Stone) for stone in source_stones):
            raise TypeError("stones must contain Stone values")
        return cls(
            size=size,
            stones=tuple(sorted(source_stones, key=lambda stone: stone.point)),
        )

    @classmethod
    def from_points(
        cls,
        size: int,
        *,
        black: Iterable[int] = (),
        white: Iterable[int] = (),
        origin_action_number: int = 1,
        origin_kind: ActionKind = ActionKind.NORMAL,
        special_event_id: str | None = None,
    ) -> "Board":
        occupancy = Occupancy(
            black=tuple(sorted(black)),
            white=tuple(sorted(white)),
        )
        colored_points = sorted(
            (
                *((point, Color.BLACK) for point in occupancy.black),
                *((point, Color.WHITE) for point in occupancy.white),
            ),
            key=lambda item: item[0],
        )
        stones = tuple(
            Stone(
                point=point,
                color=color,
                origin_action_number=origin_action_number + offset,
                origin_kind=origin_kind,
                special_event_id=(
                    None
                    if origin_kind is ActionKind.NORMAL
                    else f"special-{origin_action_number + offset}"
                    if special_event_id is None
                    else special_event_id
                ),
            )
            for offset, (point, color) in enumerate(colored_points)
        )
        return cls.from_stones(size, stones)

    def stone_at(self, point: int) -> Stone | None:
        if type(point) is not int or not (0 <= point < self.size * self.size):
            raise ValueError(f"invalid board point {point!r}")
        for stone in self.stones:
            if stone.point == point:
                return stone
            if stone.point > point:
                break
        return None

    def color_at(self, point: int) -> Color | None:
        stone = self.stone_at(point)
        return stone.color if stone is not None else None

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
    source_stones: tuple[Stone, ...]
    protected: bool = False
    immortal_anchor_points: tuple[int, ...] = ()
    eightway_anchor_points: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.color, Color):
            raise TypeError("group color must be Color")
        _validate_point_tuple("group stones", self.stones)
        _validate_point_tuple("group liberties", self.liberties)
        if set(self.stones).intersection(self.liberties):
            raise ValueError("occupied group stones cannot also be liberties")
        if not isinstance(self.source_stones, tuple):
            raise TypeError("group source_stones must be a tuple")
        if any(not isinstance(stone, Stone) for stone in self.source_stones):
            raise TypeError("group source_stones must contain Stone values")
        if tuple(stone.point for stone in self.source_stones) != self.stones:
            raise ValueError("group source_stones must exactly match group stones")
        if any(stone.color is not self.color for stone in self.source_stones):
            raise ValueError("group source stones must all have the group color")
        if type(self.protected) is not bool:
            raise TypeError("group protected flag must be bool")
        source_by_point = {stone.point: stone for stone in self.source_stones}
        for name, anchors, expected_kind in (
            (
                "immortal anchors",
                self.immortal_anchor_points,
                ActionKind.IMMORTAL,
            ),
            (
                "eightway anchors",
                self.eightway_anchor_points,
                ActionKind.EIGHTWAY,
            ),
        ):
            _validate_point_tuple(name, anchors)
            if not set(anchors).issubset(self.stones):
                raise ValueError(f"{name} must be group member points")
            if any(
                source_by_point[point].origin_kind is not expected_kind
                for point in anchors
            ):
                raise ValueError(f"{name} must refer to matching source kinds")
        if self.protected != bool(self.immortal_anchor_points):
            raise ValueError("group protection must exactly match Immortal anchors")

    @property
    def anchor_points(self) -> tuple[int, ...]:
        return tuple(
            sorted(set(self.immortal_anchor_points + self.eightway_anchor_points))
        )


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
            if (
                type(value) is not int
                or value < 0
                or value > JSON_SAFE_INTEGER_MAX
            ):
                raise ValueError(
                    f"{name} quota must be an integer in "
                    f"0..{JSON_SAFE_INTEGER_MAX}"
                )

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
class SpecialEvent:
    """Immutable ledger identity plus explicit lifecycle dispositions."""

    event_id: str
    logical_order: int
    owner: Color
    kind: ActionKind
    source_point: int
    source_stone_id: str
    ability_state: AbilityState
    stone_state: StoneState
    settlement_state: SettlementState
    tombstone: bool

    def __post_init__(self) -> None:
        if type(self.logical_order) is not int or self.logical_order < 0:
            raise ValueError("special event logical order must be nonnegative")
        origin_action_number = self.logical_order + 1
        if self.event_id != f"special-{origin_action_number}":
            raise ValueError("special event id must use its canonical action label")
        if self.source_stone_id != f"stone-{origin_action_number}":
            raise ValueError("special source id must use its canonical action label")
        if not isinstance(self.owner, Color):
            raise TypeError("special event owner must be Color")
        if self.kind not in (
            ActionKind.IMMORTAL,
            ActionKind.DOUBLE_START,
            ActionKind.EIGHTWAY,
        ):
            raise ValueError("special event kind must be a special point action")
        if type(self.source_point) is not int or self.source_point < 0:
            raise ValueError("special event source point must be nonnegative")
        if not isinstance(self.ability_state, AbilityState):
            raise TypeError("ability_state must be AbilityState")
        if not isinstance(self.stone_state, StoneState):
            raise TypeError("stone_state must be StoneState")
        if not isinstance(self.settlement_state, SettlementState):
            raise TypeError("settlement_state must be SettlementState")
        if type(self.tombstone) is not bool:
            raise TypeError("special event tombstone must be bool")

    @property
    def origin_action_number(self) -> int:
        return self.logical_order + 1


@dataclass(frozen=True, slots=True)
class PendingDouble:
    owner: Color
    event_id: str
    start_action_number: int

    def __post_init__(self) -> None:
        if not isinstance(self.owner, Color):
            raise TypeError("pending Double owner must be Color")
        if type(self.start_action_number) is not int or self.start_action_number <= 0:
            raise ValueError("pending Double start action must be positive")
        if self.event_id != f"special-{self.start_action_number}":
            raise ValueError("pending Double must use its canonical event linkage")


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
    captured_stones: tuple[Stone, ...]
    placed_stone: Stone | None
    stable_occupancy: Occupancy
    stable_stones: tuple[Stone, ...]
    psk_history_index: int
    revision: int
    log_position: int


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
    stable_stones: tuple[Stone, ...]
    psk_history_index: int
    revision: int
    log_position: int


@dataclass(frozen=True, slots=True)
class OracleState:
    config: OracleConfig
    board: Board
    actor: Color | None
    phase: Phase
    atomic_action_count: int
    consecutive_passes: int
    initial_quotas: PlayerQuotas
    remaining_quotas: PlayerQuotas
    used_quotas: PlayerQuotas
    expired_quotas: PlayerQuotas
    ledger: tuple[SpecialEvent, ...]
    pending_double: PendingDouble | None
    settled_ledger_count: int
    stable_terminal_event_count: int
    psk_history: tuple[Occupancy, ...]
    revision: int
    log_position: int
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
        for name, quotas in (
            ("initial_quotas", self.initial_quotas),
            ("remaining_quotas", self.remaining_quotas),
            ("used_quotas", self.used_quotas),
            ("expired_quotas", self.expired_quotas),
        ):
            if not isinstance(quotas, PlayerQuotas):
                raise TypeError(f"{name} must be PlayerQuotas")
        if not isinstance(self.ledger, tuple):
            raise TypeError("ledger must be a tuple")
        if any(not isinstance(entry, SpecialEvent) for entry in self.ledger):
            raise TypeError("ledger entries must be SpecialEvent values")
        if self.pending_double is not None and not isinstance(
            self.pending_double, PendingDouble
        ):
            raise TypeError("pending_double must be PendingDouble or None")
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
        for name, value in (
            ("settled_ledger_count", self.settled_ledger_count),
            ("stable_terminal_event_count", self.stable_terminal_event_count),
            ("revision", self.revision),
            ("log_position", self.log_position),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")

        if self.initial_quotas != self.config.quotas:
            raise ValueError("initial quotas must equal the configured quotas")
        _validate_quota_conservation(
            self.initial_quotas,
            self.remaining_quotas,
            self.used_quotas,
            self.expired_quotas,
        )

        # Increment 0 exposes the final exact shell but accepts no special
        # action, so every reachable state has no special ledger or pending
        # continuation and has consumed no special quota.
        if self.ledger or self.pending_double is not None:
            raise ValueError("the NORMAL/PASS slice requires empty ledger and pending Double")
        if self.settled_ledger_count != 0:
            raise ValueError("the empty ledger slice cannot settle ledger entries")
        if self.used_quotas != PlayerQuotas.zero():
            raise ValueError("the NORMAL/PASS slice cannot consume special quotas")

        for stone in self.board.stones:
            if stone.origin_action_number > self.atomic_action_count:
                raise ValueError("stone source action cannot exceed committed action count")
            if (
                stone.origin_kind is not ActionKind.NORMAL
                or stone.special_event_id is not None
            ):
                raise ValueError("Increment 0 board stones must have NORMAL sources")

        for group in scan_n4_groups(self.board):
            if not group.liberties and not group.protected:
                raise ValueError(
                    "stable states cannot contain an unprotected zero-liberty group"
                )

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
            if self.remaining_quotas != self.initial_quotas:
                raise ValueError("unused quotas must remain available before settlement")
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

        expected_terminal_events = 1 if self.phase is Phase.TERMINAL else 0
        if self.stable_terminal_event_count != expected_terminal_events:
            raise ValueError(
                "stable_terminal_event_count must match the committed terminal event"
            )
        emitted_stable_event_count = (
            self.atomic_action_count
            + self.settled_ledger_count
            + self.stable_terminal_event_count
        )
        if self.revision != self.atomic_action_count:
            raise ValueError("revision must equal accepted candidates in this slice")
        if self.log_position != emitted_stable_event_count:
            raise ValueError("log_position must equal emitted stable semantic events")
        expected_psk_length = 1 + emitted_stable_event_count
        if len(self.psk_history) != expected_psk_length:
            raise ValueError(
                "PSK history length must equal one empty seed plus atomic actions, "
                "settled ledger events, and stable terminal events"
            )

    def _validate_post_settlement_quotas(self) -> None:
        if self.remaining_quotas != PlayerQuotas.zero():
            raise ValueError("all remaining quotas expire at empty-ledger settlement")
        if self.expired_quotas != self.initial_quotas:
            raise ValueError("expired quotas must preserve the configured unused quotas")

    @property
    def threshold(self) -> int:
        return self.config.threshold

    @property
    def settlement_completed(self) -> bool:
        return self.phase is not Phase.COLLAPSE_PLAY

    @property
    def special_event_ledger(self) -> tuple[SpecialEvent, ...]:
        return self.ledger

    @property
    def stones(self) -> tuple[Stone, ...]:
        return self.board.stones

    @property
    def occupancy(self) -> Occupancy:
        return self.board.occupancy


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
        initial_quotas=config.quotas,
        remaining_quotas=config.quotas,
        used_quotas=PlayerQuotas.zero(),
        expired_quotas=PlayerQuotas.zero(),
        ledger=(),
        pending_double=None,
        settled_ledger_count=0,
        stable_terminal_event_count=0,
        psk_history=(board.occupancy,),
        revision=0,
        log_position=0,
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
    """Directly rebuild all deterministic N4 topology from source stones."""

    if not isinstance(board, Board):
        raise TypeError("board must be Board")
    stone_by_point = {stone.point: stone for stone in board.stones}
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
        ordered_stones = tuple(sorted(stones))
        groups.append(
            Group(
                color=color,
                stones=ordered_stones,
                liberties=tuple(sorted(liberties)),
                source_stones=tuple(
                    stone_by_point[point] for point in ordered_stones
                ),
                protected=False,
                immortal_anchor_points=(),
                eightway_anchor_points=(),
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
            board_after, _, own_survives = _simulate_placement(
                state.board,
                actor,
                point,
                origin_action_number=state.atomic_action_count + 1,
                origin_kind=ActionKind.DOUBLE_START,
                special_event_id=f"special-{state.atomic_action_count + 1}",
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

    board_after, captured_stones, own_survives = _simulate_placement(
        state.board,
        actor,
        point,
        origin_action_number=state.atomic_action_count + 1,
        origin_kind=ActionKind.NORMAL,
        special_event_id=None,
    )
    if not own_survives:
        return _rejected(state, actor, action, RejectionCode.SUICIDE)
    if board_after.occupancy in state.psk_history:
        return _rejected(state, actor, action, RejectionCode.POSITIONAL_SUPERKO)
    return _commit_normal(
        state,
        actor,
        action,
        board_after,
        captured_stones,
    )


def _commit_normal(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
    board_after: Board,
    captured_stones: tuple[Stone, ...],
) -> Transition:
    action_number = state.atomic_action_count + 1
    next_revision = state.revision + 1
    next_log_position = state.log_position + 1
    history = state.psk_history + (board_after.occupancy,)
    placed_stone = board_after.stone_at(_board_index(board_after.size, action))
    if placed_stone is None:
        raise AssertionError("accepted placement source is absent from the stable board")
    event = AtomicActionEvent(
        action_number=action_number,
        actor=actor,
        action=action,
        captured=_occupancy_from_stones(captured_stones),
        captured_stones=captured_stones,
        placed_stone=placed_stone,
        stable_occupancy=board_after.occupancy,
        stable_stones=board_after.stones,
        psk_history_index=len(history) - 1,
        revision=next_revision,
        log_position=next_log_position,
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
            initial_quotas=state.initial_quotas,
            remaining_quotas=PlayerQuotas.zero(),
            used_quotas=state.used_quotas,
            expired_quotas=state.initial_quotas,
            ledger=state.ledger,
            pending_double=None,
            settled_ledger_count=state.settled_ledger_count,
            stable_terminal_event_count=state.stable_terminal_event_count,
            psk_history=history,
            revision=next_revision,
            log_position=next_log_position,
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
            initial_quotas=state.initial_quotas,
            remaining_quotas=state.remaining_quotas,
            used_quotas=state.used_quotas,
            expired_quotas=state.expired_quotas,
            ledger=state.ledger,
            pending_double=state.pending_double,
            settled_ledger_count=state.settled_ledger_count,
            stable_terminal_event_count=state.stable_terminal_event_count,
            psk_history=history,
            revision=next_revision,
            log_position=next_log_position,
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
    next_revision = state.revision + 1
    action_log_position = state.log_position + 1
    consecutive_passes = state.consecutive_passes + 1
    history_after_action = state.psk_history + (state.board.occupancy,)
    event = AtomicActionEvent(
        action_number=action_number,
        actor=actor,
        action=action,
        captured=Occupancy.empty(),
        captured_stones=(),
        placed_stone=None,
        stable_occupancy=state.board.occupancy,
        stable_stones=state.board.stones,
        psk_history_index=len(history_after_action) - 1,
        revision=next_revision,
        log_position=action_log_position,
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
            initial_quotas=state.initial_quotas,
            remaining_quotas=PlayerQuotas.zero(),
            used_quotas=state.used_quotas,
            expired_quotas=state.initial_quotas,
            ledger=state.ledger,
            pending_double=None,
            settled_ledger_count=state.settled_ledger_count,
            stable_terminal_event_count=state.stable_terminal_event_count,
            psk_history=history_after_action,
            revision=next_revision,
            log_position=action_log_position,
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
        terminal_log_position = action_log_position + 1
        terminal_event = TerminalEvent(
            reason=TerminalReason.SCORE,
            winner=score.winner,
            loser=score.winner.opponent(),
            score=score,
            stable_occupancy=state.board.occupancy,
            stable_stones=state.board.stones,
            psk_history_index=len(terminal_history) - 1,
            revision=next_revision,
            log_position=terminal_log_position,
        )
        next_state = OracleState(
            config=state.config,
            board=state.board,
            actor=None,
            phase=Phase.TERMINAL,
            atomic_action_count=action_number,
            consecutive_passes=2,
            initial_quotas=state.initial_quotas,
            remaining_quotas=state.remaining_quotas,
            used_quotas=state.used_quotas,
            expired_quotas=state.expired_quotas,
            ledger=state.ledger,
            pending_double=state.pending_double,
            settled_ledger_count=state.settled_ledger_count,
            stable_terminal_event_count=state.stable_terminal_event_count + 1,
            psk_history=terminal_history,
            revision=next_revision,
            log_position=terminal_log_position,
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
        initial_quotas=state.initial_quotas,
        remaining_quotas=state.remaining_quotas,
        used_quotas=state.used_quotas,
        expired_quotas=state.expired_quotas,
        ledger=state.ledger,
        pending_double=state.pending_double,
        settled_ledger_count=state.settled_ledger_count,
        stable_terminal_event_count=state.stable_terminal_event_count,
        psk_history=history_after_action,
        revision=next_revision,
        log_position=action_log_position,
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


def _simulate_placement(
    board: Board,
    actor: Color,
    point: int,
    *,
    origin_action_number: int,
    origin_kind: ActionKind,
    special_event_id: str | None,
) -> tuple[Board, tuple[Stone, ...], bool]:
    tentative_source = Stone(
        point=point,
        color=actor,
        origin_action_number=origin_action_number,
        origin_kind=origin_kind,
        special_event_id=special_event_id,
    )
    tentative = Board.from_stones(board.size, board.stones + (tentative_source,))

    first_scan = scan_n4_groups(tentative)
    opponent = actor.opponent()
    doomed: set[int] = set()
    for group in first_scan:
        if group.color is opponent and not group.liberties:
            doomed.update(group.stones)

    captured_stones = tuple(
        stone for stone in tentative.stones if stone.point in doomed
    )
    after_capture = Board.from_stones(
        board.size,
        (stone for stone in tentative.stones if stone.point not in doomed),
    )

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
    return after_capture, captured_stones, own_survives


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


def _occupancy_from_stones(stones: Iterable[Stone]) -> Occupancy:
    black: list[int] = []
    white: list[int] = []
    for stone in stones:
        if not isinstance(stone, Stone):
            raise TypeError("captured sources must be Stone values")
        if stone.color is Color.BLACK:
            black.append(stone.point)
        else:
            white.append(stone.point)
    return Occupancy(black=tuple(sorted(black)), white=tuple(sorted(white)))


def _validate_quota_conservation(
    initial: PlayerQuotas,
    remaining: PlayerQuotas,
    used: PlayerQuotas,
    expired: PlayerQuotas,
) -> None:
    for color_name in ("black", "white"):
        vectors = tuple(
            getattr(quotas, color_name)
            for quotas in (initial, remaining, used, expired)
        )
        for ability_name in ("immortal", "double_start", "eightway"):
            initial_value, remaining_value, used_value, expired_value = (
                getattr(vector, ability_name) for vector in vectors
            )
            if initial_value != remaining_value + used_value + expired_value:
                raise ValueError(
                    f"quota conservation failed for {color_name}/{ability_name}"
                )


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
    "JSON_SAFE_INTEGER_MAX",
    "PASS_ACTION_ID",
    "SCORE_DENOMINATOR",
    "SUPPORTED_BOARD_SIZES",
    "ActionKind",
    "ActionV1DecodeError",
    "AbilityState",
    "AtomicActionEvent",
    "Board",
    "Color",
    "DecodedAction",
    "Group",
    "Occupancy",
    "OracleConfig",
    "OracleState",
    "PendingDouble",
    "Phase",
    "PlayerQuotas",
    "Point",
    "RejectionCode",
    "ScoreResult",
    "SettlementReason",
    "SettlementResult",
    "SettlementState",
    "SpecialEvent",
    "SpecialQuotas",
    "Stone",
    "StoneState",
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
