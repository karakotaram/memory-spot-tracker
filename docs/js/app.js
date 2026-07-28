// Memory Spot Price Tracker - Dashboard

// Colorblind-safe categorical palette (validated: adjacent CVD ΔE >= 8, normal-vision ΔE >= 15).
const COLORS = [
    '#2a78d6', '#eb6834', '#1baf7a', '#eda100',
    '#e87ba4', '#008300', '#4a3aa7', '#e34948',
];

// A handful of source rows carry a typo'd product name on a single date — merge them.
const PRODUCT_ALIASES = {
    'DDR4 16Gb (2Gx8)3200': 'DDR4 16Gb (2Gx8) 3200',
    'DDR5 16G (2Gx8) 4800/5600': 'DDR5 16Gb (2Gx8) 4800/5600',
};

let dramData = [];
let nandData = [];
let currentCategory = 'dram';
let currentRange = 'ytd';
let priceChart = null;
let normalizedChart = null;

// Compact label drawn at the end of each line (the legend keeps the full name).
function shortLabel(p) {
    return p
        .replace(/\(.*?\)/g, ' ')
        .replace(/\d+GBx8|\d+MBx8|\d+Mx8/g, '')
        .replace(/1600\/1866|4800\/5600|3200|1866|1600/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

// Label each series at its last point, nudging apart any that would overlap.
const endLabelPlugin = {
    id: 'endLabels',
    afterDatasetsDraw(chart) {
        const { ctx, chartArea } = chart;
        const labels = [];
        chart.data.datasets.forEach((ds, i) => {
            const meta = chart.getDatasetMeta(i);
            if (meta.hidden) return;
            const pts = meta.data;
            if (!pts || !pts.length) return;
            const last = pts[pts.length - 1];
            if (!last) return;
            labels.push({ y: last.y, color: ds.borderColor, text: ds.shortLabel || ds.label });
        });
        if (!labels.length) return;
        labels.sort((a, b) => a.y - b.y);
        const gap = 13;
        for (let i = 1; i < labels.length; i++) {
            if (labels[i].y - labels[i - 1].y < gap) labels[i].y = labels[i - 1].y + gap;
        }
        const overflow = labels[labels.length - 1].y - chartArea.bottom;
        if (overflow > 0) labels.forEach(l => (l.y -= overflow));
        ctx.save();
        ctx.font = '600 10px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
        ctx.textBaseline = 'middle';
        labels.forEach(l => {
            ctx.fillStyle = l.color;
            ctx.fillText(l.text, chartArea.right + 6, l.y);
        });
        ctx.restore();
    },
};

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
        [dramData, nandData].forEach(rows => rows.forEach(r => {
            if (r.product && PRODUCT_ALIASES[r.product]) r.product = PRODUCT_ALIASES[r.product];
        }));
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

function ytdCutoff() {
    return `${new Date().getFullYear()}-01-01`;
}

function filterByRange(data, range) {
    if (range === '0' || range === 0) return data;
    let cutoffStr;
    if (range === 'ytd') {
        cutoffStr = ytdCutoff();
    } else {
        const cutoff = new Date();
        cutoff.setDate(cutoff.getDate() - parseInt(range, 10));
        cutoffStr = cutoff.toISOString().slice(0, 10);
    }
    return data.filter(r => r.date >= cutoffStr);
}

// YTD % move: first print on/after Jan 1 vs. the latest print.
function getYtdChange(data, product) {
    const cutoff = ytdCutoff();
    const rows = data
        .filter(r => r.product === product && r.date >= cutoff)
        .sort((a, b) => a.date.localeCompare(b.date));
    if (rows.length < 2) return null;
    const first = rows[0].session_avg;
    const last = rows[rows.length - 1].session_avg;
    if (!first) return null;
    return (last / first - 1) * 100;
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

        const ytd = getYtdChange(data, product);
        const ytdClass = ytd == null ? 'change-flat' : ytd > 0 ? 'change-up' : ytd < 0 ? 'change-down' : 'change-flat';
        const ytdStr = ytd == null ? '—'
            : `${ytd > 0 ? '▲' : ytd < 0 ? '▼' : '—'} ${ytd.toFixed(1)}%`;

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><a href="${sourceUrl}" target="_blank" class="source-link">${r.product}</a></td>
            <td class="num">${r.session_avg.toFixed(2)}</td>
            <td class="num">${r.daily_low.toFixed(2)}</td>
            <td class="num">${r.daily_high.toFixed(2)}</td>
            <td class="num ${changeClass}">${arrow} ${r.session_change_pct.toFixed(2)}%</td>
            <td class="num ${ytdClass}">${ytdStr}</td>
        `;
        tbody.appendChild(tr);
    }
}

function buildDatasets(data, normalize = false) {
    const filtered = filterByRange(data, currentRange);
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
            shortLabel: shortLabel(product),
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
        layout: { padding: { right: 92 } },
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
        plugins: [endLabelPlugin],
    });
}

function renderNormalizedChart(data) {
    const ctx = document.getElementById('normalized-chart').getContext('2d');
    if (normalizedChart) normalizedChart.destroy();

    normalizedChart = new Chart(ctx, {
        type: 'line',
        data: { datasets: buildDatasets(data, true) },
        options: chartOptions('Indexed (Base = 100)'),
        plugins: [endLabelPlugin],
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
        currentRange = btn.dataset.range;
        const data = getData();
        renderPriceChart(data);
        renderNormalizedChart(data);
    });
});

// --- Start ---
init();
