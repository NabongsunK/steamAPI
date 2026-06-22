"""마인크래프트 서버 로그 tail (admin 후원 디버깅)."""

from __future__ import annotations

import os
import re
from pathlib import Path

_DONATION_PATTERNS = re.compile(
    r"donation|setSessionsId|getSessionsId|nrDonation|NR-Donation|"
    r"WebSocket server started|\bopen:|\bclose:|user//event",
    re.IGNORECASE,
)


class McLogService:
    def __init__(self, *, log_path: str, scan_lines: int = 2000, max_lines: int = 80):
        self._path = Path(os.path.expanduser(log_path)) if log_path else None
        self._scan_lines = max(100, scan_lines)
        self._max_lines = max(10, max_lines)

    @property
    def log_path(self) -> str:
        return str(self._path) if self._path else ""

    def read_donation_logs(self, *, all_lines: bool = False) -> dict:
        if not self._path:
            return {
                "configured": False,
                "path": "",
                "exists": False,
                "lines": [],
                "message": "MC_LOG_PATH 미설정",
            }

        path_str = str(self._path)
        if not self._path.is_file():
            return {
                "configured": True,
                "path": path_str,
                "exists": False,
                "lines": [],
                "message": f"로그 파일 없음: {path_str}",
            }

        raw = self._tail_text(self._path, self._scan_lines)
        if all_lines:
            lines = raw[-self._max_lines :]
        else:
            lines = [line for line in raw if _DONATION_PATTERNS.search(line)]
            lines = lines[-self._max_lines :]

        return {
            "configured": True,
            "path": path_str,
            "exists": True,
            "filtered": not all_lines,
            "lines": lines,
            "line_count": len(lines),
        }

    @staticmethod
    def _tail_text(path: Path, max_lines: int) -> list[str]:
        chunk_size = 256 * 1024
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - chunk_size))
            data = f.read().decode("utf-8", errors="replace")
        lines = data.splitlines()
        return lines[-max_lines:]
