/* Samagra procurement dashboard - the arithmetic.

   Kept separate from the rendering so every number on the page can be checked
   without a browser: this file is loadable both as a <script> (exports on
   window.DashMetrics) and by node (module.exports), and it holds no DOM.

   Two conventions run through everything here:

   - TAT is counted in WORKING days, never calendar days, because that is how
     the commitment itself is stated (15 working days up to Rs 3.5 lakh, 30
     above). A case whose PO due date passed on a Friday is one day late on
     Monday, not three.
   - Money is summed in rupees only. topic_value_inr is the normalised figure;
     a case whose currency has no published rate carries 0 there and is
     counted but never quietly added in - so the open-value tile also reports
     how many cases it could not convert. */
(function (root, factory) {
    var api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    else root.DashMetrics = api;
}(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var DAY = 864e5;
    // Two vocabularies for the same states: a buyer sees "In progress", the
    // person who raised it sees "Procurement reviewing". Both dashboards run
    // on this module, so both sets count as open.
    var OPEN_STATES = ["Unassigned", "In progress", "Waiting on requestor",
                       "Submitted", "Procurement reviewing", "Waiting for my response"];
    var CLOSED_STATES = ["Approved", "Rejected", "PO released", "Not approved"];
    var TAT_STATES = ["On track", "At risk", "Delayed", "Clock not started"];

    /* ---------- dates ---------- */

    function parseDate(value) {
        if (!value) return null;
        if (value instanceof Date) return value;
        var d = new Date(String(value).slice(0, 10) + "T00:00:00");
        return isNaN(d.getTime()) ? null : d;
    }

    function iso(d) {
        if (!d) return null;
        return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
    }

    function pad(n) { return (n < 10 ? "0" : "") + n; }

    function addDays(d, n) { return new Date(d.getTime() + n * DAY); }

    function isWeekend(d) { var w = d.getDay(); return w === 0 || w === 6; }

    /* Working days from `from` to `to`, counting the days you would actually
       work through. Negative when `to` is in the past, which is what makes a
       single number serve both "due in 4 days" and "6 days late". */
    function workingDaysBetween(from, to) {
        if (!from || !to) return null;
        var sign = 1;
        var a = from, b = to;
        if (to < from) { sign = -1; a = to; b = from; }
        var count = 0;
        var cur = new Date(a.getTime());
        while (cur < b) {
            cur = addDays(cur, 1);
            if (!isWeekend(cur)) count++;
        }
        return sign * count;
    }

    function startOfWeek(d) {
        // Monday-anchored: procurement reports weekly from Monday.
        var day = d.getDay();
        var back = (day === 0 ? 6 : day - 1);
        return addDays(new Date(d.getFullYear(), d.getMonth(), d.getDate()), -back);
    }

    function monthKey(d) { return d ? d.getFullYear() + "-" + pad(d.getMonth() + 1) : null; }

    function monthEnd(key) {
        var p = key.split("-");
        return new Date(Number(p[0]), Number(p[1]), 0);
    }

    function monthLabel(key) {
        var names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        var p = key.split("-");
        return names[Number(p[1]) - 1] + " " + p[0];
    }

    /* ---------- per-case derivation ---------- */

    function isOpen(c) { return OPEN_STATES.indexOf(c.status) !== -1; }
    function isClosed(c) { return CLOSED_STATES.indexOf(c.status) !== -1; }

    /* Where a case stands against its own PO commitment.

       "Clock not started" is a real Samagra state, not a filler bucket: the
       TAT clock only begins once the complete document set is on file, so a
       case still waiting for documents has no due date to be late against.
       Counting those as "on track" would flatter the numbers. */
    function tatState(c, today) {
        if (!isOpen(c)) return null;
        if (!c.po) return "Clock not started";
        var left = workingDaysBetween(today, c.po);
        if (left < 0) return "Delayed";
        if (left <= 5) return "At risk";
        return "On track";
    }

    /* Whose court the ball is in. Derived from the status the app can really
       be in - a case is only with the requester when procurement has raised
       an enquiry against it. */
    function withWhom(c) {
        if (c.status === "Waiting on requestor" ||
            c.status === "Waiting for my response") return "Requester";
        if (c.status === "Unassigned" || c.status === "Submitted") return "Unclaimed";
        return isOpen(c) ? "Buyer" : "Closed";
    }

    /* Normalises the JSON from dashboard.py into dated objects with the
       derived fields every view needs. Safe to call more than once. */
    function prepare(cases, todayISO) {
        var today = parseDate(todayISO) || new Date();
        return (cases || []).map(function (src) {
            var c = {};
            for (var k in src) if (Object.prototype.hasOwnProperty.call(src, k)) c[k] = src[k];
            c.sub = parseDate(src.sub);
            c.po = parseDate(src.po);
            c.closed = parseDate(src.closed);
            c.open = isOpen(c);
            c.done = isClosed(c);
            c.tat = tatState(c, today);
            c.with = withWhom(c);
            // Negative = late. Null when there is no due date to measure against.
            c.daysLeft = c.po ? workingDaysBetween(today, c.po) : null;
            c.closedLate = (c.done && c.closed && c.po) ? (c.closed > c.po) : null;
            c.month = monthKey(c.sub);
            return c;
        });
    }

    /* ---------- headline tiles ---------- */

    function kpis(cases, todayISO) {
        var today = parseDate(todayISO) || new Date();
        var open = cases.filter(isOpen);
        var value = 0, unconverted = 0;
        open.forEach(function (c) {
            var v = Number(c.value_inr || 0);
            if (v > 0) value += v; else unconverted++;
        });

        var thirty = addDays(today, -30);
        var closedRecent = cases.filter(function (c) {
            return c.closed && c.closed > thirty && c.closed <= today;
        }).length;

        var tat = { "On track": 0, "At risk": 0, "Delayed": 0, "Clock not started": 0 };
        open.forEach(function (c) {
            var s = c.tat || tatState(c, today);
            if (s in tat) tat[s]++;
        });

        var twelve = addDays(today, -84);
        var judged = cases.filter(function (c) {
            return c.closed && c.po && c.closed > twelve && c.closed <= today;
        });
        var onTime = judged.filter(function (c) { return c.closed <= c.po; }).length;

        return {
            open: open.length,
            openValueInr: value,
            openValueUnconverted: unconverted,
            closedRecent: closedRecent,
            onTrack: tat["On track"],
            atRisk: tat["At risk"],
            delayed: tat["Delayed"],
            notStarted: tat["Clock not started"],
            withinTat: judged.length ? Math.round(onTime * 100 / judged.length) : null,
            withinTatBase: judged.length
        };
    }

    /* ---------- time series ---------- */

    /* Cases raised vs cases closed, per week. Both lines are counts of events
       in the same window, so they share one axis - never a second scale. */
    function byWeek(cases, todayISO, weeks) {
        var today = parseDate(todayISO) || new Date();
        var end = startOfWeek(today);
        var out = [];
        for (var i = weeks - 1; i >= 0; i--) {
            var start = addDays(end, -7 * i);
            var stop = addDays(start, 7);
            out.push({
                start: start,
                label: iso(start),
                incoming: cases.filter(function (c) { return c.sub && c.sub >= start && c.sub < stop; }).length,
                closed: cases.filter(function (c) { return c.closed && c.closed >= start && c.closed < stop; }).length
            });
        }
        return out;
    }

    function byMonth(cases, todayISO, months) {
        var today = parseDate(todayISO) || new Date();
        var keys = [];
        for (var i = months - 1; i >= 0; i--) {
            var d = new Date(today.getFullYear(), today.getMonth() - i, 1);
            keys.push(monthKey(d));
        }
        return keys.map(function (key) {
            var end = monthEnd(key);
            var cutoff = end > today ? today : end;
            var incoming = cases.filter(function (c) { return c.month === key; }).length;
            var closedIn = cases.filter(function (c) { return c.closed && monthKey(c.closed) === key; });
            var judged = closedIn.filter(function (c) { return !!c.po; });
            var onTime = judged.filter(function (c) { return c.closed <= c.po; }).length;
            var openAtEnd = cases.filter(function (c) {
                if (!c.sub || c.sub > cutoff) return false;
                return !c.closed || c.closed > cutoff;
            }).length;
            return {
                key: key,
                label: monthLabel(key),
                partial: end > today,
                incoming: incoming,
                closed: closedIn.length,
                openAtEnd: openAtEnd,
                withinTat: judged.length ? Math.round(onTime * 100 / judged.length) : null
            };
        });
    }

    /* Share of closed cases that met their due date, per month - the trend
       behind the headline percentage. */
    function tatTrend(cases, todayISO, months) {
        return byMonth(cases, todayISO, months).map(function (m) {
            return { label: m.label, pct: m.withinTat };
        });
    }

    /* ---------- groupings ---------- */

    function groupBy(cases, key) {
        var map = {};
        cases.forEach(function (c) {
            var name = c[key] || "Not set";
            if (!map[name]) map[name] = { name: name, count: 0, value: 0, cases: [] };
            map[name].count++;
            map[name].value += Number(c.value_inr || 0);
            map[name].cases.push(c);
        });
        return Object.keys(map).map(function (k) { return map[k]; })
            .sort(function (a, b) { return b.count - a.count || a.name.localeCompare(b.name); });
    }

    /* Top N by count with everything else folded into one "Others" slice -
       never a generated hue for a 9th category. */
    function topN(groups, n) {
        if (groups.length <= n) return { top: groups.slice(), others: null };
        var top = groups.slice(0, n);
        var rest = groups.slice(n);
        var others = {
            name: "Others",
            count: rest.reduce(function (s, g) { return s + g.count; }, 0),
            value: rest.reduce(function (s, g) { return s + g.value; }, 0),
            members: rest.map(function (g) { return g.name; })
        };
        return { top: top, others: others };
    }

    /* Each group broken into its TAT states, in a fixed order so the stacked
       bars read the same way on every chart. */
    function tatByGroup(cases, key) {
        return groupBy(cases.filter(isOpen), key).map(function (g) {
            var row = { name: g.name, total: g.count };
            TAT_STATES.forEach(function (s) { row[s] = 0; });
            g.cases.forEach(function (c) { if (c.tat) row[c.tat]++; });
            return row;
        });
    }

    function buyerSummary(cases, todayISO) {
        var today = parseDate(todayISO) || new Date();
        var thirty = addDays(today, -30);
        var names = {};
        cases.forEach(function (c) {
            var n = c.buyer || "Unassigned";
            if (!names[n]) names[n] = { name: n, open: 0, closed30: 0, openValue: 0 };
            if (isOpen(c)) { names[n].open++; names[n].openValue += Number(c.value_inr || 0); }
            if (c.closed && c.closed > thirty && c.closed <= today) names[n].closed30++;
        });
        return Object.keys(names).map(function (k) { return names[k]; })
            .sort(function (a, b) { return b.open - a.open || a.name.localeCompare(b.name); });
    }

    /* ---------- drill-down list ---------- */

    /* Most urgent first: furthest past due at the top, then nearest due, with
       cases whose clock has not started last - they are not late, they are
       not started, and mixing them in would bury the real problems. */
    function urgencyOrder(a, b) {
        var av = a.daysLeft === null ? 1e6 : a.daysLeft;
        var bv = b.daysLeft === null ? 1e6 : b.daysLeft;
        return av - bv;
    }

    return {
        OPEN_STATES: OPEN_STATES,
        CLOSED_STATES: CLOSED_STATES,
        TAT_STATES: TAT_STATES,
        parseDate: parseDate,
        iso: iso,
        addDays: addDays,
        workingDaysBetween: workingDaysBetween,
        startOfWeek: startOfWeek,
        monthKey: monthKey,
        monthLabel: monthLabel,
        isOpen: isOpen,
        isClosed: isClosed,
        tatState: tatState,
        withWhom: withWhom,
        prepare: prepare,
        kpis: kpis,
        byWeek: byWeek,
        byMonth: byMonth,
        tatTrend: tatTrend,
        groupBy: groupBy,
        topN: topN,
        tatByGroup: tatByGroup,
        buyerSummary: buyerSummary,
        urgencyOrder: urgencyOrder
    };
}));
