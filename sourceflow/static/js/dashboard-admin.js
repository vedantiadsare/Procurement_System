/* The procurement head's dashboard - rendering.

   One filter rail narrows everything; five tabs each answer one question
   with their own charts and their own filterable list. All arithmetic comes
   from dash-metrics.js plus a few derivations here (age, single sourcing).
   Nothing round-trips to the server; every control re-slices one array.

   Colour is assigned by job, never by rank: six categorical slots in fixed
   order (validated for the dark surface), blue as the sequential hue, and
   the status set - good / warning / critical / not started - reserved for
   TAT state. Text always wears ink. */
(function () {
    "use strict";

    var CFG = window.SAMAGRA_DASH || {};
    var M = window.DashMetrics;
    var raw = document.getElementById("dashData");
    var ALL = M.prepare(raw ? JSON.parse(raw.textContent) : [], CFG.today);
    var TODAY = M.parseDate(CFG.today) || new Date();
    var $ = function (id) { return document.getElementById(id); };

    // Light-surface steps of the same six hues (validated on white: every
    // adjacent pair clears the CVD and normal-vision floors).
    var C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"];
    var SEQ = ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"];
    var ST = { "On track": "#0E9F5A", "At risk": "#C26D00", "Delayed": "#d03b3b", "Clock not started": "#6E8290" };
    var GREY = "#6E8290", INK = "#0B2B3A", INK2 = "#5B6E78", GRID = "rgba(11,43,58,.08)", SURFACE = "#ffffff";
    var FONT = 'Inter, "Segoe UI", system-ui, sans-serif';
    var LABEL = { dept: "Department", requester: "Requester", buyer: "Buyer", comm: "Commodity", supplier: "Supplier" };
    var FALLBACK = { dept: "Not set", requester: "Unknown", buyer: "Unassigned", comm: "Not set", supplier: "No supplier yet" };
    var STATUS_ORDER = ["Unassigned", "Clock not started", "On track", "At risk", "Delayed", "Waiting on requestor", "Approved", "Rejected"];
    var STATUS_TEXT = { "Delayed": "Overdue", "Approved": "PO created" };
    var STATUS_CLASS = { "Delayed": "late", "At risk": "risk", "On track": "ok", "Clock not started": "muted",
                         "Unassigned": "muted", "Waiting on requestor": "wait", "Approved": "done", "Rejected": "muted" };
    var AGE_BUCKETS = [["0-7 days", 0, 7], ["8-14 days", 8, 14], ["15-30 days", 15, 30], ["31-60 days", 31, 60], ["Over 60 days", 61, 1e9]];

    Chart.defaults.color = INK2;
    Chart.defaults.font.family = FONT;
    Chart.defaults.font.size = 11.5;
    Chart.defaults.borderColor = GRID;
    Chart.defaults.plugins.tooltip.backgroundColor = "#ffffff";
    Chart.defaults.plugins.tooltip.titleColor = INK;
    Chart.defaults.plugins.tooltip.bodyColor = INK2;
    Chart.defaults.plugins.tooltip.borderColor = "rgba(11,43,58,.16)";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
    Chart.defaults.plugins.legend.labels.color = INK;
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.usePointStyle = true;

    /* ---------- formatting ---------------------------------------------- */

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
    function lakhs(n) { return "₹" + lakh(n).toLocaleString("en-IN") + " L"; }
    var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    function dmy(d) { return d ? (d.getDate() < 10 ? "0" : "") + d.getDate() + " " + MON[d.getMonth()] + " " + d.getFullYear() : "—"; }
    function dm(d) { return d ? d.getDate() + " " + MON[d.getMonth()] : ""; }
    function days(a, b) { return Math.max(0, Math.round((b - a) / 864e5)); }
    function pct(a, b) { return b ? Math.round(a * 100 / b) : 0; }
    function initials(name) {
        var p = String(name || "").trim().split(/\s+/).filter(Boolean);
        return p.length ? (p.length === 1 ? p[0].slice(0, 2) : p[0][0] + p[p.length - 1][0]).toUpperCase() : "?";
    }
    function hexA(hex, a) {
        var h = hex.replace("#", "");
        return "rgba(" + parseInt(h.slice(0, 2), 16) + "," + parseInt(h.slice(2, 4), 16) + "," + parseInt(h.slice(4, 6), 16) + "," + a + ")";
    }
    function first(name) { return String(name || "").split(" ")[0]; }

    /* ---------- per-case derivations ------------------------------------ */

    function ageBucket(age) {
        if (age === null || age === undefined) return null;
        for (var i = 0; i < AGE_BUCKETS.length; i++) if (age >= AGE_BUCKETS[i][1] && age <= AGE_BUCKETS[i][2]) return AGE_BUCKETS[i][0];
        return null;
    }
    ALL.forEach(function (c) {
        c.age = c.sub ? days(c.sub, c.done && c.closed ? c.closed : TODAY) : null;
        c.ageShare = (c.tat_days && c.docs && c.po)
            ? Math.min(1, days(M.parseDate(c.docs), c.done && c.closed ? c.closed : TODAY) / (c.tat_days * 1.4)) : null;
        c.suppliers = c.suppliers || [];
        c.single = !!c.single;
        c.bucket = ageBucket(c.age);
    });
    function values(c, key) {
        if (key === "supplier") return c.suppliers.length ? c.suppliers : [FALLBACK.supplier];
        return [c[key] || FALLBACK[key]];
    }
    function has(c, key, value) { return values(c, key).indexOf(value) !== -1; }

    /* Closed within TAT, as the head defines it: POs released on or before
       the committed date, divided by every PO released - not a rolling
       window. A case counts once it is approved and had a committed date to
       be measured against; a PO with no clock is left out rather than
       counted as on time. Split by the commitment it was measured against,
       because 15-day and 30-day topics are different work. */
    function tatSplit(cases) {
        var out = { all: { n: 0, ok: 0 }, b15: { n: 0, ok: 0 }, b30: { n: 0, ok: 0 }, other: { n: 0, ok: 0 } };
        cases.forEach(function (c) {
            if (!(c.done && c.status === "Approved" && c.po && c.closed)) return;
            var ok = c.closed <= c.po;
            var band = c.tat_days === 15 ? "b15" : c.tat_days === 30 ? "b30" : "other";
            out.all.n++; out[band].n++;
            if (ok) { out.all.ok++; out[band].ok++; }
        });
        ["all", "b15", "b30", "other"].forEach(function (k) { out[k].pct = out[k].n ? Math.round(out[k].ok * 100 / out[k].n) : null; });
        return out;
    }
    function statusOf(c) {
        if (c.done) return c.status === "Approved" ? "Approved" : "Rejected";
        if (c.status === "Waiting on requestor") return "Waiting on requestor";
        if (c.status === "Unassigned") return "Unassigned";
        return c.tat || "Clock not started";
    }

    /* ---------- state ------------------------------------------------------ */

    var RAIL = ["dept", "requester", "buyer", "comm", "supplier"];
    var TABS = ["overview", "dept", "people", "suppliers", "tat"];
    var f = { dept: "all", requester: "all", buyer: "all", comm: "all", supplier: "all", single: false };
    var tab = "overview";
    var drill = {};
    var lists = {};
    var PAGE = 10;
    TABS.forEach(function (t) { drill[t] = null; lists[t] = { q: "", status: "all", sort: t === "tat" ? "late" : "age", extra: "all", shown: PAGE }; });
    var piv = { ov: "dept", who: "buyer", sp: "dept" };
    var charts = {};

    function railed(except) {
        return ALL.filter(function (c) {
            for (var i = 0; i < RAIL.length; i++) {
                var k = RAIL[i];
                if (k === except) continue;
                if (f[k] !== "all" && !has(c, k, f[k])) return false;
            }
            if (f.single && !c.single) return false;
            return true;
        });
    }

    function matchDrill(c, d) {
        if (!d) return true;
        switch (d.key) {
            case "open": return c.open;
            case "single": return c.single;
            case "tat": return c.tat === d.value;
            case "status": return statusOf(c) === d.value;
            case "sdept": return c.single && (c.dept || FALLBACK.dept) === d.value;
            case "ssup": return c.single && has(c, "supplier", d.value);
            case "age": return c.bucket === d.value;
            case "month": return !!c.closed && M.monthKey(c.closed) === d.value;
            case "cell": return (c[d.field || "dept"] || FALLBACK[d.field || "dept"]) === d.value && statusOf(c) === d.status;
            case "scell": return c.single && (c.dept || FALLBACK.dept) === d.dept && has(c, "supplier", d.supplier);
            default: return has(c, d.key, d.value);
        }
    }

    function setDrill(t, d) {
        var cur = drill[t];
        drill[t] = (cur && JSON.stringify(cur) === JSON.stringify(d)) ? null : d;
        lists[t].shown = PAGE;
        render();
        // A click on a chart is a question about which cases; the answer is
        // the list, so go there - unless the click just cleared the filter.
        if (drill[t]) goToList(t);
    }

    function goToList(t) {
        var host = document.querySelector('.ad-list[data-list="' + t + '"]');
        if (!host || !host.scrollIntoView) return;
        host.scrollIntoView({ behavior: "smooth", block: "start" });
        host.classList.remove("ad-list--flash");
        void host.offsetWidth;
        host.classList.add("ad-list--flash");
    }

    function listed(t, extraKey) {
        var L = lists[t], q = L.q.toLowerCase();
        return railed().filter(function (c) {
            if (!matchDrill(c, drill[t])) return false;
            if (L.status !== "all" && statusOf(c) !== L.status) return false;
            if (extraKey && L.extra !== "all" && !has(c, extraKey, L.extra)) return false;
            if (q) {
                var hay = [c.sc, c.id, c.topic, c.requester, c.dept, c.buyer, c.comm, c.suppliers.join(" ")].join(" ").toLowerCase();
                if (hay.indexOf(q) === -1) return false;
            }
            return true;
        });
    }

    function sorted(rows, sort) {
        var out = rows.slice();
        if (sort === "age") out.sort(function (a, b) { return (b.age || 0) - (a.age || 0); });
        else if (sort === "late") out.sort(M.urgencyOrder);
        else if (sort === "new") out.sort(function (a, b) { return (b.sub || 0) - (a.sub || 0); });
        else if (sort === "value") out.sort(function (a, b) { return (b.value_inr || 0) - (a.value_inr || 0); });
        return out;
    }

    /* ---------- grouping ----------------------------------------------- */

    function groupsFor(cases, key, filter) {
        var map = {};
        cases.forEach(function (c) {
            if (filter && !filter(c)) return;
            values(c, key).forEach(function (v) {
                if (!map[v]) map[v] = { name: v, count: 0, late: 0, value: 0, cases: [] };
                map[v].count++;
                if (c.tat === "Delayed") map[v].late++;
                map[v].value += Number(c.value_inr || 0);
                map[v].cases.push(c);
            });
        });
        return Object.keys(map).map(function (k) { return map[k]; })
            .sort(function (a, b) { return b.count - a.count || a.name.localeCompare(b.name); });
    }
    function topN(groups, n, by) {
        var g = groups.slice().sort(function (a, b) { return (b[by] || 0) - (a[by] || 0); });
        if (g.length <= n) return { top: g, other: null };
        var rest = g.slice(n);
        return { top: g.slice(0, n), other: { name: "Other", count: rest.reduce(function (s, x) { return s + x.count; }, 0),
                 value: rest.reduce(function (s, x) { return s + x.value; }, 0), members: rest.map(function (x) { return x.name; }) } };
    }

    /* ---------- rail, tabs, controls ------------------------------------ */

    function renderRail() {
        RAIL.forEach(function (k) {
            var sel = $("adRail").querySelector('select[data-f="' + k + '"]');
            var counts = {};
            railed(k).forEach(function (c) { values(c, k).forEach(function (v) { counts[v] = (counts[v] || 0) + 1; }); });
            var names = Object.keys(counts).sort();
            if (f[k] !== "all" && names.indexOf(f[k]) === -1) names.unshift(f[k]);
            sel.innerHTML = '<option value="all">All ' + esc(LABEL[k].toLowerCase()) + "s</option>" +
                names.map(function (n) {
                    return '<option value="' + esc(n) + '"' + (f[k] === n ? " selected" : "") + ">" + esc(n) + " (" + (counts[n] || 0) + ")</option>";
                }).join("");
            sel.classList.toggle("on", f[k] !== "all");
        });
        var n = railed().length;
        $("adRailCount").textContent = n === ALL.length ? ALL.length + " cases" : n + " of " + ALL.length + " cases";
    }

    (function build() {
        Array.prototype.forEach.call($("adRail").querySelectorAll("select[data-f]"), function (sel) {
            sel.addEventListener("change", function () {
                f[sel.getAttribute("data-f")] = sel.value;
                TABS.forEach(function (t) { drill[t] = null; });
                render();
            });
        });
        $("adOnlySingle").addEventListener("change", function () { f.single = this.checked; render(); });
        $("adReset").addEventListener("click", function () {
            f = { dept: "all", requester: "all", buyer: "all", comm: "all", supplier: "all", single: false };
            $("adOnlySingle").checked = false;
            TABS.forEach(function (t) { drill[t] = null; lists[t].q = ""; lists[t].status = "all"; lists[t].extra = "all"; });
            render();
        });
        Array.prototype.forEach.call($("adTabs").querySelectorAll("button"), function (b) {
            b.addEventListener("click", function () {
                tab = b.getAttribute("data-t");
                location.hash = tab;
                render();
            });
        });
        Array.prototype.forEach.call(document.querySelectorAll("[data-seg]"), function (seg) {
            var name = seg.getAttribute("data-seg");
            Array.prototype.forEach.call(seg.querySelectorAll("button"), function (b) {
                b.addEventListener("click", function () {
                    Array.prototype.forEach.call(seg.querySelectorAll("button"), function (x) { x.classList.toggle("on", x === b); });
                    var k = b.getAttribute("data-k");
                    if (name === "ovPivot") { piv.ov = k; drill.overview = null; }
                    if (name === "ppWho") { piv.who = k; drill.people = null; lists.people.extra = "all"; }
                    if (name === "spPivot") { piv.sp = k; drill.suppliers = null; }
                    render();
                });
            });
        });
        $("adAsOf").textContent = "As of " + dmy(TODAY);
        var wanted = location.hash.slice(1);
        if (TABS.indexOf(wanted) !== -1) tab = wanted;
    }());

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
            p.textContent = config.emptyText || "Nothing in this selection";
            holder.appendChild(p);
            return null;
        }
        el.style.display = "";
        charts[id] = new Chart(el.getContext("2d"), config);
        return charts[id];
    }

    // Built from the canvas's own box, which is real by the time a visible
    // tab renders; anything unusable falls back to a flat fill.
    function grad(id, hex, a0, a1, horizontal) {
        var el = $(id);
        if (!el) return hexA(hex, a0);
        var box = el.getBoundingClientRect();
        var w = box.width || el.width, h = box.height || el.height;
        if (!w || !h) return hexA(hex, a0);
        try {
            var g = horizontal ? el.getContext("2d").createLinearGradient(0, 0, w, 0)
                               : el.getContext("2d").createLinearGradient(0, 0, 0, h);
            g.addColorStop(0, hexA(hex, a0));
            g.addColorStop(1, hexA(hex, a1));
            return g;
        } catch (e) { return hexA(hex, a0); }
    }

    function centreText(big, small) {
        return { id: "centre", afterDraw: function (chart) {
            var a = chart.getDatasetMeta(0).data[0];
            if (!a) return;
            var ctx = chart.ctx;
            ctx.save(); ctx.textAlign = "center";
            ctx.fillStyle = INK; ctx.font = "700 26px " + FONT;
            ctx.fillText(big, a.x, a.y - 2);
            ctx.fillStyle = INK2; ctx.font = "11px " + FONT;
            ctx.fillText(small, a.x, a.y + 16);
            ctx.restore();
        } };
    }

    function barLabels(fmt, inside, showZero, onlyDataset) {
        return { id: "barLabels", afterDatasetsDraw: function (chart) {
            var ctx = chart.ctx;
            ctx.save(); ctx.font = "600 11px " + FONT; ctx.fillStyle = INK; ctx.textBaseline = "middle";
            var horizontal = chart.options.indexAxis === "y";
            chart.data.datasets.forEach(function (ds, di) {
                var meta = chart.getDatasetMeta(di);
                if (meta.hidden || (onlyDataset !== undefined && di !== onlyDataset)) return;
                meta.data.forEach(function (bar, i) {
                    var v = ds.data[i];
                    if (v === null || v === undefined || v === "" || (Number(v) === 0 && !showZero)) return;
                    var text = fmt ? fmt(v, i) : String(v);
                    if (horizontal) { ctx.textAlign = "left"; ctx.fillText(text, bar.x + 6, bar.y); }
                    else { ctx.textAlign = "center"; ctx.fillText(text, bar.x, inside ? bar.y + 12 : bar.y - 8); }
                });
            });
            ctx.restore();
        } };
    }

    function legendInto(el, entries, onClick, active) {
        el.innerHTML = entries.map(function (e, i) {
            return '<li data-i="' + i + '" class="' + (active === e.label ? "on" : "") + '"><i style="background:' + e.color + '"></i>' +
                esc(e.label) + (e.count == null ? "" : " <b>" + e.count + "</b>") + "</li>";
        }).join("");
        if (!onClick) return;
        Array.prototype.forEach.call(el.querySelectorAll("li"), function (li) {
            li.addEventListener("click", function () { onClick(entries[Number(li.getAttribute("data-i"))]); });
        });
    }

    function stackOpts(onPick) {
        return {
            indexAxis: "y", responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false } },
            scales: { x: { stacked: true, beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } },
                      y: { stacked: true, grid: { display: false }, ticks: { color: INK } } },
            onClick: function (evt, els) { if (els.length) onPick(els[0].index); }
        };
    }

    function stackData(rows) {
        return { labels: rows.map(function (r) { return r.name; }),
                 datasets: M.TAT_STATES.map(function (s) {
                     return { label: s, data: rows.map(function (r) { return r[s]; }), backgroundColor: ST[s],
                              borderColor: SURFACE, borderWidth: 1, borderRadius: 3, barThickness: 16 };
                 }) };
    }

    function tatRows(cases, key) {
        return groupsFor(cases, key, M.isOpen).map(function (g) {
            var row = { name: g.name, total: g.count };
            M.TAT_STATES.forEach(function (s) { row[s] = 0; });
            g.cases.forEach(function (c) { if (c.tat) row[c.tat]++; });
            return row;
        });
    }

    /* ---------- small components ------------------------------------- */

    var ICON = {
        cart: '<path d="M3 4h2l2.4 10.5a1 1 0 0 0 1 .8h8.8a1 1 0 0 0 1-.8L20 7H7"/><circle cx="9.5" cy="19" r="1.4"/><circle cx="16.5" cy="19" r="1.4"/>',
        clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
        tick: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
        bang: '<path d="M12 5v9"/><circle cx="12" cy="18" r="1.1" fill="currentColor" stroke="none"/>',
        risk: '<path d="M12 4 3 20h18L12 4z"/><path d="M12 10v5"/><circle cx="12" cy="17.5" r=".9" fill="currentColor" stroke="none"/>',
        one: '<circle cx="12" cy="12" r="8.5"/><path d="M10.5 9.5 12.5 8v8"/>',
        done: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8 12 3 3 5-6"/>',
        users: '<circle cx="9" cy="8" r="3.5"/><path d="M3 20a6 6 0 0 1 12 0"/><circle cx="17" cy="9" r="2.5"/><path d="M15.5 14.5a5 5 0 0 1 5.5 5.5"/>',
        building: '<rect x="4" y="3" width="16" height="18" rx="1"/><path d="M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10 21v-3h4v3"/>',
        pause: '<circle cx="12" cy="12" r="8.5"/><path d="M10 9v6M14 9v6"/>',
        star: '<path d="m12 3.5 2.6 5.4 5.9.8-4.3 4.1 1.1 5.9L12 16.9l-5.3 2.8 1.1-5.9-4.3-4.1 5.9-.8z"/>'
    };
    function svgIcon(k) { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + ICON[k] + "</svg>"; }

    function tiles(hostId, items) {
        $(hostId).innerHTML = items.map(function (x, i) {
            return '<div class="ad-tile' + (x.go ? " ad-tile--go" : "") + '" style="--acc:' + x.acc + '" data-i="' + i + '"' + (x.go ? ' role="button" tabindex="0" title="Show these cases"' : "") + '><span class="ad-tile__ic">' + svgIcon(x.icon) + "</span>" +
                '<div><span class="ad-tile__t">' + esc(x.t) + "</span><strong>" + esc(String(x.v)) + "</strong>" +
                '<span class="ad-tile__s">' + esc(x.s) + "</span></div></div>";
        }).join("");
        Array.prototype.forEach.call($(hostId).querySelectorAll(".ad-tile--go"), function (el) {
            el.addEventListener("click", function () { items[Number(el.getAttribute("data-i"))].go(); });
        });
    }

    function sparkSVG(vals) {
        var w = 118, h = 44, n = vals.length;
        if (n < 2) return "";
        var max = Math.max.apply(null, vals) || 1;
        var pts = vals.map(function (v, i) { return [Math.round(i * w / (n - 1)), Math.round(h - 4 - v / max * (h - 10))]; });
        var d = pts.map(function (p, i) { return (i ? "L" : "M") + p[0] + " " + p[1]; }).join(" ");
        var last = pts[n - 1];
        return '<svg viewBox="0 0 ' + w + " " + h + '" aria-hidden="true"><path d="' + d + " L" + w + " " + h + " L0 " + h + ' Z" fill="rgba(255,255,255,.22)"/>' +
            '<path d="' + d + '" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
            '<circle cx="' + last[0] + '" cy="' + last[1] + '" r="3" fill="#fff"/></svg>';
    }
    function barsSVG(vals) {
        var w = 118, h = 44, n = vals.length;
        if (!n) return "";
        var max = Math.max.apply(null, vals) || 1, bw = Math.floor((w - (n - 1) * 4) / n);
        return '<svg viewBox="0 0 ' + w + " " + h + '" aria-hidden="true">' + vals.map(function (v, i) {
            var bh = Math.max(3, Math.round(v / max * (h - 4)));
            return '<rect x="' + (i * (bw + 4)) + '" y="' + (h - bh) + '" width="' + bw + '" height="' + bh + '" rx="2" fill="rgba(255,255,255,' + (i === n - 1 ? ".95" : ".55") + ')"/>';
        }).join("") + "</svg>";
    }

    function bars(el, groups, opts) {
        if (!groups.length) { el.innerHTML = '<p class="ad-empty">' + esc(opts.empty || "Nothing in this selection.") + "</p>"; return; }
        var max = groups.reduce(function (m, g) { return Math.max(m, opts.share ? 100 : g.count); }, 0) || 1;
        el.innerHTML = groups.map(function (g) {
            var width = opts.share ? g.share : Math.max(4, Math.round(g.count * 100 / max));
            var on = opts.active === g.name;
            return '<button type="button" class="ad-bar' + (opts.share ? " ad-bar--share" : "") + (on ? " on" : "") + '" data-name="' + esc(g.name) + '">' +
                '<span class="ad-bar__label">' + esc(g.name) + "</span>" +
                '<span class="ad-bar__track"><span class="ad-bar__fill" style="width:' + width + '%"></span>' +
                (!opts.share && g.late ? '<span class="ad-bar__late" style="width:' + Math.round(g.late * 100 / max) + '%"></span>' : "") +
                (opts.share ? '<span class="ad-bar__pct">' + g.share + "%</span>" : "") + "</span>" +
                '<span class="ad-bar__n">' + g.count + (opts.sub && opts.sub(g) ? " <em>" + esc(opts.sub(g)) + "</em>" : "") + "</span></button>";
        }).join("");
        Array.prototype.forEach.call(el.querySelectorAll(".ad-bar"), function (b) {
            b.addEventListener("click", function () { opts.onPick(b.getAttribute("data-name")); });
        });
    }

    /* One full-width bar per group, split into its TAT states with the
       count inside each segment - so a department with two cases fills its
       row as fully as one with twenty, and the colour balance says how it
       is doing before the numbers do. Worst first. */
    var STATE_ORDER = ["Delayed", "At risk", "On track", "Clock not started"];
    var STATE_CLASS = { "Delayed": "late", "At risk": "risk", "On track": "ok", "Clock not started": "none" };
    function hbarRows(cases, key) {
        return groupsFor(cases, key, M.isOpen).map(function (g) {
            var by = {};
            STATE_ORDER.forEach(function (st) { by[st] = 0; });
            g.cases.forEach(function (c) { if (by[c.tat] !== undefined) by[c.tat]++; });
            var clocked = by["Delayed"] + by["At risk"] + by["On track"];
            return { name: g.name, total: g.count, by: by, trouble: by["Delayed"] + by["At risk"],
                     score: clocked ? Math.round(by["On track"] * 100 / clocked) : null };
        }).sort(function (a, b) { return (b.trouble / b.total) - (a.trouble / a.total) || b.trouble - a.trouble || b.total - a.total || a.name.localeCompare(b.name); });
    }
    function hbars(el, rows, key, onPick, onPickCell, active) {
        if (!rows.length) { el.innerHTML = '<p class="ad-empty">No open cases in this selection.</p>'; return; }
        if (window.DashExport) window.DashExport.register(el, { type: "stacked", stacked: true, series: STATE_ORDER.length,
            headers: [""].concat(STATE_ORDER.map(function (st) { return st === "Delayed" ? "Overdue" : st; })).concat(["Open", "On track %"]),
            rows: rows.map(function (r) { return [r.name].concat(STATE_ORDER.map(function (st) { return r.by[st]; })).concat([r.total, r.score]); }) });
        el.innerHTML = rows.slice(0, 14).map(function (r, i) {
            var segs = STATE_ORDER.filter(function (st) { return r.by[st]; }).map(function (st) {
                var w = r.by[st] * 100 / r.total;
                var on = active && active.key === "cell" && active.value === r.name && active.status === st;
                return '<button type="button" class="ad-hbar__seg ad-hbar__seg--' + STATE_CLASS[st] + (on ? " on" : "") + '" style="flex-basis:' + w + '%" data-name="' + esc(r.name) + '" data-st="' + st + '" title="' + esc(r.name + ": " + r.by[st] + " " + (STATUS_TEXT[st] || st).toLowerCase()) + '">' + (w >= 9 ? r.by[st] : "") + "</button>";
            }).join("");
            var tone = r.score === null ? "muted" : r.score >= 80 ? "ok" : r.score >= 60 ? "warn" : "bad";
            var rowOn = active && active.key === key && active.value === r.name;
            return '<div class="ad-hbar' + (rowOn ? " on" : "") + '" style="--i:' + i + '">' +
                '<button type="button" class="ad-hbar__label" data-name="' + esc(r.name) + '" title="Filter the list to ' + esc(r.name) + '">' + esc(r.name) + "<small>" + r.total + " open" + (r.trouble ? " · " + r.trouble + " need attention" : "") + "</small></button>" +
                '<div class="ad-hbar__bar">' + segs + "</div>" +
                '<span class="ad-hbar__score"><span class="pill pill--' + tone + '">' + (r.score === null ? "—" : r.score + "%") + "</span></span></div>";
        }).join("");
        Array.prototype.forEach.call(el.querySelectorAll(".ad-hbar__label"), function (b) {
            b.addEventListener("click", function () { onPick(b.getAttribute("data-name")); });
        });
        Array.prototype.forEach.call(el.querySelectorAll(".ad-hbar__seg"), function (b) {
            b.addEventListener("click", function () { onPickCell(b.getAttribute("data-name"), b.getAttribute("data-st")); });
        });
    }

    function heat(el, rowNames, colNames, get, hue, onPick, isOn, colText) {
        var max = 0;
        rowNames.forEach(function (r) { colNames.forEach(function (c) { max = Math.max(max, get(r, c)); }); });
        if (!rowNames.length || !max) { el.innerHTML = '<p class="ad-empty">Nothing in this selection.</p>'; return; }
        if (window.DashExport) window.DashExport.register(el, { type: "stacked", stacked: true,
            headers: [""].concat(colNames.map(function (c) { return String(colText ? colText(c) : c); })),
            rows: rowNames.map(function (r) { return [String(r)].concat(colNames.map(function (c) { return get(r, c); })); }) });
        var html = "<table><thead><tr><th></th>" + colNames.map(function (c) { return "<th>" + esc(colText ? colText(c) : c) + "</th>"; }).join("") + "</tr></thead><tbody>";
        rowNames.forEach(function (r) {
            html += "<tr><th>" + esc(r) + "</th>" + colNames.map(function (c) {
                var v = get(r, c);
                var a = v ? 0.16 + 0.74 * v / max : 0;
                var bg = v ? hexA(hue, a) : "rgba(11,43,58,.04)";
                return '<td class="' + (v ? "" : "z") + (isOn(r, c) ? " on" : "") + '" style="background:' + bg + ";color:" + (a > 0.55 ? "#fff" : INK) + '" data-r="' + esc(r) + '" data-c="' + esc(c) + '" title="' + esc(r + " · " + (colText ? colText(c) : c) + ": " + v) + '">' + (v || "·") + "</td>";
            }).join("") + "</tr>";
        });
        el.innerHTML = html + "</tbody></table>";
        Array.prototype.forEach.call(el.querySelectorAll("td"), function (td) {
            td.addEventListener("click", function () { if (td.textContent !== "·") onPick(td.getAttribute("data-r"), td.getAttribute("data-c")); });
        });
    }

    /* ---------- the list ------------------------------------------------- */

    var SORTS = [["age", "Highest age"], ["late", "Most overdue"], ["new", "Newest"], ["value", "Highest value"]];

    function drillLabel(d) {
        if (!d) return "";
        switch (d.key) {
            case "open": return "Open cases";
            case "single": return "Single-sourced";
            case "tat": return "TAT: " + d.value;
            case "status": return "Status: " + (STATUS_TEXT[d.value] || d.value);
            case "sdept": return "Single-sourced · " + d.value;
            case "ssup": return "Sole bidder: " + d.value;
            case "age": return "Age " + d.value;
            case "month": return "Closed in " + M.monthLabel(d.value);
            case "cell": return d.value + " · " + (STATUS_TEXT[d.status] || d.status);
            case "scell": return d.dept + " ← " + d.supplier;
            default: return LABEL[d.key] + ": " + d.value;
        }
    }

    function list(t, opts) {
        var host = document.querySelector('.ad-list[data-list="' + t + '"]');
        if (!host) return;
        var L = lists[t];
        var rows = sorted(listed(t, opts.extraKey), L.sort);
        var extraOptions = "";
        if (opts.extraKey) {
            var names = {};
            railed().forEach(function (c) { values(c, opts.extraKey).forEach(function (v) { names[v] = 1; }); });
            extraOptions = '<select data-l="extra"><option value="all">All ' + esc(LABEL[opts.extraKey].toLowerCase()) + "s</option>" +
                Object.keys(names).sort().map(function (n) { return '<option value="' + esc(n) + '"' + (L.extra === n ? " selected" : "") + ">" + esc(n) + "</option>"; }).join("") + "</select>";
        }
        var page = rows.slice(0, L.shown);
        host.innerHTML =
            '<div class="ad-list__h"><h2>' + esc(opts.title) + '<span class="count">' + rows.length + '</span></h2><span class="ad-note">Rows open the case · Excel export follows this list</span></div>' +
            '<div class="ad-filters"><input type="search" data-l="q" value="' + esc(L.q) + '" placeholder="Search SC number, topic, requester, buyer or supplier" aria-label="Search">' +
            extraOptions +
            '<select data-l="status"><option value="all">All statuses</option>' + STATUS_ORDER.map(function (s) {
                return '<option value="' + s + '"' + (L.status === s ? " selected" : "") + ">" + (STATUS_TEXT[s] || s) + "</option>";
            }).join("") + "</select>" +
            '<select data-l="sort">' + SORTS.map(function (s) { return '<option value="' + s[0] + '"' + (L.sort === s[0] ? " selected" : "") + ">" + s[1] + "</option>"; }).join("") + "</select></div>" +
            '<div class="ad-chips">' + (drill[t] ? '<span class="ad-chip">' + esc(drillLabel(drill[t])) + '<button type="button" data-clear aria-label="Clear">×</button></span>' : "") + "</div>" +
            '<div class="ad-tablewrap"><table>' +
            "<thead><tr><th>Shopping cart</th><th>Department</th><th>Request</th><th>Suppliers</th><th>Created</th><th>TAT</th><th>Age</th><th>Status</th><th class=\"num\">Value</th></tr></thead><tbody>" +
            (page.length ? page.map(row).join("") : '<tr><td colspan="9" class="ad-empty">No cases match these filters.</td></tr>') +
            "</tbody></table></div>" +
            (rows.length > L.shown ? '<button type="button" class="ad-more" data-more>Show all ' + rows.length + "</button>" : (L.shown > PAGE && rows.length > PAGE ? '<button type="button" class="ad-more" data-more="less">Show top ' + PAGE + "</button>" : "")) +
            '<div class="ad-foot"><span>' + (page.length < rows.length ? "Top " + page.length + " of " + rows.length : "All " + rows.length) + " in this view · " + ALL.length + " cases in total</span></div>";

        host.querySelector('[data-l="q"]').addEventListener("input", function () { L.q = this.value.trim(); L.shown = PAGE; refreshList(t, opts); });
        host.querySelector('[data-l="status"]').addEventListener("change", function () { L.status = this.value; L.shown = PAGE; refreshList(t, opts); });
        host.querySelector('[data-l="sort"]').addEventListener("change", function () { L.sort = this.value; refreshList(t, opts); });
        var ex = host.querySelector('[data-l="extra"]');
        if (ex) ex.addEventListener("change", function () { L.extra = this.value; L.shown = PAGE; refreshList(t, opts); });
        var clear = host.querySelector("[data-clear]");
        if (clear) clear.addEventListener("click", function () { drill[t] = null; render(); });
        var more = host.querySelector("[data-more]");
        if (more) more.addEventListener("click", function () { L.shown = more.getAttribute("data-more") === "less" ? PAGE : rows.length; refreshList(t, opts); });
    }

    // Re-render just the list, keeping the caret where it was.
    function refreshList(t, opts) {
        var host = document.querySelector('.ad-list[data-list="' + t + '"]');
        var q = host.querySelector('[data-l="q"]');
        var focus = document.activeElement === q, pos = q ? q.selectionStart : 0;
        list(t, opts);
        if (focus) { var nq = host.querySelector('[data-l="q"]'); nq.focus(); try { nq.setSelectionRange(pos, pos); } catch (e) { /* type=search may refuse */ } }
    }

    function row(c) {
        var st = statusOf(c), href = CFG.caseUrlBase + c.case_id;
        var tone = ST[c.tat] || ST["Clock not started"];
        var sup = c.suppliers.length
            ? "<b>" + c.suppliers.length + "</b> " + esc(c.suppliers.slice(0, 2).join(", ")) + (c.suppliers.length > 2 ? " +" + (c.suppliers.length - 2) : "")
            : '<span class="ad-muted">none yet</span>';
        return '<tr data-href="' + href + '" tabindex="0">' +
            '<td class="sc"><a href="' + href + '">' + esc(c.sc || c.id) + "</a>" + (c.basis === "Frame contract" ? '<span class="ad-tag">FC</span>' : "") +
                (c.sc && c.id && c.sc !== c.id ? "<small>" + esc(c.id) + "</small>" : "") + "</td>" +
            "<td>" + esc(c.dept) + "</td>" +
            '<td class="req"><b>' + esc(c.topic) + "</b><span>Owner: " + esc(c.requester || "—") + (c.buyer ? " · Buyer: " + esc(c.buyer) : "") + "</span></td>" +
            '<td class="sup">' + sup + (c.single ? '<span class="ad-st ad-st--single">single source</span>' : "") + "</td>" +
            "<td>" + dmy(c.sub) + "</td>" +
            "<td>" + (c.tat_days ? c.tat_days + "d" : "—") + "</td>" +
            '<td class="age"><span>' + (c.age === null ? "—" : c.age + "d") + "</span>" +
                (c.ageShare === null ? "" : '<i><b style="width:' + Math.round(c.ageShare * 100) + '%;background:' + tone + '"></b></i>') + "</td>" +
            '<td><span class="ad-st ad-st--' + (STATUS_CLASS[st] || "muted") + '">' + esc(STATUS_TEXT[st] || st) + "</span></td>" +
            '<td class="num"' + (c.ccy && c.ccy !== "INR" ? ' title="' + esc(c.ccy + " " + Math.round(c.value).toLocaleString("en-US")) + '"' : "") + ">₹" + inr(c.value_inr) + "</td></tr>";
    }

    /* ---------- overview -------------------------------------------------- */

    function renderOverview(cases) {
        var k = M.kpis(cases, CFG.today);
        var open = cases.filter(M.isOpen);
        var weeks = M.byWeek(cases, CFG.today, 12);
        var months = M.byMonth(cases, CFG.today, 6);
        var single = cases.filter(function (c) { return c.single; });
        var withOffers = cases.filter(function (c) { return c.offers > 0; }).length;
        var split = tatSplit(cases);
        var unclaimed = open.filter(function (c) { return c.status === "Unassigned"; }).length;
        var late = open.filter(function (c) { return c.tat === "Delayed"; });
        var worst = late.slice().sort(function (a, b) { return a.po - b.po; })[0];
        var lateByDept = groupsFor(late, "dept").slice(0, 6).map(function (g) { return g.count; });
        var singleByDept = groupsFor(single, "dept").slice(0, 6).map(function (g) { return g.count; });

        var hero = [
            { g: "g1", t: "Active cases", v: k.open, s: cases.length + " total · " + unclaimed + " unclaimed", mini: sparkSVG(weeks.slice(-8).map(function (w) { return w.incoming; })), d: { key: "open" } },
            { g: "g2", t: "Within TAT", v: split.all.pct === null ? "—" : split.all.pct + "%",
              s: split.all.n ? split.all.ok + " of " + split.all.n + " POs" + (split.b15.n ? " · 15-day " + split.b15.pct + "%" : "") + (split.b30.n ? " · 30-day " + split.b30.pct + "%" : "") : "No PO released against a committed date yet",
              mini: barsSVG(months.map(function (m) { return m.withinTat === null ? 0 : m.withinTat; })), d: { key: "status", value: "Approved" } },
            { g: "g3", t: "Overdue", v: k.delayed, s: worst ? "Oldest " + (-worst.daysLeft) + " working days late" : "Nothing past its date", mini: barsSVG(lateByDept), d: { key: "tat", value: "Delayed" } },
            { g: "g4", t: "Single sourcing", v: single.length, s: withOffers ? pct(single.length, withOffers) + "% of cases with quotations" : "No quotations yet", mini: barsSVG(singleByDept), d: { key: "single" } }
        ];
        $("ovHero").innerHTML = hero.map(function (h, i) {
            return '<button type="button" class="' + h.g + '" style="--i:' + i + '" data-i="' + i + '"><span class="h-t">' + esc(h.t) + '</span><span class="h-v">' + esc(String(h.v)) + '</span><span class="h-s">' + esc(h.s) + '</span><span class="h-mini">' + h.mini + "</span></button>";
        }).join("");
        Array.prototype.forEach.call($("ovHero").querySelectorAll("button"), function (b) {
            b.addEventListener("click", function () { setDrill("overview", hero[Number(b.getAttribute("data-i"))].d); });
        });

        var ages = open.map(function (c) { return c.age; }).filter(function (a) { return a !== null; });
        var avgAge = ages.length ? ages.reduce(function (s, a) { return s + a; }, 0) / ages.length : null;
        tiles("ovTiles", [
            { icon: "clock", acc: C[5], t: "Average age", v: avgAge === null ? "—" : avgAge.toFixed(1) + " days", s: "Across active requests" },
            { icon: "risk", acc: ST["At risk"], t: "At risk", v: k.atRisk, s: "Due within 5 working days" },
            { icon: "pause", acc: GREY, t: "Clock not started", v: k.notStarted, s: "Document set not yet checked" },
            { icon: "done", acc: C[4], t: "Closed", v: cases.filter(M.isClosed).length, s: k.closedRecent + " in the last 30 days" }
        ]);

        renderInsights(cases, k, months);

        // Raised vs closed - two counts on one axis, drawn as soft areas.
        var cl = C[0], cc = C[4];
        draw("ovFlow", {
            type: "line",
            data: { labels: weeks.map(function (w) { return dm(w.start); }),
                    datasets: [
                        { label: "Raised", data: weeks.map(function (w) { return w.incoming; }), borderColor: cl, backgroundColor: grad("ovFlow", cl, .38, .03),
                          fill: true, tension: .42, borderWidth: 2.5, pointRadius: 3.5, pointHoverRadius: 6, pointBackgroundColor: cl, pointBorderColor: SURFACE, pointBorderWidth: 2 },
                        { label: "Closed", data: weeks.map(function (w) { return w.closed; }), borderColor: cc, backgroundColor: grad("ovFlow", cc, .34, .03),
                          fill: true, tension: .42, borderWidth: 2.5, pointRadius: 3.5, pointHoverRadius: 6, pointBackgroundColor: cc, pointBorderColor: SURFACE, pointBorderWidth: 2, pointStyle: "rectRot" }
                    ] },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
                       plugins: { legend: { position: "top", align: "end" } },
                       scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } }, x: { grid: { display: false } } } },
            emptyText: "No cases raised or closed in the last 12 weeks"
        });
        var last4 = weeks.slice(-4), inN = 0, outN = 0;
        last4.forEach(function (w) { inN += w.incoming; outN += w.closed; });
        $("ovFlowNote").textContent = inN === outN ? "Last 4 weeks: in and out balanced" : "Last 4 weeks: " + Math.abs(inN - outN) + " more " + (inN > outN ? "raised than closed" : "closed than raised");

        // TAT donut.
        var entries = M.TAT_STATES.map(function (s) { return { label: s, color: ST[s], count: open.filter(function (c) { return c.tat === s; }).length }; });
        draw("ovDonut", {
            type: "doughnut",
            data: { labels: entries.map(function (e) { return e.label; }),
                    datasets: [{ data: entries.map(function (e) { return e.count; }), backgroundColor: entries.map(function (e) { return e.color; }),
                                 borderColor: SURFACE, borderWidth: 3, hoverOffset: 8, borderRadius: 4 }] },
            options: { responsive: true, maintainAspectRatio: false, cutout: "70%", plugins: { legend: { display: false } },
                       onClick: function (evt, els) { if (els.length) setDrill("overview", { key: "tat", value: entries[els[0].index].label }); } },
            plugins: [centreText(String(open.length), "open")],
            emptyText: "No open cases in this selection"
        });
        legendInto($("ovLegend"), entries, function (e) { setDrill("overview", { key: "tat", value: e.label }); },
                   drill.overview && drill.overview.key === "tat" ? drill.overview.value : null);

        // Open value by commodity - polar area, six slots and the rest.
        polar("ovPolar", groupsFor(open, "comm"), "comm", "overview");

        // Workload bars, pivotable.
        var groups = groupsFor(open, piv.ov).slice(0, 10);
        $("ovWorkTitle").textContent = LABEL[piv.ov] + " workload";
        bars($("ovBars"), groups, {
            active: drill.overview && drill.overview.key === piv.ov ? drill.overview.value : null,
            onPick: function (name) { setDrill("overview", { key: piv.ov, value: name }); },
            sub: function (g) { return g.late ? g.late + " late" : ""; },
            empty: "No open cases in this selection."
        });
    }

    function polar(id, groups, key, t) {
        var top = topN(groups, 6, "value");
        var labels = top.top.map(function (g) { return g.name; }), data = top.top.map(function (g) { return lakh(g.value); });
        var colors = top.top.map(function (_, i) { return hexA(C[i], .78); });
        if (top.other) { labels.push("Other"); data.push(lakh(top.other.value)); colors.push(hexA(GREY, .7)); }
        draw(id, {
            type: "polarArea",
            data: { labels: labels, datasets: [{ data: data, backgroundColor: colors, borderColor: SURFACE, borderWidth: 2 }] },
            options: { responsive: true, maintainAspectRatio: false,
                       plugins: { legend: { position: "right", labels: { pointStyle: "rectRounded", padding: 10 } },
                                  tooltip: { callbacks: { label: function (ctx) { return " ₹" + ctx.parsed.r.toLocaleString("en-IN") + " lakh"; } } } },
                       scales: { r: { grid: { color: GRID }, angleLines: { color: GRID }, ticks: { display: false }, beginAtZero: true } },
                       onClick: function (evt, els) {
                           if (!els.length) return;
                           var name = labels[els[0].index];
                           if (name === "Other") return;
                           setDrill(t, { key: key, value: name });
                       } },
            emptyText: "No open value in this selection"
        });
    }

    function renderInsights(cases, k, months) {
        var out = [], open = cases.filter(M.isOpen);
        var late = open.filter(function (c) { return c.tat === "Delayed"; });
        if (late.length) {
            var worst = late.slice().sort(function (a, b) { return a.po - b.po; })[0];
            var byDept = groupsFor(late, "dept")[0];
            out.push({ tone: "bad", head: late.length + " overdue", text: "Oldest is " + worst.topic + " (" + (-worst.daysLeft) + " working days late)" + (byDept ? "; most sit with " + byDept.name : "") + ".",
                       go: function () { drill.overview = { key: "tat", value: "Delayed" }; } });
        }
        var single = cases.filter(function (c) { return c.single; });
        if (single.length) {
            var sd = groupsFor(single, "dept")[0], sup = groupsFor(single, "supplier")[0];
            out.push({ tone: "warn", head: single.length + " single-sourced", text: (sd ? sd.name + " accounts for " + sd.count + ". " : "") + (sup && sup.count > 1 ? sup.name + " was the only bidder " + sup.count + " times." : ""),
                       go: function () { tab = "suppliers"; } });
        }
        var split = tatSplit(cases);
        if (split.all.pct !== null) {
            var thisM = months[months.length - 1], lastM = months[months.length - 2], trend = "";
            if (thisM && lastM && thisM.withinTat !== null && lastM.withinTat !== null) {
                var diff = thisM.withinTat - lastM.withinTat;
                trend = diff === 0 ? "This month level with " + first(lastM.label) + "." : "This month " + (diff > 0 ? "up " : "down ") + Math.abs(diff) + " points on " + first(lastM.label) + ".";
            }
            var bands = [];
            if (split.b15.n) bands.push("15-day " + split.b15.pct + "% (" + split.b15.ok + "/" + split.b15.n + ")");
            if (split.b30.n) bands.push("30-day " + split.b30.pct + "% (" + split.b30.ok + "/" + split.b30.n + ")");
            out.push({ tone: split.all.pct >= 80 ? "good" : split.all.pct >= 60 ? "warn" : "bad", head: split.all.pct + "% of POs within TAT",
                       text: split.all.ok + " of " + split.all.n + " POs released on time" + (bands.length ? " — " + bands.join(", ") : "") + ". " + trend,
                       go: function () { tab = "tat"; } });
        }
        var unclaimed = open.filter(function (c) { return c.status === "Unassigned"; }).length;
        var waiting = open.filter(function (c) { return c.status === "Waiting on requestor"; }).length;
        if (unclaimed || waiting) {
            out.push({ tone: unclaimed ? "warn" : "info", head: [unclaimed ? unclaimed + " unclaimed" : "", waiting ? waiting + " waiting on a requester" : ""].filter(Boolean).join(", "),
                       text: "Nothing moves on these until someone else does.",
                       go: function () { drill.overview = { key: "status", value: unclaimed ? "Unassigned" : "Waiting on requestor" }; } });
        }
        var box = $("ovInsights");
        out = out.slice(0, 4);
        box.hidden = !out.length;
        box.innerHTML = out.map(function (x, i) {
            return '<button type="button" class="ad-ins ad-ins--' + x.tone + '" style="--i:' + i + '"><b>' + esc(x.head) + "</b><span>" + esc(x.text) + "</span></button>";
        }).join("");
        Array.prototype.forEach.call(box.querySelectorAll(".ad-ins"), function (el, i) {
            el.addEventListener("click", function () {
                var before = tab;
                out[i].go(); location.hash = tab; render();
                if (tab === before && drill[tab]) goToList(tab);
            });
        });
    }

    /* ---------- departments ---------------------------------------------- */

    function renderDept(cases) {
        var open = cases.filter(M.isOpen);
        var groups = groupsFor(open, "dept");
        var byLate = groups.slice().sort(function (a, b) { return b.late - a.late; })[0];
        var byValue = groups.slice().sort(function (a, b) { return b.value - a.value; })[0];
        tiles("dpTiles", [
            { icon: "building", acc: C[0], t: "Departments with open cases", v: groups.length, s: cases.length + " cases across " + groupsFor(cases, "dept").length + " departments" },
            { icon: "cart", acc: C[5], t: "Busiest", v: groups[0] ? groups[0].name : "—", s: groups[0] ? groups[0].count + " open cases" : "" },
            { icon: "bang", acc: ST.Delayed, t: "Most overdue", v: byLate && byLate.late ? byLate.name : "—", s: byLate && byLate.late ? byLate.late + " past the PO date" : "Nothing overdue" },
            { icon: "star", acc: C[3], t: "Highest open value", v: byValue ? byValue.name : "—", s: byValue ? lakhs(byValue.value) + " open" : "" }
        ]);

        hbars($("dpUnits"), hbarRows(cases, "dept"), "dept",
              function (name) { setDrill("dept", { key: "dept", value: name }); },
              function (name, st) { setDrill("dept", { key: "cell", field: "dept", value: name, status: st }); },
              drill.dept);
        legendInto($("dpStackLegend"), M.TAT_STATES.map(function (s) { return { label: s, color: ST[s] }; }));

        polar("dpPolar", groups, "dept", "dept");

        var depts = groupsFor(cases, "dept").map(function (g) { return g.name; });
        var cell = {};
        cases.forEach(function (c) { var key = (c.dept || FALLBACK.dept) + "|" + statusOf(c); cell[key] = (cell[key] || 0) + 1; });
        var cols = STATUS_ORDER.filter(function (s) { return depts.some(function (d) { return cell[d + "|" + s]; }); });
        heat($("dpHeat"), depts, cols, function (r, c) { return cell[r + "|" + c] || 0; }, C[0],
             function (r, c) { setDrill("dept", { key: "cell", field: "dept", value: r, status: c }); },
             function (r, c) { var d = drill.dept; return !!(d && d.key === "cell" && d.field === "dept" && d.value === r && d.status === c); },
             function (c) { return STATUS_TEXT[c] || c; });
    }

    /* ---------- buyers & requesters -------------------------------------- */

    function peopleStats(cases, key) {
        var thirty = M.addDays(TODAY, -30), twelve = M.addDays(TODAY, -84);
        var map = {};
        cases.forEach(function (c) {
            var n = c[key] || FALLBACK[key];
            if (!map[n]) map[n] = { name: n, open: 0, closed30: 0, late: 0, risk: 0, judged: 0, onTime: 0, ages: [], value: 0, tat: { "On track": 0, "At risk": 0, "Delayed": 0, "Clock not started": 0 } };
            var p = map[n];
            if (M.isOpen(c)) { p.open++; p.value += Number(c.value_inr || 0); if (c.age !== null) p.ages.push(c.age); if (c.tat) p.tat[c.tat]++; if (c.tat === "Delayed") p.late++; if (c.tat === "At risk") p.risk++; }
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

    function renderPeople(cases) {
        var key = piv.who, who = LABEL[key], people = peopleStats(cases, key);
        var shown = people.filter(function (p) { return p.open || p.closed30; }).slice(0, 12);
        $("ppNote").textContent = people.length + " " + who.toLowerCase() + "s in this selection · click a card or a bar to see their cases";
        $("ppLoadTitle").textContent = "Open and closed per " + who.toLowerCase();
        $("ppTatTitle").textContent = "TAT health per " + who.toLowerCase();

        $("ppCards").innerHTML = shown.map(function (p, i) {
            var total = p.open || 1;
            var on = drill.people && drill.people.key === key && drill.people.value === p.name;
            return '<button type="button" class="ad-pc' + (on ? " on" : "") + '" style="--acc:' + C[i % C.length] + '" data-name="' + esc(p.name) + '">' +
                '<div class="ad-pc__top"><span class="ad-pc__av">' + esc(initials(p.name)) + '</span><div><div class="ad-pc__name">' + esc(p.name) + '</div><div class="ad-pc__sub">' + p.open + " open · " + p.closed30 + " closed in 30 days · " + lakhs(p.value) + "</div></div></div>" +
                '<div class="ad-pc__row"><div><span>Overdue</span><b>' + p.late + "</b></div><div><span>At risk</span><b>" + p.risk + "</b></div><div><span>On time</span><b>" + (p.onTimePct === null ? "—" : p.onTimePct + "%") + "</b></div></div>" +
                '<div class="ad-pc__bar" title="' + M.TAT_STATES.map(function (s) { return s + ": " + p.tat[s]; }).join(" · ") + '">' +
                M.TAT_STATES.map(function (s) { return p.tat[s] ? '<i style="width:' + (p.tat[s] * 100 / total) + "%;background:" + ST[s] + '"></i>' : ""; }).join("") + "</div></button>";
        }).join("") || '<p class="ad-empty">No ' + who.toLowerCase() + "s with cases in this selection.</p>";
        Array.prototype.forEach.call($("ppCards").querySelectorAll(".ad-pc"), function (b) {
            b.addEventListener("click", function () { setDrill("people", { key: key, value: b.getAttribute("data-name") }); });
        });

        var labels = shown.map(function (p) { return p.name; });
        draw("ppLoad", {
            type: "bar",
            data: { labels: labels, datasets: [
                { label: "Open now", data: shown.map(function (p) { return p.open; }), backgroundColor: grad("ppLoad", C[0], .95, .55), borderRadius: 5, maxBarThickness: 34 },
                { label: "Closed, last 30 days", data: shown.map(function (p) { return p.closed30; }), backgroundColor: grad("ppLoad", C[4], .95, .55), borderRadius: 5, maxBarThickness: 34 }
            ] },
            options: { responsive: true, maintainAspectRatio: false, layout: { padding: { top: 14 } }, plugins: { legend: { position: "top", align: "end" } },
                       scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } }, x: { grid: { display: false }, ticks: { color: INK } } },
                       onClick: function (evt, els) { if (els.length) setDrill("people", { key: key, value: labels[els[0].index] }); } },
            plugins: [barLabels(null)],
            emptyText: "Nobody has cases in this selection"
        });

        // Profile: the three busiest, five measures each scaled to the
        // largest value on that measure across everyone shown.
        var top3 = shown.slice(0, 3);
        var axes = [["Open load", "open"], ["Closed 30d", "closed30"], ["On time %", "onTimePct"], ["Overdue", "late"], ["Avg age", "avgAge"]];
        var maxes = {};
        axes.forEach(function (a) { maxes[a[1]] = Math.max.apply(null, shown.map(function (p) { return Number(p[a[1]] || 0); })) || 1; });
        draw("ppRadar", {
            type: "radar",
            data: { labels: axes.map(function (a) { return a[0]; }),
                    datasets: top3.map(function (p, i) {
                        return { label: p.name, data: axes.map(function (a) { return Math.round(Number(p[a[1]] || 0) * 100 / maxes[a[1]]); }),
                                 borderColor: C[i], backgroundColor: hexA(C[i], .18), pointBackgroundColor: C[i], pointBorderColor: SURFACE, pointRadius: 4, borderWidth: 2 };
                    }) },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false },
                       tooltip: { callbacks: { label: function (ctx) { var p = top3[ctx.datasetIndex], a = axes[ctx.dataIndex][1]; var v = p[a]; return " " + ctx.dataset.label + ": " + (a === "onTimePct" ? (v === null ? "—" : v + "%") : a === "avgAge" ? v.toFixed(1) + " days" : v); } } } },
                       scales: { r: { min: 0, max: 100, ticks: { display: false, stepSize: 25 }, grid: { color: GRID }, angleLines: { color: GRID }, pointLabels: { color: INK, font: { size: 12 } } } } },
            emptyText: "Nobody to profile in this selection"
        });
        $("ppRadarSub").textContent = top3.length ? "The " + (top3.length === 1 ? "busiest" : top3.length + " busiest") + " " + who.toLowerCase() + (top3.length === 1 ? "" : "s") + ", each measure scaled to the largest among them" : "";
        legendInto($("ppRadarLegend"), top3.map(function (p, i) { return { label: p.name, color: C[i] }; }));

        hbars($("ppUnits"), hbarRows(cases, key), key,
              function (name) { setDrill("people", { key: key, value: name }); },
              function (name, st) { setDrill("people", { key: "cell", field: key, value: name, status: st }); },
              drill.people);
        legendInto($("ppTatLegend"), M.TAT_STATES.map(function (s) { return { label: s, color: ST[s] }; }));
    }

    /* ---------- suppliers & single sourcing ---------------------------- */

    function renderSuppliers(cases) {
        var withOffers = cases.filter(function (c) { return c.offers > 0; });
        var single = withOffers.filter(function (c) { return c.single; });
        var sups = groupsFor(withOffers, "supplier").filter(function (g) { return g.name !== FALLBACK.supplier; });
        sups.forEach(function (g) { g.only = g.cases.filter(function (c) { return c.single; }).length; });
        var topOnly = sups.slice().sort(function (a, b) { return b.only - a.only || b.count - a.count; })[0];
        tiles("spTiles", [
            { icon: "users", acc: C[0], t: "Suppliers quoting", v: sups.length, s: "On " + withOffers.length + " cases with quotations" },
            { icon: "one", acc: C[1], t: "Single-sourced cases", v: single.length, s: withOffers.length ? pct(single.length, withOffers.length) + "% of cases with quotations · click to list them" : "No quotations yet",
              go: function () { setDrill("suppliers", { key: "single" }); } },
            { icon: "star", acc: C[3], t: "Most frequent sole bidder", v: topOnly && topOnly.only ? topOnly.name : "—", s: topOnly && topOnly.only ? "Only bidder on " + topOnly.only + " of " + topOnly.count : "Everyone was in competition" },
            { icon: "cart", acc: C[5], t: "Single-sourced value", v: lakhs(single.reduce(function (s, c) { return s + (c.value_inr || 0); }, 0)), s: "Awarded or pending without competition" }
        ]);

        // The map: one bubble per supplier. Emphasis, not categories - the
        // ones who were ever the sole bidder in orange, the rest in grey.
        var pts = sups.map(function (g) { return { x: g.count, y: lakh(g.value), r: 7 + g.only * 5, name: g.name, only: g.only, cases: g.count, value: g.value }; });
        var labelTop = { id: "bubbleLabels", afterDatasetsDraw: function (chart) {
            var ctx = chart.ctx, meta = chart.getDatasetMeta(0);
            ctx.save(); ctx.font = "600 11px " + FONT; ctx.fillStyle = INK; ctx.textAlign = "center"; ctx.textBaseline = "bottom";
            meta.data.forEach(function (el, i) { var p = pts[i]; if (p.only) ctx.fillText(first(p.name), el.x, el.y - el.options.radius - 4); });
            ctx.restore();
        } };
        draw("spBubble", {
            type: "bubble",
            data: { datasets: [{ label: "Suppliers", data: pts,
                                 backgroundColor: pts.map(function (p) { return p.only ? hexA(C[1], .75) : hexA(GREY, .45); }),
                                 borderColor: pts.map(function (p) { return p.only ? C[1] : GREY; }), borderWidth: 1.5, hoverBorderWidth: 2 }] },
            options: { responsive: true, maintainAspectRatio: false,
                       plugins: { legend: { display: false }, tooltip: { callbacks: {
                           title: function (items) { return items[0].raw.name; },
                           label: function (ctx) { var p = ctx.raw; return [" Quoted on " + p.cases + " case" + (p.cases === 1 ? "" : "s"), " " + lakhs(p.value) + " quoted", p.only ? " Only bidder on " + p.only : " Always in competition"]; } } } },
                       scales: { x: { title: { display: true, text: "Cases quoted on", color: INK2 }, beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } },
                                 y: { title: { display: true, text: "Value quoted, ₹ lakh", color: INK2 }, beginAtZero: true, grid: { color: GRID } } },
                       onClick: function (evt, els) { if (els.length) setDrill("suppliers", { key: "supplier", value: pts[els[0].index].name }); } },
            plugins: [labelTop],
            emptyText: "No quotations in this selection"
        });
        legendInto($("spBubbleLegend"), [{ label: "Was the only bidder at least once", color: C[1] }, { label: "Always in competition", color: GREY }]);

        // Share bars.
        var totals = {};
        groupsFor(withOffers, piv.sp).forEach(function (g) { totals[g.name] = g.count; });
        var sg = groupsFor(single, piv.sp).slice(0, 10).map(function (g) { g.share = pct(g.count, totals[g.name] || g.count); g.total = totals[g.name] || g.count; return g; });
        $("spShareSub").textContent = piv.sp === "dept" ? "Share of each department's quoted cases that had one bidder" : "How often each supplier was the only bidder, out of the cases they quoted on";
        var sk = piv.sp === "dept" ? "sdept" : "ssup";
        bars($("spShare"), sg, { share: true, active: drill.suppliers && drill.suppliers.key === sk ? drill.suppliers.value : null,
                                 onPick: function (name) { setDrill("suppliers", { key: sk, value: name }); },
                                 sub: function (g) { return "of " + g.total; },
                                 empty: withOffers.length ? "Every case in this selection had at least two bidders." : "No quotations in this selection yet." });
        $("spShareHint").textContent = single.length ? single.length + " of " + withOffers.length + " cases with quotations had a single bidder (" + pct(single.length, withOffers.length) + "%)." : "";

        // Who single-sources from whom.
        var depts = groupsFor(single, "dept").map(function (g) { return g.name; });
        var cols = groupsFor(single, "supplier").map(function (g) { return g.name; });
        var cell = {};
        single.forEach(function (c) { c.suppliers.forEach(function (s) { var k2 = (c.dept || FALLBACK.dept) + "|" + s; cell[k2] = (cell[k2] || 0) + 1; }); });
        heat($("spHeat"), depts, cols, function (r, c) { return cell[r + "|" + c] || 0; }, C[1],
             function (r, c) { setDrill("suppliers", { key: "scell", dept: r, supplier: c }); },
             function (r, c) { var d = drill.suppliers; return !!(d && d.key === "scell" && d.dept === r && d.supplier === c); },
             function (c) { return c.split(" ").slice(0, 2).join(" "); });
    }

    /* ---------- TAT & timeline --------------------------------------------- */

    function renderTat(cases) {
        var k = M.kpis(cases, CFG.today), open = cases.filter(M.isOpen);
        tiles("ttTiles", [
            { icon: "tick", acc: ST["On track"], t: "On track", v: k.onTrack, s: "More than 5 working days left" },
            { icon: "risk", acc: ST["At risk"], t: "At risk", v: k.atRisk, s: "Due within 5 working days" },
            { icon: "bang", acc: ST.Delayed, t: "Overdue", v: k.delayed, s: "Past the committed PO date" },
            { icon: "pause", acc: GREY, t: "Clock not started", v: k.notStarted, s: "Document set not yet checked" }
        ]);

        // The headline ratio, overall and per commitment, as gauges.
        var split = tatSplit(cases);
        var gauges = [
            { id: "ttG0", t: "All POs", d: split.all, s: "Every PO released against a committed date" },
            { id: "ttG1", t: "15 working days", d: split.b15, s: "Topics up to \u20b93.5 lakh" },
            { id: "ttG2", t: "30 working days", d: split.b30, s: "Topics up to \u20b940 lakh" }
        ];
        if (split.other.n) gauges.push({ id: "ttG3", t: "Other commitments", d: split.other, s: "Buyer-set TAT outside the two bands" });
        $("ttGauges").innerHTML = gauges.map(function (g) {
            return '<div class="ad-gauge"><div class="ad-gauge__cv"><canvas id="' + g.id + '"></canvas></div>' +
                "<b>" + esc(g.t) + "</b><span>" + (g.d.n ? g.d.ok + " of " + g.d.n + " PO" + (g.d.n === 1 ? "" : "s") + " on time" : "No POs yet") + "</span><small>" + esc(g.s) + "</small></div>";
        }).join("");
        gauges.forEach(function (g) {
            var p = g.d.pct, colour = p === null ? GREY : p >= 80 ? ST["On track"] : p >= 60 ? ST["At risk"] : ST.Delayed;
            var text = { id: "gaugeText", afterDraw: function (chart) {
                var a = chart.chartArea, ctx = chart.ctx;
                ctx.save(); ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
                ctx.fillStyle = INK; ctx.font = "700 26px " + FONT; ctx.fillText(p === null ? "\u2014" : p + "%", (a.left + a.right) / 2, a.bottom - 4);
                ctx.restore();
            } };
            draw(g.id, {
                type: "doughnut",
                data: { datasets: [{ data: [p === null ? 0 : p, p === null ? 100 : 100 - p],
                                     backgroundColor: [grad(g.id, colour, 1, .55, true), "rgba(11,43,58,.07)"], borderWidth: 0, borderRadius: 8 }] },
                options: { responsive: true, maintainAspectRatio: false, circumference: 180, rotation: 270, cutout: "70%",
                           plugins: { legend: { display: false }, tooltip: { enabled: false } }, events: [] },
                plugins: [text]
            });
        });
        $("ttGaugeNote").textContent = split.all.n ? "Target 80%" : "";

        // Month by month: each month is a column to 100%, filled to that
        // month's share and coloured by band, with the count it rests on
        // under the label and the 80% line the team works to.
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
        draw("ttTrend", {
            type: "bar",
            data: { labels: months.map(function (m, i) { return [first(m.label), judged[i] ? judged[i] + (judged[i] === 1 ? " case" : " cases") : "none closed"]; }),
                    datasets: [
                        { label: "Within TAT", data: months.map(function (m) { return m.withinTat; }),
                          backgroundColor: months.map(function (m) { return grad("ttTrend", band(m.withinTat), 1, .55); }), borderRadius: 7, maxBarThickness: 48, stack: "s" },
                        { label: "Remaining", data: months.map(function (m) { return m.withinTat === null ? null : 100 - m.withinTat; }),
                          backgroundColor: "rgba(11,43,58,.06)", borderRadius: 7, maxBarThickness: 48, stack: "s" }
                    ] },
            options: { responsive: true, maintainAspectRatio: false, layout: { padding: { top: 18 } },
                       plugins: { legend: { display: false }, tooltip: { filter: function (i) { return i.datasetIndex === 0; }, callbacks: { label: function (ctx) {
                           var n = judged[ctx.dataIndex]; if (!n) return " Nothing closed against a due date"; var p = ctx.parsed.y; return " " + p + "% \u2014 " + Math.round(p * n / 100) + " of " + n + " met the committed date"; } } } },
                       scales: { y: { stacked: true, beginAtZero: true, max: 100, ticks: { callback: function (v) { return v + "%"; }, stepSize: 25 }, grid: { color: GRID } },
                                 x: { stacked: true, grid: { display: false }, ticks: { color: INK } } },
                       onClick: function (evt, els) { if (els.length) setDrill("tat", { key: "month", value: months[els[0].index].key }); } },
            plugins: [target, barLabels(function (v) { return v + "%"; }, false, true, 0)],
            emptyText: "Nothing has closed against a due date yet"
        });

        // Age: how many open cases sit in each band, with the shape of the
        // distribution drawn through the tops.
        var counts = AGE_BUCKETS.map(function (b) { return open.filter(function (c) { return c.bucket === b[0]; }).length; });
        draw("ttAge", {
            type: "bar",
            data: { labels: AGE_BUCKETS.map(function (b) { return b[0]; }),
                    datasets: [
                        { type: "line", label: "Shape", data: counts, borderColor: hexA(C[0], .55), borderWidth: 2, tension: .4, pointRadius: 0, fill: false, order: 0 },
                        { label: "Open cases", data: counts, backgroundColor: SEQ.map(function (h) { return grad("ttAge", h, 1, .6); }), borderRadius: 8, maxBarThickness: 64, order: 1 }
                    ] },
            options: { responsive: true, maintainAspectRatio: false, layout: { padding: { top: 18 } }, plugins: { legend: { display: false }, tooltip: { filter: function (i) { return i.datasetIndex === 1; } } },
                       scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } }, x: { grid: { display: false }, ticks: { color: INK } } },
                       onClick: function (evt, els) { var hit = els.filter(function (e) { return e.datasetIndex === 1; })[0] || els[0]; if (hit) setDrill("tat", { key: "age", value: AGE_BUCKETS[hit.index][0] }); } },
            plugins: [barLabels(null, false, false, 1)],
            emptyText: "No open cases in this selection"
        });

        // Month balance: the open count as a line over the raised / closed bars.
        draw("ttMonth", {
            type: "bar",
            data: { labels: months.map(function (m) { return first(m.label); }), datasets: [
                { type: "line", label: "Open at month end", data: months.map(function (m) { return m.openAtEnd; }), borderColor: C[5], backgroundColor: grad("ttMonth", C[5], .28, .02),
                  fill: true, tension: .4, borderWidth: 2.5, pointRadius: 4, pointBackgroundColor: C[5], pointBorderColor: SURFACE, pointBorderWidth: 2, order: 0 },
                { label: "Raised", data: months.map(function (m) { return m.incoming; }), backgroundColor: grad("ttMonth", C[0], .9, .45), borderRadius: 5, maxBarThickness: 26, order: 1 },
                { label: "Closed", data: months.map(function (m) { return m.closed; }), backgroundColor: grad("ttMonth", C[4], .9, .45), borderRadius: 5, maxBarThickness: 26, order: 1 }
            ] },
            options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { position: "top", align: "end" } },
                       scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: GRID } }, x: { grid: { display: false }, ticks: { color: INK } } } },
            emptyText: "Not enough history yet"
        });
        var partial = months.filter(function (m) { return m.partial; })[0];
        $("ttMonthNote").textContent = partial ? first(partial.label) + " is up to today" : "";
        $("ttMonthTable").innerHTML = "<thead><tr><th>Month</th><th class=\"num\">Open at start</th><th class=\"num\">Raised</th><th class=\"num\">Closed</th><th class=\"num\">Open at end</th><th class=\"num\">Within TAT</th></tr></thead><tbody>" +
            months.map(function (m, i) {
                var start = i ? months[i - 1].openAtEnd : Math.max(m.openAtEnd - m.incoming + m.closed, 0);
                var tone = m.withinTat === null ? "muted" : m.withinTat >= 80 ? "ok" : m.withinTat >= 60 ? "warn" : "bad";
                return "<tr><td><b>" + esc(first(m.label)) + "</b>" + (m.partial ? ' <span class="ad-muted">to date</span>' : "") + '</td><td class="num">' + start + '</td><td class="num">' + m.incoming + '</td><td class="num">' + m.closed + '</td><td class="num"><b>' + m.openAtEnd + '</b></td><td class="num"><span class="pill pill--' + tone + '">' + (m.withinTat === null ? "—" : m.withinTat + "%") + "</span></td></tr>";
            }).join("") + "</tbody>";
    }

    /* ---------- export ------------------------------------------------------ */

    var LIST_OPTS = {
        overview: { title: "Cases" },
        dept: { title: "Cases by department", extraKey: "dept" },
        people: { title: "Cases", extraKey: "buyer" },
        suppliers: { title: "Cases with suppliers", extraKey: "supplier" },
        tat: { title: "Cases by urgency" }
    };

    $("adExport").addEventListener("click", function () {
        var opts = LIST_OPTS[tab];
        var rows = sorted(listed(tab, opts.extraKey), lists[tab].sort);
        var sheet = rows.map(function (c) {
            return { "Shopping cart": c.sc || c.id, "Ticket": c.id, "Topic": c.topic, "Department": c.dept, "Commodity": c.comm, "Requester": c.requester, "Buyer": c.buyer,
                     "Status": STATUS_TEXT[statusOf(c)] || statusOf(c), "Suppliers quoted": c.suppliers.join("; "), "Number of quotations": c.offers, "Single sourced": c.single ? "Yes" : "No", "Basis": c.basis,
                     "TAT (working days)": c.tat_days || "", "Age (days)": c.age === null ? "" : c.age, "Working days left": c.daysLeft === null ? "" : c.daysLeft,
                     "Value (INR)": c.value_inr, "Currency": c.ccy, "Value (as documented)": c.value, "Created": c.sub ? M.iso(c.sub) : "", "Documents complete": c.docs || "",
                     "PO due": c.po ? M.iso(c.po) : "", "Closed": c.closed ? M.iso(c.closed) : "", "PO number": c.po_no || "" };
        });
        var slice = railed(), k = M.kpis(slice, CFG.today), split = tatSplit(slice);
        var summary = [{ Measure: "As of", Value: M.iso(TODAY) }, { Measure: "Tab", Value: tab }];
        RAIL.forEach(function (key) { summary.push({ Measure: LABEL[key], Value: f[key] === "all" ? "All" : f[key] }); });
        summary.push({ Measure: "Single sourcing only", Value: f.single ? "Yes" : "No" }, { Measure: "List filter", Value: drillLabel(drill[tab]) || "None" },
                     { Measure: "Open cases", Value: k.open }, { Measure: "Overdue", Value: k.delayed }, { Measure: "At risk", Value: k.atRisk },
                     { Measure: "Single-sourced cases", Value: slice.filter(function (c) { return c.single; }).length },
                     { Measure: "Within TAT, all POs", Value: split.all.pct === null ? "n/a" : split.all.pct + "% (" + split.all.ok + " of " + split.all.n + ")" },
                     { Measure: "Within TAT, 15-day", Value: split.b15.pct === null ? "n/a" : split.b15.pct + "% (" + split.b15.ok + " of " + split.b15.n + ")" },
                     { Measure: "Within TAT, 30-day", Value: split.b30.pct === null ? "n/a" : split.b30.pct + "% (" + split.b30.ok + " of " + split.b30.n + ")" });
        window.DashExport.run({ filename: "purchase-dashboard-" + tab + "-" + M.iso(TODAY) + ".xlsx", button: $("adExport"), charts: charts,
                                sheets: [{ name: "Cases", rows: sheet }, { name: "Summary", rows: summary }] });
    });

    /* ---------- main ------------------------------------------------------ */

    function render() {
        renderRail();
        Array.prototype.forEach.call($("adTabs").querySelectorAll("button"), function (b) { b.classList.toggle("on", b.getAttribute("data-t") === tab); });
        TABS.forEach(function (t) { $("t-" + t).classList.toggle("on", t === tab); });
        var slice = railed();
        if (tab === "overview") renderOverview(slice);
        else if (tab === "dept") renderDept(slice);
        else if (tab === "people") renderPeople(slice);
        else if (tab === "suppliers") renderSuppliers(slice);
        else if (tab === "tat") renderTat(slice);
        var opts = LIST_OPTS[tab];
        if (tab === "people") opts = { title: "Cases", extraKey: piv.who };
        list(tab, opts);
    }

    render();
}());
