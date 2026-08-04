"""Per-user ordering of delivered/listed order cards (task_0004).

A small, pure re-ordering engine used both by the worker (notification
delivery order per user) and by any V2 list surface. It never changes the
legacy ``DEFAULT`` behaviour: when a user has no explicit preference the
cards keep their as-arrived (insertion) order, so existing tests/pipelines
are unaffected.

Sort contract (documented here once, enforced by tests):
    * ``DEFAULT``  → items returned unchanged.
    * ``SCORE``    → descending by ``analysis.win_probability``.
    * ``PROFITABILITY`` → descending by ``analysis.profitability_index``.
    * ``FRESHNESS`` → descending by ``project.posted_at`` (newest first).
    * Unknown/missing sort values (``None``) always sort last.
    * Ties keep the original insertion order (stable sort).
"""

from typing import Any, Callable, List, Optional, Sequence

from core.models import SortPreference

#: Sort-value accessors per preference; each takes an item exposing
#: ``.project`` (Project) and ``.analysis`` (Optional[ProjectAnalysis]).
_KEY_FUNCS: dict[SortPreference, Callable[[Any], Any]] = {
    SortPreference.SCORE: lambda it: (
        it.analysis.win_probability if it.analysis is not None else None
    ),
    SortPreference.PROFITABILITY: lambda it: (
        it.analysis.profitability_index if it.analysis is not None else None
    ),
    SortPreference.FRESHNESS: lambda it: it.project.posted_at,
}


def _ordered_key(value: Any) -> tuple:
    """Encode a sort value into a single ascending-sort key.

    ``None`` (unknown) → last. Datetimes are converted to a float timestamp.
    Negating the numeric value turns the ascending ``sorted`` into a
    descending effective order (largest first).
    """
    if value is None:
        return (1, 0.0)
    if hasattr(value, "timestamp"):
        value = value.timestamp()
    return (0, -float(value))


def sort_project_cards(
    items: Sequence[Any], preference: Optional[SortPreference | str]
) -> List[Any]:
    """Return ``items`` re-ordered per the user's sort preference.

    Args:
        items: Cards to sort. Each item must expose a ``.project``
            (Project) and an ``.analysis`` (``Optional[ProjectAnalysis]``)
            attribute — both the worker's notification rows and any V2
            list view can adapt to this contract.
        preference: A ``SortPreference`` (or its string value). ``None`` or
            ``SortPreference.DEFAULT`` returns the original order.

    Returns:
        A new list with the sorted cards. The input is never mutated.
    """
    items = list(items)
    if preference is None:
        return items
    pref = (
        SortPreference(preference)
        if not isinstance(preference, SortPreference)
        else preference
    )
    if pref is SortPreference.DEFAULT:
        return items
    key = _KEY_FUNCS[pref]
    return sorted(items, key=lambda it: _ordered_key(key(it)))


__all__ = ["sort_project_cards"]
