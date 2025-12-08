# DonutSMP Auction House Scanner + Tracker

## Project Overview
This is a DonutSMP Auction House (AH) scanner and live tracker application that monitors the DonutSMP Public API for auction listings and transactions. The project provides real-time analytics, undervalued item detection, and a live web dashboard.

## Architecture
- **Backend**: Python Flask API server (`api.py`)
- **Frontend**: Single-page HTML dashboard (`dashboard.html`, `app.js`)
- **Scanner**: Background Python script (`scanner.py`) that polls the DonutSMP API
- **Database**: SQLite (`donutsmpah.db`) with time-series data and daily rollups

## Tech Stack
- Python 3.11
- Flask 3.1.2 + Flask-CORS 6.0.1
- SQLite3
- Vanilla JavaScript (no framework)
- Requests library for API calls

## Key Features
1. **Real-time Dashboard**: Live updates of auction listings and undervalued items
2. **Analytics**: Median/quantile/stddev price analysis per item
3. **Underpricing Detection**: Automatically identifies items priced below 70% of median
4. **Data Retention**: 7-day raw retention with permanent daily rollups
5. **Transaction History**: Tracks completed auction transactions
6. **Auto-compaction**: Periodic database cleanup to maintain performance

## File Structure
```
.
├── api.py              # Flask API server (port 5000)
├── scanner.py          # Background scanner (requires API key)
├── dashboard.html      # Frontend HTML
├── app.js             # Frontend JavaScript
├── config.ini         # Configuration file
├── requirements.txt   # Python dependencies
├── donutsmpah.db      # SQLite database (auto-created)
└── replit.md          # This file
```

## Configuration
The application uses `config.ini` for settings:
- Scanner: pages, interval, search filters, sort options
- Storage: retention days, compaction interval
- API: host and port settings

Environment variables override config.ini:
- `DONUTSMP_AUTH_KEY`: Required for scanner.py to access DonutSMP API
- `DONUTSMP_DB_PATH`: Custom database path (optional)

## Running the Application

### Web Dashboard (Current Workflow)
The Flask API server runs automatically on startup:
- Access the dashboard via the Webview
- API endpoints available at `/api/*`
- Database is auto-initialized on first run

### Scanner (Optional Background Process)
To populate data, you need to:
1. Get your API key from DonutSMP using `/api` in-game
2. Set the environment variable `DONUTSMP_AUTH_KEY`
3. Run: `python scanner.py`

The scanner will:
- Perform an initial full scan of all auction pages
- Poll the API every 30 seconds (configurable)
- Store listings and transactions in the database
- Automatically compact old data based on retention settings

## API Endpoints
- `GET /` - Main dashboard
- `GET /api/live` - Recent listings (last 5 minutes)
- `GET /api/undervalued` - Undervalued items (below 70% median)
- `GET /api/trend/<item_id>` - Price trend from daily rollups
- `GET /api/stats` - Global statistics

## Database Schema
- `listings`: Current auction listings
- `prices`: Historical price data
- `transactions`: Completed sales
- `events`: All listing/transaction events with timestamps
- `rollups_daily`: Daily aggregated price statistics

## Deployment
Configured for Replit Autoscale deployment:
- Runs on-demand when requests are received
- No persistent state required (SQLite database persists)
- Environment variables must be configured for scanner

## Recent Changes
- **2024-12-08**: Trading Assistant Upgrade
  - Redesigned dashboard as "DonutSMP Trading Assistant" with smart recommendations
  - Implemented priority scoring algorithm: 40% discount, 30% price stability, 30% data confidence
  - Added `/api/recommendations` endpoint with smart purchase recommendations
  - Added `/api/market-overview` endpoint showing most-traded items with volatility metrics
  - Enhanced `/api/undervalued` to include profit potential calculations
  - Fixed stats to properly count from events table (77K+ data points collected)
  - Improved styling with dark theme, responsive layout, and visual indicators
  
- **2024-12-08**: Initial Replit setup
  - Configured Flask to bind to 0.0.0.0:5000 for Replit proxy
  - Updated JavaScript to use relative API paths
  - Added database auto-initialization to api.py
  - Created .gitignore for Python
  - Configured autoscale deployment

## Notes
- The dashboard shows zero values until the scanner populates data
- Scanner requires `DONUTSMP_AUTH_KEY` environment variable
- Respects DonutSMP API rate limit (250 req/min)
- Database uses indexed time-series for efficient queries
