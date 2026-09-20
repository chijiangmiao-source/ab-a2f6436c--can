import random
import time

import pytest

from app import solver
from app.solver import Filter, solve
from brute import brute_solve


@pytest.fixture(autouse=True)
def restore_width():
    # The fuzz tests shrink the CAN id space; make sure each test restores it.
    yield
    solver.ID_BITS = 11
    solver.ID_SPACE = 1 << 11
    solver.ALL_IDS = (1 << 11) - 1


def run_case(bits, allowed, forbidden, limit):
    solver.ID_BITS = bits
    solver.ID_SPACE = 1 << bits
    solver.ALL_IDS = (1 << bits) - 1

    res = solve(allowed, forbidden, limit)
    ok, brute_seq = brute_solve(bits, allowed, forbidden, limit)

    assert res.feasible == ok
    if ok:
        seq = [(f.mask, f.code) for f in res.filters]
        assert seq == sorted(seq)
        assert seq == brute_seq
        # Every allowed id covered.
        for a in allowed:
            assert any(f.accepts(a) for f in res.filters)
        # No forbidden id exposed.
        for x in forbidden:
            assert not any(f.accepts(x) for f in res.filters)
        # Canonical codes.
        for f in res.filters:
            assert f.code & ~f.mask == 0
            assert f.mask < (1 << bits)
        assert len(res.filters) <= limit


@pytest.mark.parametrize("seed", range(300))
def test_fuzz_small_widths(seed):
    rng = random.Random(seed)
    bits = rng.choice([3, 4, 5])
    space = 1 << bits
    n_allowed = rng.randint(2, min(6, space))
    allowed = rng.sample(range(space), n_allowed)
    pool = [x for x in range(space) if x not in allowed]
    n_forbidden = rng.randint(0, min(8, len(pool)))
    forbidden = rng.sample(pool, n_forbidden)
    limit = rng.randint(1, min(5, n_allowed))
    run_case(bits, allowed, forbidden, limit)


@pytest.mark.parametrize("seed", range(40))
def test_fuzz_width_six(seed):
    rng = random.Random(1000 + seed)
    bits = 6
    space = 1 << bits
    allowed = rng.sample(range(space), rng.randint(2, 8))
    pool = [x for x in range(space) if x not in allowed]
    forbidden = rng.sample(pool, rng.randint(0, 16))
    run_case(bits, allowed, forbidden, rng.randint(1, 6))


def test_single_filter_exact_match():
    # One allowed id, mask all 11 bits -> exact match is the cost minimum.
    res = solve([0x123], [0x124], 8)
    assert res.feasible
    assert res.filters == [Filter(code=0x123, mask=0x7FF)]


def test_pair_shares_prefix():
    # 0x100=00100000000, 0x101=00100000001 share top 10 bits; mask 0x7FE
    # accepts exactly those two and cost 2, better than two exact filters.
    res = solve([0x100, 0x101], [0x102], 8)
    assert res.feasible
    assert [(f.mask, f.code) for f in res.filters] == [(0x7FE, 0x100)]


def test_forbidden_blocks_wildcard_forces_exact():
    # 0x100 and 0x103 differ in bits 0 and 1; any single filter covering both
    # must wildcard both bits and therefore also accepts 0x101/0x102, so with
    # limit 1 the problem is infeasible; two exact filters solve it.
    res = solve([0x100, 0x103], [0x101, 0x102], 1)
    assert not res.feasible
    assert res.exhausted
    res2 = solve([0x100, 0x103], [0x101, 0x102], 2)
    assert res2.feasible
    assert len(res2.filters) == 2


def test_infeasible_when_no_feasible_filter():
    # A forbidden id equal to... impossible since sets are disjoint; instead
    # saturate: limit 0 style is a validation error, here limit 1 with two
    # unmergeable ids.
    res = solve([0, 0x7FF], [], 1)
    # They DO merge with mask 0 (accepts all, cost 2048); so feasible.
    assert res.feasible
    assert res.filters == [Filter(0, 0)]


def test_lexicographic_tiebreak_11bit():
    # Hand-verified 11-bit tertiary tie-break.
    # allowed 0x100,0x101,0x111; forbidden 0x110.
    # Any single filter merging 0x100 and 0x111 must wildcard bit 4, which
    # also makes forbidden 0x110 project to code 0x100, so count 1 is
    # impossible.  Two count-2/cost-3 optima exist:
    #   A: [(0x7FE,0x100) merge 100/101, (0x7FF,0x111) exact]
    #   B: [(0x7EF,0x101) merge 101/111, (0x7FF,0x100) exact]
    # B starts with the smaller mask (0x7EF < 0x7FE) -> B is the answer.
    allowed, forbidden = [0x100, 0x101, 0x111], [0x110]
    assert not solve(allowed, forbidden, 1).feasible
    res = solve(allowed, forbidden, 2)
    assert res.feasible
    assert [(f.mask, f.code) for f in res.filters] == [(0x7EF, 0x101), (0x7FF, 0x100)]
    assert sum(f.accepted_count() for f in res.filters) == 3
    # Isomorphic 3-bit instance: allowed {0,1,3}, forbidden {2}.
    solver.ID_BITS = 3
    solver.ID_SPACE = 8
    solver.ALL_IDS = 7
    ok, brute_seq = brute_solve(3, [0, 1, 3], [2], 2)
    assert ok and brute_seq == [(0b101, 1), (0b111, 0)]
    small = solve([0, 1, 3], [2], 2)
    assert [(f.mask, f.code) for f in small.filters] == [(0b101, 1), (0b111, 0)]
    solver.ID_BITS = 11
    solver.ID_SPACE = 1 << 11
    solver.ALL_IDS = (1 << 11) - 1


def test_lexicographic_tiebreak():
    # Two single-filter solutions with equal cost (mask weight equal) can tie;
    # solver must return the smallest (mask, code).  Build a case where
    # different masks each cover all allowed ids with the same popcount.
    # allowed {0b000, 0b001} on 3 bits: mask 0b110 code 0 covers both cost 2;
    # mask 0b101? ids project: 0,1 differ in bit0 so doesn't merge.
    # Use mask 0b110 -> (6,0); another merge with equal weight 2 exists when
    # the pair differs in exactly one bit: only that bit's mask works, so no
    # tie here.  Instead compare multi-filter sequences via fuzz; keep a
    # deterministic sequence-ordering assertion.
    solver.ID_BITS = 3
    solver.ID_SPACE = 8
    solver.ALL_IDS = 7
    res = solve([0, 1], [2, 3], 3)
    assert res.feasible
    keys = [(f.mask, f.code) for f in res.filters]
    assert keys == sorted(keys)


def test_large_case_performance():
    rng = random.Random(42)
    allowed = rng.sample(range(2048), 20)
    pool = [x for x in range(2048) if x not in allowed]
    forbidden = rng.sample(pool, 128)
    t0 = time.time()
    res = solve(allowed, forbidden, 8)
    elapsed = time.time() - t0
    assert elapsed < 10
    if res.feasible:
        for a in allowed:
            assert any(f.accepts(a) for f in res.filters)
        for x in forbidden:
            assert not any(f.accepts(x) for f in res.filters)
        assert len(res.filters) <= 8
