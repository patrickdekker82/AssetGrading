from dataclasses import dataclass, field
from typing import Any


@dataclass
class Report:
    """Counters and errors of one job run; stored as job_run.summary."""

    counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def error(self, message: str) -> None:
        self.errors.append(message[:500])

    def note_once(self, message: str) -> None:
        if message[:300] not in self.notes:
            self.notes.append(message[:300])

    def as_dict(self) -> dict[str, Any]:
        return {"counts": self.counts, "errors": self.errors[:200], "error_count": len(self.errors),
                "notes": self.notes}
