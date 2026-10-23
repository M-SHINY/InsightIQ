/**
 * InsightIQ — Client-Side Application Controller
 * Handles interactive UI state, query dispatching, Chart.js rendering,
 * data quality modals, and transparent SQL inspection.
 */

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const queryForm = document.getElementById("query-form");
    const queryInput = document.getElementById("query-input");
    const clearQueryBtn = document.getElementById("clear-query-btn");
    const submitBtn = document.getElementById("submit-btn");
    const emptyState = document.getElementById("empty-state");
    const loadingState = document.getElementById("loading-state");
    const errorState = document.getElementById("error-state");
    const answerCard = document.getElementById("answer-card");

    // Modal elements
    const dqModal = document.getElementById("dq-modal");
    const openDqModalBtn = document.getElementById("open-dq-modal-btn");
    const closeDqModalBtn = document.getElementById("close-dq-modal-btn");
    const modalCloseActionBtn = document.getElementById("modal-close-action-btn");

    // SQL Accordion
    const toggleSqlBtn = document.getElementById("toggle-sql-btn");
    const sqlDetailsPanel = document.getElementById("sql-details-panel");
    const accordionArrow = document.getElementById("accordion-arrow");

    // History elements
    const historyList = document.getElementById("history-list");
    const historyCount = document.getElementById("history-count");

    // Active chart instance holder
    let activeChart = null;

    // Fetch initial health and data quality on page load
    fetchInitialStatus();
    fetchHistory();

    // Event: Query Input Clear button visibility
    queryInput.addEventListener("input", () => {
        clearQueryBtn.style.display = queryInput.value.length > 0 ? "block" : "none";
    });

    clearQueryBtn.addEventListener("click", () => {
        queryInput.value = "";
        clearQueryBtn.style.display = "none";
        queryInput.focus();
    });

    // Event: Prompt Chips Click
    document.querySelectorAll(".chip[data-query]").forEach(chip => {
        chip.addEventListener("click", () => {
            const query = chip.getAttribute("data-query");
            queryInput.value = query;
            clearQueryBtn.style.display = "block";
            submitQuery(query);
        });
    });

    // Event: Search Form Submit
    queryForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const query = queryInput.value.trim();
        if (query) {
            submitQuery(query);
        }
    });

    // Event: SQL Accordion Toggle
    toggleSqlBtn.addEventListener("click", () => {
        const isHidden = sqlDetailsPanel.classList.toggle("hidden");
        accordionArrow.textContent = isHidden ? "▼" : "▲";
    });

    // Event: Data Quality Modal Open / Close
    openDqModalBtn.addEventListener("click", () => {
        openDataQualityModal();
    });
    closeDqModalBtn.addEventListener("click", () => {
        dqModal.classList.add("hidden");
    });
    modalCloseActionBtn.addEventListener("click", () => {
        dqModal.classList.add("hidden");
    });
    dqModal.addEventListener("click", (e) => {
        if (e.target === dqModal) {
            dqModal.classList.add("hidden");
        }
    });

    // =========================================================================
    // Core Query Processing
    // =========================================================================
    async function submitQuery(question) {
        showLoading();

        try {
            const response = await fetch("/api/query", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ question })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                renderAnswer(data);
            } else {
                renderError(data);
            }
        } catch (err) {
            renderError({
                error: "NETWORK_ERROR",
                message: `Failed to connect to InsightIQ API: ${err.message}`
            });
        } finally {
            fetchHistory();
        }
    }

    // =========================================================================
    // View Rendering Functions
    // =========================================================================
    function showLoading() {
        emptyState.classList.add("hidden");
        errorState.classList.add("hidden");
        answerCard.classList.add("hidden");
        loadingState.classList.remove("hidden");
        submitBtn.disabled = true;
    }

    function renderError(data) {
        loadingState.classList.add("hidden");
        emptyState.classList.add("hidden");
        answerCard.classList.add("hidden");
        errorState.classList.remove("hidden");
        submitBtn.disabled = false;

        document.getElementById("error-title").textContent = data.error || "Query Processing Error";
        document.getElementById("error-message").textContent = data.message || "An unexpected error occurred.";

        const detailsEl = document.getElementById("error-details");
        detailsEl.innerHTML = "";

        if (data.supported_questions && data.supported_questions.length > 0) {
            const supportList = document.createElement("div");
            supportList.className = "error-support-box";
            supportList.innerHTML = "<strong>Supported Challenge Questions:</strong>";
            const ul = document.createElement("ul");
            data.supported_questions.forEach(q => {
                const li = document.createElement("li");
                li.textContent = q;
                li.style.cursor = "pointer";
                li.style.textDecoration = "underline";
                li.addEventListener("click", () => {
                    queryInput.value = q;
                    submitQuery(q);
                });
                ul.appendChild(li);
            });
            supportList.appendChild(ul);
            detailsEl.appendChild(supportList);
        }
    }

    function renderAnswer(data) {
        loadingState.classList.add("hidden");
        errorState.classList.add("hidden");
        emptyState.classList.add("hidden");
        answerCard.classList.remove("hidden");
        submitBtn.disabled = false;

        // Title and Operation
        document.getElementById("operation-tag").textContent = data.operation ? data.operation.replace(/_/g, " ") : "Analysis";
        document.getElementById("answer-title").textContent = data.title || "Query Result";

        // Mode & Latency
        const mode = data.interpretation?.mode || "fallback_rules";
        const modeLabel = mode.includes("gemini") ? "Mode: Gemini AI" : (mode.includes("openai") ? "Mode: OpenAI" : "Mode: Deterministic Rules");
        document.getElementById("meta-mode").textContent = modeLabel;
        document.getElementById("meta-latency").textContent = `Latency: ${data.latency_ms || 0}ms`;

        // KPI Banner
        document.getElementById("kpi-label").textContent = data.primary_metric_label || "Metric";
        document.getElementById("kpi-value").textContent = data.primary_metric || "N/A";

        const secondaryWrapper = document.getElementById("kpi-secondary-wrapper");
        if (data.primary_metric_secondary) {
            secondaryWrapper.style.display = "flex";
            document.getElementById("kpi-secondary-label").textContent = "Secondary Figure";
            document.getElementById("kpi-secondary-value").textContent = data.primary_metric_secondary;
        } else {
            secondaryWrapper.style.display = "none";
        }

        // Executive Summary
        document.getElementById("executive-summary").textContent = data.summary || "";

        // Warnings
        const warningsBox = document.getElementById("warnings-box");
        const warningsList = document.getElementById("warnings-list");
        warningsList.innerHTML = "";
        if (data.warnings && data.warnings.length > 0) {
            data.warnings.forEach(w => {
                const li = document.createElement("li");
                li.textContent = w;
                warningsList.appendChild(li);
            });
            warningsBox.classList.remove("hidden");
        } else {
            warningsBox.classList.add("hidden");
        }

        // Evidence Table
        renderEvidenceTable(data.evidence);

        // Chart Rendering
        renderChart(data.chart_data);

        // Derived Analytical Observations
        const insightsList = document.getElementById("insights-list");
        insightsList.innerHTML = "";
        if (data.insights && data.insights.length > 0) {
            data.insights.forEach(ins => {
                const li = document.createElement("li");
                li.textContent = ins;
                insightsList.appendChild(li);
            });
        }

        // Contextual Follow-up Chips
        const followUpSection = document.getElementById("follow-up-section");
        const followUpChips = document.getElementById("follow-up-chips");
        followUpChips.innerHTML = "";
        if (data.follow_ups && data.follow_ups.length > 0) {
            followUpSection.style.display = "flex";
            data.follow_ups.forEach(q => {
                const chip = document.createElement("button");
                chip.className = "chip";
                chip.textContent = q;
                chip.addEventListener("click", () => {
                    queryInput.value = q;
                    submitQuery(q);
                });
                followUpChips.appendChild(chip);
            });
        } else {
            followUpSection.style.display = "none";
        }

        // SQL & Engineering Transparency
        document.getElementById("executed-sql-code").textContent = data.executed_sql || "-- Direct analytical calculation";
        const paramCount = data.sql_parameters ? data.sql_parameters.length : 0;
        document.getElementById("sql-param-badge").textContent = `${paramCount} Parameter(s): ${JSON.stringify(data.sql_parameters || [])}`;
        document.getElementById("intent-explanation-text").textContent =
            data.interpretation?.explanation || "Mapped to allowlisted read-only analytical query.";
    }

    function renderEvidenceTable(evidence) {
        const thead = document.getElementById("evidence-table-head");
        const tbody = document.getElementById("evidence-table-body");
        thead.innerHTML = "";
        tbody.innerHTML = "";

        if (!evidence || evidence.length === 0) {
            tbody.innerHTML = "<tr><td colspan='4'>No granular evidence records available.</td></tr>";
            return;
        }

        const headers = Object.keys(evidence[0]);
        const headerRow = document.createElement("tr");
        headers.forEach(h => {
            const th = document.createElement("th");
            th.textContent = h;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);

        evidence.forEach(row => {
            const tr = document.createElement("tr");
            headers.forEach(h => {
                const td = document.createElement("td");
                td.textContent = row[h];
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
    }

    function renderChart(chartData) {
        const chartWrapper = document.getElementById("chart-wrapper");
        const canvas = document.getElementById("analytics-chart");

        // Destroy previous chart instance if exists
        if (activeChart) {
            activeChart.destroy();
            activeChart = null;
        }

        if (!chartData || typeof Chart === "undefined") {
            chartWrapper.style.display = "none";
            return;
        }

        chartWrapper.style.display = "block";

        const ctx = canvas.getContext("2d");
        const isLine = chartData.type === "line";

        activeChart = new Chart(ctx, {
            type: chartData.type || "bar",
            data: {
                labels: chartData.labels,
                datasets: chartData.datasets.map(ds => ({
                    label: ds.label,
                    data: ds.data,
                    backgroundColor: isLine ? "rgba(37, 99, 235, 0.12)" : "rgba(37, 99, 235, 0.8)",
                    borderColor: "#2563eb",
                    borderWidth: 2,
                    fill: isLine,
                    tension: 0.3,
                    pointBackgroundColor: "#1d4ed8",
                    pointRadius: 4
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: "top",
                        labels: { boxWidth: 12, font: { size: 12 } }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || "";
                                if (label) label += ": ";
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(context.parsed.y);
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return (value / 1000) + "k";
                            }
                        }
                    }
                }
            }
        });
    }

    // =========================================================================
    // History & Status Helpers
    // =========================================================================
    async function fetchInitialStatus() {
        try {
            const res = await fetch("/api/health");
            const data = await res.json();
            if (data.status === "healthy") {
                const dbBadge = document.getElementById("db-status-badge");
                const aiBadge = document.getElementById("ai-mode-badge");

                dbBadge.innerHTML = `<span class="dot"></span> Database: ${data.database.total_records} Records (${data.database.valid_completed_records} Valid)`;

                if (data.interpreter.llm_configured) {
                    aiBadge.className = "badge badge-success";
                    aiBadge.innerHTML = `<span class="dot"></span> Mode: LLM Active`;
                } else {
                    aiBadge.className = "badge badge-info";
                    aiBadge.innerHTML = `<span class="dot"></span> Mode: Rule-Based Fallback`;
                }
            }
        } catch (e) {
            console.error("Health check failed:", e);
        }
    }

    async function fetchHistory() {
        try {
            const res = await fetch("/api/history");
            const data = await res.json();
            historyCount.textContent = `${data.total_queries} queries`;

            historyList.innerHTML = "";
            if (!data.history || data.history.length === 0) {
                historyList.innerHTML = `<p class="text-muted" style="font-size:0.85rem;">No questions asked yet in this session.</p>`;
                return;
            }

            data.history.forEach(item => {
                const div = document.createElement("div");
                div.className = "history-item";
                div.innerHTML = `
                    <div class="history-item-left">
                        <span class="history-time">${item.timestamp}</span>
                        <span class="history-question"><strong>${item.question}</strong></span>
                    </div>
                    <div>
                        <span class="history-metric">${item.primary_metric}</span>
                    </div>
                `;
                div.addEventListener("click", () => {
                    queryInput.value = item.question;
                    submitQuery(item.question);
                });
                historyList.appendChild(div);
            });
        } catch (e) {
            console.error("History fetch failed:", e);
        }
    }

    async function openDataQualityModal() {
        try {
            const res = await fetch("/api/data-quality");
            const dq = await res.json();

            document.getElementById("modal-total-records").textContent = dq.total_records;
            document.getElementById("modal-valid-records").textContent = dq.valid_completed_records;
            document.getElementById("modal-excluded-records").textContent = dq.excluded_records;
            document.getElementById("modal-integrity-score").textContent = `${dq.integrity_score}%`;
            document.getElementById("modal-policy-text").innerHTML = `
                <strong>Net Completed Revenue Policy:</strong><br>
                ${dq.revenue_policy}<br><br>
                <strong>Exclusion Policy:</strong> Returned orders are excluded from net completed revenue. Rows missing unit prices are excluded rather than fabricated. Zero-quantity rows are retained with zero contribution.
            `;

            const tbody = document.getElementById("modal-issues-tbody");
            tbody.innerHTML = "";
            dq.issues.forEach(issue => {
                const tr = document.createElement("tr");
                const sevClass = issue.severity === "EXCLUSION" ? "badge badge-warning" : "badge badge-info";
                tr.innerHTML = `
                    <td><strong>${issue.transaction_id}</strong></td>
                    <td>${issue.issue_type}</td>
                    <td><span class="${sevClass}">${issue.severity}</span></td>
                    <td>${issue.description}</td>
                `;
                tbody.appendChild(tr);
            });

            dqModal.classList.remove("hidden");
        } catch (e) {
            alert(`Failed to load data quality summary: ${e.message}`);
        }
    }
});
