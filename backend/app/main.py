"""FastAPI application for the CAN acceptance-filter audit console."""

from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .schemas import FilterView, SolveRequest, SolveResponse
from .solver import ID_BITS, ID_SPACE, coverage_matrix, solve

app = FastAPI(
    title="CAN 验收过滤器审计台",
    description="精确计算 11 位 CAN 验收过滤器 (code/mask) 配置",
    version="1.0.0",
)

# In docker-compose the React dev/nginx origin differs from the API origin.
# CORS is constrained in production via CORS_ORIGINS (comma separated); the
# default permissive value keeps local development frictionless.
_origins = os.getenv("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",")] if _origins != "*" else ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Collapse pydantic errors into per-field Chinese feedback."""
    fields: Dict[str, str] = {}
    for err in exc.errors():
        loc = err.get("loc", ())
        # loc looks like ("body", "allowed") or ("body", "allowed", 2);
        # take the last non-index segment so feedback is attached to a field.
        name = None
        for part in reversed(loc):
            if part == "body":
                break
            if isinstance(part, str):
                name = part
                break
        msg = err.get("msg", "非法数据")
        etype = err.get("type", "")
        if etype.startswith("value_error"):
            msg = msg.removeprefix("Value error, ")
        elif etype == "missing":
            msg = "该字段必填"
        elif etype.startswith("json_"):
            msg = "请求体不是合法的 JSON"
        key = name if name is not None else "_form"
        if key not in fields:
            fields[key] = msg
    return JSONResponse(
        status_code=422,
        content={"detail": "输入数据非法", "fields": fields},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "can-filter-audit-api"}


@app.get("/api/info")
async def info():
    return {
        "id_bits": ID_BITS,
        "id_space": ID_SPACE,
        "allowed_min": 2,
        "allowed_max": 20,
        "forbidden_max": 128,
        "limit_min": 1,
        "limit_max": 8,
    }


def _pattern(code_bin: str, mask_bin: str) -> str:
    """11-char comparison pattern: '0'/'1' compared, 'x' wildcard."""
    return "".join(c if m == "1" else "x" for c, m in zip(code_bin, mask_bin))


@app.post("/api/solve", response_model=SolveResponse)
async def solve_filters(req: SolveRequest) -> SolveResponse:
    allowed = sorted(set(req.allowed))
    forbidden = sorted(set(req.forbidden))

    result = solve(allowed, forbidden, req.limit)

    filters_out: List[FilterView] = []
    for i, f in enumerate(result.filters):
        code_bin = format(f.code, f"0{ID_BITS}b")
        mask_bin = format(f.mask, f"0{ID_BITS}b")
        matched = f.matched(allowed)
        exposed = [x for x in forbidden if f.accepts(x)]
        filters_out.append(
            FilterView(
                index=i + 1,
                code=f.code,
                mask=f.mask,
                code_hex=f"0x{f.code:03X}",
                mask_hex=f"0x{f.mask:03X}",
                code_bin=code_bin,
                mask_bin=mask_bin,
                pattern=_pattern(code_bin, mask_bin),
                accepted_count=f.accepted_count(),
                exposure_count=len(exposed),
                exposed_forbidden=exposed,
                matched_allowed=matched,
                matched_allowed_count=len(matched),
            )
        )

    matrix = coverage_matrix(result.filters, allowed)
    total_accepted = sum(f.accepted_count() for f in result.filters)

    if result.feasible:
        message = (
            f"已找到最优配置：{len(result.filters)} 个过滤器"
            f"（上限 {req.limit}），可接受标识数之和 {total_accepted}。"
        )
    else:
        message = (
            f"已穷尽：在 {req.limit} 个过滤器上限内不存在可行方案。"
            f"共评估 {result.candidate_count} 个候选过滤器，"
            "所有不命中禁用标识的过滤器组合均已验证无法覆盖全部允许标识。"
        )

    return SolveResponse(
        feasible=result.feasible,
        exhausted=result.exhausted,
        candidate_count=result.candidate_count,
        limit=req.limit,
        filter_count=len(result.filters),
        total_accepted=total_accepted,
        filters=filters_out,
        coverage=matrix,
        allowed=allowed,
        forbidden=forbidden,
        message=message,
    )
