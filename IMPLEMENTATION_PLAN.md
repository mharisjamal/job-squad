# JobSquad - Implementation Plan

**One-liner:** The multiplayer job hunt. A self-hosted web app where a small group of friends shares one pool of companies and job portals, while each member tracks their own application pipeline, statuses, and notes on every item - and everyone can see each other's progress.

This document is the **frozen contract**. All agents build exactly to it: paths, JSON field names, enums, ports. Do not invent alternatives. If something is genuinely impossible, note it in your final report instead of changing the contract.

---

## 0. House rules (ALL agents, hard requirements)

1. **NEVER use the em-dash character (U+2014) anywhere** - not in code, comments, UI strings, docs, or commit messages. Use a hyphen `-`, colon, parentheses, or reword.
2. JSON on the wire is **snake_case**. TypeScript types mirror the wire exactly.
3. All timestamps are stored and served as **UTC ISO 8601** strings (e.g. `2026-07-29T14:03:00Z`); the frontend renders local time.
4. Stay inside your assigned directory. Backend agent: `backend/` only. Frontend agent: `frontend/` only. Launcher/docs agent: root files only (`run.py`, `START.bat`, `README.md`, `DEPLOY.md`).
5. Do not run `git commit` - the orchestrator commits.
6. Code quality: small focused modules, no dead code, no TODO placeholders. Every page handles loading / empty / error states.

## 1. Requirements traceability (what the user asked for)

| # | User requirement | Feature |
|---|---|---|
| R1 | Me and my friend both log in | Username + password auth, JWT sessions |
| R2 | A group with me, my friend, or any other persons | Groups: create, join by 8-char invite code, multiple groups per user |
| R3 | Shared list of companies anyone can post | Companies CRUD, scoped to group, `created_by` attribution |
| R4 | Shared list of job portals | Portals CRUD, scoped to group |
| R5 | Friend applies + adds status/notes; I see it, apply separately, track my own status | Applications: one row per (member, company). Everyone sees all rows, edits only their own |
| R6 | Status "accepted rejected or whatever" | 7 statuses: saved, applied, assessment, interview, offer, rejected, ghosted |
| R7 | "Similarly for job portals" | Per-member portal status: signed_up / active / abandoned + 1-5 rating + notes |
| R8 | Option to add notes for that company or anything | Shared company/portal notes + personal per-application notes + comment thread per company |
| R9 | "I want to drag the application" | Kanban board: drag my application cards between status columns |
| R10 | "Very very exported" | CSV export: applications (all or mine), companies, portals |
| R11 | See what friend posted that I have not applied to | "Not applied by me" filter + dashboard nudge |

Value-adds for satisfaction: live activity feed (SSE), dashboard with member comparison + funnel + portal effectiveness, follow-up dates, invite-code sharing UI.

## 2. Architecture and stack

- **One deployable process.** FastAPI serves the JSON API under `/api/*` AND the built React SPA (static files + index.html fallback) on port **8100**. LAN-shareable instantly, free-tier deployable later (see DEPLOY.md).
- **SQLite (WAL mode) via async SQLAlchemy 2 + aiosqlite.** Zero external services, DB file at `data/jobsquad.db`, backup = copy one file. Keep SQL portable (no SQLite-only SQL besides PRAGMA setup) so Postgres is a config swap later.
- **Auth is stdlib-only:** PBKDF2-HMAC-SHA256 (250,000 iterations, 16-byte salt) password hashing + hand-rolled HS256 JWT (`hmac` + `base64url`). Never trust the JWT `alg` header. No auth libraries.
- **Realtime:** SSE activity stream per group (sse-starlette). Frontend uses events as a "refetch nudge" for TanStack Query + 30s polling fallback.
- **Frontend:** Vite 5 + React 18 + TypeScript strict + Tailwind 3 + TanStack Query 5 + react-router 6 + @dnd-kit/core (kanban drag) + lucide-react icons. Fonts self-hosted via @fontsource.

### Repo layout

```
JobSquad/
  IMPLEMENTATION_PLAN.md   (this file)
  README.md                (launcher/docs agent)
  DEPLOY.md                (launcher/docs agent)
  run.py                   (launcher/docs agent)
  START.bat                (launcher/docs agent)
  .gitignore
  data/                    (runtime: sqlite db + auto-generated secret; gitignored)
  backend/
    pyproject.toml         (project + deps + [tool.ruff] + [tool.pytest.ini_options])
    app/
      __init__.py
      main.py              (create_app(), CORS, routers, SPA static serving, /health)
      config.py            (env-driven settings)
      db.py                (engine/session factory, init_db create_all, PRAGMAs)
      models.py            (SQLAlchemy ORM)
      schemas.py           (Pydantic request/response models)
      security.py          (pbkdf2 hash/verify, jwt encode/decode)
      deps.py              (current_user, group membership guards)
      activity.py          (record() helper + SSE broadcasting)
      routers/
        auth.py groups.py companies.py applications.py portals.py
        comments.py activity.py stats.py export.py
    tests/
      conftest.py test_auth.py test_groups.py test_companies.py
      test_applications.py test_portals.py test_export.py test_scoping.py
  frontend/
    package.json vite.config.ts tsconfig.json tailwind.config.js postcss.config.js
    index.html
    src/
      main.tsx App.tsx index.css
      lib/api.ts           (fetch wrapper, token store, 401 handler, sse helper)
      lib/format.ts        (timeAgo, date formatting)
      types/api.ts         (wire types, mirror this contract)
      components/          (ui primitives + layout: Shell, Sidebar, Topbar, dialogs,
                            StatusBadge, MemberChip, EmptyState, Spinner, Toast)
      pages/
        Auth.tsx Groups.tsx Dashboard.tsx Companies.tsx CompanyDetail.tsx
        Board.tsx Portals.tsx Activity.tsx
      hooks/               (useAuth.tsx, useGroup queries, useCompanies, useApplications,
                            usePortals, useActivity, useStats)
```

## 3. Configuration (env vars, all optional)

| Var | Default | Meaning |
|---|---|---|
| `JOBSQUAD_PORT` | `8100` | API + app port |
| `JOBSQUAD_DB_PATH` | `data/jobsquad.db` | SQLite file (dir auto-created) |
| `JOBSQUAD_SECRET` | auto | JWT signing secret; if unset, generate 32 random bytes and persist to `data/.secret` so tokens survive restarts |
| `JOBSQUAD_TOKEN_TTL_HOURS` | `168` | Session token lifetime (7 days) |
| `JOBSQUAD_DEV` | unset | `1` = launcher runs Vite dev server on 3100 instead of serving the build |

CORS: allow all origins, `allow_credentials=False` (auth is via Bearer header, not cookies).

## 4. Data model (SQLAlchemy, table names exact)

- **users**: id PK, username TEXT UNIQUE NOT NULL (stored lowercase, 3-30 chars `[a-z0-9_]`), display_name TEXT NOT NULL, password_hash TEXT NOT NULL, created_at DateTime
- **groups**: id PK, name TEXT NOT NULL, invite_code TEXT UNIQUE NOT NULL (8 chars from `A-Z0-9`, unambiguous set, generated server-side), owner_id FK users, created_at
- **group_members**: id PK, group_id FK, user_id FK, role TEXT ('owner'|'member'), joined_at; UNIQUE(group_id, user_id)
- **companies**: id PK, group_id FK, name TEXT NOT NULL, website TEXT, careers_url TEXT, location TEXT, tags JSON (list of strings, default []), notes TEXT (shared facts), archived BOOL default false, created_by FK users, created_at, updated_at
- **portals**: id PK, group_id FK, name TEXT NOT NULL, url TEXT, notes TEXT (shared), created_by FK users, created_at, updated_at
- **applications**: id PK, company_id FK, user_id FK, status TEXT NOT NULL, applied_via_portal_id FK portals NULLABLE, applied_at DATE NULLABLE, follow_up_at DATE NULLABLE, url TEXT (job posting link), notes TEXT (personal), created_at, updated_at; UNIQUE(company_id, user_id)
- **portal_statuses**: id PK, portal_id FK, user_id FK, status TEXT NOT NULL, rating INT NULLABLE (1-5), notes TEXT, updated_at; UNIQUE(portal_id, user_id)
- **comments**: id PK, company_id FK, user_id FK, body TEXT NOT NULL, created_at
- **activity**: id PK, group_id FK, user_id FK, type TEXT, company_id NULLABLE, portal_id NULLABLE, detail JSON (dict), created_at

Indexes: applications(user_id), applications(company_id), activity(group_id, id), companies(group_id), portals(group_id), comments(company_id), group_members(user_id).

Deletes: deleting a company cascades its applications + comments. Deleting a portal sets `applied_via_portal_id` NULL and cascades portal_statuses. `init_db()` runs `create_all` on startup plus `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` (foreign_keys on every connection via engine event).

## 5. Enums and status colors (frozen)

Application status (order matters, kanban column order):

| value | label | color (hex) |
|---|---|---|
| `saved` | Saved | `#64748b` slate |
| `applied` | Applied | `#3b82f6` blue |
| `assessment` | Assessment | `#8b5cf6` violet |
| `interview` | Interview | `#f59e0b` amber |
| `offer` | Offer | `#10b981` emerald |
| `rejected` | Rejected | `#ef4444` red |
| `ghosted` | Ghosted | `#71717a` zinc |

Portal member status: `none` (no row), `signed_up`, `active`, `abandoned`.

Activity types: `member_joined`, `company_added`, `portal_added`, `application_status_changed` (detail `{"from": "...|null", "to": "..."}`), `application_removed`, `comment_added`, `portal_status_changed` (detail `{"to": "..."}`).

`response_rate` definition (used in stats): base = my applications with status != saved; responses = those with status in (assessment, interview, offer, rejected); rate = responses / base, null when base is 0.

## 6. API contract (frozen; base `/api`; all responses JSON)

Conventions: auth via `Authorization: Bearer <token>`; SSE endpoints ALSO accept `?access_token=<token>` (EventSource cannot send headers). Errors: `{"detail": "message"}`. 401 = bad/missing token. A resource in a group the caller does not belong to returns **404** (no existence leak). 403 only for known-but-forbidden (e.g. deleting a company you did not post). Validation errors 422 (FastAPI default).

Shared shapes:

```
User            {id, username, display_name}
ApplicationBrief{user_id, username, display_name, status, applied_at, updated_at}
ApplicationFull {id, company_id, company_name, user_id, username, display_name, status,
                 applied_via_portal_id, applied_via_portal_name, applied_at, follow_up_at,
                 url, notes, created_at, updated_at}
Company         {id, group_id, name, website, careers_url, location, tags, notes, archived,
                 created_by, created_by_username, created_at, updated_at,
                 applications: [ApplicationBrief], comment_count}
Portal          {id, group_id, name, url, notes, created_by, created_by_username,
                 created_at, updated_at,
                 statuses: [{user_id, username, display_name, status, rating, notes, updated_at}],
                 stats: {applications_via, interviews_via, offers_via}}
Comment         {id, company_id, user_id, username, display_name, body, created_at}
Activity        {id, group_id, user_id, username, display_name, type,
                 company_id, company_name, portal_id, portal_name, detail, created_at}
Group           {id, name, invite_code, owner_id, created_at, member_count}
GroupDetail     Group + {members: [{user_id, username, display_name, role, joined_at}]}
```

### Auth (`routers/auth.py`)
- `POST /api/auth/register` `{username, display_name, password}` -> `{token, user: User}`. Open registration. Password min 8 chars. Username normalized lowercase; 409 if taken.
- `POST /api/auth/login` `{username, password}` -> `{token, user: User}`. 401 on bad creds.
- `GET /api/auth/me` -> `User`.

### Groups (`routers/groups.py`)
- `POST /api/groups` `{name}` -> `Group`. Creator becomes owner member; invite_code generated.
- `GET /api/groups` -> `[Group]` (mine only).
- `GET /api/groups/{gid}` -> `GroupDetail` (members only).
- `POST /api/groups/join` `{invite_code}` -> `Group`. Case-insensitive code. 404 unknown code; joining twice is idempotent (returns group).
- `POST /api/groups/{gid}/leave` -> `{ok: true}`. Owner cannot leave while other members exist (400).
- `PATCH /api/groups/{gid}` `{name}` -> `Group`. Owner only (403 otherwise).

### Companies (`routers/companies.py`)
- `GET /api/groups/{gid}/companies?q=&tag=&status=&include_archived=false` -> `[Company]`. `q` matches name/location case-insensitive. `status` filter special values: any application status filters to companies where MY application has that status; `not_applied` = companies with no application row of mine. Sorted by updated_at desc.
- `POST /api/groups/{gid}/companies` `{name, website?, careers_url?, location?, tags?, notes?}` -> `Company`. Records `company_added` activity.
- `GET /api/companies/{cid}` -> `Company` + full detail: `applications: [ApplicationFull]`, `comments: [Comment]`.
- `PATCH /api/companies/{cid}` (any member; partial: name, website, careers_url, location, tags, notes, archived) -> `Company`.
- `DELETE /api/companies/{cid}` -> `{ok: true}`. Poster or group owner only (403 otherwise).

### Applications (`routers/applications.py`)
- `PUT /api/companies/{cid}/application` `{status, applied_via_portal_id?, applied_at?, follow_up_at?, url?, notes?}` -> `ApplicationFull`. Upserts MY application row. On status change (including create), record `application_status_changed`.
- `DELETE /api/companies/{cid}/application` -> `{ok: true}`. Removes my row; records `application_removed`. 404 if none.
- `GET /api/groups/{gid}/applications?user_id=&status=` -> `[ApplicationFull]`. `user_id` accepts an id or `me`. Sorted updated_at desc.

### Portals (`routers/portals.py`)
- `GET /api/groups/{gid}/portals` -> `[Portal]` (with per-member statuses + stats computed from applications.applied_via_portal_id: total, status in (assessment,interview) as interviews_via, offer as offers_via).
- `POST /api/groups/{gid}/portals` `{name, url?, notes?}` -> `Portal`. Activity `portal_added`.
- `PATCH /api/portals/{pid}` (partial: name, url, notes) -> `Portal` (any member).
- `DELETE /api/portals/{pid}` -> `{ok: true}`. Poster or group owner only.
- `PUT /api/portals/{pid}/status` `{status, rating?, notes?}` -> Portal's status row `{user_id, username, display_name, status, rating, notes, updated_at}`. Upsert mine; `status: "none"` deletes my row. Activity `portal_status_changed` on change.

### Comments (`routers/comments.py`)
- `GET /api/companies/{cid}/comments` -> `[Comment]` (asc by created_at).
- `POST /api/companies/{cid}/comments` `{body}` -> `Comment`. Activity `comment_added`.
- `DELETE /api/comments/{id}` -> `{ok: true}`. Author only.

### Activity + SSE (`routers/activity.py`)
- `GET /api/groups/{gid}/activity?limit=50&before_id=` -> `[Activity]` desc.
- `GET /api/groups/{gid}/activity/sse?access_token=` -> SSE. On connect sends `event: hello`. Then for each new activity row in this group: `event: activity`, `data: <Activity JSON>`. Implementation: in-process asyncio broadcast (activity.record() pushes to per-group subscriber queues) + 15s `: keepalive` comments. No cross-process bus needed (single process).

### Stats (`routers/stats.py`)
- `GET /api/groups/{gid}/stats` ->
```
{group: {companies, portals, applications, members},
 per_member: [{user_id, username, display_name,
               counts: {saved, applied, assessment, interview, offer, rejected, ghosted, total},
               response_rate}],
 per_portal: [{portal_id, name, applications_via, interviews_via, offers_via}]}
```

### Export (`routers/export.py`) - all return `text/csv` with Content-Disposition attachment
- `GET /api/groups/{gid}/export/applications.csv?user_id=` (blank = all members; `me` = mine). Columns: `company,member,status,applied_at,follow_up_at,applied_via,posting_url,notes,updated_at`
- `GET /api/groups/{gid}/export/companies.csv` Columns: `name,website,careers_url,location,tags,notes,posted_by,created_at,archived`
- `GET /api/groups/{gid}/export/portals.csv` Columns: `name,url,notes,posted_by,applications_via,created_at`
CSV via Python `csv` module (proper quoting). Tags joined with `;`. These endpoints also accept `?access_token=` (browser downloads via `<a href>` cannot set headers).

### Infra (in `main.py`)
- `GET /health` -> `{status: "ok"}` (no auth).
- SPA serving: if `frontend/dist/index.html` exists, mount `/assets` static and serve `index.html` for any non-`/api`, non-`/health` GET (catch-all route) so client routing works on refresh.

## 7. Frontend spec

### Design system ("NightShift" theme, dark only)
- Background `#0b0d12`, raised surface `#12151d`, border `#1f2430` (subtle), text `#e7e9ee`, muted `#8b93a7`.
- Accent: **emerald `#10b981`** (primary actions, active nav, focus rings). Secondary warm amber `#f59e0b` used sparingly (highlights, interview status). Status colors from section 5 everywhere a status appears (badge bg = color at 15% opacity, text = color).
- Fonts (self-hosted @fontsource, imported in main.tsx): **Manrope Variable** for UI, **IBM Plex Mono** for data bits (dates, counts, invite codes, statuses in tables).
- Tailwind config maps these as tokens (`bg`, `surface`, `border`, `accent`, plus `status.saved` ... `status.ghosted`). Rounded-xl cards, 1px borders, soft shadow, generous spacing. Buttons: solid accent primary, ghost secondary. Focus-visible rings everywhere. `prefers-reduced-motion` respected.
- Member avatars: initials in a circle, hue derived deterministically from username hash (`hsl(hash % 360, 55%, 45%)`), white initials.

### Routing and screens
- `/auth`: split screen. Left: brand panel (logo wordmark "JobSquad", tagline "The multiplayer job hunt", 3 bullet value props). Right: login/register toggle form. On success store token, redirect to `/`.
- `/` (Groups): my groups as cards (name, member_count, invite code with copy button) + "Create group" and "Join with code" dialogs. Clicking a group -> `/g/:gid`. localStorage `last_group` -> auto-redirect if it still exists (a "Switch group" item in the user menu returns here).
- `/g/:gid` shell: left sidebar nav (Dashboard, Companies, Board, Portals, Activity), group name + switcher on top, user menu (display name, Sign out), invite-code chip with copy. Mobile: sidebar collapses to a drawer (hamburger).
  - **Dashboard** (`/g/:gid`): KPI row (my totals: Applied, In interviews, Offers, Response rate). "Squad comparison": horizontal stacked bars per member colored by status counts (pure CSS, no chart lib). "Waiting for you": up to 5 companies with `not_applied` by me + link to filtered Companies. "Upcoming follow-ups": my applications with follow_up_at within 7 days. "Portal effectiveness" mini-table from stats.per_portal. Recent activity (last 8).
  - **Companies** (`/g/:gid/companies`): toolbar: search input (debounced), status filter select (All, Not applied by me, then the 7 statuses), tag filter, "Add company" button. Desktop: table (Company, Location, Tags, Squad = one MemberChip per member with status-colored dot + tooltip, My status = inline select that upserts, Updated). Mobile: stacked cards. Row click -> detail. Empty state with CTA.
  - **Company detail** (`/g/:gid/companies/:cid`): header (name, links, tags, posted by, Edit + Delete for allowed). Left column: "Squad status" cards, one per application: avatar, status badge, applied date, via portal, their notes (read-only, note "notes are visible to your group"). Right column: "My application" editor: status select, applied_at + follow_up_at date inputs, applied-via portal select, posting url, notes textarea, Save (PUT upsert), "Remove my application". Below: shared notes (editable, PATCH) + comments thread (list + input).
  - **Board** (`/g/:gid/board`): 7 kanban columns in status order, my ApplicationFull cards (company name, applied date, portal chip, follow-up badge if due). @dnd-kit drag card -> drop on column = PUT upsert with new status (optimistic update, rollback on error). Column headers show count. An "Add companies to your board" empty-state hint links to Companies when I have no applications.
  - **Portals** (`/g/:gid/portals`): grid of cards: name (link), shared notes, effectiveness line ("12 applications, 3 interviews, 1 offer via this portal"), per-member status chips, "My status" inline editor (status select + 1-5 star rating + notes popover). Add/edit/delete portal dialogs.
  - **Activity** (`/g/:gid/activity`): feed grouped by day; each item: avatar, sentence ("Ali moved TechCorp to Interview", "Haris added portal LinkedIn"), timeAgo. Live: SSE connection; on `activity` event prepend + invalidate related queries (companies, stats, portals). Reconnect with backoff; falls back to 30s polling if SSE errors.
- Export menu in topbar: three items downloading the CSVs via `<a href>` with `?access_token=`.

### API client (`lib/api.ts`)
- Base URL: same-origin relative paths (`/api/...`) - works in prod (served by FastAPI) and dev (Vite proxy). Vite dev server proxies `/api` and `/health` to `http://localhost:8100`.
- Token in localStorage (`jobsquad_token`). `apiGet/apiSend` attach Bearer; on 401 clear token + redirect `/auth`. `sseUrl(path)` appends `access_token`. Toast on mutation errors.
- TanStack Query: sensible keys per group; mutations invalidate; `refetchOnWindowFocus: true`; activity SSE nudges invalidation.

## 8. Build phases and agent ownership

- **Phase 1 (parallel, disjoint dirs):**
  - **Agent A - Backend** (`backend/`): everything in sections 3-6 + tests. Gates: `uv run ruff check .` clean; `uv run pytest` green (cover: auth flow incl. bad password + dup username; group create/join/idempotent-join/leave rules; company CRUD + filters incl. `not_applied`; application upsert + activity logging + uniqueness; portal status upsert incl. `none` delete; comments; exports return 200 + correct header row; **scoping: non-member gets 404 on other group's company/portal/application/activity/stats/export**); app boots and `/health` returns ok.
  - **Agent B - Frontend** (`frontend/`): everything in section 7. Gates: `npm run typecheck` (tsc strict, zero errors); `npm run build` succeeds; every screen handles loading/empty/error; no hardcoded `localhost:8100` anywhere except vite proxy config.
  - **Agent C - Launcher + docs** (root): `run.py` (check uv+node; `uv sync` backend with `UV_CACHE_DIR=D:\uv` when D: exists; `npm install` if node_modules missing; default mode: `npm run build` then start uvicorn `0.0.0.0:8100` serving API+SPA; `JOBSQUAD_DEV=1` mode: start uvicorn + Vite dev on 3100; print local + LAN URL via UDP-connect trick; open browser; Ctrl+C stops children cleanly on Windows). `START.bat` (py/python fallback, pause on crash). `README.md` (what it is, features mapped to a friend-group story, quickstart, config table, export, stack, project layout). `DEPLOY.md` (LAN sharing + firewall note; Oracle Cloud Always-Free A1; Render/Fly with the ephemeral-disk warning for SQLite; Cloudflare Tunnel from an always-on PC; backup = copy `data/jobsquad.db`; set `JOBSQUAD_SECRET` in real deployments).
- **Phase 2 (orchestrator):** integration: install, run gates, boot the real stack, browser end-to-end (section 9), fix or dispatch fix agents.
- **Phase 3:** adversarial review agent (authz/scoping, contract conformance, em-dash sweep) -> fixes -> final commit.

## 9. End-to-end acceptance script (run in a real browser)

1. Register user `haris`, auto-login, create group "Job Hunt 2026", see invite code.
2. Register user `ali` (second browser context), join with the code.
3. `ali` adds company "TechCorp" (tags, careers url) + portal "LinkedIn".
4. `haris` sees TechCorp under "Not applied by me", opens it, sees ali's status, sets own status Applied with a note + applied-via LinkedIn.
5. Board: drag TechCorp card Applied -> Interview; verify persistence after reload.
6. `ali` sees haris's interview status + note on company detail; comment thread works both ways.
7. Portals: haris sets LinkedIn status Active + 4 stars; effectiveness line reflects the application.
8. Activity feed shows all of the above; with both windows open, an action in one appears in the other without manual refresh (SSE).
9. Dashboard numbers match reality; export applications.csv downloads and contains both members' rows.
10. Negative: a third user `mallory` registers, cannot access the group's companies by direct URL/id (404s), sees no data.
11. Refresh on a deep route (`/g/1/board`) serves the SPA (no 404). Logout works; deep link returns after login.

## 10. Non-goals (v1)

Email/password reset, avatar uploads, push/mobile notifications, roles beyond owner/member, group deletion or member removal, multi-language, light theme, SSR, offline. All fine later; nothing in v1 blocks them.

## 11. Decisions log

- **Application notes are visible to the whole group.** That is the product's point (shared experience). The UI labels them "visible to your group".
- **SQLite over Postgres/Supabase:** no accounts or services needed to run today; single-file backup; portable SQL keeps the Postgres door open.
- **Single-port serving** (API + built SPA) keeps LAN sharing and deployment one-process simple; Vite dev mode stays available for development.
- **Open registration** is acceptable for a private/LAN deployment; DEPLOY.md tells internet deployers to treat the URL as semi-private (and hardening like invite-only registration is a listed future).
- Ports 8100/3100 chosen to avoid colliding with the user's other project (8000/3000).
