from dataclasses import dataclass
from typing import TypeAlias

Bytes: TypeAlias = int


@dataclass(slots=True, frozen=True)
class FileInfo:
    url: str
    size: Bytes
    name: str
    extension: str
    mime_type: str
