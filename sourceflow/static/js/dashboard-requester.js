/* The one chart on the requester's page. Everything else is server-rendered:
   the page has no filters beyond the period, which is a URL parameter, so
   there is nothing here to re-slice client-side. */
(function () {
    "use strict";

    // The tile numbers count up on load, as the buyer's do. Server-rendered,
    // so the target is read from the text and the text is replaced.
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    Array.prototype.forEach.call(document.querySelectorAll(".rd-kpi strong"), function (s) {
        var text = s.firstChild && s.firstChild.nodeType === 3 ? s.firstChild : null;
        if (!text) return;
        var target = parseInt(text.nodeValue, 10);
        if (isNaN(target) || reduce) return;
        var start = null;
        function tick(ts) {
            if (!start) start = ts;
            var p = Math.min(1, (ts - start) / 600);
            text.nodeValue = Math.round(target * (1 - Math.pow(1 - p, 3))) + " ";
            if (p < 1) requestAnimationFrame(tick);
            else text.nodeValue = target + " ";
        }
        requestAnimationFrame(tick);
    });

    var el = document.getElementById("rdDonut");
    var raw = document.getElementById("rdDonutData");
    if (!el || !raw || typeof Chart === "undefined") return;

    var slices = JSON.parse(raw.textContent).filter(function (s) { return s.value > 0; });
    if (!slices.length) return;

    new Chart(el.getContext("2d"), {
        type: "doughnut",
        data: {
            labels: slices.map(function (s) { return s.label; }),
            datasets: [{
                data: slices.map(function (s) { return s.value; }),
                backgroundColor: slices.map(function (s) { return s.color; }),
                // The gap reads as three separate quantities rather than one
                // ring that happens to change colour.
                borderColor: "#fff",
                borderWidth: 3,
                hoverOffset: 6
            }]
        },
        options: {
            cutout: "68%",
            responsive: true,
            maintainAspectRatio: true,
            // The legend below the chart is rendered in HTML, with the counts
            // beside it - a canvas legend would repeat it without the numbers.
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function (ctx) {
                            var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                            var pct = Math.round(ctx.parsed * 100 / total);
                            return " " + ctx.label + ": " + ctx.parsed + " (" + pct + "%)";
                        }
                    }
                }
            }
        }
    });
}());
