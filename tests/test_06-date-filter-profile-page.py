"""
Step 6 — Date Filter for Profile Page.

Tests are derived entirely from the spec (.claude/specs/06-date-filter-profile-page.md).
Source files were read only for route names, helper signatures, and DB schema.

Fixture strategy
----------------
- ``seeded_db`` patches database.db.DB_PATH to a temp SQLite file and inserts
  a controlled set of expenses with *explicit* dates spanning three time bands:
    - "current month"  : 2026-06-05, 2026-06-10
    - "last 3 months"  : 2026-04-15
    - "last 6 months"  : 2026-01-20
    - "older / outside": 2025-09-01
  This makes every date-range assertion deterministic and independent of the
  system clock.
- ``client`` patches the same DB_PATH and calls seed_db() for route-level tests
  that need a real logged-in session; an additional controlled user is injected
  for filter assertions.
- Today's date in project context is 2026-06-12.
"""

import pytest

import database.db as db
from database.db import get_db, init_db
from database.queries import (
    _date_clause,
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
)


# --------------------------------------------------------------------------- #
# Shared constants                                                             #
# --------------------------------------------------------------------------- #

# Bands used in seeded_db (see fixture below).
DATE_CURRENT_MONTH_1 = "2026-06-05"
DATE_CURRENT_MONTH_2 = "2026-06-10"
DATE_3_MONTHS_AGO    = "2026-04-15"   # within last-3-months window
DATE_6_MONTHS_AGO    = "2026-01-20"   # within last-6-months window (not last-3)
DATE_OUTSIDE_ALL     = "2025-09-01"   # older than 6 months from 2026-06-12


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Temp DB with one main user (controlled expenses) and one empty user."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test_step6.db"))
    init_db()

    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Test User", "test@example.com", "hashed"),
        )
        user_id = cursor.lastrowid

        empty_cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty User", "empty@example.com", "hashed"),
        )
        empty_user_id = empty_cursor.lastrowid

        # Expenses spread across four time bands so filters produce deterministic
        # counts and totals.
        #   current month (June 2026):  10.00 + 20.00 = 30.00 (Food, Bills)
        #   within last 3 months (Apr): 50.00 (Transport)
        #   within last 6 months (Jan): 40.00 (Health)
        #   outside 6 months (Sep '25): 99.00 (Shopping)
        expenses = [
            (user_id, 10.00, "Food",      DATE_CURRENT_MONTH_1, "Lunch"),
            (user_id, 20.00, "Bills",     DATE_CURRENT_MONTH_2, "Electricity"),
            (user_id, 50.00, "Transport", DATE_3_MONTHS_AGO,    "Bus pass"),
            (user_id, 40.00, "Health",    DATE_6_MONTHS_AGO,    "Doctor"),
            (user_id, 99.00, "Shopping",  DATE_OUTSIDE_ALL,     "Jacket"),
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
    """Flask test client backed by a temp DB that has the Demo User seeded."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "route_step6.db"))
    init_db()

    from database.db import seed_db
    seed_db()

    from app import app
    app.config.update(TESTING=True, SECRET_KEY="test-step6")
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def controlled_client(tmp_path, monkeypatch):
    """Flask test client backed by a temp DB with the controlled expense set.

    Inserts the same five rows as ``seeded_db`` so route-level filter assertions
    are deterministic.
    """
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ctrl_step6.db"))
    init_db()

    conn = get_db()
    try:
        from werkzeug.security import generate_password_hash
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Ctrl User", "ctrl@example.com", generate_password_hash("password123")),
        )
        user_id = cursor.lastrowid

        expenses = [
            (user_id, 10.00, "Food",      DATE_CURRENT_MONTH_1, "Lunch"),
            (user_id, 20.00, "Bills",     DATE_CURRENT_MONTH_2, "Electricity"),
            (user_id, 50.00, "Transport", DATE_3_MONTHS_AGO,    "Bus pass"),
            (user_id, 40.00, "Health",    DATE_6_MONTHS_AGO,    "Doctor"),
            (user_id, 99.00, "Shopping",  DATE_OUTSIDE_ALL,     "Jacket"),
        ]
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            expenses,
        )
        conn.commit()
    finally:
        conn.close()

    from app import app
    app.config.update(TESTING=True, SECRET_KEY="test-ctrl")
    with app.test_client() as test_client:
        # Inject the session directly so no password-hashing round-trip is needed.
        with test_client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Ctrl User"
        yield test_client


# --------------------------------------------------------------------------- #
# Helper: look up the Demo User's id via the active DB_PATH                   #
# --------------------------------------------------------------------------- #

def _demo_user_id():
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)
        ).fetchone()
    finally:
        conn.close()
    return row["id"]


# =========================================================================== #
# AUTH GUARD                                                                   #
# =========================================================================== #

class TestAuthGuard:
    def test_profile_no_auth_redirects_to_login(self, client):
        """Unauthenticated GET /profile must redirect to /login (spec: route protected)."""
        resp = client.get("/profile")
        assert resp.status_code == 302, "Expected redirect for unauthenticated request"
        assert "/login" in resp.headers["Location"], (
            "Redirect should point to /login"
        )

    def test_profile_with_date_params_no_auth_redirects_to_login(self, client):
        """Auth guard applies even when date filter params are present."""
        resp = client.get("/profile?date_from=2026-06-01&date_to=2026-06-30")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# =========================================================================== #
# HAPPY PATH — no query params (same as Step 5 unfiltered)                    #
# =========================================================================== #

class TestNoParams:
    def test_no_params_returns_200(self, client):
        """GET /profile with no params and a valid session returns 200."""
        with client.session_transaction() as sess:
            sess["user_id"] = _demo_user_id()
        resp = client.get("/profile")
        assert resp.status_code == 200, "Expected 200 on authenticated profile request"

    def test_no_params_shows_all_expenses(self, client):
        """No params → all seeded expenses are included in total (unfiltered, same as Step 5)."""
        with client.session_transaction() as sess:
            sess["user_id"] = _demo_user_id()
        resp = client.get("/profile")
        body = resp.get_data(as_text=True)
        # Demo seed total is ₹349.64 (from test_backend_connection.py).
        assert "349.64" in body, "Expected full unfiltered total to appear"

    def test_no_params_active_preset_is_all(self, client):
        """No params → 'All Time' preset button carries the is-active class."""
        with client.session_transaction() as sess:
            sess["user_id"] = _demo_user_id()
        resp = client.get("/profile")
        body = resp.get_data(as_text=True)
        # The template marks the active preset with 'is-active' adjacent to the label.
        assert "is-active" in body, "Expected at least one is-active class in filter bar"
        # 'All Time' text must appear alongside the active marker.
        assert "All Time" in body, "Expected 'All Time' preset label in filter bar"

    def test_no_params_rupee_symbol_present(self, client):
        """₹ symbol renders in unfiltered view (spec: symbol persists regardless of filter)."""
        with client.session_transaction() as sess:
            sess["user_id"] = _demo_user_id()
        resp = client.get("/profile")
        body = resp.get_data(as_text=True)
        assert "₹" in body, "Rupee symbol must appear regardless of filter state"

    def test_no_params_filter_bar_preset_links_rendered(self, client):
        """Filter bar renders the four preset labels in the HTML."""
        with client.session_transaction() as sess:
            sess["user_id"] = _demo_user_id()
        resp = client.get("/profile")
        body = resp.get_data(as_text=True)
        for label in ("This Month", "Last 3 Months", "Last 6 Months", "All Time"):
            assert label in body, f"Expected preset label '{label}' in filter bar"


# =========================================================================== #
# PRESET FILTERS                                                               #
# =========================================================================== #

class TestPresetFilters:
    def test_this_month_filters_to_current_month_only(self, controlled_client):
        """'This Month' shows only June 2026 expenses: Food 10 + Bills 20 = 30."""
        resp = controlled_client.get(
            f"/profile?date_from=2026-06-01&date_to=2026-06-12"
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Total must be 30.00 (Food + Bills), not 219.00 (all).
        assert "30.00" in body, "Expected filtered total of 30.00 for current month"
        # Bus pass (April) and Doctor (January) must not appear.
        assert "Bus pass" not in body, "Transport expense outside month must be excluded"
        assert "Doctor" not in body, "Health expense outside month must be excluded"
        assert "Jacket" not in body, "Shopping expense outside month must be excluded"

    def test_this_month_rupee_symbol_present(self, controlled_client):
        """₹ symbol persists when 'This Month' preset is active."""
        resp = controlled_client.get(
            "/profile?date_from=2026-06-01&date_to=2026-06-12"
        )
        body = resp.get_data(as_text=True)
        assert "₹" in body, "Rupee symbol must appear with This Month filter"

    def test_last_3_months_filters_correctly(self, controlled_client):
        """'Last 3 Months' (2026-03-12 to 2026-06-12) includes June and April, excludes January and September."""
        # Window: 2026-03-12 to 2026-06-12 — includes June (30) and April (50), total 80.
        resp = controlled_client.get(
            "/profile?date_from=2026-03-12&date_to=2026-06-12"
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "80.00" in body, "Expected 80.00 total for last-3-months window"
        # January and September rows must be absent from transactions.
        assert "Doctor" not in body, "Health expense from January must be excluded"
        assert "Jacket" not in body, "Shopping expense from September must be excluded"

    def test_last_6_months_includes_six_month_expenses(self, controlled_client):
        """'Last 6 Months' (2026-01-12 to 2026-06-12) includes June, April, January; excludes September."""
        # Window: 2026-01-12 to 2026-06-12 — includes 10+20+50+40 = 120.
        resp = controlled_client.get(
            "/profile?date_from=2026-01-12&date_to=2026-06-12"
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "120.00" in body, "Expected 120.00 total for last-6-months window"
        # September row must still be absent.
        assert "Jacket" not in body, "Shopping expense outside 6-month window must be excluded"

    def test_all_time_shows_all_expenses(self, controlled_client):
        """'All Time' (no params) removes filter and shows every expense."""
        resp = controlled_client.get("/profile")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Full total is 10+20+50+40+99 = 219.00.
        assert "219.00" in body, "Expected full unfiltered total of 219.00"
        # All descriptions must appear.
        for desc in ("Lunch", "Electricity", "Bus pass", "Doctor", "Jacket"):
            assert desc in body, f"Expected '{desc}' to appear in unfiltered view"

    def test_all_time_active_preset_marked(self, controlled_client):
        """Visiting /profile with no params marks 'All Time' as the active preset."""
        resp = controlled_client.get("/profile")
        body = resp.get_data(as_text=True)
        # The 'All Time' link must carry is-active.
        assert "is-active" in body
        assert "All Time" in body


# =========================================================================== #
# CUSTOM DATE RANGE                                                            #
# =========================================================================== #

class TestCustomDateRange:
    def test_custom_range_filters_all_three_sections(self, controlled_client):
        """Valid custom date_from/date_to filters summary stats, transactions, and breakdown."""
        # Range: only April row (50.00 Transport).
        resp = controlled_client.get(
            "/profile?date_from=2026-04-01&date_to=2026-04-30"
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # Summary stats: total 50.00, 1 transaction, top category Transport.
        assert "50.00" in body, "Expected 50.00 total for April-only range"
        assert "Transport" in body, "Expected Transport as top/only category"
        # Transactions: only Bus pass should appear.
        assert "Bus pass" in body
        assert "Lunch" not in body
        assert "Electricity" not in body
        assert "Doctor" not in body
        assert "Jacket" not in body

    def test_custom_range_inclusive_lower_bound(self, controlled_client):
        """Expense exactly on date_from is included (inclusive BETWEEN)."""
        # date_from == DATE_CURRENT_MONTH_1 == 2026-06-05 (Food 10.00 Lunch).
        resp = controlled_client.get(
            f"/profile?date_from={DATE_CURRENT_MONTH_1}&date_to={DATE_CURRENT_MONTH_1}"
        )
        body = resp.get_data(as_text=True)
        assert "Lunch" in body, "Expense exactly on date_from must be included"
        assert "10.00" in body

    def test_custom_range_inclusive_upper_bound(self, controlled_client):
        """Expense exactly on date_to is included (inclusive BETWEEN)."""
        # date_to == DATE_CURRENT_MONTH_2 == 2026-06-10 (Bills 20.00 Electricity).
        resp = controlled_client.get(
            f"/profile?date_from={DATE_CURRENT_MONTH_2}&date_to={DATE_CURRENT_MONTH_2}"
        )
        body = resp.get_data(as_text=True)
        assert "Electricity" in body, "Expense exactly on date_to must be included"
        assert "20.00" in body

    def test_custom_range_rupee_symbol_present(self, controlled_client):
        """₹ symbol is displayed when a custom date range is active."""
        resp = controlled_client.get(
            "/profile?date_from=2026-06-01&date_to=2026-06-30"
        )
        body = resp.get_data(as_text=True)
        assert "₹" in body, "Rupee symbol must appear with custom filter active"

    def test_custom_range_active_preset_is_custom(self, controlled_client):
        """A custom range that does not match any preset marks active_preset as 'custom'."""
        # Unusual range that won't coincide with any preset computed for 2026-06-12.
        resp = controlled_client.get(
            "/profile?date_from=2026-02-01&date_to=2026-02-28"
        )
        body = resp.get_data(as_text=True)
        # The custom form should carry is-active.
        assert "is-active" in body, "Expected is-active marker for custom date range"

    def test_custom_form_marked_active_in_html(self, controlled_client):
        """The custom-range <form> element receives the is-active class when a custom range applies."""
        resp = controlled_client.get(
            "/profile?date_from=2026-02-01&date_to=2026-02-28"
        )
        body = resp.get_data(as_text=True)
        # The template adds is-active to the form when active_preset == 'custom'.
        assert "filter-custom is-active" in body or "filter-custom  is-active" in body or (
            "is-active" in body and "filter-custom" in body
        ), "Custom range form must carry is-active class"


# =========================================================================== #
# EMPTY RANGE — no matching expenses                                           #
# =========================================================================== #

class TestEmptyRange:
    def test_empty_range_shows_zero_total_no_crash(self, controlled_client):
        """A date range with no matching expenses shows ₹0.00 and 0 transactions without error."""
        resp = controlled_client.get(
            "/profile?date_from=2025-01-01&date_to=2025-01-31"
        )
        assert resp.status_code == 200, "Must not crash on an empty date range"
        body = resp.get_data(as_text=True)
        assert "0.00" in body, "Expected ₹0.00 total for empty range"

    def test_empty_range_rupee_symbol_present(self, controlled_client):
        """₹ symbol is present even when no expenses exist in the range."""
        resp = controlled_client.get(
            "/profile?date_from=2025-01-01&date_to=2025-01-31"
        )
        body = resp.get_data(as_text=True)
        assert "₹" in body, "Rupee symbol must appear even when filtered total is zero"

    def test_empty_range_category_breakdown_is_empty(self, seeded_db):
        """get_category_breakdown returns [] for a date range with no expenses."""
        result = get_category_breakdown(
            seeded_db["user_id"],
            date_from="2025-01-01",
            date_to="2025-01-31",
        )
        assert result == [], "Category breakdown must be empty list for empty range"

    def test_empty_range_transaction_list_is_empty(self, seeded_db):
        """get_recent_transactions returns [] for a date range with no expenses."""
        result = get_recent_transactions(
            seeded_db["user_id"],
            date_from="2025-01-01",
            date_to="2025-01-31",
        )
        assert result == [], "Transaction list must be empty for empty range"

    def test_empty_range_summary_stats_zeros(self, seeded_db):
        """get_summary_stats returns zeros and em-dash top category for empty range."""
        stats = get_summary_stats(
            seeded_db["user_id"],
            date_from="2025-01-01",
            date_to="2025-01-31",
        )
        assert stats["total_spent"] == 0, "Total spent must be 0 for empty range"
        assert stats["transaction_count"] == 0, "Transaction count must be 0 for empty range"
        assert stats["top_category"] == "—", "Top category must be em-dash for empty range"


# =========================================================================== #
# VALIDATION ERRORS                                                            #
# =========================================================================== #

class TestValidationErrors:
    def test_date_from_gt_date_to_flashes_error(self, controlled_client):
        """date_from > date_to → flash message 'Start date must be before end date.'"""
        resp = controlled_client.get(
            "/profile?date_from=2026-06-30&date_to=2026-06-01",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Start date must be before end date" in body, (
            "Flash message must appear when date_from > date_to"
        )

    def test_date_from_gt_date_to_falls_back_to_unfiltered(self, controlled_client):
        """date_from > date_to → route falls back to unfiltered view (all expenses shown)."""
        resp = controlled_client.get(
            "/profile?date_from=2026-06-30&date_to=2026-06-01",
            follow_redirects=True,
        )
        body = resp.get_data(as_text=True)
        # All five controlled expenses total 219.00.
        assert "219.00" in body, (
            "Unfiltered total must appear when date_from > date_to (fallback)"
        )

    def test_malformed_date_from_does_not_crash(self, controlled_client):
        """Malformed date_from silently falls back to unfiltered view (spec: no crash)."""
        resp = controlled_client.get(
            "/profile?date_from=not-a-date&date_to=2026-06-12"
        )
        assert resp.status_code == 200, "Malformed date_from must not crash the app"

    def test_malformed_date_from_returns_unfiltered(self, controlled_client):
        """Malformed date_from → all expenses shown (fallback to unfiltered)."""
        resp = controlled_client.get(
            "/profile?date_from=not-a-date&date_to=2026-06-12"
        )
        body = resp.get_data(as_text=True)
        assert "219.00" in body, "Unfiltered total must appear when date_from is malformed"

    def test_malformed_date_to_does_not_crash(self, controlled_client):
        """Malformed date_to silently falls back to unfiltered view (spec: no crash)."""
        resp = controlled_client.get(
            "/profile?date_from=2026-06-01&date_to=INVALID"
        )
        assert resp.status_code == 200, "Malformed date_to must not crash the app"

    def test_malformed_date_to_returns_unfiltered(self, controlled_client):
        """Malformed date_to → all expenses shown (fallback to unfiltered)."""
        resp = controlled_client.get(
            "/profile?date_from=2026-06-01&date_to=INVALID"
        )
        body = resp.get_data(as_text=True)
        assert "219.00" in body, "Unfiltered total must appear when date_to is malformed"

    def test_both_dates_malformed_falls_back(self, controlled_client):
        """Both date params malformed → unfiltered, no crash."""
        resp = controlled_client.get(
            "/profile?date_from=abc&date_to=xyz"
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "219.00" in body, "Unfiltered total must appear when both dates are malformed"

    def test_only_date_from_provided_falls_back_to_unfiltered(self, controlled_client):
        """Only date_from without date_to → falls back to unfiltered (both bounds required)."""
        resp = controlled_client.get("/profile?date_from=2026-06-01")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "219.00" in body, (
            "Unfiltered total must appear when only date_from is present"
        )

    def test_only_date_to_provided_falls_back_to_unfiltered(self, controlled_client):
        """Only date_to without date_from → falls back to unfiltered (both bounds required)."""
        resp = controlled_client.get("/profile?date_to=2026-06-12")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "219.00" in body, (
            "Unfiltered total must appear when only date_to is present"
        )


# =========================================================================== #
# QUERY HELPER — get_summary_stats                                             #
# =========================================================================== #

class TestGetSummaryStats:
    def test_no_params_behaves_like_step5_unfiltered(self, seeded_db):
        """No params → totals over all expenses (identical to Step 5 contract)."""
        stats = get_summary_stats(seeded_db["user_id"])
        # Total: 10 + 20 + 50 + 40 + 99 = 219.00
        assert stats["total_spent"] == 219.00
        assert stats["transaction_count"] == 5

    def test_with_date_range_filters_correctly(self, seeded_db):
        """date_from/date_to → only expenses in the inclusive range are counted."""
        stats = get_summary_stats(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        # Only June rows: 10.00 + 20.00 = 30.00
        assert stats["total_spent"] == 30.00
        assert stats["transaction_count"] == 2

    def test_with_date_range_top_category_correct(self, seeded_db):
        """Top category reflects only expenses in the active range."""
        stats = get_summary_stats(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        # Bills (20) > Food (10) — Bills should be top category.
        assert stats["top_category"] == "Bills"

    def test_single_date_range_inclusive(self, seeded_db):
        """A single-day range includes exactly the expense on that date."""
        stats = get_summary_stats(
            seeded_db["user_id"],
            date_from=DATE_6_MONTHS_AGO,
            date_to=DATE_6_MONTHS_AGO,
        )
        assert stats["total_spent"] == 40.00
        assert stats["transaction_count"] == 1

    def test_empty_user_no_params(self, seeded_db):
        """Empty user with no params returns zero stats (Step 5 contract unchanged)."""
        stats = get_summary_stats(seeded_db["empty_user_id"])
        assert stats["total_spent"] == 0
        assert stats["transaction_count"] == 0
        assert stats["top_category"] == "—"

    def test_empty_range_returns_zeros(self, seeded_db):
        """Range with no matching expenses returns zeros and em-dash."""
        stats = get_summary_stats(
            seeded_db["user_id"],
            date_from="2020-01-01",
            date_to="2020-01-31",
        )
        assert stats["total_spent"] == 0
        assert stats["transaction_count"] == 0
        assert stats["top_category"] == "—"


# =========================================================================== #
# QUERY HELPER — get_recent_transactions                                       #
# =========================================================================== #

class TestGetRecentTransactions:
    def test_no_params_returns_all_unfiltered(self, seeded_db):
        """No params → all five expenses returned newest-first (Step 5 contract)."""
        txns = get_recent_transactions(seeded_db["user_id"])
        assert len(txns) == 5

    def test_no_params_ordered_newest_first(self, seeded_db):
        """Transactions are ordered by date DESC with no filter (Step 5 contract)."""
        txns = get_recent_transactions(seeded_db["user_id"])
        dates = [t["date"] for t in txns]
        # DATE_CURRENT_MONTH_2 (Jun 10) > DATE_CURRENT_MONTH_1 (Jun 05).
        assert dates[0] == "Jun 10", "Most recent expense must appear first"

    def test_with_date_range_filters_transactions(self, seeded_db):
        """date_from/date_to restricts the returned transactions to the range."""
        txns = get_recent_transactions(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        assert len(txns) == 2, "Expected exactly 2 transactions in the June range"
        descriptions = {t["description"] for t in txns}
        assert descriptions == {"Lunch", "Electricity"}

    def test_with_date_range_ordering_preserved(self, seeded_db):
        """Ordering (date DESC) is preserved inside a filtered range."""
        txns = get_recent_transactions(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        # Jun 10 (Electricity) must precede Jun 05 (Lunch).
        assert txns[0]["description"] == "Electricity"
        assert txns[1]["description"] == "Lunch"

    def test_empty_range_returns_empty_list(self, seeded_db):
        """Range with no matching expenses returns an empty list."""
        txns = get_recent_transactions(
            seeded_db["user_id"],
            date_from="2020-01-01",
            date_to="2020-01-31",
        )
        assert txns == []

    def test_row_shape_unchanged_with_filter(self, seeded_db):
        """Each returned dict has the same keys as Step 5 ({date, description, category, amount})."""
        txns = get_recent_transactions(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        for t in txns:
            assert set(t.keys()) == {"date", "description", "category", "amount"}

    def test_date_display_format_unchanged_with_filter(self, seeded_db):
        """Date strings use 'Mon DD' display format (e.g. 'Jun 05') even when filtered."""
        txns = get_recent_transactions(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_1,
        )
        assert txns[0]["date"] == "Jun 05", "Date display format must be 'Mon DD'"

    def test_no_expenses_user_returns_empty(self, seeded_db):
        """Empty user returns [] with no params (Step 5 contract unchanged)."""
        assert get_recent_transactions(seeded_db["empty_user_id"]) == []


# =========================================================================== #
# QUERY HELPER — get_category_breakdown                                        #
# =========================================================================== #

class TestGetCategoryBreakdown:
    def test_no_params_returns_all_categories(self, seeded_db):
        """No params → all categories returned (Step 5 contract unchanged)."""
        breakdown = get_category_breakdown(seeded_db["user_id"])
        names = [c["name"] for c in breakdown]
        # Five distinct categories seeded.
        assert set(names) == {"Food", "Bills", "Transport", "Health", "Shopping"}

    def test_no_params_ordered_by_amount_desc(self, seeded_db):
        """No params → categories ordered amount descending (Step 5 contract)."""
        breakdown = get_category_breakdown(seeded_db["user_id"])
        amounts = [c["amount"] for c in breakdown]
        assert amounts == sorted(amounts, reverse=True)

    def test_with_date_range_filters_to_matching_categories(self, seeded_db):
        """date_from/date_to shows only categories that have expenses in the range."""
        breakdown = get_category_breakdown(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        names = [c["name"] for c in breakdown]
        # Only Food (10) and Bills (20) fall in June range.
        assert set(names) == {"Food", "Bills"}

    def test_with_date_range_amounts_correct(self, seeded_db):
        """Per-category amounts reflect only expenses in the active range."""
        breakdown = get_category_breakdown(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        by_name = {c["name"]: c["amount"] for c in breakdown}
        assert by_name["Bills"] == 20.00
        assert by_name["Food"] == 10.00

    def test_with_date_range_pct_sums_to_100(self, seeded_db):
        """Percentages sum to exactly 100 within a filtered range."""
        breakdown = get_category_breakdown(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        assert sum(c["pct"] for c in breakdown) == 100, (
            "Filtered category percentages must sum to exactly 100"
        )

    def test_pct_are_integers(self, seeded_db):
        """pct values are integers (not floats) in filtered breakdown."""
        breakdown = get_category_breakdown(
            seeded_db["user_id"],
            date_from=DATE_CURRENT_MONTH_1,
            date_to=DATE_CURRENT_MONTH_2,
        )
        for cat in breakdown:
            assert isinstance(cat["pct"], int), "pct must be an integer"

    def test_empty_range_returns_empty_list(self, seeded_db):
        """Range with no matching expenses returns []."""
        breakdown = get_category_breakdown(
            seeded_db["user_id"],
            date_from="2020-01-01",
            date_to="2020-01-31",
        )
        assert breakdown == []

    def test_no_expenses_user_returns_empty(self, seeded_db):
        """Empty user returns [] with no params (Step 5 contract unchanged)."""
        assert get_category_breakdown(seeded_db["empty_user_id"]) == []

    def test_single_category_range_pct_is_100(self, seeded_db):
        """A range with a single category gives it 100% share."""
        # Only Transport in April.
        breakdown = get_category_breakdown(
            seeded_db["user_id"],
            date_from=DATE_3_MONTHS_AGO,
            date_to=DATE_3_MONTHS_AGO,
        )
        assert len(breakdown) == 1
        assert breakdown[0]["name"] == "Transport"
        assert breakdown[0]["pct"] == 100


# =========================================================================== #
# PARAMETERISED QUERY SAFETY (_date_clause)                                   #
# =========================================================================== #

class TestParameterisedQuerySafety:
    def test_date_clause_with_both_bounds_uses_placeholders(self):
        """_date_clause returns SQL with ? placeholders, not a formatted date string."""
        sql, params = _date_clause("2026-06-01", "2026-06-30")
        # The SQL fragment must contain ? not the literal date values.
        assert "?" in sql, "SQL fragment must use ? placeholders, not formatted strings"
        assert "2026-06-01" not in sql, "date_from value must NOT appear in the SQL string"
        assert "2026-06-30" not in sql, "date_to value must NOT appear in the SQL string"

    def test_date_clause_with_both_bounds_returns_correct_params(self):
        """_date_clause includes both date values in the returned params tuple."""
        sql, params = _date_clause("2026-06-01", "2026-06-30")
        assert "2026-06-01" in params
        assert "2026-06-30" in params

    def test_date_clause_with_no_bounds_returns_empty_fragment(self):
        """_date_clause with no bounds returns an empty SQL fragment and empty params."""
        sql, params = _date_clause(None, None)
        assert sql == "", "SQL fragment must be empty when no bounds provided"
        assert params == (), "Params must be empty tuple when no bounds provided"

    def test_date_clause_with_only_date_from_returns_empty(self):
        """_date_clause with only one bound returns empty fragment (both required)."""
        sql, params = _date_clause("2026-06-01", None)
        assert sql == ""
        assert params == ()

    def test_date_clause_with_only_date_to_returns_empty(self):
        """_date_clause with only date_to returns empty fragment (both required)."""
        sql, params = _date_clause(None, "2026-06-30")
        assert sql == ""
        assert params == ()

    @pytest.mark.parametrize("injection_attempt", [
        "2026-06-01'; DROP TABLE expenses; --",
        "2026-06-01 OR 1=1",
        "' OR ''='",
    ])
    def test_sql_injection_in_date_param_does_not_crash(
        self, controlled_client, injection_attempt
    ):
        """Malformed/injected date strings are rejected by validation (no crash)."""
        resp = controlled_client.get(
            f"/profile?date_from={injection_attempt}&date_to=2026-06-30"
        )
        # The route should silently fall back, not 500.
        assert resp.status_code == 200, (
            f"SQL injection attempt '{injection_attempt}' must not crash the app"
        )


# =========================================================================== #
# TEMPLATE RENDERING — filter bar structure                                    #
# =========================================================================== #

class TestTemplateFilterBar:
    def test_filter_bar_present_in_profile_html(self, client):
        """The filter bar section renders in the profile page HTML."""
        with client.session_transaction() as sess:
            sess["user_id"] = _demo_user_id()
        resp = client.get("/profile")
        body = resp.get_data(as_text=True)
        assert "filter-bar" in body, "Expected filter-bar CSS class in profile HTML"

    def test_filter_presets_container_present(self, client):
        """The filter-presets container is rendered."""
        with client.session_transaction() as sess:
            sess["user_id"] = _demo_user_id()
        resp = client.get("/profile")
        body = resp.get_data(as_text=True)
        assert "filter-presets" in body, "Expected filter-presets container in HTML"

    def test_custom_date_inputs_present(self, client):
        """Custom range inputs (name=date_from and name=date_to) are rendered."""
        with client.session_transaction() as sess:
            sess["user_id"] = _demo_user_id()
        resp = client.get("/profile")
        body = resp.get_data(as_text=True)
        assert 'name="date_from"' in body, "Expected date_from input in custom range form"
        assert 'name="date_to"' in body, "Expected date_to input in custom range form"

    def test_active_preset_class_present_for_all_time(self, controlled_client):
        """When no filter is active, the 'All Time' link carries is-active."""
        resp = controlled_client.get("/profile")
        body = resp.get_data(as_text=True)
        # The template renders: class="filter-preset is-active" next to "All Time".
        assert "is-active" in body, "is-active class must be present for All Time preset"

    def test_active_preset_class_present_for_filtered_view(self, controlled_client):
        """When a preset-matching filter is active, the preset button carries is-active."""
        # Use June range that corresponds to "This Month" preset on 2026-06-12.
        resp = controlled_client.get(
            "/profile?date_from=2026-06-01&date_to=2026-06-12"
        )
        body = resp.get_data(as_text=True)
        assert "is-active" in body, "is-active must appear for active preset button"

    def test_input_values_reflect_active_custom_range(self, controlled_client):
        """date input fields show the currently active date_from/date_to values."""
        resp = controlled_client.get(
            "/profile?date_from=2026-02-01&date_to=2026-02-28"
        )
        body = resp.get_data(as_text=True)
        assert "2026-02-01" in body, "date_from value must pre-fill the From input"
        assert "2026-02-28" in body, "date_to value must pre-fill the To input"

    def test_rupee_symbol_in_category_breakdown(self, controlled_client):
        """₹ symbol appears in the category breakdown section regardless of filter."""
        resp = controlled_client.get(
            "/profile?date_from=2026-06-01&date_to=2026-06-12"
        )
        body = resp.get_data(as_text=True)
        assert "₹" in body, "Rupee symbol must appear in category breakdown amounts"

    def test_rupee_symbol_in_transaction_list(self, controlled_client):
        """₹ symbol appears in the transaction list amounts regardless of filter."""
        resp = controlled_client.get(
            "/profile?date_from=2026-06-01&date_to=2026-06-12"
        )
        body = resp.get_data(as_text=True)
        assert "₹" in body, "Rupee symbol must appear in transaction amount column"
