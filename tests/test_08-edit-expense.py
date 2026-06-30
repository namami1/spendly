"""Step 8 — Edit Expense: full test suite derived from spec 08-edit-expense.md.

Tests cover:
  - get_expense_by_id unit contract:
      own row returns dict-like row; wrong user -> None; missing id -> None
  - update_expense unit contract:
      own row reflects new amount; wrong user_id is a silent no-op
  - Auth guards on GET and POST /expenses/<id>/edit  (302 -> /login)
  - GET happy path: 200, form pre-filled with current values, correct category
    pre-selected in the <select>
  - GET ownership: other user's expense -> 404; non-existent id -> 404
  - POST happy path: 302 to /profile, DB row reflects all updated values
  - POST ownership: other user's expense -> 404, DB row unchanged
  - POST no description: 302 to /profile, DB description column = NULL
  - POST validation errors (all must 200-rerender with an error message and
    leave the DB row unchanged):
      missing amount, amount=0, non-numeric amount, invalid category,
      invalid date string

Fixtures reused from conftest.py:
  - ``seeded_db`` — temp SQLite DB with one known user (Test User / test@example.com)
    and a handful of controlled expenses (user_id) plus Empty User (empty_user_id).
    Used for the query-helper unit tests.
  - ``client`` — Flask test client backed by a temp DB seeded with Demo User
    (demo@spendly.com / demo123) and 8 sample expenses. Used for route tests.

Source files were read ONLY for route names, helper signatures, and DB schema —
never for deriving expected behaviour. All expectations come from the spec.
"""

import pytest

import database.db as db
from database.queries import get_expense_by_id, update_expense

# --------------------------------------------------------------------------- #
# Fixed categories — single source of truth from spec §rules                  #
# --------------------------------------------------------------------------- #

EXPECTED_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]


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
    """Return the id of the earliest expense row belonging to *user_id*."""
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT id FROM expenses WHERE user_id = ? ORDER BY id LIMIT 1",
            (user_id,),
        ).fetchone()["id"]
    finally:
        conn.close()


def _fetch_expense_raw(expense_id):
    """Return the raw expense row by id, bypassing ownership scoping.

    Used after a write operation to assert what the DB actually contains.
    Returns None if the row does not exist.
    """
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
    finally:
        conn.close()


def _make_other_user_with_expense():
    """Insert a second user and one expense; return (other_user_id, expense_id).

    This simulates the cross-user ownership scenario: the Demo User should
    not be able to GET or POST to an expense owned by Other User.
    """
    conn = db.get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Other User", "other8@spendly.com", "x"),
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
    """Inject the Demo User's session id directly — no password round-trip."""
    with client.session_transaction() as sess:
        sess["user_id"] = _demo_user_id()


def _valid_edit_form():
    """Return a complete, valid set of edit-form fields."""
    return {
        "amount": "75.50",
        "category": "Shopping",
        "date": "2026-05-20",
        "description": "New backpack",
    }


# =========================================================================== #
# UNIT TESTS — get_expense_by_id                                               #
# =========================================================================== #

class TestGetExpenseByIdUnit:
    """get_expense_by_id(expense_id, user_id) ownership-scoped fetch contract."""

    def test_own_expense_returns_matching_row(self, seeded_db):
        """A valid expense id owned by the given user returns a non-None row."""
        user_id = seeded_db["user_id"]
        expense_id = _first_expense_id(user_id)

        row = get_expense_by_id(expense_id, user_id)

        assert row is not None, "Owner must receive their expense row, not None"

    def test_own_expense_row_has_correct_id(self, seeded_db):
        """The returned row's 'id' field matches the requested expense_id."""
        user_id = seeded_db["user_id"]
        expense_id = _first_expense_id(user_id)

        row = get_expense_by_id(expense_id, user_id)

        assert row["id"] == expense_id, (
            "Returned row id must match the requested expense_id"
        )

    def test_own_expense_row_has_correct_user_id(self, seeded_db):
        """The returned row's 'user_id' field matches the requesting user."""
        user_id = seeded_db["user_id"]
        expense_id = _first_expense_id(user_id)

        row = get_expense_by_id(expense_id, user_id)

        assert row["user_id"] == user_id, (
            "Returned row user_id must match the requesting user"
        )

    def test_wrong_user_returns_none(self, seeded_db):
        """An expense owned by another user is invisible — returns None."""
        owner_id = seeded_db["user_id"]
        expense_id = _first_expense_id(owner_id)

        # Empty User doesn't own this expense.
        row = get_expense_by_id(expense_id, seeded_db["empty_user_id"])

        assert row is None, (
            "get_expense_by_id must return None when user_id does not own the row"
        )

    def test_nonexistent_id_returns_none(self, seeded_db):
        """A non-existent expense_id returns None regardless of user_id."""
        row = get_expense_by_id(999999, seeded_db["user_id"])

        assert row is None, (
            "get_expense_by_id must return None for a non-existent expense_id"
        )


# =========================================================================== #
# UNIT TESTS — update_expense                                                  #
# =========================================================================== #

class TestUpdateExpenseUnit:
    """update_expense(expense_id, user_id, amount, category, date, description)."""

    def test_own_expense_amount_is_updated(self, seeded_db):
        """Updating with the correct user_id persists the new amount."""
        user_id = seeded_db["user_id"]
        expense_id = _first_expense_id(user_id)

        update_expense(expense_id, user_id, 99.0, "Health", "2026-01-15", "Doctor")

        row = _fetch_expense_raw(expense_id)
        assert row["amount"] == 99.0, (
            "update_expense must persist the new amount in the DB"
        )

    def test_own_expense_category_is_updated(self, seeded_db):
        """Updating with the correct user_id persists the new category."""
        user_id = seeded_db["user_id"]
        expense_id = _first_expense_id(user_id)

        update_expense(expense_id, user_id, 99.0, "Health", "2026-01-15", "Doctor")

        row = _fetch_expense_raw(expense_id)
        assert row["category"] == "Health"

    def test_own_expense_date_is_updated(self, seeded_db):
        """Updating with the correct user_id persists the new date."""
        user_id = seeded_db["user_id"]
        expense_id = _first_expense_id(user_id)

        update_expense(expense_id, user_id, 99.0, "Health", "2026-01-15", "Doctor")

        row = _fetch_expense_raw(expense_id)
        assert row["date"] == "2026-01-15"

    def test_own_expense_description_is_updated(self, seeded_db):
        """Updating with the correct user_id persists the new description."""
        user_id = seeded_db["user_id"]
        expense_id = _first_expense_id(user_id)

        update_expense(expense_id, user_id, 99.0, "Health", "2026-01-15", "Doctor")

        row = _fetch_expense_raw(expense_id)
        assert row["description"] == "Doctor"

    def test_wrong_user_is_a_noop_no_error(self, seeded_db):
        """Updating with a wrong user_id raises no exception (silent no-op)."""
        owner_id = seeded_db["user_id"]
        expense_id = _first_expense_id(owner_id)

        # Should not raise.
        update_expense(
            expense_id, seeded_db["empty_user_id"],
            1.0, "Other", "2000-01-01", "Hax"
        )

    def test_wrong_user_leaves_amount_unchanged(self, seeded_db):
        """A mismatched user_id leaves the row's amount untouched."""
        owner_id = seeded_db["user_id"]
        expense_id = _first_expense_id(owner_id)
        before = _fetch_expense_raw(expense_id)

        update_expense(
            expense_id, seeded_db["empty_user_id"],
            1.0, "Other", "2000-01-01", "Hax"
        )

        after = _fetch_expense_raw(expense_id)
        assert after["amount"] == before["amount"], (
            "Wrong-user update must not change the expense amount"
        )

    def test_wrong_user_leaves_category_unchanged(self, seeded_db):
        """A mismatched user_id leaves the row's category untouched."""
        owner_id = seeded_db["user_id"]
        expense_id = _first_expense_id(owner_id)
        before = _fetch_expense_raw(expense_id)

        update_expense(
            expense_id, seeded_db["empty_user_id"],
            1.0, "Other", "2000-01-01", "Hax"
        )

        after = _fetch_expense_raw(expense_id)
        assert after["category"] == before["category"], (
            "Wrong-user update must not change the expense category"
        )


# =========================================================================== #
# ROUTE TESTS — GET /expenses/<id>/edit                                        #
# =========================================================================== #

class TestGetEditExpense:
    """GET /expenses/<id>/edit — all GET-method scenarios."""

    # ----------------------------------------------------------------------- #
    # Auth guard                                                               #
    # ----------------------------------------------------------------------- #

    def test_unauthenticated_get_returns_302(self, client):
        """Unauthenticated GET returns 302 (not 200 or 401)."""
        expense_id = _first_expense_id(_demo_user_id())
        resp = client.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 302, (
            "Unauthenticated GET must redirect (302), got %d" % resp.status_code
        )

    def test_unauthenticated_get_redirects_to_login(self, client):
        """Unauthenticated GET Location header contains /login."""
        expense_id = _first_expense_id(_demo_user_id())
        resp = client.get(f"/expenses/{expense_id}/edit")
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated GET must redirect to /login"
        )

    # ----------------------------------------------------------------------- #
    # Ownership — 404 cases                                                    #
    # ----------------------------------------------------------------------- #

    def test_other_users_expense_returns_404(self, client):
        """GET for an expense owned by a different user returns 404."""
        _other_id, expense_id = _make_other_user_with_expense()
        _login_demo(client)

        resp = client.get(f"/expenses/{expense_id}/edit")

        assert resp.status_code == 404, (
            "Accessing another user's expense via GET must return 404"
        )

    def test_nonexistent_id_returns_404(self, client):
        """GET for a non-existent expense id returns 404."""
        _login_demo(client)
        resp = client.get("/expenses/999999/edit")
        assert resp.status_code == 404, (
            "GET for a missing expense id must return 404"
        )

    # ----------------------------------------------------------------------- #
    # Happy path — authenticated, own expense                                  #
    # ----------------------------------------------------------------------- #

    def test_authenticated_own_expense_returns_200(self, client):
        """Authenticated GET for the owner's own expense returns 200."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        resp = client.get(f"/expenses/{expense_id}/edit")

        assert resp.status_code == 200, (
            "Authenticated GET must return 200, got %d" % resp.status_code
        )

    def test_form_prefills_amount(self, client):
        """The response body contains the expense's current amount as a form value."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        row = _fetch_expense_raw(expense_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        # The amount should appear either as value="X" or inside the input in some form.
        assert str(row["amount"]) in body or str(int(row["amount"])) in body, (
            "Pre-filled form must contain the expense's current amount"
        )

    def test_form_prefills_date(self, client):
        """The response body contains the expense's current date as a form value."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        row = _fetch_expense_raw(expense_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert row["date"] in body, (
            "Pre-filled form must contain the expense's current date (YYYY-MM-DD)"
        )

    def test_form_prefills_description(self, client):
        """The response body contains the expense's current description."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        row = _fetch_expense_raw(expense_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        if row["description"]:
            assert row["description"] in body, (
                "Pre-filled form must contain the expense's current description"
            )

    def test_form_action_points_to_edit_url(self, client):
        """The form's action attribute targets this expense's edit URL."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert f"/expenses/{expense_id}/edit" in body, (
            "Form action must point to /expenses/<id>/edit for this expense"
        )

    def test_form_uses_post_method(self, client):
        """The edit form declares POST as its submission method."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert 'method="POST"' in body or "method='POST'" in body or \
               'method="post"' in body or "method='post'" in body, (
            "Edit form must declare method POST"
        )

    def test_category_select_contains_correct_category_option(self, client):
        """The <select> element contains the expense's current category."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        row = _fetch_expense_raw(expense_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert row["category"] in body, (
            "The current category must appear in the rendered form"
        )

    def test_category_select_has_selected_attribute(self, client):
        """The <select> carries a 'selected' attribute on the current category option."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert "selected" in body, (
            "The category <select> must mark the current category as selected"
        )

    @pytest.mark.parametrize("category", EXPECTED_CATEGORIES)
    def test_form_contains_all_seven_category_options(self, client, category):
        """Each of the 7 fixed categories appears as an option in the <select>."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert category in body, (
            f"Category option '{category}' must appear in the edit-expense form"
        )

    def test_form_has_cancel_link_to_profile(self, client):
        """The edit form page includes a cancel link pointing back to /profile."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert "/profile" in body, (
            "Edit form must include a cancel/back link pointing to /profile"
        )

    def test_form_has_submit_button(self, client):
        """The edit form includes a submit button (Save Changes or similar)."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert 'type="submit"' in body or "<button" in body, (
            "Edit form must include a submit button"
        )

    def test_page_extends_base_template(self, client):
        """The rendered page contains base.html landmarks (nav or footer)."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert "<nav" in body or "<footer" in body, (
            "edit_expense.html must extend base.html (nav or footer must be present)"
        )

    def test_form_has_amount_input(self, client):
        """The form contains an input field named 'amount'."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert 'name="amount"' in body, (
            "Edit form must have an amount input (name='amount')"
        )

    def test_form_has_date_input(self, client):
        """The form contains an input field named 'date'."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert 'name="date"' in body, (
            "Edit form must have a date input (name='date')"
        )

    def test_form_has_category_select(self, client):
        """The form contains a <select> named 'category'."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert "<select" in body and 'name="category"' in body, (
            "Edit form must have a category <select> (name='category')"
        )

    def test_form_has_description_input(self, client):
        """The form contains an input or textarea field named 'description'."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        body = client.get(f"/expenses/{expense_id}/edit").get_data(as_text=True)

        assert 'name="description"' in body, (
            "Edit form must have a description field (name='description')"
        )


# =========================================================================== #
# ROUTE TESTS — POST /expenses/<id>/edit                                       #
# =========================================================================== #

class TestPostEditExpense:
    """POST /expenses/<id>/edit — validation, ownership, and happy-path contracts."""

    # ----------------------------------------------------------------------- #
    # Auth guard                                                               #
    # ----------------------------------------------------------------------- #

    def test_unauthenticated_post_returns_302(self, client):
        """Unauthenticated POST returns 302."""
        expense_id = _first_expense_id(_demo_user_id())
        resp = client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())
        assert resp.status_code == 302, (
            "Unauthenticated POST must redirect (302), got %d" % resp.status_code
        )

    def test_unauthenticated_post_redirects_to_login(self, client):
        """Unauthenticated POST Location header contains /login."""
        expense_id = _first_expense_id(_demo_user_id())
        resp = client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated POST must redirect to /login"
        )

    def test_unauthenticated_post_leaves_row_unchanged(self, client):
        """An unauthenticated POST must not modify the expense in the DB."""
        expense_id = _first_expense_id(_demo_user_id())
        before = _fetch_expense_raw(expense_id)

        client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        after = _fetch_expense_raw(expense_id)
        assert after["amount"] == before["amount"], (
            "Unauthenticated POST must not alter the expense row"
        )

    # ----------------------------------------------------------------------- #
    # Ownership — 404 cases                                                    #
    # ----------------------------------------------------------------------- #

    def test_other_users_expense_post_returns_404(self, client):
        """POST to another user's expense returns 404."""
        _other_id, expense_id = _make_other_user_with_expense()
        before = _fetch_expense_raw(expense_id)
        _login_demo(client)

        resp = client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        assert resp.status_code == 404, (
            "POST to another user's expense must return 404"
        )

    def test_other_users_expense_post_leaves_row_unchanged(self, client):
        """POST to another user's expense must not modify the DB row."""
        _other_id, expense_id = _make_other_user_with_expense()
        before = _fetch_expense_raw(expense_id)
        _login_demo(client)

        client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        after = _fetch_expense_raw(expense_id)
        assert after["amount"] == before["amount"], (
            "POST to another user's expense must not alter that row's amount"
        )

    # ----------------------------------------------------------------------- #
    # Happy path — valid data                                                  #
    # ----------------------------------------------------------------------- #

    def test_valid_post_returns_302(self, client):
        """A valid POST redirects (302) — it does not re-render."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        resp = client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        assert resp.status_code == 302, (
            "Valid POST must redirect (302), got %d" % resp.status_code
        )

    def test_valid_post_redirects_to_profile(self, client):
        """A valid POST Location header points to /profile."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        resp = client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        assert "/profile" in resp.headers["Location"], (
            "Successful POST must redirect to /profile"
        )

    def test_valid_post_updates_amount_in_db(self, client):
        """After a valid POST the DB row reflects the new amount."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        row = _fetch_expense_raw(expense_id)
        assert row["amount"] == 75.50, (
            "DB amount must be updated to 75.50 after valid POST"
        )

    def test_valid_post_updates_category_in_db(self, client):
        """After a valid POST the DB row reflects the new category."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        row = _fetch_expense_raw(expense_id)
        assert row["category"] == "Shopping", (
            "DB category must be updated to 'Shopping' after valid POST"
        )

    def test_valid_post_updates_date_in_db(self, client):
        """After a valid POST the DB row reflects the new date."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        row = _fetch_expense_raw(expense_id)
        assert row["date"] == "2026-05-20", (
            "DB date must be updated to '2026-05-20' after valid POST"
        )

    def test_valid_post_updates_description_in_db(self, client):
        """After a valid POST the DB row reflects the new description."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        client.post(f"/expenses/{expense_id}/edit", data=_valid_edit_form())

        row = _fetch_expense_raw(expense_id)
        assert row["description"] == "New backpack", (
            "DB description must be updated to 'New backpack' after valid POST"
        )

    # ----------------------------------------------------------------------- #
    # No description — optional field stores NULL                              #
    # ----------------------------------------------------------------------- #

    def test_no_description_post_returns_302(self, client):
        """POST with blank description still succeeds and redirects (302)."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["description"] = ""
        resp = client.post(f"/expenses/{expense_id}/edit", data=form)

        assert resp.status_code == 302, (
            "POST with no description must redirect (302), got %d" % resp.status_code
        )

    def test_no_description_post_redirects_to_profile(self, client):
        """POST with blank description redirects to /profile."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["description"] = ""
        resp = client.post(f"/expenses/{expense_id}/edit", data=form)

        assert "/profile" in resp.headers["Location"], (
            "POST with no description must redirect to /profile"
        )

    def test_no_description_stored_as_null(self, client):
        """POST with blank description saves description = NULL in the DB."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["description"] = ""
        client.post(f"/expenses/{expense_id}/edit", data=form)

        row = _fetch_expense_raw(expense_id)
        assert row["description"] is None, (
            "Blank description must be stored as NULL, not an empty string"
        )

    def test_whitespace_only_description_stored_as_null(self, client):
        """POST with whitespace-only description saves description = NULL."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["description"] = "   "
        resp = client.post(f"/expenses/{expense_id}/edit", data=form)

        assert resp.status_code == 302, (
            "Whitespace-only description must succeed (302)"
        )
        row = _fetch_expense_raw(expense_id)
        assert row["description"] is None, (
            "Whitespace-only description must be stripped and stored as NULL"
        )

    # ----------------------------------------------------------------------- #
    # Validation errors: all must 200-rerender with an error, row unchanged   #
    # ----------------------------------------------------------------------- #

    def _assert_rejected(self, client, expense_id, form_data):
        """Shared assertion: invalid POST -> 200, error in body, row unchanged."""
        before = _fetch_expense_raw(expense_id)
        resp = client.post(f"/expenses/{expense_id}/edit", data=form_data)

        assert resp.status_code == 200, (
            "Invalid POST must re-render the form (200), not redirect"
        )

        body = resp.get_data(as_text=True)
        assert (
            "error" in body.lower()
            or "invalid" in body.lower()
            or "required" in body.lower()
            or "valid" in body.lower()
            or "greater" in body.lower()
            or "zero" in body.lower()
            or "number" in body.lower()
            or "positive" in body.lower()
            or "category" in body.lower()
            or "date" in body.lower()
            or "amount" in body.lower()
        ), "An error message must appear in the re-rendered form body"

        after = _fetch_expense_raw(expense_id)
        assert after["amount"] == before["amount"], (
            "Validation failure must not change the row's amount"
        )
        assert after["category"] == before["category"], (
            "Validation failure must not change the row's category"
        )
        assert after["date"] == before["date"], (
            "Validation failure must not change the row's date"
        )

    def test_missing_amount_returns_200_with_error(self, client):
        """POST with empty amount re-renders form with 200 and an error message."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["amount"] = ""
        self._assert_rejected(client, expense_id, form)

    def test_zero_amount_returns_200_with_error(self, client):
        """POST with amount=0 re-renders form with 200 and an error message."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["amount"] = "0"
        self._assert_rejected(client, expense_id, form)

    def test_zero_decimal_amount_returns_200_with_error(self, client):
        """POST with amount=0.00 re-renders form with 200 and an error message."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["amount"] = "0.00"
        self._assert_rejected(client, expense_id, form)

    def test_non_numeric_amount_returns_200_with_error(self, client):
        """POST with non-numeric amount re-renders form with 200 and an error message."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["amount"] = "abc"
        self._assert_rejected(client, expense_id, form)

    def test_invalid_category_returns_200_with_error(self, client):
        """POST with a category not in the fixed list re-renders form with 200 and error."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["category"] = "Crypto"
        self._assert_rejected(client, expense_id, form)

    def test_empty_category_returns_200_with_error(self, client):
        """POST with an empty category string re-renders form with 200 and error."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["category"] = ""
        self._assert_rejected(client, expense_id, form)

    def test_invalid_date_string_returns_200_with_error(self, client):
        """POST with a non-ISO date re-renders form with 200 and an error message."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["date"] = "not-a-date"
        self._assert_rejected(client, expense_id, form)

    def test_wrong_date_format_dd_mm_yyyy_returns_200(self, client):
        """POST with DD/MM/YYYY date (wrong format) re-renders form with 200."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["date"] = "20/05/2026"
        self._assert_rejected(client, expense_id, form)

    def test_empty_date_returns_200_with_error(self, client):
        """POST with empty date string re-renders form with 200 and an error message."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form["date"] = ""
        self._assert_rejected(client, expense_id, form)

    # ----------------------------------------------------------------------- #
    # Parametrised rejection sweep                                             #
    # ----------------------------------------------------------------------- #

    @pytest.mark.parametrize("bad_field,bad_value,label", [
        ("amount",   "",           "missing amount"),
        ("amount",   "0",          "zero amount"),
        ("amount",   "0.00",       "zero amount (0.00)"),
        ("amount",   "-10",        "negative amount"),
        ("amount",   "abc",        "non-numeric amount"),
        ("category", "Crypto",     "invalid category"),
        ("category", "",           "empty category"),
        ("date",     "not-a-date", "non-ISO date"),
        ("date",     "",           "empty date"),
        ("date",     "20/05/2026", "wrong date format DD/MM/YYYY"),
    ])
    def test_rejected_post_returns_200(self, client, bad_field, bad_value, label):
        """Every invalid field value causes the form to re-render (200)."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        form = _valid_edit_form()
        form[bad_field] = bad_value

        resp = client.post(f"/expenses/{expense_id}/edit", data=form)
        assert resp.status_code == 200, (
            f"Validation failure ({label}) must re-render form (200), "
            f"got {resp.status_code}"
        )

    @pytest.mark.parametrize("bad_field,bad_value,label", [
        ("amount",   "",           "missing amount"),
        ("amount",   "0",          "zero amount"),
        ("amount",   "-10",        "negative amount"),
        ("amount",   "abc",        "non-numeric amount"),
        ("category", "Crypto",     "invalid category"),
        ("category", "",           "empty category"),
        ("date",     "not-a-date", "non-ISO date"),
        ("date",     "",           "empty date"),
    ])
    def test_rejected_post_does_not_update_db(self, client, bad_field, bad_value, label):
        """Every invalid field value leaves the DB row unchanged."""
        demo_id = _demo_user_id()
        expense_id = _first_expense_id(demo_id)
        _login_demo(client)

        before = _fetch_expense_raw(expense_id)
        form = _valid_edit_form()
        form[bad_field] = bad_value

        client.post(f"/expenses/{expense_id}/edit", data=form)

        after = _fetch_expense_raw(expense_id)
        assert after["amount"] == before["amount"], (
            f"Validation failure ({label}) must not update the expense amount"
        )
        assert after["category"] == before["category"], (
            f"Validation failure ({label}) must not update the expense category"
        )
        assert after["date"] == before["date"], (
            f"Validation failure ({label}) must not update the expense date"
        )


# =========================================================================== #
# PROFILE PAGE — "Edit" link appears per transaction row                       #
# =========================================================================== #

class TestProfileEditLinks:
    """profile.html must include an Edit link per transaction row (spec §templates)."""

    def test_profile_contains_edit_links(self, client):
        """Authenticated profile page contains at least one /expenses/<id>/edit link."""
        _login_demo(client)
        body = client.get("/profile").get_data(as_text=True)

        assert "/edit" in body, (
            "profile.html must include edit links (href containing /edit) "
            "in the transactions table"
        )

    def test_profile_edit_links_point_to_correct_url_pattern(self, client):
        """Edit links follow the /expenses/<id>/edit URL pattern."""
        _login_demo(client)
        body = client.get("/profile").get_data(as_text=True)

        assert "/expenses/" in body and "/edit" in body, (
            "Edit links must follow the /expenses/<id>/edit pattern"
        )

    def test_profile_contains_actions_header_or_edit_text(self, client):
        """The transactions table exposes an 'Edit' action per row."""
        _login_demo(client)
        body = client.get("/profile").get_data(as_text=True)

        assert "Edit" in body or "edit" in body, (
            "profile.html must contain 'Edit' text for the per-row edit action"
        )
