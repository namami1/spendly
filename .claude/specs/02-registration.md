# Spec: Registration

## Overview
Registration lets a new visitor create a Spendly account by submitting their
full name, email, and password. At this point in the roadmap the data layer
(Step 1) and the register page UI already exist, but the `/register` route only
renders the form — it cannot create a user. This step wires the form up: it
makes `/register` accept a POST, validates the input, hashes the password with
werkzeug, inserts a new row into the `users` table,on success the user is shown with a success message
and redirects to the login page on success. It is the foundation for authentication (login/logout in later
steps), since no one can log in until accounts can be created.

## Depends on
- **Step 1 — Database Setup** (`database/db.py` with `get_db()`, `init_db()`,
  `seed_db()` and the `users` table). Already complete.

## Routes
- `GET /register` — render the registration form — public *(already exists)*
- `POST /register` — validate input, create the user, redirect to login —
  public *(new behavior added to the existing `register` view)*

No new URL paths are introduced; the existing `register` view is extended to
handle both `GET` and `POST` via `methods=["GET", "POST"]`.

## Database changes
No database changes. The `users` table from Step 1 already has every column
required (`name`, `email` (UNIQUE NOT NULL), `password_hash`, `created_at`).

## Templates
- **Create:** None.
- **Modify:** None required. `templates/register.html` already posts to
  `/register`, renders an `{{ error }}` block, and exposes `name`, `email`, and
  `password` fields. Only touch it if a validation message needs new markup
  (e.g. a success flash) — prefer reusing the existing `auth-error` block.

## Files to change
- `app.py` — change the `register` view to accept `GET` and `POST`, read the
  form fields, validate, hash the password, insert the user via `get_db()`, and
  `redirect` to the login page on success (re-render with `error` on failure).

## Files to create
- None.

## New dependencies
No new dependencies. `werkzeug.security.generate_password_hash` and Flask's
`request`, `redirect`, `url_for` are already available.

## Rules for implementation
- No SQLAlchemy or ORMs — use `sqlite3` via `get_db()` only.
- Parameterised queries only — never string-format or f-string values into SQL.
- Passwords hashed with `werkzeug` (`generate_password_hash`); never store the
  raw password.
- Use CSS variables — never hardcode hex values (no styling changes expected,
  but applies if any markup is touched).
- All templates extend `base.html`.
- Validate on the server: all three fields required (non-empty after strip),
  email must be unique, password minimum 8 characters. Re-render
  `register.html` with a clear `error` message on any failure — do not crash.
- Handle the duplicate-email case explicitly (check first, or catch the
  `sqlite3.IntegrityError` from the UNIQUE constraint) and show a friendly
  "email already registered" message rather than a 500.
- Always close the DB connection.
- On success, redirect (PRG pattern) to the login page — do not re-render the
  form on a successful POST.

## Definition of done
- [ ] Submitting the register form with a new, valid name/email/password
      creates exactly one row in `users` and redirects to the login page.
- [ ] The stored `password_hash` is a werkzeug hash, not the plaintext password.
- [ ] Submitting an email that already exists re-renders the form with a visible
      error and does **not** create a duplicate row or return a 500.
- [ ] Submitting with any field blank re-renders the form with an error.
- [ ] Submitting a password shorter than 8 characters re-renders the form with
      an error and creates no user.
- [ ] `GET /register` still renders the form unchanged.
- [ ] The app starts and handles both `GET` and `POST /register` without errors.
