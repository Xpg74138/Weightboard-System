"""Default output locations, without machine-specific source paths."""
import os
import sys
from pathlib import Path


def artifact_path(*parts) -> str:
    root = Path.cwd() if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    target = root.joinpath("artifacts", *parts)
    os.makedirs(str(target.parent), exist_ok=True)
    return str(target)
