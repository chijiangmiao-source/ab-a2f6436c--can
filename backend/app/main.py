"""FastAPI application: CAN acceptance-filter audit station."""
from __future__ import annotations

from typing import Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .solver import (
    FULL_ID_MASK,
    ID_BITS,
    accepted_count,
    accepts,
    solve,
)


app = FastAPI(title="CAN Acceptance-Filter Audit API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _bits(value: int) -> str:
    """11-character binary rendering, bit 10 on the left."""
    return format(value, f"0{ID_BITS}b")


def validate_payload(payload: Dict[str, object]) -> Dict[str, str]:
    """Field-by-field validation.  Returns a field-name -> message map."""
    errors: Dict[str, str] = {}

    allowed = payload.get("allowed")
    forbidden = payload.get("forbidden")
    limit = payload.get("limit")

    # ---- allowed -------------------------------------------------------
    if not isinstance(allowed, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in allowed):
        errors["allowed"] = "允许标识必须是整数列表。"
    elif not (2 <= len(allowed) <= 20):
        errors["allowed"] = f"允许标识数量必须为 2 至 20 个（当前 {len(allowed)} 个）。"
    elif any(not (0 <= v <= FULL_ID_MASK) for v in allowed):
        errors["allowed"] = f"允许标识必须是 0 至 {FULL_ID_MASK} 之间的 11 位整数。"
    elif len(set(allowed)) != len(allowed):
        dupes = sorted({v for v in allowed if allowed.count(v) > 1})
        errors["allowed"] = f"允许标识必须互异，重复项：{dupes}。"

    # ---- forbidden -----------------------------------------------------
    if not isinstance(forbidden, list) or not all(
        isinstance(v, int) and not isinstance(v, bool) for v in forbidden
    ):
        errors["forbidden"] = "禁用标识必须是整数列表。"
    elif len(forbidden) > 128:
        errors["forbidden"] = f"禁用标识数量必须为 0 至 128 个（当前 {len(forbidden)} 个）。"
    elif any(not (0 <= v <= FULL_ID_MASK) for v in forbidden):
        errors["forbidden"] = f"禁用标识必须是 0 至 {FULL_ID_MASK} 之间的 11 位整数。"

    # ---- limit ---------------------------------------------------------
    if not isinstance(limit, int) or isinstance(limit, bool):
        errors["limit"] = "过滤器上限必须是整数。"
    elif not (1 <= limit <= 8):
        errors["limit"] = f"过滤器上限必须为 1 至 8（当前 {limit!r}）。"

    # ---- cross-field: overlap -----------------------------------------
    if "allowed" not in errors and "forbidden" not in errors and isinstance(forbidden, list):
        overlap = sorted(set(allowed) & set(forbidden))
        if overlap:
            errors["forbidden"] = f"禁用标识不得与允许标识重叠，冲突项：{overlap}。"

    return errors


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/info")
def info() -> Dict[str, object]:
    return {
        "id_bits": ID_BITS,
        "id_max": FULL_ID_MASK,
        "allowed_count": [2, 20],
        "forbidden_count": [0, 128],
        "limit_range": [1, 8],
    }


@app.post("/api/solve")
def solve_endpoint(payload: Dict[str, object]) -> Dict[str, object]:
    errors = validate_payload(payload)
    if errors:
        return {"ok": False, "errors": errors}

    allowed = sorted(payload["allowed"])  # type: ignore[arg-type]
    forbidden = sorted(payload["forbidden"])  # type: ignore[arg-type]
    limit: int = payload["limit"]  # type: ignore[assignment]

    result = solve(allowed, forbidden, limit)

    if result is None:
        return {
            "ok": True,
            "feasible": False,
            "limit": limit,
            "message": f"已穷尽全部 {limit} 个以内的过滤器组合，不存在既覆盖全部允许标识又不命中任何禁用标识的方案。",
        }

    forbidden_set = set(forbidden)
    filters_out: List[Dict[str, object]] = []
    total_exposure = 0
    for idx, (mask, code) in enumerate(result):
        hits = [x for x in allowed if accepts(mask, code, x)]
        exposure = accepted_count(mask)
        total_exposure += exposure
        filters_out.append(
            {
                "index": idx,
                "mask": mask,
                "code": code,
                "mask_hex": f"0x{mask:03X}",
                "code_hex": f"0x{code:03X}",
                "mask_bin": _bits(mask),
                "code_bin": _bits(code),
                "pattern": "".join(
                    "x" if not ((mask >> b) & 1) else str((code >> b) & 1)
                    for b in range(ID_BITS - 1, -1, -1)
                ),
                "accepted_count": exposure,
                "hits": hits,
                "forbidden_hits": sorted(
                    y for y in forbidden if accepts(mask, code, y)
                ),
            }
        )

    # Full coverage evidence: which filter(s) accept each allowed id.
    coverage_evidence = [
        {
            "identifier": x,
            "hex": f"0x{x:03X}",
            "bin": _bits(x),
            "accepted_by": [i for i, (m, c) in enumerate(result) if accepts(m, c, x)],
        }
        for x in allowed
    ]

    # Exhaustiveness evidence: prove no forbidden id is accepted anywhere.
    forbidden_evidence = [
        {
            "identifier": y,
            "hex": f"0x{y:03X}",
            "rejected_by": [
                i for i, (m, c) in enumerate(result) if not accepts(m, c, y)
            ],
        }
        for y in forbidden
    ]

    assert all(f["forbidden_hits"] == [] for f in filters_out)
    assert all(e["accepted_by"] for e in coverage_evidence)
    assert all(
        len(e["rejected_by"]) == len(result) for e in forbidden_evidence
    )

    return {
        "ok": True,
        "feasible": True,
        "limit": limit,
        "filter_count": len(result),
        "total_accepted_count": total_exposure,
        "filters": filters_out,
        "coverage": coverage_evidence,
        "forbidden_check": forbidden_evidence,
        "optimality": {
            "objective_1": "过滤器数最少",
            "objective_2": "各过滤器可接受标识数之和最小",
            "objective_3": "排序后 (mask, code) 序列字典序最小",
        },
    }
