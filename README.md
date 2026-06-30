# Spendly

A personal expense tracker built with Flask, Jinja2 templates, vanilla JS, and
SQLite. Register an account, log expenses by category, filter your history by
date range, and edit or delete entries.

## Tech stack

- **Backend:** Flask 3, raw `sqlite3` (no ORM), parameterised queries
- **Frontend:** Jinja2 templates + vanilla JS (no build step)
- **Auth:** server-side sessions, passwords hashed with Werkzeug
- **Tests:** pytest + pytest-flask

## Local development

```powershell
# Windows venv lives at .venv
pip install -r requirements.txt

# Run the dev server (note the non-default port)
python app.py            # http://127.0.0.1:5001  (debug=True)

# Tests
pytest                   # run all
pytest tests/test_09-delete-expense.py -v   # a single file
```

Demo account (seeded on first run): `demo@spendly.com` / `demo123`.

## Deploying to Railway

The app uses a file-based SQLite database, so it needs a **persistent volume** —
deploy as a long-running service (not a stateless/serverless platform).

Production process model: `gunicorn` serves the WSGI app (`app:app`) per the
[`Procfile`](Procfile). Because gunicorn imports the app object directly, Flask's
`debug` dev-server block never runs in production.

### Steps

1. **Create the project:** Railway → *New Project* → *Deploy from GitHub repo* →
   select this repo and the `feature` branch. Nixpacks auto-detects Python (via
   [`.python-version`](.python-version) and `requirements.txt`) and uses the
   `Procfile`.
2. **Add a persistent volume** (this is what keeps your data across restarts):
   Service → *Settings → Volumes → New Volume*, mount path `/data`.
3. **Set environment variables** (Service → *Variables*):
   - `DATABASE_PATH=/data/expense_tracker.db` — points SQLite at the volume
   - `SECRET_KEY=<a long random string>` — secures session cookies / logins
   - Do **not** set `PORT`; Railway injects it and the `Procfile` binds to it.
4. **Generate a domain:** Service → *Settings → Networking → Generate Domain*.
5. Visit the domain and log in with the demo account above.

### Notes

- **One gunicorn worker** is configured to avoid SQLite write-lock contention.
  This is fine for a personal app; scaling to multiple workers/instances requires
  migrating to a client/server database (e.g. Postgres).
- **Seeding** runs only when the users table is empty, so the demo data is
  inserted once on the fresh volume and never overwrites real sign-ups.

## Configuration reference

| Variable        | Default                          | Purpose                               |
|-----------------|----------------------------------|---------------------------------------|
| `DATABASE_PATH` | `<repo>/expense_tracker.db`      | SQLite file location (set to a volume path in prod) |
| `SECRET_KEY`    | `dev-secret-change-me`           | Flask session signing key (set in prod) |
| `PORT`          | `5001` (local `app.py` only)     | Bind port; injected by Railway in prod |
