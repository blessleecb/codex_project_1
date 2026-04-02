from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Iterable

from auto_ledger.models import Transaction


class Provider(ABC):
    id: str
    name: str
    kind: str

    @abstractmethod
    def fetch_transactions(self, start_date: date, end_date: date) -> Iterable[Transaction]:
        raise NotImplementedError
