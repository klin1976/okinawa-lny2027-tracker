from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
import yaml

from src.schemas.budget_schema import AlertEvent, FamilyBudgetResult
from src.schemas.tour_schema import OkinawaTourPackage

DEFAULT_PROFILE_PATH = Path("config/family_profile.yaml")


class AlertDetector:
    def __init__(self, profile_data_or_path: Optional[Union[str, Path, Dict[str, Any]]] = None):
        if isinstance(profile_data_or_path, dict):
            self.profile = profile_data_or_path
        elif profile_data_or_path is not None:
            with open(profile_data_or_path, "r", encoding="utf-8") as f:
                self.profile = yaml.safe_load(f)
        else:
            if DEFAULT_PROFILE_PATH.exists():
                with open(DEFAULT_PROFILE_PATH, "r", encoding="utf-8") as f:
                    self.profile = yaml.safe_load(f)
            else:
                self.profile = {}

        alerts_cfg = self.profile.get("alerts", {})
        self.price_drop_adult_threshold = alerts_cfg.get("price_drop_per_adult_twd", 1500)
        self.price_drop_family_threshold = alerts_cfg.get("price_drop_family_total_twd", 10000)
        self.seat_buffer = alerts_cfg.get("seat_buffer", 4)

    def detect_alerts(
        self,
        tour_uid: str,
        current_snapshot: Dict[str, Any],
        prev_snapshot: Optional[Dict[str, Any]],
        budget_result: FamilyBudgetResult,
        tour_package: Optional[OkinawaTourPackage] = None,
        is_top_ranked: bool = False,
        existing_alert_keys: Optional[Set[str]] = None,
    ) -> List[AlertEvent]:
        existing_keys = existing_alert_keys or set()
        alerts: List[AlertEvent] = []
        now_iso = datetime.now(timezone.utc).isoformat()

        curr_adult_price = current_snapshot.get("adult_price")
        curr_seats = current_snapshot.get("seats_available")
        curr_family_total = budget_result.grand_total_twd
        total_seats_needed = budget_result.total_flight_seats_needed

        # 1. 新團上架偵測 (prev_snapshot 為 None)
        if prev_snapshot is None:
            has_shopping = False
            if tour_package and tour_package.comparison_flags:
                has_shopping = tour_package.comparison_flags.has_shopping_station

            seats_ok = (curr_seats is not None) and (curr_seats >= total_seats_needed)

            if (not has_shopping) and seats_ok and is_top_ranked:
                alert_key = f"NEW_HIGH_VALUE_TOUR:{tour_uid}"
                if alert_key not in existing_keys:
                    alerts.append(
                        AlertEvent(
                            alert_key=alert_key,
                            alert_type="NEW_HIGH_VALUE_TOUR",
                            tour_uid=tour_uid,
                            priority="中",
                            message=f"發現超值新上架行程！無購物站且機位充足（餘 {curr_seats} 席），家族總價 NT$ {curr_family_total:,}",
                            details={
                                "seats_available": curr_seats,
                                "grand_total_twd": curr_family_total,
                            },
                            created_at=now_iso,
                        )
                    )
            else:
                alert_key = f"NEW_TOUR:{tour_uid}"
                if alert_key not in existing_keys:
                    alerts.append(
                        AlertEvent(
                            alert_key=alert_key,
                            alert_type="NEW_TOUR",
                            tour_uid=tour_uid,
                            priority="中",
                            message=f"新團上架：成人團費 NT$ {curr_adult_price or 0:,}，家族總價 NT$ {curr_family_total:,}",
                            details={
                                "adult_price": curr_adult_price,
                                "grand_total_twd": curr_family_total,
                            },
                            created_at=now_iso,
                        )
                    )
            return alerts

        # 2. 降價偵測 (比對前後快照)
        prev_adult_price = prev_snapshot.get("adult_price")
        prev_family_total = prev_snapshot.get("estimated_family_total")

        adult_drop = (
            (prev_adult_price - curr_adult_price)
            if (prev_adult_price is not None and curr_adult_price is not None)
            else 0
        )
        family_drop = (
            (prev_family_total - curr_family_total)
            if (prev_family_total is not None and curr_family_total is not None)
            else 0
        )

        if adult_drop >= self.price_drop_adult_threshold or family_drop >= self.price_drop_family_threshold:
            alert_key = f"PRICE_DROP:{tour_uid}:{curr_adult_price}_{curr_family_total}"
            if alert_key not in existing_keys:
                alerts.append(
                    AlertEvent(
                        alert_key=alert_key,
                        alert_type="PRICE_DROP",
                        tour_uid=tour_uid,
                        priority="高",
                        message=(
                            f"【大幅降價】成人團費下降 NT$ {adult_drop:,} "
                            f"(現價 NT$ {curr_adult_price:,})，"
                            f"家族總預算省下 NT$ {family_drop:,} "
                            f"(新總價 NT$ {curr_family_total:,})！"
                        ),
                        details={
                            "prev_adult_price": prev_adult_price,
                            "curr_adult_price": curr_adult_price,
                            "prev_family_total": prev_family_total,
                            "curr_family_total": curr_family_total,
                            "adult_drop": adult_drop,
                            "family_drop": family_drop,
                        },
                        created_at=now_iso,
                    )
                )

        # 3. 機位告警 (LOW_SEATS 與 SEAT_CRITICAL)
        prev_seats = prev_snapshot.get("seats_available")
        low_seat_threshold = total_seats_needed + self.seat_buffer

        if curr_seats is not None and prev_seats is not None:
            # 機位跌破家族所需（已不足）
            if prev_seats >= total_seats_needed and curr_seats < total_seats_needed:
                alert_key = f"SEAT_CRITICAL:{tour_uid}:{curr_seats}"
                if alert_key not in existing_keys:
                    alerts.append(
                        AlertEvent(
                            alert_key=alert_key,
                            alert_type="SEAT_CRITICAL",
                            tour_uid=tour_uid,
                            priority="高",
                            message=(
                                f"【機位告急】剩餘機位從 {prev_seats} 席驟降至 {curr_seats} 席，"
                                f"已不足全家族報名所需（需 {total_seats_needed} 席）！"
                            ),
                            details={
                                "prev_seats": prev_seats,
                                "curr_seats": curr_seats,
                                "total_seats_needed": total_seats_needed,
                            },
                            created_at=now_iso,
                        )
                    )

            # 跌破低機位安全緩衝水位（但仍足夠）
            elif (
                prev_seats > low_seat_threshold
                and curr_seats <= low_seat_threshold
                and curr_seats >= total_seats_needed
            ):
                alert_key = f"LOW_SEATS:{tour_uid}:{curr_seats}"
                if alert_key not in existing_keys:
                    alerts.append(
                        AlertEvent(
                            alert_key=alert_key,
                            alert_type="LOW_SEATS",
                            tour_uid=tour_uid,
                            priority="中高",
                            message=(
                                f"【機位預警】剩餘機位已跌破安全門檻（現存 {curr_seats} 席，"
                                f"全家需 {total_seats_needed} 席，安全緩衝 {self.seat_buffer} 席），請評估儘速下訂！"
                            ),
                            details={
                                "prev_seats": prev_seats,
                                "curr_seats": curr_seats,
                                "threshold": low_seat_threshold,
                            },
                            created_at=now_iso,
                        )
                    )

        return alerts
