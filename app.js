const API_BASE = 'http://127.0.0.1:5000/api';
const POLL_INTERVAL = 3000; // 3 seconds

let statsInterval;
let undervaluedInterval;
let liveInterval;

function formatCurrency(val) {
    if (val === null || val === undefined) return 'N/A';
    return val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTimestamp(ts) {
    if (!ts) return '-';
    const date = new Date(ts);
    return date.toLocaleTimeString();
}

function formatTimeLeft(seconds) {
    if (!seconds || seconds <= 0) return 'Expired';
    // If value is very large, assume it's milliseconds
    if (seconds > 1000000) {
        seconds = Math.floor(seconds / 1000);
    }
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${minutes}m`;
    return `${minutes}m`;
}

function showError(message) {
    const container = document.getElementById('error-container');
    container.innerHTML = `<div class="error">${message}</div>`;
    setTimeout(() => {
        container.innerHTML = '';
    }, 5000);
}

async function fetchStats() {
    try {
        const response = await fetch(`${API_BASE}/stats`);
        const json = await response.json();
        if (json.status === 'ok') {
            document.getElementById('stat-events').textContent = json.data.total_events.toLocaleString();
            document.getElementById('stat-listings').textContent = json.data.total_listings.toLocaleString();
            document.getElementById('stat-transactions').textContent = json.data.total_transactions.toLocaleString();
            document.getElementById('stat-items').textContent = json.data.unique_items.toLocaleString();
        }
    } catch (err) {
        console.error('Stats fetch error:', err);
    }
}

async function fetchUndervalued() {
    try {
        const response = await fetch(`${API_BASE}/undervalued`);
        const json = await response.json();
        if (json.status === 'ok') {
            const container = document.getElementById('undervalued-container');
            if (json.data.length === 0) {
                container.innerHTML = '<div class="loading">No undervalued items found yet.</div>';
                return;
            }
            
            let html = '<table><thead><tr>';
            html += '<th>Item</th>';
            html += '<th>Count</th>';
            html += '<th>Price</th>';
            html += '<th>Median</th>';
            html += '<th>Discount</th>';
            html += '<th>Seller</th>';
            html += '<th>Time Left</th>';
            html += '</tr></thead><tbody>';
            
            json.data.forEach(item => {
                html += '<tr>';
                html += `<td>${item.item_name || item.item_id || 'Unknown'}</td>`;
                html += `<td>${item.count || '-'}</td>`;
                html += `<td class="price">${formatCurrency(item.price)}</td>`;
                html += `<td class="median">${formatCurrency(item.median)}</td>`;
                html += `<td class="discount">-${item.discount_pct}%</td>`;
                html += `<td>${item.seller || '-'}</td>`;
                html += `<td>${formatTimeLeft(item.time_left)}</td>`;
                html += '</tr>';
            });
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }
    } catch (err) {
        console.error('Undervalued fetch error:', err);
        showError('Failed to fetch undervalued listings');
    }
}

async function fetchLive() {
    try {
        const response = await fetch(`${API_BASE}/live`);
        const json = await response.json();
        if (json.status === 'ok') {
            const container = document.getElementById('live-container');
            if (json.data.length === 0) {
                container.innerHTML = '<div class="loading">No recent listings in the last 5 minutes.</div>';
                return;
            }
            
            let html = '<table><thead><tr>';
            html += '<th>Time</th>';
            html += '<th>Item</th>';
            html += '<th>Count</th>';
            html += '<th>Price</th>';
            html += '<th>Seller</th>';
            html += '<th>Time Left</th>';
            html += '</tr></thead><tbody>';
            
            json.data.forEach(item => {
                html += '<tr>';
                html += `<td class="timestamp">${formatTimestamp(item.ts)}</td>`;
                html += `<td>${item.item_name || item.item_id || 'Unknown'}</td>`;
                html += `<td>${item.count || '-'}</td>`;
                html += `<td class="price">${formatCurrency(item.price)}</td>`;
                html += `<td>${item.seller_name || '-'}</td>`;
                html += `<td>${formatTimeLeft(item.time_left)}</td>`;
                html += '</tr>';
            });
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }
    } catch (err) {
        console.error('Live fetch error:', err);
        showError('Failed to fetch live listings');
    }
}

function startPolling() {
    // Initial fetch
    fetchStats();
    fetchUndervalued();
    fetchLive();
    
    // Setup intervals
    statsInterval = setInterval(fetchStats, POLL_INTERVAL * 2); // Stats every 6s
    undervaluedInterval = setInterval(fetchUndervalued, POLL_INTERVAL);
    liveInterval = setInterval(fetchLive, POLL_INTERVAL);
}

// Start on page load
document.addEventListener('DOMContentLoaded', startPolling);

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    clearInterval(statsInterval);
    clearInterval(undervaluedInterval);
    clearInterval(liveInterval);
});
