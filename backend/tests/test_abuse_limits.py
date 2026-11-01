"""Public endpoints that cost us work are limited per IP address."""
from fastapi.testclient import TestClient

from tests.conftest import GOOD_PASSWORD


def test_free_check_limited_per_ip(api):
    visitor = TestClient(api.app, client=("203.0.113.20", 4000))
    codes = [visitor.post("/api/grader", json={"url": "http://127.0.0.1:8001"}).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    other = TestClient(api.app, client=("203.0.113.21", 4000))
    assert other.post("/api/grader", json={"url": "http://127.0.0.1:8001"}).status_code == 200


def test_signup_limited_per_ip(bare_api, db):
    visitor = TestClient(bare_api.app, client=("203.0.113.30", 4000))
    codes = [visitor.post("/api/auth/signup", json={"email": f"p{i}@example.com", "name": "P", "password": GOOD_PASSWORD})
             .status_code for i in range(11)]
    assert codes[:10] == [202] * 10 and codes[10] == 429
    assert db.one("SELECT count(*) AS n FROM users")["n"] == 10
