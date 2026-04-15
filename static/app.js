// DOM Elements
const uploadForm = document.getElementById('upload-form');
const excelInput = document.getElementById('excel-input');
const pdfInput = document.getElementById('pdf-input');
const btnAnalyze = document.getElementById('analyze-btn');

const uploadView = document.getElementById('upload-view');
const dashboardView = document.getElementById('dashboard-view');
const btnBack = document.getElementById('btn-back');

const processingTracker = document.getElementById('processing-tracker');
const pipelineProgress = document.getElementById('pipeline-progress');
const pipelineStage = document.getElementById('pipeline-stage');
const pipelinePct = document.getElementById('pipeline-pct');

const ragTrackerContainer = document.getElementById('rag-tracker-container');
const ragProgress = document.getElementById('rag-progress');
const ragStage = document.getElementById('rag-stage');

const companyBadge = document.getElementById('company-name-badge');
const aiSummaryEl = document.getElementById('ai-financial-summary');
const ragBadge = document.getElementById('rag-status-badge');

const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const chatMessages = document.getElementById('chat-messages');

let pollInterval = null;
let mainChartObj = null;

// File input handlers (UI feedback)
excelInput.addEventListener('change', (e) => {
    const p = e.target.parentElement.querySelector('p');
    if (e.target.files[0]) {
        p.textContent = e.target.files[0].name;
        e.target.parentElement.style.borderColor = "var(--success)";
    }
});
pdfInput.addEventListener('change', (e) => {
    const p = e.target.parentElement.querySelector('p');
    if (e.target.files[0]) {
        p.textContent = e.target.files[0].name;
        e.target.parentElement.style.borderColor = "var(--success)";
    }
});

// Main Upload Flow
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!excelInput.files[0]) return;

    const formData = new FormData();
    formData.append('excel_file', excelInput.files[0]);
    if (pdfInput.files[0]) {
        formData.append('pdf_file', pdfInput.files[0]);
    }

    // UI State
    btnAnalyze.disabled = true;
    btnAnalyze.innerHTML = `<span>Uploading...</span>`;
    processingTracker.classList.remove('hidden');

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) throw new Error("Upload failed");
        
        // Start polling
        pollInterval = setInterval(pollPipelineStatus, 1000);
    } catch (err) {
        alert("Upload Error: " + err.message);
        btnAnalyze.disabled = false;
        processingTracker.classList.add('hidden');
    }
});

async function pollPipelineStatus() {
    try {
        const res = await fetch('/api/status');
        const status = await res.json();
        
        // Update Core Progress
        pipelineProgress.style.width = `${status.progress}%`;
        pipelineStage.textContent = status.label;
        pipelinePct.textContent = `${status.progress}%`;

        // Update RAG Progress if active
        if (status.rag_status !== 'idle') {
            ragTrackerContainer.classList.remove('hidden');
            ragProgress.style.width = `${status.rag_progress}%`;
            ragStage.textContent = status.rag_label;
        }

        // If core is DONE, transition to dashboard
        if (status.stage === 'done') {
            clearInterval(pollInterval); // core done, but rag might be indexing, handle in dashboard
            companyBadge.textContent = status.company || "Lensight Analysis";
            await loadAnalysisData();
            switchToDashboard();
            pollRagStatusInBackground();
        } else if (status.stage === 'error') {
            clearInterval(pollInterval);
            alert("Pipeline Error: " + status.error);
            resetUploadForm();
        }

    } catch (err) {
        console.error("Polling error:", err);
    }
}

let ragPollInterval = null;
function pollRagStatusInBackground() {
    if (ragPollInterval) clearInterval(ragPollInterval);
    ragPollInterval = setInterval(async () => {
        const res = await fetch('/api/status');
        const st = await res.json();
        
        if (st.rag_status === 'ready') {
            ragBadge.textContent = "🟢 RAG Ready";
            ragBadge.style.color = "var(--success)";
            clearInterval(ragPollInterval);
        } else if (st.rag_status === 'embedding' || st.rag_status === 'processing') {
            ragBadge.textContent = `⏳ Indexing PDF... (${st.rag_progress}%)`;
            ragBadge.style.color = "var(--warning)";
        } else if (st.rag_status === 'error') {
            ragBadge.textContent = "⚠️ PDF Error";
            ragBadge.style.color = "var(--error)";
            clearInterval(ragPollInterval);
        } else if (st.rag_status === 'idle') {
            ragBadge.textContent = "⚪ Financials Only";
            ragBadge.style.color = "var(--text-muted)";
            clearInterval(ragPollInterval);
        }
    }, 2000);
}

// Data Fetch & Chart Rendering
let cachedData = null;
async function loadAnalysisData() {
    try {
        const res = await fetch('/api/analysis');
        cachedData = await res.json();
        
        // Render Summary
        aiSummaryEl.innerHTML = marked.parse(cachedData.llm_financial_summary || "No summary generated.");
        aiSummaryEl.classList.remove('skeleton-text');

        // Render Chart
        renderChart('revenueChart');
    } catch (err) {
        console.error("Analysis Load Error:", err);
    }
}

function renderChart(type) {
    if (!cachedData) return;
    const ctx = document.getElementById('mainChart').getContext('2d');
    
    if (mainChartObj) {
        mainChartObj.destroy();
    }

    let config = { type: 'bar', data: { labels: [], datasets: [] }, options: {responsive:true, maintainAspectRatio:false} };
    const periods = cachedData.periods.map(p => p.period_name).reverse(); // oldest to newest

    if (type === 'revenueChart') {
        const rev = cachedData.periods.map(p => p.ratios["Revenue"]).reverse();
        const ebitda = cachedData.periods.map(p => p.ratios["EBITDA"]).reverse();
        config.data = {
            labels: periods,
            datasets: [
                { label: 'Revenue', data: rev, backgroundColor: 'rgba(59, 130, 246, 0.7)' },
                { label: 'EBITDA', data: ebitda, backgroundColor: 'rgba(139, 92, 246, 0.7)' }
            ]
        };
    } else if (type === 'marginChart') {
        const opM = cachedData.periods.map(p => p.ratios["Operating_Margin_%"]).reverse();
        const npM = cachedData.periods.map(p => p.ratios["Net_Profit_Margin_%"]).reverse();
        config.type = 'line';
        config.data = {
            labels: periods,
            datasets: [
                { label: 'Operating Margin %', data: opM, borderColor: '#3b82f6', tension:0.4 },
                { label: 'Net Profit Margin %', data: npM, borderColor: '#8b5cf6', tension:0.4 }
            ]
        };
    } else if (type === 'liquidityChart') {
        const cr = cachedData.periods.map(p => p.ratios["Current_Ratio"]).reverse();
        config.data = {
            labels: periods,
            datasets: [{ label: 'Current Ratio', data: cr, backgroundColor: '#10b981' }]
        };
    }

    // Modern styling options
    config.options.plugins = { legend: { labels: { color: '#fff' } } };
    config.options.scales = {
        x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
    };

    mainChartObj = new Chart(ctx, config);
}

// Chart toggles
document.querySelectorAll('.chart-selector button').forEach(btn => {
    btn.addEventListener('click', (e) => {
        document.querySelectorAll('.chart-selector button').forEach(b => b.classList.remove('active'));
        e.target.classList.add('active');
        renderChart(e.target.dataset.target);
    });
});

// Chat SSE Streaming
let chatHistory = [];
chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const q = chatInput.value.trim();
    if (!q) return;

    // Add user bubble
    appendBubble('user', q);
    chatInput.value = '';
    
    // Create empty assistant bubble
    const assistantBubble = appendBubble('assistant', '<span class="typing">...</span>');
    
    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                question: q,
                chat_history: chatHistory,
                conversation_summary: ""
            })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let assistantText = "";
        
        // Clear typing indicator
        assistantBubble.innerHTML = '';

        while (true) {
            const {value, done} = await reader.read();
            if (done) break;
            
            // Parse SSE payload
            const lines = decoder.decode(value).split('\n');
            for (let line of lines) {
                if (line.startsWith('data: ')) {
                    const dataObj = line.substring(6);
                    if (dataObj === '[DONE]') break;
                    
                    try {
                        const parsed = JSON.parse(dataObj);
                        if (parsed.chunk) {
                            assistantText += parsed.chunk;
                            assistantBubble.innerHTML = marked.parse(assistantText);
                            chatMessages.scrollTop = chatMessages.scrollHeight;
                        } else if (parsed.error) {
                            assistantBubble.innerHTML = `⚠️ ${parsed.error}`;
                        }
                    } catch (e) {}
                }
            }
        }
        
        // Push to history context
        chatHistory.push({role: 'user', content: q});
        chatHistory.push({role: 'assistant', content: assistantText});

    } catch (err) {
        assistantBubble.innerHTML = `⚠️ Connection error: ${err.message}`;
    }
});

function appendBubble(role, htmlContent) {
    const div = document.createElement('div');
    div.className = `message ${role} markdown-body`;
    if (role === 'user') {
        div.textContent = htmlContent;
    } else {
        div.innerHTML = htmlContent;
    }
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

// Navigation
function switchToDashboard() {
    uploadView.classList.add('hidden');
    dashboardView.classList.remove('hidden');
}

btnBack.addEventListener('click', resetUploadForm);

function resetUploadForm() {
    dashboardView.classList.add('hidden');
    uploadView.classList.remove('hidden');
    btnAnalyze.disabled = false;
    btnAnalyze.innerHTML = `<span>Analyze Company</span><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"></path><path d="m12 5 7 7-7 7"></path></svg>`;
    processingTracker.classList.add('hidden');
    excelInput.value = '';
    pdfInput.value = '';
    excelInput.parentElement.querySelector('p').textContent = "Drag & drop Excel file here";
    pdfInput.parentElement.querySelector('p').textContent = "Drag & drop PDF for RAG context";
    excelInput.parentElement.style.borderColor = "";
    pdfInput.parentElement.style.borderColor = "";
    if (pollInterval) clearInterval(pollInterval);
    if (ragPollInterval) clearInterval(ragPollInterval);
    chatMessages.innerHTML = '';
    chatHistory = [];
}
