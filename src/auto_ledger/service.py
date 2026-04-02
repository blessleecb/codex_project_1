from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List

from auto_ledger.analysis import dedupe_transactions, detect_fixed_expenses
from auto_ledger.models import FixedExpense, Transaction
from auto_ledger.providers.base import Provider


@dataclass
class SyncResult:
    transactions: List[Transaction]
    fixed_expenses: List[FixedExpense]


def collect_transactions(
    providers: Iterable[Provider], start_date: date, end_date: date
) -> List[Transaction]:
    collected: List[Transaction] = []
    for provider in providers:
        collected.extend(provider.fetch_transactions(start_date, end_date))
    return dedupe_transactions(collected)


def build_sync_result(
    providers: Iterable[Provider], start_date: date, end_date: date
) -> SyncResult:
    transactions = collect_transactions(providers, start_date, end_date)
    fixed_expenses = detect_fixed_expenses(transactions)
    return SyncResult(transactions=transactions, fixed_expenses=fixed_expenses)


def summarize_transactions(transactions: Iterable[Transaction]) -> Dict[str, float]:
    inflow = 0.0
    outflow = 0.0
    for transaction in transactions:
        if transaction.direction == "inflow":
            inflow += float(transaction.amount)
        else:
            outflow += float(transaction.amount)
    return {"inflow": inflow, "outflow": outflow, "net": inflow - outflow}
