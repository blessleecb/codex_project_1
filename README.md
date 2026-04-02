# 로컬 자산현황 분석 대시보드

`excel/` 아래의 카드사·은행 원본 파일을 읽어 `reports/`에 분석 결과를 만들고, `dashboard/` 정적 React 페이지로 시각화하는 프로젝트다.

핵심 흐름은 아래와 같다.

1. `excel/` 원본 파일 자동 탐색
2. Python으로 거래내역 정규화, 중복 제거, 카테고리 분류, 고정지출 추정
3. `reports/*.csv`, `reports/ledger_summary.md`, `reports/input_manifest.json` 생성
4. `dashboard/`에서 생성된 보고서를 불러와 대시보드 렌더링

## 디렉토리 구조

- `excel/`: 카드/은행 원본 파일
- `src/auto_ledger/local_ledger_analysis.py`: 로컬 분석 본체
- `src/auto_ledger/local_cli.py`: 분석/서빙용 CLI
- `src/auto_ledger/local_dashboard.py`: 대시보드용 로컬 HTTP 서버
- `dashboard/`: React 기반 정적 대시보드
- `reports/`: 생성 결과물

## 입력 파일 자동 인식

분석기는 이제 파일명을 완전히 고정하지 않고 패턴 기준으로 가장 알맞은 파일을 선택한다.

- 현대카드: `*hyundaicard*.xlsx`, `*현대카드*.xlsx`
- 신한카드: `Shinhancard*.xls`, `*신한카드*.xls`
- KB국민카드: `*카드이용내역*.xls`, `*KB*카드*.xls`, `*국민카드*.xls`
- 입출금계좌: `inquiry_*.xls`
- 신한은행: `*신한은행*거래내역조회*.xls`, `신한은행_*`
- PDF 추출 텍스트: `reports/pdf_extracted_text.txt` 우선, 없으면 `reports/*.txt` 또는 `excel/*.txt` 탐색

실제로 어떤 파일이 선택되었는지는 `reports/input_manifest.json`에 기록된다.

## 실행 환경

Python 3.9 이상이면 된다.

로컬 Excel 분석은 외부 패키지 없이 동작하도록 구성돼 있다. Notion 연동 기능까지 사용할 때만 `requests`가 필요하다.

## 설치

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

만약 `py`가 없다면 설치된 Python 경로에 맞춰 `python`으로 바꿔 실행하면 된다.

## 실행 방법

### 1. 보고서만 재생성

```bash
python -m auto_ledger.local_cli analyze
```

또는 설치 후:

```bash
auto-ledger-local analyze
```

생성 결과:

- `reports/card_transactions_deduped.csv`
- `reports/account_transactions_deduped.csv`
- `reports/account_transactions_excluding_card_payments.csv`
- `reports/notion_transactions_import.csv`
- `reports/monthly_summary.csv`
- `reports/category_summary.csv`
- `reports/ledger_summary.md`
- `reports/input_manifest.json`

### 2. 대시보드만 실행

```bash
python -m auto_ledger.local_cli serve --open
```

기본 주소는 아래다.

```text
http://127.0.0.1:4173/dashboard/
```

### 3. 분석 후 바로 대시보드 실행

```bash
python -m auto_ledger.local_cli all --open
```

또는 설치 후:

```bash
auto-ledger-local all --open
```

## 대시보드에서 보이는 내용

- 월 가용 생활비
- 월 고정지출
- 최신 월 순증감
- 최대 지출 카테고리
- 최근 6개월 카드/입출금 흐름
- 상위 지출 카테고리
- 고정지출 도넛/바 차트
- 이번 보고서 생성에 사용된 입력 파일 목록
- 관리비, 교육비, 통신비, 주차비, 주유, 충전, 적금이체, 고정지출, 생활비가용금액, 최근 입금/출금 상세 섹션

## PDF 관련

토스뱅크 PDF는 직접 PDF를 읽지 않고 텍스트 추출본을 사용한다. 기존 macOS용 추출 스크립트는 아래 파일이다.

- `scripts/extract_pdf_text.swift`

기존처럼 macOS에서 텍스트를 먼저 만든 뒤 `reports/pdf_extracted_text.txt`로 저장하면 분석에 자동 반영된다.

## 테스트

### macOS / Linux

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

### Windows PowerShell

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## 참고

- 기존 Notion 연동 CLI는 그대로 `python -m auto_ledger.cli`로 유지된다.
- 로컬 자산현황 분석은 `auto_ledger.local_cli`가 별도로 담당한다.
