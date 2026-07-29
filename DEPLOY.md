# Deploying JobSquad

JobSquad is one process listening on one port (default 8100) with all state in `data/`. Every option below boils down to: get that process running somewhere your friends can reach.

Options are ordered by effort. For a group of friends, Option A or C is usually right.

## Option A: LAN only (the default)

Nothing to configure.

1. Run `START.bat` (or `python run.py`).
2. When Windows Firewall asks about Python (and Node in dev mode), click **Allow**.
3. The launcher prints two URLs. You use the Local one; everyone else on the same Wi-Fi uses the **Network** one, for example `http://192.168.1.23:8100`.

Limits: your machine must stay on and awake (check your sleep settings), and the URL only works from your own network. Your router may hand your PC a different IP now and then; the launcher always prints the current one.

## Option B: free 24/7 VM on Oracle Cloud (Always Free, Ampere A1)

Oracle's Always Free tier includes an Ampere A1 ARM VM (up to 4 cores / 24 GB total) that runs JobSquad comfortably at zero cost. About 15 minutes of setup.

1. **Create the VM.** Sign up at oracle.com/cloud (card needed for identity, not charged). Create instance: image **Ubuntu 24.04 (aarch64)**, shape **VM.Standard.A1.Flex** (1 OCPU / 6 GB is plenty). Add your SSH key and note the public IP.

2. **Open port 8100 in the cloud firewall.** Instance page -> Virtual cloud network -> your subnet's **Security List** -> Add Ingress Rule: Source CIDR `0.0.0.0/0`, protocol TCP, destination port `8100`.

3. **Open port 8100 on the VM itself.**

   ```bash
   sudo ufw allow 8100/tcp    # if ufw is active
   ```

   Oracle's Ubuntu images also ship iptables rules that reject everything except SSH. If the port still does not answer:

   ```bash
   sudo iptables -I INPUT 5 -p tcp --dport 8100 -j ACCEPT
   sudo netfilter-persistent save
   ```

4. **Install uv and Node** (both have standard ARM builds):

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source $HOME/.local/bin/env
   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
   sudo apt-get install -y nodejs
   ```

5. **Get the code onto the VM**: `git clone` your repo, or copy the folder with `scp -r`.

6. **First run by hand**, to download dependencies and build the frontend:

   ```bash
   cd ~/JobSquad
   python3 run.py
   ```

   Wait for the URL box and "API is up", check `http://<public-ip>:8100` from your browser, then press Ctrl+C.

7. **Run it under systemd** so it survives reboots and crashes. Create `/etc/systemd/system/jobsquad.service`:

   ```ini
   [Unit]
   Description=JobSquad (the multiplayer job hunt)
   After=network-online.target
   Wants=network-online.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/JobSquad
   ExecStart=/usr/bin/python3 run.py
   Restart=always
   RestartSec=5
   Environment=JOBSQUAD_SECRET=replace-with-a-long-random-string
   Environment=PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin

   [Install]
   WantedBy=multi-user.target
   ```

   The `PATH` line matters: uv installs to `~/.local/bin`, which systemd does not search by default. Generate the secret with:

   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```

   Then:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now jobsquad
   journalctl -u jobsquad -f     # watch the logs
   ```

   In real deployments always set `JOBSQUAD_SECRET` explicitly (as above) instead of relying on the auto-generated `data/.secret`.

Your app is now at `http://<public-ip>:8100`, 24/7. Read the HTTPS note below before sharing that URL widely.

## Option C: Cloudflare Tunnel from an always-on home PC

If some PC at home stays on anyway, you can expose JobSquad over HTTPS without opening any router ports. The app keeps listening on `localhost:8100`; `cloudflared` makes an outbound connection and serves it at a public HTTPS URL.

1. Keep JobSquad running locally (`START.bat`; add it to Startup or Task Scheduler, and disable PC sleep).
2. Install cloudflared: `winget install Cloudflare.cloudflared`.
3. **For testing** (URL changes on every run):

   ```
   cloudflared tunnel --url http://localhost:8100
   ```

   You get a random `https://something.trycloudflare.com` URL to share.

4. **For a stable URL** (named tunnel): you need a domain on a free Cloudflare account (any cheap domain works; some registrars hand out free subdomains).

   ```
   cloudflared tunnel login
   cloudflared tunnel create jobsquad
   cloudflared tunnel route dns jobsquad jobs.yourdomain.com
   ```

   Create `%USERPROFILE%\.cloudflared\config.yml`:

   ```yaml
   tunnel: jobsquad
   credentials-file: C:\Users\YOU\.cloudflared\<tunnel-id>.json
   ingress:
     - hostname: jobs.yourdomain.com
       service: http://localhost:8100
     - service: http_status:404
   ```

   Then `cloudflared service install` runs it at boot. Your friends get HTTPS, and your home IP stays hidden.

## Option D: Render / Fly / Railway (read this first)

Free PaaS tiers have **ephemeral disks**: the filesystem is thrown away on every deploy, restart, or scale event. JobSquad stores everything in `data/jobsquad.db`, so on such a tier **your squad's data is silently lost**.

- **Render free tier**: no persistent disk on free services (disks are a paid feature). Not suitable.
- **Fly.io**: works if you create a volume and mount it at the data directory (`fly volumes create`), but free allowances have shifted over time; check current pricing.
- **Railway**: volumes exist, free hours are limited.

For zero cost with real persistence, prefer Option B (Oracle A1) or Option C (tunnel).

## Backups

All state is `data/jobsquad.db` (plus `data/.secret` if you did not set `JOBSQUAD_SECRET`).

- Simplest: stop JobSquad, copy `data/jobsquad.db` somewhere safe, start again.
- While running: the database is in WAL mode, so a plain copy is usually fine, but the safe way is a consistent snapshot:

  ```bash
  sqlite3 data/jobsquad.db ".backup jobsquad-backup.db"
  ```

- Restore: stop JobSquad, put the backup file back as `data/jobsquad.db`, start.

## HTTPS

Port 8100 speaks plain HTTP. On a LAN that is fine; over the internet, do not send passwords in the clear:

- **Easiest**: Option C (Cloudflare Tunnel) gives you HTTPS automatically.
- **On your own VM**: put [Caddy](https://caddyserver.com) in front; it fetches certificates automatically. Point your domain's DNS at the VM, open ports 80/443, and use this entire Caddyfile:

  ```
  jobs.yourdomain.com {
      reverse_proxy localhost:8100
  }
  ```
