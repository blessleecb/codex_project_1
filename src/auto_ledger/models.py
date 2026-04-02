from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Transaction:
    provider_id: str
    institution_name: str
    source_kind: str
    transaction_id: str
    posted_at: datetime
    amount: Decimal
    currency: str
    direction: str
    merchant: str
    description: str
    account_name: str
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction == "inflow" else -self.amount

    @property
    def ledger_key(self) -> str:
        digest = sha256(
            "|".join(
                [
                    self.provider_id,
                    self.transaction_id,
                    self.posted_at.isoformat(),
                    str(self.amount),
                    self.currency,
                ]
            ).encode("utf-8")
        ).hexdigest()
        return digest


@dataclass(frozen=True)
class FixedExpense:
    merchant: str
    normalized_label: str
    source_kind: str
    expected_amount: Decimal
    currency: str
    occurrences: int
    interval_days: int
    last_posted_date: date
    next_expected_date: Optional[date]
    provider_ids: str
