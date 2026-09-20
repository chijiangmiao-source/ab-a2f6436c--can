"""API-level tests: validation, evidence and the exhaustion verdict."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_info_exposes_constraints():
    info = client.get("/api/info").json()
    assert info["id_bits"] == 11
    assert info["allowed_count"] == [2, 20]
    assert info["forbidden_count"] == [0, 128]
    assert info["limit_range"] == [1, 8]


def test_solve_success_contains_evidence():
    r = client.post(
        "/api/solve",
        json={"allowed": [256, 257], "forbidden": [258], "limit": 2},
    )
    body = r.json()
    assert body["ok"] and body["feasible"]
    # mask 0x7FE ignores bit 0 only: accepts exactly 256 and 257
    assert body["filter_count"] == 1
    f = body["filters"][0]
    # 11-bit binary rendering and wildcard pattern are present
    assert len(f["mask_bin"]) == 11 and len(f["code_bin"]) == 11
    assert set(f["pattern"]) <= {"0", "1", "x"}
    assert f["accepted_count"] == 2
    assert f["hits"] == [256, 257]
    assert f["forbidden_hits"] == []
    # full coverage evidence: every allowed id accepted at least once
    assert {e["identifier"] for e in body["coverage"]} == {256, 257}
    assert all(e["accepted_by"] for e in body["coverage"])
    # every forbidden id is rejected by every filter
    for e in body["forbidden_check"]:
        assert len(e["rejected_by"]) == body["filter_count"]


def test_infeasible_within_limit_keeps_verdict():
    r = client.post(
        "/api/solve",
        json={"allowed": [0, 3], "forbidden": [1], "limit": 1},
    )
    body = r.json()
    assert body["ok"] is True
    assert body["feasible"] is False
    assert "穷尽" in body["message"]


def test_field_errors_are_per_field():
    r = client.post(
        "/api/solve",
        json={
            "allowed": [1, 1],
            "forbidden": [1, 9999],
            "limit": 9,
        },
    )
    body = r.json()
    assert body["ok"] is False
    assert set(body["errors"]) == {"allowed", "forbidden", "limit"}


def test_overlap_is_reported_on_forbidden_field():
    r = client.post(
        "/api/solve",
        json={"allowed": [1, 2], "forbidden": [2, 3], "limit": 4},
    )
    body = r.json()
    assert body["ok"] is False
    assert "forbidden" in body["errors"]


def test_boundary_counts_accepted():
    body = client.post(
        "/api/solve",
        json={
            "allowed": list(range(100, 120)),
            "forbidden": list(range(0, 100)),
            "limit": 8,
        },
    ).json()
    assert body["ok"] and body["feasible"]


def test_too_many_allowed():
    body = client.post(
        "/api/solve",
        json={"allowed": list(range(21)), "forbidden": [], "limit": 4},
    ).json()
    assert body["ok"] is False and "allowed" in body["errors"]
