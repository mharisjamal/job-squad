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
| `JOBSQUAD_RESEND_API_KEY` | unset | **Resend API key (preferred mail transport).** Setting this (or SMTP) turns on email-OTP registration (`otp_required`) |
| `JOBSQUAD_MAIL_FROM` | unset | From address for verification mail, e.g. `JobSquad <noreply@yourdomain.com>`. Required with Resend |
| `JOBSQUAD_SMTP_HOST` | unset | SMTP server (fallback transport when no Resend key) |
| `JOBSQUAD_SMTP_PORT` | `587` | SMTP port |
| `JOBSQUAD_SMTP_USER` / `JOBSQUAD_SMTP_PASSWORD` | unset | SMTP credentials (optional for unauthenticated relays) |
| `JOBSQUAD_SMTP_STARTTLS` | `true` | Use STARTTLS |
| `JOBSQUAD_PUBLIC_URL` | `http://localhost:8100` | Public base URL of this deployment; used to build OAuth redirect URIs |
| `JOBSQUAD_GOOGLE_CLIENT_ID` / `_SECRET` | unset | Enables "Continue with Google" |
| `JOBSQUAD_GITHUB_CLIENT_ID` / `_SECRET` | unset | Enables "Continue with GitHub" |
| `JOBSQUAD_LINKEDIN_CLIENT_ID` / `_SECRET` | unset | Enables "Continue with LinkedIn" |

CORS: allow all origins, `allow_credentials=False` (auth is via Bearer header, not cookies).

## 4. Data model (SQLAlchemy, table names exact)

- **users**: id PK, username TEXT UNIQUE NOT NULL (**auto-generated, never chosen by the user**; internal handle), display_name TEXT NOT NULL, password_hash TEXT **NULLABLE** (null for social-only accounts), email TEXT UNIQUE NULLABLE (present for every account created after this change), avatar_url TEXT NULLABLE (from the provider), created_at DateTime
- **pending_registrations**: id PK, email TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, otp_hash TEXT NOT NULL, attempts INT default 0, expires_at DateTime, last_sent_at DateTime, created_at DateTime
- **user_identities**: id PK, user_id FK users (CASCADE), provider TEXT NOT NULL (`google`|`github`|`linkedin`), provider_user_id TEXT NOT NULL, email TEXT NULLABLE, created_at; UNIQUE(provider, provider_user_id), index(user_id)

(Schema changes on an existing DB are applied by a lightweight idempotent migration in `db.py` - `create_all` plus explicit `PRAGMA table_info` checks + `ALTER TABLE ... ADD COLUMN` / `CREATE UNIQUE INDEX IF NOT EXISTS` - since this project deliberately has no Alembic. SQLite cannot drop a NOT NULL constraint in place, so making `password_hash` nullable on an existing DB uses the standard 12-step table rebuild: create the new table, copy rows, drop, rename, inside one transaction.)
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

Application status (order matters, kanban column order). Status color is the ONLY vivid color in the UI; each status has a text color and a tint background (badge = tint bg + text color + leading dot, AA contrast). **Per-mode values, exposed as CSS variables (`--status-applied-text` etc.) so components never hardcode a hex:**

Dark (default):

| value | label | text | tint bg | dot |
|---|---|---|---|---|
| `saved` | Saved | `#A8B3C2` | `#1A1F26` | `#8A94A3` |
| `applied` | Applied | `#7FAAF8` | `#131C2B` | `#5B8DEF` |
| `assessment` | Assessment | `#B69CF5` | `#1E1A2E` | `#9B7BE8` |
| `interview` | Interview | `#E5A55A` | `#2A2015` | `#D9903C` |
| `offer` | Offer | `#57C08A` | `#12241C` | `#3FA875` |
| `rejected` | Rejected | `#F08585` | `#2A1719` | `#E06C6C` |
| `ghosted` | Ghosted | `#9AA0A8` | `#1C1E22` | `#7C838C` |

Light:

| value | label | text | tint bg | dot |
|---|---|---|---|---|
| `saved` | Saved | `#475569` | `#F1F5F9` | `#64748B` |
| `applied` | Applied | `#1D4ED8` | `#EFF6FF` | `#2563EB` |
| `assessment` | Assessment | `#6D28D9` | `#F5F3FF` | `#7C3AED` |
| `interview` | Interview | `#B45309` | `#FFFBEB` | `#D97706` |
| `offer` | Offer | `#047857` | `#ECFDF5` | `#059669` |
| `rejected` | Rejected | `#B91C1C` | `#FEF2F2` | `#DC2626` |
| `ghosted` | Ghosted | `#52525B` | `#F4F4F5` | `#71717A` |

Portal member status: `none` (no row), `signed_up`, `active`, `abandoned`.

Activity types: `member_joined`, `company_added`, `portal_added`, `application_status_changed` (detail `{"from": "...|null", "to": "..."}`), `application_removed`, `comment_added`, `portal_status_changed` (detail `{"to": "..."}`).

`response_rate` definition (used in stats): base = my applications with status != saved; responses = those with status in (assessment, interview, offer, rejected); rate = responses / base, null when base is 0.

## 6. API contract (frozen; base `/api`; all responses JSON)

Conventions: auth via `Authorization: Bearer <token>`; SSE and CSV-export endpoints ONLY additionally accept `?access_token=<token>` (EventSource and `<a href>` downloads cannot send headers; the query token is rejected everywhere else so full-privilege tokens do not spread into URLs, and the uvicorn access log redacts `access_token` values). Errors: `{"detail": "message"}`. 401 = bad/missing token. A resource in a group the caller does not belong to returns **404** (no existence leak). 403 only for known-but-forbidden (e.g. deleting a company you did not post). Validation errors 422 (FastAPI default).

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

**Identity model:** email is the login identifier; **usernames are never chosen by a user**. On account creation the server derives a handle from the email local part (or display name), slugified to `[a-z0-9_]`, 3-30 chars, uniquified with a numeric suffix on collision. Social accounts have `password_hash = NULL` and cannot use password login. `User` wire shape gains `avatar_url` (nullable) and `email` (nullable); `username` stays for display fallbacks.

- `GET /api/auth/config` (public) -> `{otp_required: bool, providers: ["google","github","linkedin"]}` - `providers` lists only those with credentials configured; the frontend renders exactly those buttons. `otp_required` is true when a mail transport (Resend key or SMTP host) is configured.
- `POST /api/auth/login` `{identifier, password}` -> `{token, user}`. `identifier` matches email OR username (back-compat for pre-existing accounts). 401 on bad creds or on an account with no password (message: "That account signs in with Google, GitHub, or LinkedIn."). Throttled (10 failures / 5 min per identifier+IP -> 429). The legacy `{username, password}` body still works.
- `POST /api/auth/register` `{display_name, email, password}` -> `{token, user}`. **Only when `otp_required` is false** (403 otherwise). No username field. Username auto-derived.
- **Email-OTP signup (active when a mail transport is configured):**
  - `POST /api/auth/register/start` (public) `{display_name, email, password}` -> `{ok: true, resend_after_seconds: 60}`. 409 if the email already has an account. Upserts a `pending_registrations` row keyed by email with a 6-digit code (crypto-random; stored as HMAC-SHA256 keyed by the app secret and bound to the email; never plaintext, never logged), TTL 10 minutes. Throttles: 60s resend cooldown per email (429), 10 starts per IP per hour (429). Mail failure -> 502, real error logged server-side.
  - `POST /api/auth/register/verify` (public) `{email, code}` -> `{token, user}` (auto-login). Constant-time compare; 5 wrong attempts deletes the pending row (429, start again); expired -> 410. Race-safe user creation.
- **Social sign-in (OAuth 2.0 authorization code + PKCE where supported; secrets stay server-side):**
  - `GET /api/auth/oauth/{provider}/start` (public) -> **302** to the provider's consent screen. Server generates `state` (signed, 10-minute TTL, HttpOnly-free: carried in a short-lived signed token, verified on callback) and a PKCE `code_verifier`; 404 when the provider is not configured.
  - `GET /api/auth/oauth/{provider}/callback?code=&state=` (public) -> **302 to the SPA** at `{public_url}/auth/callback#token=<jwt>` on success, or `#error=<code>` on failure. **The session token travels in the URL fragment, never the query string**, so it is not sent to servers, not written to access logs, and not leaked via Referer; the SPA reads it, stores it, and immediately `history.replaceState`s it out of the address bar.
  - Provider endpoints/scopes: **Google** OIDC (`openid email profile`), **GitHub** (`read:user user:email`; primary verified address fetched from `/user/emails` because the public profile email is often null), **LinkedIn** OIDC (`openid profile email`, userinfo endpoint).
  - **Account linking rule (takeover-safe):** find identity by `(provider, provider_user_id)` -> log in. Else, if the provider asserts a **verified** email that matches an existing user, link a new `user_identities` row to that user. If the provider does not verify the email, do **not** auto-link: return `#error=email_unverified`. Otherwise create a new user (no password, avatar + display name from the provider, derived username).
- `GET /api/auth/me` -> `User`.

### Groups (`routers/groups.py`)
- `POST /api/groups` `{name}` -> `Group`. Creator becomes owner member; invite_code generated.
- `GET /api/groups` -> `[Group]` (mine only).
- `GET /api/groups/{gid}` -> `GroupDetail` (members only).
- `POST /api/groups/join` `{invite_code}` -> `Group`. Case-insensitive code. 404 unknown code; joining twice is idempotent (returns group).
- `POST /api/groups/{gid}/leave` -> `{ok: true}`. Owner cannot leave while other members exist (400, message "Transfer ownership to another member first, then you can leave." - see Phase G2). The last remaining member cannot leave either (400; group deletion is a non-goal, so no path may destroy group data). A successful leave also deletes the leaver's applications and portal statuses in that group (their personal pipeline goes with them; stats stay reconciled); their comments and activity rows remain as history.
- `PATCH /api/groups/{gid}` `{name}` -> `Group`. Owner only (403 otherwise).
- `POST /api/groups/{gid}/transfer-ownership` `{new_owner_id}` -> `GroupDetail`. Owner only (403 for a member, 404 for a non-member). 400 on yourself, 404 when the target is not a member of this group. One transaction moves `groups.owner_id` and both role rows; records `ownership_transferred`. See Phase G2.

### Companies (`routers/companies.py`)
- `GET /api/groups/{gid}/companies?q=&tag=&status=&include_archived=false` -> `[Company]`. `q` matches name/location case-insensitive. `status` filter special values: any application status filters to companies where MY application has that status; `not_applied` = companies with no application row of mine. Sorted by updated_at desc.
- `POST /api/groups/{gid}/companies` `{name, website?, careers_url?, location?, tags?, notes?}` -> `Company`. Records `company_added` activity.
- `GET /api/companies/{cid}` -> `Company` + full detail: `applications: [ApplicationFull]`, `comments: [Comment]`.
- `PATCH /api/companies/{cid}` (any member; partial: name, website, careers_url, location, tags, notes, archived) -> `Company`.
- `DELETE /api/companies/{cid}` -> `{ok: true}`. Poster or group owner only (403 otherwise).

### Applications (`routers/applications.py`)
- `PUT /api/companies/{cid}/application` `{status, applied_via_portal_id?, applied_at?, follow_up_at?, url?, notes?}` -> `ApplicationFull`. Upserts MY application row with **merge semantics**: only fields present in the request body are applied; an explicitly null field clears; an omitted field is left unchanged on an existing row (null on create). This lets lightweight callers (inline status select, kanban drag) send `{status}` alone without wiping notes/portal/dates. On status change (including create), record `application_status_changed`.
- `DELETE /api/companies/{cid}/application` -> `{ok: true}`. Removes my row; records `application_removed`. 404 if none.
- `GET /api/groups/{gid}/applications?user_id=&status=` -> `[ApplicationFull]`. `user_id` accepts an id or `me`. Sorted updated_at desc.

### Portals (`routers/portals.py`)
- `GET /api/groups/{gid}/portals` -> `[Portal]` (with per-member statuses + stats computed from applications.applied_via_portal_id: total, status in (assessment,interview) as interviews_via, offer as offers_via).
- `POST /api/groups/{gid}/portals` `{name, url?, notes?}` -> `Portal`. Activity `portal_added`.
- `PATCH /api/portals/{pid}` (partial: name, url, notes) -> `Portal` (any member).
- `DELETE /api/portals/{pid}` -> `{ok: true}`. Poster or group owner only.
- `PUT /api/portals/{pid}/status` `{status, rating?, notes?}` -> Portal's status row `{user_id, username, display_name, status, rating, notes, updated_at}` (`updated_at` null only in the `status: "none"` response). **Merge semantics like the application PUT**: only provided fields are applied, explicit null clears, omitted fields are preserved. `status: "none"` deletes my row. Activity `portal_status_changed` on change.

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

### Design system ("Worklight", professional, usability-first, **dark by default**)

Philosophy: JobSquad is a daily-use working tool, so it must read like a serious product (Linear / Stripe-dashboard restraint), not a themed landing page. The interface is monochrome; color appears ONLY where it carries meaning: application/portal status, destructive actions, focus states. No gradients, no glow, no decorative color.

**Two modes, dark is the default.** Both are first-class and share one token contract; every token is a CSS variable on `:root` (dark) and `:root[data-theme="light"]`, and Tailwind tokens reference `var(...)` so no component hardcodes a hex. An inline script in `index.html` sets `data-theme` from `localStorage` before first paint (no theme flash). Toggle lives in the sidebar user menu ("Switch to light mode" / "Switch to dark mode"), persisted as `jobsquad_theme`; default when unset is dark.

**Dark-mode craft rules (these are what separate a professional dark UI from the generic "AI" one):**
1. **No pure black and no neon accent.** The canvas is a blue-tinted charcoal, not `#000`; there is no acid-green/violet/cyan brand glow anywhere.
2. **Elevation is expressed by surface lightness, not shadows** (shadows barely read on dark). Canvas -> card -> dialog each step lighter.
3. **Borders are lighter than their surface** (never darker), 1px, low contrast.
4. **Text is off-white, never `#FFFFFF`** (pure white on near-black causes halation and eye strain over a long session).
5. **Status colors are re-derived per mode, not reused.** Saturated light-mode colors vibrate on dark, so dark uses lighter, lower-chroma text colors on very dark tinted backgrounds.
6. **The primary button inverts** (light surface, dark text) instead of introducing a saturated brand fill: the interface stays monochrome and the action still reads as primary.

Palette (dark, default):
`canvas #0F1216` (app bg) - `paper #171B21` (cards) - `raised #1E232A` (dialogs, popovers, menus) - `line #262C34` (borders) - `line-strong #333A44` (structural dividers) - `ink #E7EAEE` (primary text) - `muted #98A2B0` (secondary text, AA on canvas) - `focus #6AA1FF` (links + focus rings only) - `danger #F87171`. Primary button: `ink` background with `canvas` text; secondary: `paper` background, `line` border, `ink` text; hover on rows/ghost controls: `#1B2028`.

Palette (light): `paper #FFFFFF` - `canvas #F7F7F5` - `raised #FFFFFF` - `line #E4E4E1` - `line-strong #D6D6D2` - `ink #1A1D21` - `muted #5C6470` - `focus #2563EB` - `danger #DC2626`. Primary button: `ink` bg, white text; row hover `#FAFAF9`.

Member avatars: `hsl(hash(username) % 360, 40%, 52%)` in dark and `hsl(..., 45%, 42%)` in light, white initials in both.
- Typography (self-hosted @fontsource, imported in main.tsx): **IBM Plex Sans** (400/500/600) for all UI, **IBM Plex Mono** for data (dates, counts, invite codes, status badge text). One family system, engineered feel. Headings are Plex Sans 600 with `-0.01em` tracking at restrained sizes (page title ~20px, section heading ~14px, body 14px, small 12.5px). Sentence case everywhere: headings, buttons, labels. No display font, no hero type, no uppercase-tracked eyebrows.
- Components: primary button = ink bg, white text, rounded-md (6px), 34px height; secondary = paper bg + 1px line border + ink text; danger styling only on destructive confirms. Cards = paper, 1px line border, rounded-lg (10px), NO shadows (a single subtle shadow allowed on dialogs/popovers only). Tables: 12.5px medium muted sentence-case header row, 44px rows, hairline dividers, hover row `#FAFAF9`, dates/counts right-aligned in Plex Mono. Inputs: paper bg, line border, labels above, 2px focus ring in `focus` blue.
- **Signature element** (the one place boldness is spent): the **Squad row**: overlapping 24px member avatars where each avatar wears a 2px ring in that member's status color for the company in question (dim gray ring outline = not applied), with tooltip "name: status". Used on company rows and the dashboard. Everything around it stays quiet.
- Member avatars: initials in a circle, deterministic hue `hsl(hash(username) % 360, 45%, 42%)`, white initials.
- Motion: 120-150ms ease-out on hover/focus/dialog transitions only. No entrance animations, no stagger reveals, no page transitions. `prefers-reduced-motion` respected.
- Microcopy rules (usability-first): control labels state exactly what happens ("Add company", "Save application", never "Submit"); errors say what failed and how to recover, no apologies; empty states are invitations with the primary action inline ("No companies yet. Add the first one your squad should apply to."); vocabulary is consistent across screens (application, squad, portal, board).

### Routing and screens
- `/auth`: split screen. Left: brand panel (wordmark "JobSquad", tagline "The multiplayer job hunt", 3 value props). Right: sign-in / create-account toggle. **Social buttons first** ("Continue with Google / GitHub / LinkedIn", rendered only for providers in `/api/auth/config`, each with its brand mark, neutral Worklight styling: paper bg, 1px line border, ink text, brand logo as the only color), then a "or" hairline divider, then the email form. **No username field anywhere.** Create account collects display name, email, password; when `otp_required` it becomes a 2-step flow (send code -> 6-digit code entry with resend countdown). On success store token, redirect to `/`.
- `/auth/callback`: handles the OAuth return. Reads `#token=` from the fragment, stores it, `history.replaceState`s the fragment away, resolves the session, redirects to `/` (or the saved deep link). On `#error=` shows the matching message on the auth screen (e.g. `email_unverified` -> "That account's email is not verified with the provider. Use email signup instead.").
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

## 9b. Resume feature (added 2026-07-30; built in three gated phases)

Delivery process for this feature: implementation agents -> adversarial verifier agent per phase -> orchestrator browser test -> **user tests locally -> only then push** (pushing main auto-deploys the live site). Local commits allowed at each phase boundary; no push without the user's explicit green signal.

Product decisions: PDF is the default upload format (general users); `.tex` is first-class for tailoring (developers); DOCX accepted for storage/analysis. AI tailoring NEVER invents facts (rephrase/reorder only, contact details untouched). No auto-submit to ATS portals ever; the "apply kit" replaces it. AI is strictly BYOK (each user's own free key); provider abstraction is OpenAI-compatible (Gemini default, Groq preset, custom base URL).

### Phase R1 - Resume vault + attachment + outcome stats (no AI, no new services)

Data:
- **resumes**: id PK, user_id FK users CASCADE, label TEXT NOT NULL (<=80), filename TEXT, kind TEXT ('pdf'|'tex'|'docx'), content_type TEXT, size_bytes INT, data (LargeBinary), extracted_text TEXT NULL, source_tex TEXT NULL (R3), created_at, updated_at. Guards: max 2 MB/file, max 10 resumes/user.
- **applications.resume_id** BIGINT NULL FK resumes ON DELETE SET NULL.
- Migration MUST be idempotent on EXISTING databases, both dialects: SQLite (existing PRAGMA-based block) AND Postgres (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`; new tables come from create_all). The live Neon DB must survive this deploy.

API (`routers/resumes.py`):
- `POST /api/resumes` multipart {label, file} -> Resume `{id, label, filename, kind, size_bytes, created_at, attached_count}`. Kind by magic bytes (%PDF, PK zip for docx) + extension for .tex; 413/422 on size/type/count violations.
- `GET /api/resumes` -> mine, with attached_count.
- `PATCH /api/resumes/{id}` {label} · `DELETE /api/resumes/{id}` (FK sets applications.resume_id NULL; UI warns when attached).
- `GET /api/resumes/{id}/file` -> bytes, `Content-Disposition: inline`, correct content type, `X-Content-Type-Options: nosniff`. AuthZ: owner, OR a user who shares a group in which this resume is attached to an application (squad visibility mirrors the notes philosophy; unattached resumes are private). In-app viewing uses fetch-with-Bearer + blob URL (the `?access_token=` allowlist does NOT widen).
- `GET /api/resumes/stats` -> per my resume: {resume_id, label, applications, interviews (assessment+interview), offers, rejected, ghosted}.
- Application PUT accepts `resume_id` (merge semantics; must be my resume -> 422 otherwise). ApplicationFull/Brief gain `resume_id, resume_label`.

Frontend: sidebar item "Resumes" (route `/g/:gid/resumes`, user-scoped data): upload (picker + label), list rows (label, kind badge in mono, size, date, attached-to count, outcome mini-stats), inline rename, delete with confirm, view (blob, new tab). "My application" editor gains a "Resume used" select + view link. Squad status cards show the attached resume as a small chip (viewable when permitted).

### Phase R2 - JD capture + deterministic match report (no LLM)

- Deps: `pypdf`, `python-docx`. Extraction at upload (pdf/docx/tex-stripped); lazy backfill for pre-existing rows on first match request.
- **applications.jd_text** TEXT NULL (<=50,000 chars), settable via the application PUT (merge).
- `backend/app/skills.py`: curated canonical->aliases dictionary (~250 entries: languages, frameworks, infra, data, soft skills; aliases like k8s/kubernetes, js/javascript, gcp/google cloud).
- `GET /api/applications/{id}/match` (my application only) -> `{jd_skills: [{skill, present}], coverage, missing, resume_id, resume_label}`; 409 when jd_text or attached resume missing (message says which).
- Frontend: collapsible "Job description" textarea in My application editor; Match panel: coverage bar + present chips (offer green) / missing chips (interview amber), copy-missing button, honest empty states.

### Phase R3 - BYOK AI tailoring + LaTeX compile + share links + apply kit

- Deps: `cryptography` (Fernet, key derived from app secret) for at-rest encryption of user AI keys. **Tectonic engine: NOT installed in the production image (decision 2026-07-31).** Local dev uses `TECTONIC_PATH` or PATH discovery; the compile endpoint returns 501 with a clear message when absent, and the frontend falls back to a `.tex` download for Overleaf. Rationale: Render's free tier has an ephemeral disk, so Tectonic's TeX package cache re-downloads on every restart (slow, needs network); shipping without it keeps the image lean and the live app exposes zero untrusted-LaTeX surface. Server-side compile is a one-flag enable later, but ONLY behind an OS sandbox (see the security note below). **LaTeX-compile security (verified against the real Tectonic 0.17 binary):** `--untrusted` + `TECTONIC_UNTRUSTED_MODE=1` block shell-escape/RCE but do NOT block absolute-path `\input`, so a pre-compile denylist in `latex.py` rejects file-io LaTeX commands (`\input`, `\include`, `\openin`, `\read`, `\write`, `\catcode`, `\csname`, `\includegraphics`, ... comment-stripped, escaped-`\%` aware) with a 422 before Tectonic runs. Confirmed live: `\input{data/.secret}` and absolute-path reads are blocked; a clean resume still compiles. The denylist is defense-in-depth; full safety for enabled server-side compile requires OS-level sandboxing (container/read-only FS/seccomp). A compile concurrency semaphore (2) bounds simultaneous 60s runs.
- **user_ai_settings**: user_id PK FK CASCADE, provider ('gemini'|'groq'|'custom'), base_url TEXT, model TEXT, key_encrypted TEXT, updated_at. Presets: gemini -> `https://generativelanguage.googleapis.com/v1beta/openai/` model `gemini-2.5-flash`; groq -> `https://api.groq.com/openai/v1` model `llama-3.3-70b-versatile`; model always user-editable. One OpenAI-compatible chat client (httpx, 60s timeout).
- **resume_shares**: id PK, resume_id FK CASCADE, token TEXT UNIQUE (32 hex, `secrets`), created_at, revoked BOOL. `POST /api/resumes/{id}/share` -> {url: `{public_url}/r/{token}`} (owner only, pdf kind only); `DELETE /api/resumes/{id}/share`; public `GET /r/{token}` serves the PDF inline, 404 when revoked/unknown.
- Settings API: `GET/PUT /api/settings/ai` (key masked on read, blank keeps), `POST /api/settings/ai/test` (minimal chat call, returns ok/error text).
- `POST /api/applications/{id}/tailor` {resume_id} -> tex kind: `{kind:"tex", tailored_tex, changes:[summary strings]}`; pdf/docx: `{kind:"advice", suggestions:[{section, original, suggested, reason}], keywords_to_add}`. System prompt hard-constrains: no invented employers/titles/dates/skills, contact block untouched, edits limited to rephrasing/reordering/emphasis. 409 without jd/resume/settings (message says which).
- `POST /api/resumes/compile` {tex_source, label} -> tectonic in a temp dir (subprocess list-args, no shell, 60s timeout, stderr captured) -> stores result as a NEW resume row (kind pdf, source_tex retained) -> Resume json.
- Frontend: AI settings panel (provider dropdown, key, model, custom base URL, test button, privacy line: "Your resume and this job description are sent to the AI provider you configure. Free tiers may use data for training."); Tailor button on my application (needs resume + JD): tex -> before/after view + "Compile to PDF" -> new version auto-attached; pdf/docx -> suggestion cards with per-item copy. Apply kit button (needs posting URL + attached resume): opens posting, ensures+copies share link, bumps status to applied when still saved/none. Loading states for 10-30s calls; errors surfaced verbatim.

### Resume tailoring best practices (researched 2026-07-30; these are REQUIREMENTS for R2/R3, not suggestions)

Sources: 2026 ATS guides (Workday/Greenhouse/Lever parser behavior), LLM-anti-hallucination prompt research, and the open-source tailoring ecosystem (resume-lm, llmresume - the latter validates our exact tex+Groq+deterministic-fallback shape). Findings that shape the build:

1. **Keyword stuffing is PENALIZED, not rewarded.** Workday's 2026 model flags unnatural density (a term repeated ~15x). Context beats frequency: one quantified bullet ("led a $12M migration across 4 teams") outscores five bare repetitions. So R2 must NOT tell users to cram; R3 must be told to integrate a missing keyword in at most a few NATURAL places, never repeat for density.
2. **Keyword LOCATION is weighted.** Terms in the summary and the FIRST bullet under a role count more than ones buried at the end. R3 should place a genuinely-held missing skill in up to 3 natural spots: the skills block, the relevant role, and a bullet that proves it.
3. **Invisible-text / white-on-white keyword injection = FRAUD FLAG -> auto-reject with a permanent marker** on Workday/Greenhouse/Lever. R3 must NEVER produce hidden text, zero-opacity, or off-page keywords, and the UI must warn against manual attempts. This is a hard safety rule in the system prompt.
4. **ATS-parseable format** (for the offered LaTeX starter template AND the advice given to PDF users): single column, standard section headers (Work Experience / Education / Skills), no tables/columns/text-boxes/images/icons, sans-serif 10-11pt, dates as "MMM YYYY - MMM YYYY" (Workday needs MM/YYYY, fails on seasonal), text-based PDF. No critical text in headers/footers.
5. **Mirror the JD's exact terminology only when the user genuinely has the skill** (e.g. rewrite "prompt tuning" -> "prompt optimization" if the JD uses the latter). The R2 skills dictionary's alias map already models this; R3 uses it to align wording, never to claim a skill not present.
6. **Bullets: STAR/quantified, strong action verbs, outcomes with numbers.** R3 rephrasing improves weak bullets toward this shape using ONLY facts already in the resume; it may not invent metrics. If a bullet has no number, it stays qualitative rather than getting a fabricated one.
7. **Anti-hallucination prompt structure** (research-backed): give the model explicit permission to abstain - a JD requirement the resume does not support is reported as a GAP ("consider adding X if you have it"), never silently written in. Chain-of-thought before edits. Contact block frozen. The user is the final quality gate and every change is shown as a reviewable diff before it is accepted.
8. **The application form matters as much as the file.** ATS recruiters search structured field values, so the apply-kit UI must remind the user to fill every field in the portal (especially Skills) even after uploading, and note Workday's strict MM/YYYY dates.
9. **Coverage target, not perfection**: aim the match report at "70+ is good, 80+ excellent" framing rather than implying 100% is the goal (100% coverage reads as stuffing). Present missing items as opportunities, flagged honestly as "only add if true".

These turn R2 from a naive keyword-coverage meter into an honest "natural alignment + gaps" report, and R3 from a keyword-crammer into a constrained editor. The verifier for R3 must confirm the system prompt encodes points 1, 3, 5, 6, 7 verbatim in intent.

### Verifier gates (each phase)

A separate adversarial agent verifies before I browser-test: contract conformance against this section; authz on every new route (resume file access matrix, cross-group 404s, share-token scope); upload hardening (magic-byte checks, size caps, nosniff, filename handling); migration idempotence on EXISTING SQLite and Postgres databases with data; R3: subprocess injection surface, key encryption at rest, prompt-constraint presence, share-token entropy/revocation; test coverage of all the above; em-dash sweep. Findings fixed before the phase closes.

## 9c. Group management (added 2026-07-31; Phase G1)

Product decisions (frozen): **invite code = instant join always** (public or private - having the code means you were invited, no approval). **Public group = discoverable in a directory + request-to-join, owner approves/rejects.** **Private group = not discoverable, code-only** (never leaks: a non-member hitting a private group's endpoints gets 404, not 403). Default visibility = **private** (matches current behavior). Roles stay owner/member.

Data:
- **groups.visibility** TEXT NOT NULL DEFAULT 'private' ('private'|'public'); **groups.description** TEXT NULL (max 280 chars; shown in the discover directory). Idempotent dual-dialect migration mirroring resume_id/jd_text/region; safe against live Neon rows (existing groups default to private).
- **group_join_requests**: id PK, group_id FK groups CASCADE, user_id FK users CASCADE, status TEXT ('pending'|'approved'|'rejected') default 'pending', created_at, decided_at NULL, decided_by NULL FK users; partial-unique so a user has at most one PENDING request per group (enforce in code: reject a second pending). Index(group_id, status).

API (all group-scoped routes keep the 404-for-non-member / 404-for-private rule; owner-only actions 403 for a non-owner member):
- `PATCH /api/groups/{gid}` (owner) extends to accept `visibility` and `description` alongside `name` (merge semantics). Switching to private does not drop existing members; pending requests on a now-private group are left but no longer reachable via discover.
- `GET /api/groups/discover?q=&limit=&offset=` -> public groups the caller is NOT already a member of, with `{id, name, description, member_count, request_status}` where request_status is `none|pending` for the caller. `q` matches name/description. Never lists private groups.
- `POST /api/groups/{gid}/request` -> create a pending join request for a PUBLIC group (404 if private/unknown; 409 if already a member or already pending; idempotent-friendly). Records activity `join_requested`.
- `GET /api/groups/{gid}/requests` (owner) -> pending requests `[{id, user_id, username, display_name, created_at}]`.
- `POST /api/groups/{gid}/requests/{req_id}/approve` (owner) -> adds the user as a member (role member), marks request approved, records `member_joined`; idempotent if already a member. `POST .../reject` (owner) -> marks rejected, no membership.
- `DELETE /api/groups/{gid}/members/{user_id}` (owner) -> remove a member. Cannot remove the owner or yourself via this route (owner uses leave rules); deletes that user's applications + portal statuses in the group (same cleanup as leave); records activity. 
- `POST /api/groups/{gid}/regenerate-invite` (owner) -> issues a fresh unique invite_code, returns the group. Old code stops working immediately.
- `Group`/`GroupDetail` shapes gain `visibility`, `description`, and (owner only, else omitted/0) `pending_request_count`. `GroupDetail.members` already carries roles.

Frontend:
- Sidebar nav gains a **"Groups"** item -> the group hub at `/` (replaces relying on the user-menu "Switch group"). The hub has: **My groups** (cards with name, visibility chip, member count, invite-code copy), **Discover** (public directory with search + a Request-to-join button that flips to "Requested"), and the existing **Create** (now with a private/public segmented toggle + an optional description field) and **Join with code** actions.
- Per-group **Members** view (route `/g/:gid/members`, linked from the sidebar or group header): everyone sees the roster (avatars, names, roles). The **owner** additionally sees: a visibility toggle + editable description, a **pending requests** list with Approve/Reject (and a count badge on the nav), **Remove** on each member, and a **Regenerate invite code** action with a confirm ("the old code stops working"). Non-owners see the roster read-only.
- Honest microcopy, loading/empty/error states, tokens-only styling, no em-dash.

Non-goals for G1 (parked): co-owner/admin role, per-request messages, email notifications of requests.

### Phase G2 - Transfer ownership (added 2026-07-31)

Why: an owner currently cannot leave a group that has other members, which is a dead end. Transfer is the unblock.

Decisions (frozen): **immediate transfer, no acceptance step** (the recipient is already a trusted member; a pending-accept state machine is not worth it for a rare action) and **only to an existing member** of that group (never a pending requester, never by email). The action is irreversible by the old owner alone, so the UI puts it behind a strong confirm.

- `POST /api/groups/{gid}/transfer-ownership` body `{new_owner_id: int}` -> returns the updated `GroupDetail`. Owner only (403 for a member, 404 for a non-member, same no-leak discipline). Errors: 400 transferring to yourself ("You already own this group."); 404 when `new_owner_id` is not a member of this group (do not leak whether the user exists at all). In ONE transaction: set `groups.owner_id = new_owner_id`, set the new owner's `group_members.role = 'owner'`, and demote the old owner's row to `'member'`. Records activity `ownership_transferred` with `detail = {"new_owner_id", "new_owner_name", "previous_owner_id", "previous_owner_name"}`.
- The owner-cannot-leave-while-others-remain rule STAYS (transfer is the intended path out), but its 400 message becomes: "Transfer ownership to another member first, then you can leave."
- Frontend: on the Members page, owner-only "Transfer ownership" control - a member picker (existing members except me) plus a ConfirmDialog: title "Transfer ownership to {name}?", body "{name} becomes the owner and you become a regular member. Only the new owner can transfer it back.", button "Transfer ownership". On success, invalidate the group so the demoted owner's controls disappear immediately. Frontend `ActivityType` gains `ownership_transferred` with the sentence "made {new_owner_name} the owner" (fallback "transferred ownership").

Verifier focus for G2: only the owner can transfer (member 403, non-member 404); transfer to a non-member or to self is rejected; the swap is atomic (owner_id and BOTH role rows consistent, no window with two owners or none); after transfer the old owner has exactly member powers (no approve/remove/regenerate/transfer) and the new owner has full owner powers; the previously-blocked owner-leave now works after transferring; activity detail names both parties.

Verifier focus for G1: private groups never appear in discover and 404 (not 403) for non-members on every route; only the owner can PATCH visibility/description, view/approve/reject requests, remove members, regenerate the code; request flow can't create duplicate pending rows or let a member re-request; remove-member cleans up that user's data like leave; regenerate-invite actually invalidates the old code; migration idempotent + non-destructive on populated SQLite AND Postgres (existing groups become private).

## 9d. Browser extension (Phase E1; added 2026-07-31)

Why: data-entry fatigue is what kills job trackers. The extension is also a BETTER scraper than any server-side one (it reads a page the user legitimately opened, works behind LinkedIn/Workday logins, costs nothing, no IP bans, far less ToS exposure). Server-side scraping stays out of scope. **The extension is free for every user; it is not a paid tier.**

It is also the missing input pipe for shipped features: the captured job description feeds the R2 match report and R3 tailoring, and the captured source domain feeds portal-effectiveness stats.

### Decisions (frozen)
- **Primary action = capture the CURRENT page** (toolbar click or Ctrl+Shift+J). Right-click a link is the secondary path.
- **Never silently save.** The popup always shows extracted fields, editable, with one confirm click. Wrong data destroys trust faster than friction does.
- **Extraction order:** (1) `schema.org/JobPosting` JSON-LD (most boards emit it for Google Jobs), (2) site rules for LinkedIn, Indeed, Workday, Greenhouse, Lever, (3) generic fallback (title + meta + main text). Always user-editable.
- **Auth = pairing flow** (works for OAuth users, unlike an in-extension password form).
- E1 permissions stay minimal: `storage`, `activeTab`, `scripting`, `contextMenus`, and host permissions ONLY for the app origins. No job-board host permissions until E2.

### Pairing protocol (exact)
1. Extension popup (unpaired) opens `{public_url}/connect` in a tab.
2. That page (user already logged in) POSTs `/api/auth/extension-token` and receives the token ONCE.
3. Page calls `window.postMessage({source:"jobsquad-app", type:"extension-token", token, api_base}, window.location.origin)`.
4. The extension content script on `/connect` accepts it ONLY when `event.source === window` AND `event.origin === location.origin` AND `data.source === "jobsquad-app"`, then forwards to the service worker, which stores it in `chrome.storage.local`.
5. Content script posts back `{source:"jobsquad-extension", type:"paired"}`; the page shows "Extension connected".
This needs no `externally_connectable` and no hardcoded extension id, so unpacked-dev and store builds both work.

### Backend
- **extension_tokens**: id PK, user_id FK CASCADE, jti TEXT UNIQUE NOT NULL, label TEXT NULL, created_at, last_used_at NULL, revoked BOOL default false. Index(user_id).
- Extension JWTs carry `{sub, exp, typ:"ext", jti}` with TTL 365 days. `get_current_user` additionally accepts `typ=="ext"` only when the jti row exists and is not revoked; it bumps `last_used_at` at most once per hour (avoid a write per request). Session tokens are unchanged (no `typ` claim).
- **Lateral-movement guard:** an extension token is REJECTED (401) on the extension-token management routes themselves, so a stolen extension token cannot mint or manage more tokens.
- `POST /api/auth/extension-token` (session token only) -> `{token, id, created_at}` (token returned once, never again). `GET /api/auth/extension-tokens` -> `[{id,label,created_at,last_used_at}]` (never the token). `DELETE /api/auth/extension-tokens/{id}` -> revoke.
- `POST /api/capture` (group-scoped, member only) body `{group_id, company_name, company_website?, careers_url?, location?, posting_url?, jd_text?, status?}` -> in ONE transaction: find-or-create the company (case-insensitive normalized name match within the group, also matching on website registrable domain, so the extension never creates duplicate companies), find-or-create the portal from the posting URL's domain (known map: linkedin.com->LinkedIn, indeed.com->Indeed, glassdoor->Glassdoor, wellfound.com->Wellfound, bayt.com->Bayt, rozee.pk->Rozee, *.myworkdayjobs.com->Workday, greenhouse.io->Greenhouse, lever.co->Lever; otherwise the registrable domain), then upsert MY application with merge semantics (`status` default `saved`, plus `url`, `jd_text`, `applied_via_portal_id`). Returns `{company_id, company_name, application_id, status, created_company, created_portal, portal_name}` so the popup can say "Added TechCorp" vs "Updated your application".
- `GET /api/capture/lookup?group_id=&url=&company_name=` -> `{company_id|null, company_name|null, my_status|null, squad:[{display_name,status}]}` so the popup shows "Ali: rejected" BEFORE you save. Member-only, 404 for a non-member group.

### Web app
- Route `/connect`: explains the extension, a "Connect extension" button running the pairing protocol, and a connected/failed state (with a clear message when the extension is not installed, i.e. no `paired` reply within ~3s).
- AI-settings-style panel entry "Connected extensions": list (label, created, last used) with Revoke, wired to the two management endpoints.

### Extension (repo folder `extension/`, plain HTML/CSS/JS, Manifest V3, no build step so it loads unpacked)
```
extension/manifest.json
extension/background.js      service worker: context menu, Ctrl+Shift+J command, token storage, API calls
extension/content/extract.js injected on demand via scripting.executeScript (activeTab), returns extracted fields
extension/content/connect.js content script on {app}/connect only, runs the pairing handshake
extension/popup/popup.html|css|js  capture card (editable fields, group picker, squad-status line, Save)
extension/icons/16|32|48|128.png   reuse the app icon (white dot in a green ring on the dark tile)
```
- Popup styling uses the Worklight dark values directly (hex is fine here; the app's CSS variables do not reach the extension).
- API base defaults to `https://jobsquad.dpdns.org`, overridable in the popup for local dev against `http://localhost:8100`; both in `host_permissions`.
- Unpaired popup shows only a "Connect to JobSquad" button. Paired popup: extracted title/company/location/URL (editable), group picker (remembers last used), status select (default Saved), the lookup line ("Ali applied here - rejected") when the company is known, and Save. Errors surfaced verbatim; never save silently.

### E1 addendum: applications carry a job title (2026-07-31)
Capture surfaces the role title, which had nowhere to live (applications tracked a company, not the role). Add **applications.job_title** TEXT NULL (max 200, trimmed, blank -> null), idempotent dual-dialect migration like resume_id/jd_text/region. Accepted by the application PUT (merge semantics) and by `POST /api/capture`; included in ApplicationFull and ApplicationBrief. The web app shows it in the My-application editor and on squad status cards; the board card shows it under the company name when present. This also makes "which role did I apply for at this company" answerable, which the product could not express before.

### Verifier focus for E1
Pairing message validated on origin+source+shape (a hostile page must not be able to hand the extension a token, and a hostile page must not be able to read it); extension token revocation actually blocks use; extension tokens rejected on the token-management routes; `/api/capture` cannot write into a group the caller is not a member of (404) and cannot create duplicate companies on repeat capture of the same posting; jd_text respects the 50k cap; lookup leaks nothing for non-members; `activeTab`/`scripting` used instead of broad host permissions; no secrets logged; no em-dash.

### Phase E2 - squad awareness on job boards (added 2026-07-31)

The multiplayer differentiator: your squad's memory appears where the decision is made (the job board), not in a separate app you must remember to open.

**Permission model (frozen, non-negotiable):** job-board access is **opt-in via `optional_host_permissions`**, never in the install-time manifest. The extension ships requesting nothing beyond E1; turning badges on in the popup triggers `chrome.permissions.request` for the boards, and turning it off calls `chrome.permissions.remove`. Rationale: "read your data on LinkedIn" at install is a privacy downgrade and a store-review magnet for a feature many users will not use.

- Optional origins: `https://*.linkedin.com/*`, `https://*.indeed.com/*`. Content script registered dynamically (`chrome.scripting.registerContentScripts`) only while the permission is held, and unregistered on revoke.
- Badge script: scans the results list, extracts each row's company name, batches them to the API, and injects one small chip per row showing the squad's standing ("Ali - rejected", "You - applied"). Rows with nothing known get no chip (silence is the default; never clutter). Re-scans on DOM mutation (boards are SPAs) with a debounce, and marks processed rows so it never double-injects. Injected DOM uses textContent only, is namespaced with a `jobsquad-` class prefix, and never blocks or alters the page.
- Backend: `POST /api/capture/lookup/batch` body `{group_id, companies: [string]}` (max 50 per call, dedup server-side) -> `{results: [{query, company_id|null, company_name|null, my_status|null, squad:[{display_name,status}]}]}`. Member-only, 404 for a non-member, same normalized-name matching as `/api/capture/lookup`. Added to the extension-token allowlist.
- Popup gains a "Show squad status on job boards" toggle reflecting the live permission state.

### Phase E3 - submit detection (added 2026-07-31)

After you actually submit an application, the extension offers to move that company to Applied, so the board stays true with no effort.

- Same **optional permission** model, separate toggle: optional origins `https://*.greenhouse.io/*`, `https://*.lever.co/*`, `https://*.myworkdayjobs.com/*`.
- Detection is conservative and never automatic: watch for a submit-confirmation signal (a known success URL fragment or a confirmation heading such as "Application submitted" / "Thank you for applying"). On a hit, show a small in-page prompt (not a silent write) offering "Mark {company} as applied in JobSquad". Only on click does it call `POST /api/capture` with `status: "applied"`. If the company is unknown to the group it captures it as well.
- Never touches form fields, never submits anything, never reads entered values. Explicitly still out of scope: ATS autofill (a permanent per-site maintenance treadmill and effectively a separate product) and email parsing.

### E1 correction: right-click on a link
Chrome's `activeTab` does not extend to a tab the extension itself opened, so the "open the link then extract" path cannot read the page. Make it honest instead of broken: right-clicking a link captures with the URL prefilled and clearly states that only the link was read, pointing at Ctrl+Shift+J on the opened page for full extraction. README updated to match.

## 10. Non-goals (v1)

Email/password reset, avatar uploads, push/mobile notifications, roles beyond owner/member, group deletion or member removal, multi-language, dark theme, SSR, offline. All fine later; nothing in v1 blocks them.

## 11. Decisions log

- **Application notes are visible to the whole group.** That is the product's point (shared experience). The UI labels them "visible to your group".
- **SQLite over Postgres/Supabase:** no accounts or services needed to run today; single-file backup; portable SQL keeps the Postgres door open.
- **Single-port serving** (API + built SPA) keeps LAN sharing and deployment one-process simple; Vite dev mode stays available for development.
- **Registration hardening (2026-07-30, user request):** bots are the concern once the app is public, so signup is now either **social OAuth** (Google/GitHub/LinkedIn - the provider has already vetted the human) or **email with a 6-digit OTP**. Both are **config-gated**: with no mail transport and no OAuth credentials (the default LAN case) plain email signup still works instantly, so nothing about the home Wi-Fi flow regresses. **Usernames are never chosen by users** - the server derives a handle - because a username field is friction that buys nothing when email is the identifier.
- **Mail transport: Resend HTTP API preferred, SMTP fallback.** Resend needs one API key and no port/TLS wrangling, has a usable free tier, and works from hosts that block outbound SMTP (most PaaS). SMTP stays supported for self-hosters. `httpx` becomes a runtime dependency (needed for OAuth token exchange anyway).
- **OAuth token returns in the URL fragment**, never the query string: fragments are not sent to the server, so the session token cannot land in access logs, proxy logs, or the Referer header.
- Ports 8100/3100 chosen to avoid colliding with the user's other project (8000/3000).
- **Design pivot (2026-07-29, user request):** the original dark "NightShift" theme was replaced by the light "Worklight" system above, following the Anthropic frontend-design skill: dark-bg-plus-single-bright-accent is a generic AI default; a professional daily-use tool wants a monochrome ink interface where color only encodes status meaning, usability-first microcopy, and minimal motion.
- **Adversarial-review hardening (2026-07-29):** last-member leave is blocked (no code path may destroy group data); leave deletes the leaver's applications/portal statuses; upsert/join races handle IntegrityError instead of 500ing; CSV cells starting with `= + - @` TAB CR are quote-prefixed (formula-injection guard); `?access_token=` is scoped to SSE + exports and redacted from access logs; PBKDF2 runs off the event loop with a per-user+IP login throttle (429); JWT base64 decoding is strict; `data/.secret` is written 0600; SSE queues are bounded (500) and re-check membership per event; company search escapes LIKE wildcards; request bodies capped (1 MB + field length limits); user-supplied URLs render through a `safeHref` http/https allowlist. Known accepted v1 limits: SSE publish happens just before commit (harmless: clients reconcile on refetch), no pagination on activity beyond `limit`, archived companies have no UI control yet.
