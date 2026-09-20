#!/usr/bin/env python3
"""End-to-end acceptance checks for the CAN acceptance-filter audit stack.

Runs against the running Compose services using only the Python standard
library:

  * black-box HTTP checks against the web entry point (nginx -> API),
  * soundness + optimality verification of every returned solution,
  * solver-level equivalence checks against a brute-force oracle,
  * per-field validation and the exhausted-search verdict.

Environment:
  WEB_URL  public web origin          (default http://web)
  API_URL  direct API origin          (default http://api:8000)

Exits 0 only if every check passes.
"""
from __future__ import annotations

import itertools
import json
import os
import random
import sys
import urllib.error
import urllib.request

WEB_URL = os.environ.get("WEB_URL", "http://web").rstrip("/")
API_URL = os.environ.get("API_URL", "http://api:8000").rstrip("/")

ID_BITS = 11
ID_MAX = 1 << ID_BITS
ID_MASK = ID_MAX - 1

failures: list[str] = []
checks = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        failures.append(f"{name}: {detail}")


def post(url: str, payload: dict):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def get(url: str):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def accepts(mask: int, code: int, x: int) -> bool:
    return (x & mask) == (code & mask)


def assert_solution_sound(body: dict, allowed: list, forbidden: list, limit: int):
    """Validate every soundness rule from the specification on a result."""
    filters = body["filters"]
    check(
        "filter count within limit",
        1 <= len(filters) <= limit,
        f"got {len(filters)}",
    )
    total_exposure = 0
    for f in filters:
        mask, code = f["mask"], f["code"]
        check(
            f"filter#{f['index']} code clears un-compared bits",
            code & ~mask == 0,
            f"mask={mask} code={code}",
        )
        check(
            f"filter#{f['index']} binary rendering length",
            len(f["mask_bin"]) == len(f["code_bin"]) == len(f["pattern"]) == 11,
            f.get("pattern"),
        )
        expected_count = ID_MAX >> mask.bit_count()
        check(
            f"filter#{f['index']} exposure = 2^(11-popcount(mask))",
            f["accepted_count"] == expected_count,
            f"{f['accepted_count']} != {expected_count}",
        )
        total_exposure += expected_count
        for y in forbidden:
            if accepts(mask, code, y):
                check(
                    f"filter#{f['index']} rejects forbidden {y}",
                    False,
                    f"mask={mask} code={code}",
                )
                break
        else:
            check(f"filter#{f['index']} rejects all forbidden", True)
        # hits reported by API must be exact
        expect_hits = sorted(x for x in allowed if accepts(mask, code, x))
        check(
            f"filter#{f['index']} reported hits exact",
            f["hits"] == expect_hits,
            f"{f['hits']} != {expect_hits}",
        )
        check(f"filter#{f['index']} forbidden_hits empty", f["forbidden_hits"] == [])
    check(
        "total exposure matches sum",
        body["total_accepted_count"] == total_exposure,
        f"{body['total_accepted_count']} != {total_exposure}",
    )
    # complete coverage evidence
    covered = {x: False for x in allowed}
    for f in filters:
        for x in f["hits"]:
            covered[x] = True
    check("every allowed id covered", all(covered.values()), str(covered))
    ev = {e["identifier"]: e["accepted_by"] for e in body["coverage"]}
    check(
        "coverage evidence lists every allowed id",
        sorted(ev) == sorted(allowed),
    )
    check("coverage evidence non-empty for each id", all(v for v in ev.values()))
    for fc in body["forbidden_check"]:
        check(
            f"forbidden {fc['identifier']} rejected by every filter",
            len(fc["rejected_by"]) == len(filters),
        )
    # sorted (mask, code) sequence
    seq = [(f["mask"], f["code"]) for f in filters]
    check("returned sequence is sorted", seq == sorted(seq), str(seq))


def brute_force_opt(allowed, forbidden, limit):
    """Independent oracle: enumerate all 3**11 sub-cubes, then exact cover."""
    candidates = {}
    for mask in range(ID_MAX):
        fb = {y & mask for y in forbidden}
        buckets = {}
        for x in allowed:
            buckets.setdefault(x & mask, []).append(x)
        cost = ID_MAX >> mask.bit_count()
        for code, xs in buckets.items():
            if code in fb:
                continue
            key = frozenset(xs)
            pat = (mask, code)
            old = candidates.get(key)
            if old is None or (cost, pat) < old:
                candidates[key] = (cost, pat)
    items = [(pat, cov, cost) for cov, (cost, pat) in candidates.items()]
    best = None
    for r in range(0, min(len(items), limit) + 1):
        for combo in itertools.combinations(range(len(items)), r):
            union = set()
            cost_sum = 0
            for i in combo:
                union |= items[i][1]
                cost_sum += items[i][2]
            if union != set(allowed):
                continue
            key = (r, cost_sum, tuple(sorted(items[i][0] for i in combo)))
            if best is None or key < best:
                best = key
        if best:
            break
    return None if best is None else list(best[2])


def main() -> int:
    print("== service health ==")
    try:
        check("web /health via nginx", get(f"{WEB_URL}/health")["status"] == "ok")
        check("api direct /health", get(f"{API_URL}/health")["status"] == "ok")
        info = get(f"{API_URL}/api/info")
        check(
            "info constraints",
            info["id_bits"] == 11
            and info["allowed_count"] == [2, 20]
            and info["forbidden_count"] == [0, 128]
            and info["limit_range"] == [1, 8],
            str(info),
        )
    except Exception as exc:  # noqa: BLE001
        check("services reachable", False, repr(exc))
        print("\nABORT: services not reachable")
        return 1

    print("\n== feasible solution via web ==")
    allowed, forbidden, limit = [256, 257], [258], 2
    body = post(f"{WEB_URL}/api/solve", {
        "allowed": allowed, "forbidden": forbidden, "limit": limit,
    })
    check("response ok+feasible", body.get("ok") and body.get("feasible"), str(body)[:200])
    check("optimal single filter", body["filter_count"] == 1)
    check(
        "single filter isolates exactly the pair",
        body["filters"][0]["mask"] == 0x7FE
        and body["filters"][0]["code"] == 0x100,
        str(body["filters"][0]),
    )
    assert_solution_sound(body, allowed, forbidden, limit)

    print("\n== exhaustive infeasibility verdict ==")
    body = post(f"{WEB_URL}/api/solve", {
        "allowed": [0, 3], "forbidden": [1], "limit": 1,
    })
    check("ok but infeasible", body.get("ok") is True and body.get("feasible") is False)
    check("verdict says exhausted", "穷尽" in body.get("message", ""), body.get("message", ""))
    body2 = post(f"{WEB_URL}/api/solve", {
        "allowed": [0, 3], "forbidden": [1], "limit": 2,
    })
    check("same instance feasible at limit 2", body2.get("feasible") is True)
    check(
        "limit-2 optimum is two exact masks",
        [(f["mask"], f["code"]) for f in body2["filters"]]
        == [(2047, 0), (2047, 3)],
    )

    print("\n== per-field validation ==")
    body = post(f"{API_URL}/api/solve", {
        "allowed": [1, 1], "forbidden": [1, 9999], "limit": 9,
    })
    check(
        "invalid payload reports each field",
        body.get("ok") is False
        and set(body.get("errors", {})) == {"allowed", "forbidden", "limit"},
        str(body),
    )
    body = post(f"{API_URL}/api/solve", {
        "allowed": [1, 2], "forbidden": [2, 3], "limit": 4,
    })
    check(
        "overlap reported on forbidden field",
        body.get("ok") is False and "forbidden" in body.get("errors", {}),
        str(body),
    )
    body = post(f"{API_URL}/api/solve", {
        "allowed": list(range(21)), "forbidden": [], "limit": 4,
    })
    check("21 allowed rejected", not body.get("ok") and "allowed" in body.get("errors", {}))
    body = post(f"{API_URL}/api/solve", {
        "allowed": "1,2,3", "forbidden": [], "limit": 4,
    })
    check("wrong type rejected", body.get("ok") is False and "allowed" in body.get("errors", {}))

    print("\n== boundary sizes (20 allowed / 128 forbidden) ==")
    rng = random.Random(20260920)
    pool = list(range(ID_MAX))
    rng.shuffle(pool)
    allowed = sorted(pool[:20])
    forbidden = sorted(pool[20:148])
    body = post(f"{API_URL}/api/solve", {
        "allowed": allowed, "forbidden": forbidden, "limit": 8,
    })
    check("boundary payload accepted", body.get("ok") is True, str(body)[:200])
    if body.get("feasible"):
        assert_solution_sound(body, allowed, forbidden, 8)
    else:
        check("exhausted verdict present", "穷尽" in body["message"])

    print("\n== black-box optimality vs brute-force oracle ==")
    rng = random.Random(4242)
    for t in range(24):
        na = rng.randint(2, 8)
        nf = rng.randint(0, 12)
        ids = rng.sample(range(ID_MAX), na + nf)
        a = sorted(ids[:na])
        f = sorted(ids[na:])
        lim = rng.randint(1, 8)
        body = post(f"{API_URL}/api/solve", {
            "allowed": a, "forbidden": f, "limit": lim,
        })
        got = (
            None
            if not body.get("feasible")
            else [(x["mask"], x["code"]) for x in body["filters"]]
        )
        want = brute_force_opt(a, f, lim)
        check(f"oracle case {t} (n={na},f={nf},lim={lim})", got == want,
              f"got={got} want={want}")
        if got is not None:
            assert_solution_sound(body, a, f, lim)

    print("\n== solver package: direct equivalence sweep ==")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from app.solver import solve as direct_solve  # noqa: E402

        rng = random.Random(7)
        ok = True
        for _ in range(40):
            na = rng.randint(2, 8)
            nf = rng.randint(0, 12)
            ids = rng.sample(range(ID_MAX), na + nf)
            a = sorted(ids[:na])
            f = sorted(ids[na:])
            lim = rng.randint(1, 8)
            if direct_solve(a, f, lim) != brute_force_opt(a, f, lim):
                ok = False
                break
        check("direct solver matches oracle on 40 cases", ok)
    except Exception as exc:  # noqa: BLE001
        check("direct solver import/run", False, repr(exc))

    print(f"\n{'='*60}")
    print(f"{checks} checks run, {len(failures)} failures")
    if failures:
        print("\nFAILURES:")
        for fmsg in failures:
            print(" -", fmsg)
        return 1
    print("ALL ACCEPTANCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
