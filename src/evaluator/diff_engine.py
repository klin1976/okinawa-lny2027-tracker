from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from src.schemas.budget_schema import AlertEvent


@dataclass
class DiffReport:
    """結構化彙整當次巡檢偵測到的高價值差異與維運警報。"""

    new_tours: List[AlertEvent] = field(default_factory=list)
    price_drops: List[AlertEvent] = field(default_factory=list)
    seats_released: List[AlertEvent] = field(default_factory=list)
    guaranteed_departures: List[AlertEvent] = field(default_factory=list)
    low_seats: List[AlertEvent] = field(default_factory=list)
    other_alerts: List[AlertEvent] = field(default_factory=list)

    @property
    def urgent_alerts(self) -> List[AlertEvent]:
        """需要主動推播提醒的高價值異動事件。"""
        return (
            self.price_drops
            + self.seats_released
            + self.guaranteed_departures
            + self.new_tours
            + self.low_seats
        )

    @property
    def all_alerts(self) -> List[AlertEvent]:
        return self.urgent_alerts + self.other_alerts

    @property
    def total_count(self) -> int:
        return len(self.all_alerts)

    def to_summary_dict(self) -> Dict[str, int]:
        return {
            "new_count": len(self.new_tours),
            "price_drop_count": len(self.price_drops),
            "seats_released_count": len(self.seats_released),
            "guaranteed_count": len(self.guaranteed_departures),
            "low_seats_count": len(self.low_seats),
            "other_count": len(self.other_alerts),
            "total": self.total_count,
        }


class DiffEngine:
    """將 AlertEvent 列表依事件類型分類彙整為 DiffReport。"""

    @staticmethod
    def build_report(alerts: List[AlertEvent]) -> DiffReport:
        report = DiffReport()
        for ev in alerts:
            if ev.alert_type in {"NEW_TOUR", "NEW_HIGH_VALUE_TOUR"}:
                report.new_tours.append(ev)
            elif ev.alert_type == "PRICE_DROP":
                report.price_drops.append(ev)
            elif ev.alert_type == "SEATS_RELEASED":
                report.seats_released.append(ev)
            elif ev.alert_type == "GUARANTEED_DEPARTURE":
                report.guaranteed_departures.append(ev)
            elif ev.alert_type in {"LOW_SEATS", "SEAT_CRITICAL"}:
                report.low_seats.append(ev)
            else:
                report.other_alerts.append(ev)
        return report
