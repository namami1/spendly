"""Step 5 — unit tests for the query helpers and route tests for /profile."""

import re

import database.db as db
from database.queries import (
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_id,
)


# --------------------------------------------------------------------------- #
# get_user_by_id                                                              #
# --------------------------------------------------------------------------- #

def test_get_user_by_id_returns_user(seeded_db):
    user = get_user_by_id(seeded_db["user_id"])
    assert user["name"] == "Test User"
    assert user["email"] == "test@example.com"
    # created_at DEFAULT is "now"; assert the shape, not an exact month (avoids
    # a UTC/local month-boundary flake).
    assert re.match(r"^[A-Z][a-z]+ \d{4}$", user["member_since"])


def test_get_user_by_id_missing_returns_none(seeded_db):
    assert get_user_by_id(999999) is None


# --------------------------------------------------------------------------- #
# get_summary_stats                                                           #
# --------------------------------------------------------------------------- #

def test_get_summary_stats_with_expenses(seeded_db):
    stats = get_summary_stats(seeded_db["user_id"])
    assert stats["total_spent"] == 200.00
    assert stats["transaction_count"] == 4
    assert stats["top_category"] == "Bills"  # 100 > Food 70 > Transport 30


def test_get_summary_stats_no_expenses(seeded_db):
    stats = get_summary_stats(seeded_db["empty_user_id"])
    assert stats == {"total_spent": 0, "transaction_count": 0, "top_category": "—"}


# --------------------------------------------------------------------------- #
# get_recent_transactions                                                     #
# --------------------------------------------------------------------------- #

def test_get_recent_transactions_newest_first(seeded_db):
    txns = get_recent_transactions(seeded_db["user_id"])
    assert len(txns) == 4

    # Both Food rows share 2026-06-12; the id-DESC tie-break puts the later
    # insert ("Snacks") ahead of "Groceries".
    assert txns[0]["date"] == "Jun 12"
    assert txns[0]["description"] == "Snacks"
    assert txns[1]["date"] == "Jun 12"
    assert txns[1]["description"] == "Groceries"
    assert txns[-1]["date"] == "Jun 01"  # the oldest row (Transport)

    assert set(txns[0]) == {"date", "description", "category", "amount"}


def test_get_recent_transactions_no_expenses(seeded_db):
    assert get_recent_transactions(seeded_db["empty_user_id"]) == []


# --------------------------------------------------------------------------- #
# get_category_breakdown                                                      #
# --------------------------------------------------------------------------- #

def test_get_category_breakdown_with_expenses(seeded_db):
    breakdown = get_category_breakdown(seeded_db["user_id"])
    # Ordered amount desc: Bills 100, Food 70, Transport 30.
    assert [c["name"] for c in breakdown] == ["Bills", "Food", "Transport"]
    assert all(isinstance(c["pct"], int) for c in breakdown)
    assert sum(c["pct"] for c in breakdown) == 100


def test_get_category_breakdown_no_expenses(seeded_db):
    assert get_category_breakdown(seeded_db["empty_user_id"]) == []


# --------------------------------------------------------------------------- #
# GET /profile                                                                #
# --------------------------------------------------------------------------- #

def _seed_user_id():
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
        ).fetchone()
    finally:
        conn.close()
    return row["id"]


def test_profile_unauthenticated_redirects_to_login(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")


def test_profile_authenticated_renders_real_data(client):
    with client.session_transaction() as sess:
        sess["user_id"] = _seed_user_id()

    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "Demo User" in body
    assert "demo@spendly.com" in body
    assert "₹" in body
    assert "₹349.64" in body            # real seed total
    assert "Bills" in body              # top category

    # Newest-first: "Coffee and snacks" (Jun 15) precedes "Lunch at cafe" (Jun 02).
    assert body.index("Coffee and snacks") < body.index("Lunch at cafe")

    # All 7 seeded categories appear in the breakdown.
    for category in ("Food", "Transport", "Bills", "Health",
                     "Entertainment", "Shopping", "Other"):
        assert category in body
