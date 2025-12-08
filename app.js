const API_BASE = '/api';
const POLL_INTERVAL = 5000;

function formatCurrency(val) {
    if (val === null || val === undefined) return 'N/A';
    if (val >= 1000000000) return (val / 1000000000).toFixed(1) + 'B';
    if (val >= 1000000) return (val / 1000000).toFixed(1) + 'M';
    if (val >= 1000) return (val / 1000).toFixed(1) + 'K';
    return val.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function formatFullCurrency(val) {
    if (val === null || val === undefined) return 'N/A';
    return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTimeLeft(seconds) {
    if (!seconds || seconds <= 0) return 'Expired';
    if (seconds > 1000000) seconds = Math.floor(seconds / 1000);
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

function formatItemName(name) {
    if (!name) return 'Unknown';
    return name.replace('minecraft:', '').replace(/_/g, ' ');
}

function getPriorityClass(score) {
    if (score >= 70) return 'priority-high';
    if (score >= 50) return 'priority-medium';
    return 'priority-low';
}

function getVolatilityClass(vol) {
    if (vol < 30) return 'volatility-low';
    if (vol < 60) return 'volatility-medium';
    return 'volatility-high';
}

function showError(message) {
    const container = document.getElementById('error-container');
    container.innerHTML = `<div class="error">${message}</div>`;
    setTimeout(() => container.innerHTML = '', 5000);
}

async function fetchStats() {
    try {
        const response = await fetch(`${API_BASE}/stats`);
        const json = await response.json();
        if (json.status === 'ok') {
            const d = json.data;
            document.getElementById('stat-events').textContent = formatCurrency(d.total_events);
            document.getElementById('stat-listings').textContent = formatCurrency(d.total_listings);
            document.getElementById('stat-transactions').textContent = formatCurrency(d.total_transactions);
            document.getElementById('stat-items').textContent = d.unique_items.toLocaleString();
            document.getElementById('stat-hour').textContent = formatCurrency(d.events_last_hour);
            
            const hours = d.data_span_hours;
            let timeText = '';
            if (hours >= 24) {
                timeText = `${Math.round(hours / 24)} days of data`;
            } else {
                timeText = `${Math.round(hours)} hours of data`;
            }
            document.getElementById('stat-hours').textContent = timeText;
        }
    } catch (err) {
        console.error('Stats fetch error:', err);
    }
}

async function fetchRecommendations() {
    const container = document.getElementById('recommendations-container');
    const badge = document.getElementById('rec-count');
    try {
        const response = await fetch(`${API_BASE}/recommendations`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const json = await response.json();
        if (json.status === 'ok' && json.data) {
            badge.textContent = json.data.length;
            
            if (json.data.length === 0) {
                container.innerHTML = '<div class="loading">No strong recommendations yet. Collecting more data...</div>';
                return;
            }
            
            let html = '<table><thead><tr>';
            html += '<th>Score</th>';
            html += '<th>Item</th>';
            html += '<th>Price</th>';
            html += '<th>Median</th>';
            html += '<th>Profit</th>';
            html += '<th>Confidence</th>';
            html += '<th>Time</th>';
            html += '</tr></thead><tbody>';
            
            json.data.slice(0, 20).forEach(item => {
                const priorityClass = getPriorityClass(item.priority_score);
                html += '<tr>';
                html += `<td><div class="priority-score ${priorityClass}">${item.priority_score}</div></td>`;
                html += `<td class="item-name" title="${item.item_name}">${formatItemName(item.item_name)}</td>`;
                html += `<td class="price">${formatCurrency(item.current_price)}</td>`;
                html += `<td class="median">${formatCurrency(item.median_price)}</td>`;
                html += `<td class="profit">+${formatCurrency(item.profit_potential)}</td>`;
                html += `<td><div class="confidence-bar"><div class="fill" style="width:${item.confidence}%"></div></div></td>`;
                html += `<td class="time-left">${formatTimeLeft(item.time_left)}</td>`;
                html += '</tr>';
            });
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }
    } catch (err) {
        console.error('Recommendations fetch error:', err);
        container.innerHTML = `<div class="loading" style="color:#e74c3c">Error loading: ${err.message}</div>`;
    }
}

async function fetchUndervalued() {
    const container = document.getElementById('undervalued-container');
    const badge = document.getElementById('deals-count');
    try {
        const response = await fetch(`${API_BASE}/undervalued`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const json = await response.json();
        if (json.status === 'ok' && json.data) {
            badge.textContent = json.data.length;
            
            if (json.data.length === 0) {
                container.innerHTML = '<div class="loading">No undervalued items found yet.</div>';
                return;
            }
            
            let html = '<table><thead><tr>';
            html += '<th>Item</th>';
            html += '<th>Qty</th>';
            html += '<th>Price</th>';
            html += '<th>Median</th>';
            html += '<th>Discount</th>';
            html += '<th>Est. Profit</th>';
            html += '<th>Seller</th>';
            html += '</tr></thead><tbody>';
            
            json.data.slice(0, 25).forEach(item => {
                html += '<tr>';
                html += `<td class="item-name" title="${item.item_name}">${formatItemName(item.item_name)}</td>`;
                html += `<td>${item.count || 1}</td>`;
                html += `<td class="price">${formatCurrency(item.price)}</td>`;
                html += `<td class="median">${formatCurrency(item.median)}</td>`;
                html += `<td><span class="discount">-${item.discount_pct}%</span></td>`;
                html += `<td class="profit">+${formatCurrency(item.profit_potential)}</td>`;
                html += `<td class="seller">${item.seller || '-'}</td>`;
                html += '</tr>';
            });
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }
    } catch (err) {
        console.error('Undervalued fetch error:', err);
        showError('Failed to fetch deals');
    }
}

async function fetchMarketOverview() {
    try {
        const response = await fetch(`${API_BASE}/market-overview`);
        const json = await response.json();
        if (json.status === 'ok') {
            const container = document.getElementById('market-container');
            
            if (json.data.length === 0) {
                container.innerHTML = '<div class="loading">No market data yet.</div>';
                return;
            }
            
            let html = '<table><thead><tr>';
            html += '<th>Item</th>';
            html += '<th>Trades</th>';
            html += '<th>Median Price</th>';
            html += '<th>Min</th>';
            html += '<th>Max</th>';
            html += '<th>Volatility</th>';
            html += '<th>Samples</th>';
            html += '</tr></thead><tbody>';
            
            json.data.forEach(item => {
                const volClass = getVolatilityClass(item.volatility);
                html += '<tr>';
                html += `<td class="item-name" title="${item.item_name}">${formatItemName(item.item_name)}</td>`;
                html += `<td>${item.trade_count.toLocaleString()}</td>`;
                html += `<td class="median">${formatCurrency(item.median)}</td>`;
                html += `<td class="price">${formatCurrency(item.min)}</td>`;
                html += `<td>${formatCurrency(item.max)}</td>`;
                html += `<td class="${volClass}">${item.volatility}%</td>`;
                html += `<td>${item.sample_size}</td>`;
                html += '</tr>';
            });
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }
    } catch (err) {
        console.error('Market overview fetch error:', err);
    }
}

async function fetchLive() {
    try {
        const response = await fetch(`${API_BASE}/live`);
        const json = await response.json();
        if (json.status === 'ok') {
            const container = document.getElementById('live-container');
            
            if (json.data.length === 0) {
                container.innerHTML = '<div class="loading">No recent listings in the last 5 minutes. Scanner may be paused.</div>';
                return;
            }
            
            let html = '<table><thead><tr>';
            html += '<th>Item</th>';
            html += '<th>Qty</th>';
            html += '<th>Price</th>';
            html += '<th>Seller</th>';
            html += '<th>Time Left</th>';
            html += '</tr></thead><tbody>';
            
            json.data.slice(0, 30).forEach(item => {
                html += '<tr>';
                html += `<td class="item-name" title="${item.item_name}">${formatItemName(item.item_name)}</td>`;
                html += `<td>${item.count || 1}</td>`;
                html += `<td class="price">${formatCurrency(item.price)}</td>`;
                html += `<td class="seller">${item.seller_name || '-'}</td>`;
                html += `<td class="time-left">${formatTimeLeft(item.time_left)}</td>`;
                html += '</tr>';
            });
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }
    } catch (err) {
        console.error('Live fetch error:', err);
    }
}

function startPolling() {
    fetchStats();
    fetchRecommendations();
    fetchUndervalued();
    fetchMarketOverview();
    fetchLive();
    
    setInterval(fetchStats, POLL_INTERVAL * 2);
    setInterval(fetchRecommendations, POLL_INTERVAL * 2);
    setInterval(fetchUndervalued, POLL_INTERVAL);
    setInterval(fetchMarketOverview, POLL_INTERVAL * 4);
    setInterval(fetchLive, POLL_INTERVAL);
}

document.addEventListener('DOMContentLoaded', startPolling);
