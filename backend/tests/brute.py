"""Reference brute-force solver used only for cross-checking tests.

It works on a configurable bit width so exhaustive verification is cheap.
"""
from __future__ import annotations

from itertools import combinations
from typing import List, Optional, Sequence, Tuple


def brute_solve(bits: int, allowed: Sequence[int], forbidden: Sequence[int],
                limit: int):
    space = 1 << bits
    allowed = list(dict.fromkeys(allowed))
    forbidden_set = set(forbidden)

    # Enumerate feasible filters independently of the production solver.
    filters: List[Tuple[int, int, int, int]] = []  # (mask, code, cover, cost)
    for mask in range(space):
        groups = {}
        for i, aid in enumerate(allowed):
            code = aid & mask
            groups.setdefault(code, []).append(i)
        bad = {fid & mask for fid in forbidden_set}
        for code, idxs in groups.items():
            if code in bad:
                continue
            cover = 0
            for i in idxs:
                cover |= 1 << i
            cost = 1 << (bits - mask.bit_count())
            filters.append((mask, code, cover, cost))

    filters.sort(key=lambda f: (f[0], f[1]))
    n = len(allowed)
    full = (1 << n) - 1

    best: Optional[Tuple[int, int, Tuple[Tuple[int, int], ...]]] = None
    for size in range(1, limit + 1):
        for combo in combinations(filters, size):
            cover = 0
            cost = 0
            for _, _, c, w in combo:
                cover |= c
                cost += w
            if cover != full:
                continue
            seq = tuple((m, c) for m, c, _, _ in combo)
            cand = (size, cost, seq)
            if best is None or (cand[0], cand[1], cand[2]) < best:
                best = cand
        if best is not None:
            return True, list(best[2])
    return False, []
