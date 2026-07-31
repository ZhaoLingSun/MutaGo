"""Independent stdlib-only Collapse Go reference oracle.

This module implements source-aware immutable NORMAL, PASS, Immortal,
Double-Move, and Eightway semantics. It uses direct mixed-connectivity scans,
ordered occupancy-only PSK transactions, exact special-source lifecycles, and
global newest-first settlement to a deterministic fixed point.

The oracle does not import KataGo's Python game helpers, the executable
contract implementation, C++, subprocess/FFI bridges, or numerical frameworks.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    INVALID_LOSER = "INVALID_LOSER"
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
    RESIGNATION = "RESIGNATION"
    TIMEOUT = "TIMEOUT"


class AdministrativeTerminationReason(str, Enum):
    RESIGNATION = "RESIGNATION"
    TIMEOUT = "TIMEOUT"


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


_ARMED_ABILITY_KINDS = frozenset((ActionKind.IMMORTAL, ActionKind.EIGHTWAY))
_SPECIAL_KINDS = frozenset((*_ARMED_ABILITY_KINDS, ActionKind.DOUBLE_START))


class ActionV1DecodeError(ValueError):
    """Raised when a value is not the closed canonical Action V1 envelope."""


class UnsupportedSliceAction(RuntimeError):
    """Legacy compatibility exception retained for older slice callers."""

    def __init__(self, action: "DecodedAction", actor: Color) -> None:
        self.action = action
        self.actor = actor
        super().__init__(
            f"{action.kind.value} action {action.action_id} for {actor.value} "
            "is not supported by the requested compatibility slice"
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
        if type(self.point) is not int or not (0 <= self.point < CANVAS_POINT_COUNT):
            raise ValueError("stone point must be an integer in 0..360")
        if not isinstance(self.color, Color):
            raise TypeError("stone color must be Color")
        _validate_positive_safe_integer(
            "stone origin_action_number", self.origin_action_number
        )
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

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or (
            self.schema_version != ACTION_SCHEMA_VERSION
        ):
            raise ValueError("decoded action schema_version must be action-v1")
        if type(self.action_id) is not int or not (0 <= self.action_id <= PASS_ACTION_ID):
            raise ValueError("decoded action_id must be an integer in 0..1444")
        if not isinstance(self.kind, ActionKind):
            raise TypeError("decoded action kind must be ActionKind")
        expected_kind = (
            ActionKind.PASS
            if self.action_id == PASS_ACTION_ID
            else _kind_for_action_id(self.action_id)
        )
        if self.kind is not expected_kind:
            raise ValueError("decoded action kind must match action_id")

        if self.kind is ActionKind.PASS:
            if (
                self.canvas_point is not None
                or self.board_point is not None
                or self.board_index is not None
            ):
                raise ValueError("decoded PASS cannot contain point fields")
            return

        point_index = self.action_id % CANVAS_POINT_COUNT
        expected_canvas = Point(
            x=point_index % CANVAS_SIZE,
            y=point_index // CANVAS_SIZE,
        )
        if self.canvas_point != expected_canvas:
            raise ValueError("decoded canvas point must match action_id")
        if (self.board_point is None) is not (self.board_index is None):
            raise ValueError("decoded board point and index must be present together")

        footprint_matches: list[tuple[Point, int]] = []
        outside_some_footprint = False
        for board_size in SUPPORTED_BOARD_SIZES:
            offset = (CANVAS_SIZE - board_size) // 2
            inside = (
                offset <= expected_canvas.x < offset + board_size
                and offset <= expected_canvas.y < offset + board_size
            )
            if not inside:
                outside_some_footprint = True
                continue
            board_point = Point(
                x=expected_canvas.x - offset,
                y=expected_canvas.y - offset,
            )
            footprint_matches.append(
                (board_point, board_size * board_point.y + board_point.x)
            )

        if self.board_point is None:
            if not outside_some_footprint:
                raise ValueError("decoded in-footprint action requires a board point")
        else:
            if not isinstance(self.board_point, Point):
                raise TypeError("decoded board_point must be Point or None")
            if type(self.board_index) is not int:
                raise TypeError("decoded board_index must be int or None")
            if (self.board_point, self.board_index) not in footprint_matches:
                raise ValueError(
                    "decoded board point and index must match a supported footprint"
                )


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
        _validate_nonnegative_safe_integer(
            "special event logical order",
            self.logical_order,
            maximum=JSON_SAFE_INTEGER_MAX - 1,
        )
        origin_action_number = self.logical_order + 1
        if self.event_id != f"special-{origin_action_number}":
            raise ValueError("special event id must use its canonical action label")
        if self.source_stone_id != f"stone-{origin_action_number}":
            raise ValueError("special source id must use its canonical action label")
        if not isinstance(self.owner, Color):
            raise TypeError("special event owner must be Color")
        if not isinstance(self.kind, ActionKind):
            raise TypeError("special event kind must be ActionKind")
        if self.kind not in _SPECIAL_KINDS:
            raise ValueError("special event kind must be a special point action")
        if type(self.source_point) is not int or not (
            0 <= self.source_point < CANVAS_POINT_COUNT
        ):
            raise ValueError("special event source point must be an integer in 0..360")
        if not isinstance(self.ability_state, AbilityState):
            raise TypeError("ability_state must be AbilityState")
        if not isinstance(self.stone_state, StoneState):
            raise TypeError("stone_state must be StoneState")
        if not isinstance(self.settlement_state, SettlementState):
            raise TypeError("settlement_state must be SettlementState")
        if type(self.tombstone) is not bool:
            raise TypeError("special event tombstone must be bool")

        if self.kind is ActionKind.IMMORTAL:
            if self.settlement_state is SettlementState.PENDING:
                if (
                    self.ability_state is not AbilityState.ARMED
                    or self.stone_state is not StoneState.ON_BOARD
                    or self.tombstone
                ):
                    raise ValueError(
                        "pending Immortal must be armed, on board, and non-tombstone"
                    )
            elif (
                self.ability_state is not AbilityState.INACTIVE
                or not self.tombstone
            ):
                raise ValueError(
                    "settled Immortal must be inactive and tombstoned"
                )
        elif self.kind is ActionKind.EIGHTWAY:
            if (
                self.settlement_state is SettlementState.PENDING
                and self.stone_state is StoneState.ON_BOARD
            ):
                if self.ability_state is not AbilityState.ARMED or self.tombstone:
                    raise ValueError(
                        "pending on-board Eightway must be armed and non-tombstone"
                    )
            elif (
                self.ability_state is not AbilityState.INACTIVE
                or not self.tombstone
            ):
                raise ValueError(
                    "captured or settled Eightway must be inactive and tombstoned"
                )
        else:
            expected_ability = (
                AbilityState.CONSUMED
                if self.settlement_state is SettlementState.PENDING
                else AbilityState.INACTIVE
            )
            if self.ability_state is not expected_ability or not self.tombstone:
                raise ValueError(
                    "Double event lifecycle must match its settlement state and "
                    "remain tombstoned"
                )

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
        _validate_positive_safe_integer(
            "pending Double start action", self.start_action_number
        )
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

    def __post_init__(self) -> None:
        for name, value in (
            ("black_stones", self.black_stones),
            ("white_stones", self.white_stones),
            ("black_empty_area", self.black_empty_area),
            ("white_empty_area", self.white_empty_area),
            ("black_score_numerator", self.black_score_numerator),
            ("white_score_numerator", self.white_score_numerator),
            ("margin_numerator", self.margin_numerator),
        ):
            _validate_nonnegative_safe_integer(f"score {name}", value)
        if (
            self.black_stones
            + self.white_stones
            + self.black_empty_area
            + self.white_empty_area
            > CANVAS_POINT_COUNT
        ):
            raise ValueError("score stones and owned area cannot exceed the canvas")
        if type(self.denominator) is not int or self.denominator != SCORE_DENOMINATOR:
            raise ValueError(f"score denominator must be exactly {SCORE_DENOMINATOR}")
        if not isinstance(self.winner, Color):
            raise TypeError("score winner must be Color")
        expected_black = 2 * (self.black_stones + self.black_empty_area)
        expected_white = (
            2 * (self.white_stones + self.white_empty_area) + KOMI_NUMERATOR
        )
        if self.black_score_numerator != expected_black:
            raise ValueError("black score numerator must match stones and area")
        if self.white_score_numerator != expected_white:
            raise ValueError("white score numerator must match stones, area, and komi")
        if self.margin_numerator != abs(expected_black - expected_white):
            raise ValueError("score margin must match the score numerators")
        expected_winner = (
            Color.BLACK if expected_black > expected_white else Color.WHITE
        )
        if self.winner is not expected_winner:
            raise ValueError("score winner must match the exact score numerators")


@dataclass(frozen=True, slots=True)
class TerminalResult:
    reason: TerminalReason
    winner: Color
    loser: Color
    score: ScoreResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reason, TerminalReason):
            raise TypeError("terminal reason must be TerminalReason")
        if not isinstance(self.winner, Color) or not isinstance(self.loser, Color):
            raise TypeError("terminal players must be Color")
        if self.loser is not self.winner.opponent():
            raise ValueError("terminal loser must be the winner's opponent")
        if self.reason is TerminalReason.SCORE:
            if not isinstance(self.score, ScoreResult):
                raise TypeError("score terminal result requires ScoreResult")
            if self.score.winner is not self.winner:
                raise ValueError("terminal winner must match the score winner")
        elif self.score is not None:
            raise ValueError("administrative terminal results cannot contain a score")


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

    def __post_init__(self) -> None:
        _validate_positive_safe_integer("atomic action_number", self.action_number)
        if not isinstance(self.actor, Color):
            raise TypeError("atomic action actor must be Color")
        if not isinstance(self.action, DecodedAction):
            raise TypeError("atomic action must be DecodedAction")
        if not isinstance(self.action.kind, ActionKind):
            raise TypeError("atomic action kind must be ActionKind")
        if type(self.action.action_id) is not int or not (
            0 <= self.action.action_id <= PASS_ACTION_ID
        ):
            raise ValueError("atomic action ID must be an integer in 0..1444")
        expected_kind = (
            ActionKind.PASS
            if self.action.action_id == PASS_ACTION_ID
            else _kind_for_action_id(self.action.action_id)
        )
        if self.action.kind is not expected_kind:
            raise ValueError("atomic action kind must match its action ID")
        if not isinstance(self.captured, Occupancy):
            raise TypeError("atomic captured projection must be Occupancy")
        if not isinstance(self.captured_stones, tuple) or any(
            not isinstance(stone, Stone) for stone in self.captured_stones
        ):
            raise TypeError("atomic captured_stones must contain Stone values")
        if any(stone.color is self.actor for stone in self.captured_stones):
            raise ValueError("atomic captures must contain only opponent stones")
        if self.captured != _occupancy_from_stones(self.captured_stones):
            raise ValueError("atomic captured projection must match captured_stones")
        if self.placed_stone is not None and not isinstance(self.placed_stone, Stone):
            raise TypeError("atomic placed_stone must be Stone or None")
        if not isinstance(self.stable_occupancy, Occupancy):
            raise TypeError("atomic stable_occupancy must be Occupancy")
        if not isinstance(self.stable_stones, tuple) or any(
            not isinstance(stone, Stone) for stone in self.stable_stones
        ):
            raise TypeError("atomic stable_stones must contain Stone values")
        if self.stable_occupancy != _occupancy_from_stones(self.stable_stones):
            raise ValueError("atomic stable occupancy must match stable_stones")

        for name, stones in (
            ("captured_stones", self.captured_stones),
            ("stable_stones", self.stable_stones),
        ):
            points = tuple(stone.point for stone in stones)
            if points != tuple(sorted(points)) or len(points) != len(set(points)):
                raise ValueError(f"atomic {name} must be strictly ordered by point")
            source_ids = tuple(stone.source_id for stone in stones)
            if len(source_ids) != len(set(source_ids)):
                raise ValueError(f"atomic {name} source IDs must be unique")
            if any(stone.origin_action_number > self.action_number for stone in stones):
                raise ValueError(
                    f"atomic {name} sources cannot originate after the action"
                )
        captured_points = {stone.point for stone in self.captured_stones}
        stable_points = {stone.point for stone in self.stable_stones}
        captured_sources = {stone.source_id for stone in self.captured_stones}
        stable_sources = {stone.source_id for stone in self.stable_stones}
        if captured_points.intersection(stable_points) or captured_sources.intersection(
            stable_sources
        ):
            raise ValueError("captured sources cannot remain in the stable snapshot")

        if self.action.kind is ActionKind.PASS:
            if self.placed_stone is not None or self.captured_stones:
                raise ValueError("PASS events cannot place or capture stones")
        else:
            if self.placed_stone is None:
                raise ValueError("point action events require their placed source")
            if self.action.board_index is None:
                raise ValueError("point action events require a board-local point")
            if (
                self.placed_stone.point != self.action.board_index
                or self.placed_stone.color is not self.actor
                or self.placed_stone.origin_action_number != self.action_number
                or self.placed_stone.origin_kind is not self.action.kind
            ):
                raise ValueError("placed source must exactly match the atomic action")
            stable_source = next(
                (
                    stone
                    for stone in self.stable_stones
                    if stone.source_id == self.placed_stone.source_id
                ),
                None,
            )
            if stable_source != self.placed_stone:
                raise ValueError("placed source must remain in the atomic stable snapshot")

        for name, value in (
            ("psk_history_index", self.psk_history_index),
            ("revision", self.revision),
            ("log_position", self.log_position),
        ):
            _validate_nonnegative_safe_integer(f"atomic {name}", value)
        if self.revision != self.action_number:
            raise ValueError("atomic revision must equal action_number")
        if self.psk_history_index != self.log_position:
            raise ValueError("atomic PSK history index must equal log_position")


@dataclass(frozen=True, slots=True)
class SettlementStepEvent:
    """One immutable internal settlement-pop semantic record."""

    event_id: str
    logical_order: int
    owner: Color
    kind: ActionKind
    ability_deactivated: bool
    no_op: bool
    stable_occupancy: Occupancy
    stable_stones: tuple[Stone, ...]
    psk_history_index: int
    revision: int
    log_position: int
    removal_batches: tuple[Occupancy, ...] = ()

    def __post_init__(self) -> None:
        max_logical_order = JSON_SAFE_INTEGER_MAX - 1
        if type(self.logical_order) is not int or not (
            0 <= self.logical_order <= max_logical_order
        ):
            raise ValueError(
                "settlement step logical_order must be an integer in "
                f"0..{max_logical_order} so its one-based action remains JSON-safe"
            )
        if self.event_id != f"special-{self.logical_order + 1}":
            raise ValueError("settlement step must reference its canonical event ID")
        if not isinstance(self.owner, Color):
            raise TypeError("settlement step owner must be Color")
        if not isinstance(self.kind, ActionKind):
            raise TypeError("settlement step kind must be ActionKind")
        if self.kind not in _SPECIAL_KINDS:
            raise ValueError(
                "settlement steps must reference Immortal, Double, or Eightway events"
            )
        if type(self.ability_deactivated) is not bool or type(self.no_op) is not bool:
            raise TypeError("settlement step disposition flags must be bool")
        if not isinstance(self.removal_batches, tuple) or any(
            not isinstance(batch, Occupancy) for batch in self.removal_batches
        ):
            raise TypeError("settlement removal_batches must contain Occupancy values")
        if any(not (batch.black or batch.white) for batch in self.removal_batches):
            raise ValueError("settlement removal batches cannot be empty")
        if self.kind is ActionKind.DOUBLE_START:
            if self.ability_deactivated or self.removal_batches or not self.no_op:
                raise ValueError(
                    "Double settlement steps must be no-op without deactivation or removals"
                )
        else:
            expected_no_op = not self.ability_deactivated and not self.removal_batches
            if self.no_op is not expected_no_op:
                raise ValueError(
                    "settlement no_op must exactly match deactivation and removals"
                )
        if not isinstance(self.stable_occupancy, Occupancy):
            raise TypeError("settlement step occupancy must be Occupancy")
        if not isinstance(self.stable_stones, tuple) or any(
            not isinstance(stone, Stone) for stone in self.stable_stones
        ):
            raise TypeError("settlement step stable_stones must contain Stone values")
        if self.stable_occupancy != _occupancy_from_stones(self.stable_stones):
            raise ValueError("settlement stable occupancy must match stable_stones")
        for name, value in (
            ("psk_history_index", self.psk_history_index),
            ("revision", self.revision),
            ("log_position", self.log_position),
        ):
            if type(value) is not int or not (0 <= value <= JSON_SAFE_INTEGER_MAX):
                raise ValueError(
                    f"settlement step {name} must be an integer in "
                    f"0..{JSON_SAFE_INTEGER_MAX}"
                )
        if self.psk_history_index != self.log_position:
            raise ValueError("settlement step PSK history index must equal log_position")


@dataclass(frozen=True, slots=True)
class SettlementResult:
    reason: SettlementReason
    ledger_entry_count: int = 0
    psk_appends: int = 0
    steps: tuple[SettlementStepEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reason, SettlementReason):
            raise TypeError("settlement reason must be SettlementReason")
        for name, value in (
            ("ledger_entry_count", self.ledger_entry_count),
            ("psk_appends", self.psk_appends),
        ):
            if type(value) is not int or not (0 <= value <= JSON_SAFE_INTEGER_MAX):
                raise ValueError(
                    f"settlement {name} must be an integer in "
                    f"0..{JSON_SAFE_INTEGER_MAX}"
                )
        if not isinstance(self.steps, tuple) or any(
            not isinstance(step, SettlementStepEvent) for step in self.steps
        ):
            raise TypeError("settlement steps must contain SettlementStepEvent values")
        if len(self.steps) != self.ledger_entry_count:
            raise ValueError("settlement step count must match ledger_entry_count")
        if self.psk_appends != self.ledger_entry_count:
            raise ValueError("each settlement ledger entry must append one PSK state")
        for previous, current in zip(self.steps, self.steps[1:]):
            if previous.logical_order <= current.logical_order:
                raise ValueError(
                    "settlement steps must be strictly newest-to-oldest"
                )
            if (
                current.revision != previous.revision
                or current.log_position != previous.log_position + 1
                or current.psk_history_index
                != previous.psk_history_index + 1
            ):
                raise ValueError(
                    "settlement step positions must be consecutive at one revision"
                )


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

    def __post_init__(self) -> None:
        if not isinstance(self.reason, TerminalReason):
            raise TypeError("terminal event reason must be TerminalReason")
        if self.reason is not TerminalReason.SCORE:
            raise ValueError("action terminal events must use SCORE")
        if not isinstance(self.winner, Color) or not isinstance(self.loser, Color):
            raise TypeError("terminal event players must be Color")
        if self.loser is not self.winner.opponent():
            raise ValueError("terminal event loser must be the winner's opponent")
        if not isinstance(self.score, ScoreResult):
            raise TypeError("terminal event score must be ScoreResult")
        if self.score.winner is not self.winner:
            raise ValueError("terminal event winner must match the score winner")
        if not isinstance(self.stable_occupancy, Occupancy):
            raise TypeError("terminal event stable_occupancy must be Occupancy")
        if (
            self.score.black_stones != len(self.stable_occupancy.black)
            or self.score.white_stones != len(self.stable_occupancy.white)
        ):
            raise ValueError(
                "terminal event score stone counts must match stable occupancy"
            )
        if not isinstance(self.stable_stones, tuple) or any(
            not isinstance(stone, Stone) for stone in self.stable_stones
        ):
            raise TypeError("terminal event stable_stones must contain Stone values")
        if self.stable_occupancy != _occupancy_from_stones(self.stable_stones):
            raise ValueError("terminal event stable occupancy must match stable_stones")
        for name, value in (
            ("psk_history_index", self.psk_history_index),
            ("revision", self.revision),
            ("log_position", self.log_position),
        ):
            _validate_nonnegative_safe_integer(f"terminal event {name}", value)
        if self.psk_history_index != self.log_position:
            raise ValueError("terminal event PSK history index must equal log_position")


@dataclass(frozen=True, slots=True)
class ImmediateTerminalEvent:
    reason: AdministrativeTerminationReason
    winner: Color
    loser: Color
    settlement_completed: bool
    stable_occupancy: Occupancy
    stable_stones: tuple[Stone, ...]
    psk_history_index: int
    revision: int
    log_position: int

    def __post_init__(self) -> None:
        if not isinstance(self.reason, AdministrativeTerminationReason):
            raise TypeError(
                "immediate terminal reason must be AdministrativeTerminationReason"
            )
        if not isinstance(self.winner, Color) or not isinstance(self.loser, Color):
            raise TypeError("immediate terminal players must be Color")
        if self.loser is not self.winner.opponent():
            raise ValueError(
                "immediate terminal loser must be the winner's opponent"
            )
        if type(self.settlement_completed) is not bool:
            raise TypeError("immediate terminal settlement_completed must be bool")
        if not isinstance(self.stable_occupancy, Occupancy):
            raise TypeError("immediate terminal stable_occupancy must be Occupancy")
        if not isinstance(self.stable_stones, tuple) or any(
            not isinstance(stone, Stone) for stone in self.stable_stones
        ):
            raise TypeError(
                "immediate terminal stable_stones must contain Stone values"
            )
        if self.stable_occupancy != _occupancy_from_stones(self.stable_stones):
            raise ValueError(
                "immediate terminal stable occupancy must match stable_stones"
            )
        for name, value in (
            ("psk_history_index", self.psk_history_index),
            ("revision", self.revision),
            ("log_position", self.log_position),
        ):
            _validate_positive_safe_integer(
                f"immediate terminal event {name}", value
            )
        if self.psk_history_index != self.log_position:
            raise ValueError(
                "immediate terminal PSK history index must equal log_position"
            )


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
    settlement_completed: bool
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
        if type(self.settlement_completed) is not bool:
            raise TypeError("settlement_completed must be bool")
        if self.terminal is not None and not isinstance(self.terminal, TerminalResult):
            raise TypeError("terminal must be TerminalResult or None")
        if self.board.size != self.config.board_size:
            raise ValueError("board size does not match oracle configuration")
        _validate_nonnegative_safe_integer(
            "atomic_action_count", self.atomic_action_count
        )
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
            _validate_nonnegative_safe_integer(name, value)

        if self.initial_quotas != self.config.quotas:
            raise ValueError("initial quotas must equal the configured quotas")
        _validate_quota_conservation(
            self.initial_quotas,
            self.remaining_quotas,
            self.used_quotas,
            self.expired_quotas,
        )

        for group in scan_mixed_groups(self.board, self.ledger):
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

        self._validate_special_state()

        if self.phase is Phase.COLLAPSE_PLAY:
            if self.actor is None or self.terminal is not None:
                raise ValueError("collapse play requires an actor and no terminal result")
            if self.settlement_completed:
                raise ValueError("collapse play cannot have completed settlement")
            self._validate_pre_settlement_facts()
        elif self.phase is Phase.ORDINARY_PLAY:
            if self.actor is None or self.terminal is not None:
                raise ValueError("ordinary play requires an actor and no terminal result")
            if not self.settlement_completed:
                raise ValueError("ordinary play requires completed settlement")
            settlement_trigger_action = self._settlement_trigger_action_number()
            if settlement_trigger_action is None:
                raise ValueError("completed settlement has no committed settlement trigger")
            expected_passes = self._post_settlement_pass_count(
                settlement_trigger_action
            )
            if self.consecutive_passes != expected_passes:
                raise ValueError(
                    "ordinary pass counter must match the committed action suffix"
                )
            if expected_passes > 1:
                raise ValueError("two ordinary passes must already have ended the game")
            self._validate_post_settlement_quotas()
        elif self.phase is Phase.TERMINAL:
            if self.actor is not None or self.terminal is None:
                raise ValueError("terminal state requires no actor and a terminal result")
            if len(self.psk_history) < 2 or self.psk_history[-2] != self.psk_history[-1]:
                raise ValueError(
                    "terminal PSK append must preserve unchanged occupancy"
                )
            if self.terminal.reason is TerminalReason.SCORE:
                if not self.settlement_completed:
                    raise ValueError("score terminal requires completed settlement")
                settlement_trigger_action = self._settlement_trigger_action_number()
                if (
                    settlement_trigger_action is None
                    or self.atomic_action_count < settlement_trigger_action + 2
                ):
                    raise ValueError(
                        "score terminal requires a settlement trigger and two ordinary passes"
                    )
                expected_passes = self._post_settlement_pass_count(
                    settlement_trigger_action
                )
                if self.consecutive_passes != 2 or expected_passes != 2:
                    raise ValueError(
                        "score terminal state requires exactly two consecutive passes "
                        "as committed ordinary passes"
                    )
                if len(self.psk_history) < 4 or any(
                    occupancy != self.psk_history[-1]
                    for occupancy in self.psk_history[-4:]
                ):
                    raise ValueError(
                        "score terminal requires two PASS appends and one terminal append"
                    )
                if self.terminal.score != score_chinese_area(self.board):
                    raise ValueError("terminal score must exactly match the stable board")
                self._validate_post_settlement_quotas()
            elif self.settlement_completed:
                settlement_trigger_action = self._settlement_trigger_action_number()
                if settlement_trigger_action is None:
                    raise ValueError(
                        "completed settlement has no committed settlement trigger"
                    )
                expected_passes = self._post_settlement_pass_count(
                    settlement_trigger_action
                )
                if self.consecutive_passes != expected_passes:
                    raise ValueError(
                        "administrative terminal pass counter must match the committed action suffix"
                    )
                if expected_passes > 1:
                    raise ValueError(
                        "administrative terminal cannot follow two ordinary passes"
                    )
                self._validate_post_settlement_quotas()
            else:
                self._validate_pre_settlement_facts()
        else:
            raise ValueError(f"unsupported phase {self.phase!r}")

        if self.phase is Phase.TERMINAL or self.settlement_completed:
            source_trigger_action = (
                self._settlement_trigger_action_number()
                if self.settlement_completed
                else None
            )
            self._validate_live_stone_sources(source_trigger_action)

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
        administrative_terminal_count = int(
            self.terminal is not None
            and self.terminal.reason is not TerminalReason.SCORE
        )
        expected_revision = self.atomic_action_count + administrative_terminal_count
        if self.revision != expected_revision:
            raise ValueError(
                "revision must equal accepted actions plus administrative terminals"
            )
        if self.log_position != emitted_stable_event_count:
            raise ValueError("log_position must equal emitted stable semantic events")
        expected_psk_length = 1 + emitted_stable_event_count
        if len(self.psk_history) != expected_psk_length:
            raise ValueError(
                "PSK history length must equal one empty seed plus atomic actions, "
                "settled ledger events, and stable terminal events"
            )

    def _action_has_live_stone_source(self, action_number: int) -> bool:
        return any(
            stone.origin_action_number == action_number
            for stone in self.board.stones
        )

    def _action_has_committed_point_source(self, action_number: int) -> bool:
        return self._action_has_live_stone_source(action_number) or any(
            event.origin_action_number == action_number for event in self.ledger
        )

    def _settlement_trigger_action_number(self) -> int | None:
        early_limit = min(self.atomic_action_count, self.config.threshold - 1)
        for action_number in range(2, early_limit + 1):
            if (
                not self._action_has_committed_point_source(action_number - 1)
                and not self._action_has_committed_point_source(action_number)
                and self.psk_history[action_number - 2]
                == self.psk_history[action_number - 1]
                == self.psk_history[action_number]
            ):
                return action_number
        if self.atomic_action_count >= self.config.threshold:
            return self.config.threshold
        return None

    def _post_settlement_pass_count(self, trigger_action: int) -> int:
        pass_count = 0
        for action_number in range(
            trigger_action + 1, self.atomic_action_count + 1
        ):
            history_index = action_number + self.settled_ledger_count
            if (
                self.psk_history[history_index - 1]
                == self.psk_history[history_index]
            ):
                pass_count += 1
                if pass_count > 2:
                    raise ValueError(
                        "post-settlement action history contains more than two passes"
                    )
            else:
                if pass_count == 2:
                    raise ValueError(
                        "post-settlement action follows an earlier scoring boundary"
                    )
                pass_count = 0

        if pass_count == 0 and self.atomic_action_count > trigger_action:
            if not self._action_has_live_stone_source(self.atomic_action_count):
                raise ValueError(
                    "post-settlement non-pass action must have a live stone source"
                )
        elif pass_count == 1 and self.atomic_action_count > trigger_action + 1:
            if not self._action_has_live_stone_source(
                self.atomic_action_count - 1
            ):
                raise ValueError(
                    "post-settlement pass suffix must follow a live stone source"
                )
        elif pass_count == 2 and self.atomic_action_count > trigger_action + 2:
            if not self._action_has_live_stone_source(
                self.atomic_action_count - 2
            ):
                raise ValueError(
                    "two-pass suffix must follow a live stone source"
                )
        return pass_count

    def _validate_live_stone_sources(self, trigger_action: int | None) -> None:
        for stone in self.board.stones:
            history_index = stone.origin_action_number
            if trigger_action is not None and stone.origin_action_number > trigger_action:
                history_index += self.settled_ledger_count
            before = self.psk_history[history_index - 1]
            after = self.psk_history[history_index]
            if stone.point in before.black or stone.point in before.white:
                raise ValueError(
                    "live stone source point must be empty before its origin action"
                )
            expected_points = after.black if stone.color is Color.BLACK else after.white
            if stone.point not in expected_points:
                raise ValueError(
                    "live stone source must match its origin action PSK entry"
                )
            if after in self.psk_history[:history_index]:
                raise ValueError(
                    "live stone source origin occupancy must be new under PSK"
                )
            for occupancy in self.psk_history[history_index:]:
                occupied_by_source_color = (
                    occupancy.black
                    if stone.color is Color.BLACK
                    else occupancy.white
                )
                if stone.point not in occupied_by_source_color:
                    raise ValueError(
                        "live stone source must survive continuously from its "
                        "origin action"
                    )

    def _validate_pre_settlement_facts(self) -> None:
        if (
            self.phase is Phase.TERMINAL
            and self._settlement_trigger_action_number() is not None
        ):
            raise ValueError(
                "a pre-settlement administrative terminal contains a committed "
                "settlement trigger"
            )
        if self.atomic_action_count >= self.config.threshold:
            raise ValueError("an exposed pre-settlement state must be before the threshold")
        if self.consecutive_passes > 1:
            raise ValueError("two collapse passes must already have triggered settlement")
        if self.expired_quotas != PlayerQuotas.zero():
            raise ValueError("quotas cannot expire before settlement")

    def _validate_special_state(self) -> None:
        board_by_source: dict[str, Stone] = {}
        special_source_ids: set[str] = set()
        for stone in self.board.stones:
            if stone.origin_action_number > self.atomic_action_count:
                raise ValueError("stone source action cannot exceed committed action count")
            if stone.origin_kind is ActionKind.NORMAL:
                if stone.special_event_id is not None:
                    raise ValueError("NORMAL stone source cannot link to an event")
            elif stone.origin_kind in _SPECIAL_KINDS:
                special_source_ids.add(stone.source_id)
            else:
                raise ValueError(
                    "board stones must originate from a point action"
                )
            board_by_source[stone.source_id] = stone

        event_by_source: dict[str, SpecialEvent] = {}
        used_immortal = {Color.BLACK: 0, Color.WHITE: 0}
        used_double = {Color.BLACK: 0, Color.WHITE: 0}
        used_eightway = {Color.BLACK: 0, Color.WHITE: 0}
        previous_order = -1
        previous_was_double = False
        seen_settled = False
        settled_count = 0
        for event in self.ledger:
            if event.kind not in _SPECIAL_KINDS:
                raise ValueError("ledger entries must use a special point action kind")
            if event.logical_order <= previous_order:
                raise ValueError("special ledger must be strictly ordered globally")
            if previous_was_double and event.logical_order == previous_order + 1:
                raise ValueError("Double starts require an intervening continuation")
            previous_order = event.logical_order
            previous_was_double = event.kind is ActionKind.DOUBLE_START
            if event.origin_action_number > self.atomic_action_count:
                raise ValueError("special event action cannot exceed committed action count")
            if event.kind is ActionKind.DOUBLE_START:
                if event.origin_action_number >= self.threshold:
                    raise ValueError(
                        "Double start action must be strictly before the threshold"
                    )
            elif event.origin_action_number > self.threshold:
                raise ValueError(
                    "Immortal and Eightway actions cannot occur after the threshold"
                )
            if event.source_point >= self.board.size * self.board.size:
                raise ValueError("special event source point is off board")
            if event.origin_action_number >= len(self.psk_history):
                raise ValueError("special event source action occupancy is missing")
            origin_occupancy = self.psk_history[event.origin_action_number]
            prior_occupancy = self.psk_history[event.origin_action_number - 1]
            if event.source_point in prior_occupancy.black + prior_occupancy.white:
                raise ValueError("special event source point was occupied before its action")
            owner_points = (
                origin_occupancy.black
                if event.owner is Color.BLACK
                else origin_occupancy.white
            )
            if event.source_point not in owner_points:
                raise ValueError("special event source identity disagrees with PSK history")

            if event.settlement_state is SettlementState.SETTLED:
                seen_settled = True
                settled_count += 1
            elif seen_settled:
                raise ValueError("settled ledger entries must form a suffix")

            if event.kind is ActionKind.IMMORTAL:
                used_immortal[event.owner] += 1
            elif event.kind is ActionKind.EIGHTWAY:
                used_eightway[event.owner] += 1
            else:
                used_double[event.owner] += 1

            source = board_by_source.get(event.source_stone_id)
            if event.stone_state is StoneState.ON_BOARD:
                if source is None:
                    raise ValueError("on-board special event source is missing")
                if (
                    source.point != event.source_point
                    or source.color is not event.owner
                    or source.origin_action_number != event.origin_action_number
                    or source.origin_kind is not event.kind
                    or source.special_event_id != event.event_id
                ):
                    raise ValueError("special event source linkage is inconsistent")
            elif source is not None:
                raise ValueError("captured special event source remains on board")

            event_by_source[event.source_stone_id] = event

        if self.settled_ledger_count != settled_count:
            raise ValueError("settled_ledger_count must exactly match settled entries")
        expected_settled_count = len(self.ledger) if self.settlement_completed else 0
        if settled_count != expected_settled_count:
            raise ValueError(
                "settled ledger count must match settlement_completed provenance"
            )

        for source_id in special_source_ids:
            stone = board_by_source[source_id]
            event = event_by_source.get(source_id)
            if event is None or event.event_id != stone.special_event_id:
                raise ValueError("special stone source must link to its ledger event")

        expected_used = PlayerQuotas(
            black=SpecialQuotas(
                immortal=used_immortal[Color.BLACK],
                double_start=used_double[Color.BLACK],
                eightway=used_eightway[Color.BLACK],
            ),
            white=SpecialQuotas(
                immortal=used_immortal[Color.WHITE],
                double_start=used_double[Color.WHITE],
                eightway=used_eightway[Color.WHITE],
            ),
        )
        if self.used_quotas != expected_used:
            raise ValueError(
                "used Double quotas, Immortal quotas, and Eightway quotas must "
                "exactly match the ledger"
            )

        if self.pending_double is None:
            if any(
                event.kind is ActionKind.DOUBLE_START
                and event.origin_action_number >= self.atomic_action_count
                for event in self.ledger
            ):
                raise ValueError("a Double start requires its committed continuation")
            return
        if self.settlement_completed:
            raise ValueError("pending Double requires pre-settlement provenance")
        if self.phase is Phase.COLLAPSE_PLAY:
            if self.actor is not self.pending_double.owner:
                raise ValueError("pending Double owner must remain the current actor")
        elif (
            self.phase is not Phase.TERMINAL
            or self.terminal is None
            or self.terminal.reason is TerminalReason.SCORE
        ):
            raise ValueError(
                "pending Double requires collapse play or administrative terminal"
            )
        linked = next(
            (
                event
                for event in self.ledger
                if event.event_id == self.pending_double.event_id
            ),
            None,
        )
        if linked is None or linked is not self.ledger[-1]:
            raise ValueError("pending Double must link to the newest ledger event")
        if (
            linked.kind is not ActionKind.DOUBLE_START
            or linked.owner is not self.pending_double.owner
            or linked.origin_action_number != self.pending_double.start_action_number
            or linked.stone_state is not StoneState.ON_BOARD
        ):
            raise ValueError("pending Double linkage is inconsistent")
        if self.atomic_action_count != self.pending_double.start_action_number:
            raise ValueError("pending Double must immediately follow its start action")
        if self.consecutive_passes != 0:
            raise ValueError("Double start must reset the pass streak")

    def _validate_post_settlement_quotas(self) -> None:
        if self.remaining_quotas != PlayerQuotas.zero():
            raise ValueError("all remaining quotas expire at settlement")

    @property
    def threshold(self) -> int:
        return self.config.threshold

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
class AdministrativeTerminationTransition:
    accepted: bool
    state: OracleState
    rejection_code: RejectionCode | None
    terminal_event: ImmediateTerminalEvent | None

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise TypeError("administrative transition accepted must be bool")
        if not isinstance(self.state, OracleState):
            raise TypeError("administrative transition state must be OracleState")
        if self.rejection_code is not None and not isinstance(
            self.rejection_code, RejectionCode
        ):
            raise TypeError(
                "administrative rejection_code must be RejectionCode or None"
            )
        if not self.accepted:
            expected_rejection = (
                RejectionCode.TERMINAL_STATE
                if self.state.phase is Phase.TERMINAL
                else RejectionCode.INVALID_LOSER
            )
            if (
                self.rejection_code is not expected_rejection
                or self.terminal_event is not None
            ):
                raise ValueError(
                    "rejected administrative transition violates terminal-first precedence"
                )
            return
        if self.rejection_code is not None:
            raise ValueError(
                "accepted administrative transition cannot contain a rejection"
            )
        if not isinstance(self.terminal_event, ImmediateTerminalEvent):
            raise ValueError(
                "accepted administrative transition requires an immediate "
                "terminal event"
            )
        terminal = self.state.terminal
        if self.state.phase is not Phase.TERMINAL or terminal is None:
            raise ValueError(
                "accepted administrative transition requires a terminal state"
            )
        expected_reason = TerminalReason(self.terminal_event.reason.value)
        if (
            terminal.reason is not expected_reason
            or terminal.winner is not self.terminal_event.winner
            or terminal.loser is not self.terminal_event.loser
            or terminal.score is not None
            or self.state.settlement_completed
            is not self.terminal_event.settlement_completed
            or self.state.board.occupancy != self.terminal_event.stable_occupancy
            or self.state.board.stones != self.terminal_event.stable_stones
            or self.terminal_event.psk_history_index
            != len(self.state.psk_history) - 1
            or self.terminal_event.revision != self.state.revision
            or self.terminal_event.log_position != self.state.log_position
        ):
            raise ValueError(
                "immediate terminal event must exactly match the committed state"
            )


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
        if not isinstance(self.action, DecodedAction):
            raise TypeError("transition action must be DecodedAction")
        if not isinstance(self.candidate_actor, Color):
            raise TypeError("transition candidate_actor must be Color")
        if not isinstance(self.state, OracleState):
            raise TypeError("transition state must be OracleState")
        canonical_action = decode_action_v1(
            {
                "schemaVersion": self.action.schema_version,
                "actionId": self.action.action_id,
                "kind": self.action.kind.value,
            },
            self.state.config.board_size,
        )
        if self.action != canonical_action:
            raise ValueError(
                "transition action must match the selected board-size decoding"
            )
        if self.rejection_code is not None and not isinstance(
            self.rejection_code, RejectionCode
        ):
            raise TypeError("transition rejection_code must be RejectionCode or None")
        if self.accepted:
            if self.rejection_code is not None or not isinstance(
                self.atomic_event, AtomicActionEvent
            ):
                raise ValueError("accepted transition requires an event and no rejection")
            if (
                self.atomic_event.action != self.action
                or self.atomic_event.actor is not self.candidate_actor
                or self.atomic_event.action_number != self.state.atomic_action_count
                or self.atomic_event.revision != self.state.revision
            ):
                raise ValueError(
                    "accepted transition action and actor must match its atomic event"
                )
            self._validate_settlement_commit()
            if self.terminal_event is None:
                if self.state.phase is Phase.TERMINAL:
                    raise ValueError("terminal accepted transition requires terminal_event")
            else:
                if not isinstance(self.terminal_event, TerminalEvent):
                    raise TypeError("transition terminal_event must be TerminalEvent or None")
                terminal = self.state.terminal
                if self.state.phase is not Phase.TERMINAL or terminal is None:
                    raise ValueError("terminal_event requires a terminal next state")
                if (
                    self.terminal_event.reason is not terminal.reason
                    or self.terminal_event.winner is not terminal.winner
                    or self.terminal_event.loser is not terminal.loser
                    or self.terminal_event.score != terminal.score
                    or self.terminal_event.stable_occupancy != self.state.board.occupancy
                    or self.terminal_event.stable_stones != self.state.board.stones
                    or self.terminal_event.psk_history_index
                    != len(self.state.psk_history) - 1
                    or self.terminal_event.revision != self.state.revision
                    or self.terminal_event.log_position != self.state.log_position
                ):
                    raise ValueError(
                        "terminal_event must exactly match the committed terminal state"
                    )
        elif (
            self.rejection_code is None
            or self.atomic_event is not None
            or self.settlement is not None
            or self.terminal_event is not None
        ):
            raise ValueError("rejected transition must have exactly one rejection code")

    def _validate_settlement_commit(self) -> None:
        atomic_event = self.atomic_event
        if not isinstance(atomic_event, AtomicActionEvent):
            raise AssertionError("accepted transition lost its atomic event")
        if not (0 < atomic_event.psk_history_index < len(self.state.psk_history)) or (
            self.state.psk_history[atomic_event.psk_history_index]
            != atomic_event.stable_occupancy
        ):
            raise ValueError(
                "atomic event stable occupancy must match its committed PSK entry"
            )

        prior_occupancy = self.state.psk_history[
            atomic_event.psk_history_index - 1
        ]
        expected_black = set(prior_occupancy.black)
        expected_white = set(prior_occupancy.white)
        for stone in atomic_event.captured_stones:
            prior_points = expected_black if stone.color is Color.BLACK else expected_white
            if stone.point not in prior_points:
                raise ValueError(
                    "atomic captured stones must exist in the immediately prior occupancy"
                )
            prior_points.remove(stone.point)
        if atomic_event.action.kind is not ActionKind.PASS:
            placed_stone = atomic_event.placed_stone
            if placed_stone is None:
                raise AssertionError("point action lost its placed source")
            if placed_stone.point in expected_black or placed_stone.point in expected_white:
                raise ValueError("atomic placed point must be empty in the prior occupancy")
            own_points = (
                expected_black if placed_stone.color is Color.BLACK else expected_white
            )
            own_points.add(placed_stone.point)
        expected_atomic_occupancy = Occupancy(
            black=tuple(sorted(expected_black)),
            white=tuple(sorted(expected_white)),
        )
        if atomic_event.stable_occupancy != expected_atomic_occupancy:
            raise ValueError(
                "atomic placement and captures must yield the declared stable occupancy"
            )

        if self.settlement is not None and not isinstance(
            self.settlement, SettlementResult
        ):
            raise TypeError("transition settlement must be SettlementResult or None")
        if self.terminal_event is not None:
            if not isinstance(self.terminal_event, TerminalEvent):
                raise TypeError("transition terminal_event must be TerminalEvent or None")
            if self.settlement is not None:
                raise ValueError("terminal transition cannot also contain settlement")
            if (
                atomic_event.action.kind is not ActionKind.PASS
                or self.state.phase is not Phase.TERMINAL
                or self.state.actor is not None
                or self.state.consecutive_passes != 2
                or atomic_event.log_position + 1 != self.state.log_position
                or atomic_event.psk_history_index + 1
                != self.terminal_event.psk_history_index
                or self.terminal_event.log_position != self.state.log_position
                or atomic_event.stable_occupancy != self.state.board.occupancy
                or atomic_event.stable_stones != self.state.board.stones
            ):
                raise ValueError(
                    "score terminal must exactly follow the second ordinary PASS"
                )
            return

        settlement_step_count = self.state.log_position - atomic_event.log_position
        if settlement_step_count < 0:
            raise ValueError("accepted state log_position cannot precede its atomic event")
        if self.settlement is None:
            if settlement_step_count:
                raise ValueError(
                    "post-settlement state requires its complete settlement trace"
                )
            if self.state.phase is Phase.TERMINAL:
                raise ValueError("terminal accepted transition requires terminal_event")
            if atomic_event.action.kind is ActionKind.DOUBLE_START:
                valid_control = (
                    self.state.actor is self.candidate_actor
                    and self.state.pending_double is not None
                    and self.state.consecutive_passes == 0
                )
            else:
                expected_passes = (
                    1 if atomic_event.action.kind is ActionKind.PASS else 0
                )
                valid_control = (
                    self.state.actor is self.candidate_actor.opponent()
                    and self.state.pending_double is None
                    and self.state.consecutive_passes == expected_passes
                )
            if not valid_control:
                raise ValueError(
                    "accepted atomic action must commit the exact actor and pass control state"
                )
            if (
                atomic_event.stable_occupancy != self.state.board.occupancy
                or atomic_event.stable_stones != self.state.board.stones
            ):
                raise ValueError(
                    "non-settlement atomic event must match the committed stable board"
                )
            return

        if (
            self.state.phase is not Phase.ORDINARY_PLAY
            or self.state.actor is not self.candidate_actor.opponent()
            or self.state.pending_double is not None
            or self.state.consecutive_passes != 0
        ):
            raise ValueError(
                "settlement exit must preserve handoff actor and reset pass control"
            )
        if self.settlement.ledger_entry_count != settlement_step_count:
            raise ValueError("settlement step count must match the committed log delta")
        if (
            self.state.settled_ledger_count != settlement_step_count
            or len(self.state.ledger) != settlement_step_count
        ):
            raise ValueError(
                "settlement trace must cover the complete committed special ledger"
            )
        expected_reason = (
            SettlementReason.THRESHOLD
            if atomic_event.action_number == self.state.threshold
            else SettlementReason.PRE_THRESHOLD_TWO_PASSES
        )
        if self.settlement.reason is not expected_reason:
            raise ValueError("settlement reason must match the triggering action")
        if expected_reason is SettlementReason.PRE_THRESHOLD_TWO_PASSES and (
            atomic_event.action.kind is not ActionKind.PASS
            or atomic_event.action_number >= self.state.threshold
        ):
            raise ValueError(
                "pre-threshold settlement requires a PASS before the threshold"
            )

        entry_board = Board.from_stones(
            self.state.board.size,
            atomic_event.stable_stones,
        )
        entry_sources = {stone.source_id: stone for stone in entry_board.stones}
        replay_ledger: list[SpecialEvent] = []
        for final_event in self.state.ledger:
            source = entry_sources.get(final_event.source_stone_id)
            if source is None:
                replay_ledger.append(
                    replace(
                        final_event,
                        ability_state=(
                            AbilityState.CONSUMED
                            if final_event.kind is ActionKind.DOUBLE_START
                            else AbilityState.INACTIVE
                        ),
                        stone_state=StoneState.CAPTURED,
                        settlement_state=SettlementState.PENDING,
                        tombstone=True,
                    )
                )
            else:
                if (
                    source.point != final_event.source_point
                    or source.color is not final_event.owner
                    or source.origin_kind is not final_event.kind
                    or source.special_event_id != final_event.event_id
                ):
                    raise ValueError(
                        "settlement entry source must match its immutable ledger event"
                    )
                replay_ledger.append(
                    replace(
                        final_event,
                        ability_state=(
                            AbilityState.CONSUMED
                            if final_event.kind is ActionKind.DOUBLE_START
                            else AbilityState.ARMED
                        ),
                        stone_state=StoneState.ON_BOARD,
                        settlement_state=SettlementState.PENDING,
                        tombstone=final_event.kind is ActionKind.DOUBLE_START,
                    )
                )

        replay_board = entry_board
        for step_index, ledger_index in enumerate(
            range(len(replay_ledger) - 1, -1, -1)
        ):
            event = replay_ledger[ledger_index]
            step = self.settlement.steps[step_index]
            (
                _settled_event,
                replay_board,
                updated_ledger,
                ability_deactivated,
                removal_batches,
            ) = _pop_settlement_event(
                replay_board,
                tuple(replay_ledger),
                ledger_index,
            )
            replay_ledger = list(updated_ledger)
            expected_position = atomic_event.log_position + step_index + 1
            if (
                step.event_id != event.event_id
                or step.logical_order != event.logical_order
                or step.owner is not event.owner
                or step.kind is not event.kind
                or step.ability_deactivated is not ability_deactivated
                or step.no_op is not (
                    not ability_deactivated and not removal_batches
                )
                or step.removal_batches != removal_batches
                or step.stable_occupancy != replay_board.occupancy
                or step.stable_stones != replay_board.stones
                or step.revision != self.state.revision
                or step.log_position != expected_position
                or step.psk_history_index != expected_position
                or step.psk_history_index >= len(self.state.psk_history)
                or self.state.psk_history[step.psk_history_index]
                != step.stable_occupancy
            ):
                raise ValueError(
                    "settlement step must exactly replay deactivation and deterministic closure"
                )

        if (
            replay_board != self.state.board
            or tuple(replay_ledger) != self.state.ledger
        ):
            raise ValueError(
                "settlement trace final board and ledger must match the committed state"
            )


_POINT_KIND_RANGES = (
    (0, 360, ActionKind.NORMAL),
    (361, 721, ActionKind.IMMORTAL),
    (722, 1082, ActionKind.DOUBLE_START),
    (1083, 1443, ActionKind.EIGHTWAY),
)


def _is_live_armed_event(event: SpecialEvent) -> bool:
    return (
        event.kind in _ARMED_ABILITY_KINDS
        and event.ability_state is AbilityState.ARMED
        and event.stone_state is StoneState.ON_BOARD
        and event.settlement_state is SettlementState.PENDING
        and not event.tombstone
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
        settlement_completed=False,
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


def scan_mixed_groups(
    board: Board,
    ledger: Iterable[SpecialEvent] | None = None,
    *,
    events: Iterable[SpecialEvent] | None = None,
) -> tuple[Group, ...]:
    """Rebuild deterministic mixed N4/N8 topology and protection directly."""

    if not isinstance(board, Board):
        raise TypeError("board must be Board")
    if ledger is not None and events is not None:
        raise TypeError("provide either ledger or events to group scan, not both")
    source_events = events if events is not None else ledger
    if source_events is None:
        ledger_events: tuple[SpecialEvent, ...] = ()
    else:
        if isinstance(source_events, (str, bytes)):
            raise TypeError("group-scan ledger must contain SpecialEvent values")
        ledger_events = tuple(source_events)
        if any(not isinstance(event, SpecialEvent) for event in ledger_events):
            raise TypeError("group-scan ledger must contain SpecialEvent values")

    stone_by_point = {stone.point: stone for stone in board.stones}
    live_immortal_points: set[int] = set()
    live_eightway_points: set[int] = set()
    for event in ledger_events:
        if not _is_live_armed_event(event):
            continue
        source = stone_by_point.get(event.source_point)
        if (
            source is None
            or source.source_id != event.source_stone_id
            or source.color is not event.owner
            or source.origin_kind is not event.kind
            or source.special_event_id != event.event_id
        ):
            continue
        if event.kind is ActionKind.IMMORTAL:
            live_immortal_points.add(source.point)
        else:
            live_eightway_points.add(source.point)

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

            orthogonal_neighbors = _n4_neighbors(board.size, point)
            if point in live_eightway_points:
                interface = _n8_neighbors(board.size, point)
                connection_neighbors = interface
            elif live_eightway_points:
                interface = orthogonal_neighbors
                connection_neighbors = _n8_neighbors(board.size, point)
            else:
                interface = orthogonal_neighbors
                connection_neighbors = orthogonal_neighbors
            liberties.update(
                neighbor for neighbor in interface if neighbor not in occupied
            )

            for neighbor in connection_neighbors:
                if neighbor not in own or neighbor in visited:
                    continue
                if (
                    neighbor in orthogonal_neighbors
                    or point in live_eightway_points
                    or neighbor in live_eightway_points
                ):
                    visited.add(neighbor)
                    stack.append(neighbor)

        ordered_stones = tuple(sorted(stones))
        immortal_anchor_points = tuple(
            point for point in ordered_stones if point in live_immortal_points
        )
        eightway_anchor_points = tuple(
            point for point in ordered_stones if point in live_eightway_points
        )
        groups.append(
            Group(
                color=color,
                stones=ordered_stones,
                liberties=tuple(sorted(liberties)),
                source_stones=tuple(
                    stone_by_point[point] for point in ordered_stones
                ),
                protected=bool(immortal_anchor_points),
                immortal_anchor_points=immortal_anchor_points,
                eightway_anchor_points=eightway_anchor_points,
            )
        )
    return tuple(groups)


def scan_n4_groups(
    board: Board,
    ledger: Iterable[SpecialEvent] | None = None,
    *,
    events: Iterable[SpecialEvent] | None = None,
) -> tuple[Group, ...]:
    """Compatibility name for the frozen mixed-topology group rebuild.

    With no live Eightway source this is exactly the historical N4 scan.
    """

    return scan_mixed_groups(board, ledger, events=events)


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


def apply_administrative_termination(
    state: OracleState,
    loser: Color | str,
    reason: AdministrativeTerminationReason,
) -> AdministrativeTerminationTransition:
    """Commit resignation or game timeout at an exposed stable boundary."""

    if not isinstance(state, OracleState):
        raise TypeError("state must be OracleState")
    if not isinstance(reason, AdministrativeTerminationReason):
        raise TypeError("reason must be AdministrativeTerminationReason")

    if state.phase is Phase.TERMINAL:
        return AdministrativeTerminationTransition(
            accepted=False,
            state=state,
            rejection_code=RejectionCode.TERMINAL_STATE,
            terminal_event=None,
        )

    if isinstance(loser, Color):
        resolved_loser = loser
    elif type(loser) is str:
        try:
            resolved_loser = Color(loser)
        except ValueError:
            return AdministrativeTerminationTransition(
                accepted=False,
                state=state,
                rejection_code=RejectionCode.INVALID_LOSER,
                terminal_event=None,
            )
    else:
        return AdministrativeTerminationTransition(
            accepted=False,
            state=state,
            rejection_code=RejectionCode.INVALID_LOSER,
            terminal_event=None,
        )

    winner = resolved_loser.opponent()
    terminal_reason = TerminalReason(reason.value)
    next_revision = state.revision + 1
    next_log_position = state.log_position + 1
    history = state.psk_history + (state.board.occupancy,)
    terminal = TerminalResult(
        reason=terminal_reason,
        winner=winner,
        loser=resolved_loser,
        score=None,
    )
    terminal_event = ImmediateTerminalEvent(
        reason=reason,
        winner=winner,
        loser=resolved_loser,
        settlement_completed=state.settlement_completed,
        stable_occupancy=state.board.occupancy,
        stable_stones=state.board.stones,
        psk_history_index=len(history) - 1,
        revision=next_revision,
        log_position=next_log_position,
    )
    next_state = replace(
        state,
        actor=None,
        phase=Phase.TERMINAL,
        settlement_completed=state.settlement_completed,
        stable_terminal_event_count=state.stable_terminal_event_count + 1,
        psk_history=history,
        revision=next_revision,
        log_position=next_log_position,
        terminal=terminal,
    )
    return AdministrativeTerminationTransition(
        accepted=True,
        state=next_state,
        rejection_code=None,
        terminal_event=terminal_event,
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
    if state.pending_double is not None and action.kind not in (
        ActionKind.NORMAL,
        ActionKind.PASS,
    ):
        return _rejected(
            state,
            actor,
            action,
            RejectionCode.DOUBLE_CONTINUATION_KIND_FORBIDDEN,
        )

    if action.kind in _SPECIAL_KINDS:
        if (
            action.kind is ActionKind.DOUBLE_START
            and state.atomic_action_count + 2 > state.threshold
        ):
            return _rejected(state, actor, action, RejectionCode.DOUBLE_THRESHOLD)
        if state.remaining_quotas.for_player(actor).for_kind(action.kind) == 0:
            return _rejected(state, actor, action, RejectionCode.QUOTA_EXHAUSTED)

    if action.kind is ActionKind.PASS:
        return _commit_pass(state, actor, action)

    prepared = _prepare_placement(state, actor, action)
    if isinstance(prepared, RejectionCode):
        return _rejected(state, actor, action, prepared)
    board_after, captured_stones = prepared
    if action.kind is ActionKind.NORMAL:
        return _commit_normal(
            state,
            actor,
            action,
            board_after,
            captured_stones,
        )
    if action.kind is ActionKind.DOUBLE_START:
        return _commit_double_start(
            state,
            actor,
            action,
            board_after,
            captured_stones,
        )
    if action.kind in _ARMED_ABILITY_KINDS:
        return _commit_armed_special(
            state,
            actor,
            action,
            board_after,
            captured_stones,
        )
    raise AssertionError(f"unhandled action kind {action.kind.value}")


def _prepare_placement(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
) -> tuple[Board, tuple[Stone, ...]] | RejectionCode:
    if action.kind is ActionKind.PASS:
        raise AssertionError("PASS does not use the placement transaction")
    point = _board_index(state.board.size, action)
    if state.board.color_at(point) is not None:
        return RejectionCode.POINT_OCCUPIED
    action_number = state.atomic_action_count + 1
    origin_kind = action.kind
    special_event_id = (
        f"special-{action_number}" if origin_kind in _SPECIAL_KINDS else None
    )
    tentative_ledger = state.ledger
    if origin_kind in _ARMED_ABILITY_KINDS:
        tentative_ledger += (
            SpecialEvent(
                event_id=f"special-{action_number}",
                logical_order=action_number - 1,
                owner=actor,
                kind=origin_kind,
                source_point=point,
                source_stone_id=f"stone-{action_number}",
                ability_state=AbilityState.ARMED,
                stone_state=StoneState.ON_BOARD,
                settlement_state=SettlementState.PENDING,
                tombstone=False,
            ),
        )
    board_after, captured_stones, own_survives = _simulate_placement(
        state.board,
        tentative_ledger,
        actor,
        point,
        origin_action_number=action_number,
        origin_kind=origin_kind,
        special_event_id=special_event_id,
    )
    if not own_survives:
        return RejectionCode.SUICIDE
    if board_after.occupancy in state.psk_history:
        return RejectionCode.POSITIONAL_SUPERKO
    return board_after, captured_stones


def _build_point_action_event(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
    board_after: Board,
    captured_stones: tuple[Stone, ...],
) -> tuple[AtomicActionEvent, tuple[Occupancy, ...]]:
    action_number = state.atomic_action_count + 1
    history = state.psk_history + (board_after.occupancy,)
    placed_stone = board_after.stone_at(_board_index(board_after.size, action))
    if placed_stone is None:
        raise AssertionError("accepted placement source is absent from the stable board")
    return (
        AtomicActionEvent(
            action_number=action_number,
            actor=actor,
            action=action,
            captured=_occupancy_from_stones(captured_stones),
            captured_stones=captured_stones,
            placed_stone=placed_stone,
            stable_occupancy=board_after.occupancy,
            stable_stones=board_after.stones,
            psk_history_index=len(history) - 1,
            revision=state.revision + 1,
            log_position=state.log_position + 1,
        ),
        history,
    )


def _commit_armed_special(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
    board_after: Board,
    captured_stones: tuple[Stone, ...],
) -> Transition:
    kind = action.kind
    if kind not in _ARMED_ABILITY_KINDS:
        raise AssertionError("armed special commit requires Immortal or Eightway")
    atomic_event, history = _build_point_action_event(
        state,
        actor,
        action,
        board_after,
        captured_stones,
    )
    action_number = atomic_event.action_number
    placed_stone = atomic_event.placed_stone
    if placed_stone is None:
        raise AssertionError("point action event must contain its placed source")
    event_id = f"special-{action_number}"
    if placed_stone.origin_kind is not kind or placed_stone.special_event_id != event_id:
        raise AssertionError("accepted armed special source has inconsistent linkage")

    ledger = _ledger_after_captures(state.ledger, captured_stones) + (
        SpecialEvent(
            event_id=event_id,
            logical_order=action_number - 1,
            owner=actor,
            kind=kind,
            source_point=placed_stone.point,
            source_stone_id=placed_stone.source_id,
            ability_state=AbilityState.ARMED,
            stone_state=StoneState.ON_BOARD,
            settlement_state=SettlementState.PENDING,
            tombstone=False,
        ),
    )
    remaining_quotas = _replace_special_quota(
        state.remaining_quotas,
        actor,
        kind,
        state.remaining_quotas.for_player(actor).for_kind(kind) - 1,
    )
    used_quotas = _replace_special_quota(
        state.used_quotas,
        actor,
        kind,
        state.used_quotas.for_player(actor).for_kind(kind) + 1,
    )
    settlement_reason = _settlement_reason(
        state.phase, action_number, state.threshold, consecutive_passes=0
    )
    if settlement_reason is not None:
        next_state, settlement = _settle_after_action(
            state,
            board_after=board_after,
            handoff_actor=actor.opponent(),
            action_number=action_number,
            ledger=ledger,
            remaining_quotas=remaining_quotas,
            used_quotas=used_quotas,
            history_after_action=history,
            next_revision=atomic_event.revision,
            action_log_position=atomic_event.log_position,
            reason=settlement_reason,
        )
    else:
        next_state = OracleState(
            config=state.config,
            board=board_after,
            actor=actor.opponent(),
            phase=state.phase,
            atomic_action_count=action_number,
            consecutive_passes=0,
            initial_quotas=state.initial_quotas,
            remaining_quotas=remaining_quotas,
            used_quotas=used_quotas,
            expired_quotas=state.expired_quotas,
            ledger=ledger,
            pending_double=None,
            settlement_completed=state.settlement_completed,
            settled_ledger_count=state.settled_ledger_count,
            stable_terminal_event_count=state.stable_terminal_event_count,
            psk_history=history,
            revision=atomic_event.revision,
            log_position=atomic_event.log_position,
        )
        settlement = None
    return Transition(
        accepted=True,
        action=action,
        candidate_actor=actor,
        state=next_state,
        rejection_code=None,
        atomic_event=atomic_event,
        settlement=settlement,
        terminal_event=None,
    )


def _commit_double_start(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
    board_after: Board,
    captured_stones: tuple[Stone, ...],
) -> Transition:
    atomic_event, history = _build_point_action_event(
        state,
        actor,
        action,
        board_after,
        captured_stones,
    )
    action_number = atomic_event.action_number
    placed_stone = atomic_event.placed_stone
    if placed_stone is None:
        raise AssertionError("point action event must contain its placed source")
    event_id = f"special-{action_number}"
    if (
        placed_stone.origin_kind is not ActionKind.DOUBLE_START
        or placed_stone.special_event_id != event_id
    ):
        raise AssertionError("accepted Double source has inconsistent event linkage")

    ledger = _ledger_after_captures(state.ledger, captured_stones) + (
        SpecialEvent(
            event_id=event_id,
            logical_order=action_number - 1,
            owner=actor,
            kind=ActionKind.DOUBLE_START,
            source_point=placed_stone.point,
            source_stone_id=placed_stone.source_id,
            ability_state=AbilityState.CONSUMED,
            stone_state=StoneState.ON_BOARD,
            settlement_state=SettlementState.PENDING,
            tombstone=True,
        ),
    )
    remaining_quotas = _replace_double_quota(
        state.remaining_quotas,
        actor,
        state.remaining_quotas.for_player(actor).double_start - 1,
    )
    used_quotas = _replace_double_quota(
        state.used_quotas,
        actor,
        state.used_quotas.for_player(actor).double_start + 1,
    )
    next_state = OracleState(
        config=state.config,
        board=board_after,
        actor=actor,
        phase=state.phase,
        atomic_action_count=action_number,
        consecutive_passes=0,
        initial_quotas=state.initial_quotas,
        remaining_quotas=remaining_quotas,
        used_quotas=used_quotas,
        expired_quotas=state.expired_quotas,
        ledger=ledger,
        pending_double=PendingDouble(
            owner=actor,
            event_id=event_id,
            start_action_number=action_number,
        ),
        settlement_completed=False,
        settled_ledger_count=state.settled_ledger_count,
        stable_terminal_event_count=state.stable_terminal_event_count,
        psk_history=history,
        revision=atomic_event.revision,
        log_position=atomic_event.log_position,
    )
    return Transition(
        accepted=True,
        action=action,
        candidate_actor=actor,
        state=next_state,
        rejection_code=None,
        atomic_event=atomic_event,
        settlement=None,
        terminal_event=None,
    )


def _commit_normal(
    state: OracleState,
    actor: Color,
    action: DecodedAction,
    board_after: Board,
    captured_stones: tuple[Stone, ...],
) -> Transition:
    atomic_event, history = _build_point_action_event(
        state,
        actor,
        action,
        board_after,
        captured_stones,
    )
    action_number = atomic_event.action_number
    ledger = _ledger_after_captures(state.ledger, captured_stones)
    settlement_reason = _settlement_reason(
        state.phase, action_number, state.threshold, consecutive_passes=0
    )
    if settlement_reason is not None:
        next_state, settlement = _settle_after_action(
            state,
            board_after=board_after,
            handoff_actor=actor.opponent(),
            action_number=action_number,
            ledger=ledger,
            remaining_quotas=state.remaining_quotas,
            used_quotas=state.used_quotas,
            history_after_action=history,
            next_revision=atomic_event.revision,
            action_log_position=atomic_event.log_position,
            reason=settlement_reason,
        )
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
            ledger=ledger,
            pending_double=None,
            settlement_completed=state.settlement_completed,
            settled_ledger_count=state.settled_ledger_count,
            stable_terminal_event_count=state.stable_terminal_event_count,
            psk_history=history,
            revision=atomic_event.revision,
            log_position=atomic_event.log_position,
        )
        settlement = None
    return Transition(
        accepted=True,
        action=action,
        candidate_actor=actor,
        state=next_state,
        rejection_code=None,
        atomic_event=atomic_event,
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
        next_state, settlement = _settle_after_action(
            state,
            board_after=state.board,
            handoff_actor=actor.opponent(),
            action_number=action_number,
            ledger=state.ledger,
            remaining_quotas=state.remaining_quotas,
            used_quotas=state.used_quotas,
            history_after_action=history_after_action,
            next_revision=next_revision,
            action_log_position=action_log_position,
            reason=settlement_reason,
        )
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
            pending_double=None,
            settlement_completed=True,
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
        pending_double=None,
        settlement_completed=state.settlement_completed,
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


def _pop_settlement_event(
    board: Board,
    ledger: tuple[SpecialEvent, ...],
    ledger_index: int,
) -> tuple[
    SpecialEvent,
    Board,
    tuple[SpecialEvent, ...],
    bool,
    tuple[Occupancy, ...],
]:
    event = ledger[ledger_index]
    if event.settlement_state is not SettlementState.PENDING:
        raise AssertionError("settlement encountered an already-settled event")
    ability_deactivated = _is_live_armed_event(event)
    settled_event = replace(
        event,
        ability_state=AbilityState.INACTIVE,
        settlement_state=SettlementState.SETTLED,
        tombstone=True,
    )
    settled_ledger = list(ledger)
    settled_ledger[ledger_index] = settled_event
    settled_board, updated_ledger, removal_batches = _run_settlement_closure(
        board,
        tuple(settled_ledger),
    )
    return (
        settled_event,
        settled_board,
        updated_ledger,
        ability_deactivated,
        removal_batches,
    )


def _settle_after_action(
    state: OracleState,
    *,
    board_after: Board,
    handoff_actor: Color,
    action_number: int,
    ledger: tuple[SpecialEvent, ...],
    remaining_quotas: PlayerQuotas,
    used_quotas: PlayerQuotas,
    history_after_action: tuple[Occupancy, ...],
    next_revision: int,
    action_log_position: int,
    reason: SettlementReason,
) -> tuple[OracleState, SettlementResult]:
    settled_ledger = list(ledger)
    settled_count = len(settled_ledger)
    current_board = board_after
    history = list(history_after_action)
    steps: list[SettlementStepEvent] = []
    for index in range(settled_count - 1, -1, -1):
        (
            settled_event,
            current_board,
            updated_ledger,
            ability_deactivated,
            removal_batches,
        ) = _pop_settlement_event(
            current_board,
            tuple(settled_ledger),
            index,
        )
        settled_ledger = list(updated_ledger)
        step_offset = len(steps) + 1
        history.append(current_board.occupancy)
        steps.append(
            SettlementStepEvent(
                event_id=settled_event.event_id,
                logical_order=settled_event.logical_order,
                owner=settled_event.owner,
                kind=settled_event.kind,
                ability_deactivated=ability_deactivated,
                no_op=not ability_deactivated and not removal_batches,
                stable_occupancy=current_board.occupancy,
                stable_stones=current_board.stones,
                psk_history_index=len(history) - 1,
                revision=next_revision,
                log_position=action_log_position + step_offset,
                removal_batches=removal_batches,
            )
        )
    log_position = action_log_position + settled_count

    next_state = OracleState(
        config=state.config,
        board=current_board,
        actor=handoff_actor,
        phase=Phase.ORDINARY_PLAY,
        atomic_action_count=action_number,
        consecutive_passes=0,
        initial_quotas=state.initial_quotas,
        remaining_quotas=PlayerQuotas.zero(),
        used_quotas=used_quotas,
        expired_quotas=_add_player_quotas(
            state.expired_quotas,
            remaining_quotas,
        ),
        ledger=tuple(settled_ledger),
        pending_double=None,
        settlement_completed=True,
        settled_ledger_count=state.settled_ledger_count + settled_count,
        stable_terminal_event_count=state.stable_terminal_event_count,
        psk_history=tuple(history),
        revision=next_revision,
        log_position=log_position,
    )
    return next_state, SettlementResult(
        reason=reason,
        ledger_entry_count=settled_count,
        psk_appends=settled_count,
        steps=tuple(steps),
    )


def _run_settlement_closure(
    board: Board,
    ledger: tuple[SpecialEvent, ...],
) -> tuple[Board, tuple[SpecialEvent, ...], tuple[Occupancy, ...]]:
    current_board = board
    current_ledger = ledger
    removal_batches: list[Occupancy] = []
    while True:
        groups = scan_mixed_groups(current_board, current_ledger)
        doomed = {
            point
            for group in groups
            if not group.liberties and not group.protected
            for point in group.stones
        }
        if not doomed:
            break
        removed_stones = tuple(
            stone for stone in current_board.stones if stone.point in doomed
        )
        removal_batches.append(_occupancy_from_stones(removed_stones))
        current_board = Board.from_stones(
            current_board.size,
            (stone for stone in current_board.stones if stone.point not in doomed),
        )
        current_ledger = _ledger_after_captures(current_ledger, removed_stones)

    # The frozen algorithm requires a final full rebuild even after the fixed
    # point is known; the deterministic scan has no cached topology to retain.
    scan_mixed_groups(current_board, current_ledger)
    return current_board, current_ledger, tuple(removal_batches)


def _simulate_placement(
    board: Board,
    ledger: tuple[SpecialEvent, ...],
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

    first_scan = scan_mixed_groups(tentative, ledger)
    opponent = actor.opponent()
    doomed: set[int] = set()
    for group in first_scan:
        if group.color is opponent and not group.liberties and not group.protected:
            doomed.update(group.stones)

    captured_stones = tuple(
        stone for stone in tentative.stones if stone.point in doomed
    )
    after_capture = Board.from_stones(
        board.size,
        (stone for stone in tentative.stones if stone.point not in doomed),
    )

    second_scan = scan_mixed_groups(after_capture, ledger)
    own_group = next(
        (
            group
            for group in second_scan
            if group.color is actor and point in group.stones
        ),
        None,
    )
    own_survives = own_group is not None and bool(
        own_group.liberties or own_group.protected
    )
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


def _ledger_after_captures(
    ledger: tuple[SpecialEvent, ...],
    captured_stones: tuple[Stone, ...],
) -> tuple[SpecialEvent, ...]:
    captured_source_ids = {
        stone.source_id
        for stone in captured_stones
        if stone.special_event_id is not None
    }
    if not captured_source_ids:
        return ledger
    matched: set[str] = set()
    updated: list[SpecialEvent] = []
    for event in ledger:
        if event.source_stone_id in captured_source_ids:
            matched.add(event.source_stone_id)
            if event.kind in _ARMED_ABILITY_KINDS:
                updated.append(
                    replace(
                        event,
                        ability_state=AbilityState.INACTIVE,
                        stone_state=StoneState.CAPTURED,
                        tombstone=True,
                    )
                )
            else:
                updated.append(replace(event, stone_state=StoneState.CAPTURED))
        else:
            updated.append(event)
    if matched != captured_source_ids:
        raise AssertionError("captured special source is absent from the ledger")
    return tuple(updated)


def _replace_double_quota(
    quotas: PlayerQuotas,
    player: Color,
    value: int,
) -> PlayerQuotas:
    return _replace_special_quota(
        quotas,
        player,
        ActionKind.DOUBLE_START,
        value,
    )


def _replace_special_quota(
    quotas: PlayerQuotas,
    player: Color,
    kind: ActionKind,
    value: int,
) -> PlayerQuotas:
    current = quotas.for_player(player)
    if kind is ActionKind.IMMORTAL:
        updated = replace(current, immortal=value)
    elif kind is ActionKind.DOUBLE_START:
        updated = replace(current, double_start=value)
    elif kind is ActionKind.EIGHTWAY:
        updated = replace(current, eightway=value)
    else:
        raise ValueError(f"{kind.value} does not have a special quota")
    if player is Color.BLACK:
        return replace(quotas, black=updated)
    return replace(quotas, white=updated)


def _add_player_quotas(left: PlayerQuotas, right: PlayerQuotas) -> PlayerQuotas:
    def add_special(
        left_special: SpecialQuotas,
        right_special: SpecialQuotas,
    ) -> SpecialQuotas:
        return SpecialQuotas(
            immortal=left_special.immortal + right_special.immortal,
            double_start=left_special.double_start + right_special.double_start,
            eightway=left_special.eightway + right_special.eightway,
        )

    return PlayerQuotas(
        black=add_special(left.black, right.black),
        white=add_special(left.white, right.white),
    )


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


def _n8_neighbors(size: int, point: int) -> tuple[int, ...]:
    x = point % size
    y = point // size
    return tuple(
        size * neighbor_y + neighbor_x
        for neighbor_y in range(max(0, y - 1), min(size, y + 2))
        for neighbor_x in range(max(0, x - 1), min(size, x + 2))
        if neighbor_x != x or neighbor_y != y
    )


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


def _validate_nonnegative_safe_integer(
    name: str,
    value: int,
    *,
    maximum: int = JSON_SAFE_INTEGER_MAX,
) -> None:
    if type(value) is not int or not (0 <= value <= maximum):
        raise ValueError(f"{name} must be an integer in 0..{maximum}")


def _validate_positive_safe_integer(name: str, value: int) -> None:
    if type(value) is not int or not (1 <= value <= JSON_SAFE_INTEGER_MAX):
        raise ValueError(
            f"{name} must be an integer in 1..{JSON_SAFE_INTEGER_MAX}"
        )


def _validate_point_tuple(name: str, points: tuple[int, ...]) -> None:
    if not isinstance(points, tuple):
        raise TypeError(f"{name} occupancy must be a tuple")
    previous = -1
    for point in points:
        if type(point) is not int or not (0 <= point < CANVAS_POINT_COUNT):
            raise ValueError(f"{name} occupancy points must be integers in 0..360")
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
    "AdministrativeTerminationReason",
    "AdministrativeTerminationTransition",
    "ActionKind",
    "ActionV1DecodeError",
    "AbilityState",
    "AtomicActionEvent",
    "Board",
    "Color",
    "DecodedAction",
    "Group",
    "ImmediateTerminalEvent",
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
    "SettlementStepEvent",
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
    "apply_administrative_termination",
    "decode_action_v1",
    "new_game",
    "scan_mixed_groups",
    "scan_n4_groups",
    "score_chinese_area",
    "settlement_threshold",
]
