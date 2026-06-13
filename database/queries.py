# Step 5 — Profile data access
#
# Pure query helpers for the profile page. No Flask imports: each function opens
# its own connection via get_db(), reads only the given user's rows with a
# parameterised WHERE user_id = ?, and closes the connection before returning.

from datetime import datetime

from database.db import get_db


def get_user_by_id(user_id):
    """Return {name, email, member_since} for the user, or None if not found."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    # created_at comes from db.py's `datetime('now')` DEFAULT, i.e. the
    # "%Y-%m-%d %H:%M:%S" format. Keep this format string matched to db.py.
    member_since = datetime.strptime(
        row["created_at"], "%Y-%m-%d %H:%M:%S"
    ).strftime("%B %Y")

    return {
        "name": row["name"],
        "email": row["email"],
        "member_since": member_since,
    }


def insert_expense(user_id, amount, category, expense_date, description):
    """Insert one expense for the given user and return the new row id.

    The connection is opened via get_db() (foreign keys on) and closed before
    returning. All values are bound as parameters; `description` may be None,
    which is stored as SQL NULL. `created_at` is left to the table DEFAULT.
    (`expense_date` avoids shadowing the `datetime.date` import at module top.)
    """
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, expense_date, description),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def _date_clause(date_from, date_to):
    """Return (sql_fragment, params) for an optional inclusive date range.

    When both bounds are given, restricts to `date BETWEEN ? AND ?` via bound
    parameters; otherwise returns an empty fragment so the query is unfiltered
    and behaves exactly as it did before date filtering existed.
    """
    if date_from and date_to:
        return " AND date BETWEEN ? AND ?", (date_from, date_to)
    return "", ()


def get_summary_stats(user_id, date_from=None, date_to=None):
    """Return {total_spent, transaction_count, top_category} for the user.

    A user with no expenses (in the active range) returns zeros and an em-dash
    top category. When both date bounds are given, only expenses with
    `date BETWEEN date_from AND date_to` (inclusive) are counted.
    """
    clause, date_params = _date_clause(date_from, date_to)
    conn = get_db()
    try:
        totals = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt "
            "FROM expenses WHERE user_id = ?" + clause,
            (user_id, *date_params),
        ).fetchone()
        top = conn.execute(
            "SELECT category FROM expenses WHERE user_id = ?" + clause + " "
            "GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            (user_id, *date_params),
        ).fetchone()
    finally:
        conn.close()

    if top is None:
        return {"total_spent": 0, "transaction_count": 0, "top_category": "—"}

    return {
        "total_spent": round(totals["total"], 2),
        "transaction_count": totals["cnt"],
        "top_category": top["category"],
    }


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    """Return the user's expenses newest-first as a list of dicts.

    Each item: {date (display "Jun 15"), description, category, amount}.
    When both date bounds are given, the list is restricted to that inclusive
    range; ordering and limit are unchanged.
    """
    clause, date_params = _date_clause(date_from, date_to)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT date, description, category, amount FROM expenses "
            "WHERE user_id = ?" + clause + " ORDER BY date DESC, id DESC LIMIT ?",
            (user_id, *date_params, limit),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            # Stored "YYYY-MM-DD" -> display "Jun 15" (matches the static design).
            "date": datetime.strptime(row["date"], "%Y-%m-%d").strftime("%b %d"),
            "description": row["description"],
            "category": row["category"],
            "amount": row["amount"],
        }
        for row in rows
    ]


def get_category_breakdown(user_id, date_from=None, date_to=None):
    """Return per-category totals high-to-low as {name, amount, pct} dicts.

    pct values are integers that sum to exactly 100; the largest category
    (index 0, since rows are ordered amount-desc) absorbs any rounding remainder.
    An empty user (or empty range) returns []. When both date bounds are given,
    only expenses in that inclusive range are aggregated.
    """
    clause, date_params = _date_clause(date_from, date_to)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category AS name, SUM(amount) AS amount FROM expenses "
            "WHERE user_id = ?" + clause + " GROUP BY category ORDER BY amount DESC",
            (user_id, *date_params),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    total = sum(row["amount"] for row in rows)
    result = [
        {"name": row["name"], "amount": round(row["amount"], 2), "pct": 0}
        for row in rows
    ]

    if total > 0:
        for item, row in zip(result, rows):
            item["pct"] = round(row["amount"] / total * 100)
        # Force the integer percentages to sum to exactly 100; the diff may be
        # positive or negative and is absorbed by the largest category.
        result[0]["pct"] += 100 - sum(item["pct"] for item in result)

    return result
