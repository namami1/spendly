"""Pytest fixtures for the Step 5 backend-connection tests.

get_db() reads the module-global database.db.DB_PATH at call time, so patching
that attribute redirects every connection — the query helpers and the app alike —
to a throwaway temp DB. The real project DB is never touched.
"""

import pytest

import database.db as db
from database.db import init_db, seed_db


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """A temp DB with one known user and a small, controlled set of expenses."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    init_db()

    conn = db.get_db()
    try:
        # Omit created_at so the column DEFAULT (datetime('now')) applies, which
        # get_user_by_id parses with "%Y-%m-%d %H:%M:%S".
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Test User", "test@example.com", "x"),
        )
        user_id = cursor.lastrowid

        # A second user with no expenses, to exercise the empty-state paths.
        empty_cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty User", "empty@example.com", "x"),
        )
        empty_user_id = empty_cursor.lastrowid

        # The two Food rows share a date to exercise the id-DESC tie-break.
        expenses = [
            (user_id, 100.00, "Bills", "2026-06-10", "Rent share"),
            (user_id, 50.00, "Food", "2026-06-12", "Groceries"),
            (user_id, 20.00, "Food", "2026-06-12", "Snacks"),
            (user_id, 30.00, "Transport", "2026-06-01", "Bus"),
        ]
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            expenses,
        )
        conn.commit()
    finally:
        conn.close()

    return {"user_id": user_id, "empty_user_id": empty_user_id}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A Flask test client backed by a freshly seeded temp DB (Demo User + 8 rows)."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "route.db"))
    init_db()
    seed_db()

    from app import app

    app.config.update(TESTING=True, SECRET_KEY="test")
    with app.test_client() as test_client:
        yield test_client
