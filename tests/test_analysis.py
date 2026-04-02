from datetime import datetime
from decimal import Decimal
import unittest

from auto_ledger.analysis import dedupe_transactions, detect_fixed_expenses, normalize_merchant
from auto_ledger.models import Transaction


def build_transaction(
    provider_id: str,
    transaction_id: str,
    posted_at: str,
    amount: str,
    direction: str,
    merchant: str,
) -> Transaction:
    return Transaction(
        provider_id=provider_id,
        institution_name="테스트기관",
        source_kind="card",
        transaction_id=transaction_id,
        posted_at=datetime.fromisoformat(posted_at),
        amount=Decimal(amount),
        currency="KRW",
        direction=direction,
        merchant=merchant,
        description=merchant,
        account_name="테스트카드",
    )


class AnalysisTests(unittest.TestCase):
    def test_normalize_merchant(self) -> None:
        self.assertEqual(normalize_merchant("넷플릭스  (정기결제)"), "넷플릭스정기결제")

    def test_dedupe_transactions(self) -> None:
        first = build_transaction("kb-card", "A1", "2026-01-01T10:00:00", "12000", "outflow", "Spotify")
        duplicate = build_transaction("kb-card", "A1", "2026-01-01T10:00:00", "12000", "outflow", "Spotify")
        deduped = dedupe_transactions([first, duplicate])
        self.assertEqual(len(deduped), 1)

    def test_detect_fixed_expenses(self) -> None:
        transactions = [
            build_transaction("hyundai-card", "1", "2026-01-05T08:00:00", "17000", "outflow", "Netflix"),
            build_transaction("hyundai-card", "2", "2026-02-05T08:00:00", "17000", "outflow", "Netflix"),
            build_transaction("hyundai-card", "3", "2026-03-05T08:00:00", "17000", "outflow", "Netflix"),
            build_transaction("tossbank", "4", "2026-03-10T08:00:00", "5000000", "inflow", "월급"),
        ]
        detected = detect_fixed_expenses(transactions)
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0].merchant, "Netflix")
        self.assertEqual(detected[0].interval_days, 29)


if __name__ == "__main__":
    unittest.main()
