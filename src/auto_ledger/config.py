from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


def load_dotenv(dotenv_path: str = ".env") -> None:
    path = Path(dotenv_path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class AppConfig:
    notion_token: str
    transactions_database_id: str
    fixed_expenses_database_id: str
    providers_config_path: Path

    @classmethod
    def from_env(cls) -> "AppConfig":
        load_dotenv()
        return cls(
            notion_token=os.environ["NOTION_TOKEN"],
            transactions_database_id=os.environ["NOTION_TRANSACTIONS_DATABASE_ID"],
            fixed_expenses_database_id=os.environ["NOTION_FIXED_EXPENSES_DATABASE_ID"],
            providers_config_path=Path(
                os.environ.get("PROVIDERS_CONFIG_PATH", "config/providers.json")
            ),
        )

    def load_provider_specs(self) -> List[Dict[str, Any]]:
        return json.loads(self.providers_config_path.read_text(encoding="utf-8"))
