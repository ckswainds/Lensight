/* =================================================================
   LENSIGHT AI — Professional Equity Research Platform
   Frontend Application Logic
================================================================= */

'use strict';

// ── Chart registry — track all Chart.js instances ──
const _charts = new Map();

// ── State ──
let cachedData       = null;
let chatHistory      = [];
let activePeriodYears = 0;   // 0 = All
let pollInterval     = null;
let ragPollInterval  = null;
let currentPage      = 'overview';

// ── All ratio categories and their metrics ──
const METRIC_GROUPS = [
    {
        id: 'profitability', label: 'Profitability', color: '#8b5cf6',
        metrics: [
            { key: 'net_profit_margin',   label: 'Net Profit Margin',   unit: '%',    type: 'line' },
            { key: 'op_profit_margin',    label: 'Operating Margin',    unit: '%',    type: 'line' },
            { key: 'ebitda_margin',       label: 'EBITDA Margin',       unit: '%',    type: 'line' },
            { key: 'roe',                 label: 'ROE',                 unit: '%',    type: 'bar'  },
            { key: 'roce',                label: 'ROCE',                unit: '%',    type: 'bar'  },
            { key: 'roa',                 label: 'ROA',                 unit: '%',    type: 'bar'  },
        ]
    },
    {
        id: 'valuation', label: 'Valuation', color: '#3b82f6',
        metrics: [
            { key: 'pe_ratio',        label: 'P/E Ratio',        unit: 'x',  type: 'bar' },
            { key: 'pb_ratio',        label: 'P/B Ratio',        unit: 'x',  type: 'bar' },
            { key: 'ev_ebitda',       label: 'EV / EBITDA',      unit: 'x',  type: 'bar' },
            { key: 'mktcap_to_sales', label: 'Market Cap / Sales', unit: 'x', type: 'bar' },
        ]
    },
    {
        id: 'leverage', label: 'Leverage', color: '#f59e0b',
        metrics: [
            { key: 'debt_to_equity',   label: 'Debt / Equity',      unit: 'x',  type: 'bar' },
            { key: 'debt_to_assets',   label: 'Debt / Assets',      unit: 'x',  type: 'bar' },
            { key: 'interest_coverage', label: 'Interest Coverage',  unit: 'x',  type: 'bar' },
        ]
    },
    {
        id: 'liquidity', label: 'Liquidity', color: '#10b981',
        metrics: [
            { key: 'current_ratio',   label: 'Current Ratio',   unit: 'x',  type: 'bar' },
            { key: 'cash_ratio',      label: 'Cash Ratio',      unit: 'x',  type: 'bar' },
        ]
    },
    {
        id: 'efficiency', label: 'Efficiency', color: '#06b6d4',
        metrics: [
            { key: 'asset_turnover',          label: 'Asset Turnover',     unit: 'x',    type: 'bar'  },
            { key: 'inventory_turnover_days', label: 'Inventory Days',     unit: ' days', type: 'bar' },
            { key: 'receivables_days',        label: 'Receivables Days',   unit: ' days', type: 'bar' },
        ]
    },
    {
        id: 'per_share', label: 'Per Share', color: '#ec4899',
        metrics: [
            { key: 'eps',                  label: 'EPS',               unit: '',  type: 'bar' },
            { key: 'book_value_per_share', label: 'Book Value / Share', unit: '',  type: 'bar' },
            { key: 'dividend_per_share',   label: 'Dividend / Share',   unit: '',  type: 'bar' },
        ]
    },
];

// KPIs shown in the Overview quick-panel (category, ratioKey)
const OVERVIEW_KPIS = [
    ['profitability', 'roe',              'ROE'],
    ['profitability', 'roce',             'ROCE'],
    ['profitability', 'net_profit_margin','Net Profit Margin'],
    ['profitability', 'ebitda_margin',    'EBITDA Margin'],
    ['valuation',     'pe_ratio',         'P/E Ratio'],
    ['valuation',     'pb_ratio',         'P/B Ratio'],
    ['valuation',     'ev_ebitda',        'EV/EBITDA'],
    ['leverage',      'debt_to_equity',   'Debt/Equity'],
    ['leverage',      'interest_coverage','Interest Coverage'],
    ['liquidity',     'current_ratio',    'Current Ratio'],
    ['liquidity',     'cash_ratio',       'Cash Ratio'],
    ['per_share',     'eps',              'EPS'],
    ['per_share',     'book_value_per_share','Book Value/Share'],
    ['efficiency',    'asset_turnover',   'Asset Turnover'],
];

/* =================================================================
   HELPERS
================================================================= */

function getEl(id) { return document.getElementById(id); }

function labelClass(label) {
    const map = {
        excellent: 'lbl-excellent', strong: 'lbl-strong', good: 'lbl-good',
        average: 'lbl-average', fair: 'lbl-fair', weak: 'lbl-weak',
        poor: 'lbl-poor', negative: 'lbl-negative', low: 'lbl-low',
        undervalued: 'lbl-undervalued', cheap: 'lbl-cheap',
        expensive: 'lbl-expensive', very_expensive: 'lbl-very_expensive',
    };
    return map[label] || 'lbl-default';
}

function trendMeta(trend) {
    const map = {
        strong_uptrend:   { icon: '↑',  cls: 'trend-up',    text: 'Strong Uptrend'   },
        uptrend:          { icon: '↗',  cls: 'trend-mup',   text: 'Uptrend'          },
        improving:        { icon: '↗',  cls: 'trend-mup',   text: 'Improving'        },
        stable:           { icon: '→',  cls: 'trend-flat',  text: 'Stable'           },
        declining:        { icon: '↘',  cls: 'trend-mdown', text: 'Declining'        },
        downtrend:        { icon: '↘',  cls: 'trend-mdown', text: 'Downtrend'        },
        strong_downtrend: { icon: '↓',  cls: 'trend-down',  text: 'Strong Downtrend'},
        volatile:         { icon: '⟡',  cls: 'trend-vol',   text: 'Volatile'        },
    };
    return map[trend] || { icon: '–', cls: 'trend-flat', text: trend || '–' };
}

function scoreColorClass(score) {
    if (score >= 4.5) return 'score-5';
    if (score >= 3.5) return 'score-4';
    if (score >= 2.5) return 'score-3';
    if (score >= 1.5) return 'score-2';
    return 'score-1';
}
function scoreBarClass(score) { return scoreColorClass(score).replace('score-', 'score-bar-'); }

function formatVal(v, unit) {
    if (v === null || v === undefined) return '—';
    const num = parseFloat(v);
    if (isNaN(num)) return '—';
    const formatted = Math.abs(num) >= 1000
        ? num.toLocaleString('en-IN', { maximumFractionDigits: 1 })
        : num.toFixed(2);
    return formatted + (unit || '');
}

/** Extract series array from analysis.json nested format */
function extractSeries(data, category, ratioKey, periods) {
    const cat = data[category];
    if (!cat) return periods.map(() => null);
    const ratio = cat[ratioKey];
    if (!ratio || !ratio.values) return periods.map(() => null);
    return periods.map(p => {
        const v = ratio.values[p];
        return (v === null || v === undefined) ? NaN : v;
    });
}

/** Filter periods by last N years (0 = all) */
function filterPeriods(allPeriods, years) {
    if (!years) return allPeriods;
    // Only annual (non-TTM) periods — exclude TTM (non-March) if possible
    const annual = allPeriods.filter(p => {
        const m = new Date(p).getMonth() + 1; // 1-12
        return m === 3; // March year-end — most Indian companies
    });
    const base = annual.length > 0 ? annual : allPeriods;
    return years >= base.length ? base : base.slice(-years);
}

/** Period labels for chart X-axis */
function periodLabels(periods) {
    return periods.map(p => {
        const d = new Date(p);
        const mon = d.toLocaleString('en', { month: 'short' });
        return `${mon} '${String(d.getFullYear()).slice(2)}`;
    });
}

/* =================================================================
   CHART FACTORY
================================================================= */

const CHART_DEFAULTS = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 400 },
    plugins: {
        legend: { display: false },
        tooltip: {
            backgroundColor: 'rgba(6,11,20,0.92)',
            titleColor: '#e8edf5',
            bodyColor: '#8899b0',
            borderColor: 'rgba(139,92,246,0.3)',
            borderWidth: 1,
            padding: 10,
            cornerRadius: 8,
        }
    },
    scales: {
        x: {
            ticks: { color: '#4b6080', font: { family: 'Inter', size: 10 }, maxRotation: 45 },
            grid: { color: 'rgba(255,255,255,0.04)' },
        },
        y: {
            ticks: { color: '#4b6080', font: { family: 'Inter', size: 10 } },
            grid: { color: 'rgba(255,255,255,0.04)' },
        }
    }
};

function makeChart(canvasId, type, labels, datasets, extra = {}) {
    const existing = _charts.get(canvasId);
    if (existing) { existing.destroy(); }

    const canvas = getEl(canvasId);
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');

    const cfg = {
        type,
        data: { labels, datasets },
        options: { ...CHART_DEFAULTS, ...extra }
    };

    const chart = new Chart(ctx, cfg);
    _charts.set(canvasId, chart);
    return chart;
}

function destroyAllCharts() {
    _charts.forEach(c => c.destroy());
    _charts.clear();
}

/* =================================================================
   UPLOAD FLOW
================================================================= */

// File input listeners
getEl('excel-input').addEventListener('change', e => {
    const f = e.target.files[0];
    getEl('excel-label').textContent = f ? f.name : 'Financial Data';
    getEl('excel-zone').classList.toggle('active-file', !!f);
});
getEl('pdf-input').addEventListener('change', e => {
    const f = e.target.files[0];
    getEl('pdf-label').textContent = f ? f.name : 'Annual Report';
    getEl('pdf-zone').classList.toggle('active-file', !!f);
});

getEl('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const excelFile = getEl('excel-input').files[0];
    if (!excelFile) return;

    const btn     = getEl('analyze-btn');
    const btnText = getEl('analyze-btn-text');
    const tracker = getEl('processing-tracker');

    btn.disabled = true;
    btnText.textContent = 'Uploading...';
    tracker.classList.remove('hidden');

    const fd = new FormData();
    fd.append('excel_file', excelFile);
    const pdfFile = getEl('pdf-input').files[0];
    if (pdfFile) fd.append('pdf_file', pdfFile);

    try {
        const res = await fetch('/api/upload', { method: 'POST', body: fd });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        btnText.textContent = 'Analyzing...';
        pollInterval = setInterval(pollStatus, 1000);
    } catch (err) {
        alert('Upload Error: ' + err.message);
        btn.disabled = false;
        btnText.textContent = 'Run Analysis';
        tracker.classList.add('hidden');
    }
});

async function pollStatus() {
    try {
        const res = await fetch('/api/status');
        const st  = await res.json();

        // Update progress bar
        getEl('pipeline-progress').style.width = `${st.progress}%`;
        getEl('pipeline-stage').textContent    = st.label;
        getEl('pipeline-pct').textContent      = `${st.progress}%`;

        // RAG tracker
        if (st.rag_status !== 'idle') {
            getEl('rag-tracker-container').classList.remove('hidden');
            getEl('rag-progress').style.width = `${st.rag_progress}%`;
            getEl('rag-stage').textContent    = st.rag_label;
        }

        if (st.stage === 'done') {
            clearInterval(pollInterval);
            await loadDashboard(st);
        } else if (st.stage === 'error') {
            clearInterval(pollInterval);
            alert('Pipeline Error: ' + (st.error || 'Unknown error'));
            resetToUpload();
        }
    } catch (err) {
        console.error('Poll error:', err);
    }
}

/* =================================================================
   DASHBOARD LOAD & SWITCH
================================================================= */

async function loadDashboard(statusData) {
    try {
        const res = await fetch('/api/analysis');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        cachedData = await res.json();
    } catch (err) {
        alert('Failed to load analysis: ' + err.message);
        resetToUpload();
        return;
    }

    const company = cachedData.company || statusData?.company || '—';
    const periods  = cachedData.periods || [];
    const latest   = cachedData.latest_period || (periods.length ? periods[periods.length - 1] : '—');
    const scores   = cachedData.summary_scores || {};

    // Sidebar
    getEl('sb-company-name').textContent = company;
    getEl('sb-period').textContent       = `Latest: ${latest}`;
    const scoreVal = scores.overall_score;
    const sbScore  = getEl('sb-overall-score');
    sbScore.textContent = scoreVal != null ? scoreVal.toFixed(1) + ' / 5' : '—';
    sbScore.className   = 'sb-score-value ' + (scoreVal != null ? scoreColorClass(scoreVal) : '');

    // Topbar
    getEl('topbar-company').textContent = company;

    // Switch views
    getEl('upload-view').classList.add('hidden');
    getEl('dashboard-view').classList.remove('hidden');

    // Render pages
    renderOverview();
    renderAnalysis();

    // RAG and Summary status — pass full status object so panels reflect real state
    updateRagState(statusData || { rag_status: 'idle', rag_progress: 0, rag_label: '' });
    updateSummaryState(statusData || { summary_status: 'idle' });
    pollBackgroundTasks();

    // Navigate to overview by default
    navigateTo('overview');
}

/* =================================================================
   NAVIGATION
================================================================= */

function navigateTo(page) {
    currentPage = page;

    // Update sidebar active state
    document.querySelectorAll('.sb-nav-item').forEach(el => {
        el.classList.toggle('active', el.dataset.page === page);
    });

    // Show/hide page sections
    const pages = ['overview', 'analysis', 'chat'];
    pages.forEach(p => {
        const el = getEl(`page-${p}`);
        if (el) el.classList.toggle('hidden', p !== page);
    });

    // Update topbar
    const titles = { overview: 'Overview', analysis: 'Charts & Ratios', chat: 'AI Research' };
    getEl('topbar-title').textContent = titles[page] || page;
}

document.querySelectorAll('.sb-nav-item').forEach(el => {
    el.addEventListener('click', (e) => {
        e.preventDefault();
        if (cachedData) navigateTo(el.dataset.page);
    });
});

/* =================================================================
   OVERVIEW PAGE
================================================================= */

function renderOverview() {
    if (!cachedData) return;

    const scores  = cachedData.summary_scores || {};
    const periods  = cachedData.periods || [];
    const latest   = cachedData.latest_period || (periods.length ? periods[periods.length - 1] : '—');

    // Score row
    const scoreRow = getEl('score-row');
    scoreRow.innerHTML = '';

    // Overall score card
    const overall = scores.overall_score;
    const overallCard = document.createElement('div');
    overallCard.className = 'overall-score-card';
    overallCard.innerHTML = `
        <div class="overall-score-label">Overall Score</div>
        <div class="overall-score-value ${overall != null ? scoreColorClass(overall) : ''}">${overall != null ? overall.toFixed(1) : '—'}</div>
        <div class="overall-score-max">out of 5.0</div>
    `;
    scoreRow.appendChild(overallCard);

    // Category scores
    const cats = [
        ['profitability', 'Profitability'],
        ['valuation',     'Valuation'],
        ['leverage',      'Leverage'],
        ['liquidity',     'Liquidity'],
        ['efficiency',    'Efficiency'],
        ['per_share',     'Per Share'],
        ['growth',        'Growth'],
    ];
    const cGrid = document.createElement('div');
    cGrid.className = 'category-scores-grid';
    cats.forEach(([key, label]) => {
        const s = scores[`${key}_score`];
        const pct = s != null ? (s / 5) * 100 : 0;
        const card = document.createElement('div');
        card.className = 'cat-score-card';
        card.innerHTML = `
            <div class="cat-score-name">${label}</div>
            <div class="cat-score-val ${s != null ? scoreColorClass(s) : ''}">${s != null ? s.toFixed(1) : '—'}</div>
            <div class="cat-score-bar-track">
                <div class="cat-score-bar-fill ${s != null ? scoreBarClass(s) : ''}" style="width:${pct}%"></div>
            </div>
        `;
        cGrid.appendChild(card);
    });
    scoreRow.appendChild(cGrid);

    // Latest period badge
    getEl('ov-latest-period').textContent = latest;

    // KPI grid
    const kpiGrid = getEl('kpi-grid');
    kpiGrid.innerHTML = '';
    OVERVIEW_KPIS.forEach(([cat, key, name]) => {
        const catData = cachedData[cat];
        if (!catData) return;
        const ratio = catData[key];
        if (!ratio) return;
        const val   = ratio.latest_value;
        const lbl   = ratio.latest_label || '';
        const trend = ratio.trend || '';
        const tm    = trendMeta(trend);
        const card  = document.createElement('div');
        card.className = 'kpi-card';

        // Determine unit from METRIC_GROUPS
        let unit = '';
        METRIC_GROUPS.forEach(g => {
            if (g.id === cat) {
                const m = g.metrics.find(m => m.key === key);
                if (m) unit = m.unit;
            }
        });

        card.innerHTML = `
            <div class="kpi-cat">${cat.replace('_', ' ')}</div>
            <div class="kpi-name">${name}</div>
            <div class="kpi-value">${val != null ? parseFloat(val).toFixed(2) : '—'}${val != null ? unit : ''}</div>
            <div class="kpi-bottom">
                <span class="kpi-label ${labelClass(lbl)}">${lbl || '—'}</span>
                <span class="kpi-trend ${tm.cls}">${tm.icon} ${tm.text}</span>
            </div>
        `;
        kpiGrid.appendChild(card);
    });

    // AI Summary
    const summaryEl  = getEl('ai-summary');
    const llmSummary = cachedData.llm_financial_summary;
    if (llmSummary && llmSummary.trim()) {
        summaryEl.innerHTML = marked.parse(llmSummary);
    } else {
        summaryEl.innerHTML = buildQuickSummary();
    }

    // Growth table
    renderGrowthTable();
}

function buildQuickSummary() {
    if (!cachedData) return '<em>No data</em>';
    const scores   = cachedData.summary_scores || {};
    const company  = cachedData.company || '';
    const overall  = scores.overall_score;
    const prof     = cachedData.profitability || {};
    const periods  = cachedData.periods || [];
    const from     = periods[0] || '';
    const to       = periods[periods.length - 1] || '';

    let html = `<p><strong>${company}</strong> — Analysis from <em>${from}</em> to <em>${to}</em>.</p>`;
    if (overall !== null && overall !== undefined) {
        html += `<p>Overall investment quality score: <strong class="${scoreColorClass(overall)}">${overall.toFixed(1)} / 5</strong>.</p>`;
    }
    html += '<ul>';
    [['roe','ROE'], ['roce','ROCE'], ['net_profit_margin','Net Profit Margin'], ['ebitda_margin','EBITDA Margin']].forEach(([k, lbl]) => {
        const r = prof[k];
        if (r && r.latest_value != null) {
            const tm = trendMeta(r.trend);
            html += `<li><strong>${lbl}:</strong> ${r.latest_value.toFixed(2)}% &nbsp; <span class="${tm.cls}">${tm.icon} ${tm.text}</span></li>`;
        }
    });
    html += '</ul>';
    return html;
}

function renderGrowthTable() {
    const growth = cachedData.growth || {};
    const wrap   = getEl('growth-table');
    if (!Object.keys(growth).length) { wrap.innerHTML = '<p style="padding:16px;color:var(--text-muted)">No CAGR data available.</p>'; return; }

    // Build structured data: metric → {3y, 5y, 7y, 10y}
    const metrics = {};
    Object.entries(growth).forEach(([key, g]) => {
        const match = key.match(/^(.+)_cagr_(\d+)y$/);
        if (!match) return;
        const [, base, yrs] = match;
        if (!metrics[base]) metrics[base] = {};
        metrics[base][yrs] = g;
    });

    const windows = ['3', '5', '7', '10'].filter(y =>
        Object.values(metrics).some(m => m[y])
    );

    const nameMap = { sales: 'Sales', net_profit: 'Net Profit' };

    let html = `<table class="growth-table">
        <thead><tr>
            <th>Metric</th>
            ${windows.map(w => `<th>${w}Y CAGR</th><th>Quality</th>`).join('')}
        </tr></thead>
        <tbody>`;

    Object.entries(metrics).forEach(([base, data]) => {
        const name = (nameMap[base] || base).replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        html += `<tr><td>${name}</td>`;
        windows.forEach(w => {
            const g = data[w];
            if (g) {
                const val = g.value != null ? g.value.toFixed(1) + '%' : '—';
                html += `<td class="val-cell" style="color:${g.value > 0 ? '#34d399':'#ef4444'}">${val}</td>`;
                html += `<td><span class="kpi-label ${labelClass(g.label)}">${g.label || '—'}</span></td>`;
            } else {
                html += `<td class="val-cell">—</td><td>—</td>`;
            }
        });
        html += `</tr>`;
    });

    html += '</tbody></table>';
    wrap.innerHTML = html;
}

/* =================================================================
   ANALYSIS PAGE — ALL CHARTS
================================================================= */

function renderAnalysis() {
    if (!cachedData) return;
    buildAllCharts('all');
    setupAnalysisControls();
}

function setupAnalysisControls() {
    // Category tabs
    document.querySelectorAll('.cat-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.cat-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            filterCategories(btn.dataset.cat);
        });
    });

    // Period filter
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activePeriodYears = parseInt(btn.dataset.years);
            // Destroy & rebuild all charts with new period
            destroyAllCharts();
            buildAllCharts(document.querySelector('.cat-tab.active')?.dataset.cat || 'all');
        });
    });
}

function filterCategories(catId) {
    document.querySelectorAll('.analysis-category-section').forEach(section => {
        const show = catId === 'all' || section.dataset.cat === catId;
        section.style.display = show ? '' : 'none';
    });
}

function buildAllCharts(activeFilter) {
    const container = getEl('charts-container');
    container.innerHTML = '';

    const periods    = cachedData.periods || [];
    const filteredPs = filterPeriods(periods, activePeriodYears);

    METRIC_GROUPS.forEach(group => {
        // Filter to metrics that actually have data
        const hasData = group.metrics.filter(m => {
            const cat = cachedData[group.id];
            if (!cat || !cat[m.key]) return false;
            const vals = Object.values(cat[m.key].values || {});
            return vals.some(v => v !== null && v !== undefined);
        });
        if (!hasData.length) return;

        // Category section
        const section = document.createElement('div');
        section.className  = 'analysis-category-section';
        section.dataset.cat = group.id;
        if (activeFilter !== 'all' && activeFilter !== group.id) section.style.display = 'none';

        section.innerHTML = `
            <div class="analysis-cat-header">
                <div class="analysis-cat-dot" style="background:${group.color}"></div>
                <div class="analysis-cat-label" style="color:${group.color}">${group.label}</div>
                <div class="analysis-cat-count">${hasData.length} metrics</div>
            </div>
            <div class="charts-grid" id="grid-${group.id}"></div>
        `;
        container.appendChild(section);

        const grid = section.querySelector('.charts-grid');

        hasData.forEach(metric => {
            const ratioData  = cachedData[group.id]?.[metric.key];
            if (!ratioData) return;

            const latestVal  = ratioData.latest_value;
            const latestLbl  = ratioData.latest_label || '';
            const trend      = ratioData.trend || '';
            const tm         = trendMeta(trend);
            const chartId    = `chart-${group.id}-${metric.key}`;

            const card = document.createElement('div');
            card.className = 'chart-card';
            card.innerHTML = `
                <div class="chart-card-header">
                    <div class="chart-card-title">${metric.label}</div>
                    <div class="chart-card-meta">
                        <span class="chart-card-trend ${tm.cls}">${tm.icon} ${tm.text}</span>
                    </div>
                </div>
                <div class="chart-card-value-row">
                    <span class="chart-card-value">${latestVal != null ? parseFloat(latestVal).toFixed(2) : '—'}</span>
                    <span class="chart-card-unit">${metric.unit}</span>
                    ${latestLbl ? `<span class="chart-card-label ${labelClass(latestLbl)}">${latestLbl}</span>` : ''}
                </div>
                <div class="chart-card-canvas-wrap">
                    <canvas id="${chartId}"></canvas>
                </div>
            `;
            grid.appendChild(card);

            // Render chart (deferred to ensure DOM is ready)
            requestAnimationFrame(() => renderMiniChart(chartId, metric, group, filteredPs));
        });
    });
}

function renderMiniChart(chartId, metric, group, periods) {
    const series = extractSeries(cachedData, group.id, metric.key, periods);
    const labels  = periodLabels(periods);

    // Gradient fill for line charts
    const canvas = getEl(chartId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    let dataset;
    if (metric.type === 'line') {
        const grad = ctx.createLinearGradient(0, 0, 0, 130);
        grad.addColorStop(0, group.color + '33');
        grad.addColorStop(1, group.color + '05');
        dataset = {
            data: series,
            borderColor: group.color,
            backgroundColor: grad,
            fill: true,
            tension: 0.4,
            pointRadius: 3,
            pointBackgroundColor: group.color,
            pointHoverRadius: 5,
            borderWidth: 2,
        };
    } else {
        dataset = {
            data: series,
            backgroundColor: group.color + '55',
            borderColor: group.color,
            borderWidth: 1.5,
            borderRadius: 4,
            hoverBackgroundColor: group.color + '88',
        };
    }

    makeChart(chartId, metric.type === 'line' ? 'line' : 'bar', labels, [dataset], {
        animation: { duration: 300 },
        scales: {
            x: {
                ticks: { color: '#4b6080', font: { size: 9 }, maxRotation: 45 },
                grid: { color: 'rgba(255,255,255,0.03)' },
            },
            y: {
                ticks: { color: '#4b6080', font: { size: 9 } },
                grid: { color: 'rgba(255,255,255,0.03)' },
            }
        },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: 'rgba(6,11,20,0.92)',
                titleColor: '#e8edf5',
                bodyColor: '#8899b0',
                borderColor: group.color + '66',
                borderWidth: 1,
                padding: 8,
                cornerRadius: 6,
                callbacks: {
                    label: ctx => `${ctx.parsed.y != null ? ctx.parsed.y.toFixed(2) : '—'}${metric.unit}`
                }
            }
        }
    });
}

/* =================================================================
   RAG STATUS
================================================================= */

// ETA tracking state
let ragIndexingStartTime = null;

/** Format seconds into human-readable remaining time */
function formatETA(seconds) {
    if (!isFinite(seconds) || seconds <= 0) return '';
    if (seconds < 10)  return '< 10 seconds remaining';
    if (seconds < 60)  return `~${Math.round(seconds)}s remaining`;
    const mins = Math.round(seconds / 60);
    return `~${mins} min${mins > 1 ? 's' : ''} remaining`;
}

/** Show/hide a sidebar panel by ID; hides all others in the list first */
function showSidebarPanel(panelId) {
    const allPanels = [
        'rag-progress-panel',
        'rag-no-pdf-banner',
        'rag-error-banner',
        'rag-ready-banner',
    ];
    allPanels.forEach(id => {
        const el = getEl(id);
        if (el) el.classList.add('hidden');
    });
    if (panelId) {
        const el = getEl(panelId);
        if (el) el.classList.remove('hidden');
    }
}

/**
 * Central RAG status updater — controls:
 *  - compact dot + label in sidebar header
 *  - expanded panel (indexing progress | no-pdf | error | ready)
 *  - topbar badge and chat pill
 * @param {object} st — full status object from /api/status
 */
function updateRagState(st) {
    const ragStatus   = st.rag_status || 'idle';
    const ragProgress = st.rag_progress || 0;
    const ragLabel    = st.rag_label   || '';

    const dot    = getEl('rag-status-dot');
    const sbText = getEl('sb-rag-text');
    const topBadge = getEl('topbar-rag-badge');
    const chatPill = getEl('chat-rag-pill');

    const INDEXING_STATES = ['loading', 'chunking', 'embedding', 'storing', 'processing'];
    const isIndexing = INDEXING_STATES.includes(ragStatus);

    // ── Compact dot + label in SB header row ──
    const dotClsMap  = { ready: 'ready', error: 'error', idle: 'idle' };
    const dotCls     = isIndexing ? 'indexing' : (dotClsMap[ragStatus] || 'idle');
    if (dot) dot.className = `rag-dot ${dotCls}`;

    // ── Sidebar text (one-liner) ──
    const sbTextMap = {
        idle:  'No annual report uploaded',
        ready: 'Annual report indexed ✓',
        error: 'PDF processing unavailable',
    };
    if (sbText) sbText.textContent = isIndexing ? ragLabel || 'Processing report...' : (sbTextMap[ragStatus] || '—');

    // ── Topbar badge + chat pill ──
    const badgeMap = {
        idle:  { text: '○ Financials Only',            style: '' },
        ready: { text: '● RAG Enhanced',               style: 'color:#10b981;border-color:rgba(16,185,129,0.3)' },
        error: { text: '◐ Financials Only',            style: 'color:#f59e0b;border-color:rgba(245,158,11,0.25)' },
    };
    const indexingBadge = { text: `● Indexing Report (${ragProgress}%)`, style: 'color:#06b6d4;border-color:rgba(6,182,212,0.3)' };
    const badge = isIndexing ? indexingBadge : (badgeMap[ragStatus] || badgeMap.idle);
    if (topBadge) { topBadge.textContent = badge.text; topBadge.style.cssText = badge.style; }
    if (chatPill) { chatPill.textContent = badge.text; chatPill.style.cssText = badge.style; }

    // ── Expanded sidebar panel ──
    if (isIndexing) {
        // Start ETA timer on first indexing poll
        if (!ragIndexingStartTime) ragIndexingStartTime = Date.now();

        showSidebarPanel('rag-progress-panel');

        // Update progress bar
        const fill  = getEl('rag-prog-fill');
        const pct   = getEl('rag-prog-pct');
        const stage = getEl('rag-prog-stage');
        const eta   = getEl('rag-prog-eta');

        if (fill)  fill.style.width  = `${ragProgress}%`;
        if (pct)   pct.textContent   = `${ragProgress}%`;
        if (stage) stage.textContent = ragLabel || 'Processing...';

        // ETA calculation
        if (eta) {
            if (ragProgress > 2 && ragIndexingStartTime) {
                const elapsedSec = (Date.now() - ragIndexingStartTime) / 1000;
                const rate       = ragProgress / elapsedSec; // % per second
                const remaining  = rate > 0 ? (100 - ragProgress) / rate : Infinity;
                eta.textContent  = formatETA(remaining);
            } else {
                eta.textContent = 'Estimating time...';
            }
        }

    } else if (ragStatus === 'ready') {
        ragIndexingStartTime = null;
        showSidebarPanel('rag-ready-banner');

    } else if (ragStatus === 'error') {
        ragIndexingStartTime = null;
        showSidebarPanel('rag-error-banner');

    } else {
        // idle — no PDF uploaded
        ragIndexingStartTime = null;
        showSidebarPanel('rag-no-pdf-banner');
    }
}

/** Backward-compatible wrapper for single-argument calls from init() */
function updateRagBadge(ragStatus) {
    updateRagState({ rag_status: ragStatus, rag_progress: 0, rag_label: '' });
}

function pollBackgroundTasks() {
    if (ragPollInterval) clearInterval(ragPollInterval);
    ragPollInterval = setInterval(async () => {
        try {
            const res = await fetch('/api/status');
            const st  = await res.json();
            updateRagState(st);
            await updateSummaryState(st);
            
            // Terminal states
            const ragDone = ['ready', 'error', 'idle'].includes(st.rag_status);
            const sumDone = ['ready', 'error', 'idle'].includes(st.summary_status || 'idle');
            
            if (ragDone && sumDone) {
                clearInterval(ragPollInterval);
            }
        } catch (_) {}
    }, 2000);
}

/** Handles dynamic updates of the AI Summary box on the Overview page */
async function updateSummaryState(st) {
    const status = st.summary_status || 'idle';
    
    // If it's ready, but we don't have the text cached yet, fetch it.
    if (status === 'ready' && cachedData && !cachedData.llm_financial_summary) {
        try {
            const res = await fetch('/api/analysis');
            if (res.ok) {
                const fresh = await res.json();
                if (fresh.llm_financial_summary) {
                    cachedData.llm_financial_summary = fresh.llm_financial_summary;
                    if (currentPage === 'overview') renderOverview();
                }
            }
        } catch (_) {}
        return;
    }

    // Only inject loading/error states if the summary hasn't already been downloaded
    if (cachedData && !cachedData.llm_financial_summary) {
        const sumEl = getEl('ai-summary');
        if (!sumEl) return;
        
        let content = buildQuickSummary();
        if (status === 'generating') {
            sumEl.innerHTML = `<div style="padding: 1.25rem; background: rgba(139,92,246,0.06); border-radius: 8px; border: 1px solid rgba(139,92,246,0.15); display: flex; flex-direction: column; gap: 12px; align-items: center; justify-content: center; min-height: 120px;">
                <div class="typing-dots"><span></span><span></span><span></span></div>
                <span style="color: var(--purple); font-weight: 500; font-size: 0.95rem;">Synthesizing comprehensive AI narrative...</span>
            </div>`;
        } else if (status === 'error') {
            const isQuota = st.summary_error === 'quota';
            const errorMsg = isQuota 
                ? "<b>AI Synthesis Unavailable.</b> The narrative generation service is currently experiencing exceptionally high demand and is at full capacity." 
                : "<b>AI Narrative Generation Failed.</b> The AI service encountered an unexpected network disruption.";
            const helpText = isQuota
                ? "All automated financial scoring, historical trends, and structured analytics have been successfully generated and remain fully accessible below."
                : "All structured data and standalone metrics below are fully available despite this error.";
            const icon = isQuota ? "⏳" : "⚠️";

            sumEl.innerHTML = content + `<div style="margin-top: 1rem; padding: 1.25rem; background: rgba(245,158,11,0.06); border-radius: 8px; border: 1px solid rgba(245,158,11,0.25); display: flex; gap: 14px;">
                <div style="font-size: 1.4rem;">${icon}</div>
                <div style="display: flex; flex-direction: column; gap: 4px; color: var(--text-secondary);">
                    <span style="color: var(--amber); font-weight: 500; font-size: 0.95rem;">${errorMsg}</span>
                    <span style="font-size: 0.88rem; line-height: 1.5;">${helpText}</span>
                </div>
            </div>`;
        }
    }
}

/* =================================================================
   CHAT PAGE
================================================================= */

// Suggestion chips
document.querySelectorAll('.suggestion-chip').forEach(btn => {
    btn.addEventListener('click', () => {
        getEl('chat-input').value = btn.dataset.q;
        getEl('chat-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
});

getEl('chat-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = getEl('chat-input').value.trim();
    if (!q) return;

    // Hide welcome if visible
    const welcome = document.querySelector('.chat-welcome');
    if (welcome) welcome.remove();

    addChatBubble('user', q);
    getEl('chat-input').value = '';
    getEl('btn-send').disabled = true;

    // Typing indicator
    const typingId = 'typing-' + Date.now();
    const typingBubble = addChatBubble('assistant', `<div class="typing-dots"><span></span><span></span><span></span></div>`, typingId);

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: q,
                chat_history: chatHistory,
                conversation_summary: ''
            })
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }

        const reader  = res.body.getReader();
        const decoder = new TextDecoder();
        let fullText  = '';
        let started   = false;

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            const raw = decoder.decode(value, { stream: true });
            for (const line of raw.split('\n')) {
                const l = line.trim();
                if (!l.startsWith('data: ')) continue;
                const payload = l.slice(6);
                if (payload === '[DONE]') break;
                try {
                    const obj = JSON.parse(payload);
                    if (obj.chunk) {
                        if (!started) {
                            typingBubble.querySelector('.msg-bubble').innerHTML = '';
                            started = true;
                        }
                        fullText += obj.chunk;
                        typingBubble.querySelector('.msg-bubble').innerHTML = marked.parse(fullText);
                        getEl('chat-messages').scrollTop = getEl('chat-messages').scrollHeight;
                    } else if (obj.error) {
                        typingBubble.querySelector('.msg-bubble').classList.add('msg-error');
                        typingBubble.querySelector('.msg-bubble').innerHTML = marked.parse(obj.error);
                    }
                } catch (_) {}
            }
        }

        if (fullText) {
            typingBubble.querySelector('.msg-bubble').innerHTML = marked.parse(fullText);
        }
        chatHistory.push({ role: 'user', content: q });
        chatHistory.push({ role: 'assistant', content: fullText });

    } catch (err) {
        if (typingBubble) {
            typingBubble.querySelector('.msg-bubble').classList.add('msg-error');
            typingBubble.querySelector('.msg-bubble').innerHTML = marked.parse(
                `**Connection Error**\n\nCould not reach the AI service. Please check your connection and try again.`
            );
        }
    } finally {
        getEl('btn-send').disabled = false;
        getEl('chat-messages').scrollTop = getEl('chat-messages').scrollHeight;
    }
});

function addChatBubble(role, html, id) {
    const msgs = getEl('chat-messages');

    const wrapper = document.createElement('div');
    wrapper.className = `msg ${role}`;
    if (id) wrapper.id = id;

    const avatarHTML = role === 'user'
        ? `<div class="msg-avatar user-avatar">
               <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
                   <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                   <circle cx="12" cy="7" r="4"/>
               </svg>
           </div>`
        : `<div class="msg-avatar ai-avatar">
               <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                   <path d="M12 2L13.09 8.26L19 6L14.74 10.74L21 12L14.74 13.26L19 18L13.09 15.74L12 22L10.91 15.74L5 18L9.26 13.26L3 12L9.26 10.74L5 6L10.91 8.26L12 2Z"
                         fill="url(#avatar-grad)" stroke="none"/>
                   <defs>
                       <linearGradient id="avatar-grad" x1="3" y1="2" x2="21" y2="22" gradientUnits="userSpaceOnUse">
                           <stop offset="0%" stop-color="#a78bfa"/>
                           <stop offset="100%" stop-color="#60a5fa"/>
                       </linearGradient>
                   </defs>
               </svg>
           </div>`;

    wrapper.innerHTML = `${avatarHTML}<div class="msg-bubble">${html}</div>`;
    msgs.appendChild(wrapper);
    msgs.scrollTop = msgs.scrollHeight;
    return wrapper;
}

/* =================================================================
   RESET
================================================================= */

function resetToUpload() {
    getEl('dashboard-view').classList.add('hidden');
    getEl('upload-view').classList.remove('hidden');

    // Reset form
    getEl('upload-form').reset();
    getEl('excel-zone').classList.remove('active-file');
    getEl('pdf-zone').classList.remove('active-file');
    getEl('excel-label').textContent = 'Financial Data';
    getEl('pdf-label').textContent   = 'Annual Report';
    getEl('analyze-btn').disabled = false;
    getEl('analyze-btn-text').textContent = 'Run Analysis';
    getEl('processing-tracker').classList.add('hidden');
    getEl('rag-tracker-container').classList.add('hidden');
    getEl('pipeline-progress').style.width = '0%';
    getEl('rag-progress').style.width = '0%';

    // Clear intervals
    if (pollInterval)    clearInterval(pollInterval);
    if (ragPollInterval) clearInterval(ragPollInterval);

    // Reset state
    cachedData      = null;
    chatHistory     = [];
    activePeriodYears = 0;

    // Destroy all charts
    destroyAllCharts();

    // Reset chat
    const msgs = getEl('chat-messages');
    msgs.innerHTML = `
        <div class="chat-welcome">
            <div class="welcome-icon">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>
                </svg>
            </div>
            <p>Hello! I've analyzed the financial data and I'm ready to answer your questions.</p>
            <div class="chat-suggestions">
                <button class="suggestion-chip" data-q="What is the ROE trend over the last 5 years?">ROE trend?</button>
                <button class="suggestion-chip" data-q="Analyze the valuation metrics. Is the stock expensive?">Valuation analysis</button>
                <button class="suggestion-chip" data-q="What are the key risks for this company?">Key risks</button>
                <button class="suggestion-chip" data-q="Summarize the profitability performance.">Profitability summary</button>
            </div>
        </div>`;

    // Re-attach suggestion chip listeners
    msgs.querySelectorAll('.suggestion-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            getEl('chat-input').value = btn.dataset.q;
            getEl('chat-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        });
    });

    // Reset analysis page
    getEl('charts-container').innerHTML = '';
}

getEl('btn-back').addEventListener('click', async () => {
    try {
        await fetch('/api/reset', { method: 'POST' });
    } catch (err) {
        console.error('Failed to reset analysis state on server:', err);
    }
    resetToUpload();
});

/* =================================================================
   INIT
================================================================= */

// On page load, check if analysis data already exists (e.g., after page refresh)
(async function init() {
    try {
        const statusRes = await fetch('/api/status');
        const st = await statusRes.json();
        if (st.stage === 'done') {
            const dataRes = await fetch('/api/analysis');
            if (dataRes.ok) {
                cachedData = await dataRes.json();
                // Minimal init without pipeline loading
                const company = cachedData.company || '—';
                const periods  = cachedData.periods || [];
                const latest   = cachedData.latest_period || (periods.length ? periods[periods.length - 1] : '—');
                const scores   = cachedData.summary_scores || {};

                getEl('sb-company-name').textContent = company;
                getEl('sb-period').textContent = `Latest: ${latest}`;
                const scoreVal = scores.overall_score;
                const sbScore = getEl('sb-overall-score');
                sbScore.textContent = scoreVal != null ? scoreVal.toFixed(1) + ' / 5' : '—';
                sbScore.className = 'sb-score-value ' + (scoreVal != null ? scoreColorClass(scoreVal) : '');
                getEl('topbar-company').textContent = company;

                getEl('upload-view').classList.add('hidden');
                getEl('dashboard-view').classList.remove('hidden');

                renderOverview();
                renderAnalysis();
                updateRagState(st);   // full object → correct panel shown on refresh
                navigateTo('overview');
            }
        }
    } catch (_) {
        // Fresh start — upload view is shown by default
    }
})();
