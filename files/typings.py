from dataclasses import dataclass
from typing import TypeAlias

Bytes: TypeAlias = int


@dataclass(slots=True, frozen=True)
class UserFileInfo:
    size: Bytes
    name: str
    extension: str
    mime_type: str
