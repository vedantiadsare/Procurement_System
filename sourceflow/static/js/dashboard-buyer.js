/* Samagra procurement dashboard - rendering.

   Every number shown here comes from dash-metrics.js, which holds no DOM and
   is unit-tested outside the browser. This file's only job is to turn those
   numbers into charts, tables and chips, and to keep the six views in sync
   with the two filters above them.

   Nothing round-trips to the server: the whole case list arrives once in
   #dashData, so switching view, filtering by month or buyer, drilling into a
   department and exporting are all instant re-slices of the same array.

   Colour is assigned by job: six categorical hues in a fixed order (the same
   set the head's dashboard uses, validated on white), blue for magnitude,
   and green / amber / red reserved for on track / at risk / overdue. */
(function () {
    "use strict";

    var CFG = window.SAMAGRA_DASH || {};
    var M = window.DashMetrics;
    var raw = document.getElementById("dashData");
    var ALL = M.prepare(raw ? JSON.parse(raw.textContent) : [], CFG.today);
    var TODAY = M.parseDate(CFG.today) || new Date();

    var $ = function (id) { return document.getElementById(id); };

    if (!ALL.length) {
        $("nodata").hidden = false;
        $("dashbody").hidden = true;
        $("kpis").hidden = true;
        $("tabs").hidden = true;
        var tools = document.querySelector(".sf-bd .tools");
        if (tools) tools.hidden = true;
        $("msub").textContent = asOf();
        return;
    }

    /* ---------- palette -------------------------------------------------- */

    var C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"];
    var SEQ = ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];
    var ST = { "On track": "#0E9F5A", "At risk": "#C26D00", "Delayed": "#d03b3b", "Clock not started": "#6E8290" };
    var GREY = "#6E8290", INK = "#002733", INK2 = "#4D6670", GRID = "#E6E9EB", SURFACE = "#ffffff";
    var FONT = '"VW Text","Segoe UI",system-ui,Arial,sans-serif';
    var VG = "#008C82", DSB = "#002733";

    Chart.defaults.color = INK2;
    Chart.defaults.font.family = FONT;
    Chart.defaults.font.size = 11;
    Chart.defaults.borderColor = GRID;
    Chart.defaults.plugins.tooltip.backgroundColor = "#ffffff";
    Chart.defaults.plugins.tooltip.titleColor = INK;
    Chart.defaults.plugins.tooltip.bodyColor = INK;
    Chart.defaults.plugins.tooltip.borderColor = "rgba(0,39,51,.16)";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.legend.labels.color = INK;
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;

    /* ---------- formatting ------------------------------------------------ */

    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"]/g, function (ch) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
        });
    }
    function inr(n) {
        var s = Math.round(Number(n) || 0).toString();
        if (s.length <= 3) return s;
        return s.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + s.slice(-3);
    }
    function lakh(n) { return Math.round((Number(n) || 0) / 10000) / 10; }
    var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    function dmy(d) { return d ? (d.getDate() < 10 ? "0" : "") + d.getDate() + " " + MON[d.getMonth()] : "—"; }
    function asOf() { return "As of " + TODAY.getDate() + " " + MON[TODAY.getMonth()] + " " + TODAY.getFullYear(); }
    function first(name) { return String(name || "").split(" ")[0]; }
    function pct(a, b) { return b ? Math.round(a * 100 / b) : 0; }
    function hexA(hex, a) {
        var h = hex.replace("#", "");
        return "rgba(" + parseInt(h.slice(0, 2), 16) + "," + parseInt(h.slice(2, 4), 16) + "," + parseInt(h.slice(4, 6), 16) + "," + a + ")";
    }

    /* ---------- measures ----------------------------------------------- */

    // A PO that can be judged: approved, and it had a committed date.
    function isPO(c) { return c.done && c.status === "Approved" && c.po && c.closed; }
    function bandOf(c) { return c.tat_days === 15 ? "15" : c.tat_days === 30 ? "30" : "other"; }

    /* Closed within TAT, as the head defines it: POs released on or before
       the committed date, divided by every PO released - split by the
       commitment they were measured against. */
    function tatSplit(cases) {
        var out = { all: { n: 0, ok: 0 }, "15": { n: 0, ok: 0 }, "30": { n: 0, ok: 0 }, other: { n: 0, ok: 0 } };
        cases.forEach(function (c) {
            if (!isPO(c)) return;
            var ok = c.closed <= c.po, b = bandOf(c);
            out.all.n++; out[b].n++;
            if (ok) { out.all.ok++; out[b].ok++; }
        });
        Object.keys(out).forEach(function (k) { out[k].pct = out[k].n ? Math.round(out[k].ok * 100 / out[k].n) : null; });
        return out;
    }

    /* ---------- state ---------------------------------------------------- */

    var NOUN = CFG.listNoun || "cases";
    var VIEWS = {
        overview: { title: "Overview", months: true },
        cases: { title: "Open and closed", months: false },
        dept: { title: "Departments", months: true },
        com: { title: "Commodities", months: true },
        buyers: { title: "Buyers", months: true },
        tat: { title: "TAT health", months: true }
    };
    var view = "overview";
    var fMonth = "all";
    var fBuyer = "all";
    // One drill-down per view, so moving between tabs doesn't silently carry
    // a department filter onto a commodity chart.
    var drill = { overview: null, cases: null, dept: null, com: null, buyers: null, tat: null };
    var listScope = "open";   // open | closed | all - applies to the table only
    var PAGE = 10;
    var shown = { overview: PAGE, dept: PAGE, com: PAGE, buyers: PAGE, tat: PAGE };
    var charts = {};

    /* ---------- filters -------------------------------------------------- */

    function scoped() {
        var useMonth = VIEWS[view].months && fMonth !== "all";
        return ALL.filter(function (c) {
            if (fBuyer !== "all" && (c.buyer || "Unassigned") !== fBuyer) return false;
            if (useMonth && c.month !== fMonth) return false;
            return true;
        });
    }

    function matchDrill(c, d) {
        switch (d.key) {
            case "tat": return c.tat === d.value;
            case "dept": return (c.dept || "Not set") === d.value;
            case "comm": return (c.comm || "Not set") === d.value;
            case "buyer": return (c.buyer || "Unassigned") === d.value;
            case "owner": return (c.owner || "Unallocated") === d.value;
            case "others": return d.members.indexOf(c[d.on] || "Not set") !== -1;
            case "open": return c.open;
            case "closed30": return !!c.closed && c.closed > M.addDays(TODAY, -30) && c.closed <= TODAY;
            case "pos": return isPO(c);
            case "band": return isPO(c) && bandOf(c) === d.value;
            case "month": return !!c.closed && M.monthKey(c.closed) === d.value;
            case "cell": return (c[d.field] || (d.field === "buyer" ? "Unassigned" : "Not set")) === d.value && c.tat === d.status;
            default: return true;
        }
    }

    function drilled(cases) {
        var d = drill[view];
        return d ? cases.filter(function (c) { return matchDrill(c, d); }) : cases;
    }

    // Some filters only make sense over closed cases; the list follows.
    var CLOSED_KEYS = { closed30: 1, pos: 1, band: 1, month: 1 };

    function setDrill(key, value, extra) {
        var cur = drill[view];
        var next = Object.assign({ key: key, value: value }, extra || {});
        drill[view] = (cur && JSON.stringify(cur) === JSON.stringify(next)) ? null : next;
        shown[view] = PAGE;
        if (drill[view]) listScope = CLOSED_KEYS[key] ? "all" : "open";
        render();
        if (drill[view]) goToList();
    }

    var LIST_IDS = { overview: "ovList", dept: "dpList", com: "cmList", buyers: "byList", tat: "tList" };
    function goToList() {
        var table = $(LIST_IDS[view]);
        if (!table) return;
        var card = table.closest ? table.closest(".card") : null;
        if (!card || !card.scrollIntoView) return;
        card.scrollIntoView({ behavior: "smooth", block: "start" });
        card.classList.remove("flash");
        void card.offsetWidth;
        card.classList.add("flash");
    }

    /* ---------- controls ------------------------------------------------- */

    (function buildMonthPicker() {
        var counts = {};
        ALL.forEach(function (c) { if (c.month) counts[c.month] = (counts[c.month] || 0) + 1; });
        var keys = Object.keys(counts).sort();
        if (!keys.length) { $("mwrap").hidden = true; return; }

        var thisYear = TODAY.getFullYear();
        var minYear = Math.min(Number(keys[0].slice(0, 4)), thisYear - 1);
        var maxYear = Math.max(Number(keys[keys.length - 1].slice(0, 4)), thisYear);
        var year = thisYear;
        var btn = $("monthBtn"), pop = $("monthPop"), grid = $("mGrid");

        function pad2(n) { return (n < 10 ? "0" : "") + n; }
        function paint() {
            $("mYear").textContent = year;
            $("mPrev").disabled = year <= minYear;
            $("mNext").disabled = year >= maxYear;
            grid.innerHTML = MON.map(function (name, i) {
                var key = year + "-" + pad2(i + 1);
                var n = counts[key] || 0;
                return '<button type="button" class="mpick__m' + (n ? "" : " is-empty") + (fMonth === key ? " on" : "") +
                    '" data-k="' + key + '"' + (n ? "" : " disabled") + ' title="' + esc(name + " " + year + ": " + n + " " + NOUN) + '">' +
                    esc(name) + "<i>" + (n || "") + "</i></button>";
            }).join("");
        }
        function close() { pop.hidden = true; btn.setAttribute("aria-expanded", "false"); }
        function open() { year = fMonth === "all" ? thisYear : Number(fMonth.slice(0, 4)); paint(); pop.hidden = false; btn.setAttribute("aria-expanded", "true"); }
        function choose(key) {
            fMonth = key;
            btn.textContent = key === "all" ? "All months" : M.monthLabel(key);
            btn.classList.toggle("on", key !== "all");
            close(); resetDrills(); render();
        }
        btn.addEventListener("click", function () { pop.hidden ? open() : close(); });
        $("mPrev").addEventListener("click", function () { if (year > minYear) { year--; paint(); } });
        $("mNext").addEventListener("click", function () { if (year < maxYear) { year++; paint(); } });
        $("mAll").addEventListener("click", function () { choose("all"); });
        grid.addEventListener("click", function (e) { var cell = e.target.closest("button[data-k]"); if (cell && !cell.disabled) choose(cell.getAttribute("data-k")); });
        document.addEventListener("click", function (e) { if (!pop.hidden && !pop.contains(e.target) && e.target !== btn) close(); });
        document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !pop.hidden) { close(); btn.focus(); } });
        paint();
    }());

    (function buildControls() {
        var buyers = {};
        ALL.forEach(function (c) { buyers[c.buyer || "Unassigned"] = true; });
        var bsel = $("buyer");
        bsel.innerHTML = '<option value="all">All buyers</option>' +
            Object.keys(buyers).sort().map(function (b) { return '<option value="' + esc(b) + '">' + esc(b) + "</option>"; }).join("");
        bsel.addEventListener("change", function () { fBuyer = bsel.value; resetDrills(); render(); });
    }());

    function resetDrills() { Object.keys(drill).forEach(function (k) { drill[k] = null; shown[k] = PAGE; }); }

    function selectTab(name) {
        Array.prototype.forEach.call($("tabs").querySelectorAll("button"), function (b) {
            var on = b.getAttribute("data-p") === name;
            b.classList.toggle("on", on);
            b.setAttribute("aria-selected", on ? "true" : "false");
        });
        view = name;
    }
    Array.prototype.forEach.call($("tabs").querySelectorAll("button"), function (btn) {
        btn.addEventListener("click", function () {
            if (btn.classList.contains("on")) return;
            selectTab(btn.getAttribute("data-p"));
            location.hash = view;
            render();
        });
    });

    /* ---------- chart plumbing ------------------------------------------- */

    function draw(id, config) {
        var el = $(id);
        if (!el) return null;
        if (charts[id]) { charts[id].destroy(); delete charts[id]; }
        var holder = el.parentNode;
        var old = holder.querySelector(".nodata");
        if (old) holder.removeChild(old);
        var empty = !config.data.datasets.some(function (ds) {
            return ds.data.some(function (v) { return v !== null && v !== undefined && (typeof v === "object" ? true : Number(v) > 0); });
        });
        if (empty) {
            el.style.display = "none";
            var p = document.createElement("div");
            p.className = "nodata";
            p.textContent = config.emptyText || "No cases in this selection";
            holder.appendChild(p);
            return null;
        }
        el.style.display = "";
        charts[id] = new Chart(el.getContext("2d"), config);
        return charts[id];
    }

    // Built from the canvas's own box, which is real by the time a visible
    // view renders; anything unusable falls back to a flat fill.
    function grad(id, hex, a0, a1, horizontal) {
        var el = $(id);
        if (!el) return hexA(hex, a0);
        var box = el.getBoundingClientRect();
        var w = box.width || el.width, h = box.height || el.height;
        if (!w || !h) return hexA(hex, a0);
        try {
            var g = horizontal ? el.getContext("2d").createLinearGradient(0, 0, w, 0) : el.getContext("2d").createLinearGradient(0, 0, 0, h);
            g.addColorStop(0, hexA(hex, a0)); g.addColorStop(1, hexA(hex, a1));
            return g;
        } catch (e) { return hexA(hex, a0); }
    }

    function centreText(big, small) {
        return { id: "centreText", afterDraw: function (chart) {
            var a = chart.getDatasetMeta(0).data[0];
            if (!a) return;
            var ctx = chart.ctx;
            ctx.save(); ctx.textAlign = "center";
            ctx.fillStyle = DSB; ctx.font = "700 26px " + FONT; ctx.fillText(big, a.x, a.y - 2);
            ctx.fillStyle = INK2; ctx.font = "12px " + FONT; ctx.fillText(small, a.x, a.y + 16);
            ctx.restore();
        } };
    }

    function barLabels(fmt, onlyDataset, showZero) {
        return { id: "barLabels", afterDatasetsDraw: function (chart) {
            var ctx = chart.ctx;
            ctx.save(); ctx.font = "600 11px " + FONT; ctx.fillStyle = INK2; ctx.textBaseline = "middle";
            var horizontal = chart.options.indexAxis === "y";
            chart.data.datasets.forEach(function (ds, di) {
                var meta = chart.getDatasetMeta(di);
                if (meta.hidden || (onlyDataset !== undefined && di !== onlyDataset)) return;
                meta.data.forEach(function (bar, i) {
                    var v = ds.data[i];
                    if (v === null || v === undefined || v === "" || (Number(v) === 0 && !showZero)) return;
                    var text = fmt ? fmt(v, i) : String(v);
                    if (horizontal) { ctx.textAlign = "left"; ctx.fillText(text, bar.x + 6, bar.y); }
                    else { ctx.textAlign = "center"; ctx.fillText(text, bar.x, bar.y - 8); }
                });
            });
            ctx.restore();
        } };
    }

    function legendInto(el, entries, onClick) {
        el.innerHTML = entries.map(function (e, i) {
            return '<span data-i="' + i + '"' + (onClick ? ' style="cursor:pointer"' : "") + '><i class="sw" style="background:' + e.color + '"></i>' +
                esc(e.label) + (e.count == null ? "" : " <b>" + e.count + "</b>") + "</span>";
        }).join("");
        if (!onClick) return;
        Array.prototype.forEach.call(el.querySelectorAll("span"), function (span) {
            span.addEventListener("click", function () { onClick(entries[Number(span.getAttribute("data-i"))]); });
        });
    }

    function groupBy(cases, key) { return M.groupBy(cases, key); }

    /* One full-width bar per group, split into its TAT states with the
       count inside each segment - so a department with two cases fills its
       row as fully as one with twenty. Worst first. */
    var STATE_ORDER = ["Delayed", "At risk", "On track", "Clock not started"];
    var STATE_CLASS = { "Delayed": "late", "At risk": "risk", "On track": "ok", "Clock not started": "none" };
    var STATE_TEXT = { "Delayed": "overdue", "At risk": "at risk", "On track": "on track", "Clock not started": "clock not started" };
    function hbarRows(cases, key) {
        return groupBy(cases.filter(M.isOpen), key).map(function (g) {
            var by = {};
            STATE_ORDER.forEach(function (st) { by[st] = 0; });
            g.cases.forEach(function (c) { if (by[c.tat] !== undefined) by[c.tat]++; });
            var clocked = by["Delayed"] + by["At risk"] + by["On track"];
            return { name: g.name, total: g.count, by: by, trouble: by["Delayed"] + by["At risk"],
                     score: clocked ? Math.round(by["On track"] * 100 / clocked) : null };
        }).sort(function (a, b) { return (b.trouble / b.total) - (a.trouble / a.total) || b.trouble - a.trouble || b.total - a.total || a.name.localeCompare(b.name); });
    }
    function hbars(el, rows, key, onPick, onPickCell, active) {
        if (!rows.length) { el.innerHTML = '<div class="nodata nodata--static">No open cases in this selection</div>'; return; }
        if (window.DashExport) window.DashExport.register(el, { type: "stacked", stacked: true, series: STATE_ORDER.length,
            headers: [""].concat(STATE_ORDER.map(function (st) { return st === "Delayed" ? "Overdue" : st; })).concat(["Open", "On track %"]),
            rows: rows.map(function (r) { return [r.name].concat(STATE_ORDER.map(function (st) { return r.by[st]; })).concat([r.total, r.score]); }) });
        el.innerHTML = rows.slice(0, 14).map(function (r, i) {
            var segs = STATE_ORDER.filter(function (st) { return r.by[st]; }).map(function (st) {
                var w = r.by[st] * 100 / r.total;
                var on = active && active.key === "cell" && active.value === r.name && active.status === st;
                return '<button type="button" class="hbar__seg hbar__seg--' + STATE_CLASS[st] + (on ? " on" : "") + '" style="flex-basis:' + w + '%" data-name="' + esc(r.name) + '" data-st="' + st + '" title="' + esc(r.name + ": " + r.by[st] + " " + STATE_TEXT[st]) + '">' + (w >= 9 ? r.by[st] : "") + "</button>";
            }).join("");
            var tone = r.score === null ? "muted" : r.score >= 80 ? "ok" : r.score >= 60 ? "warn" : "bad";
            var rowOn = active && active.key === key && active.value === r.name;
            return '<div class="hbar' + (rowOn ? " on" : "") + '" style="--i:' + i + '">' +
                '<button type="button" class="hbar__label" data-name="' + esc(r.name) + '" title="Show ' + esc(r.name) + "'s cases\">" + esc(r.name) + "<small>" + r.total + " open" + (r.trouble ? " · " + r.trouble + " need attention" : "") + "</small></button>" +
                '<div class="hbar__bar">' + segs + "</div>" +
                '<span class="hbar__score"><span class="pill pill--' + tone + '">' + (r.score === null ? "—" : r.score + "%") + "</span></span></div>";
        }).join("");
        Array.prototype.forEach.call(el.querySelectorAll(".hbar__label"), function (b) {
            b.addEventListener("click", function () { onPick(b.getAttribute("data-name")); });
        });
        Array.prototype.forEach.call(el.querySelectorAll(".hbar__seg"), function (b) {
            b.addEventListener("click", function () { onPickCell(b.getAttribute("data-name"), b.getAttribute("data-st")); });
        });
    }

    /* Scorecard heatmap: groups down the side, the four TAT states across,
       the count in each cell and the cell tinted by how heavy it is within
       its column. Worst first, so the top-left corner is where to look. */
    function heatgrid(el, rows, key, onPick, onPickCell, active) {
        if (!rows.length) { el.innerHTML = '<div class="nodata nodata--static">No open cases in this selection</div>'; return; }
        if (window.DashExport) window.DashExport.register(el, { type: "stacked", stacked: true, series: STATE_ORDER.length,
            headers: [""].concat(STATE_ORDER.map(function (st) { return st === "Delayed" ? "Overdue" : st; })).concat(["Open", "On track %"]),
            rows: rows.map(function (r) { return [r.name].concat(STATE_ORDER.map(function (st) { return r.by[st]; })).concat([r.total, r.score]); }) });
        var colMax = {};
        STATE_ORDER.forEach(function (st) { colMax[st] = Math.max.apply(null, rows.map(function (r) { return r.by[st]; })) || 1; });
        var head = "<thead><tr><th></th>" + STATE_ORDER.map(function (st) { return '<th><i class="sw" style="background:' + ST[st] + '"></i>' + esc(st === "Delayed" ? "Overdue" : st) + "</th>"; }).join("") + '<th class="num">Open</th><th class="num">On track</th></tr></thead>';
        var body = rows.slice(0, 16).map(function (r) {
            var rowOn = active && active.key === key && active.value === r.name;
            var cells = STATE_ORDER.map(function (st) {
                var v = r.by[st], a = v ? 0.16 + 0.72 * v / colMax[st] : 0;
                var on = active && active.key === "cell" && active.value === r.name && active.status === st;
                return '<td class="' + (v ? "" : "z") + (on ? " on" : "") + '" style="' + (v ? "background:" + hexA(ST[st], a) + ";color:" + (a > 0.55 ? "#fff" : INK) : "") + '" data-name="' + esc(r.name) + '" data-st="' + st + '" title="' + esc(r.name + ": " + v + " " + STATE_TEXT[st]) + '">' + (v || "·") + "</td>";
            }).join("");
            var tone = r.score === null ? "muted" : r.score >= 80 ? "ok" : r.score >= 60 ? "warn" : "bad";
            return '<tr class="' + (rowOn ? "on" : "") + '"><th><button type="button" data-name="' + esc(r.name) + '" title="Show ' + esc(r.name) + "'s cases\">" + esc(r.name) + "</button></th>" + cells +
                '<td class="num total">' + r.total + '</td><td class="num"><span class="pill pill--' + tone + '">' + (r.score === null ? "—" : r.score + "%") + "</span></td></tr>";
        }).join("");
        el.innerHTML = "<table>" + head + "<tbody>" + body + "</tbody></table>";
        Array.prototype.forEach.call(el.querySelectorAll("th button"), function (b) {
            b.addEventListener("click", function () { onPick(b.getAttribute("data-name")); });
        });
        Array.prototype.forEach.call(el.querySelectorAll("td[data-st]"), function (td) {
            td.addEventListener("click", function () { if (!td.classList.contains("z")) onPickCell(td.getAttribute("data-name"), td.getAttribute("data-st")); });
        });
    }

    /* Packed bubbles: one circle per category with open cases, area by open
       value, colour by the worst TAT state inside. Placed largest-first on
       an outward spiral until nothing overlaps, then scaled to the box - a
       cluster, not a grid, so ninety-six categories never look like a list
       and the fifteen that are live are the whole picture. */
    function packCircles(items) {
        items.sort(function (a, b) { return b.r - a.r; });
        var placed = [];
        items.forEach(function (it) {
            if (!placed.length) { it.x = 0; it.y = 0; placed.push(it); return; }
            var angle = 0, radius = 0, x = 0, y = 0;
            while (radius < 4000) {
                x = Math.cos(angle) * radius; y = Math.sin(angle) * radius;
                var ok = true;
                for (var i = 0; i < placed.length; i++) { var q = placed[i]; if (Math.hypot(q.x - x, q.y - y) < q.r + it.r + 3) { ok = false; break; } }
                if (ok) break;
                angle += 0.28; radius += 0.7;
            }
            it.x = x; it.y = y; placed.push(it);
        });
        return placed;
    }

    function bubbles(el, legendEl, groups, onPick, active) {
        if (!groups.length) { el.innerHTML = '<div class="nodata nodata--static">No open cases in this selection</div>'; legendEl.innerHTML = ""; return; }
        var anyValue = groups.some(function (g) { return g.value > 0; });
        var items = groups.map(function (g) {
            var late = g.cases.filter(function (c) { return c.tat === "Delayed"; }).length;
            var risk = g.cases.filter(function (c) { return c.tat === "At risk"; }).length;
            return { name: g.name, count: g.count, value: g.value, late: late, risk: risk, raw: Math.sqrt(anyValue ? Math.max(g.value, 40000) : g.count) };
        });
        var maxRaw = Math.max.apply(null, items.map(function (i) { return i.raw; })) || 1;
        items.forEach(function (i) { i.r = 18 + 46 * i.raw / maxRaw; });
        if (window.DashExport) window.DashExport.register(el, { type: "bar",
            headers: ["Commodity", "Open cases", "Open value (INR)", "Overdue", "At risk"],
            rows: items.slice().sort(function (a, b) { return b.value - a.value || b.count - a.count; }).map(function (i) { return [i.name, i.count, i.value, i.late, i.risk]; }) });
        packCircles(items);
        var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        items.forEach(function (i) { minX = Math.min(minX, i.x - i.r); maxX = Math.max(maxX, i.x + i.r); minY = Math.min(minY, i.y - i.r); maxY = Math.max(maxY, i.y + i.r); });
        var W = 640, H = 300, pad = 6;
        var scale = Math.min((W - pad * 2) / (maxX - minX), (H - pad * 2) / (maxY - minY), 1.6);
        var ox = (W - (maxX - minX) * scale) / 2 - minX * scale, oy = (H - (maxY - minY) * scale) / 2 - minY * scale;
        el.innerHTML = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Commodities with open cases">' + items.map(function (i) {
            var cx = ox + i.x * scale, cy = oy + i.y * scale, r = i.r * scale;
            var cls = i.late ? "late" : i.risk ? "risk" : "ok";
            var short = i.name.length > Math.max(6, Math.floor(r / 3.6)) ? i.name.slice(0, Math.max(5, Math.floor(r / 3.6)) - 1) + "…" : i.name;
            var tip = i.name + ": " + i.count + " open case" + (i.count === 1 ? "" : "s") + " · ₹" + lakh(i.value).toLocaleString("en-IN") + " lakh" + (i.late ? " · " + i.late + " overdue" : "") + (i.risk ? " · " + i.risk + " at risk" : "");
            return '<g class="bub bub--' + cls + (active === i.name ? " on" : "") + '" data-name="' + esc(i.name) + '"><title>' + esc(tip) + "</title>" +
                '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + r.toFixed(1) + '"/>' +
                (r >= 26 ? '<text x="' + cx.toFixed(1) + '" y="' + (cy - (r >= 38 ? 4 : 0)).toFixed(1) + '" class="bub__name">' + esc(short) + "</text>" : "") +
                (r >= 38 ? '<text x="' + cx.toFixed(1) + '" y="' + (cy + 12).toFixed(1) + '" class="bub__sub">' + i.count + (i.count === 1 ? " case" : " cases") + "</text>" : "") + "</g>";
        }).join("") + "</svg>";
        Array.prototype.forEach.call(el.querySelectorAll(".bub"), function (g) {
            g.addEventListener("click", function () { onPick(g.getAttribute("data-name")); });
        });
        legendInto(legendEl, [{ label: "Has an overdue case", color: ST.Delayed }, { label: "Has a case at risk", color: ST["At risk"] }, { label: "On track or not started", color: C[0] }]);
    }

    function polar(id, groups, key, byValue) {
        var g = groups.slice().sort(function (a, b) { return byValue ? b.value - a.value : b.count - a.count; });
        var top = g.slice(0, 6), rest = g.slice(6);
        var labels = top.map(function (x) { return x.name; });
        var data = top.map(function (x) { return byValue ? lakh(x.value) : x.count; });
        var colors = top.map(function (_, i) { return hexA(C[i], .78); });
        var members = rest.map(function (x) { return x.name; });
        if (rest.length) {
            labels.push("Others");
            data.push(byValue ? lakh(rest.reduce(function (s, x) { return s + x.value; }, 0)) : rest.reduce(function (s, x) { return s + x.count; }, 0));
            colors.push(hexA(GREY, .6));
        }
        draw(id, {
            type: "polarArea",
            data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderColor: SURFACE, borderWidth: 2 }] },
            options: { responsive: true, maintainAspectRatio: false,
                       plugins: { legend: { position: "right", labels: { pointStyle: "rectRounded", padding: 8, font: { size: 11 } } },
                                  tooltip: { callbacks: { label: function (ctx) { return byValue ? " ₹" + ctx.parsed.r.toLocaleString("en-IN") + " lakh" : " " + ctx.parsed.r + " open"; } } } },
                       scales: { r: { grid: { color: GRID }, angleLines: { color: GRID }, ticks: { display: false }, beginAtZero: true } },
                       onClick: function (evt, els) {
                           if (!els.length) return;
                           var name = labels[els[0].index];
                           if (name === "Others") setDrill("others", "Others", { on: key, members: members, label: "Others" });
                           else setDrill(key, name, { label: name });
                       } },
            emptyText: "No open cases in this selection"
        });
    }

    /* ---------- KPI strip: every tile is a filter ------------------------- */

    /* An eight-week shape behind a tile's number - a gesture, not a chart;
       the real chart is one tab away. */
    function spark(vals, color) {
        var known = vals.filter(function (v) { return v !== null; });
        if (known.length < 2) return "";
        var max = Math.max.apply(null, known) || 1, w = 84, h = 24, step = w / (vals.length - 1);
        var pts = vals.map(function (v, i) { return [Math.round(i * step), Math.round(h - 3 - v / max * (h - 6))]; });
        var d = pts.map(function (pt, i) { return (i ? "L" : "M") + pt[0] + " " + pt[1]; }).join(" ");
        var last = pts[pts.length - 1];
        return '<svg class="spark" viewBox="0 0 ' + w + " " + h + '" aria-hidden="true"><path d="' + d + " L" + w + " " + h + " L0 " + h + ' Z" fill="' + color + '" fill-opacity=".12"/>' +
            '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="' + last[0] + '" cy="' + last[1] + '" r="2.6" fill="' + color + '"/></svg>';
    }

    function countUp(el) {
        var raw = el.getAttribute("data-n");
        if (raw === null || raw === "" || isNaN(Number(raw))) return;
        var target = Number(raw), suffix = el.getAttribute("data-suffix") || "", start = null;
        if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) { el.textContent = target + suffix; return; }
        function tick(ts) {
            if (!start) start = ts;
            var p = Math.min(1, (ts - start) / 600);
            el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))) + suffix;
            if (p < 1) requestAnimationFrame(tick);
        }
        requestAnimationFrame(tick);
    }

    function renderKpis(cases) {
        var k = M.kpis(cases, CFG.today);
        var split = tatSplit(cases);
        var openValue = "₹" + lakh(k.openValueInr).toLocaleString("en-IN") + " lakh open value" + (k.openValueUnconverted ? " · " + k.openValueUnconverted + " not converted" : "");
        var weeks = M.byWeek(cases, CFG.today, 8);
        var tiles = [
            { t: "Open cases", v: k.open, s: openValue, acc: DSB, sp: spark(weeks.map(function (w) { return w.incoming; }), DSB), go: function () { setDrill("open", true, { label: "Open cases" }); } },
            { t: "Closed", v: k.closedRecent, s: "last 30 days", acc: VG, sp: spark(weeks.map(function (w) { return w.closed; }), VG), go: function () { setDrill("closed30", true, { label: "Closed in the last 30 days" }); } },
            { t: "On track", v: k.onTrack, s: "open cases", acc: ST["On track"], go: function () { setDrill("tat", "On track", { label: "On track" }); } },
            { t: "At risk", v: k.atRisk, s: "due within 5 working days", acc: ST["At risk"], go: function () { setDrill("tat", "At risk", { label: "At risk" }); } },
            { t: "Delayed", v: k.delayed, s: "past PO due date", acc: ST.Delayed, go: function () { setDrill("tat", "Delayed", { label: "Overdue" }); } },
            { t: "Closed within TAT", v: split.all.pct === null ? "—" : split.all.pct, suffix: split.all.pct === null ? "" : "%",
              s: split.all.n ? split.all.ok + " of " + split.all.n + " POs" + (split["15"].n ? " · 15-day " + split["15"].pct + "%" : "") + (split["30"].n ? " · 30-day " + split["30"].pct + "%" : "") : "no PO released yet",
              acc: VG, go: function () { setDrill("pos", true, { label: "POs released against a committed date" }); } }
        ];
        var active = drill[view] ? (drill[view].label || "") : "";
        $("kpis").innerHTML = tiles.map(function (x, i) {
            var num = typeof x.v === "number";
            var on = active && (x.t === "Open cases" && active === "Open cases" || x.t === "Closed" && active.indexOf("Closed in") === 0 || x.t === "On track" && active === "On track" ||
                                 x.t === "At risk" && active === "At risk" || x.t === "Delayed" && active === "Overdue" || x.t === "Closed within TAT" && active.indexOf("POs released") === 0);
            return '<div class="kpi kpi--go' + (on ? " on" : "") + '" style="--acc:' + x.acc + ';--i:' + i + '" data-i="' + i + '" role="button" tabindex="0" title="Show these cases">' +
                "<span>" + esc(x.t) + "</span>" +
                '<strong data-n="' + (num ? x.v : "") + '" data-suffix="' + esc(x.suffix || "") + '">' + esc(String(x.v)) + esc(x.suffix || "") + "</strong>" +
                "<small>" + esc(x.s) + "</small>" + (x.sp || "") + "</div>";
        }).join("");
        Array.prototype.forEach.call($("kpis").querySelectorAll("strong[data-n]"), countUp);
        Array.prototype.forEach.call($("kpis").querySelectorAll(".kpi--go"), function (el) {
            el.addEventListener("click", function () { tiles[Number(el.getAttribute("data-i"))].go(); });
            el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); tiles[Number(el.getAttribute("data-i"))].go(); } });
        });
        return k;
    }

    /* ---------- drill-down table ----------------------------------------- */

    var COLS = ["SC number", "Topic", "Department", "Commodity", "Buyer", "Value (₹)", "PO due", "With", "Status"];

    function statusCell(c) {
        if (c.done) {
            if (c.status !== "Approved") return '<span class="st"><i style="background:' + INK2 + '"></i>Not approved</span>';
            if (isPO(c)) {
                var late = c.closed > c.po;
                return '<span class="st"><i style="background:' + (late ? ST.Delayed : ST["On track"]) + '"></i>PO released · ' + (late ? "late" : "on time") + "</span>";
            }
            return '<span class="st"><i style="background:' + VG + '"></i>PO released</span>';
        }
        if (c.tat === "Delayed") return '<span class="st late"><i style="background:' + ST.Delayed + '"></i>' + Math.abs(c.daysLeft) + " days late</span>";
        if (c.tat === "At risk") return '<span class="st"><i style="background:' + ST["At risk"] + '"></i>due in ' + c.daysLeft + " day" + (c.daysLeft === 1 ? "" : "s") + "</span>";
        if (c.tat === "On track") return '<span class="st"><i style="background:' + ST["On track"] + '"></i>' + c.daysLeft + " days left</span>";
        return '<span class="st muted"><i style="background:' + GREY + '"></i>clock not started</span>';
    }

    function scopedForList(cases) {
        if (listScope === "closed") return cases.filter(M.isClosed);
        if (listScope === "all") return cases;
        return cases.filter(M.isOpen);
    }
    var SCOPES = [["open", "Open"], ["closed", "Closed"], ["all", "All"]];

    function renderTable(tableId, headId, chipsId, moreId, cases, label) {
        var d = drill[view];
        var rows = cases.slice();
        if (listScope === "closed" || (d && CLOSED_KEYS[d.key])) rows.sort(function (a, b) { return (b.closed || 0) - (a.closed || 0); });
        else rows.sort(M.urgencyOrder);

        var head = $(headId);
        head.innerHTML = esc(label) + ' <span class="count">(' + rows.length + ")</span>" +
            '<span class="scope">' + SCOPES.map(function (s) {
                return '<button type="button" data-scope="' + s[0] + '"' + (listScope === s[0] ? ' class="on"' : "") + ">" + s[1] + "</button>";
            }).join("") + "</span>";
        Array.prototype.forEach.call(head.querySelectorAll("[data-scope]"), function (btn) {
            btn.addEventListener("click", function () { listScope = btn.getAttribute("data-scope"); shown[view] = PAGE; render(); });
        });

        var chips = $(chipsId);
        if (d) {
            chips.innerHTML = '<span class="chip">' + esc(d.label || d.value) + '<button type="button" aria-label="Clear filter">×</button></span>';
            chips.querySelector("button").addEventListener("click", function () { drill[view] = null; render(); });
        } else chips.innerHTML = "";

        var limit = shown[view];
        var page = rows.slice(0, limit);
        var thead = "<thead><tr>" + COLS.map(function (h, i) { return "<th" + (i === 5 ? ' class="num"' : "") + ">" + h + "</th>"; }).join("") + "</tr></thead>";
        var body = page.map(function (c) {
            var href = CFG.caseUrlBase + c.case_id;
            var native = (c.ccy && c.ccy !== "INR") ? ' title="' + esc(c.ccy + " " + Math.round(c.value).toLocaleString("en-US")) + '"' : "";
            return '<tr data-href="' + href + '" tabindex="0">' +
                '<td class="sc"><a href="' + href + '">' + esc(c.sc || c.id) + "</a>" + (c.sc && c.id && c.sc !== c.id ? '<small class="muted">' + esc(c.id) + "</small>" : "") + "</td>" +
                '<td class="topic">' + esc(c.topic) + "</td><td>" + esc(c.dept) + "</td><td>" + esc(c.comm) + "</td><td>" + esc(c.buyer || "—") + "</td>" +
                '<td class="num"' + native + ">" + inr(c.value_inr) + "</td><td>" + dmy(c.po) + "</td>" +
                '<td class="muted">' + esc(c.with) + "</td><td>" + statusCell(c) + "</td></tr>";
        }).join("");
        $(tableId).innerHTML = rows.length ? thead + "<tbody>" + body + "</tbody>"
            : thead + '<tbody><tr><td colspan="9" class="muted" style="padding:20px;text-align:center">No cases match this selection</td></tr></tbody>';

        var more = $(moreId);
        if (rows.length > limit) { more.hidden = false; more.textContent = "Show all " + rows.length + " cases"; more.onclick = function () { shown[view] = rows.length; render(); }; }
        else if (limit > PAGE && rows.length > PAGE) { more.hidden = false; more.textContent = "Show top " + PAGE; more.onclick = function () { shown[view] = PAGE; render(); }; }
        else more.hidden = true;
    }

    function listLabel() {
        var d = drill[view];
        if (d && CLOSED_KEYS[d.key]) return "Closed " + NOUN;
        return listScope === "closed" ? "Closed " + NOUN : (listScope === "all" ? "All " + NOUN : "Open " + NOUN);
    }

    /* ---------- shared charts ------------------------------------------- */

    function tatEntries(cases) {
        var open = cases.filter(M.isOpen);
        return M.TAT_STATES.map(function (s) { return { label: s, color: ST[s], count: open.filter(function (c) { return c.tat === s; }).length }; });
    }

    function drawTatDonut(canvasId, legendId, cases) {
        var entries = tatEntries(cases), open = cases.filter(M.isOpen).length;
        draw(canvasId, {
            type: "doughnut",
            data: { labels: entries.map(function (e) { return e.label; }),
                    datasets: [{ data: entries.map(function (e) { return e.count; }), backgroundColor: entries.map(function (e) { return e.color; }),
                                 borderColor: SURFACE, borderWidth: 3, borderRadius: 4, hoverOffset: 9 }] },
            options: { responsive: true, maintainAspectRatio: false, cutout: "68%", plugins: { legend: { display: false } },
                       onClick: function (evt, els) { if (els.length) { var s = entries[els[0].index]; setDrill("tat", s.label, { label: s.label }); } } },
            plugins: [centreText(String(open), "open cases")],
            emptyText: "No open cases in this selection"
        });
        legendInto($(legendId), entries, function (e) { setDrill("tat", e.label, { label: e.label }); });
    }

    // Raised vs closed - two counts on one axis, drawn as soft gradient areas.
    function drawWeekArea(canvasId, cases, weeks) {
        var series = M.byWeek(cases, CFG.today, weeks);
        var cl = C[0], cc = C[4];
        draw(canvasId, {
            type: "line",
            data: { labels: series.map(function (w) { return dmy(w.start); }),
                    datasets: [
                        { label: "Raised", data: series.map(function (w) { return w.incoming; }), borderColor: cl, backgroundColor: grad(canvasId, cl, .38, .03),
                          fill: true, tension: .42, borderWidth: 2.5, pointRadius: 3.5, pointHoverRadius: 6, pointBackgroundColor: cl, pointBorderColor: SURFACE, pointBorderWidth: 2 },
                        { label: "Closed", data: series.map(function (w) { return w.closed; }), borderColor: cc, backgroundColor: grad(canvasId, cc, .34, .03),
                          fill: true, tension: .42, borderWidth: 2.5, pointRadius: 3.5, pointHoverRadius: 6, pointBackgroundColor: cc, pointBorderColor: SURFACE, pointBorderWidth: 2, pointStyle: "rectRot" }
                    ] },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
                       plugins: { legend: { position: "top", align: "end" } },
                       scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } }, x: { grid: { display: false } } } },
            emptyText: "No cases raised or closed in this window"
        });
        return series;
    }

    /* ---------- views ---------------------------------------------------- */

    function renderOverview(cases) {
        drawTatDonut("ovTat", "ovTatLg", cases);

        var series = drawWeekArea("ovLine", cases, 8);
        var inN = 0, outN = 0;
        series.slice(-4).forEach(function (w) { inN += w.incoming; outN += w.closed; });
        $("ovNet").textContent = inN === outN ? "Last 4 weeks: in and out balanced" : "Last 4 weeks: " + Math.abs(inN - outN) + " more " + (inN > outN ? "in than closed" : "closed than in");

        polar("ovDept", groupBy(cases.filter(M.isOpen), "dept"), "dept", false);

        var comm = groupBy(cases.filter(M.isOpen), "comm").slice(0, 8);
        var labels = comm.map(function (g) { return g.name; });
        draw("ovCom", {
            type: "bar",
            data: { labels: labels, datasets: [{ label: "Open cases", data: comm.map(function (g) { return g.count; }),
                    backgroundColor: labels.map(function (_, i) { return grad("ovCom", C[i % C.length], 1, .55, true); }), borderRadius: 5, barThickness: 18 }] },
            options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, layout: { padding: { right: 36 } }, plugins: { legend: { display: false } },
                       scales: { x: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } }, y: { ticks: { color: INK }, grid: { display: false } } },
                       onClick: function (evt, els) { if (els.length) setDrill("comm", labels[els[0].index], { label: labels[els[0].index] }); } },
            plugins: [barLabels(null)],
            emptyText: "No open cases in this selection"
        });
        $("ovTop").textContent = comm.length ? "Highest: " + comm[0].name + " (" + comm[0].count + ")" : "";

        renderTable("ovList", "ovH", "ovChips", "ovMore", scopedForList(drilled(cases)), listLabel());
    }

    function renderCases(cases) {
        drawWeekArea("csLine", cases, 12);

        var months = M.byMonth(cases, CFG.today, 6);
        var partial = months.filter(function (m) { return m.partial; })[0];
        $("csMonthSub").textContent = partial ? first(partial.label) + " is up to today" : "";

        // The open count as a line over the raised / closed bars.
        draw("csMonth", {
            type: "bar",
            data: { labels: months.map(function (m) { return first(m.label); }), datasets: [
                { type: "line", label: "Open at month end", data: months.map(function (m) { return m.openAtEnd; }), borderColor: C[5], backgroundColor: grad("csMonth", C[5], .26, .02),
                  fill: true, tension: .4, borderWidth: 2.5, pointRadius: 4, pointBackgroundColor: C[5], pointBorderColor: SURFACE, pointBorderWidth: 2, order: 0 },
                { label: "Raised", data: months.map(function (m) { return m.incoming; }), backgroundColor: grad("csMonth", C[0], .9, .45), borderRadius: 5, maxBarThickness: 26, order: 1 },
                { label: "Closed", data: months.map(function (m) { return m.closed; }), backgroundColor: grad("csMonth", C[4], .9, .45), borderRadius: 5, maxBarThickness: 26, order: 1 }
            ] },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { position: "top", align: "end" } },
                       scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } }, x: { grid: { display: false }, ticks: { color: INK } } } },
            emptyText: "Not enough history yet"
        });

        $("csTable").innerHTML =
            '<thead><tr><th>Month</th><th class="num">Open at start</th><th class="num">Raised</th><th class="num">Closed</th><th class="num">Open at end</th><th class="num">Within TAT</th></tr></thead><tbody>'
            + months.map(function (m, i) {
                var start = i ? months[i - 1].openAtEnd : Math.max(m.openAtEnd - m.incoming + m.closed, 0);
                var tone = m.withinTat === null ? "muted" : (m.withinTat >= 80 ? "ok" : (m.withinTat >= 60 ? "warn" : "bad"));
                return '<tr><td class="month"><b>' + esc(first(m.label)) + "</b>" + (m.partial ? ' <span class="muted">to date</span>' : "") + "</td>"
                    + '<td class="num muted">' + start + '</td><td class="num">' + m.incoming + '</td><td class="num">' + m.closed + '</td><td class="num"><b>' + m.openAtEnd + "</b></td>"
                    + '<td class="num"><span class="pill pill--' + tone + '">' + (m.withinTat === null ? "no closures" : m.withinTat + "%") + "</span></td></tr>";
            }).join("") + "</tbody>";
    }

    function renderDept(cases) {
        polar("dpPie", groupBy(cases.filter(M.isOpen), "dept"), "dept", false);
        heatgrid($("dpBars"), hbarRows(cases, "dept"), "dept",
                 function (name) { setDrill("dept", name, { label: name }); },
                 function (name, st) { setDrill("cell", name, { field: "dept", status: st, label: name + " · " + STATE_TEXT[st] }); },
                 drill.dept);
        $("dpLg").innerHTML = "";
        renderTable("dpList", "dpH", "dpChips", "dpMore", scopedForList(drilled(cases)), listLabel());
    }

    function renderCom(cases) {
        var groups = groupBy(cases.filter(M.isOpen), "comm");
        bubbles($("cmBub"), $("cmBubLg"), groups, function (name) { setDrill("comm", name, { label: name }); }, drill.com && drill.com.key === "comm" ? drill.com.value : null);
        var activeN = groups.length, totalN = CFG.commodityCount || 0;
        $("comTop").textContent = (totalN ? activeN + " of " + totalN + " categories have open cases. " : "") + "Size is open value, colour is the worst TAT state in it. Click a bubble for its cases.";

        var byValue = groups.slice().sort(function (a, b) { return b.value - a.value; }).slice(0, 8);
        var labels = byValue.map(function (g) { return g.name; });
        draw("cmVal", {
            type: "bar",
            data: { labels: labels, datasets: [{ label: "Open value (₹ lakh)", data: byValue.map(function (g) { return lakh(g.value); }),
                    backgroundColor: labels.map(function (_, i) { return grad("cmVal", SEQ[Math.min(4, 4 - Math.floor(i / 2))], 1, .55, true); }), borderRadius: 5, barThickness: 18 }] },
            options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, layout: { padding: { right: 52 } }, plugins: { legend: { display: false } },
                       scales: { x: { beginAtZero: true, ticks: { precision: 1 }, grid: { color: GRID } }, y: { ticks: { color: INK }, grid: { display: false } } },
                       onClick: function (evt, els) { if (els.length) setDrill("comm", labels[els[0].index], { label: labels[els[0].index] }); } },
            plugins: [barLabels(function (v) { return "₹" + v + "L"; })],
            emptyText: "No open value in this selection"
        });
        var unconverted = cases.filter(M.isOpen).filter(function (c) { return !Number(c.value_inr); }).length;
        $("cmValNote").textContent = unconverted ? unconverted + " open case" + (unconverted === 1 ? " has" : "s have") + " no rupee value on file and are not included in these totals." : "";

        renderTable("cmList", "cmH", "cmChips", "cmMore", scopedForList(drilled(cases)), listLabel());
    }

    function buyerStats(cases) {
        var thirty = M.addDays(TODAY, -30), twelve = M.addDays(TODAY, -84), map = {};
        cases.forEach(function (c) {
            var n = c.buyer || "Unassigned";
            if (!map[n]) map[n] = { name: n, open: 0, closed30: 0, late: 0, judged: 0, onTime: 0, ages: [] };
            var p = map[n];
            if (M.isOpen(c)) { p.open++; if (c.tat === "Delayed") p.late++; if (c.sub) p.ages.push(Math.max(0, Math.round((TODAY - c.sub) / 864e5))); }
            if (c.closed && c.closed > thirty && c.closed <= TODAY) p.closed30++;
            if (c.closed && c.po && c.closed > twelve && c.closed <= TODAY) { p.judged++; if (c.closed <= c.po) p.onTime++; }
        });
        return Object.keys(map).map(function (k) {
            var p = map[k];
            p.avgAge = p.ages.length ? p.ages.reduce(function (s, a) { return s + a; }, 0) / p.ages.length : 0;
            p.onTimePct = p.judged ? Math.round(p.onTime * 100 / p.judged) : null;
            return p;
        }).sort(function (a, b) { return b.open - a.open || a.name.localeCompare(b.name); });
    }

    function renderBuyers(cases) {
        var rows = buyerStats(cases);
        var labels = rows.map(function (r) { return r.name; });
        draw("byBar", {
            type: "bar",
            data: { labels: labels, datasets: [
                { label: "Open", data: rows.map(function (r) { return r.open; }), backgroundColor: grad("byBar", C[0], .95, .5), borderRadius: 5, maxBarThickness: 34 },
                { label: "Closed (30 days)", data: rows.map(function (r) { return r.closed30; }), backgroundColor: grad("byBar", C[4], .95, .5), borderRadius: 5, maxBarThickness: 34 }
            ] },
            options: { responsive: true, maintainAspectRatio: false, layout: { padding: { top: 14 } }, plugins: { legend: { position: "top", align: "end" } },
                       scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } }, x: { grid: { display: false }, ticks: { color: INK } } },
                       onClick: function (evt, els) { if (els.length) setDrill("buyer", labels[els[0].index], { label: labels[els[0].index] }); } },
            plugins: [barLabels(null)],
            emptyText: "No cases in this selection"
        });

        // Profile: the three busiest, five measures each scaled to the
        // largest value on that measure across everyone.
        var top3 = rows.filter(function (r) { return r.name !== "Unassigned"; }).slice(0, 3);
        var axes = [["Open load", "open"], ["Closed 30d", "closed30"], ["On time %", "onTimePct"], ["Overdue", "late"], ["Avg age", "avgAge"]];
        var maxes = {};
        axes.forEach(function (a) { maxes[a[1]] = Math.max.apply(null, rows.map(function (r) { return Number(r[a[1]] || 0); })) || 1; });
        draw("byRadar", {
            type: "radar",
            data: { labels: axes.map(function (a) { return a[0]; }),
                    datasets: top3.map(function (r, i) {
                        return { label: r.name, data: axes.map(function (a) { return Math.round(Number(r[a[1]] || 0) * 100 / maxes[a[1]]); }),
                                 borderColor: C[i], backgroundColor: hexA(C[i], .18), pointBackgroundColor: C[i], pointBorderColor: SURFACE, pointRadius: 4, borderWidth: 2 };
                    }) },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false },
                       tooltip: { callbacks: { label: function (ctx) { var r = top3[ctx.datasetIndex], a = axes[ctx.dataIndex][1], v = r[a]; return " " + ctx.dataset.label + ": " + (a === "onTimePct" ? (v === null ? "—" : v + "%") : a === "avgAge" ? v.toFixed(1) + " days" : v); } } } },
                       scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: GRID }, angleLines: { color: GRID }, pointLabels: { color: INK, font: { size: 11 } } } } },
            emptyText: "Nobody to profile in this selection"
        });
        $("byRadarSub").textContent = top3.length ? "The " + (top3.length === 1 ? "busiest buyer" : top3.length + " busiest buyers") + ", each measure scaled to the largest among them" : "";
        legendInto($("byRadarLg"), top3.map(function (r, i) { return { label: r.name, color: C[i] }; }));

        hbars($("byBars"), hbarRows(cases, "buyer"), "buyer",
              function (name) { setDrill("buyer", name, { label: name }); },
              function (name, st) { setDrill("cell", name, { field: "buyer", status: st, label: name + " · " + STATE_TEXT[st] }); },
              drill.buyers);
        legendInto($("byLg"), M.TAT_STATES.map(function (s) { return { label: s, color: ST[s] }; }));
        renderTable("byList", "byH", "byChips", "byMore", scopedForList(drilled(cases)), listLabel());
    }

    function renderTat(cases) {
        drawTatDonut("tTat", "tTatLg", cases);

        // The headline ratio, overall and per commitment, as gauges - each
        // one a filter on the list of POs it counts.
        var split = tatSplit(cases);
        var gauges = [
            { id: "tG0", t: "All POs", d: split.all, s: "Every PO released against a committed date", band: null },
            { id: "tG1", t: "15 working days", d: split["15"], s: "Topics up to ₹3.5 lakh", band: "15" },
            { id: "tG2", t: "30 working days", d: split["30"], s: "Topics up to ₹40 lakh", band: "30" }
        ];
        if (split.other.n) gauges.push({ id: "tG3", t: "Other commitments", d: split.other, s: "Buyer-set TAT outside the two bands", band: "other" });
        $("tGauges").innerHTML = gauges.map(function (g, i) {
            var on = drill.tat && ((g.band === null && drill.tat.key === "pos") || (g.band !== null && drill.tat.key === "band" && drill.tat.value === g.band));
            return '<button type="button" class="gauge' + (on ? " on" : "") + '" data-i="' + i + '"><div class="gauge__cv"><canvas id="' + g.id + '"></canvas></div>' +
                "<b>" + esc(g.t) + "</b><span>" + (g.d.n ? g.d.ok + " of " + g.d.n + " PO" + (g.d.n === 1 ? "" : "s") + " on time" : "No POs yet") + "</span><small>" + esc(g.s) + "</small></button>";
        }).join("");
        gauges.forEach(function (g) {
            var p = g.d.pct, colour = p === null ? GREY : p >= 80 ? ST["On track"] : p >= 60 ? ST["At risk"] : ST.Delayed;
            var text = { id: "gaugeText", afterDraw: function (chart) {
                var a = chart.chartArea, ctx = chart.ctx;
                ctx.save(); ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
                ctx.fillStyle = DSB; ctx.font = "700 24px " + FONT; ctx.fillText(p === null ? "—" : p + "%", (a.left + a.right) / 2, a.bottom - 4);
                ctx.restore();
            } };
            draw(g.id, {
                type: "doughnut",
                data: { datasets: [{ data: [p === null ? 0 : p, p === null ? 100 : 100 - p], backgroundColor: [grad(g.id, colour, 1, .55, true), "rgba(0,39,51,.07)"], borderWidth: 0, borderRadius: 8 }] },
                options: { responsive: true, maintainAspectRatio: false, circumference: 180, rotation: 270, cutout: "70%", plugins: { legend: { display: false }, tooltip: { enabled: false } }, events: [] },
                plugins: [text]
            });
        });
        Array.prototype.forEach.call($("tGauges").querySelectorAll(".gauge"), function (el) {
            el.addEventListener("click", function () {
                var g = gauges[Number(el.getAttribute("data-i"))];
                if (g.band === null) setDrill("pos", true, { label: "POs released against a committed date" });
                else setDrill("band", g.band, { label: (g.band === "other" ? "Other" : g.band + "-day") + " TAT POs" });
            });
        });
        $("tGaugeNote").textContent = split.all.n ? "Target 80%" : "";

        // Month by month: each month is a column to 100%, filled to that
        // month's share and coloured by band, with the count it rests on.
        var months = M.byMonth(cases, CFG.today, 6);
        var judged = months.map(function (m) { return cases.filter(function (c) { return c.closed && c.po && M.monthKey(c.closed) === m.key; }).length; });
        function band(p) { return p === null ? GREY : p >= 80 ? ST["On track"] : p >= 60 ? ST["At risk"] : ST.Delayed; }
        var target = { id: "target", afterDatasetsDraw: function (chart) {
            var y = chart.scales.y.getPixelForValue(80), a = chart.chartArea, ctx = chart.ctx;
            ctx.save(); ctx.strokeStyle = hexA(INK, .45); ctx.setLineDash([5, 5]); ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(a.left, y); ctx.lineTo(a.right, y); ctx.stroke();
            ctx.setLineDash([]); ctx.fillStyle = INK2; ctx.font = "600 10.5px " + FONT; ctx.textAlign = "right"; ctx.fillText("target 80%", a.right - 4, y - 5);
            ctx.restore();
        } };
        draw("tTrend", {
            type: "bar",
            data: { labels: months.map(function (m, i) { return [first(m.label), judged[i] ? judged[i] + (judged[i] === 1 ? " case" : " cases") : "none closed"]; }),
                    datasets: [
                        { label: "Within TAT", data: months.map(function (m) { return m.withinTat; }), backgroundColor: months.map(function (m) { return grad("tTrend", band(m.withinTat), 1, .55); }), borderRadius: 7, maxBarThickness: 46, stack: "s" },
                        { label: "Remaining", data: months.map(function (m) { return m.withinTat === null ? null : 100 - m.withinTat; }), backgroundColor: "rgba(0,39,51,.06)", borderRadius: 7, maxBarThickness: 46, stack: "s" }
                    ] },
            options: { responsive: true, maintainAspectRatio: false, layout: { padding: { top: 18 } },
                       plugins: { legend: { display: false }, tooltip: { filter: function (i) { return i.datasetIndex === 0; }, callbacks: { label: function (ctx) {
                           var n = judged[ctx.dataIndex]; if (!n) return " Nothing closed against a due date"; var p = ctx.parsed.y; return " " + p + "% — " + Math.round(p * n / 100) + " of " + n + " met the committed date"; } } } },
                       scales: { y: { stacked: true, beginAtZero: true, max: 100, ticks: { callback: function (v) { return v + "%"; }, stepSize: 25 }, grid: { color: GRID } },
                                 x: { stacked: true, grid: { display: false }, ticks: { color: INK } } },
                       onClick: function (evt, els) { if (els.length) setDrill("month", months[els[0].index].key, { label: "Closed in " + months[els[0].index].label }); } },
            plugins: [target, barLabels(function (v) { return v + "%"; }, 0, true)],
            emptyText: "Nothing has closed against a due date yet"
        });
        var totalJudged = judged.reduce(function (a, b) { return a + b; }, 0);
        $("tTrendNote").textContent = totalJudged ? "Based on " + totalJudged + " closed case" + (totalJudged === 1 ? "" : "s") + " with a PO due date." : "Nothing has closed against a due date yet.";

        renderTable("tList", "tH", "tChips", "tMore", scopedForList(drilled(cases)), listLabel());
    }

    /* ---------- export ---------------------------------------------------- */

    $("exp").addEventListener("click", function () {
        var cases = drilled(scoped());
        var sheet = cases.slice().sort(M.urgencyOrder).map(function (c) {
            return { "SC number": c.sc || c.id, "Ticket": c.id, "Topic": c.topic, "Department": c.dept, "Commodity": c.comm, "Requester": c.requester, "Buyer": c.buyer,
                     "Status": c.status, "TAT status": c.tat || "", "TAT commitment (working days)": c.tat_days || "",
                     "Working days left": c.daysLeft === null ? "" : c.daysLeft, "Value (INR)": c.value_inr, "Currency": c.ccy, "Value (as documented)": c.value,
                     "Submitted": c.sub ? M.iso(c.sub) : "", "Documents complete": c.docs || "", "PO due": c.po ? M.iso(c.po) : "", "Closed": c.closed ? M.iso(c.closed) : "",
                     "PO number": c.po_no || "", "With": c.with };
        });
        var k = M.kpis(cases, CFG.today), split = tatSplit(cases);
        var summary = [
            { Measure: "As of", Value: M.iso(TODAY) }, { Measure: "View", Value: VIEWS[view].title },
            { Measure: "Month filter", Value: fMonth === "all" ? "All months" : M.monthLabel(fMonth) }, { Measure: "Buyer filter", Value: fBuyer === "all" ? "All buyers" : fBuyer },
            { Measure: "List filter", Value: drill[view] ? (drill[view].label || drill[view].value) : "None" },
            { Measure: "Open cases", Value: k.open }, { Measure: "Open value (INR)", Value: k.openValueInr }, { Measure: "Closed in last 30 days", Value: k.closedRecent },
            { Measure: "On track", Value: k.onTrack }, { Measure: "At risk", Value: k.atRisk }, { Measure: "Delayed", Value: k.delayed }, { Measure: "Clock not started", Value: k.notStarted },
            { Measure: "Within TAT, all POs", Value: split.all.pct === null ? "n/a" : split.all.pct + "% (" + split.all.ok + " of " + split.all.n + ")" },
            { Measure: "Within TAT, 15-day", Value: split["15"].pct === null ? "n/a" : split["15"].pct + "% (" + split["15"].ok + " of " + split["15"].n + ")" },
            { Measure: "Within TAT, 30-day", Value: split["30"].pct === null ? "n/a" : split["30"].pct + "% (" + split["30"].ok + " of " + split["30"].n + ")" }
        ];
        // The list and the summary, then every chart on this view - its data,
        // a native Excel chart and the picture - built server side.
        window.DashExport.run({ filename: "samagra-dashboard-" + view + "-" + M.iso(TODAY) + ".xlsx", button: $("exp"), charts: charts,
                                sheets: [{ name: "Cases", rows: sheet }, { name: "Summary", rows: summary }] });
    });

    /* ---------- main ------------------------------------------------------ */

    function render() {
        var cases = scoped();
        $("ptitle").textContent = VIEWS[view].title;
        $("msub").textContent = asOf();
        $("mwrap").hidden = !VIEWS[view].months;
        Array.prototype.forEach.call(document.querySelectorAll(".sf-bd .page"), function (p) { p.classList.toggle("on", p.id === "p-" + view); });
        renderKpis(cases);
        if (view === "overview") renderOverview(cases);
        else if (view === "cases") renderCases(cases);
        else if (view === "dept") renderDept(cases);
        else if (view === "com") renderCom(cases);
        else if (view === "buyers") renderBuyers(cases);
        else if (view === "tat") renderTat(cases);
    }

    var wanted = location.hash.slice(1);
    if (wanted && VIEWS[wanted]) selectTab(wanted);
    render();
}());
