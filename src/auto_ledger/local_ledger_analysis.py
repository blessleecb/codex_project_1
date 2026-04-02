from __future__ import annotations

import csv
import json
import fnmatch
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from auto_ledger.analysis import detect_fixed_expenses
from auto_ledger.excel_readers import read_html_xls, read_xls, read_xlsx
from auto_ledger.models import FixedExpense, Transaction

CARD_PAYMENT_KEYWORDS = ("현대카드", "ＫＢ카드출금", "KB카드출금", "우리카드결제")
SHINHAN_BANK_PREFIX = "신한은행_"
PDF_TXN_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}:\d{2}) (?P<kind>\S+) (?P<amount>-?[\d,]+) (?P<balance>[\d,]+) (?P<desc>.+)$"
)
ANALYSIS_START = datetime(2025, 4, 1, 0, 0, 0)
ANALYSIS_END = datetime(2026, 4, 1, 23, 59, 59)
MONTHLY_SALARY_BASE = Decimal("5132087")
FIXED_EXPENSE_EXCLUDE_KEYWORDS = (
    "김포지역화폐",
    "GOOGLE *YouTube",
    "GS25",
    "통장 이자 → 이자모으기",
    "통장 이자 → 이자 모으기",
    "통장 이자 → 달러로 모으기",
    "주식회사 피클플러스",
    "피클플러스",
    "230364442742",
    "쿠팡(와우 멤버십)",
    "쿠팡와우멤버십",
    "kb생",
    "ＫＢ생",
    "일산대교",
)


def parse_amount(value: str) -> Decimal:
    normalized = value.replace(",", "").replace("원", "").strip()
    if not normalized:
        return Decimal("0")
    return Decimal(normalized)


def parse_datetime(value: str, formats: Sequence[str]) -> datetime:
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported datetime format: {value}")


def cell(row: Sequence[str], index: int) -> str:
    return row[index] if index < len(row) else ""


def load_xls_rows(path: Path) -> List[List[str]]:
    sheets = read_xls(path)
    if not sheets:
        return []
    return next(iter(sheets.values()))


def pick_latest(paths: Iterable[Path]) -> Path:
    candidates = sorted({path for path in paths if path.exists()}, key=lambda item: (item.stat().st_mtime, item.name))
    if not candidates:
        raise FileNotFoundError("No matching files found")
    return candidates[-1]


def pick_all(paths: Iterable[Path]) -> List[Path]:
    return sorted({path for path in paths if path.exists()}, key=lambda item: (item.name.lower(), item.stat().st_mtime))


def pick_latest_optional(paths: Iterable[Path]) -> Path | None:
    candidates = pick_all(paths)
    return candidates[-1] if candidates else None


def find_files_by_patterns(directory: Path, patterns: Sequence[str]) -> List[Path]:
    matches: List[Path] = []
    normalized_patterns = [unicodedata.normalize("NFC", pattern) for pattern in patterns]
    for path in directory.iterdir():
        normalized_name = unicodedata.normalize("NFC", path.name)
        if any(fnmatch.fnmatch(normalized_name, pattern) for pattern in normalized_patterns):
            matches.append(path)
    return pick_all(matches)


def resolve_input_files(excel_dir: Path, report_dir: Path) -> Dict[str, List[Path] | Path | None]:
    hyundai_card = pick_latest_optional(find_files_by_patterns(excel_dir, ["*hyundaicard*.xlsx", "*현대카드*.xlsx"]))
    shinhan_cards = find_files_by_patterns(excel_dir, ["Shinhancard*.xls", "*신한카드*.xls"])
    kb_card = pick_latest_optional(find_files_by_patterns(excel_dir, ["*카드이용내역*.xls", "*KB*카드*.xls", "*국민카드*.xls"]))
    account_exports = find_files_by_patterns(excel_dir, ["inquiry_*.xls"])
    shinhan_bank_exports = find_files_by_patterns(excel_dir, ["*신한은행*거래내역조회*.xls", f"{SHINHAN_BANK_PREFIX}*.xls"])
    pdf_text_candidates = pick_all(
        [
            report_dir / "pdf_extracted_text.txt",
            *find_files_by_patterns(report_dir, ["*pdf*text*.txt"]),
            *find_files_by_patterns(excel_dir, ["*.txt"]),
        ]
    )
    pdf_text = pdf_text_candidates[-1] if pdf_text_candidates else None
    pdf_source = None
    pdf_candidates = find_files_by_patterns(excel_dir, ["*.pdf"])
    if pdf_candidates:
        pdf_source = pdf_candidates[-1]

    missing: List[str] = []
    if not hyundai_card:
        missing.append("현대카드 xlsx")
    if not shinhan_cards:
        missing.append("신한카드 xls")
    if not kb_card:
        missing.append("KB국민카드 xls")
    if not account_exports:
        missing.append("입출금계좌 inquiry xls")
    if not shinhan_bank_exports:
        missing.append("신한은행 거래내역 xls")
    if missing:
        raise FileNotFoundError(f"Required input files are missing: {', '.join(missing)}")

    return {
        "hyundai_card": hyundai_card,
        "shinhan_cards": shinhan_cards,
        "kb_card": kb_card,
        "account_exports": account_exports,
        "shinhan_bank_exports": shinhan_bank_exports,
        "pdf_text": pdf_text,
        "pdf_source": pdf_source,
    }


def build_card_transaction(
    provider_id: str,
    institution_name: str,
    source_file: str,
    transaction_id: str,
    posted_at: datetime,
    amount: Decimal,
    merchant: str,
    description: str,
    account_name: str,
) -> Transaction:
    return Transaction(
        provider_id=provider_id,
        institution_name=institution_name,
        source_kind="card",
        transaction_id=transaction_id,
        posted_at=posted_at,
        amount=abs(amount),
        currency="KRW",
        direction="outflow" if amount >= 0 else "inflow",
        merchant=merchant,
        description=description,
        account_name=account_name or source_file,
        raw={"source_file": source_file},
    )


def load_hyundai_cards(path: Path) -> List[Transaction]:
    sheet = next(iter(read_xlsx(path).values()))
    rows = sheet[6:]
    transactions: List[Transaction] = []
    for row in rows:
        if not cell(row, 0):
            continue
        status = cell(row, 8).strip()
        amount = parse_amount(cell(row, 4) or cell(row, 3))
        if status == "취소":
            amount = -abs(amount)
        if status not in {"정상", "취소"}:
            continue
        transactions.append(
            build_card_transaction(
                provider_id="hyundai-card",
                institution_name="현대카드",
                source_file=path.name,
                transaction_id=f"{cell(row, 9)}-{cell(row, 0)}-{cell(row, 3)}",
                posted_at=parse_datetime(cell(row, 0), ("%Y.%m.%d",)),
                amount=amount,
                merchant=cell(row, 2).strip(),
                description=status,
                account_name=cell(row, 1).strip(),
            )
        )
    return transactions


def load_shinhan_cards(paths: Iterable[Path]) -> List[Transaction]:
    transactions: List[Transaction] = []
    for path in paths:
        rows = load_xls_rows(path)[1:]
        for row in rows:
            if not cell(row, 0):
                continue
            status = cell(row, 10).strip()
            amount = parse_amount(cell(row, 5))
            if status == "취소":
                amount = -abs(amount)
            transactions.append(
                build_card_transaction(
                    provider_id="shinhan-card",
                    institution_name="신한카드",
                    source_file=path.name,
                    transaction_id=f"{cell(row, 4)}-{cell(row, 0)}-{cell(row, 5)}",
                    posted_at=parse_datetime(cell(row, 0), ("%Y.%m.%d %H:%M",)),
                    amount=amount,
                    merchant=cell(row, 3).strip(),
                    description=f"{cell(row, 6).strip()} {cell(row, 7).strip()}".strip(),
                    account_name=cell(row, 2).strip(),
                )
            )
    return transactions


def load_kb_cards(path: Path) -> List[Transaction]:
    rows = load_xls_rows(path)[7:]
    transactions: List[Transaction] = []
    for row in rows:
        if not cell(row, 0):
            continue
        status = cell(row, 11).strip()
        amount = parse_amount(cell(row, 5))
        if status == "승인취소":
            amount = -abs(amount)
        transactions.append(
            build_card_transaction(
                provider_id="kb-card",
                institution_name="KB국민카드",
                source_file=path.name,
                transaction_id=f"{cell(row, 13)}-{cell(row, 0)}-{cell(row, 5)}",
                posted_at=parse_datetime(f"{cell(row, 0)} {cell(row, 1)}", ("%Y-%m-%d %H:%M",)),
                amount=amount,
                merchant=cell(row, 4).strip(),
                description=status or cell(row, 7).strip(),
                account_name=cell(row, 3).strip(),
            )
        )
    return transactions


def load_account_transactions(paths: Iterable[Path]) -> List[Transaction]:
    transactions: List[Transaction] = []
    for path in paths:
        table = read_html_xls(path)[1]
        for row in table[1:]:
            if len(row) < 7 or not row[0]:
                continue
            out_amount = parse_amount(row[1])
            in_amount = parse_amount(row[2])
            if out_amount and in_amount:
                continue
            if out_amount:
                direction = "outflow"
                amount = out_amount
            else:
                direction = "inflow"
                amount = in_amount
            transactions.append(
                Transaction(
                    provider_id="account-394-20-014951",
                    institution_name="입출금계좌",
                    source_kind="bank",
                    transaction_id=f"{row[0]}-{row[1]}-{row[2]}-{row[5]}-{row[6]}",
                    posted_at=parse_datetime(row[0], ("%Y.%m.%d %H:%M",)),
                    amount=amount,
                    currency="KRW",
                    direction=direction,
                    merchant=row[5].strip() or row[4].strip(),
                    description=" | ".join(part.strip() for part in [row[4], row[5], row[6]] if part.strip()),
                    account_name="내지갑통장",
                    raw={"source_file": path.name, "balance": row[3].strip()},
                )
            )
    return transactions


def load_shinhan_bank_transactions(paths: Iterable[Path]) -> List[Transaction]:
    transactions: List[Transaction] = []
    for path in paths:
        rows = load_xls_rows(path)
        account_number = ""
        account_name = "신한은행 계좌"
        for row in rows[:6]:
            if cell(row, 0) == "계좌번호":
                account_number = cell(row, 1)
                account_name = f"신한은행 {account_number}"
                break

        for row in rows[7:]:
            if not cell(row, 0):
                continue
            out_amount = parse_amount(cell(row, 3))
            in_amount = parse_amount(cell(row, 4))
            if out_amount and in_amount:
                continue
            direction = "outflow" if out_amount else "inflow"
            amount = out_amount or in_amount
            posted_at = parse_datetime(
                f"{cell(row, 0)} {cell(row, 1)}", ("%Y-%m-%d %H:%M:%S",)
            )
            summary = " | ".join(part for part in [cell(row, 2), cell(row, 5), cell(row, 7)] if part)
            transactions.append(
                Transaction(
                    provider_id=f"shinhan-bank-{account_number or 'unknown'}",
                    institution_name="신한은행",
                    source_kind="bank",
                    transaction_id=f"{cell(row, 0)}-{cell(row, 1)}-{cell(row, 2)}-{cell(row, 3)}-{cell(row, 4)}-{cell(row, 5)}",
                    posted_at=posted_at,
                    amount=amount,
                    currency="KRW",
                    direction=direction,
                    merchant=cell(row, 5) or cell(row, 2),
                    description=summary,
                    account_name=account_name,
                    raw={"source_file": path.name, "balance": cell(row, 6), "branch": cell(row, 7)},
                )
            )
    return transactions


def load_tossbank_pdf_transactions(path: Path) -> List[Transaction]:
    text = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    account_name = "토스뱅크 1000-1499-0535"
    transactions: List[Transaction] = []
    pending_index: int | None = None

    for line in lines:
        if not line or line.startswith("=== PAGE") or re.fullmatch(r"\d+ / \d+", line):
            continue
        match = PDF_TXN_PATTERN.match(line)
        if match:
            amount_value = Decimal(match.group("amount").replace(",", ""))
            direction = "inflow" if amount_value >= 0 else "outflow"
            amount = abs(amount_value)
            kind = match.group("kind")
            desc = match.group("desc")
            transactions.append(
                Transaction(
                provider_id="tossbank-1000-1499-0535",
                institution_name="토스뱅크",
                source_kind="bank",
                transaction_id=f"{match.group('date')}-{match.group('time')}-{kind}-{match.group('amount')}-{desc}",
                posted_at=parse_datetime(
                    f"{match.group('date')} {match.group('time')}", ("%Y-%m-%d %H:%M:%S",)
                ),
                amount=amount,
                currency="KRW",
                direction=direction,
                merchant=desc,
                description=f"{kind} | {desc}",
                account_name=account_name,
                raw={"source_file": path.name, "balance": match.group("balance"), "kind": kind},
            )
            )
            pending_index = len(transactions) - 1
            continue

        if pending_index is not None and not line.startswith("거래내역서") and not line.startswith("이축복님") and not line.startswith("예금주") and not line.startswith("계좌번호") and not line.startswith("예금종류") and not line.startswith("조회기간") and not line.startswith("본 확인서") and not line.startswith("단위:") and not line.startswith("거래일자"):
            pending = transactions[pending_index]
            transactions[pending_index] = Transaction(
                provider_id=pending.provider_id,
                institution_name=pending.institution_name,
                source_kind=pending.source_kind,
                transaction_id=pending.transaction_id,
                posted_at=pending.posted_at,
                amount=pending.amount,
                currency=pending.currency,
                direction=pending.direction,
                merchant=f"{pending.merchant} {line}",
                description=f"{pending.description} {line}",
                account_name=pending.account_name,
                raw=pending.raw,
            )

    return transactions


def dedupe_by_key(transactions: Iterable[Transaction]) -> List[Transaction]:
    unique: Dict[str, Transaction] = {}
    for transaction in transactions:
        key = "|".join(
            [
                transaction.provider_id,
                transaction.transaction_id,
                transaction.posted_at.isoformat(),
                str(transaction.amount),
                transaction.direction,
                transaction.merchant,
            ]
        )
        unique[key] = transaction
    return sorted(unique.values(), key=lambda item: (item.posted_at, item.provider_id, item.transaction_id))


def is_card_payment(transaction: Transaction) -> bool:
    if transaction.source_kind != "bank" or transaction.direction != "outflow":
        return False
    text = f"{transaction.merchant} {transaction.description}"
    return any(keyword in text for keyword in (*CARD_PAYMENT_KEYWORDS, "신한카드"))


def categorize_transaction(transaction: Transaction) -> str:
    text = f"{transaction.merchant} {transaction.description}".lower()
    if "230364442742" in text:
        return "적금이체"
    if is_parking_transaction(transaction):
        return "주차비"
    if is_charging_transaction(transaction):
        return "충전"
    if is_fuel_transaction(transaction):
        return "주유"
    if is_management_fee_transaction(transaction):
        return "관리비"
    if any(keyword in text for keyword in ("이하나", "돌봄", "방과후")):
        return "교육비"
    if any(keyword in text for keyword in ("lgu+", "lguplus", "유플러스", "엘지유플러스")):
        return "통신비"
    if transaction.source_kind == "bank" and transaction.direction == "inflow":
        if "급여" in text:
            return "급여"
        if "이자" in text:
            return "이자"
        if any(keyword in text for keyword in ("펜타린크", "최수연", "이축복", "토뱅", "국민", "신한", "하나", "기업")):
            return "계좌이체입금"
        return "기타입금"
    if transaction.source_kind == "bank" and transaction.direction == "outflow":
        if is_card_payment(transaction):
            return "카드대금"
        if any(keyword in text for keyword in ("토뱅", "오픈뱅킹", "모바일뱅킹", "real", "rtc", "공동망")):
            return "계좌이체출금"
        if "자동이체" in text:
            return "자동이체"
        return "기타출금"

    if any(keyword in text for keyword in ("주유", "ev", "에버온")):
        return "교통/차량"
    if any(keyword in text for keyword in ("택시", "주차", "티머니", "도로공사", "일산대교", "고속도로")):
        return "교통/차량"
    if any(keyword in text for keyword in ("쿠팡", "우아한", "배민", "11번가", "네이버페이", "스토어", "당근", "이니시스")):
        return "쇼핑"
    if any(keyword in text for keyword in ("병원", "의원", "약국", "치과")):
        return "의료"
    if any(keyword in text for keyword in ("lguplus", "google *youtube", "피클플러스", "oculus", "microsoft", "카카오")):
        return "구독/디지털"
    if any(keyword in text for keyword in ("마트", "편의점", "gs25", "세븐일레븐", "올리브영", "이삭토스트", "빵", "식빵", "떡", "토스트", "도너츠", "돈까스", "세계로")):
        return "생활/식비"
    if any(keyword in text for keyword in ("아파트관리비", "도시가스", "주택금융공사", "교보", "한화손", "보험")):
        return "주거/공과금/보험"
    return "기타"


def display_merchant(transaction: Transaction) -> str:
    text = f"{transaction.merchant} {transaction.description}"
    if transaction.source_kind == "bank" and transaction.direction == "inflow":
        if transaction.institution_name == "입출금계좌" and transaction.merchant.startswith("신한") and "펜타린크" in text:
            return "이축복 월급"
        if transaction.institution_name == "신한은행" and "급여" in text:
            return "최수연 월급"
    return transaction.merchant


def is_salary_income(transaction: Transaction) -> bool:
    return (
        transaction.source_kind == "bank"
        and transaction.direction == "inflow"
        and display_merchant(transaction) in {"이축복 월급", "최수연 월급"}
    )


def is_internal_transfer_inflow(transaction: Transaction) -> bool:
    if transaction.source_kind != "bank" or transaction.direction != "inflow":
        return False
    if is_salary_income(transaction):
        return False
    merchant = display_merchant(transaction).strip()
    return merchant in {"이축복", "최수연", "토뱅 이축복", "토뱅  이축복", "비상금"}


def to_csv(path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize_amounts(transactions: Iterable[Transaction]) -> Decimal:
    return sum((txn.amount for txn in transactions), Decimal("0"))


def month_key(posted_at: datetime) -> str:
    return posted_at.strftime("%Y-%m")


def format_won(value: Decimal) -> str:
    return f"{int(value):,}원"


def format_report_transaction(transaction: Transaction) -> str:
    return (
        f"- {transaction.posted_at:%Y-%m-%d %H:%M} | "
        f"{format_won(transaction.amount)} | "
        f"{transaction.merchant} | "
        f"{transaction.description}"
    )


def filter_analysis_period(transactions: Iterable[Transaction]) -> List[Transaction]:
    return [
        txn
        for txn in transactions
        if ANALYSIS_START <= txn.posted_at <= ANALYSIS_END
    ]


def monthly_average_amount(transactions: Iterable[Transaction]) -> Decimal:
    monthly_totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for txn in transactions:
        monthly_totals[month_key(txn.posted_at)] += txn.amount
    if not monthly_totals:
        return Decimal("0")
    total = sum(monthly_totals.values(), Decimal("0"))
    return total / Decimal(len(monthly_totals))


def filter_fixed_expense_candidates(expenses: Iterable[FixedExpense]) -> List[FixedExpense]:
    filtered: List[FixedExpense] = []
    for expense in expenses:
        text = f"{expense.merchant} {expense.normalized_label}".lower()
        if expense.merchant.startswith("ＫＢ생") or expense.merchant.startswith("KB생"):
            continue
        if any(keyword.lower() in text for keyword in FIXED_EXPENSE_EXCLUDE_KEYWORDS):
            continue
        filtered.append(expense)
    return filtered


def is_management_fee_transaction(transaction: Transaction) -> bool:
    text = f"{transaction.merchant} {transaction.description} {transaction.account_name}".lower()
    return any(keyword in text for keyword in ("관리비", "중흥s클래스", "중흥에스클래스"))


def is_child_education_transaction(transaction: Transaction) -> bool:
    text = f"{transaction.merchant} {transaction.description} {transaction.account_name}".lower()
    return any(keyword in text for keyword in ("이*나", "이하나", "돌봄", "방과후"))


def is_telecom_transaction(transaction: Transaction) -> bool:
    text = f"{transaction.merchant} {transaction.description} {transaction.account_name}".lower()
    return any(keyword in text for keyword in ("lgu+", "lguplus", "유플러스", "엘지유플러스"))


def is_parking_transaction(transaction: Transaction) -> bool:
    text = f"{transaction.merchant} {transaction.description} {transaction.account_name}".lower()
    return (
        transaction.source_kind == "card"
        and transaction.direction == "outflow"
        and "카카오모빌리티" in text
        and transaction.amount <= Decimal("7500")
    )


def is_charging_transaction(transaction: Transaction) -> bool:
    text = f"{transaction.merchant} {transaction.description} {transaction.account_name}".lower()
    return any(
        keyword in text
        for keyword in (
            "충전",
            "전기차",
            "ev",
            "에버온",
            "evinfra",
            "ev infra",
            "환경부",
            "차지비",
            "이지차저",
            "파워큐브",
            "한국전력",
        )
    )


def is_fuel_transaction(transaction: Transaction) -> bool:
    text = f"{transaction.merchant} {transaction.description} {transaction.account_name}".lower()
    return any(
        keyword in text
        for keyword in (
            "주유",
            "주유소",
            "오일",
            "s-oil",
            "에스오일",
            "gs칼텍스",
            "sk에너지",
            "현대오일뱅크",
        )
    )


FIXED_EXPENSE_CATEGORY_ORDER = ["보험", "구독", "대출", "통신비", "자동차", "교육", "주거", "연금", "청년도약계좌", "용돈"]


def fixed_expense_category(expense: FixedExpense) -> str:
    merchant = expense.merchant.strip()
    if merchant in {"한화손０４５", "교보０３０００", "현대０３１１０", "한화손보００２건"}:
        return "보험"
    if merchant in {"(주)와이즐리컴퍼니"}:
        return "구독"
    if merchant in {"주택금융공사", "엄마"}:
        return "대출"
    if merchant in {"통신비 평균"}:
        return "통신비"
    if merchant in {"주유 평균", "충전 평균", "주차 평균"}:
        return "자동차"
    if merchant in {"이하나 교육비 평균", "이하나 미술학원"}:
        return "교육"
    if merchant in {"KB카드 관리비 평균"}:
        return "주거"
    if merchant in {"IRP", "IRP_ROBO"}:
        return "연금"
    if merchant in {"청년도약계좌"}:
        return "청년도약계좌"
    if merchant in {"이축복", "최수연", "이하나"}:
        return "용돈"
    return "기타"


def build_report(
    card_transactions: List[Transaction],
    account_transactions: List[Transaction],
    pure_account_transactions: List[Transaction],
) -> str:
    total_card_spend = summarize_amounts(txn for txn in card_transactions if txn.direction == "outflow")
    total_card_refunds = summarize_amounts(txn for txn in card_transactions if txn.direction == "inflow")
    salary_inflows = [txn for txn in pure_account_transactions if is_salary_income(txn)]
    account_inflow = summarize_amounts(salary_inflows)
    account_outflow = summarize_amounts(txn for txn in pure_account_transactions if txn.direction == "outflow")

    fixed_candidates = filter_fixed_expense_candidates(detect_fixed_expenses(card_transactions + pure_account_transactions))
    management_fee_transactions = sorted(
        (
            txn for txn in card_transactions
            if txn.institution_name == "KB국민카드" and txn.direction == "outflow" and is_management_fee_transaction(txn)
        ),
        key=lambda txn: txn.posted_at,
    )
    child_education_transactions = sorted(
        (
            txn for txn in card_transactions
            if txn.institution_name == "KB국민카드" and txn.direction == "outflow" and is_child_education_transaction(txn)
        ),
        key=lambda txn: txn.posted_at,
    )
    telecom_transactions = sorted(
        (
            txn for txn in card_transactions
            if txn.direction == "outflow" and is_telecom_transaction(txn)
        ),
        key=lambda txn: txn.posted_at,
    )
    parking_transactions = sorted(
        (
            txn for txn in card_transactions
            if is_parking_transaction(txn)
        ),
        key=lambda txn: txn.posted_at,
    )
    charging_transactions = sorted(
        (
            txn for txn in card_transactions
            if txn.direction == "outflow" and is_charging_transaction(txn)
        ),
        key=lambda txn: txn.posted_at,
    )
    fuel_transactions = sorted(
        (
            txn for txn in card_transactions
            if txn.direction == "outflow" and is_fuel_transaction(txn)
        ),
        key=lambda txn: txn.posted_at,
    )
    savings_transfers = sorted(
        (
            txn for txn in pure_account_transactions
            if txn.direction == "outflow" and categorize_transaction(txn) == "적금이체"
        ),
        key=lambda txn: txn.posted_at,
    )
    lines = [
        "# 자산 현황",
        "",
        "## 전체 요약",
        "- 기준 기간: 2025.04 ~ 2026.04",
        f"- 카드 사용 합계: {format_won(total_card_spend)}",
        f"- 계좌 순수 입금 합계: {format_won(account_inflow)}",
        f"- 계좌 순수 출금 합계: {format_won(account_outflow)}",
        f"- 카드대금 제외 계좌 출금 합계: {format_won(account_outflow)}",
        f"- 카드 취소/환불 합계: {format_won(total_card_refunds)}",
        "",
        "## KB 카드 관리비",
        "- KB카드 결제내역 중 중흥에스클래스 또는 아파트 관리비 관련 내역만 정리",
    ]
    management_total = sum((txn.amount for txn in management_fee_transactions), Decimal("0"))
    management_avg = (
        (management_total / Decimal(len(management_fee_transactions)))
        if management_fee_transactions
        else Decimal("0")
    )
    education_total = sum((txn.amount for txn in child_education_transactions), Decimal("0"))
    education_avg = monthly_average_amount(child_education_transactions)
    telecom_total = sum((txn.amount for txn in telecom_transactions), Decimal("0"))
    telecom_avg = monthly_average_amount(telecom_transactions)
    parking_total = sum((txn.amount for txn in parking_transactions), Decimal("0"))
    parking_avg = monthly_average_amount(parking_transactions)
    charging_total = sum((txn.amount for txn in charging_transactions), Decimal("0"))
    charging_avg = monthly_average_amount(charging_transactions)
    fuel_total = sum((txn.amount for txn in fuel_transactions), Decimal("0"))
    fuel_avg = monthly_average_amount(fuel_transactions)
    effective_fixed_candidates = list(fixed_candidates)
    if management_fee_transactions:
        effective_fixed_candidates.append(
            FixedExpense(
                merchant="KB카드 관리비 평균",
                normalized_label="kb관리비평균",
                source_kind="card",
                expected_amount=management_avg,
                currency="KRW",
                occurrences=len(management_fee_transactions),
                interval_days=30,
                last_posted_date=management_fee_transactions[-1].posted_at.date(),
                next_expected_date=None,
                provider_ids="kb-card",
            )
        )
    if child_education_transactions:
        effective_fixed_candidates.append(
            FixedExpense(
                merchant="이하나 교육비 평균",
                normalized_label="이하나교육비평균",
                source_kind="card",
                expected_amount=education_avg,
                currency="KRW",
                occurrences=len(child_education_transactions),
                interval_days=30,
                last_posted_date=child_education_transactions[-1].posted_at.date(),
                next_expected_date=None,
                provider_ids="kb-card",
            )
        )
    if telecom_transactions:
        effective_fixed_candidates.append(
            FixedExpense(
                merchant="통신비 평균",
                normalized_label="통신비평균",
                source_kind="card",
                expected_amount=telecom_avg,
                currency="KRW",
                occurrences=len(telecom_transactions),
                interval_days=30,
                last_posted_date=telecom_transactions[-1].posted_at.date(),
                next_expected_date=None,
                provider_ids=", ".join(sorted({txn.provider_id for txn in telecom_transactions})),
            )
        )
    if fuel_transactions:
        effective_fixed_candidates.append(
            FixedExpense(
                merchant="주유 평균",
                normalized_label="주유평균",
                source_kind="card",
                expected_amount=fuel_avg,
                currency="KRW",
                occurrences=len(fuel_transactions),
                interval_days=30,
                last_posted_date=fuel_transactions[-1].posted_at.date(),
                next_expected_date=None,
                provider_ids=", ".join(sorted({txn.provider_id for txn in fuel_transactions})),
            )
        )
    if charging_transactions:
        effective_fixed_candidates.append(
            FixedExpense(
                merchant="충전 평균",
                normalized_label="충전평균",
                source_kind="card",
                expected_amount=charging_avg,
                currency="KRW",
                occurrences=len(charging_transactions),
                interval_days=30,
                last_posted_date=charging_transactions[-1].posted_at.date(),
                next_expected_date=None,
                provider_ids=", ".join(sorted({txn.provider_id for txn in charging_transactions})),
            )
        )
    if parking_transactions:
        effective_fixed_candidates.append(
            FixedExpense(
                merchant="주차 평균",
                normalized_label="주차평균",
                source_kind="card",
                expected_amount=parking_avg,
                currency="KRW",
                occurrences=len(parking_transactions),
                interval_days=30,
                last_posted_date=parking_transactions[-1].posted_at.date(),
                next_expected_date=None,
                provider_ids=", ".join(sorted({txn.provider_id for txn in parking_transactions})),
            )
        )
    effective_fixed_candidates.extend(
        [
            FixedExpense(
                merchant="엄마",
                normalized_label="엄마",
                source_kind="manual",
                expected_amount=Decimal("200000"),
                currency="KRW",
                occurrences=0,
                interval_days=30,
                last_posted_date=ANALYSIS_END.date(),
                next_expected_date=None,
                provider_ids="manual",
            ),
            FixedExpense(
                merchant="이하나 미술학원",
                normalized_label="이하나미술학원",
                source_kind="manual",
                expected_amount=Decimal("75000"),
                currency="KRW",
                occurrences=0,
                interval_days=30,
                last_posted_date=ANALYSIS_END.date(),
                next_expected_date=None,
                provider_ids="manual",
            ),
            FixedExpense(
                merchant="IRP",
                normalized_label="irp",
                source_kind="manual",
                expected_amount=Decimal("300000"),
                currency="KRW",
                occurrences=0,
                interval_days=30,
                last_posted_date=ANALYSIS_END.date(),
                next_expected_date=None,
                provider_ids="manual",
            ),
            FixedExpense(
                merchant="IRP_ROBO",
                normalized_label="irp_robo",
                source_kind="manual",
                expected_amount=Decimal("200000"),
                currency="KRW",
                occurrences=0,
                interval_days=30,
                last_posted_date=ANALYSIS_END.date(),
                next_expected_date=None,
                provider_ids="manual",
            ),
            FixedExpense(
                merchant="이축복",
                normalized_label="이축복",
                source_kind="manual",
                expected_amount=Decimal("600000"),
                currency="KRW",
                occurrences=0,
                interval_days=30,
                last_posted_date=ANALYSIS_END.date(),
                next_expected_date=None,
                provider_ids="manual",
            ),
            FixedExpense(
                merchant="최수연",
                normalized_label="최수연",
                source_kind="manual",
                expected_amount=Decimal("300000"),
                currency="KRW",
                occurrences=0,
                interval_days=30,
                last_posted_date=ANALYSIS_END.date(),
                next_expected_date=None,
                provider_ids="manual",
            ),
            FixedExpense(
                merchant="이하나",
                normalized_label="이하나",
                source_kind="manual",
                expected_amount=Decimal("20000"),
                currency="KRW",
                occurrences=0,
                interval_days=30,
                last_posted_date=ANALYSIS_END.date(),
                next_expected_date=None,
                provider_ids="manual",
            ),
            FixedExpense(
                merchant="청년도약계좌",
                normalized_label="청년도약계좌",
                source_kind="manual",
                expected_amount=Decimal("700000"),
                currency="KRW",
                occurrences=0,
                interval_days=30,
                last_posted_date=ANALYSIS_END.date(),
                next_expected_date=None,
                provider_ids="manual",
            ),
        ]
    )
    fixed_expense_groups: Dict[str, List[FixedExpense]] = defaultdict(list)
    for item in effective_fixed_candidates:
        fixed_expense_groups[fixed_expense_category(item)].append(item)
    monthly_fixed_total = sum((item.expected_amount for item in effective_fixed_candidates), Decimal("0"))
    monthly_disposable_income = MONTHLY_SALARY_BASE - monthly_fixed_total
    if management_fee_transactions:
        for txn in management_fee_transactions:
            lines.append(format_report_transaction(txn))
    else:
        lines.append("- 없음")

    lines.extend(["", "## 이하나 교육비"])
    lines.append("- KB카드 결제내역 중 돌봄, 방과후 관련 내역만 정리")
    if child_education_transactions:
        for txn in child_education_transactions:
            lines.append(format_report_transaction(txn))
    else:
        lines.append("- 없음")

    lines.extend(["", "## 통신비"])
    lines.append("- LGU+ 또는 엘지유플러스 관련 결제내역만 정리")
    if telecom_transactions:
        for txn in telecom_transactions:
            lines.append(format_report_transaction(txn))
    else:
        lines.append("- 없음")

    lines.extend(["", "## 주차비"])
    lines.append("- 카카오모빌리티 주차 관련 결제내역만 정리")
    if parking_transactions:
        for txn in parking_transactions:
            lines.append(format_report_transaction(txn))
    else:
        lines.append("- 없음")

    lines.extend(["", "## 주유"])
    lines.append("- 주유소라는 단어가 들어간 결제내역만 정리")
    if fuel_transactions:
        for txn in fuel_transactions:
            lines.append(format_report_transaction(txn))
    else:
        lines.append("- 없음")

    lines.extend(["", "## 충전"])
    lines.append("- 전기차 충전 관련 결제내역만 정리")
    if charging_transactions:
        for txn in charging_transactions:
            lines.append(format_report_transaction(txn))
    else:
        lines.append("- 없음")

    lines.extend(["", "## 적금 이체"])
    lines.append("- 적금이체로 분류된 계좌 출금 내역만 정리")
    if savings_transfers:
        for txn in savings_transfers:
            lines.append(format_report_transaction(txn))
    else:
        lines.append("- 없음")

    lines.extend(["", "## 고정지출"])
    lines.append(f"- 매월 고정지출 총액(추정): {format_won(monthly_fixed_total)}")
    if effective_fixed_candidates:
        for category in FIXED_EXPENSE_CATEGORY_ORDER:
            items = fixed_expense_groups.get(category, [])
            category_total = sum((item.expected_amount for item in items), Decimal("0"))
            lines.append(f"- {category}: {format_won(category_total)}")
            for item in items:
                lines.append(
                    f"  - {item.merchant}: {format_won(item.expected_amount)} / {item.occurrences}회 / 약 {item.interval_days}일 간격 / 다음 예상 {item.next_expected_date}"
                )
    else:
        lines.append("- 없음")

    lines.extend(["", "## 생활비가용금액"])
    lines.append(f"- 월 급여 기준: {format_won(MONTHLY_SALARY_BASE)}")
    lines.append(f"- 월 고정지출 차감: {format_won(monthly_fixed_total)}")
    lines.append(f"- 생활비가용금액: {format_won(monthly_disposable_income)}")

    return "\n".join(lines) + "\n"


def analyze_local_ledger(project_root: Path) -> Dict[str, Path]:
    excel_dir = project_root / "excel"
    report_dir = project_root / "reports"
    selected_files = resolve_input_files(excel_dir, report_dir)
    hyundai_card = selected_files["hyundai_card"]
    shinhan_cards = selected_files["shinhan_cards"]
    kb_card = selected_files["kb_card"]
    account_exports = selected_files["account_exports"]
    shinhan_bank_exports = selected_files["shinhan_bank_exports"]
    pdf_text = selected_files["pdf_text"]

    if not isinstance(hyundai_card, Path) or not isinstance(kb_card, Path):
        raise FileNotFoundError("Card input files were not resolved correctly")
    if not isinstance(shinhan_cards, list) or not isinstance(account_exports, list) or not isinstance(shinhan_bank_exports, list):
        raise FileNotFoundError("Bank input files were not resolved correctly")

    card_transactions = dedupe_by_key(
        filter_analysis_period(
            load_hyundai_cards(hyundai_card)
            + load_shinhan_cards(shinhan_cards)
            + load_kb_cards(kb_card)
        )
    )
    account_transactions = dedupe_by_key(
        filter_analysis_period(
            load_account_transactions(account_exports)
            + load_shinhan_bank_transactions(shinhan_bank_exports)
            + (
                load_tossbank_pdf_transactions(pdf_text)
                if isinstance(pdf_text, Path)
                else []
            )
        )
    )
    pure_account_transactions = [txn for txn in account_transactions if not is_card_payment(txn)]

    card_csv = report_dir / "card_transactions_deduped.csv"
    account_csv = report_dir / "account_transactions_deduped.csv"
    pure_account_csv = report_dir / "account_transactions_excluding_card_payments.csv"
    report_md = report_dir / "ledger_summary.md"
    notion_csv = report_dir / "notion_transactions_import.csv"
    monthly_csv = report_dir / "monthly_summary.csv"
    category_csv = report_dir / "category_summary.csv"
    input_manifest = report_dir / "input_manifest.json"

    to_csv(
        card_csv,
        [
            {
                "posted_at": txn.posted_at.isoformat(sep=" "),
                "institution": txn.institution_name,
                "merchant": display_merchant(txn),
                "amount": str(txn.amount),
                "direction": txn.direction,
                "category": categorize_transaction(txn),
                "description": txn.description,
                "account_name": txn.account_name,
                "transaction_id": txn.transaction_id,
            }
            for txn in card_transactions
        ],
        ["posted_at", "institution", "merchant", "amount", "direction", "category", "description", "account_name", "transaction_id"],
    )
    to_csv(
        account_csv,
        [
            {
                "posted_at": txn.posted_at.isoformat(sep=" "),
                "direction": txn.direction,
                "amount": str(txn.amount),
                "merchant": display_merchant(txn),
                "category": categorize_transaction(txn),
                "description": txn.description,
                "source_file": str(txn.raw.get("source_file", "")),
                "balance": str(txn.raw.get("balance", "")),
                "is_card_payment": "Y" if is_card_payment(txn) else "N",
            }
            for txn in account_transactions
        ],
        ["posted_at", "direction", "amount", "merchant", "category", "description", "source_file", "balance", "is_card_payment"],
    )
    to_csv(
        pure_account_csv,
        [
            {
                "posted_at": txn.posted_at.isoformat(sep=" "),
                "direction": txn.direction,
                "amount": str(txn.amount),
                "merchant": display_merchant(txn),
                "category": categorize_transaction(txn),
                "description": txn.description,
                "source_file": str(txn.raw.get("source_file", "")),
                "balance": str(txn.raw.get("balance", "")),
            }
            for txn in pure_account_transactions
        ],
        ["posted_at", "direction", "amount", "merchant", "category", "description", "source_file", "balance"],
    )
    unified_transactions = sorted(card_transactions + pure_account_transactions, key=lambda txn: txn.posted_at)
    to_csv(
        notion_csv,
        [
            {
                "Name": display_merchant(txn) or txn.description or txn.account_name,
                "Posted At": txn.posted_at.isoformat(sep=" "),
                "Institution": txn.institution_name,
                "Source Type": txn.source_kind,
                "Account": txn.account_name,
                "Direction": txn.direction,
                "Amount": str(txn.amount if txn.direction == "inflow" else -txn.amount),
                "Absolute Amount": str(txn.amount),
                "Currency": txn.currency,
                "Category": categorize_transaction(txn),
                "Description": txn.description,
                "Provider ID": txn.provider_id,
                "Transaction ID": txn.transaction_id,
            }
            for txn in unified_transactions
        ],
        ["Name", "Posted At", "Institution", "Source Type", "Account", "Direction", "Amount", "Absolute Amount", "Currency", "Category", "Description", "Provider ID", "Transaction ID"],
    )

    monthly_totals: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: {"card_spend": Decimal("0"), "account_inflow": Decimal("0"), "account_outflow": Decimal("0")})
    for txn in card_transactions:
        if txn.direction == "outflow":
            monthly_totals[month_key(txn.posted_at)]["card_spend"] += txn.amount
    for txn in pure_account_transactions:
        monthly_totals[month_key(txn.posted_at)][f"account_{txn.direction}"] += txn.amount
    to_csv(
        monthly_csv,
        [
            {
                "month": month,
                "card_spend": str(values["card_spend"]),
                "account_inflow": str(values["account_inflow"]),
                "account_outflow": str(values["account_outflow"]),
                "net_account_flow": str(values["account_inflow"] - values["account_outflow"]),
            }
            for month, values in sorted(monthly_totals.items())
        ],
        ["month", "card_spend", "account_inflow", "account_outflow", "net_account_flow"],
    )

    category_totals: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for txn in unified_transactions:
        if txn.direction == "outflow":
            category_totals[categorize_transaction(txn)] += txn.amount
    to_csv(
        category_csv,
        [
            {"category": category, "amount": str(amount)}
            for category, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
        ],
        ["category", "amount"],
    )
    report_md.write_text(
        build_report(card_transactions, account_transactions, pure_account_transactions),
        encoding="utf-8-sig",
    )
    input_manifest.write_text(
        json.dumps(
            {
                "selected_inputs": {
                    key: (
                        [str(path.relative_to(project_root)) for path in value]
                        if isinstance(value, list)
                        else (str(value.relative_to(project_root)) if isinstance(value, Path) else None)
                    )
                    for key, value in selected_files.items()
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "card_csv": card_csv,
        "account_csv": account_csv,
        "pure_account_csv": pure_account_csv,
        "report_md": report_md,
        "notion_csv": notion_csv,
        "monthly_csv": monthly_csv,
        "category_csv": category_csv,
        "input_manifest": input_manifest,
    }
