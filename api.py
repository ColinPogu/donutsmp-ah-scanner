import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

DB_PATH = os.getenv("DONUTSMP_DB_PATH", os.path.join(os.path.dirname(__file__), "donutsmpah.db"))

app = Flask(__name__)
CORS(app)


def init_db() -> None:
    """Initialize database tables if they don't exist"""
    conn = sqlite3.connect(DB_PATH)
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
    conn.close()


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now_millis() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "dashboard.html")


@app.route("/app.js")
def app_js():
    return send_from_directory(os.path.dirname(__file__), "app.js")


@app.route("/api/live")
def api_live():
    """Recent listings from events table (last 5 minutes)"""
    conn = _get_conn()
    cur = conn.cursor()
    cutoff = _now_millis() - (5 * 60 * 1000)
    try:
        cur.execute(
            """
            SELECT ts, item_id, item_name, price, seller_name, count, time_left
            FROM events
            WHERE ts > ? AND type = 'listing'
            ORDER BY ts DESC
            LIMIT 100
            """,
            (cutoff,),
        )
        rows = cur.fetchall()
        conn.close()
        data = []
        for row in rows:
            data.append({
                "ts": row[0],
                "item_id": row[1],
                "item_name": row[2],
                "price": row[3],
                "seller_name": row[4],
                "count": row[5],
                "time_left": row[6]
            })
        return jsonify({"status": "ok", "data": data})
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/undervalued")
def api_undervalued():
    """Current undervalued listings - shows ALL individual listings, not grouped"""
    conn = _get_conn()
    cur = conn.cursor()
    try:
        # Get unique items to calculate medians
        cur.execute(
            """
            SELECT DISTINCT item_id, item_name FROM events WHERE type = 'listing'
            """
        )
        items = cur.fetchall()
        findings: List[Dict[str, Any]] = []
        threshold_factor = 0.7
        
        for item_row in items:
            item_id, item_name = item_row[0], item_row[1]
            # Get all prices for this item
            cur.execute(
                """
                SELECT price FROM events WHERE item_id = ? AND item_name = ? AND type = 'listing' AND price IS NOT NULL
                """,
                (item_id, item_name),
            )
            prices = [r[0] for r in cur.fetchall()]
            if not prices or len(prices) < 2:
                continue
            import statistics
            
            # Filter outliers to avoid scam/junk listings skewing median
            sorted_prices = sorted(prices)
            n = len(sorted_prices)
            if n >= 3:
                q1_idx = n // 4
                q3_idx = (3 * n) // 4
                q1 = sorted_prices[q1_idx]
                q3 = sorted_prices[q3_idx]
                iqr = q3 - q1
                if iqr > 0:
                    lower_bound = max(0, q1 - 1.5 * iqr)
                    upper_bound = q3 + 1.5 * iqr
                    prices_filtered = [p for p in prices if lower_bound <= p <= upper_bound]
                else:
                    prices_filtered = prices
            else:
                prices_filtered = prices
            
            median = statistics.median(sorted(prices_filtered))
            if median == 0:
                continue
            threshold = median * threshold_factor
            
            # Get ALL undervalued listings (not limited per item)
            cur.execute(
                """
                SELECT ts, item_id, item_name, count, price, seller_name, time_left
                FROM events
                WHERE item_id = ? AND item_name = ? AND price IS NOT NULL AND price < ? AND type = 'listing'
                ORDER BY price ASC
                """,
                (item_id, item_name, threshold),
            )
            for listing_row in cur.fetchall():
                findings.append(
                    {
                        "ts": listing_row[0],
                        "item_id": listing_row[1],
                        "item_name": listing_row[2] or listing_row[1],
                        "count": listing_row[3],
                        "price": listing_row[4],
                        "seller": listing_row[5],
                        "time_left": listing_row[6],
                        "median": median,
                        "threshold": threshold,
                        "discount_pct": round((1 - listing_row[4] / median) * 100)
                    }
                )
        
        # Sort by discount % descending (best deals first)
        findings.sort(key=lambda x: x['discount_pct'], reverse=True)
        conn.close()
        return jsonify({"status": "ok", "data": findings[:200]})
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/trend/<item_id>")
def api_trend(item_id: str):
    """Price trend from rollups_daily for a given item_id"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date, item_id, item_name, median, p25, p75, count
        FROM rollups_daily
        WHERE item_id IS ?
        ORDER BY date ASC
        """,
        (item_id,),
    )
    rows = cur.fetchall()
    conn.close()
    data = [dict(row) for row in rows]
    return jsonify({"status": "ok", "data": data})


@app.route("/api/stats")
def api_stats():
    """Global stats: total events, listings, transactions, unique items"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events")
    total_events = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM listings")
    total_listings = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM transactions")
    total_transactions = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT item_id) FROM events")
    unique_items = cur.fetchone()[0]
    conn.close()
    return jsonify(
        {
            "status": "ok",
            "data": {
                "total_events": total_events,
                "total_listings": total_listings,
                "total_transactions": total_transactions,
                "unique_items": unique_items,
            },
        }
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
