from __future__ import annotations

from typing import Any, Dict, Iterable, List

from auto_ledger.providers.base import Provider
from auto_ledger.providers.json_api import JsonApiProvider


def build_providers(specs: Iterable[Dict[str, Any]]) -> List[Provider]:
    providers: List[Provider] = []
    for spec in specs:
        driver = spec["driver"]
        if driver != "json_api":
            raise ValueError(f"Unsupported provider driver: {driver}")
        providers.append(
            JsonApiProvider(
                id=spec["id"],
                name=spec["name"],
                kind=spec["kind"],
                base_url=spec["base_url"],
                transactions_path=spec["transactions_path"],
                auth=spec.get("auth", {}),
                params=spec.get("params", {}),
                field_map=spec["field_map"],
            )
        )
    return providers
