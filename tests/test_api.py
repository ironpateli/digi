"""
DigiPlus API test suite.
Run: python tests/test_api.py
"""
from pathlib import Path
import sys

# Allow the documented command, `python tests/test_api.py`, to work from the
# repository root on Windows and POSIX shells alike.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

CREATED_IDS = []


def run(name, fn):
    try:
        fn()
        print(f"  ✅ {name}")
        return True
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        return False


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_dashboard():
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert "meetings" in d and "open_tasks" in d


def test_create_meeting():
    r = client.post("/api/meetings", json={
        "title": "Test Sprint Review",
        "type": "meeting",
        "scheduled_at": "2026-11-05T10:00:00Z",
        "agenda": "Review progress and assign tasks",
    })
    assert r.status_code == 201
    d = r.json()
    assert d["title"] == "Test Sprint Review"
    CREATED_IDS.append(d["id"])


def test_create_meeting_invalid_type():
    r = client.post("/api/meetings", json={
        "title": "Bad Type Meeting",
        "type": "invalid_type",
        "scheduled_at": "2026-11-05T10:00:00Z",
    })
    assert r.status_code == 422


def test_create_meeting_short_title():
    r = client.post("/api/meetings", json={
        "title": "AB",
        "type": "meeting",
        "scheduled_at": "2026-11-05T10:00:00Z",
    })
    assert r.status_code == 422


def test_get_meeting():
    assert CREATED_IDS, "No meeting created yet"
    r = client.get(f"/api/meetings/{CREATED_IDS[0]}")
    assert r.status_code == 200
    assert r.json()["id"] == CREATED_IDS[0]


def test_get_meeting_not_found():
    r = client.get("/api/meetings/nonexistent-id")
    assert r.status_code == 404


def test_update_meeting_notes():
    assert CREATED_IDS
    r = client.patch(f"/api/meetings/{CREATED_IDS[0]}", json={
        "agenda": "Updated agenda", "manual_notes": "These are manual notes",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["agenda"] == "Updated agenda"
    assert d["manual_notes"] == "These are manual notes"


def test_risk_radar():
    r = client.get("/api/risk-radar")
    assert r.status_code == 200
    d = r.json()
    assert all(k in d for k in ("overdue", "no_owner", "blocked", "no_due_date", "total_risks"))


def test_transcript_too_short():
    assert CREATED_IDS
    r = client.post(f"/api/meetings/{CREATED_IDS[0]}/transcripts",
                    json={"content": "too short"})
    assert r.status_code == 422


def test_task_invalid_status():
    # Get a real task ID from seeded data
    dash = client.get("/api/dashboard").json()
    task_id = None
    for m in dash["meetings"]:
        if m["tasks"]:
            task_id = m["tasks"][0]["id"]
            break
    if not task_id:
        print("    (skipped — no tasks in DB)")
        return
    r = client.patch(f"/api/tasks/{task_id}", json={"status": "flying"})
    assert r.status_code == 422


def test_task_complete_requires_outcome():
    dash = client.get("/api/dashboard").json()
    task_id = None
    for m in dash["meetings"]:
        for t in m["tasks"]:
            if t["status"] not in ("completed", "cancelled"):
                task_id = t["id"]
                break
        if task_id:
            break
    if not task_id:
        print("    (skipped — no open tasks)")
        return
    r = client.patch(f"/api/tasks/{task_id}", json={"status": "completed"})
    assert r.status_code == 422


def test_delete_meeting():
    assert CREATED_IDS
    r = client.delete(f"/api/meetings/{CREATED_IDS[0]}")
    assert r.status_code == 204
    r2 = client.get(f"/api/meetings/{CREATED_IDS[0]}")
    assert r2.status_code == 404


def test_static_served():
    r = client.get("/")
    assert r.status_code == 200
    assert b"DigiPlus" in r.content


# ── Runner ─────────────────────────────────────────────────────────────────────
TESTS = [
    ("Health check",                 test_health),
    ("Dashboard loads",              test_dashboard),
    ("Create meeting",               test_create_meeting),
    ("Reject invalid meeting type",  test_create_meeting_invalid_type),
    ("Reject short title",           test_create_meeting_short_title),
    ("Get meeting by ID",            test_get_meeting),
    ("404 for missing meeting",      test_get_meeting_not_found),
    ("Update meeting notes",         test_update_meeting_notes),
    ("Risk radar endpoint",          test_risk_radar),
    ("Reject short transcript",      test_transcript_too_short),
    ("Reject invalid task status",   test_task_invalid_status),
    ("Require outcome to complete",  test_task_complete_requires_outcome),
    ("Delete meeting cascades",      test_delete_meeting),
    ("Static HTML served",           test_static_served),
]

if __name__ == "__main__":
    print("\nRunning DigiPlus API tests...\n")
    passed = sum(run(name, fn) for name, fn in TESTS)
    total  = len(TESTS)
    print(f"\n{'─'*40}")
    print(f"  {passed}/{total} tests passed")
    if passed < total:
        exit(1)
