/* Requester dashboard: "where are my requests, and is anything waiting on
   me?". Stats, a status donut, the things Procurement is blocked on, and the
   full list with search / filter / sort / paging - all client-side off one
   JSON payload, so every control responds instantly.

   Statuses are the requester-facing wording of Samagra's real states (see
   dashboard.py). There is deliberately no "Comparing offers" stage - the app
   has no way to be in one. */
(function () {
    var CFG = window.SAMAGRA_RQ || {};
    var raw = document.getElementById("dashData");
    var CASES = raw ? JSON.parse(raw.textContent) : [];

    CASES.forEach(function (c) {
        c.sub = c.sub ? new Date(c.sub + "T00:00:00") : null;
        c.po = c.po ? new Date(c.po + "T00:00:00") : null;
        c.closed = c.closed ? new Date(c.closed + "T00:00:00") : null;
    });

    var TODAY = new Date(CFG.today + "T00:00:00");
    var ORDER = ["Submitted", "Procurement reviewing", "Waiting for my response",
        "PO released", "Not approved"];
    var COLOR = {
        "Submitted": "#c9cfd9",
        "Procurement reviewing": "#93c5fd",
        "Waiting for my response": "#f0b429",
        "PO released": "#6ccf9e",
        "Not approved": "#ef8a8a"
    };
    var CHIP = {
        "Submitted": "c-g",
        "Procurement reviewing": "c-b",
        "Waiting for my response": "c-a",
        "PO released": "c-t",
        "Not approved": "c-red"
    };
    var OPEN = ["Submitted", "Procurement reviewing", "Waiting for my response"];

    /* ---------- helpers ---------- */
    function inr(n) {
        var s = Math.round(n || 0).toString();
        if (s.length <= 3) return "₹" + s;
        return "₹" + s.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + s.slice(-3);
    }
    function fmt(dt) { return dt ? dt.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—"; }
    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"]/g, function (ch) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
        });
    }
    function statusOf(c) { return c.rstatus || c.status; }

    /* ---------- greeting ---------- */
    // First name only - "Good morning, Vedanti" is the warm version;
    // the full legal name reads like a system notice.
    var firstName = String(CFG.userName || "there").trim().split(/\s+/)[0];
    var hour = new Date().getHours();
    var sun = '<svg width="26" height="26" viewBox="0 0 24 24" fill="#f0b429" aria-hidden="true">' +
        '<circle cx="12" cy="12" r="5"></circle>' +
        '<g stroke="#f0b429" stroke-width="2" stroke-linecap="round">' +
        '<path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>' +
        "</g></svg>";
    document.getElementById("greet").innerHTML =
        esc((hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening") + ", " + firstName) + " " + sun;
    document.getElementById("dateBar").innerHTML =
        esc(TODAY.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })) +
        "<span>|</span>Track your sourcing requests and see what needs your attention";

    // Greeting is rendered above this point on purpose: a requester with no
    // requests yet should still be welcomed by name, not shown a blank header.
    var dashBody = document.getElementById("dashBody");
    var noData = document.getElementById("noData");
    if (!CASES.length) {
        if (noData) noData.hidden = false;
        if (dashBody) dashBody.hidden = true;
        return;
    }

    /* ---------- state ---------- */
    var statusF = null;   // set by KPI tile, donut slice or legend click
    var page = 1;
    var PER_PAGE = 10;

    var qEl = document.getElementById("q");
    var fStatus = document.getElementById("fStatus");
    var fSort = document.getElementById("fSort");

    fStatus.innerHTML = '<option value="all">All</option>' +
        ORDER.filter(function (s) { return CASES.some(function (c) { return statusOf(c) === s; }); })
            .map(function (s) { return '<option value="' + esc(s) + '">' + esc(s) + "</option>"; }).join("");

    [qEl, fStatus, fSort].forEach(function (el) {
        el.addEventListener("input", function () {
            if (el === fStatus) statusF = fStatus.value === "all" ? null : fStatus.value;
            page = 1;
            render();
        });
    });

    function visible() {
        var needle = (qEl.value || "").trim().toLowerCase();
        var rows = CASES.filter(function (c) {
            if (statusF && statusOf(c) !== statusF) return false;
            if (!needle) return true;
            return (c.topic || "").toLowerCase().indexOf(needle) !== -1
                || (c.id || "").toLowerCase().indexOf(needle) !== -1;
        });
        var mode = fSort.value;
        rows.sort(function (a, b) {
            if (mode === "old") return (a.sub || 0) - (b.sub || 0);
            if (mode === "value") return b.value - a.value;
            if (mode === "due") {
                // Requests with no expected date sort last rather than first -
                // "no date yet" is not "due soonest".
                if (!a.po && !b.po) return 0;
                if (!a.po) return 1;
                if (!b.po) return -1;
                return a.po - b.po;
            }
            return (b.sub || 0) - (a.sub || 0);
        });
        return rows;
    }

    /* ---------- charts ---------- */
    Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
    Chart.defaults.color = "#4b5563";
    Chart.defaults.plugins.legend.display = false;
    var donut = null;

    function render() {
        /* ---- KPI tiles (each one filters the list) ---- */
        var total = CASES.length;
        var inProgress = CASES.filter(function (c) {
            return statusOf(c) === "Submitted" || statusOf(c) === "Procurement reviewing";
        }).length;
        var needAction = CASES.filter(function (c) { return statusOf(c) === "Waiting for my response"; }).length;
        var completed = CASES.filter(function (c) { return statusOf(c) === "PO released"; }).length;

        var tiles = [
            { key: null, t: "Requests raised", v: total, s: "everything you have submitted" },
            { key: "Procurement reviewing", t: "In progress", v: inProgress, s: "being processed by procurement" },
            { key: "Waiting for my response", t: "Need my action", v: needAction, s: needAction ? "waiting on your reply" : "nothing waiting on you", tone: needAction ? "warn" : "" },
            { key: "PO released", t: "Completed", v: completed, s: "PO released" }
        ];
        document.getElementById("kpis").innerHTML = tiles.map(function (k) {
            var on = (k.key === statusF) || (k.key === null && statusF === null);
            return '<button type="button" class="sf-rq-kpi ' + (k.tone || "") + (on ? " on" : "") +
                '" data-k="' + esc(k.key == null ? "" : k.key) + '">' +
                '<div class="t">' + k.t + '</div><div class="v">' + k.v + '</div><div class="s">' + k.s + "</div></button>";
        }).join("");
        Array.prototype.forEach.call(document.querySelectorAll("[data-k]"), function (b) {
            b.onclick = function () {
                var k = b.dataset.k || null;
                statusF = (k && statusF === k) ? null : k;
                fStatus.value = statusF || "all";
                page = 1;
                render();
            };
        });

        /* ---- status donut ---- */
        var present = ORDER.filter(function (s) { return CASES.some(function (c) { return statusOf(c) === s; }); });
        var counts = present.map(function (s) { return CASES.filter(function (c) { return statusOf(c) === s; }).length; });
        if (donut) donut.destroy();
        donut = new Chart(document.getElementById("cStatus"), {
            type: "doughnut",
            data: {
                labels: present,
                datasets: [{
                    data: counts,
                    backgroundColor: present.map(function (s) { return COLOR[s]; }),
                    borderWidth: 3, borderColor: "#fff", hoverOffset: 8,
                    offset: present.map(function (s) { return s === statusF ? 12 : 0; })
                }]
            },
            options: {
                cutout: "62%", maintainAspectRatio: false,
                onHover: function (e, el) { e.native.target.style.cursor = el.length ? "pointer" : "default"; },
                onClick: function (e, el) {
                    if (!el.length) return;
                    var s = present[el[0].index];
                    statusF = statusF === s ? null : s;
                    fStatus.value = statusF || "all";
                    page = 1;
                    render();
                },
                plugins: { tooltip: { callbacks: { label: function (t) { return " " + t.label + ": " + t.raw; } } } }
            },
            plugins: [{
                id: "centre",
                afterDraw: function (ch) {
                    var ctx = ch.ctx, a = ch.chartArea;
                    ctx.save(); ctx.textAlign = "center";
                    ctx.fillStyle = "#1a1f2b"; ctx.font = '600 28px "Segoe UI", sans-serif';
                    ctx.fillText(CASES.length, (a.left + a.right) / 2, (a.top + a.bottom) / 2 + 2);
                    ctx.font = '12px "Segoe UI", sans-serif'; ctx.fillStyle = "#8a929c";
                    ctx.fillText("requests", (a.left + a.right) / 2, (a.top + a.bottom) / 2 + 20);
                    ctx.restore();
                }
            }]
        });

        var legend = document.getElementById("statusLegend");
        legend.innerHTML = present.map(function (s, i) {
            return '<button type="button" class="' + (statusF === s ? "on" : "") + '" data-s="' + esc(s) + '">' +
                '<i style="background:' + COLOR[s] + '"></i>' + esc(s) + " <b>" + counts[i] + "</b></button>";
        }).join("");
        Array.prototype.forEach.call(legend.querySelectorAll("[data-s]"), function (b) {
            b.onclick = function () {
                statusF = statusF === b.dataset.s ? null : b.dataset.s;
                fStatus.value = statusF || "all";
                page = 1;
                render();
            };
        });

        /* ---- needs your action ---- */
        var waiting = CASES.filter(function (c) { return statusOf(c) === "Waiting for my response"; });
        document.getElementById("actionList").innerHTML = waiting.length
            ? waiting.map(function (c) {
                return '<a class="sf-rq-action" href="' + CFG.caseUrlBase + c.case_id + '">' +
                    '<div><div class="nm">' + esc(c.topic) + "</div>" +
                    '<div class="sub">' + esc(c.id) + " · raised " + fmt(c.sub) + "</div></div>" +
                    '<span class="sf-dash-rowbtn">Respond</span></a>';
            }).join("")
            : '<div class="sf-rq-allclear">Nothing needs your action right now.</div>';

        renderTable();
    }

    /* ---------- the list ---------- */
    function renderTable() {
        var rows = visible();
        var pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
        if (page > pages) page = pages;
        var slice = rows.slice((page - 1) * PER_PAGE, page * PER_PAGE);

        document.getElementById("totalCount").textContent = CASES.length;
        document.getElementById("shownCount").textContent =
            rows.length === CASES.length ? rows.length + " shown" : rows.length + " of " + CASES.length + " shown";

        var tbl = document.getElementById("rqTable");
        if (!rows.length) {
            tbl.innerHTML = '<tbody><tr><td class="sf-dash-empty">No requests match this filter.</td></tr></tbody>';
        } else {
            tbl.innerHTML = "<thead><tr><th>Request</th><th>Request ID</th><th>Status</th>" +
                "<th class='num'>Value</th><th>Submitted</th><th>Procurement owner</th>" +
                "<th>PO expected</th><th></th></tr></thead><tbody>" +
                slice.map(function (c) {
                    var st = statusOf(c);
                    // Once a PO is released the expected date is history - show
                    // when it actually landed instead of a stale target.
                    var poCell = st === "PO released"
                        ? (c.closed ? "released " + fmt(c.closed) : "released")
                        : (c.po ? fmt(c.po) : '<span class="sf-rq-muted">not set yet</span>');
                    return "<tr>" +
                        '<td><a href="' + CFG.caseUrlBase + c.case_id + '">' + esc(c.topic) + "</a></td>" +
                        '<td class="sf-rq-muted">' + esc(c.id) + "</td>" +
                        '<td><span class="sf-dash-chip ' + CHIP[st] + '">' + esc(st) + "</span></td>" +
                        '<td class="num">' + inr(c.value) + "</td>" +
                        "<td>" + fmt(c.sub) + "</td>" +
                        "<td>" + (c.buyer ? esc(c.buyer) : '<span class="sf-rq-muted">not assigned</span>') + "</td>" +
                        "<td>" + poCell + "</td>" +
                        '<td><a class="sf-dash-rowbtn" href="' + CFG.caseUrlBase + c.case_id + '">View</a></td>' +
                        "</tr>";
                }).join("") + "</tbody>";
        }

        var pager = document.getElementById("pager");
        pager.innerHTML = pages > 1
            ? '<button type="button" id="prev"' + (page === 1 ? " disabled" : "") + ">‹ Prev</button>" +
            "<span>Page " + page + " of " + pages + "</span>" +
            '<button type="button" id="next"' + (page === pages ? " disabled" : "") + ">Next ›</button>"
            : "";
        var prev = document.getElementById("prev"), next = document.getElementById("next");
        if (prev) prev.onclick = function () { if (page > 1) { page--; renderTable(); } };
        if (next) next.onclick = function () { if (page < pages) { page++; renderTable(); } };
    }

    render();
})();
