# Step 1 — Database Setup
# Exposes:
#   get_db()   — returns a SQLite connection with row_factory and foreign keys enabled
#   init_db()  — creates all tables using CREATE TABLE IF NOT EXISTS
#   seed_db()  — inserts sample data for development

import os
import sqlite3
from datetime import date

from werkzeug.security import generate_password_hash

# Path to the SQLite file in the project root (one level up from this file).
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "expense_tracker.db")


def get_db():
    """Return a SQLite connection with dict-like rows and foreign keys enforced."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the users and expenses tables if they don't already exist."""
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL NOT NULL,
            category    TEXT NOT NULL,
            date        TEXT NOT NULL,
            description TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    conn.close()


def seed_db():
    """Insert a demo user and sample expenses once. No-op if data already exists."""
    conn = get_db()

    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        conn.close()
        return

    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@spendly.com", generate_password_hash("demo123")),
    )
    user_id = cursor.lastrowid

    today = date.today()

    def d(day):
        """Return a YYYY-MM-DD string for the given day in the current month."""
        return today.replace(day=day).isoformat()

    # (amount, category, date, description) — covers every fixed category (spec §10).
    sample_expenses = [
        (12.50, "Food", d(2), "Lunch at cafe"),
        (45.00, "Transport", d(3), "Monthly metro pass"),
        (120.00, "Bills", d(5), "Electricity bill"),
        (30.00, "Health", d(7), "Pharmacy"),
        (18.75, "Entertainment", d(9), "Movie ticket"),
        (89.99, "Shopping", d(11), "New shoes"),
        (25.00, "Other", d(13), "Gift"),
        (8.40, "Food", d(15), "Coffee and snacks"),
    ]

    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        [(user_id, *row) for row in sample_expenses],
    )

    conn.commit()
    conn.close()
