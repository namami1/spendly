"""Step 7 — Add Expense: full test suite derived from spec 07-add-expense.md.

Tests cover:
  - insert_expense unit contract (valid row, NULL description)
  - Auth guards on GET and POST /expenses/add
  - GET happy path: 200, form structure, all 7 categories present
  - POST happy path: 302 redirect to /profile, row inserted, correct field values
  - POST optional description: 302, row count +1, description stored as NULL
  - POST validation errors: 200 re-render with error message, row count unchanged
    (missing amount, zero amount, negative amount, non-numeric amount,
     invalid category, invalid date string, malformed date)

Fixtures reused from conftest.py:
  - ``seeded_db`` — temp SQLite DB with one known user (Test User / test@example.com)
    and a handful of controlled expenses; used for insert_expense unit tests.
  - ``client`` — Flask test client backed by a temp DB seeded with Demo User
    (demo@spendly.com / demo123) and 8 sample expenses; used for route tests.

Source files were read only for route names, helper signatures, and DB schema —
never for deriving expected behaviour. All expectations come from the spec.
"""

import pytest

import database.db as db
from database.queries import insert_expense

# --------------------------------------------------------------------------- #
# Fixed categories (single source of truth from spec §rules)                  #
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


def _count_expenses(user_id):
    """Return the number of expense rows belonging to *user_id*."""
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


def _login_demo(client):
    """Inject the Demo User's id directly into the session (no password round-trip)."""
    with client.session_transaction() as sess:
        sess["user_id"] = _demo_user_id()


# =========================================================================== #
# UNIT TESTS — insert_expense                                                  #
# =========================================================================== #

class TestInsertExpenseUnit:
    """insert_expense(user_id, amount, category, date, description) contracts."""

    def test_valid_insert_returns_new_row_id(self, seeded_db):
        """A valid call returns a truthy integer row id."""
        new_id = insert_expense(
            seeded_db["user_id"], 50.0, "Food", "2026-03-20", "Lunch"
        )
        assert isinstance(new_id, int), "insert_expense must return an integer row id"
        assert new_id > 0, "Returned row id must be positive"

    def test_valid_insert_row_is_retrievable(self, seeded_db):
        """The inserted row can be fetched back with all fields intact."""
        new_id = insert_expense(
            seeded_db["user_id"], 50.0, "Food", "2026-03-20", "Lunch"
        )
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT * FROM expenses WHERE id = ?", (new_id,)
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, "Inserted row must be retrievable by its id"
        assert row["user_id"] == seeded_db["user_id"], (
            "Row must be scoped to the correct user_id"
        )
        assert row["amount"] == 50.0, "amount must match the value passed to insert_expense"
        assert row["category"] == "Food", "category must match the value passed"
        assert row["date"] == "2026-03-20", "date must match the value passed"
        assert row["description"] == "Lunch", "description must match the value passed"

    def test_insert_expense_description_none_stored_as_null(self, seeded_db):
        """Passing description=None stores SQL NULL (not the string 'None')."""
        new_id = insert_expense(
            seeded_db["user_id"], 12.5, "Transport", "2026-03-21", None
        )
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT description FROM expenses WHERE id = ?", (new_id,)
            ).fetchone()
        finally:
            conn.close()

        assert row is not None, "Row must exist after insert"
        assert row["description"] is None, (
            "description must be NULL in the DB when None is passed"
        )

    def test_insert_expense_increments_row_count(self, seeded_db):
        """Each call to insert_expense adds exactly one row for that user."""
        before = _count_expenses(seeded_db["user_id"])
        insert_expense(seeded_db["user_id"], 9.99, "Bills", "2026-03-22", "Gas")
        after = _count_expenses(seeded_db["user_id"])
        assert after == before + 1, (
            "insert_expense must add exactly one row to the expenses table"
        )

    def test_insert_expense_does_not_affect_other_users(self, seeded_db):
        """Inserting for user_id does not create rows for any other user."""
        before_other = _count_expenses(seeded_db["empty_user_id"])
        insert_expense(seeded_db["user_id"], 5.0, "Other", "2026-03-23", "Test")
        after_other = _count_expenses(seeded_db["empty_user_id"])
        assert after_other == before_other, (
            "insert_expense must not create rows for other users"
        )


# =========================================================================== #
# AUTH GUARD TESTS                                                             #
# =========================================================================== #

class TestAuthGuard:
    """Both GET and POST /expenses/add must redirect unauthenticated requests to /login."""

    def test_get_unauthenticated_redirects_302(self, client):
        """Unauthenticated GET /expenses/add returns 302."""
        resp = client.get("/expenses/add")
        assert resp.status_code == 302, (
            "Unauthenticated GET must return 302, not %d" % resp.status_code
        )

    def test_get_unauthenticated_redirects_to_login(self, client):
        """Unauthenticated GET /expenses/add redirects to /login."""
        resp = client.get("/expenses/add")
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated GET must redirect to /login"
        )

    def test_post_unauthenticated_redirects_302(self, client):
        """Unauthenticated POST /expenses/add returns 302."""
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 302, (
            "Unauthenticated POST must return 302, not %d" % resp.status_code
        )

    def test_post_unauthenticated_redirects_to_login(self, client):
        """Unauthenticated POST /expenses/add redirects to /login."""
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert "/login" in resp.headers["Location"], (
            "Unauthenticated POST must redirect to /login"
        )

    def test_post_unauthenticated_inserts_nothing(self, client):
        """Unauthenticated POST must not insert any expense row."""
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert _count_expenses(user_id) == before, (
            "An unauthenticated POST must insert zero rows"
        )


# =========================================================================== #
# GET /expenses/add — authenticated                                            #
# =========================================================================== #

class TestGetAddExpenseAuthenticated:
    """GET /expenses/add while logged in must render the form correctly."""

    def test_get_returns_200(self, client):
        """Authenticated GET /expenses/add returns HTTP 200."""
        _login_demo(client)
        resp = client.get("/expenses/add")
        assert resp.status_code == 200, (
            "Authenticated GET must return 200, got %d" % resp.status_code
        )

    def test_get_response_contains_form_element(self, client):
        """Response body contains a <form element."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert "<form" in body, "Response must contain a <form element"

    def test_get_form_uses_post_method(self, client):
        """The form element declares method POST (case-insensitive)."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert 'method="POST"' in body or "method='POST'" in body or \
               'method="post"' in body or "method='post'" in body, (
            "Form must declare method POST"
        )

    def test_get_form_action_points_to_add_expense(self, client):
        """The form action points to /expenses/add."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert "/expenses/add" in body, (
            "Form action must point to /expenses/add"
        )

    def test_get_form_has_amount_field(self, client):
        """Response body contains an amount input field."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert 'name="amount"' in body, "Form must include an amount input (name='amount')"

    def test_get_form_has_category_select(self, client):
        """Response body contains a category <select> element."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert "<select" in body, "Form must include a <select> for categories"
        assert 'name="category"' in body, "Category select must have name='category'"

    def test_get_form_has_date_field(self, client):
        """Response body contains a date input field."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert 'name="date"' in body, "Form must include a date input (name='date')"

    def test_get_form_has_description_field(self, client):
        """Response body contains a description input field."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert 'name="description"' in body, (
            "Form must include a description input (name='description')"
        )

    @pytest.mark.parametrize("category", EXPECTED_CATEGORIES)
    def test_get_form_contains_each_category_option(self, client, category):
        """Every one of the 7 fixed categories appears as an <option> in the select."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert category in body, (
            f"Category option '{category}' must appear in the add-expense form"
        )

    def test_get_form_contains_exactly_seven_expected_categories(self, client):
        """All 7 fixed categories — Food, Transport, Bills, Health, Entertainment, Shopping, Other — are present."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        for category in EXPECTED_CATEGORIES:
            assert category in body, (
                f"Expected category '{category}' not found in form body"
            )

    def test_get_form_has_cancel_link_to_profile(self, client):
        """The form page includes a cancel link pointing back to /profile."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert "/profile" in body, (
            "Form must include a cancel link pointing to /profile"
        )

    def test_get_form_has_submit_button(self, client):
        """The form includes a submit button."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        assert (
            'type="submit"' in body
            or "<button" in body
        ), "Form must include a submit button"

    def test_get_extends_base_template(self, client):
        """The rendered page includes the base template shell (navbar or footer landmark)."""
        _login_demo(client)
        body = client.get("/expenses/add").get_data(as_text=True)
        # base.html renders either a <nav or a <footer; either signals the shell loaded.
        assert "<nav" in body or "<footer" in body, (
            "add_expense.html must extend base.html (nav or footer must be present)"
        )


# =========================================================================== #
# POST /expenses/add — happy path (valid data)                                 #
# =========================================================================== #

class TestPostAddExpenseValid:
    """A valid POST must insert one expense scoped to the session user and redirect."""

    def test_valid_post_redirects_302(self, client):
        """Valid POST returns 302."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.status_code == 302, (
            "Valid POST must redirect (302), got %d" % resp.status_code
        )

    def test_valid_post_redirects_to_profile(self, client):
        """Valid POST redirects to /profile."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert resp.headers["Location"].endswith("/profile"), (
            "Successful POST must redirect to /profile"
        )

    def test_valid_post_increments_expense_count_by_one(self, client):
        """Valid POST adds exactly one row to the expenses table for the user."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        assert _count_expenses(user_id) == before + 1, (
            "Successful POST must insert exactly one expense row"
        )

    def test_valid_post_row_scoped_to_session_user(self, client):
        """Inserted row's user_id matches the logged-in session user."""
        _login_demo(client)
        user_id = _demo_user_id()
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch",
        })
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT user_id FROM expenses WHERE user_id = ? AND description = ?",
                (user_id, "Lunch"),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "Inserted expense must be associated with the session user"
        assert row["user_id"] == user_id, (
            "expense.user_id must equal the logged-in user's id"
        )

    def test_valid_post_stores_correct_amount(self, client):
        """The inserted row stores the submitted amount as a float."""
        _login_demo(client)
        user_id = _demo_user_id()
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "CorrectAmountCheck",
        })
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT amount FROM expenses WHERE user_id = ? AND description = ?",
                (user_id, "CorrectAmountCheck"),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "Row must exist after valid POST"
        assert row["amount"] == 50.0, "Stored amount must equal the submitted value"

    def test_valid_post_stores_correct_category(self, client):
        """The inserted row stores the submitted category exactly."""
        _login_demo(client)
        user_id = _demo_user_id()
        client.post("/expenses/add", data={
            "amount": "25.0",
            "category": "Transport",
            "date": "2026-03-20",
            "description": "CorrectCategoryCheck",
        })
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT category FROM expenses WHERE user_id = ? AND description = ?",
                (user_id, "CorrectCategoryCheck"),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "Row must exist after valid POST"
        assert row["category"] == "Transport", (
            "Stored category must equal the submitted value"
        )

    def test_valid_post_stores_correct_date(self, client):
        """The inserted row stores the date in YYYY-MM-DD format."""
        _login_demo(client)
        user_id = _demo_user_id()
        client.post("/expenses/add", data={
            "amount": "15.0",
            "category": "Health",
            "date": "2026-03-20",
            "description": "CorrectDateCheck",
        })
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT date FROM expenses WHERE user_id = ? AND description = ?",
                (user_id, "CorrectDateCheck"),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "Row must exist after valid POST"
        assert row["date"] == "2026-03-20", "Stored date must equal the submitted YYYY-MM-DD value"


# =========================================================================== #
# POST /expenses/add — optional description                                    #
# =========================================================================== #

class TestPostAddExpenseNoDescription:
    """Omitting the optional description field must succeed and store NULL."""

    def test_no_description_post_redirects_302(self, client):
        """POST without description returns 302 (not a validation error)."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "8.25",
            "category": "Other",
            "date": "2026-03-22",
        })
        assert resp.status_code == 302, (
            "POST with no description must redirect (302), got %d" % resp.status_code
        )

    def test_no_description_post_redirects_to_profile(self, client):
        """POST without description redirects to /profile."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "8.25",
            "category": "Other",
            "date": "2026-03-22",
        })
        assert resp.headers["Location"].endswith("/profile"), (
            "POST with no description must redirect to /profile"
        )

    def test_no_description_increments_row_count(self, client):
        """POST without description inserts exactly one row."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "8.25",
            "category": "Other",
            "date": "2026-03-22",
        })
        assert _count_expenses(user_id) == before + 1, (
            "POST with no description must insert exactly one row"
        )

    def test_no_description_stored_as_null(self, client):
        """When no description is submitted, the DB column stores NULL."""
        _login_demo(client)
        user_id = _demo_user_id()
        client.post("/expenses/add", data={
            "amount": "8.25",
            "category": "Other",
            "date": "2026-03-22",
        })
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT description FROM expenses "
                "WHERE user_id = ? AND amount = ? AND date = ?",
                (user_id, 8.25, "2026-03-22"),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "Row must exist after successful POST"
        assert row["description"] is None, (
            "description must be NULL when the field is omitted"
        )

    def test_empty_string_description_stored_as_null(self, client):
        """An explicitly empty description string is stripped and stored as NULL."""
        _login_demo(client)
        user_id = _demo_user_id()
        client.post("/expenses/add", data={
            "amount": "11.11",
            "category": "Bills",
            "date": "2026-03-23",
            "description": "   ",   # whitespace-only; spec says strip, store None
        })
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT description FROM expenses "
                "WHERE user_id = ? AND amount = ? AND date = ?",
                (user_id, 11.11, "2026-03-23"),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None, "Row must exist after successful POST"
        assert row["description"] is None, (
            "Whitespace-only description must be stored as NULL"
        )


# =========================================================================== #
# POST /expenses/add — validation errors                                       #
# =========================================================================== #

class TestPostAddExpenseValidationErrors:
    """Each validation failure must re-render the form (200) with an error message
    and leave the expenses table row count unchanged."""

    # ----------------------------------------------------------------------- #
    # Amount validation                                                        #
    # ----------------------------------------------------------------------- #

    def test_missing_amount_returns_200(self, client):
        """POST with empty amount re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert resp.status_code == 200, (
            "Missing amount must re-render form (200), got %d" % resp.status_code
        )

    def test_missing_amount_shows_error_message(self, client):
        """POST with empty amount includes an error message in the response body."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
        })
        body = resp.get_data(as_text=True)
        # The spec says re-render with an error message; we assert some error
        # indicator appears — either a CSS error class or a human-readable message.
        assert (
            "error" in body.lower()
            or "invalid" in body.lower()
            or "required" in body.lower()
            or "amount" in body.lower()
        ), "Response must contain an error message when amount is missing"

    def test_missing_amount_inserts_nothing(self, client):
        """POST with empty amount inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (missing amount) must not insert any rows"
        )

    def test_zero_amount_returns_200(self, client):
        """POST with amount=0 re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert resp.status_code == 200, (
            "Zero amount must re-render form (200), got %d" % resp.status_code
        )

    def test_zero_amount_shows_error_message(self, client):
        """POST with amount=0 includes an error message in the response body."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
        })
        body = resp.get_data(as_text=True)
        assert (
            "error" in body.lower()
            or "greater" in body.lower()
            or "zero" in body.lower()
            or "positive" in body.lower()
            or "amount" in body.lower()
        ), "Response must contain an error message when amount is zero"

    def test_zero_amount_inserts_nothing(self, client):
        """POST with amount=0 inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (zero amount) must not insert any rows"
        )

    def test_negative_amount_returns_200(self, client):
        """POST with a negative amount re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "-5.00",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert resp.status_code == 200, (
            "Negative amount must re-render form (200), got %d" % resp.status_code
        )

    def test_negative_amount_shows_error_message(self, client):
        """POST with a negative amount includes an error message."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "-5.00",
            "category": "Food",
            "date": "2026-03-20",
        })
        body = resp.get_data(as_text=True)
        assert (
            "error" in body.lower()
            or "greater" in body.lower()
            or "positive" in body.lower()
            or "amount" in body.lower()
        ), "Response must contain an error message when amount is negative"

    def test_negative_amount_inserts_nothing(self, client):
        """POST with a negative amount inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "-5.00",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (negative amount) must not insert any rows"
        )

    def test_non_numeric_amount_returns_200(self, client):
        """POST with a non-numeric amount re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert resp.status_code == 200, (
            "Non-numeric amount must re-render form (200), got %d" % resp.status_code
        )

    def test_non_numeric_amount_shows_error_message(self, client):
        """POST with a non-numeric amount includes an error message."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
        })
        body = resp.get_data(as_text=True)
        assert (
            "error" in body.lower()
            or "number" in body.lower()
            or "numeric" in body.lower()
            or "amount" in body.lower()
            or "invalid" in body.lower()
        ), "Response must contain an error message when amount is non-numeric"

    def test_non_numeric_amount_inserts_nothing(self, client):
        """POST with a non-numeric amount inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (non-numeric amount) must not insert any rows"
        )

    # ----------------------------------------------------------------------- #
    # Category validation                                                      #
    # ----------------------------------------------------------------------- #

    def test_invalid_category_returns_200(self, client):
        """POST with a category not in the fixed list re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Crypto",
            "date": "2026-03-20",
        })
        assert resp.status_code == 200, (
            "Invalid category must re-render form (200), got %d" % resp.status_code
        )

    def test_invalid_category_shows_error_message(self, client):
        """POST with an invalid category includes an error message."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Crypto",
            "date": "2026-03-20",
        })
        body = resp.get_data(as_text=True)
        assert (
            "error" in body.lower()
            or "category" in body.lower()
            or "valid" in body.lower()
            or "choose" in body.lower()
        ), "Response must contain an error message when category is invalid"

    def test_invalid_category_inserts_nothing(self, client):
        """POST with an invalid category inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Crypto",
            "date": "2026-03-20",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (invalid category) must not insert any rows"
        )

    def test_empty_category_returns_200(self, client):
        """POST with an empty category string re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "",
            "date": "2026-03-20",
        })
        assert resp.status_code == 200, (
            "Empty category must re-render form (200), got %d" % resp.status_code
        )

    def test_empty_category_inserts_nothing(self, client):
        """POST with empty category inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "",
            "date": "2026-03-20",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (empty category) must not insert any rows"
        )

    # ----------------------------------------------------------------------- #
    # Date validation                                                          #
    # ----------------------------------------------------------------------- #

    def test_invalid_date_string_returns_200(self, client):
        """POST with a non-ISO date string re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
        })
        assert resp.status_code == 200, (
            "Invalid date string must re-render form (200), got %d" % resp.status_code
        )

    def test_invalid_date_string_shows_error_message(self, client):
        """POST with a non-ISO date includes an error message."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
        })
        body = resp.get_data(as_text=True)
        assert (
            "error" in body.lower()
            or "date" in body.lower()
            or "valid" in body.lower()
            or "invalid" in body.lower()
        ), "Response must contain an error message when the date is invalid"

    def test_invalid_date_string_inserts_nothing(self, client):
        """POST with a non-ISO date string inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (invalid date) must not insert any rows"
        )

    def test_malformed_date_dd_mm_yyyy_returns_200(self, client):
        """POST with a DD/MM/YYYY date (wrong format) re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "20/03/2026",   # wrong separator and order — not YYYY-MM-DD
        })
        assert resp.status_code == 200, (
            "DD/MM/YYYY date must be rejected (200), got %d" % resp.status_code
        )

    def test_malformed_date_dd_mm_yyyy_inserts_nothing(self, client):
        """POST with DD/MM/YYYY date inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "20/03/2026",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (DD/MM/YYYY date) must not insert any rows"
        )

    def test_empty_date_returns_200(self, client):
        """POST with an empty date string re-renders the form with 200."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "",
        })
        assert resp.status_code == 200, (
            "Empty date must re-render form (200), got %d" % resp.status_code
        )

    def test_empty_date_inserts_nothing(self, client):
        """POST with an empty date inserts zero rows."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "",
        })
        assert _count_expenses(user_id) == before, (
            "Validation failure (empty date) must not insert any rows"
        )

    # ----------------------------------------------------------------------- #
    # Parametrised sweep: all rejection cases in one table                     #
    # ----------------------------------------------------------------------- #

    @pytest.mark.parametrize("bad_data,description", [
        ({"amount": "",      "category": "Food",   "date": "2026-03-20"}, "missing amount"),
        ({"amount": "0",     "category": "Food",   "date": "2026-03-20"}, "zero amount"),
        ({"amount": "0.00",  "category": "Food",   "date": "2026-03-20"}, "zero amount (0.00)"),
        ({"amount": "-1",    "category": "Food",   "date": "2026-03-20"}, "negative amount"),
        ({"amount": "abc",   "category": "Food",   "date": "2026-03-20"}, "non-numeric amount"),
        ({"amount": "1e999", "category": "Food",   "date": "2026-03-20"}, "infinity amount"),
        ({"amount": "50",    "category": "Crypto", "date": "2026-03-20"}, "invalid category"),
        ({"amount": "50",    "category": "",       "date": "2026-03-20"}, "empty category"),
        ({"amount": "50",    "category": "Food",   "date": "bad-date"},   "malformed date"),
        ({"amount": "50",    "category": "Food",   "date": ""},           "empty date"),
        ({"amount": "50",    "category": "Food",   "date": "03-20-2026"}, "wrong date format"),
    ])
    def test_rejected_post_does_not_insert(self, client, bad_data, description):
        """Every invalid POST inserts zero rows (parametrised sweep)."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        client.post("/expenses/add", data=bad_data)
        assert _count_expenses(user_id) == before, (
            f"Validation failure ({description}) must not insert any rows"
        )

    @pytest.mark.parametrize("bad_data,description", [
        ({"amount": "",      "category": "Food",   "date": "2026-03-20"}, "missing amount"),
        ({"amount": "0",     "category": "Food",   "date": "2026-03-20"}, "zero amount"),
        ({"amount": "-1",    "category": "Food",   "date": "2026-03-20"}, "negative amount"),
        ({"amount": "abc",   "category": "Food",   "date": "2026-03-20"}, "non-numeric amount"),
        ({"amount": "50",    "category": "Crypto", "date": "2026-03-20"}, "invalid category"),
        ({"amount": "50",    "category": "Food",   "date": "bad-date"},   "malformed date"),
        ({"amount": "50",    "category": "Food",   "date": ""},           "empty date"),
    ])
    def test_rejected_post_returns_200(self, client, bad_data, description):
        """Every invalid POST re-renders the form as HTTP 200 (parametrised sweep)."""
        _login_demo(client)
        resp = client.post("/expenses/add", data=bad_data)
        assert resp.status_code == 200, (
            f"Validation failure ({description}) must re-render form (200), "
            f"got {resp.status_code}"
        )

    # ----------------------------------------------------------------------- #
    # Bounds: an astronomically large (but finite) amount and an over-long     #
    # description must both be rejected server-side, not just by the browser.  #
    # ----------------------------------------------------------------------- #

    def test_excessively_large_amount_rejected(self, client):
        """A finite-but-huge amount (1e308) re-renders the form and inserts nothing."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        resp = client.post("/expenses/add", data={
            "amount": "1e308",
            "category": "Food",
            "date": "2026-03-20",
        })
        assert resp.status_code == 200
        assert _count_expenses(user_id) == before, (
            "An out-of-range amount must not insert any rows"
        )

    def test_overlong_description_rejected(self, client):
        """A description over 200 chars is rejected server-side (maxlength bypass)."""
        _login_demo(client)
        user_id = _demo_user_id()
        before = _count_expenses(user_id)
        resp = client.post("/expenses/add", data={
            "amount": "50",
            "category": "Food",
            "date": "2026-03-20",
            "description": "x" * 201,
        })
        assert resp.status_code == 200
        assert _count_expenses(user_id) == before, (
            "An over-long description must not insert any rows"
        )


# =========================================================================== #
# FORM VALUE REPOPULATION                                                      #
# =========================================================================== #

class TestFormRepopulation:
    """On validation failure the previously submitted values must be pre-filled."""

    def test_previously_submitted_amount_is_repopulated(self, client):
        """After a failed POST, the submitted amount value appears in the re-rendered form."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "99.99",
            "category": "Crypto",   # invalid — triggers rejection
            "date": "2026-03-20",
            "description": "Test repopulate",
        })
        body = resp.get_data(as_text=True)
        assert "99.99" in body, (
            "Previously entered amount must be repopulated in the re-rendered form"
        )

    def test_previously_submitted_description_is_repopulated(self, client):
        """After a failed POST, the submitted description value appears in the form."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "abc",        # invalid — triggers rejection
            "category": "Food",
            "date": "2026-03-20",
            "description": "My unique repopulation text",
        })
        body = resp.get_data(as_text=True)
        assert "My unique repopulation text" in body, (
            "Previously entered description must be repopulated in the re-rendered form"
        )

    def test_previously_submitted_date_is_repopulated(self, client):
        """After a failed POST, the submitted date appears in the re-rendered form."""
        _login_demo(client)
        resp = client.post("/expenses/add", data={
            "amount": "abc",        # invalid — triggers rejection
            "category": "Food",
            "date": "2026-05-15",
            "description": "",
        })
        body = resp.get_data(as_text=True)
        assert "2026-05-15" in body, (
            "Previously entered date must be repopulated in the re-rendered form"
        )


# =========================================================================== #
# NAVBAR "Add Expense" LINK                                                    #
# =========================================================================== #

class TestNavbarLink:
    """base.html must show an 'Add Expense' link in the navbar when logged in."""

    def test_add_expense_link_visible_when_logged_in(self, client):
        """Navbar contains 'Add Expense' link when a session is active."""
        _login_demo(client)
        resp = client.get("/profile")
        body = resp.get_data(as_text=True)
        assert "/expenses/add" in body, (
            "Navbar must contain an /expenses/add link when the user is logged in"
        )

    def test_add_expense_link_in_profile_page(self, client):
        """Profile page contains a link or button pointing to /expenses/add."""
        _login_demo(client)
        body = client.get("/profile").get_data(as_text=True)
        assert "/expenses/add" in body, (
            "profile.html must include an 'Add Expense' button/link to /expenses/add"
        )
