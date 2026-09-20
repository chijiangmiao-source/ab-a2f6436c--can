"""Pydantic schemas with field-level validation for the audit console."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from .solver import ID_SPACE


def _parse_int_list(value) -> List[int]:
    """Accept a JSON list of ints, rejecting bools and fractional numbers."""
    if not isinstance(value, list):
        raise ValueError("必须是整数列表")
    out: List[int] = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("每个标识必须是整数")
        out.append(v)
    return out


class SolveRequest(BaseModel):
    allowed: List[int] = Field(description="允许标识（飞控遥测 CAN ID）")
    forbidden: List[int] = Field(
        default_factory=list, description="禁用标识（绝不可被任何过滤器命中）"
    )
    limit: int = Field(description="过滤器数量上限 (1-8)")

    @field_validator("allowed", "forbidden", mode="before")
    @classmethod
    def _coerce_list(cls, v):
        return _parse_int_list(v)

    @field_validator("limit", mode="before")
    @classmethod
    def _coerce_limit(cls, v):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError("上限必须是 1 到 8 之间的整数")
        return v

    @field_validator("allowed")
    @classmethod
    def _validate_allowed(cls, v: List[int]):
        if not (2 <= len(v) <= 20):
            raise ValueError("允许标识数量必须为 2 至 20 个")
        if len(set(v)) != len(v):
            raise ValueError("允许标识不得重复")
        bad = [x for x in v if not (0 <= x < ID_SPACE)]
        if bad:
            raise ValueError(f"存在超出 11 位范围 (0-2047) 的标识: {sorted(set(bad))}")
        return v

    @field_validator("forbidden")
    @classmethod
    def _validate_forbidden(cls, v: List[int], info: ValidationInfo):
        if len(v) > 128:
            raise ValueError("禁用标识数量必须为 0 至 128 个")
        if len(set(v)) != len(v):
            raise ValueError("禁用标识不得重复")
        bad = [x for x in v if not (0 <= x < ID_SPACE)]
        if bad:
            raise ValueError(f"存在超出 11 位范围 (0-2047) 的标识: {sorted(set(bad))}")
        # Field-level overlap feedback (allowed is validated before forbidden
        # by field declaration order).
        allowed = info.data.get("allowed")
        if allowed is not None:
            overlap = sorted(set(allowed) & set(v))
            if overlap:
                raise ValueError(f"与允许标识重叠，同一标识不得禁用: {overlap}")
        return v

    @field_validator("limit")
    @classmethod
    def _validate_limit(cls, v: int):
        if not (1 <= v <= 8):
            raise ValueError("上限必须在 1 到 8 之间")
        return v


class FilterView(BaseModel):
    index: int
    code: int
    mask: int
    code_hex: str
    mask_hex: str
    code_bin: str  # 11-char binary, MSB first
    mask_bin: str
    pattern: str  # human-readable "x vs 0/1" comparison string
    accepted_count: int  # total 11-bit ids this filter accepts
    exposure_count: int  # forbidden ids hit (always 0 for solver output)
    exposed_forbidden: List[int]
    matched_allowed: List[int]  # allowed ids accepted by this filter
    matched_allowed_count: int


class SolveResponse(BaseModel):
    feasible: bool
    exhausted: bool
    candidate_count: int
    limit: int
    filter_count: int
    total_accepted: int
    filters: List[FilterView]
    coverage: List[List[bool]]  # rows = filters, columns = allowed ids
    allowed: List[int]
    forbidden: List[int]
    message: Optional[str] = None
