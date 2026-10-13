/* Dashboard export, shared by the buyer and head dashboards.

   Gathers what is on screen - every Chart.js canvas that is visible, plus
   the data tables the HTML-built visuals (heat grids, health bars, bubbles)
   register as they render - and posts it with the case list and summary to
   /dashboard/export.xlsx, which answers with a workbook: a sheet per chart
   holding its data, a native Excel chart and the picture. If the server
   cannot be reached the list and summary still go out through SheetJS, so
   the button never does nothing. */
(function () {
    "use strict";

    var tables = {}; // element id -> {title, subtitle, type, headers, rows}

    function titleFor(el) {
        var gauge = el.closest && el.closest(".gauge");
        if (gauge) {
            var b = gauge.querySelector("b");
            return { title: b ? b.textContent.trim() : "Gauge", subtitle: (gauge.querySelector("small") || {}).textContent || "" };
        }
        var card = el.closest && el.closest(".card, .ad-card, .ad-hero__card");
        if (!card) return { title: el.id || "Chart", subtitle: "" };
        var h = card.querySelector("h2, h3, .ad-card__t, .card__t");
        var p = card.querySelector(".ch-h p, .ad-card__h p, .ad-card__s, .card__s");
        return { title: h ? h.textContent.replace(/\s+/g, " ").trim() : (el.id || "Chart"), subtitle: p ? p.textContent.replace(/\s+/g, " ").trim() : "" };
    }
    function visible(el) { return !!(el && el.offsetParent !== null && el.getBoundingClientRect().width > 0); }
    function num(v) {
        if (v === null || v === undefined) return null;
        if (typeof v === "number") return v;
        if (typeof v === "object") return typeof v.y === "number" ? v.y : (typeof v.r === "number" ? v.r : null);
        var n = Number(v); return isNaN(n) ? String(v) : n;
    }

    /* HTML-built visuals call this when they render, so their numbers travel
       with the export even though there is no canvas to picture. */
    function register(el, spec) {
        if (!el || !el.id) return;
        var t = titleFor(el);
        tables[el.id] = { el: el, title: spec.title || t.title, subtitle: spec.subtitle || t.subtitle, type: spec.type || "table",
                          stacked: !!spec.stacked, series: spec.series || null, headers: spec.headers, rows: spec.rows };
    }

    function fromChart(ch) {
        var canvas = ch.canvas;
        if (!visible(canvas)) return null;
        var t = titleFor(canvas), d = ch.config.data || {}, labels = d.labels || [], ds = d.datasets || [];
        var headers, rows;
        if (labels.length) {
            headers = [""].concat(ds.map(function (x, i) { return x.label || ("Series " + (i + 1)); }));
            rows = labels.map(function (l, i) { return [String(l)].concat(ds.map(function (x) { return num((x.data || [])[i]); })); });
        } else {
            headers = ["Series", "x", "y", "r"]; rows = [];
            ds.forEach(function (x) { (x.data || []).forEach(function (pt) { rows.push([x.label || "", num(pt && pt.x), num(pt && pt.y), num(pt && pt.r)]); }); });
        }
        var sc = (ch.config.options || {}).scales || {};
        var png = null;
        try { png = ch.toBase64Image("image/png", 1); } catch (e) { png = null; }
        return { title: t.title, subtitle: t.subtitle, type: ch.config.type, stacked: !!((sc.x && sc.x.stacked) || (sc.y && sc.y.stacked)),
                 headers: headers, rows: rows, png: png };
    }

    function collect(charts) {
        var out = [], seen = {};
        Object.keys(charts || {}).forEach(function (id) {
            var c = charts[id]; if (!c || !c.canvas) return;
            var item = fromChart(c); if (item) { out.push(item); seen[item.title] = 1; }
        });
        Object.keys(tables).forEach(function (id) {
            var t = tables[id];
            if (!visible(t.el) || !t.rows || !t.rows.length) return;
            out.push({ title: t.title, subtitle: t.subtitle, type: t.type, stacked: t.stacked, series: t.series, headers: t.headers, rows: t.rows, png: null });
        });
        return out;
    }

    function download(blob, filename) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob); a.download = filename;
        document.body.appendChild(a); a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    }

    /* sheets: [{name, rows:[{col: val}]}], charts registry, filename, button
       to disable while it runs. Falls back to SheetJS for the sheets alone. */
    function run(opts) {
        var btn = opts.button, was = btn && btn.textContent;
        if (btn) { btn.disabled = true; btn.textContent = "Preparing…"; }
        var payload = { filename: opts.filename, sheets: opts.sheets, charts: collect(opts.charts) };
        var done = function () { if (btn) { btn.disabled = false; btn.textContent = was; } };
        if (!window.fetch) { fallback(opts); done(); return; }
        fetch("/dashboard/export.xlsx", { method: "POST", credentials: "same-origin",
                                          headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })
            .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.blob(); })
            .then(function (blob) { download(blob, opts.filename); })
            .catch(function () { fallback(opts); })
            .then(done, done);
    }
    function fallback(opts) {
        if (!window.XLSX) return;
        var wb = XLSX.utils.book_new();
        opts.sheets.forEach(function (s) { XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(s.rows), s.name); });
        XLSX.writeFile(wb, opts.filename);
    }

    window.DashExport = { register: register, run: run, collect: collect };
}());
