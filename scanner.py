import os
import sys
import time
import json
import sqlite3
import statistics
import configparser
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

# Load config if present
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.ini")
config = configparser.ConfigParser()
if os.path.isfile(CONFIG_PATH):
    config.read(CONFIG_PATH)

def _get_config(section: str, key: str, default: str) -> str:
    try:
        return config.get(section, key)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default

BASE_URL = os.getenv("DONUTSMP_BASE_URL", "https://api.donutsmp.net")
AUTH_KEY = os.getenv("DONUTSMP_AUTH_KEY")
DB_PATH = os.getenv("DONUTSMP_DB_PATH", os.path.join(os.path.dirname(__file__), "donutsmpah.db"))
UNDERPRICE_THRESHOLD = float(os.getenv("DONUTSMP_UNDERPRICE_THRESHOLD", "0.7"))  # 30% below median
REQUEST_TIMEOUT = int(os.getenv("DONUTSMP_REQUEST_TIMEOUT", "30"))
MAX_TRANSACTIONS_PAGES = 10
RAW_RETENTION_DAYS = int(_get_config("storage", "raw_retention_days", "7"))
COMPACTION_INTERVAL = int(_get_config("storage", "compaction_interval_hours", "24")) * 3600

_last_compaction = 0

# Safety: never print or persist AUTH_KEY


def _auth_headers() -> Dict[str, str]:
    if not AUTH_KEY:
        raise RuntimeError("DONUTSMP_AUTH_KEY not set. Set environment variable before running.")
    return {"Authorization": f"Bearer {AUTH_KEY}", "Content-Type": "application/json"}


def _now_millis() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            item_id TEXT,
            item_name TEXT,
            count INTEGER,
            price REAL,
            seller_name TEXT,
            seller_uuid TEXT,
            time_left INTEGER,
            seen_at INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id TEXT,
            item_id TEXT,
            item_name TEXT,
            price REAL,
            seen_at INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            unixMillisDateSold INTEGER,
            item_id TEXT,
            item_name TEXT,
            price REAL,
            seller_name TEXT,
            seller_uuid TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            ts INTEGER,
            item_id TEXT,
            item_name TEXT,
            price REAL,
            seller_name TEXT,
            seller_uuid TEXT,
            count INTEGER,
            time_left INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS rollups_daily (
            date TEXT,
            item_id TEXT,
            item_name TEXT,
            median REAL,
            p25 REAL,
            p75 REAL,
            count INTEGER,
            PRIMARY KEY (date, item_id, item_name)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_item ON events(item_id, item_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rollups_item ON rollups_daily(item_id, item_name)")
    conn.commit()


def fetch_listings(page: int, search: Optional[str] = None, sort: Optional[str] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}/v1/auction/list/{page}"
    body = {}
    if search:
        body["search"] = search
    if sort:
        body["sort"] = sort
    try:
        resp = requests.get(url, headers=_auth_headers(), json=(body or None), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        raise RuntimeError(f"Request error for listings page {page}: {e}")
    if resp.status_code == 401:
        time.sleep(2)
        raise PermissionError("Unauthorized: Check DONUTSMP_AUTH_KEY and header format.")
    if resp.status_code >= 500:
        raise RuntimeError(f"Server error {resp.status_code}: {resp.text}")
    if resp.status_code != 200:
        raise RuntimeError(f"Unexpected status {resp.status_code}: {resp.text}")
    return resp.json()


def fetch_transactions(page: int) -> Dict[str, Any]:
    if page < 1 or page > MAX_TRANSACTIONS_PAGES:
        raise ValueError("Transaction page must be between 1 and 10")
    url = f"{BASE_URL}/v1/auction/transactions/{page}"
    try:
        resp = requests.get(url, headers=_auth_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        raise RuntimeError(f"Request error for transactions page {page}: {e}")
    if resp.status_code == 401:
        time.sleep(2)
        raise PermissionError("Unauthorized: Check DONUTSMP_AUTH_KEY and header format.")
    if resp.status_code >= 500:
        raise RuntimeError(f"Server error {resp.status_code}: {resp.text}")
    if resp.status_code != 200:
        raise RuntimeError(f"Unexpected status {resp.status_code}: {resp.text}")
    return resp.json()


def _item_display(item: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    name = item.get("display_name")
    item_id = item.get("id")
    if not name:
        # Fallback to id if name is missing
        name = item_id
    return item_id, name


def store_listings(conn: sqlite3.Connection, response: Dict[str, Any]) -> int:
    result = response.get("result", [])
    cur = conn.cursor()
    inserted = 0
    ts = _now_millis()
    for entry in result:
        item = entry.get("item", {})
        price = entry.get("price")
        seller = entry.get("seller", {})
        time_left = entry.get("time_left")
        item_id, item_name = _item_display(item)
        count = item.get("count")
        cur.execute(
            """
            INSERT INTO events (type, ts, item_id, item_name, price, seller_name, seller_uuid, count, time_left)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "listing",
                ts,
                item_id,
                item_name,
                float(price) if price is not None else None,
                seller.get("name"),
                seller.get("uuid"),
                count,
                int(time_left) if time_left is not None else None,
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def store_transactions(conn: sqlite3.Connection, response: Dict[str, Any]) -> int:
    result = response.get("result", [])
    cur = conn.cursor()
    inserted = 0
    ts = _now_millis()
    for entry in result:
        item = entry.get("item", {})
        price = entry.get("price")
        seller = entry.get("seller", {})
        sold_at = entry.get("unixMillisDateSold")
        item_id, item_name = _item_display(item)
        cur.execute(
            """
            INSERT INTO events (type, ts, item_id, item_name, price, seller_name, seller_uuid, count, time_left)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "transaction",
                ts,
                item_id,
                item_name,
                float(price) if price is not None else None,
                seller.get("name"),
                seller.get("uuid"),
                None,
                None,
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def compute_stats(conn: sqlite3.Connection, item_key: Tuple[Optional[str], Optional[str]]) -> Dict[str, Any]:
    item_id, item_name = item_key
    cur = conn.cursor()
    cur.execute(
        """
        SELECT price FROM prices WHERE item_id IS ? AND item_name IS ? AND price IS NOT NULL
        """,
        (item_id, item_name),
    )
    prices = [row[0] for row in cur.fetchall()]
    if not prices:
        return {"count": 0}
    prices_sorted = sorted(prices)
    median_price = statistics.median(prices_sorted)
    # robust stddev: use population stdev if at least 2 values
    stddev = statistics.pstdev(prices_sorted) if len(prices_sorted) > 1 else 0.0
    p25 = prices_sorted[max(0, (len(prices_sorted) * 25) // 100 - 1)]
    p75 = prices_sorted[min(len(prices_sorted) - 1, (len(prices_sorted) * 75) // 100 - 1)]
    return {
        "count": len(prices_sorted),
        "median": median_price,
        "stddev": stddev,
        "p25": p25,
        "p75": p75,
    }


def detect_undervalued(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT item_id, item_name FROM prices GROUP BY item_id, item_name
        """
    )
    items = cur.fetchall()
    findings: List[Dict[str, Any]] = []
    for item_id, item_name in items:
        stats = compute_stats(conn, (item_id, item_name))
        if not stats.get("count"):
            continue
        median_price = stats.get("median")
        if median_price is None or median_price == 0:
            continue
        threshold_price = median_price * UNDERPRICE_THRESHOLD
        cur.execute(
            """
            SELECT id, price, seller_name, seller_uuid, seen_at FROM listings
            WHERE item_id IS ? AND item_name IS ? AND price IS NOT NULL AND price < ?
            ORDER BY price ASC
            """,
            (item_id, item_name, threshold_price),
        )
        rows = cur.fetchall()
        for row in rows:
            findings.append(
                {
                    "id": row[0],
                    "item_id": item_id,
                    "item_name": item_name,
                    "price": row[1],
                    "seller_name": row[2],
                    "seller_uuid": row[3],
                    "seen_at": row[4],
                    "median": median_price,
                    "threshold": threshold_price,
                }
            )
    return findings


def poll_once(conn: sqlite3.Connection, pages: int, search: Optional[str], sort: Optional[str]) -> Tuple[int, int]:
    listings_inserted = 0
    transactions_inserted = 0
    for p in range(1, pages + 1):
        try:
            data = fetch_listings(page=p, search=search, sort=sort)
            count = store_listings(conn, data)
            listings_inserted += count
        except Exception as e:
            print(f"[WARN] Listings page {p} error: {e}")
    for p in range(1, min(MAX_TRANSACTIONS_PAGES, pages) + 1):
        try:
            data = fetch_transactions(page=p)
            count = store_transactions(conn, data)
            transactions_inserted += count
        except Exception as e:
            print(f"[WARN] Transactions page {p} error: {e}")
    return listings_inserted, transactions_inserted


def format_currency(v: Optional[float]) -> str:
    if v is None:
        return "N/A"
    return f"{v:,.2f}"


def _get_listing_details(conn: sqlite3.Connection, listing_id: str) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT item_id, item_name, count, time_left
        FROM listings
        WHERE id IS ?
        """,
        (listing_id,),
    )
    row = cur.fetchone()
    if not row:
        return {}
    return {"item_id": row[0], "item_name": row[1], "count": row[2], "time_left": row[3]}


def print_summary(conn: sqlite3.Connection) -> None:
    findings = detect_undervalued(conn)
    print(f"Undervalued findings: {len(findings)}")
    for f in findings[:20]:  # cap output
        extra = _get_listing_details(conn, f["id"]) if f.get("id") else {}
        item_label = (extra.get("item_name") or f.get("item_name") or extra.get("item_id") or f.get("item_id") or "unknown")
        out = {
            "item": item_label,
            "item_id": extra.get("item_id") or f.get("item_id"),
            "count": extra.get("count"),
            "time_left": extra.get("time_left"),
            "price": format_currency(f.get("price")),
            "median": format_currency(f.get("median")),
            "threshold": format_currency(f.get("threshold")),
            "seller": f.get("seller_name") or "",
        }
        print(json.dumps(out, ensure_ascii=False))


def read_guide_if_present() -> Optional[str]:
    # Search for GUIDE.md at workspace root siblings; we avoid creating or modifying it.
    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        candidate = os.path.join(base_dir, "GUIDE.md")
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
    except Exception:
        pass
    return None


def write_backup_snapshot() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(os.path.dirname(__file__), f"backup-{ts}.md")
    guide = read_guide_if_present()
    content = [
        "# DonutSMP AH Scanner Snapshot\n",
        f"Timestamp: {ts} UTC\n\n",
        "## Architecture\n",
        "- Python requests client + SQLite store\n",
        "- Periodic polling of listings and transactions\n",
        "- Median-based undervaluation detection\n\n",
        "## Schemas\n",
        "- listings(id, item_id, item_name, count, price, seller_name, seller_uuid, time_left, seen_at)\n",
        "- prices(id, item_id, item_name, price, seen_at)\n",
        "- transactions(unixMillisDateSold, item_id, item_name, price, seller_name, seller_uuid)\n\n",
        "## Logic Flow\n",
        "1. Fetch /v1/auction/list/{page} with optional search/sort\n",
        "2. Fetch /v1/auction/transactions/{page} pages 1..10\n",
        "3. Insert into SQLite; compute rolling stats\n",
        "4. Detect listings priced below median * threshold\n\n",
        "## Assumptions\n",
        "- AUTH header strictly 'Authorization: Bearer <key>'\n",
        "- Transactions limited to 10 pages per docs\n",
        "- Time units for time_left are not specified in docs\n\n",
        "## Future Improvements\n",
        "- Persist item NBT/enchants for deeper valuation\n",
        "- Per-item category baseline medians\n",
        "- Adaptive polling based on activity\n\n",
        "## Known Bugs\n",
        "- Synthetic listing id may collide on identical tuples\n",
        "- Percentile calculation uses simple index approximations\n\n",
    ]
    if guide:
        content.append("## GUIDE.md (User-provided; highest priority)\n\n")
        content.append("````\n")
        content.append(guide)
        content.append("\n````\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(content))
    return path


def compact_old_data(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    now = _now_millis()
    cutoff = now - (RAW_RETENTION_DAYS * 86400 * 1000)
    
    # Compute daily rollups for old data
    cur.execute(
        """
        SELECT date(ts / 1000, 'unixepoch') as date, item_id, item_name
        FROM events
        WHERE ts < ? AND type = 'listing'
        GROUP BY date, item_id, item_name
        """,
        (cutoff,),
    )
    groups = cur.fetchall()
    for date_str, item_id, item_name in groups:
        cur.execute(
            """
            SELECT price FROM events
            WHERE date(ts / 1000, 'unixepoch') = ? AND item_id IS ? AND item_name IS ? AND price IS NOT NULL AND type = 'listing'
            """,
            (date_str, item_id, item_name),
        )
        prices = [row[0] for row in cur.fetchall()]
        if prices:
            prices_sorted = sorted(prices)
            median = statistics.median(prices_sorted)
            p25 = prices_sorted[max(0, len(prices_sorted) * 25 // 100 - 1)]
            p75 = prices_sorted[min(len(prices_sorted) - 1, len(prices_sorted) * 75 // 100 - 1)]
            cur.execute(
                """
                INSERT OR REPLACE INTO rollups_daily (date, item_id, item_name, median, p25, p75, count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (date_str, item_id, item_name, median, p25, p75, len(prices)),
            )
    
    # Delete old events
    cur.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
    cur.execute("DELETE FROM prices WHERE seen_at < ?", (cutoff,))
    conn.commit()
    print(f"Compaction complete: removed events older than {RAW_RETENTION_DAYS} days")


def full_scan_ah(conn: sqlite3.Connection, search: Optional[str], sort: Optional[str]) -> Tuple[int, int]:
    """Scan ALL pages of the AH until no more results, with retry logic"""
    listings_total = 0
    transactions_total = 0
    page = 1
    consecutive_empty = 0
    max_empty_pages = 3  # Stop after 3 empty pages in a row
    retry_count = 0
    max_retries = 3
    
    print(f"\n{'='*90}")
    print(f"INITIAL FULL AH SCAN - Fetching all pages until empty...")
    print(f"{'='*90}\n")
    
    while consecutive_empty < max_empty_pages:
        try:
            ts_iso = datetime.now(timezone.utc).isoformat()
            data = fetch_listings(page=page, search=search, sort=sort)
            result = data.get("result", [])
            
            if not result:
                consecutive_empty += 1
                print(f"[{ts_iso}] Page {page}: Empty (consecutive empty: {consecutive_empty}/{max_empty_pages})")
                page += 1
                retry_count = 0  # Reset retry on success
                continue
            
            consecutive_empty = 0
            count = store_listings(conn, data)
            listings_total += count
            print(f"[{ts_iso}] Page {page}: Scanned {count} listings (total: {listings_total})")
            page += 1
            retry_count = 0  # Reset retry on success
            
        except KeyboardInterrupt:
            print(f"\n[!] Scan interrupted by user. Partial scan: {listings_total} listings")
            raise
        except Exception as e:
            retry_count += 1
            if retry_count > max_retries:
                print(f"[ERROR] Page {page}: Max retries exceeded ({max_retries}). {e}")
                consecutive_empty += 1
                page += 1
                retry_count = 0
            else:
                backoff = 3 + (retry_count * 2)  # 5s, 7s, 9s
                print(f"[WARN] Page {page}: {e} (retry {retry_count}/{max_retries}, waiting {backoff}s)")
                time.sleep(backoff)
                # Don't increment page; retry same page
    
    # Also scan all transaction pages (with retries)
    print(f"\n[*] Scanning transaction history (pages 1-10)...")
    for p in range(1, MAX_TRANSACTIONS_PAGES + 1):
        retry = 0
        while retry <= max_retries:
            try:
                data = fetch_transactions(page=p)
                count = store_transactions(conn, data)
                transactions_total += count
                ts_iso = datetime.now(timezone.utc).isoformat()
                print(f"[{ts_iso}] Transactions page {p}: {count} (total: {transactions_total})")
                break  # Success, move to next page
            except Exception as e:
                retry += 1
                if retry > max_retries:
                    print(f"[ERROR] Transactions page {p}: Max retries exceeded. {e}")
                    break
                else:
                    print(f"[WARN] Transactions page {p}: {e} (retry {retry}/{max_retries})")
                    time.sleep(2)
    
    print(f"\n{'='*90}")
    print(f"FULL SCAN COMPLETE: {listings_total} listings + {transactions_total} transactions")
    print(f"{'='*90}\n")
    
    return listings_total, transactions_total


def run_poll_loop(pages: int, interval_sec: int, search: Optional[str], sort: Optional[str]) -> None:
    global _last_compaction
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    start_ts = datetime.now(timezone.utc).isoformat()
    print(f"\n{'='*90}")
    print(f"[{start_ts}] DonutSMP AH Scanner Started")
    print(f"{'='*90}")
    print(f"[CONFIG] Pages: {pages}, Interval: {interval_sec}s")
    print(f"[CONFIG] Retention: {RAW_RETENTION_DAYS} days, Compaction: every {COMPACTION_INTERVAL // 3600} hours")
    print(f"[CONFIG] Database: {DB_PATH}")
    print(f"[CONFIG] Auth: {'OK' if AUTH_KEY else 'NOT SET'}")
    if search:
        print(f"[CONFIG] Search filter: {search}")
    if sort:
        print(f"[CONFIG] Sort: {sort}")
    print(f"{'='*90}\n")
    
    # Perform initial slightly-expanded scan before polling (scan 10 pages instead of 3)
    print("[*] Starting initial expanded AH scan (pages 1-10)...")
    try:
        for i in range(1, 11):
            try:
                data = fetch_listings(page=i, search=search, sort=sort)
                count = store_listings(conn, data)
                result = data.get("result", [])
                if not result:
                    break
                print(f"[*] Initial scan page {i}: {count} listings")
            except Exception as e:
                print(f"[WARN] Initial scan page {i}: {e}")
                break
        print("[*] Initial expanded scan complete. Starting incremental polling...\n")
    except Exception as e:
        print(f"[WARN] Initial scan skipped: {e}. Starting polling anyway.\n")
    
    
    poll_count = 0
    while True:
        start = time.time()
        poll_count += 1
        try:
            ts_iso = datetime.now(timezone.utc).isoformat()
            l_ins, t_ins = poll_once(conn, pages, search, sort)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM events")
            total_events = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT item_id) FROM events")
            unique_items = cur.fetchone()[0]
            print(f"[{ts_iso}] Poll #{poll_count:05d} | +{l_ins:4d} listings | +{t_ins:4d} transactions | Total: {total_events:7d} events | {unique_items:3d} unique items")
            # Run compaction if interval passed
            if time.time() - _last_compaction > COMPACTION_INTERVAL:
                comp_ts = datetime.now(timezone.utc).isoformat()
                print(f"[{comp_ts}] ► Running data compaction...")
                compact_old_data(conn)
                _last_compaction = time.time()
        except PermissionError as e:
            print(f"[ERROR] {str(e)}")
            time.sleep(5)
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)
        elapsed = time.time() - start
        sleep_time = max(0, interval_sec - int(elapsed))
        if sleep_time > 0:
            time.sleep(sleep_time)


def main(argv: List[str]) -> None:
    if len(argv) >= 2:
        cmd = " ".join(argv[1:]).strip().lower()
        if cmd in ("snapshot", "create backup", "make restore point"):
            path = write_backup_snapshot()
            print(f"Backup created: {path}")
            return
    # Normal run
    pages = int(os.getenv("DONUTSMP_PAGES", _get_config("scanner", "pages", "3")))
    interval = int(os.getenv("DONUTSMP_INTERVAL", _get_config("scanner", "interval", "30")))
    search = os.getenv("DONUTSMP_SEARCH", _get_config("scanner", "search", ""))
    sort = os.getenv("DONUTSMP_SORT", _get_config("scanner", "sort", ""))
    if not search:
        search = None
    if not sort:
        sort = None
    run_poll_loop(pages, interval, search, sort)


if __name__ == "__main__":
    main(sys.argv)
