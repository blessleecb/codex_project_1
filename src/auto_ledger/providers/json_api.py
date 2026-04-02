from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List

import requests

from auto_ledger.models import Transaction
from auto_ledger.providers.base import Provider


def _dig(data: Dict[str, Any], dotted_key: str, default: Any = None) -> Any:
    current: Any = data
    for part in dotted_key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def _parse_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


@dataclass
class JsonApiProvider(Provider):
    id: str
    name: str
    kind: str
    base_url: str
    transactions_path: str
    auth: Dict[str, Any]
    params: Dict[str, str]
    field_map: Dict[str, str]
    timeout_seconds: int = 20

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        auth_type = self.auth.get("type")
        if auth_type == "bearer_env":
            token = os.environ.get(self.auth["env"])
            if not token:
                raise RuntimeError(f"Missing token env var: {self.auth['env']}")
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request_params(self, start_date: date, end_date: date) -> Dict[str, str]:
        values = {}
        for key, value in self.params.items():
            values[key] = value.format(start_date=start_date.isoformat(), end_date=end_date.isoformat())
        return values

    def fetch_transactions(self, start_date: date, end_date: date) -> Iterable[Transaction]:
        response = requests.get(
            f"{self.base_url.rstrip('/')}{self.transactions_path}",
            headers=self._headers(),
            params=self._request_params(start_date, end_date),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        items_path = self.field_map.get("items_path", "")
        records: List[Dict[str, Any]]
        if items_path:
            raw_records = _dig(payload, items_path, [])
            records = raw_records if isinstance(raw_records, list) else []
        else:
            records = payload if isinstance(payload, list) else []

        for record in records:
            amount = Decimal(str(_dig(record, self.field_map["amount"])))
            direction = str(_dig(record, self.field_map.get("direction", ""), "")).lower()
            if direction not in {"inflow", "outflow"}:
                direction = "outflow" if amount >= 0 else "inflow"
                amount = abs(amount)
            yield Transaction(
                provider_id=self.id,
                institution_name=self.name,
                source_kind=self.kind,
                transaction_id=str(_dig(record, self.field_map["transaction_id"])),
                posted_at=_parse_datetime(str(_dig(record, self.field_map["posted_at"]))),
                amount=abs(amount),
                currency=str(_dig(record, self.field_map.get("currency", ""), "KRW")),
                direction=direction,
                merchant=str(_dig(record, self.field_map.get("merchant", ""), "")),
                description=str(_dig(record, self.field_map.get("description", ""), "")),
                account_name=str(_dig(record, self.field_map.get("account_name", ""), self.name)),
                raw=record,
            )
