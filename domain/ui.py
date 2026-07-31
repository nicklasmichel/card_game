from dataclasses import dataclass


@dataclass
class ButtonSpec:
    label: str
    enabled: bool
    action: str
