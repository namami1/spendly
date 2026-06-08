# Spec: Login and Logout

## Overview
Login and logout give a registered user a real session: they can sign in with
their email and password, stay recognised across requests, and sign out again.
At this point in the roadmap accounts can be created (Step 2) but the `/login`
route only renders the form and `/logout` is a placeholder string — there is no
notion of "who is logged in". This step introduces Flask server-side sessions:
verifying credentials against the `users` table with werkzeug, storing the
user's id (and name) in `session` on success, and clearing it on logout. It is
the gate every logged-in feature later in the roadmap (profile, expenses) will
depend on.

## Depends on
- **Step 1 — Database Setup** (`users` table, `get_db()`). Complete.
- **Step 2 — Registration** (accounts exist with werkzeug `password_hash`).
  Complete. You cannot log in until you can register.

## Routes
- `GET /login` — render the login form — public *(already exists)*
- `POST /login` — verify email + password, start a session, redirect — public
  *(new behaviour added to the existing `login` view via `methods=["GET","POST"]`)*
- `GET /logout` — clear the session and redirect to the landing page — logged-in
  *(replaces the placeholder string in the existing `logout` view)*

No new URL paths are introduced; the existing `login` and `logout` views are
implemented.

## Database changes
No database changes. The `users` table from Step 1 already stores `id`, `name`,
`email`, and `password_hash` — everything credential verification needs.

## Templates
- **Create:** None.
- **Modify:**
  - `templates/login.html` — None required. It already posts to `/login`,
    renders an `{{ error }}` block, and exposes `email` and `password` fields.
    Only touch it if a new validation message needs markup — prefer reusing the
    existing `auth-error` block.
  - `templates/base.html` — make the navbar session-aware: when a user is logged
    in (e.g. `session.user_id` is set) show a **Log out** link (to
    `url_for('logout')`) and hide "Sign in" / "Get started"; otherwise show the
    current links. This is what makes logout reachable and login observable.

## Files to change
- `app.py`
  - Set `app.secret_key` (read from an environment variable with a dev
    fallback) so `session` works.
  - Import `session` from Flask and `check_password_hash` from
    `werkzeug.security`.
  - Extend the `login` view to accept `GET` and `POST`: read + strip the form
    fields, look up the user by email with a parameterised query, verify the
    password with `check_password_hash`, store `user_id` (and `name`) in
    `session` on success and redirect, or re-render `login.html` with a single
    generic `error` on failure.
  - Replace the `logout` placeholder: clear the session (`session.clear()`) and
    redirect to the landing page.
- `templates/base.html` — conditional navbar (see Templates).

## Files to create
- None.

## New dependencies
No new dependencies. Flask `session` is built in; `check_password_hash` ships
with werkzeug, already installed.

## Rules for implementation
- No SQLAlchemy or ORMs — use `sqlite3` via `get_db()` only.
- Parameterised queries only — never string-format or f-string values into SQL.
- Passwords hashed with werkzeug — verify with `check_password_hash`; never
  compare raw passwords and never log them.
- Use CSS variables — never hardcode hex values (applies to any navbar markup
  touched).
- All templates extend `base.html`.
- `app.secret_key` must be set before any `session` use. Read it from an env var
  (e.g. `SECRET_KEY`) with a development fallback so the app still runs locally.
- Use a **single, generic** failure message ("Invalid email or password.") for
  both unknown email and wrong password — do not reveal which was wrong.
- Validate on the server: both fields required (non-empty after strip);
  re-render `login.html` with an `error` on any failure — do not crash.
- Always close the DB connection (use `try/finally`).
- On successful login, redirect (PRG) — do not re-render the form.
- `GET /logout` must work whether or not a session exists (no crash if already
  logged out).

## Definition of done
- [ ] Submitting `/login` with a registered email and correct password starts a
      session and redirects (no error shown).
- [ ] Submitting a correct email with a wrong password re-renders the form with
      "Invalid email or password." and starts **no** session.
- [ ] Submitting an email that does not exist shows the same generic error and
      starts no session.
- [ ] Submitting with either field blank re-renders the form with an error.
- [ ] While logged in, the navbar shows a **Log out** link and hides
      "Sign in" / "Get started".
- [ ] Visiting `/logout` clears the session and redirects to the landing page;
      the navbar reverts to "Sign in" / "Get started".
- [ ] `GET /login` still renders the form unchanged.
- [ ] The app starts and handles `GET`/`POST /login` and `/logout` without
      errors, with `app.secret_key` set.
