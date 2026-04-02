from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Dict, Iterable, List

from auto_ledger.models import FixedExpense, Transaction


NORMALIZE_PATTERN = re.compile(r"[^0-9a-zA-Z가-힣]+")


def normalize_merchant(value: str) -> str:
    compact = NORMALIZE_PATTERN.sub("", value).lower()
    return compact or "unknown"


def dedupe_transactions(transactions: Iterable[Transaction]) -> List[Transaction]:
    deduped: Dict[str, Transaction] = {}
    for transaction in transactions:
        deduped[transaction.ledger_key] = transaction
    return sorted(deduped.values(), key=lambda item: item.posted_at)


def detect_fixed_expenses(
    transactions: Iterable[Transaction],
    min_occurrences: int = 3,
    amount_tolerance: Decimal = Decimal("5000"),
    target_interval_days: int = 30,
    interval_tolerance_days: int = 6,
) -> List[FixedExpense]:
    grouped: Dict[tuple, List[Transaction]] = defaultdict(list)
    for transaction in transactions:
        if transaction.direction != "outflow":
            continue
        grouped[(normalize_merchant(transaction.merchant or transaction.description), transaction.currency)].append(
            transaction
        )

    results: List[FixedExpense] = []
    for (normalized_label, currency), items in grouped.items():
        ordered = sorted(items, key=lambda item: item.posted_at)
        if len(ordered) < min_occurrences:
            continue
        amounts = [item.amount for item in ordered]
        if max(amounts) - min(amounts) > amount_tolerance:
            continue
        intervals = [
            (ordered[index].posted_at.date() - ordered[index - 1].posted_at.date()).days
            for index in range(1, len(ordered))
        ]
        if not intervals:
            continue
        interval_days = int(median(intervals))
        if abs(interval_days - target_interval_days) > interval_tolerance_days:
            continue
        last_posted = ordered[-1].posted_at.date()
        results.append(
            FixedExpense(
                merchant=ordered[-1].merchant or ordered[-1].description,
                normalized_label=normalized_label,
                source_kind=ordered[-1].source_kind,
                expected_amount=amounts[len(amounts) // 2],
                currency=currency,
                occurrences=len(ordered),
                interval_days=interval_days,
                last_posted_date=last_posted,
                next_expected_date=last_posted + timedelta(days=interval_days),
                provider_ids=", ".join(sorted({item.provider_id for item in ordered})),
            )
        )
    return sorted(results, key=lambda item: (item.next_expected_date or date.max, item.merchant))
