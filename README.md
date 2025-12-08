# DonutSMP AH Scanner + Live Tracker

This folder contains a standalone Auction House scanner, analytics, live dashboard, and backup system for the DonutSMP Public API.

Do not place secrets in code or comments. Provide your API key via environment variable.

## Features
- Periodic polling of `/v1/auction/list/{page}` and optional search/sort
- Transaction history via `/v1/auction/transactions/{page}` (pages 1–10)
- SQLite time-series database with auto-compaction (keeps raw 7 days, rollups forever)
- Median/quantile/stddev analytics and underpricing detection
- **Live web dashboard** with real-time listings, undervalued items, and stats
- Snapshot backup command that writes `backup-[timestamp].md`
- Safe auth handling: `Authorization: Bearer <AUTH_KEY>` header

## Quick Start
1. Create your API key in-game with `/api`.
2. Set environment variable `DONUTSMP_AUTH_KEY` to your key.
3. Install dependencies.
4. Run the scanner in one terminal.
5. Run the API server in another terminal.
6. Open http://127.0.0.1:5000 in your browser.

### Windows PowerShell commands
```powershell
# Terminal 1: Scanner
$env:DONUTSMP_AUTH_KEY = "<YOUR_API_KEY>"
python -m pip install -r requirements.txt
python scanner.py

# Terminal 2: API Server
$env:DONUTSMP_AUTH_KEY = "<YOUR_API_KEY>"
python api.py
```

Then open http://127.0.0.1:5000 in your browser.

### Snapshot / Backup
Trigger a full system snapshot (backup markdown file):
```powershell
python scanner.py snapshot
```
Aliases: `snapshot`, `create backup`, `make restore point`

## Configuration (config.ini)
Edit `config.ini` to customize:
- `[scanner]`: pages, interval, search, sort
- `[storage]`: raw_retention_days (default 7), compaction_interval_hours (default 24)
- `[api]`: host, port

Environment variables override config.ini values.

## Database Schema
- `listings(id TEXT PRIMARY KEY, item_id TEXT, item_name TEXT, count INTEGER, price REAL, seller_name TEXT, seller_uuid TEXT, time_left INTEGER, seen_at INTEGER)`
- `prices(id TEXT, item_id TEXT, item_name TEXT, price REAL, seen_at INTEGER)`
- `transactions(unixMillisDateSold INTEGER, item_id TEXT, item_name TEXT, price REAL, seller_name TEXT, seller_uuid TEXT)`
- `events(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, ts INTEGER, item_id TEXT, item_name TEXT, price REAL, seller_name TEXT, seller_uuid TEXT, count INTEGER, time_left INTEGER)`
- `rollups_daily(date TEXT, item_id TEXT, item_name TEXT, median REAL, p25 REAL, p75 REAL, count INTEGER, PRIMARY KEY (date, item_id, item_name))`

## API Endpoints
- `GET /` - Dashboard HTML
- `GET /api/live` - Recent listings (last 5 minutes)
- `GET /api/undervalued` - Current undervalued listings (below 70% median)
- `GET /api/trend/<item_id>` - Price trend from daily rollups
- `GET /api/stats` - Global stats (total events, listings, transactions, unique items)

## Storage Efficiency
- Raw events stored for 7 days (configurable)
- Daily rollups computed and kept indefinitely
- Automatic compaction runs every 24 hours
- Minimal overhead: SQLite indexed time-series + periodic pruning

## Notes
- Follows API docs from `https://api.donutsmp.net/doc.json`
- Respects 250 req/min limit; uses backoff on 401/5xx
- GUIDE.md: If present (provided by user), it is read at startup and treated as highest priority; never generated or modified by this tool
