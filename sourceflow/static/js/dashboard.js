/* Samagra dashboard - a buyer's working cockpit: what's open, what's landing
   this week, and what needs doing today.

   Cases arrive as JSON from dashboard.py (#dashData) with stages already
   mapped to real Samagra states, so nothing here needs to know about the
   SUBMITTED/IN_PROGRESS/ENQUIRED enum. All aggregation is client-side, so
   changing scope never costs a round trip. */
(function () {
    var CFG = window.SAMAGRA_DASH || {};
    var raw = document.getElementById("dashData");
    var CASES = raw ? JSON.parse(raw.textContent) : [];
    var IS_BUYER = CFG.scope === "buyer";

    CASES.forEach(function (c) {
        c.sub = c.sub ? new Date(c.sub + "T00:00:00") : null;
        c.po = c.po ? new Date(c.po + "T00:00:00") : null;
        c.closed = c.closed ? new Date(c.closed + "T00:00:00") : null;
    });

    var TODAY = new Date(CFG.today + "T00:00:00");
    // Only stages Samagra can actually be in - no "Quote comparison" or
    // "Ready for approval", which the app has no way to set.
    var STAGES = ["Unassigned", "In progress", "Waiting on requestor"];
    var COLOR = {
        "Unassigned": "#93c5fd",
        "In progress": "#3b82f6",
        "Waiting on requestor": "#f0b429",
        "Approved": "#0b7a5c",
        "Rejected": "#d9534f"
    };
    var STCLS = {
        "Unassigned": "c-g", "In progress": "c-b", "Waiting on requestor": "c-a",
        "Approved": "c-t", "Rejected": "c-red"
    };

    var dashBody = document.getElementById("dashBody");
    var noData = document.getElementById("noData");
    if (!CASES.length) {
        if (noData) noData.hidden = false;
        if (dashBody) dashBody.hidden = true;
        return;
    }

    /* ---------- helpers ---------- */
    var days = function (a, b) { return Math.round((b - a) / 864e5); };
    function inr(n) {
        var s = Math.round(n).toString();
        if (s.length <= 3) return "₹" + s;
        return "₹" + s.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + s.slice(-3);
    }
    function fmt(dt) { return dt ? dt.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—"; }
    function ageOf(c) { return c.sub ? days(c.sub, TODAY) : 0; }
    function isOpen(c) { return STAGES.indexOf(c.status) !== -1; }
    function isOverdue(c) { return isOpen(c) && c.po && c.po < TODAY; }
    function uniq(a) { return Array.from(new Set(a)).sort(); }
    function esc(s) {
        return String(s == null ? "" : s).replace(/[&<>"]/g, function (ch) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch];
        });
    }

    /* ---------- greeting ---------- */
    var hour = new Date().getHours();
    var sun = '<svg width="26" height="26" viewBox="0 0 24 24" fill="#f0b429" aria-hidden="true">' +
        '<circle cx="12" cy="12" r="5"></circle>' +
        '<g stroke="#f0b429" stroke-width="2" stroke-linecap="round">' +
        '<path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"></path>' +
        "</g></svg>";
    // First name only - warmer, and keeps both dashboards greeting the same way.
    var firstName = String(CFG.userName || "there").trim().split(/\s+/)[0];
    document.getElementById("greet").innerHTML =
        esc((hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening") + ", " + firstName) + " " + sun;
    document.getElementById("dateBar").innerHTML =
        esc(TODAY.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })) +
        "<span>|</span>" + esc(CFG.org || "");

    /* ---------- scope + stage/department filters ---------- */
    var stageF = null;
    var deptF = null;
    var scopeVal = "me";
    var DEPT_KEY = IS_BUYER ? "dept" : "comm";
    // Scope is a two-tab segmented control rather than a dropdown: which set
    // of cases you're looking at changes every number on the page, so it
    // should be readable at a glance instead of hidden behind a closed
    // <select>. Switching scope clears the stage/department drill-down,
    // since a filter chosen against one scope rarely makes sense in the other.
    var scopeTabs = document.querySelectorAll("[data-scope]");
    Array.prototype.forEach.call(scopeTabs, function (tab) {
        tab.addEventListener("click", function () {
            if (tab.classList.contains("is-active")) return;
            scopeVal = tab.getAttribute("data-scope");
            Array.prototype.forEach.call(scopeTabs, function (other) {
                var on = other === tab;
                other.classList.toggle("is-active", on);
                other.setAttribute("aria-selected", on ? "true" : "false");
            });
            stageF = null;
            deptF = null;
            render();
        });
    });

    function scoped() {
        if (!IS_BUYER || scopeVal === "all") return CASES;
        // "My cases" = mine, plus anything unassigned that I could pick up.
        return CASES.filter(function (c) { return c.buyer === CFG.userName || !c.buyer; });
    }

    /* ---------- charts ---------- */
    Chart.defaults.font.family = '"Segoe UI", system-ui, sans-serif';
    Chart.defaults.color = "#4b5563";
    Chart.defaults.plugins.legend.display = false;
    var stageChart = null, deptChart = null;

    /* Fold a long tail into "Others" so the chart stays readable - past
       ~9 rows the labels start colliding and nothing is gained. */
    function groupBy(list, key, limit) {
        var counts = {};
        list.forEach(function (c) {
            var k = c[key] || "Not set";
            counts[k] = (counts[k] || 0) + 1;
        });
        var rows = Object.keys(counts).map(function (k) { return { name: k, n: counts[k] }; })
            .sort(function (a, b) { return b.n - a.n || a.name.localeCompare(b.name); });
        var totalGroups = rows.length;
        if (limit && rows.length > limit + 1) {
            var rest = rows.slice(limit);
            rows = rows.slice(0, limit).concat([{
                name: "Others (" + rest.length + ")",
                n: rest.reduce(function (s, r) { return s + r.n; }, 0),
                isOthers: true,
                members: rest.map(function (r) { return r.name; })
            }]);
        }
        return { rows: rows, totalGroups: totalGroups };
    }

    function render() {
        var all = scoped();
        var open = all.filter(isOpen);

        /* ---- hero status band ---- */
        var newThisWeek = open.filter(function (c) { return ageOf(c) <= 7; }).length;
        document.getElementById("sOpen").textContent = open.length;
        document.getElementById("sSub").innerHTML =
            newThisWeek + " new this week<i>·</i>" +
            inr(open.reduce(function (s, c) { return s + c.value; }, 0)) + " in the queue";

        // On-time rate from real closures only: a case that actually closed,
        // that had an expected PO date to be judged against. With nothing
        // closed yet there is no rate - showing one would be inventing it.
        var judged = all.filter(function (c) { return c.closed && c.po; });
        var pctEl = document.getElementById("sPct"),
            barEl = document.getElementById("sBar"),
            subEl = document.getElementById("sPctSub");
        if (judged.length) {
            var onTime = judged.filter(function (c) { return c.closed <= c.po; }).length;
            var pct = Math.round(onTime / judged.length * 100);
            var avgDays = Math.round(judged.reduce(function (s, c) { return s + days(c.sub, c.closed); }, 0) / judged.length);
            pctEl.textContent = pct + "%";
            barEl.style.width = pct + "%";
            subEl.textContent = "(last " + judged.length + " PO" + (judged.length === 1 ? "" : "s") + " · avg " + avgDays + " days to close)";
        } else {
            pctEl.textContent = "—";
            barEl.style.width = "0%";
            subEl.textContent = "no POs closed yet";
        }

        /* ---- cases by stage ---- */
        var cnt = STAGES.map(function (s) { return open.filter(function (c) { return c.status === s; }).length; });
        if (stageChart) stageChart.destroy();
        stageChart = new Chart(document.getElementById("cStage"), {
            type: "doughnut",
            data: {
                labels: STAGES,
                datasets: [{
                    data: cnt,
                    backgroundColor: STAGES.map(function (s) { return COLOR[s]; }),
                    borderWidth: 3, borderColor: "#fff", hoverOffset: 8,
                    offset: STAGES.map(function (s) { return s === stageF ? 12 : 0; })
                }]
            },
            options: {
                cutout: "55%", maintainAspectRatio: false,
                onHover: function (e, el) { e.native.target.style.cursor = el.length ? "pointer" : "default"; },
                onClick: function (e, el) {
                    if (!el.length) return;
                    var s = STAGES[el[0].index];
                    stageF = stageF === s ? null : s;
                    render();
                },
                plugins: { tooltip: { callbacks: { label: function (t) { return " " + t.label + ": " + t.raw; } } } }
            },
            plugins: [{
                id: "stageLbl",
                afterDraw: function (ch) {
                    var ctx = ch.ctx, meta = ch.getDatasetMeta(0), a = ch.chartArea;
                    ctx.save();
                    ctx.fillStyle = "#fff";
                    ctx.font = '600 15px "Segoe UI", sans-serif';
                    ctx.textAlign = "center"; ctx.textBaseline = "middle";
                    meta.data.forEach(function (arc, i) {
                        if (!cnt[i]) return;
                        var ang = (arc.startAngle + arc.endAngle) / 2;
                        var r = (arc.innerRadius + arc.outerRadius) / 2;
                        ctx.fillText(cnt[i], arc.x + Math.cos(ang) * r, arc.y + Math.sin(ang) * r);
                    });
                    ctx.fillStyle = "#1a1f2b";
                    ctx.font = '600 30px "Segoe UI", sans-serif';
                    ctx.fillText(open.length, (a.left + a.right) / 2, (a.top + a.bottom) / 2 - 8);
                    ctx.font = '13px "Segoe UI", sans-serif';
                    ctx.fillStyle = "#8a929c";
                    ctx.fillText("open cases", (a.left + a.right) / 2, (a.top + a.bottom) / 2 + 14);
                    ctx.restore();
                }
            }]
        });

        var lg = document.getElementById("lg");
        lg.innerHTML = STAGES.map(function (s, i) {
            return '<button type="button" class="' + (stageF === s ? "on" : "") + '" data-s="' + esc(s) + '">' +
                '<i style="background:' + COLOR[s] + '"></i><span>' + esc(s) + "</span><b>" + cnt[i] + "</b></button>";
        }).join("");
        Array.prototype.forEach.call(lg.querySelectorAll("button"), function (b) {
            b.onclick = function () { stageF = stageF === b.dataset.s ? null : b.dataset.s; render(); };
        });

        /* ---- PO due (next 14 days) ---- */
        var due = function (c) { return c.po ? days(TODAY, c.po) : null; };
        var wkEnd = new Date(TODAY); wkEnd.setDate(wkEnd.getDate() + 6);
        var nwS = new Date(wkEnd); nwS.setDate(nwS.getDate() + 1);
        var nwE = new Date(wkEnd); nwE.setDate(nwE.getDate() + 7);
        var groups = [
            ["Overdue", open.filter(function (c) { return due(c) !== null && due(c) < 0; }), "#f26b6b", ""],
            ["This week", open.filter(function (c) { return due(c) >= 0 && due(c) <= 6; }), "#6ccf9e", fmt(TODAY) + " – " + fmt(wkEnd)],
            ["Next week", open.filter(function (c) { return due(c) >= 7 && due(c) <= 13; }), "#6ccf9e", fmt(nwS) + " – " + fmt(nwE)],
            ["Later", open.filter(function (c) { return due(c) > 13; }), "#cfd6de", "After " + fmt(nwE)]
        ];
        var mx = Math.max.apply(null, [1].concat(groups.map(function (g) { return g[1].length; })));
        document.getElementById("bars").innerHTML = groups.map(function (g) {
            return '<div class="sf-dash-bargrp"><span class="n">' + g[1].length + "</span>" +
                '<div class="b" style="height:' + Math.max(6, g[1].length / mx * 110) + "px;background:" + g[2] + '"></div>' +
                '<div class="lbl">' + g[0] + "<small>" + (g[3] || "&nbsp;") + "</small></div></div>";
        }).join("");
        // "Expected", not "confirmed": this date is the document-check date
        // plus the agreed TAT, i.e. a calculated target. No PO has been
        // raised and no supplier has committed to it - calling it confirmed
        // would claim something that hasn't happened.
        var withDate = open.filter(function (c) { return c.po; }).length;
        var withoutDate = open.length - withDate;
        document.getElementById("fA").textContent =
            withDate + " case" + (withDate === 1 ? "" : "s") + " have an expected PO date";
        document.getElementById("fB").innerHTML =
            withoutDate + " still awaiting document check <small>(no date until then)</small>";

        renderDept(all);
        renderTatByDept(all);
        renderAttn(open);
        renderRecords(all);
    }

    /* ---------- cases by department (pie + legend) ---------- */
    var DEPT_COLORS = ["#3b82f6", "#0b7a5c", "#f0b429", "#a855f7", "#2dd4bf",
        "#93c5fd", "#f472b6", "#fb923c", "#cfd6de"];

    function renderDept(all) {
        var g = groupBy(all, DEPT_KEY, 8);
        var rows = g.rows;
        var total = rows.reduce(function (s, r) { return s + r.n; }, 0) || 1;
        document.getElementById("deptCount").textContent =
            all.length + " raised · " + g.totalGroups + (g.totalGroups === 1 ? " department" : " departments");

        if (deptChart) deptChart.destroy();
        deptChart = new Chart(document.getElementById("cDept"), {
            type: "pie",
            data: {
                labels: rows.map(function (r) { return r.name; }),
                datasets: [{
                    data: rows.map(function (r) { return r.n; }),
                    backgroundColor: rows.map(function (r, i) {
                        return r.isOthers ? "#cfd6de" : DEPT_COLORS[i % DEPT_COLORS.length];
                    }),
                    borderWidth: 2, borderColor: "#fff", hoverOffset: 8,
                    offset: rows.map(function (r) { return r.name === deptF ? 12 : 0; })
                }]
            },
            options: {
                maintainAspectRatio: false, animation: { duration: 250 },
                onHover: function (e, el) { e.native.target.style.cursor = el.length ? "pointer" : "default"; },
                onClick: function (e, el) {
                    if (!el.length) return;
                    var r = rows[el[0].index];
                    if (r.isOthers) return;  // synthetic bucket - nothing single to filter to
                    deptF = deptF === r.name ? null : r.name;
                    render();
                },
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function (t) {
                                var r = rows[t.dataIndex];
                                return " " + r.n + " case" + (r.n === 1 ? "" : "s") +
                                    " · " + Math.round(r.n / total * 100) + "%";
                            },
                            footer: function (items) {
                                return rows[items[0].dataIndex].isOthers ? "" : "click to filter the list below";
                            }
                        }
                    }
                }
            }
        });

        var legend = document.getElementById("deptLegend");
        legend.innerHTML = rows.map(function (r, i) {
            var col = r.isOthers ? "#cfd6de" : DEPT_COLORS[i % DEPT_COLORS.length];
            return '<button type="button" class="' + (deptF === r.name ? "on" : "") +
                '" data-g="' + esc(r.name) + '"' + (r.isOthers ? " disabled" : "") + ">" +
                '<i style="background:' + col + '"></i><span>' + esc(r.name) + "</span><b>" + r.n + "</b></button>";
        }).join("");
        Array.prototype.forEach.call(legend.querySelectorAll("button[data-g]:not([disabled])"), function (b) {
            b.onclick = function () {
                deptF = deptF === b.dataset.g ? null : b.dataset.g;
                render();
            };
        });
    }

    /* ---------- TAT performance by department ---------- */
    function renderTatByDept(all) {
        // Only completed cases can be judged against TAT, and only those
        // that had an expected PO date to be judged against.
        var judged = all.filter(function (c) { return c.closed && c.po; });
        var el = document.getElementById("tatList");
        if (!judged.length) {
            el.innerHTML = '<div class="sf-dash-empty">No completed cases yet — this fills in as cases close.</div>';
            return;
        }
        var by = {};
        judged.forEach(function (c) {
            var k = c[DEPT_KEY] || "Not set";
            if (!by[k]) by[k] = { name: k, done: 0, late: 0 };
            by[k].done++;
            if (c.closed > c.po) by[k].late++;
        });
        var rows = Object.keys(by).map(function (k) {
            var r = by[k];
            r.onTime = r.done - r.late;
            r.pct = Math.round(r.onTime / r.done * 100);
            return r;
        }).sort(function (a, b) { return b.pct - a.pct || b.done - a.done; });

        var totalDone = rows.reduce(function (s, r) { return s + r.done; }, 0);
        var totalLate = rows.reduce(function (s, r) { return s + r.late; }, 0);

        el.innerHTML =
            '<div class="sf-dash-tattotals">' +
            '<span><i class="g"></i>' + (totalDone - totalLate) + " on time</span>" +
            '<span><i class="r"></i>' + totalLate + " over TAT</span>" +
            "<span>" + totalDone + " completed in total</span>" +
            "</div>" +
            rows.map(function (r) {
                // A rate off 1-2 cases is noise, not a trend - say so rather
                // than letting "0%" read as a damning verdict.
                var thin = r.done < 3;
                // Stacked track: green = closed within TAT, red = exceeded.
                // Both counts are stated outright, not just the percentage,
                // so the misses are as visible as the hits.
                return '<div class="sf-dash-tatrow' + (thin ? " thin" : "") + '">' +
                    '<div><div class="nm">' + esc(r.name) + "</div>" +
                    '<div class="sub"><b class="ok">' + r.onTime + " on time</b> · " +
                    '<b class="late">' + r.late + " over TAT</b>" +
                    (thin ? " · too few to read into" : "") + "</div></div>" +
                    '<div class="track">' +
                    '<i class="g" style="width:' + (r.onTime / r.done * 100) + '%"></i>' +
                    '<i class="r" style="width:' + (r.late / r.done * 100) + '%"></i>' +
                    "</div>" +
                    '<div class="pct">' + r.pct + "%</div></div>";
            }).join("");
    }

    /* ---------- needs attention ---------- */
    function needsNudge(c) {
        return isOverdue(c) || c.status === "Unassigned" || c.status === "Waiting on requestor";
    }

    function attentionRows(open) {
        var base = open;
        if (stageF) base = base.filter(function (c) { return c.status === stageF; });
        if (deptF) base = base.filter(function (c) { return (c[DEPT_KEY] || "Not set") === deptF; });

        // Unfiltered, this is the "needs a nudge" shortlist. But once the
        // user clicks a stage or a department they've explicitly asked to
        // see that slice, so show ALL of its open cases - narrowing the
        // shortlist instead would hand back an empty table for a department
        // that visibly has cases in it, which just reads as broken.
        if (!stageF && !deptF) base = base.filter(needsNudge);

        return base.map(function (c) {
            var issue, action;
            if (isOverdue(c)) {
                issue = "PO was due " + fmt(c.po);
                action = "Open";
            } else if (c.status === "Unassigned") {
                issue = "Needs a buyer";
                action = "Claim";
            } else if (c.status === "Waiting on requestor") {
                issue = IS_BUYER ? "Waiting for requester reply" : "Your reply is needed";
                action = IS_BUYER ? "Follow up" : "Reply";
            } else {
                issue = "In progress";
                action = "Open";
            }
            return { c: c, issue: issue, action: action, age: ageOf(c) };
        }).sort(function (a, b) {
            return (isOverdue(b.c) - isOverdue(a.c)) || b.age - a.age;
        });
    }

    function renderAttn(open) {
        var rows = attentionRows(open);
        var isFiltered = !!(stageF || deptF);
        var badge = document.getElementById("nAttn");
        badge.textContent = rows.length;
        // A red badge is an alarm. Zero is the opposite of an alarm, so it
        // gets no badge at all - the empty-state line carries the message.
        // A filtered slice is just a count, so it drops to neutral grey.
        badge.hidden = rows.length === 0;
        badge.classList.toggle("neutral", isFiltered);
        document.getElementById("attnTitle").textContent = isFiltered
            ? "Open " + (IS_BUYER ? "cases" : "requests") + " in this selection"
            : "⚡ Needs " + (IS_BUYER ? "your " : "") + "attention";

        // Make any active filter visible and undoable - otherwise a short
        // list looks like "nothing to do" when it's really "you filtered".
        var chips = [];
        if (stageF) chips.push({ label: "Stage: " + stageF, key: "stage" });
        if (deptF) chips.push({ label: (IS_BUYER ? "Department: " : "Commodity: ") + deptF, key: "dept" });
        var fbar = document.getElementById("attnFilters");
        fbar.innerHTML = chips.length
            ? chips.map(function (c) {
                return '<button type="button" class="sf-dash-fchip" data-k="' + c.key + '">' + esc(c.label) + " ✕</button>";
            }).join("") + '<button type="button" class="sf-dash-fclear">Clear</button>'
            : "";
        Array.prototype.forEach.call(fbar.querySelectorAll("[data-k]"), function (b) {
            b.onclick = function () {
                if (b.dataset.k === "stage") stageF = null; else deptF = null;
                render();
            };
        });
        var clr = fbar.querySelector(".sf-dash-fclear");
        if (clr) clr.onclick = function () { stageF = null; deptF = null; render(); };

        var attn = document.getElementById("attn");
        if (!rows.length) {
            attn.innerHTML = '<tbody><tr><td class="sf-dash-empty">' +
                (chips.length ? "Nothing matches this filter." : "Nothing needs chasing right now.") +
                "</td></tr></tbody>";
            return;
        }
        attn.innerHTML = "<thead><tr><th></th><th>Case</th>" +
            (IS_BUYER ? "<th>Requester</th>" : "") +
            "<th>Stage</th><th>Issue</th><th>Age</th><th>Value</th><th>Action</th><th></th></tr></thead><tbody>" +
            rows.map(function (r) {
                var c = r.c;
                var dot = isOverdue(c) ? "#f26b6b"
                    : (c.status === "Unassigned" || c.status === "Waiting on requestor") ? "#f0b429"
                        : COLOR[c.status];
                return "<tr>" +
                    '<td><i class="sf-dash-dot" style="background:' + dot + '"></i></td>' +
                    '<td><a href="' + CFG.caseUrlBase + c.case_id + '">' + esc(c.topic) + "</a>" +
                    '<div class="sf-dash-id">' + esc(c.id) + "<i>·</i>" + esc(c.dept) + "</div></td>" +
                    (IS_BUYER ? "<td>" + esc(c.requester || "—") + "</td>" : "") +
                    '<td><span class="sf-dash-chip ' + STCLS[c.status] + '">' + esc(c.status) + "</span></td>" +
                    "<td>" + esc(r.issue) + "</td>" +
                    '<td class="sf-dash-age ' + (r.age > 30 ? "bad" : "") + '">' + r.age + " day" + (r.age === 1 ? "" : "s") + "</td>" +
                    "<td>" + inr(c.value) + "</td>" +
                    '<td><a class="sf-dash-rowbtn" href="' + CFG.caseUrlBase + c.case_id + '">' + r.action + "</a></td>" +
                    '<td class="sf-dash-more"><a href="' + CFG.caseUrlBase + c.case_id + '" title="Open case">···</a></td>' +
                    "</tr>";
            }).join("") + "</tbody>";
    }

    /* ---------- record list ----------
       The needs-attention table above is a shortlist - it answers "what
       should I touch". This one answers "show me the actual cases", with
       the full set of columns and every row in the current selection, so
       the page can be worked from rather than only read. It follows the
       same scope + stage/department selection as everything else. */
    var REC_PER_PAGE = 10;
    var recPage = 1;
    var recKey = null;

    function renderRecords(all) {
        // Reset to page 1 whenever the selection changes - staying on page 3
        // of a list that just became 4 rows long would show an empty table.
        var key = scopeVal + "|" + (stageF || "") + "|" + (deptF || "");
        if (key !== recKey) { recPage = 1; recKey = key; }

        var rows = all.slice();
        if (stageF) rows = rows.filter(function (c) { return c.status === stageF; });
        if (deptF) rows = rows.filter(function (c) { return (c[DEPT_KEY] || "Not set") === deptF; });
        rows.sort(function (a, b) { return (b.sub || 0) - (a.sub || 0); });

        var noun = IS_BUYER ? "cases" : "requests";
        var bits = [];
        if (stageF) bits.push(stageF);
        if (deptF) bits.push(deptF);
        document.getElementById("recTitle").textContent = bits.length
            ? (IS_BUYER ? "Cases" : "Requests") + " — " + bits.join(" · ")
            : (scopeVal === "all" ? "All " + noun : "My " + noun);

        var badge = document.getElementById("nRec");
        badge.textContent = rows.length;
        badge.hidden = !rows.length;

        var table = document.getElementById("recTable");
        var shown = document.getElementById("recShown");
        var pager = document.getElementById("recPager");
        if (!rows.length) {
            table.innerHTML = '<tbody><tr><td class="sf-dash-empty">No ' + noun + " in this selection.</td></tr></tbody>";
            shown.textContent = "";
            pager.innerHTML = "";
            return;
        }

        var pages = Math.ceil(rows.length / REC_PER_PAGE);
        if (recPage > pages) recPage = pages;
        var start = (recPage - 1) * REC_PER_PAGE;
        var slice = rows.slice(start, start + REC_PER_PAGE);
        shown.textContent = "Showing " + (start + 1) + "–" + (start + slice.length) + " of " + rows.length;

        table.innerHTML = "<thead><tr>" +
            "<th>" + (IS_BUYER ? "Case" : "Request") + "</th><th>Topic</th>" +
            (IS_BUYER ? "<th>Department</th><th>Requester</th><th>Buyer</th>" : "<th>Commodity</th>") +
            "<th>Stage</th><th class='num'>Value</th><th>Submitted</th><th>PO due</th>" +
            "</tr></thead><tbody>" +
            slice.map(function (c) {
                var href = CFG.caseUrlBase + c.case_id;
                var overdue = isOverdue(c);
                return '<tr class="sf-dash-recrow">' +
                    '<td><a href="' + href + '">' + esc(c.id) + "</a></td>" +
                    '<td class="sf-dash-rectopic"><a href="' + href + '">' + esc(c.topic) + "</a></td>" +
                    (IS_BUYER
                        ? "<td>" + esc(c.dept || "—") + "</td><td>" + esc(c.requester || "—") + "</td>" +
                          "<td>" + esc(c.buyer || "Unassigned") + "</td>"
                        : "<td>" + esc(c.comm || "—") + "</td>") +
                    '<td><span class="sf-dash-chip ' + STCLS[c.status] + '">' + esc(c.status) + "</span></td>" +
                    '<td class="num">' + inr(c.value) + "</td>" +
                    "<td>" + fmt(c.sub) + "</td>" +
                    '<td class="' + (overdue ? "sf-dash-recdue" : "") + '">' + fmt(c.po) +
                    (overdue ? " <b>overdue</b>" : "") + "</td>" +
                    "</tr>";
            }).join("") + "</tbody>";

        pager.innerHTML = pages > 1
            ? '<button type="button" data-p="prev"' + (recPage === 1 ? " disabled" : "") + ">‹ Previous</button>" +
              "<span>Page " + recPage + " of " + pages + "</span>" +
              '<button type="button" data-p="next"' + (recPage === pages ? " disabled" : "") + ">Next ›</button>"
            : "";
        Array.prototype.forEach.call(pager.querySelectorAll("[data-p]"), function (b) {
            b.onclick = function () {
                recPage += b.getAttribute("data-p") === "next" ? 1 : -1;
                renderRecords(all);
            };
        });
    }

    /* ---------- Excel export ---------- */
    document.getElementById("exportAll").onclick = function () {
        var all = scoped(), open = all.filter(isOpen), wb = XLSX.utils.book_new();
        var stamp = TODAY.toISOString().slice(0, 10);
        var rows = all.map(function (c) {
            return {
                "Case ID": c.id, "Topic": c.topic, "Department": c.dept,
                "Requester": c.requester || "", "Buyer": c.buyer || "Unassigned",
                "Commodity": c.comm, "Stage": c.status, "Value (INR)": c.value,
                "Submitted": c.sub ? c.sub.toISOString().slice(0, 10) : "",
                "Days open": isOpen(c) ? ageOf(c) : "",
                "Expected PO": c.po ? c.po.toISOString().slice(0, 10) : "",
                "Overdue": isOverdue(c) ? "Yes" : "",
                "Closed on": c.closed ? c.closed.toISOString().slice(0, 10) : ""
            };
        });
        if (!rows.length) rows = [{ "Note": "No cases for this scope" }];
        var ws = XLSX.utils.json_to_sheet(rows);
        ws["!cols"] = Object.keys(rows[0]).map(function (k) {
            return { wch: Math.min(42, Math.max.apply(null, [k.length].concat(rows.map(function (r) { return String(r[k] == null ? "" : r[k]).length; }))) + 2) };
        });
        XLSX.utils.book_append_sheet(wb, ws, "Cases");

        var judged = all.filter(function (c) { return c.closed && c.po; });
        var byStage = STAGES.map(function (s) {
            var o = open.filter(function (c) { return c.status === s; });
            return { "Stage": s, "Cases": o.length, "Value (INR)": o.reduce(function (t, c) { return t + c.value; }, 0) };
        });
        byStage.push({
            "Stage": "POs closed on time",
            "Cases": judged.length ? judged.filter(function (c) { return c.closed <= c.po; }).length + " of " + judged.length : "none closed yet",
            "Value (INR)": ""
        });
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(byStage), "By stage");
        XLSX.writeFile(wb, "Samagra_dashboard_" + stamp + ".xlsx");
    };

    render();
})();
