from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

from auto_ledger.config import AppConfig
from auto_ledger.notion import NotionClient, refresh_fixed_expenses, upsert_transactions
from auto_ledger.providers import build_providers
from auto_ledger.service import build_sync_result, summarize_transactions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync bank and card transactions into Notion.")
    parser.add_argument("--start-date", default=(date.today() - timedelta(days=90)).isoformat())
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AppConfig.from_env()
    providers = build_providers(config.load_provider_specs())
    result = build_sync_result(
        providers=providers,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
    )
    summary = {
        "transactions": len(result.transactions),
        "fixed_expenses": len(result.fixed_expenses),
        **summarize_transactions(result.transactions),
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    notion = NotionClient(config.notion_token)
    transaction_status = upsert_transactions(
        notion, config.transactions_database_id, result.transactions
    )
    fixed_expense_status = refresh_fixed_expenses(
        notion, config.fixed_expenses_database_id, result.fixed_expenses
    )
    print(
        json.dumps(
            {"summary": summary, "transactions_sync": transaction_status, "fixed_expenses_sync": fixed_expense_status},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
