"""
Shared utility functions.
"""

import re
from typing import Any


def normalize_name(name: str) -> str:
    """Lowercase, strip whitespace, collapse internal whitespace."""
    return re.sub(r"\s+", " ", name.strip().lower())


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float safely, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def truncate_label(label: str, max_len: int = 25) -> str:
    """Truncate a string for display, appending '...' if needed."""
    return label[:max_len] + "..." if len(label) > max_len else label


def strip_version_suffix(skill_name: str) -> str:
    """
    Remove version numbers from skill names for better matching.
    e.g. 'Python 3.11' → 'Python', 'Node.js 18' → 'Node.js'
    """
    return re.sub(r"\s+\d+[\.\d]*$", "", skill_name.strip())


def build_explanation_text(scores: dict[str, float], weights: dict[str, float]) -> str:
    """Build a human-readable explanation from score components and their weights."""
    lines = []
    for component, score in scores.items():
        weight = weights.get(component, 0.0)
        contribution = score * weight
        lines.append(
            f"{component.replace('_', ' ').title()}: "
            f"{score:.0%} match (contributes {contribution:.1%} to total)"
        )
    return " | ".join(lines)
