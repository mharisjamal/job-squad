# Deploying JobSquad

The chosen path: **Render** runs the app as a Docker web service, **Neon** holds the Postgres database, an **is-a.dev** subdomain gives it a clean name, and **UptimeRobot** pings it so the free instance stays awake. Total cost: nothing.

Local and LAN use is unchanged and needs no configuration: with no `DATABASE_URL` set, JobSquad uses SQLite at `data/jobsquad.db` exactly as before. Run `START.bat` and ignore this whole document.

---

## 1. Create the database (Neon)

1. Sign up at [neon.tech](https://neon.tech) (free tier, no card) and create a project. Any region works; pick one near your users.
2. Open **Connection Details** and copy the **Pooled connection** string. It looks like:

   ```
   postgresql://USER:PASSWORD@ep-something-123456-pooler.REGION.aws.neon.tech/neondb?sslmode=require&channel_binding=require
   ```

   Use the **pooled** one (the host contains `-pooler`). Neon's free tier suspends idle databases and the pooler handles reconnects far better.

You do not need to create any tables. The app creates its schema on first boot.

## 2. Create the web service (Render)

1. Push this repo to GitHub, then at [render.com](https://render.com): **New +** -> **Web Service** -> connect the repo.
2. Settings:

   | Setting | Value |
   |---|---|
   | Language / Runtime | **Docker** |
   | Branch | `main` |
   | Region | same continent as your Neon project |
   | Instance type | **Free** |
   | Dockerfile path | `./Dockerfile` |
   | Health check path | **`/health`** |

   The repo also contains `render.yaml`, so you can instead use **New +** -> **Blueprint** and let Render read those settings itself. Either way the environment variables below are still pasted by hand.

3. Add the environment variables (**Environment** tab):

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the pooled Neon string from step 1 |
   | `JOBSQUAD_SECRET` | a long random string (Render's **Generate** button is fine) |
   | `JOBSQUAD_PUBLIC_URL` | your final URL, e.g. `https://jobsquad.is-a.dev` |

   Optional, only if you want those features:

   | Key | Purpose |
   |---|---|
   | `JOBSQUAD_RESEND_API_KEY` + `JOBSQUAD_MAIL_FROM` | email-OTP signup (turns registration into verify-by-code) |
   | `JOBSQUAD_GOOGLE_CLIENT_ID` / `_SECRET` | "Continue with Google" |
   | `JOBSQUAD_GITHUB_CLIENT_ID` / `_SECRET` | "Continue with GitHub" |
   | `JOBSQUAD_LINKEDIN_CLIENT_ID` / `_SECRET` | "Continue with LinkedIn" |

   Do **not** set `PORT`: Render injects it and the container binds it automatically.

4. Deploy. The first build takes a few minutes (it builds the frontend, then installs Python dependencies). When the health check at `/health` goes green, open the `onrender.com` URL.

`JOBSQUAD_SECRET` must stay stable: changing it signs everyone out, because it signs the session tokens.

## 3. Point a free domain at it (is-a.dev)

[is-a.dev](https://is-a.dev) hands out free `yourname.is-a.dev` subdomains by pull request.

1. In Render: **Settings** -> **Custom Domains** -> add `jobsquad.is-a.dev`. Render shows a target host like `jobsquad-xxxx.onrender.com`.
2. Fork [is-a-dev/register](https://github.com/is-a-dev/register), add `domains/jobsquad.json`:

   ```json
   {
     "owner": { "username": "your-github-username", "email": "you@example.com" },
     "record": { "CNAME": "jobsquad-xxxx.onrender.com" }
   }
   ```

   Open the pull request and wait for it to merge (usually a day or two).
3. Once DNS resolves, Render issues the TLS certificate on its own. Then set `JOBSQUAD_PUBLIC_URL` to `https://jobsquad.is-a.dev` and redeploy, so OAuth redirect URIs point at the real domain.

If you enabled social sign-in, register these callback URLs with each provider:

```
https://jobsquad.is-a.dev/api/auth/oauth/google/callback
https://jobsquad.is-a.dev/api/auth/oauth/github/callback
https://jobsquad.is-a.dev/api/auth/oauth/linkedin/callback
```

## 4. Keep it awake (UptimeRobot)

Render's free instances sleep after about 15 minutes idle, and the next visitor waits roughly 50 seconds for a cold start.

1. Sign up at [uptimerobot.com](https://uptimerobot.com) (free).
2. **Add New Monitor**: type **HTTP(s)**, URL `https://jobsquad.is-a.dev/health`, interval **5 minutes**.

`/health` needs no authentication and only pings the database, so it is cheap to call. This also gives you email alerts when the app goes down.

Note: Render's free plan has a monthly instance-hours budget. Pinging around the clock consumes it faster than idling does; if you run out before month end, raise the interval or pause the monitor overnight.

---

## Backups

State lives in Postgres now, so back up the Neon database.

- **Dump** (needs the `postgresql-client` package locally, version 16 or newer):

  ```bash
  pg_dump "postgresql://USER:PASSWORD@ep-something-pooler.REGION.aws.neon.tech/neondb?sslmode=require" \
    -Fc -f jobsquad-backup.dump
  ```

  Use the connection string exactly as Neon gives it (with `sslmode=require`); `pg_dump` understands those parameters even though the app strips them for asyncpg.

- **Restore** into an empty database:

  ```bash
  pg_restore --clean --if-exists -d "postgresql://.../neondb?sslmode=require" jobsquad-backup.dump
  ```

- Neon's own console also offers point-in-time restore on the free tier (a rolling window of a few days). That covers "I deleted the wrong thing" without any dump.

**Running locally instead?** Then state is still the single file `data/jobsquad.db` (plus `data/.secret` if you never set `JOBSQUAD_SECRET`). Stop the app and copy the file, or take a live consistent snapshot:

```bash
sqlite3 data/jobsquad.db ".backup jobsquad-backup.db"
```

Restore by putting the file back as `data/jobsquad.db` while the app is stopped.

## Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | unset | Postgres URL. **Unset means local SQLite** at `JOBSQUAD_DB_PATH` |
| `PORT` | unset | Injected by Render; the server binds it |
| `JOBSQUAD_PORT` | `8100` | Port when `PORT` is not set |
| `JOBSQUAD_DB_PATH` | `data/jobsquad.db` | SQLite file (ignored when `DATABASE_URL` is set) |
| `JOBSQUAD_SECRET` | auto-generated to `data/.secret` | Signs session tokens. Always set this in a real deployment |
| `JOBSQUAD_TOKEN_TTL_HOURS` | `168` | Session lifetime |
| `JOBSQUAD_PUBLIC_URL` | `http://localhost:8100` | Public base URL; builds OAuth redirect URIs |

These can also live in a `.env` file at the repo root or in `backend/`, which is handy locally. Real environment variables always win over the file, so a stray `.env` can never override what you set in Render. Never commit `.env`: it is gitignored.

## Running the container yourself

The same image works anywhere Docker does:

```bash
docker build -t jobsquad .
docker run -p 8100:8100 -e DATABASE_URL="postgresql://..." -e JOBSQUAD_SECRET="..." jobsquad
```

Without `DATABASE_URL` it falls back to SQLite inside the container, in which case mount a volume at `/app/data` or the data disappears with the container.

## Alternatives

If you would rather not depend on a host at all, two options that were considered and still work:

- **LAN only**: run `START.bat`, allow Python through Windows Firewall, and share the Network URL the launcher prints. Free, private, and only reachable from your own Wi-Fi while your machine is awake.
- **Cloudflare Tunnel** from an always-on home PC: `cloudflared tunnel --url http://localhost:8100` gives an HTTPS URL without opening router ports, and a named tunnel gives a stable hostname. Data stays on your machine in SQLite.

## AI resume tailoring and LaTeX compile

The AI tailoring feature is bring-your-own-key: each user pastes their own free Gemini or Groq key in AI settings. The server never holds its own key, and every user key is encrypted at rest (Fernet, derived from `JOBSQUAD_SECRET`). Set `JOBSQUAD_SECRET` to a stable value in production or stored keys become undecryptable after a restart.

Server-side LaTeX-to-PDF compile is intentionally OFF in the deployed image. When Tectonic is not present the compile endpoint returns 501 and the app offers a `.tex` download to compile on Overleaf, which is the recommended flow. Reason: on an ephemeral-disk host (like Render free) Tectonic re-downloads its TeX package cache on every restart, and running untrusted LaTeX server-side is a security surface.

If you do enable server-side compile (install Tectonic and set `TECTONIC_PATH`), only do so behind an OS sandbox (a locked-down container with a read-only filesystem and no access to `data/.secret` or the database). The app already runs Tectonic with `--untrusted` (blocks shell-escape) plus a denylist that rejects file-input LaTeX commands (`\input`, `\openin`, `\read`, `\write`, `\catcode`, ...), but that is defense-in-depth, not a substitute for a sandbox.
