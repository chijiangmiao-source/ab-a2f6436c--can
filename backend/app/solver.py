"""Exact solver for 11-bit CAN acceptance filter configurations.

Problem statement
-----------------
A filter is a pair ``(code, mask)`` of 11-bit integers.  An incoming CAN id
``x`` is accepted when ``(x & mask) == (code & mask)``.  Only bits where the
mask is 1 are compared, so the code MUST have zero in every un-compared bit
(we canonicalise every code as ``code & mask``).

Given a set of *allowed* ids (telemetry that must be received) and a set of
*forbidden* ids (disabled frames that must never be received), find a list of
at most ``limit`` filters such that:

* every allowed id is accepted by at least one filter (full coverage), and
* no forbidden id is accepted by any filter (zero exposure).

Optimal solutions are found exactly, ordered by the lexicographic objective

1. number of filters,
2. sum over filters of the number of ids (0..2047) each filter accepts,
3. lexicographically smallest sorted ``(mask, code)`` sequence.

The optimisation is a branch-and-bound DFS with MRV branching.  Allowed sets
have at most 20 elements, so coverage is tracked with a single machine word.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

ID_BITS = 11
ID_SPACE = 1 << ID_BITS  # 2048
ALL_IDS = ID_SPACE - 1


def _popcount(x: int) -> int:
    return x.bit_count()


def _iter_bits(mask: int):
    """Yield indices of set bits, ascending."""
    while mask:
        lsb = mask & -mask
        yield lsb.bit_length() - 1
        mask ^= lsb


@dataclass(frozen=True)
class Filter:
    """A canonical (code, mask) acceptance filter."""

    code: int
    mask: int

    def accepted_count(self) -> int:
        """Number of 11-bit ids this filter accepts."""
        return 1 << (ID_BITS - _popcount(self.mask))

    def accepts(self, can_id: int) -> bool:
        return (can_id & self.mask) == self.code

    def matched(self, ids: Sequence[int]) -> List[int]:
        return [x for x in ids if self.accepts(x)]


@dataclass
class Candidate:
    """Internal solver representation of a feasible filter."""

    code: int
    mask: int
    cover: int  # bit mask of covered allowed ids (bit i -> allowed[i])
    cost: int  # how many 11-bit ids the filter accepts (acceptance width)

    @property
    def key(self) -> Tuple[int, int]:
        # (mask, code) ordering used for the tertiary tie-break
        return (self.mask, self.code)


@dataclass
class SolveResult:
    feasible: bool
    filters: List[Filter]
    exhausted: bool  # True => search space up to `limit` was fully explored
    candidate_count: int


def _build_candidates(allowed: Sequence[int], forbidden: Sequence[int]) -> List[Candidate]:
    """Enumerate every feasible filter.

    For each mask a filter's code is fully determined by the shared projection
    of a group of allowed ids: ``code = id & mask``.  A projection is feasible
    iff no forbidden id projects onto the same code.  Because code must have
    zero un-compared bits, ``id & mask`` is the only legal code for the group.

    Only provably safe dominance pruning is applied: a candidate is removed if
    another candidate covers a superset and is strictly cheaper (it can never
    occur in a count/cost-optimal solution), or if it is identical in cover and
    cost with a lexicographically smaller key.  Equal-cost strict-superset
    candidates are kept, because dropping the smaller one could destroy the
    tertiary (lexicographic) optimum.
    """
    forbidden_set = set(forbidden)
    raw: dict[int, dict[int, Tuple[int, int]]] = {}
    # raw[cost][cover] = smallest (mask, code) key producing that cover at
    # that cost.  cost depends only on popcount(mask) (12 distinct values).
    for mask in range(ID_SPACE):
        groups: dict[int, int] = {}
        for i, aid in enumerate(allowed):
            code = aid & mask
            groups[code] = groups.get(code, 0) | (1 << i)

        bad_projections = {fid & mask for fid in forbidden_set}
        cost = 1 << (ID_BITS - _popcount(mask))
        bucket = raw.setdefault(cost, {})

        for code, cover in groups.items():
            if code in bad_projections:
                continue
            key = (mask, code)
            old = bucket.get(cover)
            if old is None or key < old:
                bucket[cover] = key

    # Safe dominance pruning, processing buckets from cheapest to costliest.
    # `maximals` is the inclusion-maximal antichain of covers from STRICTLY
    # CHEAPER buckets.  A cover is dominated iff some maximal y is a superset
    # of it (y is a strictly cheaper filter covering everything it does).
    # Equal-cost entries never prune one another: a strict superset at equal
    # cost can belong to the lexicographically smallest optimum.  All status
    # checks for a bucket therefore run BEFORE the survivors are merged into
    # the antichain (merging early would discard cheap singleton dominators -
    # e.g. exact matches - when a later wide cover arrives).
    maximals: List[int] = []
    kept: List[Candidate] = []
    for cost in sorted(raw):
        bucket = raw[cost]

        # Phase 1: status against strictly cheaper witnesses only.
        surviving: List[Tuple[int, Tuple[int, int]]] = []
        for cover, key in bucket.items():
            if not any((y | cover) == y for y in maximals):
                surviving.append((cover, key))

        for cover, key in surviving:
            kept.append(Candidate(code=key[1], mask=key[0], cover=cover, cost=cost))

        # Phase 2: merge all survivors into the antichain.  For future
        # (costlier) buckets every survivor is a strictly cheaper witness, so
        # keeping only inclusion-maximal covers is exact.
        for cover, _ in surviving:
            if any((y | cover) == y for y in maximals):
                continue
            maximals = [y for y in maximals if (y | cover) != cover]
            maximals.append(cover)

    # Canonical order: ascending (mask, code).
    kept.sort(key=lambda c: c.key)
    return kept


def solve(
    allowed: Sequence[int],
    forbidden: Sequence[int],
    limit: int,
) -> SolveResult:
    """Find the optimal filter set, or report that none exists within ``limit``.

    The search is exhaustive, so ``exhausted`` is always True: a False result
    means every combination of up to ``limit`` feasible filters was considered.
    """
    allowed = list(dict.fromkeys(allowed))  # de-duplicate, preserve order
    n = len(allowed)
    full = (1 << n) - 1

    candidates = _build_candidates(allowed, forbidden)
    m = len(candidates)
    keys = [c.key for c in candidates]
    covers = [c.cover for c in candidates]
    costs = [c.cost for c in candidates]

    # Exact-match filters (mask = ALL_IDS) are always feasible for every
    # allowed id because allowed/forbidden never overlap, hence each allowed id
    # is coverable by at least one candidate.
    coverable = 0
    for c in candidates:
        coverable |= c.cover
    if coverable != full:  # defensive; unreachable under validated inputs
        return SolveResult(False, [], True, m)

    # Incumbent: (num_filters, total_cost, tuple of candidate indices).
    # The tertiary tie-break compares the sorted key sequence.
    incumbent: Optional[Tuple[int, int, Tuple[int, ...]]] = None

    def sorted_keys(idx_tuple: Tuple[int, ...]) -> Tuple[Tuple[int, int], ...]:
        return tuple(sorted(keys[i] for i in idx_tuple))

    def is_better(sol: Tuple[int, int, Tuple[int, ...]]) -> bool:
        nonlocal incumbent
        if incumbent is None:
            return True
        if (sol[0], sol[1]) != (incumbent[0], incumbent[1]):
            return (sol[0], sol[1]) < (incumbent[0], incumbent[1])
        return sorted_keys(sol[2]) < sorted_keys(incumbent[2])

    # For each allowed bit, the set of candidates covering it (as a bit mask
    # over candidate indices).
    coverers_of_bit: List[int] = [0] * n
    for i, cv in enumerate(covers):
        bit = 0
        x = cv
        while x:
            if x & 1:
                coverers_of_bit[bit] |= 1 << i
            x >>= 1
            bit += 1

    def lower_bound_count(missing_bits: int, avail: int) -> int:
        """Admissible lower bound on additional filters needed.

        The union of k sets has at most as many bits as the sum of their
        individual contributions, so k filters can cover at most the sum of
        the k largest single-set contributions.
        """
        sizes = []
        a = avail
        while a:
            lsb = a & -a
            i = lsb.bit_length() - 1
            new_bits = _popcount(covers[i] & missing_bits)
            if new_bits:
                sizes.append(new_bits)
            a ^= lsb
        sizes.sort(reverse=True)
        total = 0
        for k, size in enumerate(sizes, start=1):
            total += size
            if total >= _popcount(missing_bits):
                return k
        return len(sizes) + 1  # nothing covers some remaining bit

    def dfs(covered: int, avail: int, depth: int, total_cost: int,
            chosen: Tuple[int, ...]) -> None:
        nonlocal incumbent

        if covered == full:
            sol = (depth, total_cost, chosen)
            if is_better(sol):
                incumbent = sol
            return

        remaining_slots = limit - depth
        if remaining_slots <= 0:
            return
        if incumbent is not None and depth >= incumbent[0]:
            return

        missing_bits = full ^ covered

        # Available candidates that contribute at least one new allowed id.
        contributing = 0
        a = avail
        while a:
            lsb = a & -a
            i = lsb.bit_length() - 1
            if covers[i] & missing_bits:
                contributing |= lsb
            a ^= lsb
        if not contributing:
            return

        # If a single available candidate finishes coverage, stop here: any
        # multi-filter continuation is strictly worse in the primary
        # objective.  Record the cheapest, then lexicographically smallest,
        # one-filter completion.
        finishers: List[int] = []
        c = contributing
        while c:
            lsb = c & -c
            i = lsb.bit_length() - 1
            if (covers[i] & missing_bits) == missing_bits:
                finishers.append(i)
            c ^= lsb
        if finishers:
            best = min(finishers, key=lambda i: (costs[i], keys[i]))
            sol = (depth + 1, total_cost + costs[best], chosen + (best,))
            if is_better(sol):
                incumbent = sol
            return

        lb = lower_bound_count(missing_bits, contributing)
        if lb > remaining_slots:
            return
        if incumbent is not None:
            if depth + lb > incumbent[0]:
                return
            # Cheapest possible additional filter costs >= min contributing cost.
            min_cost = min(costs[i] for i in _iter_bits(contributing))
            if depth + lb == incumbent[0] and total_cost + lb * min_cost > incumbent[1]:
                return

        # MRV: uncovered allowed id with fewest available covering candidates.
        best_bit = -1
        best_degree = m + 1
        for bit in range(n):
            if not ((missing_bits >> bit) & 1):
                continue
            degree = _popcount(avail & coverers_of_bit[bit])
            if degree < best_degree:
                best_degree, best_bit = degree, bit
                if degree == 1:
                    break

        # Canonical branches: let c be the smallest-index filter in the
        # solution that covers `best_bit`.  For each available covering
        # candidate c: include c and forbid every covering candidate with
        # index <= c (c itself is now chosen).  Branches are disjoint and
        # complete, and never regenerate permutations.
        choices_mask = avail & coverers_of_bit[best_bit]
        choices = list(_iter_bits(choices_mask))
        choices.sort(
            key=lambda i: (
                -_popcount(covers[i] & missing_bits),
                costs[i],
                keys[i],
            )
        )

        for bi in choices:
            if incumbent is not None and depth + 1 > incumbent[0]:
                break
            forbidden_now = coverers_of_bit[best_bit] & ((1 << (bi + 1)) - 1)
            dfs(
                covered | covers[bi],
                (avail & ~forbidden_now) & ~(1 << bi),
                depth + 1,
                total_cost + costs[bi],
                chosen + (bi,),
            )

    all_avail = (1 << m) - 1
    dfs(0, all_avail, 0, 0, ())

    if incumbent is None:
        return SolveResult(False, [], True, m)

    filters = [Filter(code=keys[i][1], mask=keys[i][0]) for i in incumbent[2]]
    filters.sort(key=lambda f: (f.mask, f.code))
    return SolveResult(True, filters, True, m)


def coverage_matrix(filters: Sequence[Filter], allowed: Sequence[int]) -> List[List[bool]]:
    """Rows are filters (sorted (mask, code)), columns are allowed ids."""
    return [[f.accepts(a) for a in allowed] for f in filters]


def exposure(f: Filter, forbidden: Sequence[int]) -> List[int]:
    """Forbidden ids a filter accepts (always empty for solver output)."""
    return [x for x in forbidden if f.accepts(x)]
