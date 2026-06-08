import os
import sqlite3

from flask import Flask, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# Ensure the database exists and is seeded before handling requests.
with app.app_context():
    init_db()
    seed_db()


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
    # Step 4 builds the profile UI with static, hardcoded data. The real DB
    # queries land in Step 5 — for now everything below is placeholder content.
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user = {
        "name": session.get("user_name", "Demo User"),
        "email": "demo@spendly.com",
        "initials": "DU",
        "member_since": "January 2026",
    }

    stats = {
        "total_spent": 349.64,
        "transaction_count": 8,
        "top_category": "Bills",
    }

    transactions = [
        {"date": "Jun 15", "description": "Coffee and snacks", "category": "Food", "amount": 8.40},
        {"date": "Jun 13", "description": "Gift", "category": "Other", "amount": 25.00},
        {"date": "Jun 11", "description": "New shoes", "category": "Shopping", "amount": 89.99},
        {"date": "Jun 09", "description": "Movie ticket", "category": "Entertainment", "amount": 18.75},
        {"date": "Jun 07", "description": "Pharmacy", "category": "Health", "amount": 30.00},
        {"date": "Jun 05", "description": "Electricity bill", "category": "Bills", "amount": 120.00},
        {"date": "Jun 03", "description": "Monthly metro pass", "category": "Transport", "amount": 45.00},
        {"date": "Jun 02", "description": "Lunch at cafe", "category": "Food", "amount": 12.50},
    ]

    categories = [
        {"name": "Bills", "amount": 120.00, "pct": 34},
        {"name": "Shopping", "amount": 89.99, "pct": 26},
        {"name": "Transport", "amount": 45.00, "pct": 13},
        {"name": "Health", "amount": 30.00, "pct": 9},
        {"name": "Other", "amount": 25.00, "pct": 7},
        {"name": "Food", "amount": 20.90, "pct": 6},
        {"name": "Entertainment", "amount": 18.75, "pct": 5},
    ]

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
