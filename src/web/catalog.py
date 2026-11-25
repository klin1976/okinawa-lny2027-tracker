from __future__ import annotations

import copy
from datetime import date, timedelta
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import yaml

from src.schemas.trip_schema import (
    DestinationConfig,
    FlightBenchmarkConfig,
    PartyOverrides,
    ScheduleConfig,
    TripConfig,
)

DESTINATION_CATALOG: List[Dict[str, Any]] = [
    {
        "country": "日本",
        "regions": [
            {
                "region_name": "沖繩",
                "slug": "okinawa",
                "keywords": ["沖繩", "琉球", "OKA"],
                "airports": ["OKA"],
                "default_min_days": 4,
                "default_max_days": 5,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "北海道",
                "slug": "hokkaido",
                "keywords": ["北海道", "札幌", "函館"],
                "airports": ["CTS", "HKD"],
                "default_min_days": 5,
                "default_max_days": 7,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "東京/關東",
                "slug": "tokyo",
                "keywords": ["東京", "關東", "迪士尼", "富士山"],
                "airports": ["NRT", "HND"],
                "default_min_days": 4,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "大阪/關西",
                "slug": "osaka",
                "keywords": ["大阪", "京都", "關西", "環球影城"],
                "airports": ["KIX"],
                "default_min_days": 4,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "九州",
                "slug": "kyushu",
                "keywords": ["九州", "福岡", "豪斯登堡", "熊本"],
                "airports": ["FUK", "KMJ"],
                "default_min_days": 4,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "東北",
                "slug": "tohoku",
                "keywords": ["東北", "仙台", "青森", "藏王"],
                "airports": ["SDJ", "AOJ"],
                "default_min_days": 5,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "北陸立山",
                "slug": "hokuriku",
                "keywords": ["北陸", "立山", "黑部", "合掌村", "名古屋"],
                "airports": ["NGO", "KMQ"],
                "default_min_days": 5,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
        ],
    },
    {
        "country": "韓國",
        "regions": [
            {
                "region_name": "首爾",
                "slug": "seoul",
                "keywords": ["首爾", "愛寶樂園", "南怡島"],
                "airports": ["ICN", "GMP"],
                "default_min_days": 4,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "釜山",
                "slug": "busan",
                "keywords": ["釜山", "大邱", "慶州"],
                "airports": ["PUS"],
                "default_min_days": 4,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "濟州島",
                "slug": "jeju",
                "keywords": ["濟州"],
                "airports": ["CJU"],
                "default_min_days": 4,
                "default_max_days": 5,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
        ],
    },
    {
        "country": "東南亞",
        "regions": [
            {
                "region_name": "泰國/曼谷清邁",
                "slug": "thailand",
                "keywords": ["泰國", "曼谷", "芭達雅", "清邁"],
                "airports": ["BKK", "CNX"],
                "default_min_days": 5,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "越南/峴港富國島",
                "slug": "vietnam",
                "keywords": ["越南", "峴港", "富國島", "下龍灣"],
                "airports": ["DAD", "PQC", "HAN"],
                "default_min_days": 5,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "馬來西亞/新加坡",
                "slug": "maysin",
                "keywords": ["新加坡", "馬來西亞", "新馬", "樂高樂園"],
                "airports": ["SIN", "KUL"],
                "default_min_days": 5,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
            {
                "region_name": "印尼/峇里島",
                "slug": "bali",
                "keywords": ["峇里島", "巴里島"],
                "airports": ["DPS"],
                "default_min_days": 5,
                "default_max_days": 6,
                "child_bed_age_threshold": 6,
                "tip_per_day_twd": 300,
                "max_stops": 0,
            },
        ],
    },
    {
        "country": "歐洲",
        "regions": [
            {
                "region_name": "奧捷/德瑞",
                "slug": "austria_czech",
                "keywords": ["奧捷", "德瑞", "歐洲"],
                "airports": ["VIE", "PRG", "ZRH", "FRA"],
                "default_min_days": 9,
                "default_max_days": 13,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 450,
                "max_stops": 1,
            },
            {
                "region_name": "義大利",
                "slug": "italy",
                "keywords": ["義大利", "羅馬", "威尼斯", "米蘭"],
                "airports": ["FCO", "MXP"],
                "default_min_days": 9,
                "default_max_days": 14,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 450,
                "max_stops": 1,
            },
            {
                "region_name": "法瑞",
                "slug": "france_swiss",
                "keywords": ["法瑞", "巴黎", "瑞士"],
                "airports": ["CDG", "ZRH"],
                "default_min_days": 9,
                "default_max_days": 13,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 450,
                "max_stops": 1,
            },
            {
                "region_name": "西班牙/葡萄牙",
                "slug": "spain_portugal",
                "keywords": ["西班牙", "葡萄牙", "西葡"],
                "airports": ["MAD", "BCN", "LIS"],
                "default_min_days": 10,
                "default_max_days": 14,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 450,
                "max_stops": 1,
            },
            {
                "region_name": "北歐",
                "slug": "nordic",
                "keywords": ["北歐", "挪威", "冰島", "芬蘭"],
                "airports": ["HEL", "OSL", "CPH"],
                "default_min_days": 10,
                "default_max_days": 14,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 450,
                "max_stops": 1,
            },
        ],
    },
    {
        "country": "紐澳美加",
        "regions": [
            {
                "region_name": "澳洲",
                "slug": "australia",
                "keywords": ["澳洲", "雪梨", "墨爾本", "黃金海岸"],
                "airports": ["SYD", "MEL", "BNE"],
                "default_min_days": 6,
                "default_max_days": 9,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 400,
                "max_stops": 1,
            },
            {
                "region_name": "紐西蘭",
                "slug": "new_zealand",
                "keywords": ["紐西蘭", "奧克蘭", "南島", "北島"],
                "airports": ["AKL", "CHC"],
                "default_min_days": 8,
                "default_max_days": 12,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 400,
                "max_stops": 1,
            },
            {
                "region_name": "美西",
                "slug": "us_west",
                "keywords": ["美西", "洛杉磯", "舊金山", "大峽谷"],
                "airports": ["LAX", "SFO"],
                "default_min_days": 8,
                "default_max_days": 12,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 450,
                "max_stops": 1,
            },
            {
                "region_name": "加拿大",
                "slug": "canada",
                "keywords": ["加拿大", "洛磯山脈", "溫哥華", "極光"],
                "airports": ["YVR", "YYZ"],
                "default_min_days": 8,
                "default_max_days": 12,
                "child_bed_age_threshold": 12,
                "tip_per_day_twd": 450,
                "max_stops": 1,
            },
        ],
    },
]


def _slugify(text: str) -> str:
    ascii_only = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    if ascii_only:
        return ascii_only
    return f"dest_{abs(hash(text)) % 100000}"


def find_catalog_entry(country: str, region_name: str) -> Optional[Dict[str, Any]]:
    """依國家與地區名稱查找內建目的地設定。"""
    c_norm = country.strip()
    r_norm = region_name.strip()
    for group in DESTINATION_CATALOG:
        if group["country"] != c_norm:
            continue
        for region in group["regions"]:
            if region["region_name"] == r_norm:
                return copy.deepcopy(region)
    return None


def build_destination_catalog(trips: List[TripConfig]) -> List[Dict[str, Any]]:
    """合併內建國家/地區目錄與 config/trips/*.yaml，標註已綁定的 trip_ids。"""
    catalog = copy.deepcopy(DESTINATION_CATALOG)
    country_map: Dict[str, Dict[str, Any]] = {g["country"]: g for g in catalog}

    for group in catalog:
        for region in group["regions"]:
            region["trip_ids"] = []

    for trip in trips:
        c_name = trip.destination.country.strip()
        r_name = trip.destination.region_name.strip()
        group = country_map.get(c_name)
        if group is None:
            group = {"country": c_name, "regions": []}
            catalog.append(group)
            country_map[c_name] = group

        matched_region = next(
            (r for r in group["regions"] if r["region_name"] == r_name), None
        )
        if matched_region is None:
            matched_region = {
                "region_name": r_name,
                "slug": _slugify(f"{c_name}_{r_name}"),
                "keywords": list(trip.destination.search_keywords),
                "airports": list(trip.destination.airports),
                "default_min_days": trip.schedule.min_days,
                "default_max_days": trip.schedule.max_days,
                "child_bed_age_threshold": trip.party.child_bed_age_threshold,
                "tip_per_day_twd": trip.party.tip_per_day_twd or 300,
                "max_stops": trip.flight_benchmark.max_stops,
                "trip_ids": [],
            }
            group["regions"].append(matched_region)

        matched_region["trip_ids"].append(trip.trip_id)

    return catalog


def build_party_members(
    adults: int = 2,
    children_with_bed: int = 0,
    children_no_bed: int = 0,
    infants: int = 0,
    child_bed_age_threshold: int = 6,
) -> List[Dict[str, Any]]:
    """將成人/兒童人數轉為 BudgetEngine 相容的 members 明細清單。"""
    members: List[Dict[str, Any]] = []
    if adults > 0:
        members.append(
            {
                "role": "adult",
                "count": adults,
                "age_note": "一般成人",
                "require_bed": True,
                "require_flight_seat": True,
            }
        )
    if children_with_bed > 0:
        members.append(
            {
                "role": "child",
                "count": children_with_bed,
                "age": max(child_bed_age_threshold, 7),
                "age_note": f"兒童（佔床，滿{child_bed_age_threshold}歲）",
                "require_bed": True,
                "require_flight_seat": True,
            }
        )
    if children_no_bed > 0:
        members.append(
            {
                "role": "child",
                "count": children_no_bed,
                "age": max(2, child_bed_age_threshold - 2),
                "age_note": f"兒童（不佔床，未滿{child_bed_age_threshold}歲）",
                "require_bed": False,
                "require_flight_seat": True,
            }
        )
    if infants > 0:
        members.append(
            {
                "role": "infant",
                "count": infants,
                "age": 1,
                "age_note": "嬰兒（未滿2歲）",
                "require_bed": False,
                "require_flight_seat": False,
            }
        )
    return members


def build_dynamic_trip_config(
    country: str,
    region_name: str,
    departure_date_start: Optional[str] = None,
    departure_date_end: Optional[str] = None,
    min_days: Optional[int] = None,
    max_days: Optional[int] = None,
    adults: Optional[int] = None,
    children_with_bed: Optional[int] = None,
    children_no_bed: Optional[int] = None,
    infants: Optional[int] = None,
    custom_keywords: Optional[List[str]] = None,
    save_as_trip: bool = False,
    trips_dir: str | Path = "config/trips",
) -> TripConfig:
    """依國家、地區與成人/兒童人數動態組裝 TripConfig（並可選存為 YAML）。"""
    c_clean = country.strip() or "其他"
    r_clean = region_name.strip()
    entry = find_catalog_entry(c_clean, r_clean)

    today = date.today()
    start_str = departure_date_start or (today + timedelta(days=30)).isoformat()
    end_str = departure_date_end or (today + timedelta(days=90)).isoformat()

    is_long_haul = c_clean in ("歐洲", "紐澳美加")
    default_bed_age = 12 if is_long_haul else 6
    default_tip = 450 if is_long_haul else 300

    if entry:
        keywords = list(custom_keywords) if custom_keywords else list(entry["keywords"])
        airports = list(entry["airports"])
        eff_min_days = min_days if min_days is not None else int(entry["default_min_days"])
        eff_max_days = max_days if max_days is not None else int(entry["default_max_days"])
        bed_age = int(entry["child_bed_age_threshold"])
        tip_per_day = int(entry["tip_per_day_twd"])
        max_stops = int(entry["max_stops"])
        slug = entry["slug"]
    else:
        keywords = list(custom_keywords) if custom_keywords else [r_clean]
        airports = []
        eff_min_days = min_days if min_days is not None else 4
        eff_max_days = max_days if max_days is not None else 7
        bed_age = default_bed_age
        tip_per_day = default_tip
        max_stops = 1 if is_long_haul else 0
        slug = _slugify(r_clean)

    if eff_min_days > eff_max_days:
        eff_max_days = eff_min_days

    members: Optional[List[Dict[str, Any]]] = None
    if any(
        val is not None
        for val in (adults, children_with_bed, children_no_bed, infants)
    ):
        members = build_party_members(
            adults=adults if adults is not None else 2,
            children_with_bed=children_with_bed or 0,
            children_no_bed=children_no_bed or 0,
            infants=infants or 0,
            child_bed_age_threshold=bed_age,
        )

    trip_id = f"custom_{slug}"
    trip_cfg = TripConfig(
        trip_id=trip_id,
        trip_name=f"{c_clean} · {r_clean} 動態探索",
        enabled=True,
        destination=DestinationConfig(
            country=c_clean,
            region_name=r_clean,
            search_keywords=keywords,
            exclude_keywords=["郵輪", "機加酒"],
            airports=airports,
        ),
        schedule=ScheduleConfig(
            departure_date_start=start_str,
            departure_date_end=end_str,
            min_days=eff_min_days,
            max_days=eff_max_days,
        ),
        flight_benchmark=FlightBenchmarkConfig(
            enabled=bool(airports),
            origins=["TPE", "KHH"],
            max_stops=max_stops,
        ),
        party=PartyOverrides(
            members=members,
            child_bed_age_threshold=bed_age,
            tip_per_day_twd=tip_per_day,
        ),
    )

    if save_as_trip:
        target_dir = Path(trips_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = target_dir / f"{trip_id}.yaml"
        yaml_path.write_text(
            yaml.safe_dump(
                trip_cfg.model_dump(mode="json"),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    return trip_cfg
