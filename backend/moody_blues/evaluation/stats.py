"""The little statistics this project can honestly use.

Samples here are tiny, so everything is an exact interval on raw counts. There are no significance
tests: the trials were not drawn to support one, and a p-value would suggest more than they show.
"""

from __future__ import annotations

from math import comb


def _tail_at_least(k: int, n: int, p: float) -> float:
    return sum(comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def _solve_tail(k: int, n: int, target: float) -> float:
    """The p at which P(X >= k) equals target. The tail rises with p."""
    low, high = 0.0, 1.0
    for _ in range(60):
        middle = (low + high) / 2
        if _tail_at_least(k, n, middle) < target:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def clopper_pearson(k: int, n: int, *, confidence: float = 0.95) -> tuple[float, float] | None:
    """Exact two-sided interval for k events in n trials. None when there are no trials."""
    if not 0 <= k <= n:
        raise ValueError(f"impossible count {k} of {n}")
    if n == 0:
        return None
    alpha = 1 - confidence
    lower = 0.0 if k == 0 else _solve_tail(k, n, alpha / 2)
    # Upper bound: the p at which seeing k or fewer has probability alpha/2.
    upper = 1.0 if k == n else _solve_tail(k + 1, n, 1 - alpha / 2)
    return round(lower, 4), round(upper, 4)


def rate_text(k: int, n: int) -> str:
    """Raw counts first. A percentage alone hides how little a small sample says."""
    interval = clopper_pearson(k, n)
    if interval is None:
        return f"{k}/{n}"
    return f"{k}/{n} (95% exact CI {interval[0]:.0%}-{interval[1]:.0%})"
