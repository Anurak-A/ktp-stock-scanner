/* ─── Stock Scanner — Frontend ─── */

let currentCategory = "nasdaq100";
let currentSymbol = null;
let allResults = [];
let fiboStats = {};  // per-symbol fibo+RR stats
let mainChart = null;
let rsiChart = null;
let stochChart = null;
let candleSeries = null;
let volumeSeries = null;
let stochKSeries = null;
let stochDSeries = null;
let obLine = null;
let osLine = null;
let currentFilter = "all";
let currentSort = "none"; // none | az | za
let tickedOnly = false;

/* ─── Per-stock RR (saved in localStorage) ─── */
function getStockRR() {
    try { return JSON.parse(localStorage.getItem("stock_rr") || "{}"); } catch { return {}; }
}
function saveStockRR(data) {
    localStorage.setItem("stock_rr", JSON.stringify(data));
}
function setStockRR(symbol, value, event) {
    if (event) event.stopPropagation();
    if (!requirePassword()) return;
    const rr = prompt(`Set RR for ${symbol.replace('.BK','')}:`, value || "1.0");
    if (rr === null) return;
    const num = parseFloat(rr);
    if (isNaN(num) || num <= 0) { alert("Invalid RR"); return; }
    const data = getStockRR();
    data[symbol] = num;
    saveStockRR(data);
    // Update in-place
    const el = document.querySelector(`.rr-value[data-symbol="${symbol}"]`);
    if (el) el.textContent = num.toFixed(2);
}

// Pre-populate best RR from backtest analysis
function initBestRR() {
    const existing = getStockRR();
    if (Object.keys(existing).length > 0) return; // already set
    const bestRR = {
        "BKR": 1.25, "BIIB": 1.0, "AAPL": 1.25, "REGN": 1.25, "GEHC": 1.25,
        "FAST": 1.0, "ROST": 1.25, "INTC": 0.5, "SBUX": 0.75, "DASH": 1.25,
        "MNST": 1.25, "CCEP": 1.25,
    };
    saveStockRR(bestRR);
}

/* ─── Password gate ─── */
let isUnlocked = false;
const EDIT_PASSWORD = "1234";

function requirePassword() {
    if (isUnlocked) return true;
    const input = prompt("Enter password to edit:");
    if (input === EDIT_PASSWORD) {
        isUnlocked = true;
        return true;
    }
    if (input !== null) alert("Wrong password");
    return false;
}

/* ─── Ticked stocks (saved in localStorage) ─── */
// One-time preset tick states (v5: star only, no cross)
if (localStorage.getItem("tick_reset_v5") !== "done") {
    const preset = {};
    // Star (check) — WL technique profitable, RR > 0.5
    ["AEP","AMGN","BIIB","BKR","CCEP","COST","CSX","FAST","GOOG","GOOGL",
     "KDP","LIN","MDLZ","MNST","PEP","REGN","ROST","SBUX","TSLA","TXN",
     "VRTX","AAPL","CSGP","CTSH","DASH","DDOG","DLTR","GEHC","INTC","MSFT",
     "NXPI","PANW","PAYX","WDAY"].forEach(s => preset[s] = "check");
    localStorage.setItem("tick_states", JSON.stringify(preset));
    localStorage.setItem("tick_reset_v5", "done");
}

// States: "check" = ticked, "cross" = excluded, absent = neutral
function getTickStates() {
    try {
        return JSON.parse(localStorage.getItem("tick_states") || "{}");
    } catch { return {}; }
}
function saveTickStates(states) {
    localStorage.setItem("tick_states", JSON.stringify(states));
}
function getTickedSet() {
    // For backward compat with filter
    const states = getTickStates();
    return new Set(Object.keys(states).filter(k => states[k] === "check"));
}
function getCrossedSet() {
    const states = getTickStates();
    return new Set(Object.keys(states).filter(k => states[k] === "cross"));
}
function toggleTick(symbol, event) {
    event.stopPropagation();
    if (!requirePassword()) return;
    const states = getTickStates();
    const current = states[symbol] || "none";
    // Cycle: none → check → cross → none
    if (current === "none") states[symbol] = "check";
    else if (current === "check") states[symbol] = "cross";
    else delete states[symbol]; // cross → none
    saveTickStates(states);
    // Update only the tick box in-place, don't re-render entire list
    updateTickBox(symbol);
}

function updateTickBox(symbol) {
    document.querySelectorAll(".stock-row").forEach(row => {
        const symEl = row.querySelector(".stock-symbol");
        if (symEl && (symEl.textContent === symbol || symEl.textContent === symbol.replace('.BK', ''))) {
            const tickBox = row.querySelector(".tick-box");
            if (!tickBox) return;
            const states = getTickStates();
            const state = states[symbol] || "none";
            tickBox.className = "tick-box" + (state === "check" ? " ticked" : state === "cross" ? " crossed" : "");
            tickBox.innerHTML = state === "check" ? "&#10003;" : state === "cross" ? "&#10005;" : "";
        }
    });
}

/* ─── Init ─── */
document.addEventListener("DOMContentLoaded", () => {
    // Load fibo stats
    fetch("/static/fibo_stats.json").then(r => r.json()).then(d => { fiboStats = d; }).catch(() => {});
    initBestRR();
    setupTabs();
    setupFilters();
    setupSearch();
    setupSort();
    setupTickedToggle();
    loadCategory(currentCategory);
});

/* ─── Tabs ─── */
function setupTabs() {
    document.querySelectorAll(".tab").forEach(tab => {
        tab.addEventListener("click", () => {
            document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            currentCategory = tab.dataset.category;

            if (currentCategory === "simulator") {
                document.querySelector(".main").style.display = "none";
                document.getElementById("simulator-panel").style.display = "block";
                loadSimulator();
            } else {
                document.querySelector(".main").style.display = "grid";
                document.getElementById("simulator-panel").style.display = "none";
                currentFilter = "all";
                document.querySelectorAll(".filter-bar .filter-btn").forEach(f => f.classList.remove("active"));
                const allBtn = document.querySelector('.filter-bar .filter-btn[data-filter="all"]');
                if (allBtn) allBtn.classList.add("active");
                loadCategory(currentCategory);
            }
        });
    });
}

/* ─── Filters ─── */
function setupFilters() {
    document.querySelectorAll(".filter-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentFilter = btn.dataset.filter;
            renderList(filterAndSort(allResults));
        });
    });
}

// ─── Sort by priority: Plan → Fibo → Sto → Stock ───
const PLAN_ORDER = {
    "BUY": 0, "RUNNING": 1, "WAIT": 2, "WATCH": 3, "NO ENTRY": 4, "WARN": 5,
};
function getPlanOrder(plan) {
    if (!plan) return 9;
    for (const [key, val] of Object.entries(PLAN_ORDER)) {
        if (plan.startsWith(key)) return val;
    }
    return 9;
}

const FIBO_ORDER = [0.5, 0.618, 0.382, 0.786, 1.0, 0.0, 1.382, 1.618, 2.0, 2.618];
function getFiboOrder(fiboPos) {
    if (!fiboPos || fiboPos === "-") return 99;
    const val = parseFloat(fiboPos);
    if (isNaN(val)) return 99;
    const idx = FIBO_ORDER.indexOf(val);
    return idx >= 0 ? idx : 50;
}

function getStoOrder(r) {
    // OS first (potential buy), then OB, then neutral
    if (r.in_os) return 0;
    if (r.in_ob) return 1;
    return 2;
}

function sortByPriority(a, b) {
    // 1. Plan priority
    const pa = getPlanOrder(a.plan);
    const pb = getPlanOrder(b.plan);
    if (pa !== pb) return pa - pb;
    // 2. Fibo level priority (golden zone first)
    const fa = getFiboOrder(a.fibo_pos);
    const fb = getFiboOrder(b.fibo_pos);
    if (fa !== fb) return fa - fb;
    // 3. Sto zone (OS > OB > neutral)
    const sa = getStoOrder(a);
    const sb = getStoOrder(b);
    if (sa !== sb) return sa - sb;
    // 4. Symbol A-Z
    return a.symbol.localeCompare(b.symbol);
}

function filterResults(results) {
    if (currentFilter === "all") return results;
    if (currentFilter === "uptrend") {
        return results.filter(r => r.trend === "UT").sort(sortByPriority);
    }
    if (currentFilter === "downtrend") {
        return results.filter(r => r.trend === "DT").sort(sortByPriority);
    }
    if (currentFilter === "sideway") {
        return results.filter(r => r.trend === "SW").sort(sortByPriority);
    }
    if (currentFilter === "ready") return results.filter(r => r.is_ready_entry);
    if (currentFilter === "ob") return results.filter(r => r.in_ob);
    if (currentFilter === "os") return results.filter(r => r.in_os);
    return results;
}

function sortResults(results) {
    const sorted = [...results];
    if (currentSort === "az") {
        sorted.sort((a, b) => a.symbol.localeCompare(b.symbol));
    } else if (currentSort === "za") {
        sorted.sort((a, b) => b.symbol.localeCompare(a.symbol));
    }
    return sorted;
}

function filterAndSort(results, applyExclude = true) {
    const crossed = getCrossedSet();
    let r;
    if (showExcluded) {
        r = results.filter(x => crossed.has(x.symbol));
    } else {
        if (applyExclude) {
            r = results.filter(x => !crossed.has(x.symbol));
        } else {
            r = [...results];
        }
        r = filterResults(r);
        if (tickedOnly) {
            const ticked = getTickedSet();
            r = r.filter(x => ticked.has(x.symbol));
        }
        if (starOnly) {
            r = r.filter(x => x.suitable);
        }
        if (warnOnly) {
            r = r.filter(x => !x.suitable);
        }
    }
    return sortResults(r);
}

let showExcluded = false;
let starOnly = false;
let warnOnly = false;

/* ─── Ticked Toggle ─── */
function setupTickedToggle() {
    const btn = document.getElementById("ticked-toggle");
    btn.addEventListener("click", () => {
        tickedOnly = !tickedOnly;
        btn.classList.toggle("active", tickedOnly);
        renderList(filterAndSort(allResults));
    });

    const exBtn = document.getElementById("excluded-toggle");
    exBtn.addEventListener("click", () => {
        showExcluded = !showExcluded;
        exBtn.classList.toggle("active", showExcluded);
        renderList(filterAndSort(allResults));
    });

    document.getElementById("star-toggle").addEventListener("click", () => {
        starOnly = !starOnly;
        if (starOnly) warnOnly = false;
        document.getElementById("star-toggle").classList.toggle("active", starOnly);
        document.getElementById("warn-toggle").classList.remove("active");
        renderList(filterAndSort(allResults));
    });

    document.getElementById("warn-toggle").addEventListener("click", () => {
        warnOnly = !warnOnly;
        if (warnOnly) starOnly = false;
        document.getElementById("warn-toggle").classList.remove("active");
        document.getElementById("star-toggle").classList.remove("active");
        document.getElementById("warn-toggle").classList.toggle("active", warnOnly);
        renderList(filterAndSort(allResults));
    });
}

/* ─── Sort ─── */
function setupSort() {
    document.querySelectorAll(".sort-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            if (btn.classList.contains("active")) {
                // Toggle off — remove sort
                btn.classList.remove("active");
                currentSort = "none";
            } else {
                document.querySelectorAll(".sort-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                currentSort = btn.dataset.sort;
            }
            renderList(filterAndSort(allResults));
        });
    });
}

/* ─── Search ─── */
function setupSearch() {
    const searchBox = document.getElementById("search-box");
    searchBox.addEventListener("input", () => {
        const q = searchBox.value.toUpperCase().trim();
        let filtered = filterAndSort(allResults);
        if (q) {
            filtered = filtered.filter(r => r.symbol.toUpperCase().includes(q));
        }
        renderList(filtered);
    });
}

/* ─── Load Category ─── */
async function loadCategory(category) {
    const loadingBar = document.getElementById("loading-bar");
    const listEl = document.getElementById("stock-list");
    const countEl = document.getElementById("stock-count");

    loadingBar.classList.add("active");
    listEl.innerHTML = '<div class="empty-state">Scanning stocks...</div>';
    countEl.textContent = "Loading...";

    try {
        const res = await fetch(`/api/scan/${category}`);
        allResults = await res.json();
        countEl.textContent = `${allResults.length} stocks loaded`;
        renderList(filterAndSort(allResults, false));
    } catch (e) {
        listEl.innerHTML = '<div class="empty-state">Error loading data</div>';
        console.error(e);
    } finally {
        loadingBar.classList.remove("active");
    }
}

/* ─── Render Stock List ─── */
function renderList(results) {
    const listEl = document.getElementById("stock-list");
    const countEl = document.getElementById("stock-count");

    countEl.textContent = `${results.length} stocks` + (currentFilter !== "all" ? ` (filtered)` : "");

    if (results.length === 0) {
        listEl.innerHTML = '<div class="empty-state">No stocks match filter</div>';
        return;
    }

    const tickStates = getTickStates();

    // Header row
    const headerHtml = `
        <div class="stock-row stock-header">
            <div class="stock-tick"></div>
            <div class="stock-symbol">Stock</div>
            <div class="stock-price">Price</div>
            <div class="stock-change">Change%</div>
            <div class="stock-zone">Sto</div>
            <div class="stock-div">Sto Div</div>
            <div class="stock-div">RSI Div</div>
            <div class="stock-fibo">Fibo</div>
            <div class="stock-status">Plan</div>
            <div class="stock-stat">Statistic</div>
        </div>
    `;

    const rowsHtml = results.map(r => {
        const changeClass = r.change_pct >= 0 ? "up" : "down";
        const changeSign = r.change_pct >= 0 ? "+" : "";

        // OB/OS badge
        let zoneHtml = "";
        if (r.in_ob) {
            zoneHtml = `<span class="zone-badge ob">OB</span>`;
        } else if (r.in_os) {
            zoneHtml = `<span class="zone-badge os">OS</span>`;
        }

        const activeClass = r.symbol === currentSymbol ? "active" : "";
        const tickState = tickStates[r.symbol] || "none";
        const tickClass = tickState === "check" ? "ticked" : tickState === "cross" ? "crossed" : "";
        const tickChar = tickState === "check" ? "&#10003;" : tickState === "cross" ? "&#10005;" : "";

        // Divergence badges
        const stoDivHtml = r.sto_div ? '<span class="div-badge sto">Div</span>' : "";
        const rsiDivHtml = r.rsi_div ? '<span class="div-badge rsi">Div</span>' : "";

        // Plan
        const planText = r.plan || r.status || "";

        return `
            <div class="stock-row ${activeClass}" onclick="loadChart('${r.symbol}')">
                <div class="stock-tick" onclick="toggleTick('${r.symbol}', event)">
                    <span class="tick-box ${tickClass}">${tickChar}</span>
                </div>
                <div class="stock-symbol">${r.symbol.replace('.BK', '')}</div>
                <div class="stock-price">${formatPrice(r.close)}</div>
                <div class="stock-change ${changeClass}"><span>${changeSign}${r.change_pct}%</span></div>
                <div class="stock-zone">${zoneHtml}</div>
                <div class="stock-div">${stoDivHtml}</div>
                <div class="stock-div">${rsiDivHtml}</div>
                <div class="stock-fibo"><span class="fibo-val">${r.fibo_pos || '-'}</span></div>
                <div class="stock-status"><span class="status-badge ${r.suitable ? 'ut-wait' : 'dt'}" style="font-size:9px;">${planText}</span></div>
                <div class="stock-stat">${fiboStats[r.symbol] || ''}</div>
            </div>
        `;
    }).join("");

    listEl.innerHTML = headerHtml + rowsHtml;
}

function formatPrice(price) {
    if (price > 1000) return price.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (price > 1) return price.toFixed(2);
    return price.toFixed(4);
}

/* ─── Chart ─── */
async function loadChart(symbol) {
    currentSymbol = symbol;

    document.querySelectorAll(".stock-row").forEach(row => row.classList.remove("active"));
    document.querySelectorAll(".stock-row").forEach(row => {
        if (row.querySelector(".stock-symbol").textContent === symbol.replace('.BK', '')) {
            row.classList.add("active");
        }
    });

    document.getElementById("chart-title").textContent = symbol.replace('.BK', '');
    document.querySelector(".chart-panel").classList.add("visible");

    try {
        const res = await fetch(`/api/chart/${symbol}`);
        const data = await res.json();
        renderChart(data);
        renderScanInfo(data.scan);
    } catch (e) {
        console.error("Chart error:", e);
    }
}

function renderChart(data) {
    const mainEl = document.getElementById("main-chart");
    const rsiEl = document.getElementById("rsi-chart");
    const stochEl = document.getElementById("stoch-chart");

    mainEl.innerHTML = "";
    rsiEl.innerHTML = "";
    stochEl.innerHTML = "";

    const chartOpts = {
        layout: {
            background: { color: "#0f1117" },
            textColor: "#8b8fa3",
            fontSize: 11,
        },
        grid: {
            vertLines: { color: "#1a1d28" },
            horzLines: { color: "#1a1d28" },
        },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: "#2a2d3e" },
        timeScale: {
            borderColor: "#2a2d3e",
            timeVisible: false,
            rightOffset: 15,
        },
    };

    // ─── Main candlestick chart ───
    mainChart = LightweightCharts.createChart(mainEl, {
        ...chartOpts,
        width: mainEl.clientWidth,
        height: mainEl.clientHeight,
    });

    candleSeries = mainChart.addCandlestickSeries({
        upColor: "#26a69a",
        downColor: "#ef5350",
        borderUpColor: "#26a69a",
        borderDownColor: "#ef5350",
        wickUpColor: "#26a69a",
        wickDownColor: "#ef5350",
    });
    candleSeries.setData(data.candles);

    volumeSeries = mainChart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "volume",
    });
    mainChart.priceScale("volume").applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeSeries.setData(data.volumes);

    // ─── WL / SL / TP lines — only for Uptrend ───
    // Override TP with per-stock RR if available
    if (data.scan && data.scan.sl_ref && data.scan.close) {
        const rrData = getStockRR();
        const customRR = rrData[data.symbol];
        if (customRR) {
            const slDist = Math.abs(data.scan.close - data.scan.sl_ref);
            data.scan.tp_ref = data.scan.close + slDist * customRR;
        }
    }
    if (data.scan && data.scan.trend === "UT") {
        if (data.scan.white_line) {
            candleSeries.createPriceLine({
                price: data.scan.white_line,
                color: "#ffffff",
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: "WL",
            });
        }
        if (data.scan.sl_ref) {
            candleSeries.createPriceLine({
                price: data.scan.sl_ref,
                color: "#ef5350",
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: "SL",
            });
        }
        if (data.scan.tp_ref) {
            candleSeries.createPriceLine({
                price: data.scan.tp_ref,
                color: "#26a69a",
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: "TP",
            });
        }
    }

    // ─── Fibonacci levels on chart (start from fibo_start_date) ───
    if (data.scan && data.scan.fibo_levels && data.scan.fibo_start_date) {
        const fiboColor = "#5b7fff";
        const startDate = data.scan.fibo_start_date;
        const endDate = data.candles[data.candles.length - 1].time;
        const levels = data.scan.fibo_levels;

        // Find the candle date just before startDate for the label
        let labelDate = startDate;
        for (let ci = data.candles.length - 1; ci >= 0; ci--) {
            if (data.candles[ci].time < startDate) {
                labelDate = data.candles[ci].time;
                break;
            }
        }

        for (const [lvl, price] of Object.entries(levels)) {
            const series = mainChart.addLineSeries({
                color: fiboColor,
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                crosshairMarkerVisible: false,
                lastValueVisible: false,
                priceLineVisible: false,
            });
            // Line from labelDate (with label) to endDate
            series.setData([
                { time: labelDate, value: price },
                { time: startDate, value: price },
                { time: endDate, value: price },
            ]);
            // Label marker at labelDate (left end of line)
            series.setMarkers([{
                time: labelDate,
                position: "aboveBar",
                color: fiboColor,
                shape: "square",
                text: lvl,
                size: 0,
            }]);
        }
    }

    mainChart.timeScale().fitContent();

    // ─── RSI chart ───
    rsiChart = LightweightCharts.createChart(rsiEl, {
        layout: chartOpts.layout,
        grid: chartOpts.grid,
        crosshair: chartOpts.crosshair,
        width: rsiEl.clientWidth,
        height: rsiEl.clientHeight,
        rightPriceScale: { borderColor: "#2a2d3e", scaleMargins: { top: 0.05, bottom: 0.05 } },
        timeScale: { borderColor: "#2a2d3e", timeVisible: false, rightOffset: 15 },
        handleScroll: false,
        handleScale: false,
    });

    // RSI data — API already aligned to same dates as candles
    const rsiSeries = rsiChart.addLineSeries({
        color: "#e040fb", lineWidth: 1.5, title: "RSI",
        priceFormat: { type: "custom", formatter: v => v.toFixed(0) },
    });
    if (data.rsi) rsiSeries.setData(data.rsi);

    // RSI 70/30 lines
    const allDates = data.candles.map(c => c.time);
    rsiChart.addLineSeries({
        color: "rgba(239,83,80,0.6)", lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Solid,
        crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
    }).setData(allDates.map(t => ({ time: t, value: 70 })));
    rsiChart.addLineSeries({
        color: "rgba(38,166,154,0.6)", lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Solid,
        crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
    }).setData(allDates.map(t => ({ time: t, value: 30 })));

    // ─── Stochastic chart ───
    stochChart = LightweightCharts.createChart(stochEl, {
        layout: chartOpts.layout,
        grid: chartOpts.grid,
        crosshair: chartOpts.crosshair,
        width: stochEl.clientWidth,
        height: stochEl.clientHeight,
        rightPriceScale: { borderColor: "#2a2d3e", scaleMargins: { top: 0.05, bottom: 0.05 } },
        timeScale: { borderColor: "#2a2d3e", timeVisible: false, rightOffset: 15 },
        handleScroll: false,
        handleScale: false,
    });

    stochKSeries = stochChart.addLineSeries({
        color: "#5b7fff",
        lineWidth: 1.5,
        title: "K",
        priceFormat: { type: "custom", formatter: v => v.toFixed(1) },
    });

    stochDSeries = stochChart.addLineSeries({
        color: "#ff6d00",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        title: "D",
        priceFormat: { type: "custom", formatter: v => v.toFixed(1) },
    });

    // Stoch data — API provides same count as candles, no nulls
    const kData = data.stochastic.map(s => ({ time: s.time, value: s.k }));
    const dData = data.stochastic.map(s => ({ time: s.time, value: s.d }));
    stochKSeries.setData(kData);
    stochDSeries.setData(dData);

    const obLineData = allDates.map(t => ({ time: t, value: 80 }));
    const osLineData = allDates.map(t => ({ time: t, value: 20 }));

    obLine = stochChart.addLineSeries({
        color: "rgba(239,83,80,0.6)", lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
    });
    obLine.setData(obLineData);

    osLine = stochChart.addLineSeries({
        color: "rgba(38,166,154,0.6)", lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
    });
    osLine.setData(osLineData);

    // Sync all 3 charts: main is the leader, RSI + stoch follow
    // Initial sync: copy main's range after fitContent
    const initRange = mainChart.timeScale().getVisibleLogicalRange();
    if (initRange) {
        rsiChart.timeScale().setVisibleLogicalRange(initRange);
        stochChart.timeScale().setVisibleLogicalRange(initRange);
    }

    // Ongoing sync: main → RSI + stoch
    let syncPending = false;
    mainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (syncPending || !range) return;
        syncPending = true;
        requestAnimationFrame(() => {
            rsiChart.timeScale().setVisibleLogicalRange(range);
            stochChart.timeScale().setVisibleLogicalRange(range);
            syncPending = false;
        });
    });


    const resizeObserver = new ResizeObserver(() => {
        mainChart.applyOptions({ width: mainEl.clientWidth, height: mainEl.clientHeight });
        rsiChart.applyOptions({ width: rsiEl.clientWidth, height: rsiEl.clientHeight });
        stochChart.applyOptions({ width: stochEl.clientWidth, height: stochEl.clientHeight });
    });
    resizeObserver.observe(mainEl);
    resizeObserver.observe(rsiEl);
    resizeObserver.observe(stochEl);
}

/* ─── Scan Info Panel ─── */
function renderScanInfo(scan) {
    const el = document.getElementById("scan-info");
    if (!scan) {
        el.innerHTML = '<div class="info-item"><span class="info-value neutral">No scan data</span></div>';
        return;
    }

    const statusClass = scan.trend === "UT" ? "buy" : scan.trend === "SW" ? "neutral" : "sell";

    el.innerHTML = `
        <div class="info-item">
            <span class="info-label">Status</span>
            <span class="info-value ${statusClass}">${scan.status}</span>
        </div>
        <div class="info-item">
            <span class="info-label">Structure</span>
            <span class="info-value neutral">${scan.structure ? scan.structure.toUpperCase() : '-'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">Sto Div</span>
            <span class="info-value ${scan.sto_div ? 'buy' : 'neutral'}">${scan.sto_div ? 'Yes' : 'No'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">RSI Div</span>
            <span class="info-value ${scan.rsi_div ? 'buy' : 'neutral'}">${scan.rsi_div ? 'Yes' : 'No'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">Fibo Level</span>
            <span class="info-value neutral">${scan.fibo_pos || '-'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">Stoch K / D</span>
            <span class="info-value neutral">${scan.stoch_k} / ${scan.stoch_d}</span>
        </div>
        <div class="info-item">
            <span class="info-label">White Line</span>
            <span class="info-value neutral">${scan.white_line ? formatPrice(scan.white_line) : '-'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">Swing Low</span>
            <span class="info-value neutral">${formatPrice(scan.swing_price)} (${scan.swing_date})</span>
        </div>
        <div class="info-item">
            <span class="info-label">SL Ref</span>
            <span class="info-value sell">${scan.sl_ref ? formatPrice(scan.sl_ref) : '-'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">TP Ref</span>
            <span class="info-value buy">${scan.tp_ref ? formatPrice(scan.tp_ref) : '-'}</span>
        </div>
        <div class="info-item">
            <span class="info-label">R:R</span>
            <span class="info-value neutral">${scan.rr_ratio ? '1:' + scan.rr_ratio : '-'}</span>
        </div>
    `;
}

/* ═══════════════════════════════════════════════════════════════════════
   SIMULATOR
   ═══════════════════════════════════════════════════════════════════════ */

let simFilter = "all"; // all | nasdaq100 | sp500 | set100 | thai_energy | open | pending | closed
let simTrades = [];

function setupSimulator() {
    document.querySelectorAll("[data-simfilter]").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("[data-simfilter]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            simFilter = btn.dataset.simfilter;
            renderSimTrades();
        });
    });

    document.getElementById("sim-scan-btn").addEventListener("click", runSimScan);

    // Sort by clicking column headers
    document.querySelectorAll(".sim-sortable").forEach(th => {
        th.addEventListener("click", () => {
            document.querySelectorAll(".sim-sortable").forEach(h => h.classList.remove("sort-active"));
            th.classList.add("sort-active");
            simSort = th.dataset.simsort;
            renderSimTrades();
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    setupSimulator();
});

async function loadSimulator() {
    await loadSimSummary();
    await loadSimTrades();
}

async function loadSimSummary() {
    try {
        const res = await fetch("/api/simulator/summary");
        const s = await res.json();
        const statsEl = document.getElementById("sim-stats");
        const pnlClass = s.total_pnl_thb >= 0 ? "positive" : "negative";
        const unrealClass = s.total_unrealized_thb >= 0 ? "positive" : "negative";

        statsEl.innerHTML = `
            <div class="sim-stat">
                <span class="sim-stat-label">Budget/Trade</span>
                <span class="sim-stat-value">${Number(s.budget_per_trade).toLocaleString()} THB</span>
            </div>
            <div class="sim-stat">
                <span class="sim-stat-label">USD/THB</span>
                <span class="sim-stat-value">${s.usdthb.toFixed(2)}</span>
            </div>
            <div class="sim-stat">
                <span class="sim-stat-label">Open</span>
                <span class="sim-stat-value">${s.open}</span>
            </div>
            <div class="sim-stat">
                <span class="sim-stat-label">Pending</span>
                <span class="sim-stat-value">${s.pending}</span>
            </div>
            <div class="sim-stat">
                <span class="sim-stat-label">Win / Loss</span>
                <span class="sim-stat-value">${s.tp_hit} / ${s.sl_hit}</span>
            </div>
            <div class="sim-stat">
                <span class="sim-stat-label">Win Rate</span>
                <span class="sim-stat-value">${s.win_rate}%</span>
            </div>
            <div class="sim-stat">
                <span class="sim-stat-label">Realized P/L</span>
                <span class="sim-stat-value ${pnlClass}">${s.total_pnl_thb >= 0 ? '+' : ''}${Number(s.total_pnl_thb).toLocaleString()} THB</span>
            </div>
            <div class="sim-stat">
                <span class="sim-stat-label">Unrealized P/L</span>
                <span class="sim-stat-value ${unrealClass}">${s.total_unrealized_thb >= 0 ? '+' : ''}${Number(s.total_unrealized_thb).toLocaleString()} THB</span>
            </div>
        `;
    } catch (e) {
        console.error("Summary error:", e);
    }
}

async function loadSimTrades() {
    try {
        const res = await fetch("/api/simulator/trades");
        simTrades = await res.json();
        renderSimTrades();
    } catch (e) {
        console.error("Trades error:", e);
    }
}

let simSort = "status"; // default sort
const SIM_STATUS_ORDER = { open: 0, pending: 1, tp_hit: 2, sl_hit: 3, skipped: 4 };
const SIM_CAT_ORDER = { nasdaq100: 0, sp500: 1, set100: 2, thai_energy: 3 };

function sortSimTrades(trades) {
    return [...trades].sort((a, b) => {
        if (simSort === "status") {
            const sa = SIM_STATUS_ORDER[a.status] ?? 9;
            const sb = SIM_STATUS_ORDER[b.status] ?? 9;
            if (sa !== sb) return sa - sb;
            const ca = SIM_CAT_ORDER[a.category] ?? 9;
            const cb = SIM_CAT_ORDER[b.category] ?? 9;
            if (ca !== cb) return ca - cb;
            return a.symbol.localeCompare(b.symbol);
        }
        if (simSort === "market") {
            const ca = SIM_CAT_ORDER[a.category] ?? 9;
            const cb = SIM_CAT_ORDER[b.category] ?? 9;
            if (ca !== cb) return ca - cb;
            return a.symbol.localeCompare(b.symbol);
        }
        if (simSort === "symbol") {
            return a.symbol.localeCompare(b.symbol);
        }
        if (simSort === "pnl") {
            const pa = a.pnl_thb || a.unrealized_thb || 0;
            const pb = b.pnl_thb || b.unrealized_thb || 0;
            return pb - pa; // highest first
        }
        return 0;
    });
}

function renderSimTrades() {
    const tbody = document.getElementById("sim-tbody");
    let filtered = simTrades;

    const catFilters = ["nasdaq100", "sp500", "set100", "thai_energy"];

    if (catFilters.includes(simFilter)) {
        filtered = filtered.filter(t => t.category === simFilter);
    } else if (simFilter === "open") {
        filtered = filtered.filter(t => t.status === "open");
    } else if (simFilter === "pending") {
        filtered = filtered.filter(t => t.status === "pending");
    } else if (simFilter === "closed") {
        filtered = filtered.filter(t => t.status === "tp_hit" || t.status === "sl_hit");
    }

    filtered = sortSimTrades(filtered);

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;color:var(--text-muted);padding:40px;">No trades</td></tr>';
        return;
    }

    const catLabels = { nasdaq100: "NASDAQ", sp500: "SP500", set100: "SET", thai_energy: "Energy" };
    const tickStatesForSim = getTickStates();

    tbody.innerHTML = filtered.map(t => {
        const statusLabel = {open: "Open", pending: "Pending", tp_hit: "TP Hit", sl_hit: "SL Hit", skipped: "Skipped"}[t.status] || t.status;
        const simTickState = tickStatesForSim[t.symbol] || "none";
        const simTickIcon = simTickState === "check" ? '<span class="tick-box ticked" style="width:16px;height:16px;font-size:10px;">&#10003;</span>' : '';

        // P/L
        let plThb = null;
        let plPct = null;
        if (t.status === "tp_hit" || t.status === "sl_hit") {
            plThb = t.pnl_thb;
            if (t.entry_price && t.close_price) plPct = ((t.close_price - t.entry_price) / t.entry_price * 100);
        } else if (t.status === "open" && t.unrealized_thb !== undefined) {
            plThb = t.unrealized_thb;
            if (t.entry_price && t.current_price) plPct = ((t.current_price - t.entry_price) / t.entry_price * 100);
        }

        const plHtml = plThb !== null
            ? `<span class="sim-pnl ${plThb >= 0 ? 'positive' : 'negative'}">${plThb >= 0 ? '+' : ''}${Number(Math.round(plThb)).toLocaleString()}</span>`
            : "-";
        const plPctHtml = plPct !== null
            ? `<span class="sim-pnl ${plPct >= 0 ? 'positive' : 'negative'}">${plPct >= 0 ? '+' : ''}${plPct.toFixed(1)}%</span>`
            : "-";

        const curPrice = t.current_price || t.close_price;

        return `<tr onclick="loadSimChart('${t.symbol}', ${JSON.stringify(t).replace(/"/g, '&quot;')})" data-symbol="${t.symbol}">
            <td style="text-align:center;">${simTickIcon}</td>
            <td>${catLabels[t.category] || t.category}</td>
            <td style="font-weight:600;">${t.symbol.replace('.BK','')}</td>
            <td><span class="sim-status ${t.status}">${statusLabel}</span></td>
            <td>${t.signal_date || '-'}</td>
            <td>${t.entry_date || '-'}</td>
            <td>${t.entry_price ? formatPrice(t.entry_price) : '-'}</td>
            <td>${t.shares || '-'}</td>
            <td>${t.entry_price && t.shares ? Math.round((t.is_thai ? t.entry_price * t.shares : t.entry_price * t.shares * (t.usdthb_at_entry || 34))).toLocaleString() : '-'}</td>
            <td>${t.sl ? formatPrice(t.sl) : '-'}</td>
            <td>${t.tp ? formatPrice(t.tp) : '-'}</td>
            <td>${curPrice ? formatPrice(curPrice) : '-'}</td>
            <td>${plHtml}</td>
            <td>${plPctHtml}</td>
        </tr>`;
    }).join("");
}

let simMainChart = null;
let simStochChart = null;

async function loadSimChart(symbol, trade) {
    // Highlight active row
    document.querySelectorAll("#sim-tbody tr").forEach(r => r.classList.remove("active"));
    document.querySelectorAll(`#sim-tbody tr[data-symbol="${symbol}"]`).forEach(r => r.classList.add("active"));

    document.getElementById("sim-chart-title").textContent = symbol.replace('.BK', '');

    try {
        const res = await fetch(`/api/chart/${symbol}`);
        const data = await res.json();
        if (data.error) return;
        renderSimChart(data, trade);
    } catch (e) {
        console.error("Sim chart error:", e);
    }
}

function renderSimChart(data, trade) {
    const mainEl = document.getElementById("sim-main-chart");
    const stochEl = document.getElementById("sim-stoch-chart");
    mainEl.innerHTML = "";
    stochEl.innerHTML = "";

    const chartOpts = {
        layout: { background: { color: "#0f1117" }, textColor: "#8b8fa3", fontSize: 11 },
        grid: { vertLines: { color: "#1a1d28" }, horzLines: { color: "#1a1d28" } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: "#2a2d3e" },
        timeScale: { borderColor: "#2a2d3e", timeVisible: false, rightOffset: 15 },
    };

    // Main chart
    simMainChart = LightweightCharts.createChart(mainEl, {
        ...chartOpts, width: mainEl.clientWidth, height: mainEl.clientHeight,
    });

    const candles = simMainChart.addCandlestickSeries({
        upColor: "#26a69a", downColor: "#ef5350",
        borderUpColor: "#26a69a", borderDownColor: "#ef5350",
        wickUpColor: "#26a69a", wickDownColor: "#ef5350",
    });
    candles.setData(data.candles);

    const vol = simMainChart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "volume" });
    simMainChart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    vol.setData(data.volumes);

    // Trade lines: Entry, SL, TP
    if (trade && trade.entry_price) {
        candles.createPriceLine({
            price: trade.entry_price, color: "#42a5f5", lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Solid, axisLabelVisible: true, title: "Entry",
        });
    }
    if (trade && trade.sl) {
        candles.createPriceLine({
            price: trade.sl, color: "#ef5350", lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: "SL",
        });
    }
    if (trade && trade.tp) {
        candles.createPriceLine({
            price: trade.tp, color: "#26a69a", lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: "TP",
        });
    }
    if (trade && trade.white_line) {
        candles.createPriceLine({
            price: trade.white_line, color: "#ffffff", lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: "WL",
        });
    }

    simMainChart.timeScale().fitContent();

    // Stoch chart
    simStochChart = LightweightCharts.createChart(stochEl, {
        ...chartOpts, width: stochEl.clientWidth, height: stochEl.clientHeight,
        rightPriceScale: { borderColor: "#2a2d3e", scaleMargins: { top: 0.05, bottom: 0.05 } },
        handleScroll: { mouseWheel: false, pressedMouseMove: false, horzTouchDrag: false, vertTouchDrag: false },
        handleScale: { mouseWheel: false, pinch: false, axisPressedMouseMove: false, axisDoubleClickReset: false },
    });

    const kSeries = simStochChart.addLineSeries({
        color: "#5b7fff", lineWidth: 1.5, title: "K",
        priceFormat: { type: "custom", formatter: v => v.toFixed(1) },
    });
    const dSeries = simStochChart.addLineSeries({
        color: "#ff6d00", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: "D",
        priceFormat: { type: "custom", formatter: v => v.toFixed(1) },
    });

    const stochMap = {};
    data.stochastic.forEach(s => { if (s.k !== null) stochMap[s.time] = s; });
    const kData = [], dData2 = [];
    for (const c of data.candles) {
        if (stochMap[c.time]) {
            kData.push({ time: c.time, value: stochMap[c.time].k });
            if (stochMap[c.time].d !== null) dData2.push({ time: c.time, value: stochMap[c.time].d });
        }
    }
    kSeries.setData(kData);
    dSeries.setData(dData2);

    const allDates = data.candles.map(c => c.time);
    const obL = simStochChart.addLineSeries({
        color: "rgba(239,83,80,0.4)", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
        crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
    });
    obL.setData(allDates.map(t => ({ time: t, value: 79 })));
    const osL = simStochChart.addLineSeries({
        color: "rgba(38,166,154,0.4)", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
        crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
    });
    osL.setData(allDates.map(t => ({ time: t, value: 21 })));

    simStochChart.timeScale().fitContent();

    // Sync
    let sp = false;
    simMainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (sp || !range) return;
        sp = true;
        requestAnimationFrame(() => {
            simStochChart.timeScale().setVisibleLogicalRange(range);
            sp = false;
        });
    });

    // Resize
    const ro = new ResizeObserver(() => {
        simMainChart.applyOptions({ width: mainEl.clientWidth, height: mainEl.clientHeight });
        simStochChart.applyOptions({ width: stochEl.clientWidth, height: stochEl.clientHeight });
    });
    ro.observe(mainEl);
    ro.observe(stochEl);
}

async function runSimScan() {
    const btn = document.getElementById("sim-scan-btn");
    const loading = document.getElementById("sim-loading");
    btn.classList.add("loading");
    btn.textContent = "Scanning...";
    loading.classList.add("active");

    try {
        await fetch("/api/simulator/scan");
        await loadSimulator();
    } catch (e) {
        console.error("Scan error:", e);
    } finally {
        btn.classList.remove("loading");
        btn.textContent = "Scan & Update";
        loading.classList.remove("active");
    }
}

/* backtest removed */
if (false) {

    document.querySelectorAll("[data-btfilter]").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("[data-btfilter]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            btFilter = btn.dataset.btfilter;
            renderBtTrades();
        });
    });

    document.querySelectorAll("[data-rr]").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("[data-rr]").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            btSelectedRR = parseFloat(btn.dataset.rr);
            // Re-run with new RR if we have data
            if (btTrades.length > 0 || document.getElementById("bt-rr-compare").innerHTML) {
                runBacktest();
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", () => {
    setupBacktest();
});

async function runBacktest() {
    const btn = document.getElementById("bt-run-btn");
    const loading = document.getElementById("bt-loading");
    btn.classList.add("loading");
    btn.textContent = "Running backtest...";
    loading.classList.add("active");

    const ticked = getTickedSet();
    const symbols = [...ticked];

    if (symbols.length === 0) {
        alert("No ticked stocks. Tick some stocks first.");
        btn.classList.remove("loading");
        btn.textContent = "Run Backtest (Ticked, 12M)";
        loading.classList.remove("active");
        return;
    }

    try {
        const res = await fetch("/api/backtest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbols, rr: btSelectedRR }),
        });
        const data = await res.json();
        btTrades = data.trades || [];
        renderBtSummary(data.summary || {});
        renderBtRRCompare(data.rr_comparison || [], data.selected_rr);
        renderBtPerStock(data.per_stock_rr || []);
        renderBtTrades();
    } catch (e) {
        console.error("Backtest error:", e);
    } finally {
        btn.classList.remove("loading");
        btn.textContent = "Run Backtest (Ticked, 12M)";
        loading.classList.remove("active");
    }
}

function renderBtRRCompare(comparisons, selectedRR) {
    const el = document.getElementById("bt-rr-compare");
    if (!comparisons || comparisons.length === 0) {
        el.innerHTML = "";
        return;
    }

    // Find best by total_pnl_thb
    let bestIdx = 0;
    comparisons.forEach((c, i) => { if (c.total_pnl_thb > comparisons[bestIdx].total_pnl_thb) bestIdx = i; });

    const rows = comparisons.map((c, i) => {
        const isBest = i === bestIdx;
        const isSelected = c.rr === selectedRR;
        const pnlClass = c.total_pnl_thb >= 0 ? "rr-positive" : "rr-negative";
        const rowClass = isBest ? "best" : "";
        const marker = isSelected ? " *" : "";
        return `<tr class="${rowClass}">
            <td style="font-weight:${isSelected ? '700' : '400'};">RR ${c.rr}${marker}</td>
            <td>${c.total || 0}</td>
            <td>${c.tp || 0}</td>
            <td>${c.sl || 0}</td>
            <td>${c.win_rate || 0}%</td>
            <td class="${pnlClass}">${c.total_pnl_thb >= 0 ? '+' : ''}${Number(Math.round(c.total_pnl_thb || 0)).toLocaleString()}</td>
            <td class="rr-positive">+${Number(Math.round(c.avg_win_thb || 0)).toLocaleString()}</td>
            <td class="rr-negative">${Number(Math.round(c.avg_loss_thb || 0)).toLocaleString()}</td>
            <td>${c.profit_factor || 0}</td>
        </tr>`;
    }).join("");

    el.innerHTML = `<table>
        <thead><tr>
            <th>R:R</th><th>Trades</th><th>Win</th><th>Loss</th><th>Win Rate</th>
            <th>Total P/L (THB)</th><th>Avg Win</th><th>Avg Loss</th><th>PF</th>
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;
}

function renderBtPerStock(perStock) {
    const el = document.getElementById("bt-per-stock");
    if (!perStock || perStock.length === 0) {
        el.innerHTML = "";
        return;
    }

    const rrs = [0.5, 0.75, 1.0, 1.25];

    const headerCols = rrs.map(rr => `<th colspan="3" style="border-left:1px solid var(--border);">RR ${rr}</th>`).join("");
    const subHeader = rrs.map(() => `<th style="border-left:1px solid var(--border);">W/L</th><th>WR%</th><th>P/L</th>`).join("");

    const rows = perStock.map(s => {
        const rrCells = rrs.map(rr => {
            const d = s.rr_details[rr] || { trades: 0, tp: 0, sl: 0, wr: 0, pnl_thb: 0 };
            const isBest = rr === s.best_rr;
            const pnlClass = d.pnl_thb >= 0 ? "rr-positive" : "rr-negative";
            const cellStyle = isBest ? "font-weight:700;background:rgba(38,166,154,0.08);" : "";
            return `<td style="border-left:1px solid var(--border);${cellStyle}">${d.tp}/${d.sl}</td>` +
                   `<td style="${cellStyle}">${d.wr}%</td>` +
                   `<td class="${pnlClass}" style="${cellStyle}">${d.pnl_thb >= 0 ? '+' : ''}${Number(Math.round(d.pnl_thb)).toLocaleString()}</td>`;
        }).join("");

        const bestClass = s.best_pnl_thb >= 0 ? "rr-positive" : "rr-negative";
        return `<tr>
            <td style="font-weight:600;">${s.symbol.replace('.BK','')}</td>
            <td style="font-weight:700;color:var(--accent);">${s.best_rr}</td>
            <td class="${bestClass}" style="font-weight:600;">${s.best_pnl_thb >= 0 ? '+' : ''}${Number(Math.round(s.best_pnl_thb)).toLocaleString()}</td>
            ${rrCells}
        </tr>`;
    }).join("");

    el.innerHTML = `<div style="font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:6px;">Per-Stock RR Analysis</div>
    <div style="overflow-x:auto;"><table>
        <thead>
            <tr><th>Symbol</th><th>Best RR</th><th>Best P/L</th>${headerCols}</tr>
            <tr><th></th><th></th><th>(THB)</th>${subHeader}</tr>
        </thead>
        <tbody>${rows}</tbody>
    </table></div>`;
}

function renderBtSummary(s) {
    const el = document.getElementById("bt-stats");
    if (!s || !s.total) {
        el.innerHTML = '<div class="sim-stat"><span class="sim-stat-value neutral">No results</span></div>';
        return;
    }
    const pnlClass = s.total_pnl_thb >= 0 ? "positive" : "negative";
    el.innerHTML = `
        <div class="sim-stat">
            <span class="sim-stat-label">Total Trades</span>
            <span class="sim-stat-value">${s.total}</span>
        </div>
        <div class="sim-stat">
            <span class="sim-stat-label">Win / Loss</span>
            <span class="sim-stat-value">${s.tp} / ${s.sl}</span>
        </div>
        <div class="sim-stat">
            <span class="sim-stat-label">Win Rate</span>
            <span class="sim-stat-value">${s.win_rate}%</span>
        </div>
        <div class="sim-stat">
            <span class="sim-stat-label">Total P/L</span>
            <span class="sim-stat-value ${pnlClass}">${s.total_pnl_thb >= 0 ? '+' : ''}${Number(s.total_pnl_thb).toLocaleString()} THB</span>
        </div>
        <div class="sim-stat">
            <span class="sim-stat-label">Avg Win</span>
            <span class="sim-stat-value positive">+${Number(s.avg_win_thb).toLocaleString()} THB</span>
        </div>
        <div class="sim-stat">
            <span class="sim-stat-label">Avg Loss</span>
            <span class="sim-stat-value negative">${Number(s.avg_loss_thb).toLocaleString()} THB</span>
        </div>
        <div class="sim-stat">
            <span class="sim-stat-label">Profit Factor</span>
            <span class="sim-stat-value">${s.profit_factor}</span>
        </div>
        <div class="sim-stat">
            <span class="sim-stat-label">Avg Bars Held</span>
            <span class="sim-stat-value">${s.avg_bars_held}</span>
        </div>
    `;
}

function renderBtTrades() {
    const tbody = document.getElementById("bt-tbody");
    let filtered = btTrades;

    if (btFilter !== "all") {
        filtered = filtered.filter(t => t.result === btFilter);
    }

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;color:var(--text-muted);padding:40px;">No trades</td></tr>';
        return;
    }

    tbody.innerHTML = filtered.map(t => {
        const resultClass = t.result === "TP" ? "tp_hit" : t.result === "SL" ? "sl_hit" : "open";
        const pnlClass = t.pnl_thb >= 0 ? "positive" : "negative";

        return `<tr onclick="loadBtChart('${t.symbol}', ${JSON.stringify(t).replace(/"/g, '&quot;')})" data-symbol="${t.symbol}">
            <td style="font-weight:600;">${t.symbol.replace('.BK','')}</td>
            <td><span class="sim-status ${resultClass}">${t.result}</span></td>
            <td>${t.signal_date}</td>
            <td>${t.entry_date}</td>
            <td>${formatPrice(t.entry_price)}</td>
            <td>${t.close_date}</td>
            <td>${formatPrice(t.close_price)}</td>
            <td>${t.shares}</td>
            <td>${Math.round(t.invested_thb).toLocaleString()}</td>
            <td><span class="sim-pnl ${pnlClass}">${t.pnl_thb >= 0 ? '+' : ''}${Number(Math.round(t.pnl_thb)).toLocaleString()}</span></td>
            <td><span class="sim-pnl ${pnlClass}">${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct}%</span></td>
            <td>${t.bars_held}</td>
        </tr>`;
    }).join("");
}

async function loadBtChart(symbol, trade) {
    document.querySelectorAll("#bt-tbody tr").forEach(r => r.classList.remove("active"));
    document.querySelectorAll(`#bt-tbody tr[data-symbol="${symbol}"]`).forEach(r => r.classList.add("active"));
    document.getElementById("bt-chart-title").textContent = symbol.replace('.BK', '');

    try {
        const res = await fetch(`/api/chart/${symbol}`);
        const data = await res.json();
        if (data.error) return;
        renderBtChart(data, trade);
    } catch (e) {
        console.error("BT chart error:", e);
    }
}

function renderBtChart(data, trade) {
    const mainEl = document.getElementById("bt-main-chart");
    const stochEl = document.getElementById("bt-stoch-chart");
    mainEl.innerHTML = "";
    stochEl.innerHTML = "";

    const chartOpts = {
        layout: { background: { color: "#0f1117" }, textColor: "#8b8fa3", fontSize: 11 },
        grid: { vertLines: { color: "#1a1d28" }, horzLines: { color: "#1a1d28" } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: "#2a2d3e" },
        timeScale: { borderColor: "#2a2d3e", timeVisible: false, rightOffset: 15 },
    };

    btMainChart = LightweightCharts.createChart(mainEl, {
        ...chartOpts, width: mainEl.clientWidth, height: mainEl.clientHeight,
    });

    const candles = btMainChart.addCandlestickSeries({
        upColor: "#26a69a", downColor: "#ef5350",
        borderUpColor: "#26a69a", borderDownColor: "#ef5350",
        wickUpColor: "#26a69a", wickDownColor: "#ef5350",
    });
    candles.setData(data.candles);

    const vol = btMainChart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "volume" });
    btMainChart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
    vol.setData(data.volumes);

    // Trade lines
    if (trade.entry_price) {
        candles.createPriceLine({ price: trade.entry_price, color: "#42a5f5", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Solid, axisLabelVisible: true, title: "Entry" });
    }
    if (trade.sl) {
        candles.createPriceLine({ price: trade.sl, color: "#ef5350", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: "SL" });
    }
    if (trade.tp) {
        candles.createPriceLine({ price: trade.tp, color: "#26a69a", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted, axisLabelVisible: true, title: "TP" });
    }

    btMainChart.timeScale().fitContent();

    // Stoch
    btStochChart = LightweightCharts.createChart(stochEl, {
        ...chartOpts, width: stochEl.clientWidth, height: stochEl.clientHeight,
        rightPriceScale: { borderColor: "#2a2d3e", scaleMargins: { top: 0.05, bottom: 0.05 } },
        handleScroll: { mouseWheel: false, pressedMouseMove: false, horzTouchDrag: false, vertTouchDrag: false },
        handleScale: { mouseWheel: false, pinch: false, axisPressedMouseMove: false, axisDoubleClickReset: false },
    });

    const kS = btStochChart.addLineSeries({ color: "#5b7fff", lineWidth: 1.5, title: "K", priceFormat: { type: "custom", formatter: v => v.toFixed(1) } });
    const dS = btStochChart.addLineSeries({ color: "#ff6d00", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, title: "D", priceFormat: { type: "custom", formatter: v => v.toFixed(1) } });

    const sm = {};
    data.stochastic.forEach(s => { if (s.k !== null) sm[s.time] = s; });
    const kD = [], dD = [];
    for (const c of data.candles) { if (sm[c.time]) { kD.push({time:c.time, value:sm[c.time].k}); if(sm[c.time].d!==null) dD.push({time:c.time,value:sm[c.time].d}); }}
    kS.setData(kD); dS.setData(dD);

    const ad = data.candles.map(c => c.time);
    btStochChart.addLineSeries({ color:"rgba(239,83,80,0.4)", lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dashed, crosshairMarkerVisible:false, lastValueVisible:false, priceLineVisible:false }).setData(ad.map(t=>({time:t,value:79})));
    btStochChart.addLineSeries({ color:"rgba(38,166,154,0.4)", lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dashed, crosshairMarkerVisible:false, lastValueVisible:false, priceLineVisible:false }).setData(ad.map(t=>({time:t,value:21})));

    btStochChart.timeScale().fitContent();

    let sp2 = false;
    btMainChart.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (sp2||!range) return; sp2=true;
        requestAnimationFrame(() => { btStochChart.timeScale().setVisibleLogicalRange(range); sp2=false; });
    });

    const ro2 = new ResizeObserver(() => {
        btMainChart.applyOptions({ width: mainEl.clientWidth, height: mainEl.clientHeight });
        btStochChart.applyOptions({ width: stochEl.clientWidth, height: stochEl.clientHeight });
    });
    ro2.observe(mainEl); ro2.observe(stochEl);
} /* end backtest removed */
