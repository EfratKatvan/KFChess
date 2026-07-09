from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Command:
    name: str
    args: List[str]


def parse_line(line: str) -> Optional[Command]:
    parts = line.strip().split()
    if not parts:
        return None
    return Command(parts[0], parts[1:])
