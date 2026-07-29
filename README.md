# JobSquad

**The multiplayer job hunt.**

JobSquad is a small self-hosted web app for a group of friends who are job hunting at the same time. You share one pool of companies and job portals: when anyone finds an interesting company, they post it once and the whole squad sees it. Each member then tracks their own application against it - status (saved, applied, assessment, interview, offer, rejected, ghosted), dates, links, and notes - and everyone can see each other's progress. Drag your applications across a kanban board, watch the group's moves in a live activity feed, and export everything to CSV whenever you want your data elsewhere.

It runs as one process on one port from one command, stores everything in a single SQLite file, and is instantly shareable over your Wi-Fi.

## Features

- **Shared company pool**: anyone in the group posts a company (website, careers page, location, tags, shared notes); everyone sees it.
- **Shared job portals**: a common list of job boards. Each member tracks their own relationship with a portal (signed up / active / abandoned), rates it 1-5, and adds notes.
- **Your pipeline, visible to the squad**: each member keeps one application per company with status, applied date, the portal they applied through, the posting URL, and notes. Notes are visible to your group - that is the point.
- **Seven statuses**: saved, applied, assessment, interview, offer, rejected, ghosted.
- **Kanban board**: drag your application cards between status columns.
- **Comments**: a discussion thread on every company.
- **Dashboard**: your KPIs, squad comparison bars, portal effectiveness ("12 applications, 3 interviews, 1 offer via this portal"), companies you have not applied to yet, and upcoming follow-ups.
- **Follow-up dates**: set one per application and see what is due in the next 7 days.
- **Live activity feed**: "Ali moved TechCorp to Interview" shows up for everyone in real time (SSE), grouped by day.
- **Invite codes**: create a group, share the 8-character code, friends join with it. You can be in several groups.
- **CSV export**: applications (all members or just yours), companies, and portals.
- **LAN sharing**: the launcher prints a network URL that friends on the same Wi-Fi can open.

## Quickstart

Prerequisites:

- Python 3.12+ and [uv](https://astral.sh/uv)
- Node.js 18+ (includes npm) from [nodejs.org](https://nodejs.org)

Then:

1. **Windows**: double-click `START.bat`. **macOS / Linux**: `python3 run.py`.
2. The first run downloads dependencies and builds the app (a few minutes). Later starts are fast.
3. Your browser opens at `http://localhost:8100`.
4. The console also prints a **Network URL** (for example `http://192.168.1.23:8100`). Share it with friends on the same Wi-Fi. If Windows Firewall asks, allow access.
5. Create an account, create a group, and share the **invite code**. Friends open the network URL, register, and join with the code.

## Dev mode

For hacking on the frontend with hot reload:

```
set JOBSQUAD_DEV=1        (Windows)
export JOBSQUAD_DEV=1     (macOS / Linux)
python run.py
```

This skips the production build and starts the Vite dev server at `http://localhost:3100` (it proxies `/api` to the backend on 8100). Backend tests: `uv run pytest` inside `backend/`. Frontend checks: `npm run typecheck` inside `frontend/`.

## Configuration

All optional, via environment variables:

| Var | Default | Meaning |
|---|---|---|
| `JOBSQUAD_PORT` | `8100` | API + app port |
| `JOBSQUAD_DB_PATH` | `data/jobsquad.db` | SQLite file (dir auto-created) |
| `JOBSQUAD_SECRET` | auto | JWT signing secret; if unset, 32 random bytes are generated and persisted to `data/.secret` so sessions survive restarts |
| `JOBSQUAD_TOKEN_TTL_HOURS` | `168` | Session token lifetime (7 days) |
| `JOBSQUAD_DEV` | unset | `1` = launcher runs the Vite dev server on 3100 instead of serving the build |

## Your data

Everything lives in one SQLite file: `data/jobsquad.db`. To back up, copy that file (see [DEPLOY.md](DEPLOY.md) for a safe hot-backup command). The auto-generated auth secret lives in `data/.secret`; keep it with the database if you move the app, or set `JOBSQUAD_SECRET` yourself.

## Export

Inside a group, the topbar **Export** menu downloads three CSVs: applications (all members, or just yours), companies, and portals.

## Stack

One process serves everything: FastAPI answers the JSON API under `/api/*` and serves the built React app on port 8100. SQLite (WAL mode) via async SQLAlchemy. Authentication is stdlib-only (PBKDF2 password hashing + HS256 JWT, no auth libraries). Realtime is server-sent events. Frontend: React 18, Vite, TypeScript (strict), Tailwind, TanStack Query, dnd-kit for the kanban drag.

```
JobSquad/
  START.bat     Windows double-click launcher
  run.py        cross-platform launcher: installs, builds, runs, opens the app
  backend/      FastAPI app: the API + serves the built frontend
  frontend/     React SPA (Vite)
  data/         created at first run: jobsquad.db + .secret
  DEPLOY.md     LAN sharing and free 24/7 hosting options
```

## Putting it on the internet

See [DEPLOY.md](DEPLOY.md): LAN-only (the default), a free 24/7 VM on Oracle Cloud, a Cloudflare Tunnel from an always-on home PC, and why free-tier PaaS disks will eat your SQLite data.

## Security, honestly

Accounts are simple username + password, built for a private deployment among friends. **Anyone who can reach the URL can register and create groups**, so treat the URL as semi-private: keep it on your LAN, or put it behind a tunnel/VPN, and set `JOBSQUAD_SECRET` explicitly on a real server. Passwords are hashed (PBKDF2, 250,000 iterations) and group data is only visible to group members.

## Later ideas

Deliberately not in v1: password reset, email or push notifications, invite-only registration, removing members or deleting groups, avatar uploads, a light theme, and a Postgres option (the SQL is kept portable, so that stays a config swap away).
