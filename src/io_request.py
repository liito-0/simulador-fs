"""Requisição de E/S associada a um bloco físico do disco."""
from dataclasses import dataclass
from typing import Literal


@dataclass
class IORequest:
    op: Literal["R", "W"]
    block: int
    track: int
    owner: str
