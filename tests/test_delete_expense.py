"""Step 9 — Delete Expense: full test suite derived from spec 09-delete-expense.md.

Tests cover:
  - delete_expense unit contract (own row removed; wrong user is a no-op;
    non-existent id is a no-op — no error, DB unchanged)
  - Auth guard on POST /expenses/<id>/delete (unauthenticated -> 302 /login)
  - Method guard: GET /expenses/<id>/delete -> 405 (route is POST-only)
  - POST happy path: 302 redirect to /profile, row removed from the DB
  - POST other user's expense / non-existent id -> 404, target row untouched

Fixtures reused from conftest.py:
  - ``seeded_db`` — temp DB with one known user (Test User) plus an
    ``empty_user_id`` (no expenses); used for the query-helper units.
  - ``client`` — Flask test client backed by a temp DB seeded with Demo User
    (demo@spendly.com) and 8 sample expenses; used for route tests.

Source files were read only for route names, helper signatures, and DB schema —
never for deriving expected behaviour. All expectations come from the spec.
"""

import database.db as db
from database.queries import delete_expense


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _demo_user_id():
    """Look up the Demo User's id through the currently patched DB_PATH."""
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
        ).fetchone()
    finally:
        conn.close()
    return row["id"]


def _first_expense_id(user_id):
    """Return the id of some expense belonging to *user_id*."""
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT id FROM expenses WHERE user_id = ? ORDER BY id LIMIT 1",
            (user_id,),
        ).fetchone()["id"]
    finally:
        conn.close()


def _row_exists(expense_id):
    """True if an expense row with *expense_id* is present in the DB."""
    conn = db.get_db()
    try:
        return (
            conn.execute(
                "SELECT 1 FROM expenses WHERE id = ?", (expense_id,)
            ).fetchone()
            is not None
        )
    finally:
        conn.close()


def _count_expenses(user_id):
    """Return the number of expense rows belonging to *user_id*."""
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


def _make_other_user_with_expense():
    """Insert a second user and one expense for them; return (user_id, expense_id)."""
    conn = db.get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Other User", "other9@spendly.com", "x"),
        )
        other_id = cursor.lastrowid
        ex_cursor = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (other_id, 42.00, "Food", "2026-06-15", "Their lunch"),
        )
        expense_id = ex_cursor.lastrowid
        conn.commit()
    finally:
        conn.close()
    return other_id, expense_id


def _login_demo(client):
    """Inject the Demo User's id directly into the session (no password round-trip)."""
    with client.session_transaction() as sess:
        sess["user_id"] = _demo_user_id()


# =========================================================================== #
# UNIT TESTS — delete_expense                                                  #
# =========================================================================== #

class TestDeleteExpenseUnit:
    """delete_expense(expense_id, user_id) ownership-scoped delete."""

    def test_own_expense_is_removed(self, seeded_db):
        """Deleting an owned expense removes the row from the DB."""
        user_id = seeded_db["user_id"]
        expense_id = _first_expense_id(user_id)

        delete_expense(expense_id, user_id)

        assert not _row_exists(expense_id), "Owned expense must be deleted"

    def test_wrong_user_is_a_noop(self, seeded_db):
        """Deleting with the wrong user_id removes nothing and raises no error."""
        owner_id = seeded_db["user_id"]
        expense_id = _first_expense_id(owner_id)

        # Empty User does not own this row — the WHERE clause matches nothing.
        delete_expense(expense_id, seeded_db["empty_user_id"])

        assert _row_exists(expense_id), "A non-owner must not be able to delete the row"

    def test_nonexistent_id_is_a_noop(self, seeded_db):
        """Deleting a non-existent id raises no error and leaves other rows intact."""
        user_id = seeded_db["user_id"]
        before = _count_expenses(user_id)

        delete_expense(999999, user_id)  # must not raise

        assert _count_expenses(user_id) == before, "No rows should be removed"


# =========================================================================== #
# ROUTE TESTS — POST /expenses/<id>/delete                                     #
# =========================================================================== #

class TestDeleteExpenseRoute:

    def test_post_unauthenticated_redirects_to_login(self, client):
        """An anonymous POST is bounced to /login (302); nothing is deleted."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)

        resp = client.post(f"/expenses/{expense_id}/delete")

        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        assert _row_exists(expense_id), "Row must survive an unauthenticated POST"

    def test_get_method_not_allowed(self, client):
        """The route is POST-only: a bare GET returns 405."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        resp = client.get(f"/expenses/{expense_id}/delete")

        assert resp.status_code == 405

    def test_post_own_expense_redirects_and_deletes(self, client):
        """A valid POST redirects to /profile and removes the row."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        before = _count_expenses(demo_id)
        _login_demo(client)

        resp = client.post(f"/expenses/{expense_id}/delete")

        assert resp.status_code == 302
        assert "/profile" in resp.headers["Location"]
        assert not _row_exists(expense_id), "Expense must be deleted from the DB"
        assert _count_expenses(demo_id) == before - 1, "Owner count drops by one"

    def test_post_other_users_expense_returns_404(self, client):
        """A POST to another user's expense is a 404 and deletes nothing."""
        _other_id, expense_id = _make_other_user_with_expense()
        _login_demo(client)

        resp = client.post(f"/expenses/{expense_id}/delete")

        assert resp.status_code == 404
        assert _row_exists(expense_id), "Another user's row must survive"

    def test_post_nonexistent_id_returns_404(self, client):
        """A POST to a non-existent expense id is a 404."""
        _login_demo(client)
        resp = client.post("/expenses/999999/delete")
        assert resp.status_code == 404


# =========================================================================== #
# PROFILE INTEGRATION — Delete control is present                              #
# =========================================================================== #

class TestProfileDeleteControl:

    def test_profile_renders_delete_forms(self, client):
        """Each transaction row exposes a Delete control posting to its delete URL."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get("/profile").get_data(as_text=True)

        assert f"/expenses/{expense_id}/delete" in body
        assert "Delete" in body

    def test_deleted_row_absent_after_delete(self, client):
        """After a delete, the row's description no longer appears on /profile."""
        demo_id = _demo_user_id()
        # Pick a row with a known, unique-ish description to assert on.
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT id, description FROM expenses WHERE user_id = ? "
                "AND description IS NOT NULL ORDER BY id LIMIT 1",
                (demo_id,),
            ).fetchone()
        finally:
            conn.close()
        _login_demo(client)

        client.post(f"/expenses/{row['id']}/delete")
        body = client.get("/profile").get_data(as_text=True)

        assert not _row_exists(row["id"]), "Row must be gone from the DB"
        assert row["description"] not in body, "Deleted row must not render on /profile"
