"""Admin pages and onboarding a client's website."""
from tests.conftest import CLIENT, MEMBER, STAFF


def test_admin_lists_all_people(api):
    people = api.get("/api/admin/users", headers=STAFF).json()
    owner = next(p for p in people if p["email"] == "owner@seosys.test")
    assert owner["clients"] == [{"client_id": 1, "client_name": "Lone Star Comfort HVAC", "role": "owner"}]
    assert "password_hash" not in owner and "totp_secret" not in owner


def test_non_admin_refused(api):
    for path in ("/api/admin/users", "/api/admin/audit"):
        assert api.get(path, headers=CLIENT).status_code == 403


def test_suspend_user_and_reactivate(api, db):
    member = db.one("SELECT id FROM users WHERE email = 'member@seosys.test'")["id"]
    assert api.post(f"/api/admin/users/{member}/suspend", headers=STAFF).status_code == 200
    assert api.get("/api/clients/1", headers=MEMBER).status_code == 401
    assert api.post(f"/api/admin/users/{member}/reactivate", headers=STAFF).status_code == 200
    assert db.one("SELECT status FROM users WHERE id = ?", (member,))["status"] == "active"


def test_admin_cannot_suspend_self(api, db):
    me = db.one("SELECT id FROM users WHERE is_admin")["id"]
    assert api.post(f"/api/admin/users/{me}/suspend", headers=STAFF).status_code == 403


def test_owner_adds_website_and_gets_plugin_key_once(api, db):
    r = api.put("/api/clients/1/site", json={"base_url": "https://www.example.com/", "cms": "wordpress"}, headers=CLIENT)
    body = r.json()
    assert r.status_code == 200 and body["site"]["base_url"] == "https://www.example.com" and len(body["plugin_key"]) > 30
    assert "adapter_secret" not in body["site"]
    assert db.for_client(1).site()["adapter_secret"] == body["plugin_key"]
    assert api.put("/api/clients/1/site", json={"base_url": "https://x.example"}, headers=MEMBER).status_code == 403


def test_summary_works_before_a_website_is_added(api, db):
    db.execute("DELETE FROM sites")
    assert api.get("/api/clients/1", headers=CLIENT).json()["site"] is None
