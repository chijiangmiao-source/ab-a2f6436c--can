from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_info():
    r = client.get("/api/info")
    assert r.status_code == 200
    data = r.json()
    assert data["id_bits"] == 11
    assert data["limit_max"] == 8


def test_solve_feasible():
    r = client.post(
        "/api/solve",
        json={"allowed": [0x100, 0x101], "forbidden": [0x102], "limit": 8},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["feasible"] is True
    assert data["filter_count"] == 1
    f0 = data["filters"][0]
    assert f0["mask"] == 0x7FE
    assert f0["code"] == 0x100
    assert f0["mask_bin"] == "11111111110"
    assert f0["code_bin"] == "00100000000"
    assert f0["pattern"] == "0010000000x"
    assert f0["accepted_count"] == 2
    assert f0["exposure_count"] == 0
    assert f0["matched_allowed"] == [256, 257]
    # Coverage matrix: one row, two hits.
    assert data["coverage"] == [[True, True]]
    # Full-coverage evidence: every column has at least one hit.
    for col in range(len(data["allowed"])):
        assert any(row[col] for row in data["coverage"])
    # Zero-exposure evidence.
    for f in data["filters"]:
        assert f["exposure_count"] == 0


def test_solve_exhausted_preserves_input():
    r = client.post(
        "/api/solve",
        json={"allowed": [0x100, 0x103], "forbidden": [0x101, 0x102], "limit": 1},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["feasible"] is False
    assert data["exhausted"] is True
    assert "穷尽" in data["message"]
    # Echoed inputs let the page retain them.
    assert data["allowed"] == [256, 259]
    assert data["forbidden"] == [257, 258]


def test_field_errors_counts_and_range():
    r = client.post("/api/solve", json={"allowed": [1], "forbidden": [], "limit": 8})
    assert r.status_code == 422
    fields = r.json()["fields"]
    assert "allowed" in fields

    r = client.post(
        "/api/solve",
        json={"allowed": [1, 2], "forbidden": list(range(129)), "limit": 8},
    )
    # overlaps are also illegal; forbidden count error must be reported
    assert r.status_code == 422
    assert "forbidden" in r.json()["fields"]

    r = client.post("/api/solve", json={"allowed": [1, 2048], "forbidden": [], "limit": 8})
    assert r.status_code == 422
    assert "allowed" in r.json()["fields"]

    r = client.post("/api/solve", json={"allowed": [1, 2], "forbidden": [], "limit": 9})
    assert r.status_code == 422
    assert "limit" in r.json()["fields"]


def test_field_errors_duplicates_and_overlap():
    r = client.post(
        "/api/solve",
        json={"allowed": [1, 1, 2], "forbidden": [], "limit": 8},
    )
    assert r.status_code == 422
    assert "allowed" in r.json()["fields"]

    r = client.post(
        "/api/solve",
        json={"allowed": [1, 2], "forbidden": [2, 3], "limit": 8},
    )
    assert r.status_code == 422
    fields = r.json()["fields"]
    assert "forbidden" in fields
    assert "重叠" in fields["forbidden"]


def test_field_errors_type():
    r = client.post(
        "/api/solve",
        json={"allowed": ["a", 2], "forbidden": [], "limit": 8},
    )
    assert r.status_code == 422
    assert "allowed" in r.json()["fields"]

    r = client.post(
        "/api/solve",
        json={"allowed": [1, 2], "forbidden": [], "limit": "x"},
    )
    assert r.status_code == 422
    assert "limit" in r.json()["fields"]
