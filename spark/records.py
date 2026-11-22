"""发送记录（JSONL），用于「每个好友每天最多一条」的幂等判断。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path


class SentRecords:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                self._records.append(record)

    def has_sent_today(self, platform: str, friend_key: str, today: date | None = None) -> bool:
        today = today or date.today()
        return any(
            record.get("platform") == platform
            and record.get("friend_key") == friend_key
            and self._record_date(record) == today
            for record in self._records
        )

    def last_message(self, platform: str, friend_key: str) -> str | None:
        """取该好友最近一次发送的文案，用于避免连续两天完全相同。"""
        for record in reversed(self._records):
            if record.get("platform") == platform and record.get("friend_key") == friend_key:
                message = str(record.get("message") or "").strip()
                return message or None
        return None

    def add(self, platform: str, friend_key: str, friend_name: str, message: str) -> datetime:
        sent_at = datetime.now().astimezone()
        record = {
            "platform": platform,
            "friend_key": friend_key,
            "friend_name": friend_name,
            "message": message,
            "sent_at": sent_at.isoformat(timespec="seconds"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._records.append(record)
        return sent_at

    @staticmethod
    def _record_date(record: dict) -> date | None:
        raw = str(record.get("sent_at") or "")
        try:
            return datetime.fromisoformat(raw).astimezone().date()
        except ValueError:
            return None
