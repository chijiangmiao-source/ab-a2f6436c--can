"""Exact CAN acceptance-filter solver.

A filter is an 11-bit ``(code, mask)`` pair.  Identifier ``x`` is accepted
iff ``(x & mask) == (code & mask)``; the bits of ``code`` where ``mask`` is
zero must themselves be zero ("code must clear un-compared bits").

Every valid filter therefore corresponds to a sub-cube of the 11-bit
identifier space -- a length-11 pattern of ``0`` / ``1`` / ``x`` -- with an
11-bit ``mask`` and a canonical ``code`` (zero outside the mask).  We
generate the relevant sub-cubes by bucketing allowed/forbidden identifiers
per mask (all 2**11 masks).

The solver searches for at most ``limit`` filters that, in order of priority

  1. accept every allowed identifier,
  2. accept no forbidden identifier,
  3. minimise the number of filters,
  4. among those, minimise the sum of accepted-identifier counts
     (2 ** (# zero bits of mask)) of the chosen filters,
  5. among those, minimise the sorted ``(mask, code)`` sequence in
     lexicographic order.

It returns ``None`` when no feasible cover exists within the limit.  The
search is an exact memoised set-cover DP: branching only over filters that
cover a pivot (least uncovered) identifier keeps the search exhaustive
without enumerating permutations, and a set-packing lower bound prunes
branches that cannot beat the incumbent on objectives 3 and 4.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

ID_BITS = 11
ID_MAX = 1 << ID_BITS  # 2048
FULL_ID_MASK = ID_MAX - 1

# A canonical filter: (mask, code) with code & ~mask == 0.
Pattern = Tuple[int, int]


def build_candidates(
    allowed: Sequence[int], forbidden: Sequence[int]
) -> Tuple[List[Pattern], List[int], List[int]]:
    """Return ``(patterns, cover_bits, costs)`` for every useful filter.

    A candidate accepts at least one allowed identifier and no forbidden
    identifier.  For each distinct subset of covered allowed identifiers we
    keep only the filter with minimum accepted-identifier cost, breaking
    ties toward the lexicographically smaller ``(mask, code)``: every other
    filter with the same coverage is worse on objective 4 (or 5).
    """
    allowed = sorted(allowed)
    index_of = {x: i for i, x in enumerate(allowed)}
    n_allowed = len(allowed)

    # covered-bitmask -> (minimum cost, smallest pattern at that cost)
    best: Dict[int, Tuple[int, Pattern]] = {}

    for mask in range(ID_MAX):
        forbidden_buckets = {y & mask for y in forbidden}
        buckets: Dict[int, int] = {}
        for x in allowed:
            b = x & mask
            buckets[b] = buckets.get(b, 0) | (1 << index_of[x])
        cost = ID_MAX >> mask.bit_count()  # identifiers the filter accepts
        for code, cover in buckets.items():
            if code in forbidden_buckets:
                continue  # the filter would also accept a forbidden id
            pat = (mask, code)
            old = best.get(cover)
            if old is None or (cost, pat) < old:
                best[cover] = (cost, pat)

    items = sorted(
        ((pat, cover, cost) for cover, (cost, pat) in best.items()),
        key=lambda t: (t[2], t[0]),
    )
    patterns = [t[0] for t in items]
    cover_bits = [t[1] for t in items]
    costs = [t[2] for t in items]
    return patterns, cover_bits, costs


def solve(
    allowed: Sequence[int],
    forbidden: Sequence[int],
    limit: int,
) -> Optional[List[Pattern]]:
    """Return the optimal filter list in ascending ``(mask, code)`` order.

    ``None`` means the feasible space within ``limit`` was exhausted with no
    cover.
    """
    allowed = sorted(set(allowed))
    n_allowed = len(allowed)
    patterns, cover_bits, costs = build_candidates(allowed, forbidden)
    full = (1 << n_allowed) - 1

    # Candidate indices covering each allowed bit (cost/pattern ordered).
    owners: List[List[int]] = [[] for _ in range(n_allowed)]
    for i, cov in enumerate(cover_bits):
        b = cov
        while b:
            bit = b & -b
            owners[bit.bit_length() - 1].append(i)
            b ^= bit
    if any(not o for o in owners):
        # An allowed id is only co-accepted with a forbidden id: infeasible.
        return None

    # Data for the set-packing lower bound.  Two allowed bits that never
    # co-occur in any candidate cover cannot be served by the same filter.
    # blocked[b] is the union of all candidate covers containing bit b.
    blocked = [0] * n_allowed
    min_cost_owner = [10**9] * n_allowed
    for b in range(n_allowed):
        u = 0
        for i in owners[b]:
            u |= cover_bits[i]
            if costs[i] < min_cost_owner[b]:
                min_cost_owner[b] = costs[i]
        blocked[b] = u

    def packing_lb(need: int) -> Tuple[int, int]:
        """Greedy set-packing bound: (minimum filters, minimum cost sum).

        Greedily pick needed bits no single filter can jointly cover with a
        previously picked bit; each picked bit forces a distinct filter, so
        the count is a lower bound on filter count and the sum of the
        cheapest owner costs is a lower bound on total cost.
        """
        cnt = 0
        cost_lb = 0
        remaining = need
        while remaining:
            b = (remaining & -remaining).bit_length() - 1
            cnt += 1
            cost_lb += min_cost_owner[b]
            remaining &= ~blocked[b]
        return cnt, cost_lb

    global_count_lb, _ = packing_lb(full)
    if global_count_lb > limit:
        return None

    INF_COST = 10**18

    def _greedy(mode: str) -> Optional[Tuple[int, int]]:
        """A deterministic greedy feasible cover: (filter count, cost).

        mode "width" picks the filter covering the most still-needed bits
        (fewest filters); mode "rate" picks the cheapest per newly covered
        bit; mode "cheap" picks the cheapest filter overall.  Different
        modes give different (count, cost) trade-offs for tighter search
        budgets at each filter count.
        """
        need = full
        cnt = 0
        total = 0
        while need:
            if cnt >= limit:
                return None
            pivot = (need & -need).bit_length() - 1
            best_i = -1
            best_key = None
            for i in owners[pivot]:
                new = int.bit_count(cover_bits[i] & need)
                if new == 0:
                    continue
                if mode == "width":
                    key = (new, -costs[i], -patterns[i][0], -patterns[i][1])
                elif mode == "rate":
                    key = (-costs[i] / new, new, -patterns[i][0], -patterns[i][1])
                else:  # cheap
                    key = (-costs[i], new, -patterns[i][0], -patterns[i][1])
                if best_key is None or key > best_key:
                    best_key = key
                    best_i = i
            if best_i < 0:
                return None
            cnt += 1
            total += costs[best_i]
            need &= ~cover_bits[best_i]
        return (cnt, total)

    # Smallest known cover cost for each exact filter count; the iteration
    # for count k uses budgets[k] as its cost cap.
    budgets: Dict[int, int] = {}
    for mode in ("width", "rate", "cheap"):
        seed = _greedy(mode)
        if seed is not None:
            budgets[seed[0]] = min(budgets.get(seed[0], INF_COST), seed[1])

    # Feasibility-only memo (no cost dimension): can `need` be covered by
    # at most `kleft` candidates?  Shared across all cost budgets, this
    # proves infeasible filter counts quickly.
    @lru_cache(maxsize=None)
    def feas(need: int, kleft: int) -> bool:
        if need == 0:
            return True
        if kleft <= 0:
            return False
        lb_cnt, _ = packing_lb(need)
        if lb_cnt > kleft:
            return False
        # Each remaining filter covers at most `max_new` of the needed
        # bits, so kleft filters cover at most kleft * max_new of them.
        max_new = 0
        b = need
        while b:
            bit = b & -b
            i_owner = owners[bit.bit_length() - 1]
            for i in i_owner:
                v = int.bit_count(cover_bits[i] & need)
                if v > max_new:
                    max_new = v
            b ^= bit
        if int.bit_count(need) > kleft * max_new:
            return False
        pivot = (need & -need).bit_length() - 1
        for i in owners[pivot]:
            rest = need & ~cover_bits[i]
            if rest == need:
                continue
            if feas(rest, kleft - 1):
                return True
        return False

    # Exact DP for a *fixed* filter count: minimum (cost, sorted pattern
    # sequence) covering `need` with exactly `kleft` filters, spending no
    # more than `cost_left`.  Iterating k = 1..limit implements objective
    # 3; the tuple comparison implements objectives 4 and 5.  Memoising on
    # all three arguments keeps answers valid as the budget changes.
    @lru_cache(maxsize=None)
    def opt(
        need: int, kleft: int, cost_left: int
    ) -> Tuple[int, Tuple[Pattern, ...]]:
        if need == 0:
            return (0, ()) if kleft == 0 else (INF_COST, ())
        if kleft <= 0:
            return (INF_COST, ())
        if not feas(need, kleft):
            return (INF_COST, ())
        pivot = (need & -need).bit_length() - 1
        best_cost = INF_COST
        best_seq: Tuple[Pattern, ...] = ()
        for i in owners[pivot]:
            rest = need & ~cover_bits[i]
            if rest == need:
                continue  # adds no needed bit
            lb_cnt, lb_cost = packing_lb(rest)
            if lb_cnt > kleft - 1:
                continue
            if costs[i] + lb_cost > cost_left:
                continue
            sub_cost, sub_seq = opt(rest, kleft - 1, cost_left - costs[i])
            if sub_cost >= INF_COST:
                continue
            total = costs[i] + sub_cost
            seq = tuple(sorted((patterns[i],) + sub_seq))
            if (total, seq) < (best_cost, best_seq):
                best_cost = total
                best_seq = seq
        return (best_cost, best_seq)

    for k in range(1, limit + 1):
        budget = budgets.get(k, INF_COST)
        final_cost, seq = opt(full, k, budget)
        if final_cost < INF_COST:
            return list(seq)
    return None


def accepts(mask: int, code: int, x: int) -> bool:
    """Identifier ``x`` is accepted by filter ``(mask, code)``."""
    return (x & mask) == (code & mask)


def accepted_count(mask: int) -> int:
    """Number of 11-bit identifiers accepted by a filter with this mask."""
    return ID_MAX >> mask.bit_count()


def covered_allowed(mask: int, code: int, allowed: Sequence[int]) -> List[int]:
    """Allowed identifiers accepted by the filter, ascending."""
    return sorted(x for x in allowed if accepts(mask, code, x))
