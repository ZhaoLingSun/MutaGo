from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from mutago.collapse_go import (  # noqa: E402
    JSON_SAFE_INTEGER_MAX,
    ActionKind,
    Color,
    Occupancy,
    SettlementReason,
    SettlementResult,
    SettlementStepEvent,
)


def settlement_step(**overrides: object) -> SettlementStepEvent:
    values: dict[str, object] = {
        "event_id": "special-1",
        "logical_order": 0,
        "owner": Color.BLACK,
        "kind": ActionKind.DOUBLE_START,
        "ability_deactivated": False,
        "no_op": True,
        "stable_occupancy": Occupancy.empty(),
        "stable_stones": (),
        "psk_history_index": 0,
        "revision": 0,
        "log_position": 0,
    }
    values.update(overrides)
    if "logical_order" in overrides and "event_id" not in overrides:
        logical_order = overrides["logical_order"]
        if type(logical_order) is int:
            values["event_id"] = f"special-{logical_order + 1}"
    return SettlementStepEvent(**values)  # type: ignore[arg-type]


class SettlementProjectionIntegerBoundsTests(unittest.TestCase):
    def test_safe_integer_maximums_are_accepted_where_semantically_valid(self) -> None:
        step = settlement_step(
            event_id=f"special-{JSON_SAFE_INTEGER_MAX}",
            logical_order=JSON_SAFE_INTEGER_MAX - 1,
            psk_history_index=JSON_SAFE_INTEGER_MAX,
            revision=JSON_SAFE_INTEGER_MAX,
            log_position=JSON_SAFE_INTEGER_MAX,
        )
        self.assertEqual(JSON_SAFE_INTEGER_MAX - 1, step.logical_order)
        self.assertEqual(JSON_SAFE_INTEGER_MAX, step.psk_history_index)
        self.assertEqual(JSON_SAFE_INTEGER_MAX, step.revision)
        self.assertEqual(JSON_SAFE_INTEGER_MAX, step.log_position)

        empty = SettlementResult(reason=SettlementReason.THRESHOLD)
        self.assertEqual(0, empty.ledger_entry_count)
        self.assertEqual(0, empty.psk_appends)
        self.assertEqual((), empty.steps)

    def test_logical_order_rejects_negative_bool_and_unsafe_one_based_action(self) -> None:
        invalid_values = (
            -1,
            False,
            True,
            JSON_SAFE_INTEGER_MAX,
            JSON_SAFE_INTEGER_MAX + 1,
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError,
                "logical_order",
            ):
                settlement_step(logical_order=value)

    def test_step_indices_reject_negative_bool_and_unsafe_values(self) -> None:
        for field_name in ("psk_history_index", "revision", "log_position"):
            for value in (-1, False, True, JSON_SAFE_INTEGER_MAX + 1):
                with self.subTest(field=field_name, value=value), self.assertRaisesRegex(
                    ValueError,
                    field_name,
                ):
                    settlement_step(**{field_name: value})

    def test_settlement_counts_reject_negative_bool_and_unsafe_values(self) -> None:
        for field_name in ("ledger_entry_count", "psk_appends"):
            for value in (-1, False, True, JSON_SAFE_INTEGER_MAX + 1):
                values = {
                    "reason": SettlementReason.THRESHOLD,
                    field_name: value,
                }
                with self.subTest(field=field_name, value=value), self.assertRaisesRegex(
                    ValueError,
                    field_name,
                ):
                    SettlementResult(**values)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
