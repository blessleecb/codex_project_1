from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import requests

from auto_ledger.models import FixedExpense, Transaction


NOTION_VERSION = "2022-06-28"


class NotionClient:
    def __init__(self, token: str) -> None:
        self.base_url = "https://api.notion.com/v1"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            }
        )

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=20)
        response.raise_for_status()
        return response.json()

    def query_database(self, database_id: str, filter_payload: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        payload: Dict[str, Any] = {}
        if filter_payload:
            payload["filter"] = filter_payload
        results: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            if cursor:
                payload["start_cursor"] = cursor
            data = self._post(f"/databases/{database_id}/query", payload)
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                return results
            cursor = data.get("next_cursor")

    def create_page(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._post("/pages", payload)

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        response = self.session.patch(
            f"{self.base_url}/pages/{page_id}",
            json={"properties": properties},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()


def transaction_properties(transaction: Transaction) -> Dict[str, Any]:
    title = transaction.merchant or transaction.description or transaction.account_name
    return {
        "Name": {"title": [{"text": {"content": title[:200]}}]},
        "Ledger Key": {"rich_text": [{"text": {"content": transaction.ledger_key}}]},
        "Institution": {"select": {"name": transaction.institution_name}},
        "Source Type": {"select": {"name": transaction.source_kind}},
        "Account": {"rich_text": [{"text": {"content": transaction.account_name[:200]}}]},
        "Direction": {"select": {"name": transaction.direction}},
        "Amount": {"number": float(transaction.signed_amount)},
        "Absolute Amount": {"number": float(transaction.amount)},
        "Currency": {"select": {"name": transaction.currency}},
        "Posted At": {"date": {"start": transaction.posted_at.isoformat()}},
        "Description": {"rich_text": [{"text": {"content": transaction.description[:2000]}}]},
        "Provider ID": {"rich_text": [{"text": {"content": transaction.provider_id}}]},
        "Transaction ID": {"rich_text": [{"text": {"content": transaction.transaction_id[:200]}}]},
    }


def fixed_expense_properties(expense: FixedExpense) -> Dict[str, Any]:
    return {
        "Name": {"title": [{"text": {"content": expense.merchant[:200]}}]},
        "Normalized Label": {"rich_text": [{"text": {"content": expense.normalized_label[:200]}}]},
        "Source Type": {"select": {"name": expense.source_kind}},
        "Expected Amount": {"number": float(expense.expected_amount)},
        "Currency": {"select": {"name": expense.currency}},
        "Occurrences": {"number": expense.occurrences},
        "Interval Days": {"number": expense.interval_days},
        "Last Posted Date": {"date": {"start": expense.last_posted_date.isoformat()}},
        "Next Expected Date": {
            "date": {"start": expense.next_expected_date.isoformat() if expense.next_expected_date else None}
        },
        "Provider IDs": {"rich_text": [{"text": {"content": expense.provider_ids[:2000]}}]},
    }


def upsert_transactions(
    client: NotionClient,
    database_id: str,
    transactions: Iterable[Transaction],
) -> Dict[str, int]:
    inserted = 0
    skipped = 0
    for transaction in transactions:
        existing = client.query_database(
            database_id,
            {
                "property": "Ledger Key",
                "rich_text": {"equals": transaction.ledger_key},
            },
        )
        if existing:
            skipped += 1
            continue
        client.create_page({"parent": {"database_id": database_id}, "properties": transaction_properties(transaction)})
        inserted += 1
    return {"inserted": inserted, "skipped": skipped}


def refresh_fixed_expenses(
    client: NotionClient,
    database_id: str,
    expenses: Iterable[FixedExpense],
) -> Dict[str, int]:
    existing_pages = client.query_database(database_id)
    existing_by_label = {
        _property_text(page.get("properties", {}).get("Normalized Label")): page["id"]
        for page in existing_pages
    }
    inserted = 0
    updated = 0
    for expense in expenses:
        properties = fixed_expense_properties(expense)
        page_id = existing_by_label.get(expense.normalized_label)
        if page_id:
            client.update_page(page_id, properties)
            updated += 1
        else:
            client.create_page({"parent": {"database_id": database_id}, "properties": properties})
            inserted += 1
    return {"inserted": inserted, "updated": updated}


def _property_text(property_value: Optional[Dict[str, Any]]) -> str:
    if not property_value:
        return ""
    texts = property_value.get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in texts)
