import os
import sqlite3
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

DB_PATH = os.getenv("DONUTSMP_DB_PATH", os.path.join(os.path.dirname(__file__), "donutsmpah.db"))

app = Flask(__name__)
CORS(app)


@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


def _init_db() -> None:
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


_init_db()


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


def _get_item_stats(cur, item_id: str, item_name: str) -> Dict[str, Any]:
    """Calculate comprehensive stats for an item"""
    cur.execute(
        """
        SELECT price FROM events 
        WHERE item_id = ? AND item_name = ? AND type = 'listing' AND price IS NOT NULL
        ORDER BY ts DESC
        LIMIT 1000
        """,
        (item_id, item_name),
    )
    prices = [r[0] for r in cur.fetchall()]
    
    if not prices or len(prices) < 3:
        return None
    
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    
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
    
    if not prices_filtered:
        prices_filtered = prices
    
    median = statistics.median(prices_filtered)
    mean = statistics.mean(prices_filtered)
    
    try:
        stdev = statistics.stdev(prices_filtered) if len(prices_filtered) > 1 else 0
    except:
        stdev = 0
    
    volatility = (stdev / mean * 100) if mean > 0 else 0
    
    return {
        "median": median,
        "mean": mean,
        "min": min(prices_filtered),
        "max": max(prices_filtered),
        "q1": q1,
        "q3": q3,
        "stdev": stdev,
        "volatility": volatility,
        "sample_size": len(prices)
    }


@app.route("/api/recommendations")
def api_recommendations():
    """Smart purchase recommendations with priority scoring"""
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT item_id, item_name, COUNT(*) as cnt FROM events 
            WHERE type = 'listing' 
            GROUP BY item_id, item_name 
            HAVING cnt >= 10
            ORDER BY cnt DESC
            LIMIT 200
            """
        )
        items = cur.fetchall()
        recommendations: List[Dict[str, Any]] = []
        
        for item_row in items:
            item_id, item_name = item_row[0], item_row[1]
            stats = _get_item_stats(cur, item_id, item_name)
            
            if not stats or stats["median"] == 0:
                continue
            
            median = stats["median"]
            volatility = stats["volatility"]
            sample_size = stats["sample_size"]
            
            cur.execute(
                """
                SELECT ts, count, price, seller_name, time_left
                FROM events
                WHERE item_id = ? AND item_name = ? AND price IS NOT NULL 
                AND price < ? AND type = 'listing'
                ORDER BY ts DESC
                LIMIT 1
                """,
                (item_id, item_name, median * 0.85),
            )
            
            listing = cur.fetchone()
            if not listing:
                continue
            
            ts, count, price, seller, time_left = listing
            
            discount_pct = round((1 - price / median) * 100)
            if discount_pct < 15:
                continue
            
            profit_potential = median - price
            profit_margin_pct = (profit_potential / price * 100) if price > 0 else 0
            
            confidence_score = min(100, sample_size / 10 * 10)
            stability_score = max(0, 100 - volatility)
            discount_score = min(100, discount_pct * 1.5)
            
            priority_score = round(
                (discount_score * 0.4) + 
                (stability_score * 0.3) + 
                (confidence_score * 0.3)
            )
            
            if priority_score < 30:
                continue
            
            recommendations.append({
                "item_id": item_id,
                "item_name": item_name or item_id,
                "count": count,
                "current_price": price,
                "median_price": median,
                "discount_pct": discount_pct,
                "profit_potential": profit_potential,
                "profit_margin_pct": round(profit_margin_pct),
                "priority_score": priority_score,
                "confidence": round(confidence_score),
                "stability": round(stability_score),
                "volatility": round(volatility, 1),
                "sample_size": sample_size,
                "seller": seller,
                "time_left": time_left,
                "ts": ts
            })
        
        recommendations.sort(key=lambda x: x['priority_score'], reverse=True)
        conn.close()
        return jsonify({"status": "ok", "data": recommendations[:50]})
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/undervalued")
def api_undervalued():
    """Current undervalued listings with enhanced data"""
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT item_id, item_name, COUNT(*) as cnt FROM events 
            WHERE type = 'listing' 
            GROUP BY item_id, item_name 
            HAVING cnt >= 5
            ORDER BY cnt DESC
            LIMIT 300
            """
        )
        items = cur.fetchall()
        findings: List[Dict[str, Any]] = []
        threshold_factor = 0.7
        
        for item_row in items:
            item_id, item_name = item_row[0], item_row[1]
            stats = _get_item_stats(cur, item_id, item_name)
            
            if not stats or stats["median"] == 0:
                continue
            
            median = stats["median"]
            threshold = median * threshold_factor
            
            cur.execute(
                """
                SELECT ts, item_id, item_name, count, price, seller_name, time_left
                FROM events
                WHERE item_id = ? AND item_name = ? AND price IS NOT NULL AND price < ? AND type = 'listing'
                ORDER BY price ASC
                LIMIT 10
                """,
                (item_id, item_name, threshold),
            )
            
            for listing_row in cur.fetchall():
                price = listing_row[4]
                discount_pct = round((1 - price / median) * 100)
                profit = median - price
                
                findings.append({
                    "ts": listing_row[0],
                    "item_id": listing_row[1],
                    "item_name": listing_row[2] or listing_row[1],
                    "count": listing_row[3],
                    "price": price,
                    "seller": listing_row[5],
                    "time_left": listing_row[6],
                    "median": median,
                    "threshold": threshold,
                    "discount_pct": discount_pct,
                    "profit_potential": profit,
                    "sample_size": stats["sample_size"],
                    "volatility": round(stats["volatility"], 1)
                })
        
        findings.sort(key=lambda x: x['discount_pct'], reverse=True)
        conn.close()
        return jsonify({"status": "ok", "data": findings[:100]})
    except Exception as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/market-overview")
def api_market_overview():
    """Get top traded items with price info"""
    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT item_id, item_name, COUNT(*) as trade_count
            FROM events
            WHERE type = 'listing' AND price IS NOT NULL
            GROUP BY item_id, item_name
            ORDER BY trade_count DESC
            LIMIT 20
            """
        )
        items = cur.fetchall()
        
        market_data = []
        for row in items:
            item_id, item_name, trade_count = row[0], row[1], row[2]
            stats = _get_item_stats(cur, item_id, item_name)
            
            if stats:
                market_data.append({
                    "item_id": item_id,
                    "item_name": item_name or item_id,
                    "trade_count": trade_count,
                    "median": stats["median"],
                    "min": stats["min"],
                    "max": stats["max"],
                    "volatility": round(stats["volatility"], 1),
                    "sample_size": stats["sample_size"]
                })
        
        conn.close()
        return jsonify({"status": "ok", "data": market_data})
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
    """Global stats from events table"""
    conn = _get_conn()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM events")
    total_events = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM events WHERE type = 'listing'")
    total_listings = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM events WHERE type = 'transaction'")
    total_transactions = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(DISTINCT item_id) FROM events")
    unique_items = cur.fetchone()[0]
    
    one_hour_ago = _now_millis() - (60 * 60 * 1000)
    cur.execute("SELECT COUNT(*) FROM events WHERE ts > ?", (one_hour_ago,))
    events_last_hour = cur.fetchone()[0]
    
    cur.execute("SELECT MIN(ts), MAX(ts) FROM events")
    time_range = cur.fetchone()
    first_event = time_range[0]
    last_event = time_range[1]
    
    data_span_hours = 0
    if first_event and last_event:
        data_span_hours = round((last_event - first_event) / (1000 * 60 * 60), 1)
    
    conn.close()
    return jsonify({
        "status": "ok",
        "data": {
            "total_events": total_events,
            "total_listings": total_listings,
            "total_transactions": total_transactions,
            "unique_items": unique_items,
            "events_last_hour": events_last_hour,
            "data_span_hours": data_span_hours
        },
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
