let activeTaskId = null;
let pollInterval = null;
let allResults = [];

function updateDepthLabel(val) {
    const approx = val * 20;
    document.getElementById('pages-val').textContent = `${val} (approx. ${approx - 10}-${approx + 20} leads)`;
}

function setPreset(query, places, pages) {
    document.getElementById('query-input').value = query;
    document.getElementById('places-input').value = places;
    document.getElementById('pages-slider').value = pages;
    updateDepthLabel(pages);
}

document.getElementById('scrape-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    const query = document.getElementById('query-input').value.trim();
    const places = document.getElementById('places-input').value.trim();
    const pages = parseInt(document.getElementById('pages-slider').value);
    const skipDuplicates = document.getElementById('skip-duplicates').checked;
    const scrapeWebsite = document.getElementById('scrape-website').checked;

    if (!query || !places) {
        alert('Please fill in both query and places.');
        return;
    }

    setScrapingState(true);
    clearResults();
    logEntry(`Starting scraper for: "${query}" in "${places}"...`, 'info');

    try {
        const response = await fetch('/api/scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: query,
                places: places,
                pages: pages,
                skip_duplicates: skipDuplicates,
                scrape_website: scrapeWebsite
            })
        });

        const data = await response.json();
        if (data.success) {
            activeTaskId = data.task_id;
            document.getElementById('table-subtitle').textContent = `Searching: ${query} in ${places}`;
            startPolling(activeTaskId);
        } else {
            logEntry(`Failed to start: ${data.error}`, 'error');
            setScrapingState(false);
        }
    } catch (err) {
        logEntry(`Network error: ${err.message}`, 'error');
        setScrapingState(false);
    }
});

function startPolling(taskId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        try {
            const res = await fetch(`/api/status/${taskId}`);
            if (!res.ok) throw new Error('Task not found');
            const data = await res.json();

            // Update stats
            document.getElementById('stat-time').textContent = `${data.elapsed}s`;
            document.getElementById('stat-total').textContent = data.count;
            
            // Logs
            updateLogs(data.logs);

            // Results Table
            if (data.results && data.results.length !== allResults.length) {
                allResults = data.results;
                renderTable(allResults);
                updateWebPhoneStats(allResults);
            }

            // Check if finished or stopped
            if (data.status === 'completed' || data.status === 'failed' || data.status === 'stopped') {
                clearInterval(pollInterval);
                setScrapingState(false);
                
                if (data.count > 0) {
                    enableDownloadButtons(taskId);
                }

                if (data.status === 'completed') {
                    logEntry(`Completed! Extracted ${data.count} leads in ${data.elapsed}s.`, 'success');
                } else if (data.status === 'stopped') {
                    logEntry(`Scraper stopped. Saved ${data.count} leads.`, 'info');
                } else {
                    logEntry(`Scraper stopped with an issue.`, 'error');
                }
            }
        } catch (err) {
            console.error(err);
        }
    }, 800);
}

async function stopCurrentScrape() {
    if (!activeTaskId) return;
    
    logEntry('Stopping scraper immediately...', 'system');
    const stopBtn = document.getElementById('stop-btn');
    stopBtn.disabled = true;
    stopBtn.innerHTML = '<span>Stopping...</span>';

    try {
        await fetch(`/api/stop/${activeTaskId}`, { method: 'POST' });
    } catch (err) {
        console.error(err);
    }

    if (pollInterval) clearInterval(pollInterval);
    setTimeout(() => {
        setScrapingState(false);
        if (allResults.length > 0) {
            enableDownloadButtons(activeTaskId);
        }
        logEntry(`Scraper stopped. ${allResults.length} leads preserved.`, 'info');
    }, 500);
}

function setScrapingState(isScraping) {
    const startBtn = document.getElementById('start-btn');
    const stopBtn = document.getElementById('stop-btn');
    const liveIndicator = document.getElementById('live-indicator');
    const statusPill = document.getElementById('server-status');

    if (isScraping) {
        startBtn.style.display = 'none';
        stopBtn.style.display = 'inline-flex';
        stopBtn.disabled = false;
        stopBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="6" y="6" width="12" height="12"></rect>
            </svg>
            <span>Stop</span>
        `;
        liveIndicator.style.display = 'inline-block';
        statusPill.innerHTML = '<span class="status-dot" style="background:#06B6D4;box-shadow:0 0 10px #06B6D4;"></span> Scraping Active';
    } else {
        startBtn.style.display = 'inline-flex';
        stopBtn.style.display = 'none';
        liveIndicator.style.display = 'none';
        statusPill.innerHTML = '<span class="status-dot"></span> System Ready';
    }
}

function clearResults() {
    allResults = [];
    document.getElementById('results-body').innerHTML = `
        <tr class="empty-state">
            <td colspan="6">
                <div class="empty-content">
                    <div class="empty-icon">⏳</div>
                    <h3>Scraping In Progress...</h3>
                    <p>Results will stream in within seconds.</p>
                </div>
            </td>
        </tr>
    `;
    document.getElementById('stat-total').textContent = '0';
    document.getElementById('stat-website').textContent = '0';
    document.getElementById('stat-phone').textContent = '0';
    document.getElementById('stat-time').textContent = '0.0s';
    
    document.getElementById('download-excel-btn').classList.add('disabled');
    document.getElementById('download-csv-btn').classList.add('disabled');
}

function renderTable(results) {
    const tbody = document.getElementById('results-body');
    if (!results || results.length === 0) return;

    tbody.innerHTML = results.map((item, index) => {
        const hasWeb = item.has_website === 'Yes';
        const webHtml = hasWeb && item.website 
            ? `<a href="${item.website}" target="_blank" rel="noopener" class="link-btn">
                🌐 Visit Site
               </a>`
            : `<span class="badge badge-no">None</span>`;

        const mapsHtml = item.maps_link 
            ? `<a href="${item.maps_link}" target="_blank" rel="noopener" class="link-btn maps-btn">
                📍 Open Maps
               </a>`
            : `<span class="badge badge-no">N/A</span>`;

        return `
            <tr>
                <td style="color: var(--text-dim); font-weight: 600;">${index + 1}</td>
                <td><strong>${escapeHtml(item.name)}</strong></td>
                <td><span style="font-family: monospace; color: var(--accent-cyan);">${escapeHtml(item.phone || 'N/A')}</span></td>
                <td><small style="color: var(--text-muted);">${escapeHtml(item.address || 'N/A')}</small></td>
                <td>${webHtml}</td>
                <td>${mapsHtml}</td>
            </tr>
        `;
    }).join('');
}

function updateWebPhoneStats(results) {
    let withWeb = 0;
    let withPhone = 0;
    for (const r of results) {
        if (r.has_website === 'Yes' || r.website) withWeb++;
        if (r.phone && r.phone !== 'N/A') withPhone++;
    }
    document.getElementById('stat-website').textContent = withWeb;
    document.getElementById('stat-phone').textContent = withPhone;
}

function filterTable() {
    const term = document.getElementById('filter-input').value.toLowerCase();
    const rows = document.querySelectorAll('#results-body tr');
    rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(term) ? '' : 'none';
    });
}

function enableDownloadButtons(taskId) {
    const excelBtn = document.getElementById('download-excel-btn');
    const csvBtn = document.getElementById('download-csv-btn');

    excelBtn.href = `/api/download/${taskId}`;
    excelBtn.classList.remove('disabled');

    csvBtn.href = `/api/download-csv/${taskId}`;
    csvBtn.classList.remove('disabled');
}

function updateLogs(logs) {
    if (!logs) return;
    const consoleEl = document.getElementById('logs-console');
    consoleEl.innerHTML = logs.map(l => `<div class="log-entry">${escapeHtml(l)}</div>`).join('');
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

function logEntry(msg, type = 'info') {
    const consoleEl = document.getElementById('logs-console');
    const div = document.createElement('div');
    div.className = `log-entry ${type}`;
    div.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    consoleEl.appendChild(div);
    consoleEl.scrollTop = consoleEl.scrollHeight;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
