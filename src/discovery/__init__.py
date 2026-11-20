from typing import Any, Dict, List, Optional, Type

from src.discovery.base_adapter import BaseAgencyAdapter
from src.discovery.cola_adapter import ColaAdapter
from src.discovery.fourp_adapter import FourPAdapter
from src.discovery.lion_adapter import LionAdapter
from src.discovery.richmont_adapter import RichmontAdapter
from src.discovery.settour_adapter import SettourAdapter

ADAPTER_REGISTRY: Dict[str, Type[BaseAgencyAdapter]] = {
    "lion": LionAdapter,
    "cola": ColaAdapter,
    "settour": SettourAdapter,
    "richmont": RichmontAdapter,
    "fourp": FourPAdapter,
}


def build_enabled_adapters(agencies_cfg: Dict[str, Any], target_keys: Optional[List[str]] = None) -> List[BaseAgencyAdapter]:
    common_filters = agencies_cfg.get("common_filters", {})
    concurrency_cfg = agencies_cfg.get("concurrency", {})
    agencies_map = agencies_cfg.get("agencies", {})

    adapters: List[BaseAgencyAdapter] = []
    for key, cfg in agencies_map.items():
        if not cfg.get("enabled", True):
            continue
        if target_keys and "all" not in target_keys:
            if key not in target_keys and cfg.get("name") not in target_keys:
                continue
        cls = ADAPTER_REGISTRY.get(key)
        if cls is not None:
            adapters.append(
                cls(
                    agency_config=cfg,
                    common_filters=common_filters,
                    concurrency_config=concurrency_cfg,
                )
            )
    return adapters


__all__ = [
    "BaseAgencyAdapter",
    "LionAdapter",
    "ColaAdapter",
    "SettourAdapter",
    "RichmontAdapter",
    "FourPAdapter",
    "ADAPTER_REGISTRY",
    "build_enabled_adapters",
]
