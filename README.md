# SmartStore AI

SmartStore AI is a local-first store builder with a FastAPI/SQLite backend and a
Next.js owner dashboard and storefront. The repository contains application
source, tests, lockfiles, bundled UI assets, and additive database migrations.

## Prerequisites

- Windows 10/11 with PowerShell.
- Git.
- Python 3.11 or newer.
- Node.js 20.9 or newer and npm. `frontend/package-lock.json` pins frontend
  dependencies.

## Clone and configure

```powershell
git clone https://github.com/psj032005-algo/hackathon-project.git
Set-Location hackathon-project
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env.local
```

Create the backend virtual environment and install the pinned dependencies:

```powershell
Set-Location backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

`JWT_SECRET` is required for owner registration and sign-in. Generate a new
private value in `backend/.env` without printing it to the terminal:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import secrets; p=Path('.env'); lines=p.read_text(encoding='utf-8').splitlines(); lines=[('JWT_SECRET=' + secrets.token_urlsafe(48) if line.startswith('JWT_SECRET=') else line) for line in lines]; p.write_text('\n'.join(lines) + '\n', encoding='utf-8')"
```

Keep `.env` files private. The backend reads `backend/.env`; process environment
variables override its values. Gemini, alternate AI, and SMTP settings are
optional. Those features need credentials from their respective providers.

Install the frontend dependencies from the lockfile:

```powershell
Set-Location ..\frontend
npm.cmd ci
```

`frontend/.env.local` configures the browser to call the backend on port 8005
and selects the seeded demo store. Change the API base URL if you use another
host or port. The backend currently allows the local frontend origin
`http://localhost:3000`.

## Initialize and run

Database initialization runs automatically when the backend starts. It creates
the SQLite schema, applies additive migrations, and inserts the demo store and
starter catalog if they are missing. To run initialization explicitly, after
installing dependencies and while in `backend`:

```powershell
.\.venv\Scripts\python.exe -c "import main; main.initialize_database()"
```

Start the backend from `backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8005
```

In a second PowerShell window, start the frontend from `frontend`:

```powershell
npm.cmd run dev
```

Open <http://localhost:3000>. FastAPI documentation is at
<http://127.0.0.1:8005/docs>. The API root `/` is not a health page and may
return `{"detail":"Not Found"}`; use `/docs` or an API route to verify it.

## Tests and checks

Backend tests use temporary SQLite databases and do not need the local runtime
database or external AI/mail accounts:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

Frontend checks, from `frontend`:

```powershell
npm.cmd run lint
npm.cmd run build
npx.cmd tsc --noEmit
```

Run the build before the standalone TypeScript command on a fresh clone; Next.js
generates the route/layout type declarations consumed by `tsc` during the build.

## Database and recovery

The default runtime database is `backend/storefront.db`. It is generated locally,
ignored by Git, and absent from a fresh clone. Startup migrations in
`backend/database.py` currently run through schema version 7 and are additive.
Startup also seeds the demo store and sample catalog. A clean clone restores the
code and an empty local database, not accounts, store changes, products, orders,
or customer/order data from another computer.

The current local SQLite database contains user-created accounts, stores,
products, orders, and order events. It is intentionally excluded from Git
because it contains private runtime data. Back it up separately before deleting
or replacing a working folder. Keep backups private and do not upload them to
the public repository.

To make a consistent SQLite backup while the backend may be running, use
Python's SQLite backup API. Run from `backend`; it creates a new timestamped
backup in your user profile and refuses to overwrite an existing backup:

```powershell
@'
import config
import sqlite3
from datetime import datetime
from pathlib import Path
from database import get_database_path

source_path = get_database_path()
backup_dir = Path.home() / "SmartStoreBackups"
backup_dir.mkdir(parents=True, exist_ok=True)
backup_path = backup_dir / f"storefront-{datetime.now():%Y%m%d-%H%M%S}.db"
if backup_path.exists():
    raise FileExistsError("Backup already exists; choose a new destination")
with sqlite3.connect(f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True) as source:
    with sqlite3.connect(backup_path) as destination:
        source.backup(destination)
print(f"Created private backup: {backup_path}")
'@ | .\.venv\Scripts\python.exe -
```

To restore into a **fresh clone before its first backend start**, copy that
backup to `backend\storefront.db`. Do not overwrite an existing database. If
one already exists, preserve it and configure a different
`STOREFRONT_DATABASE_PATH` in `backend/.env`. The restored database is migrated
additively at startup. Database backups contain private account and order data;
protect and retain them separately from source control.

Demo product images use remote image URLs and need network access. The
application code and bundled SVG/favicon assets are tracked in Git.

## Optional services and limits

- `GEMINI_API_KEY` enables the backend-only Gemini integration. Without it, the
  deterministic assistant fallback remains available. Never put the key in a
  frontend environment file.
- `AI_API_KEY`, `AI_MODEL`, and `AI_BASE_URL` configure the optional compatible
  Responses API integration when Gemini is not configured.
- SMTP delivery is optional and uses STARTTLS. Without SMTP configuration,
  order updates still work and delivery is recorded as not configured.
- Checkout is a demo order flow; it does not charge payment cards.
- Live provider calls, SMTP delivery, and browser/device coverage require
  external accounts or devices and are not established by the test suite.

See [backend/ORDERS.md](backend/ORDERS.md) for order, analytics, notification,
and AI behavior details.
