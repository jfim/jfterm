from __future__ import annotations

from collections.abc import Callable, Iterable

BOUNDARY = 10
CONSECUTIVE = 5
BASE = 1

_BOUNDARY_CHARS = frozenset(" :_-/")


def _is_boundary(candidate: str, j: int) -> bool:
    if j == 0:
        return True
    prev = candidate[j - 1]
    if prev in _BOUNDARY_CHARS:
        return True
    cur = candidate[j]
    return prev.islower() and cur.isupper()


def _matches(q: str, q_lower: str, c_lower: str, candidate: str, j: int) -> bool:
    if q_lower != c_lower:
        return False
    if q.isupper():
        return candidate[j].isupper() or _is_boundary(candidate, j)
    return True


def score(query: str, candidate: str) -> int | None:
    """Return a non-negative score for fuzzy-matching query against
    candidate, or None when no subsequence match exists.

    Higher is better. See module docstring for the bonus constants.
    """
    if query == "":
        return 0
    n, m = len(query), len(candidate)
    if n > m:
        return None
    # Lower-case each character once, preserving one entry per source
    # index. Indexing the original positions stays correct even for
    # characters whose lowercase expands to multiple code points (e.g.
    # 'İ' -> 'i' + combining dot); a whole-string .lower() would shift
    # every later index and corrupt the match.
    query_lower = [ch.lower() for ch in query]
    candidate_lower = [ch.lower() for ch in candidate]
    NEG = -1
    prev = [NEG] * m
    q0 = query[0]
    q0_lower = query_lower[0]
    for j in range(m):
        if _matches(q0, q0_lower, candidate_lower[j], candidate, j):
            bonus = BOUNDARY if _is_boundary(candidate, j) else 0
            prev[j] = BASE + bonus
    if n == 1:
        best = max((v for v in prev if v != NEG), default=NEG)
        return best if best != NEG else None
    for i in range(2, n + 1):
        cur = [NEG] * m
        qi = query[i - 1]
        qi_lower = query_lower[i - 1]
        running_best_prev = NEG
        running_best_prev_j = -1
        for j in range(m):
            if j > 0 and prev[j - 1] > running_best_prev:
                running_best_prev = prev[j - 1]
                running_best_prev_j = j - 1
            if not _matches(qi, qi_lower, candidate_lower[j], candidate, j):
                continue
            if running_best_prev == NEG:
                continue
            bonus = BOUNDARY if _is_boundary(candidate, j) else 0
            consec = CONSECUTIVE if running_best_prev_j == j - 1 else 0
            if running_best_prev_j == j - 1:
                cur[j] = prev[j - 1] + BASE + bonus + consec
                non_consec = running_best_prev + BASE + bonus
                if non_consec > cur[j]:
                    cur[j] = non_consec
            else:
                cur[j] = running_best_prev + BASE + bonus
        prev = cur
    best = max((v for v in prev if v != NEG), default=NEG)
    return best if best != NEG else None


def rank[T](query: str, items: Iterable[T], key: Callable[[T], str]) -> list[T]:
    """Return items sorted by descending score against query, dropping
    items that don't match. Stable on ties (preserves input order)."""
    scored: list[tuple[int, int, T]] = []
    for idx, item in enumerate(items):
        s = score(query, key(item))
        if s is None:
            continue
        scored.append((-s, idx, item))
    scored.sort()
    return [item for _, _, item in scored]
