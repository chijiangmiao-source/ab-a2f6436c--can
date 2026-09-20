"""End-to-end acceptance checks executed inside the compose `verify` service.

Hits the REAL HTTP endpoints (nginx web container -> FastAPI api container):
  1. health checks for web and api
  2. the SPA is served by the web container
  3. a feasible optimisation case with full structural assertions
     (canonical codes, binary patterns, coverage matrix, zero exposure,
     complete coverage evidence, known optimal answer)
  4. an infeasible case proving the "exhausted" conclusion and input echo
  5. field-level validation feedback for each invalid field
"""

import json
import os
import sys
import urllib.request
import urllib.error

API_URL = os.getenv("API_URL", "http://api:8000")
WEB_URL = os.getenv("WEB_URL", "http://web:80")

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def http(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def main():
    # ---- 1. health ---------------------------------------------------------
    st, body = http("GET", f"{API_URL}/health")
    check("API /health 200 + status ok", st == 200 and body.get("status") == "ok", str(body))

    st, body = http("GET", f"{WEB_URL}/health")
    check("WEB /health proxies to API", st == 200 and body.get("status") == "ok", str(body))

    # ---- 2. SPA served -----------------------------------------------------
    try:
        with urllib.request.urlopen(f"{WEB_URL}/", timeout=10) as resp:
            html = resp.read().decode()
            st = resp.status
    except Exception as exc:  # noqa: BLE001
        st, html = 0, str(exc)
    check("WEB serves SPA index.html", st == 200 and "CAN" in html and 'id="root"' in html)

    # ---- 3. feasible case --------------------------------------------------
    st, r = http(
        "POST",
        f"{API_URL}/api/solve",
        {"allowed": [256, 257, 258, 259], "forbidden": [260, 261], "limit": 4},
    )
    check("feasible case returns 200", st == 200, str(r))
    if st == 200:
        check("feasible=true, filter_count=1", r["feasible"] is True and r["filter_count"] == 1,
              f"{r.get('feasible')}, {r.get('filter_count')}")
        f0 = r["filters"][0]
        # 256..259 = 001000000xx, mask 0x7FC (2044), code 0x100 (256), cost 4.
        check("optimal mask 0x7FC", f0["mask"] == 0x7FC, hex(f0["mask"]))
        check("optimal code 0x100", f0["code"] == 0x100, hex(f0["code"]))
        check("canonical code clears un-compared bits", f0["code"] & ~f0["mask"] == 0)
        check("mask binary is 11111111100", f0["mask_bin"] == "11111111100", f0["mask_bin"])
        check("code binary is 00100000000", f0["code_bin"] == "00100000000", f0["code_bin"])
        check("pattern is 001000000xx", f0["pattern"] == "001000000xx", f0["pattern"])
        check("accepted_count == 4", f0["accepted_count"] == 4, str(f0["accepted_count"]))
        check("single-filter exposure == 0", f0["exposure_count"] == 0)
        check("matched all 4 allowed", f0["matched_allowed"] == [256, 257, 258, 259])
        check("coverage matrix row all hits", r["coverage"] == [[True, True, True, True]])
        # complete coverage evidence: every column covered
        for c, aid in enumerate(r["allowed"]):
            covered = any(row[c] for row in r["coverage"])
            check(f"coverage evidence column {aid}", covered)
        check("total_accepted == 4", r["total_accepted"] == 4)

    # Two-filter example where limit 1 is impossible.
    st, r = http(
        "POST",
        f"{API_URL}/api/solve",
        {"allowed": [256, 259], "forbidden": [257, 258], "limit": 2},
    )
    check("separated pair feasible with limit 2",
          st == 200 and r["feasible"] and r["filter_count"] == 2, str(r)[:300])
    if st == 200 and r["feasible"]:
        for f in r["filters"]:
            check(f"filter #{f['index']} zero exposure", f["exposure_count"] == 0)
            check(f"filter #{f['index']} canonical code", f["code"] & ~f["mask"] == 0)
        for c, aid in enumerate(r["allowed"]):
            check(f"separated pair coverage {aid}", any(row[c] for row in r["coverage"]))

    # ---- 4. exhausted case -------------------------------------------------
    st, r = http(
        "POST",
        f"{API_URL}/api/solve",
        {"allowed": [256, 259], "forbidden": [257, 258], "limit": 1},
    )
    check("infeasible case returns 200", st == 200)
    check("feasible=false exhausted=true",
          r.get("feasible") is False and r.get("exhausted") is True, str(r))
    check("exhausted conclusion text", "穷尽" in r.get("message", ""), r.get("message"))
    check("inputs retained/echoed (allowed)", r.get("allowed") == [256, 259])
    check("inputs retained/echoed (forbidden)", r.get("forbidden") == [257, 258])
    check("inputs retained (limit)", r.get("limit") == 1)

    # ---- 5. field-level validation ----------------------------------------
    st, r = http("POST", f"{API_URL}/api/solve",
                 {"allowed": [1], "forbidden": [], "limit": 8})
    check("422 on too few allowed", st == 422 and "allowed" in r.get("fields", {}), str(r))

    st, r = http("POST", f"{API_URL}/api/solve",
                 {"allowed": [1, 2, 3], "forbidden": list(range(4, 133)), "limit": 8})
    check("422 on too many forbidden", st == 422 and "forbidden" in r.get("fields", {}))

    st, r = http("POST", f"{API_URL}/api/solve",
                 {"allowed": [1, 2], "forbidden": [2], "limit": 8})
    check("422 on overlap flagged on forbidden",
          st == 422 and "forbidden" in r.get("fields", {}))

    st, r = http("POST", f"{API_URL}/api/solve",
                 {"allowed": [1, 2], "forbidden": [], "limit": 0})
    check("422 on limit out of range", st == 422 and "limit" in r.get("fields", {}))

    st, r = http("POST", f"{API_URL}/api/solve",
                 {"allowed": [1, 2048], "forbidden": [], "limit": 8})
    check("422 on id out of 11-bit range", st == 422 and "allowed" in r.get("fields", {}))

    st, r = http("POST", f"{API_URL}/api/solve",
                 {"allowed": "1,2", "forbidden": [], "limit": 8})
    check("422 on wrong type", st == 422 and "allowed" in r.get("fields", {}))

    if failures:
        print(f"\n{len(failures)} acceptance check(s) FAILED")
        sys.exit(1)
    print("\nAll HTTP acceptance checks passed.")


if __name__ == "__main__":
    main()
