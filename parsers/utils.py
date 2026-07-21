"""Shared utilities for parsers."""
import re
from typing import Optional, Tuple, List


def extract_budget_range_from_text(text: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Extract budget min/max from text.

    Args:
        text: Budget text like "5000 - 10000 ₽"

    Returns:
        Tuple of (min, max) or (None, None)
    """
    if not text:
        return None, None
    clean = text.replace("\xa0", " ").replace(" ", "").replace("₽", "").replace("руб.", "")
    numbers = re.findall(r"\d+", clean)
    values = [int(n) for n in numbers if int(n) > 10]
    if len(values) >= 2:
        return min(values), max(values)
    elif len(values) == 1:
        return values[0], values[0]
    return None, None


def extract_deadline_days(text: Optional[str]) -> Optional[int]:
    """Extract deadline in days from text.

    Args:
        text: Deadline text like "5 дней" or "2 недели"

    Returns:
        Number of days or None
    """
    if not text:
        return None
    text_lower = text.lower()

    # Check for weeks
    weeks_match = re.search(r"(\d+)\s*(?:недел|неделю|недели)", text_lower)
    if weeks_match:
        return int(weeks_match.group(1)) * 7

    # Check for days
    days_match = re.search(r"(\d+)\s*д(?:\.|[няей]+)", text_lower)
    if days_match:
        days = int(days_match.group(1))
        hours_match = re.search(r"(\d+)\s*ч(?:\.|[асов]+)", text_lower)
        if hours_match and int(hours_match.group(1)) >= 12:
            days += 1
        return days

    # Check for months
    months_match = re.search(r"(\d+)\s*(?:месяц|месяца|месяцев)", text_lower)
    if months_match:
        return int(months_match.group(1)) * 30

    # Check for hours
    hours_match = re.search(r"(\d+)\s*ч(?:\.|[асов]+)", text_lower)
    if hours_match:
        return 1 if int(hours_match.group(1)) > 0 else 0

    numbers = re.findall(r"\d+", text)
    return int(numbers[0]) if numbers else None


def extract_numbers(text: Optional[str]) -> List[int]:
    """Extract all numbers from text.

    Args:
        text: Input text

    Returns:
        List of integers found in text
    """
    if not text:
        return []
    numbers = re.findall(r"\d+", text.replace(" ", "").replace("\u2009", ""))
    return [int(n) for n in numbers]


def extract_budget_values(text: Optional[str]) -> List[int]:
    """Extract budget values from text (numbers > 100).

    Args:
        text: Input text

    Returns:
        List of budget values
    """
    values = extract_numbers(text)
    return [v for v in values if v > 100]
