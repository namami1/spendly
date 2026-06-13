import calendar
import math
import os
import sqlite3
from datetime import date, datetime

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db
from database.queries import (
    get_category_breakdown,
    get_recent_transactions,
    get_summary_stats,
    get_user_by_id,
    insert_expense,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# User-facing message when a custom date range is reversed (date_from > date_to).
DATE_RANGE_ERROR = "Start date must be before end date."

# The fixed set of expense categories (single source of truth: the add-expense
# template iterates this list and the POST handler validates against it).
EXPENSE_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]

# Upper bound on a single expense amount (₹1 crore) — guards against absurd but
# technically-finite floats like 1e308. Description length mirrors the template's
# maxlength so a crafted POST can't bypass the browser-side limit.
MAX_EXPENSE_AMOUNT = 10_000_000
MAX_DESCRIPTION_LENGTH = 200

# Ensure the database exists and is seeded before handling requests.
with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Date-filter helpers (profile page, Step 6)                          #
# ------------------------------------------------------------------ #

def _parse_iso(value):
    """Return `value` if it is a well-formed YYYY-MM-DD date, else None."""
    if not value or len(value) != 10:  # "YYYY-MM-DD" is exactly 10 chars
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def _months_ago(today, months):
    """Return the date `months` calendar months before `today`.

    The day is clamped to the last valid day of the target month (e.g. three
    months before 31 May is 28/29 Feb), avoiding any dateutil dependency.
    """
    month_index = today.year * 12 + (today.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(today.day, last_day))


def _preset(key, label, date_from, date_to):
    """Build one preset dict, including a ready-made href.

    Bounds are carried so the route can match the active preset; the href is
    built here (with url_for) so the template stays a single anchor and never
    needs to know the "no bounds means clean /profile URL" contract.
    """
    if date_from and date_to:
        href = url_for("profile", date_from=date_from, date_to=date_to)
    else:
        href = url_for("profile")
    return {
        "key": key,
        "label": label,
        "date_from": date_from,
        "date_to": date_to,
        "href": href,
    }


def _build_presets(today):
    """Quick-select ranges, computed here (never in the template).

    "All Time" carries no bounds so its link is a clean /profile URL.
    """
    iso = "%Y-%m-%d"
    today_iso = today.strftime(iso)
    return [
        _preset("this_month", "This Month", today.replace(day=1).strftime(iso), today_iso),
        _preset("last_3", "Last 3 Months", _months_ago(today, 3).strftime(iso), today_iso),
        _preset("last_6", "Last 6 Months", _months_ago(today, 6).strftime(iso), today_iso),
        _preset("all", "All Time", None, None),
    ]


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not name or not email or not password:
            return render_template("register.html", error="All fields are required.")

        if len(password) < 8:
            return render_template(
                "register.html", error="Password must be at least 8 characters."
            )

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return render_template(
                "register.html", error="That email is already registered."
            )
        finally:
            conn.close()

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            return render_template("login.html", error="All fields are required.")

        conn = get_db()
        try:
            user = conn.execute(
                "SELECT id, name, password_hash FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        finally:
            conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid email or password.")

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        return redirect(url_for("profile"))

    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    if user is None:
        # Stale session — the user row no longer exists. Sign out and bounce.
        session.clear()
        return redirect(url_for("login"))

    parts = user["name"].split()
    user = {**user, "initials": "".join(word[0] for word in parts[:2]).upper()}

    # Optional date-range filter from the query string. Malformed values are
    # treated as absent so the page never errors out (falls back to All Time).
    date_from = _parse_iso(request.args.get("date_from"))
    date_to = _parse_iso(request.args.get("date_to"))
    if date_from and date_to and date_from > date_to:
        flash(DATE_RANGE_ERROR)
        date_from = date_to = None

    presets = _build_presets(date.today())
    if date_from and date_to:
        active_preset = next(
            (p["key"] for p in presets
             if p["date_from"] == date_from and p["date_to"] == date_to),
            "custom",
        )
    else:
        active_preset = "all"

    return render_template(
        "profile.html",
        user=user,
        stats=get_summary_stats(user_id, date_from=date_from, date_to=date_to),
        transactions=get_recent_transactions(user_id, date_from=date_from, date_to=date_to),
        categories=get_category_breakdown(user_id, date_from=date_from, date_to=date_to),
        presets=presets,
        active_preset=active_preset,
        date_from=date_from,
        date_to=date_to,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    today = date.today().isoformat()

    if request.method == "POST":
        amount_raw = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        date_value = request.form.get("date", "").strip()
        description = request.form.get("description", "").strip()

        # Preserved verbatim so a failed submission re-fills the form.
        values = {
            "amount": amount_raw,
            "category": category,
            "date": date_value,
            "description": description,
        }

        def reject(message):
            return render_template(
                "add_expense.html",
                categories=EXPENSE_CATEGORIES,
                values=values,
                today=today,
                error=message,
            )

        try:
            amount = float(amount_raw)
        except ValueError:
            return reject("Amount must be a number.")
        if not math.isfinite(amount):  # rejects inf, -inf, nan (e.g. "1e999")
            return reject("Amount must be a number.")
        if amount <= 0:
            return reject("Amount must be greater than zero.")
        if amount > MAX_EXPENSE_AMOUNT:
            return reject("Amount is too large.")
        if category not in EXPENSE_CATEGORIES:
            return reject("Please choose a valid category.")
        if _parse_iso(date_value) is None:
            return reject("Please enter a valid date.")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            return reject("Description must be 200 characters or fewer.")

        insert_expense(
            session["user_id"], amount, category, date_value, description or None
        )
        return redirect(url_for("profile"))

    return render_template(
        "add_expense.html",
        categories=EXPENSE_CATEGORIES,
        values={},
        today=today,
    )


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
