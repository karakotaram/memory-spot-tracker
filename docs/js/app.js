// Memory Spot Price Tracker - Dashboard

const COLORS = [
    '#2563eb', '#dc2626', '#16a34a', '#9333ea',
    '#ea580c', '#0891b2', '#ca8a04', '#be185d',
];

let dramData = [];
let nandData = [];
let currentCategory = 'dram';
let currentDays = 180;
let priceChart = null;
let normalizedChart = null;

// --- Data Loading ---

async function loadCSV(url) {
    const resp = await fetch(url);
    const text = await resp.text();
    return new Promise((resolve) => {
        Papa.parse(text, {
            header: true,
            dynamicTyping: true,
            skipEmptyLines: true,
            complete: (results) => resolve(results.data),
        });
    });
}

async function init() {
    try {
        [dramData, nandData] = await Promise.all([
            loadCSV('data/dram_spot.csv'),
            loadCSV('data/nand_spot.csv'),
        ]);
        updateLastUpdated();
        renderAll();
    } catch (err) {
        document.getElementById('last-updated').textContent = 'Error loading data';
        console.error('Failed to load data:', err);
    }
}

function updateLastUpdated() {
    const data = currentCategory === 'dram' ? dramData : nandData;
    if (data.length > 0) {
        const dates = data.map(r => r.date).sort();
        const latest = dates[dates.length - 1];
        document.getElementById('last-updated').textContent = `Last updated: ${latest}`;
    }
}

// --- Helpers ---

function getData() {
    return currentCategory === 'dram' ? dramData : nandData;
}

function getProducts(data) {
    return [...new Set(data.map(r => r.product))];
}

function filterByDays(data, days) {
    if (days === 0) return data;
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    const cutoffStr = cutoff.toISOString().slice(0, 10);
    return data.filter(r => r.date >= cutoffStr);
}

function getLatestByProduct(data) {
    const latest = {};
    for (const row of data) {
        if (!latest[row.product] || row.date > latest[row.product].date) {
            latest[row.product] = row;
        }
    }
    return latest;
}

// --- Render ---

function renderAll() {
    const data = getData();
    renderTable(data);
    renderPriceChart(data);
    renderNormalizedChart(data);
    updateLastUpdated();
}

function renderTable(data) {
    const latest = getLatestByProduct(data);
    const tbody = document.getElementById('price-tbody');
    tbody.innerHTML = '';

    for (const product of getProducts(data)) {
        const r = latest[product];
        if (!r) continue;

        const changeClass = r.session_change_pct > 0 ? 'change-up'
            : r.session_change_pct < 0 ? 'change-down' : 'change-flat';
        const arrow = r.session_change_pct > 0 ? '▲'
            : r.session_change_pct < 0 ? '▼' : '—';

        const sourceUrl = r.category === 'dram'
            ? 'https://www.trendforce.com/price/dram/dram_spot'
            : 'https://www.trendforce.com/price/flash/flash_spot';

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><a href="${sourceUrl}" target="_blank" class="source-link">${r.product}</a></td>
            <td class="num">${r.session_avg.toFixed(2)}</td>
            <td class="num">${r.daily_low.toFixed(2)}</td>
            <td class="num">${r.daily_high.toFixed(2)}</td>
            <td class="num ${changeClass}">${arrow} ${r.session_change_pct.toFixed(2)}%</td>
        `;
        tbody.appendChild(tr);
    }
}

function buildDatasets(data, normalize = false) {
    const filtered = filterByDays(data, currentDays);
    const products = getProducts(filtered);
    const datasets = [];

    products.forEach((product, i) => {
        const rows = filtered
            .filter(r => r.product === product)
            .sort((a, b) => a.date.localeCompare(b.date));

        if (rows.length === 0) return;

        const baseValue = normalize ? rows[0].session_avg : 1;
        const points = rows.map(r => ({
            x: r.date,
            y: normalize ? (r.session_avg / baseValue) * 100 : r.session_avg,
        }));

        datasets.push({
            label: product,
            data: points,
            borderColor: COLORS[i % COLORS.length],
            backgroundColor: COLORS[i % COLORS.length] + '20',
            borderWidth: 2,
            pointRadius: rows.length > 60 ? 0 : 3,
            pointHoverRadius: 5,
            tension: 0.1,
            fill: false,
        });
    });

    return datasets;
}

function chartOptions(yLabel) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            mode: 'index',
            intersect: false,
        },
        plugins: {
            legend: {
                position: 'bottom',
                labels: { boxWidth: 12, padding: 16, font: { size: 11 } },
            },
            tooltip: {
                backgroundColor: '#1a1a2e',
                titleFont: { size: 12 },
                bodyFont: { size: 11 },
                padding: 10,
                cornerRadius: 6,
            },
        },
        scales: {
            x: {
                type: 'time',
                time: { unit: 'day', tooltipFormat: 'MMM d, yyyy' },
                grid: { display: false },
                ticks: { font: { size: 10 }, maxTicksLimit: 10 },
            },
            y: {
                title: { display: true, text: yLabel, font: { size: 11 } },
                grid: { color: '#f0f0f0' },
                ticks: { font: { size: 10 } },
            },
        },
    };
}

function renderPriceChart(data) {
    const ctx = document.getElementById('price-chart').getContext('2d');
    if (priceChart) priceChart.destroy();

    priceChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: buildDatasets(data, false) },
        options: chartOptions('Price (USD)'),
    });
}

function renderNormalizedChart(data) {
    const ctx = document.getElementById('normalized-chart').getContext('2d');
    if (normalizedChart) normalizedChart.destroy();

    normalizedChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: buildDatasets(data, true) },
        options: chartOptions('Indexed (Base = 100)'),
    });
}

// --- Event Handlers ---

document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentCategory = btn.dataset.category;
        renderAll();
    });
});

document.querySelectorAll('.range-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentDays = parseInt(btn.dataset.days);
        const data = getData();
        renderPriceChart(data);
        renderNormalizedChart(data);
    });
});

// --- Start ---
init();
