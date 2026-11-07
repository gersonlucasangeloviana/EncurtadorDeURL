from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Link:
    short_code: str
    sequence_id: int
    destination_url: str
    project_name: str | None = None
    public_path: str | None = None
    expires_at: datetime | None = None
    active: bool = True
    deleted: bool = False
    version: int = 1
