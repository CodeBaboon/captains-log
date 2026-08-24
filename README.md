# Captain's Log

A solo game log for Star Trek: Captain's Chair. Photograph the scorepad, check
what it read, save. Or type it in by hand.

Built to sit on a Raspberry Pi on your LAN. Flask, SQLite, and one outbound API
call when you scan a sheet. No compiled dependencies beyond Pillow.

## What it records

Per game: date, your captain, board side, the bot's captain and rank, how the
game ended, the eight score rows for both sides, computed totals, and the photo
of the sheet if you scanned one.

Three rules are enforced in `_parse_game_form`:

- **No draws against the bot.** You need strictly more points; equal totals is a
  loss.
- **Mission points need the Advanced side.** On Basic the row is disabled and
  stored as null, not zero, so it renders as a dash rather than a real score.
- **The Burn is a loss with no score.** Selecting it hides the grid and stores
  nulls, because you would not have written the scores down.

Card VP accepts negatives, which is how Incidents land in the total.

## Running it locally

```bash
pip install -r requirements.txt
export CC_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export ANTHROPIC_API_KEY="sk-ant-..."
python3 app.py
```

Open http://localhost:8080. The first visit sends you to `/setup` to create your
account; that page stops working once an account exists.

Without an API key everything works except scanning, which reports that it is
unconfigured and leaves you to type the game in.

## Installing on the Pi

```bash
sudo apt install python3-pip python3-venv
git clone <your repo> /opt/captains-log
cd /opt/captains-log
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

If Pillow tries to build from source, `sudo apt install python3-pil` first and
create the venv with `--system-site-packages`; piwheels usually has a prebuilt
wheel on Raspberry Pi OS.

Create `/etc/captains-log.env`, readable only by root:

```
CC_SECRET_KEY=<64 hex characters>
ANTHROPIC_API_KEY=sk-ant-...
CC_DATA_DIR=/var/lib/captains-log
```

Then `/etc/systemd/system/captains-log.service`:

```ini
[Unit]
Description=Captain's Log
After=network-online.target

[Service]
User=pi
EnvironmentFile=/etc/captains-log.env
WorkingDirectory=/opt/captains-log
ExecStart=/opt/captains-log/.venv/bin/gunicorn \
    --workers 2 --threads 2 --timeout 120 \
    --bind 0.0.0.0:8080 app:app
Restart=on-failure

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/captains-log

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/lib/captains-log
sudo chown pi:pi /var/lib/captains-log
sudo systemctl enable --now captains-log
```

Two workers with two threads each is comfortable on a Pi 3. The 120 second
timeout exists because a scan waits on the API.

Do not forward a port for this. On your LAN it is reachable at
`http://<pi>:8080`. If you later want it from outside, put Tailscale on the Pi
under your personal account rather than opening the router.

### Add it to your phone

Visit the address in mobile Safari or Chrome and choose "Add to home screen".
The manifest makes it open without browser chrome.

## Backups

Everything lives under `CC_DATA_DIR`: `captains_log.db` plus a `photos/`
folder. The database is in WAL mode, so copy it with sqlite rather than `cp`:

```bash
sqlite3 /var/lib/captains-log/captains_log.db ".backup /tmp/cc-backup.db"
tar czf cc-$(date +%F).tar.gz -C /var/lib/captains-log photos /tmp/cc-backup.db
```

## Captains

`db.py` seeds the eleven captains I could confirm across both boxes. The captain
fields are free text with autocomplete, so anyone you type gets remembered and
appears in the list next time. When you pick up the original box, you should not
need to touch the code.

## Scanning

`extract.py` downscales the photo to 1568px on its longest edge, sends it with a
prompt describing the fixed row order and your handwriting quirks (slashed
zeros, the diagonal for not-applicable, leading minus signs), and validates the
JSON that comes back.

It also sums the rows it read and compares that against the total written on the
sheet. A mismatch is surfaced as a warning above the form rather than silently
corrected, since there is no way to know which cell was misread.

Costs a fraction of a cent per game. Swap models with `CC_MODEL`.

## Tests

```bash
python3 test_app.py
```

Covers the scoring rules, the Burn path, negative values, validation, auth,
pagination, and the extraction parser. Uses a temporary database and leaves no
trace.

## Layout notes

The score header, each score row, the totals line, and the read-only detail rows
all share one CSS grid template, so the three columns cannot drift apart. If you
change a column width, change it in the shared rule and everything follows.
