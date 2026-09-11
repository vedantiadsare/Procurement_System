// Live ₹-formatted display for the topic value field: typed as plain
// digits, shown with Indian comma grouping, kept in sync with the hidden
// numeric field that actually submits, and flags the real ₹40,00,000
// self-service cutoff (config.TAT_BAND_MEDIUM_MAX) inline as you type
// instead of only after submission.
(function () {
    var display = document.querySelector("[data-inr-display]");
    var hidden = document.querySelector("[data-fx-value]");
    var warning = document.querySelector("[data-topic-value-warning]");
    if (!display || !hidden) return;

    var LIMIT = 4000000;

    function groupIndian(digits) {
        if (!digits) return "";
        var last3 = digits.slice(-3);
        var rest = digits.slice(0, -3);
        var groups = [];
        while (rest.length > 2) {
            groups.unshift(rest.slice(-2));
            rest = rest.slice(0, -2);
        }
        if (rest) groups.unshift(rest);
        return groups.length ? groups.join(",") + "," + last3 : last3;
    }

    display.addEventListener("input", function () {
        var digits = display.value.replace(/\D/g, "");
        display.value = groupIndian(digits);
        hidden.value = digits;
        hidden.dispatchEvent(new Event("input", { bubbles: true }));
        if (warning) warning.hidden = !digits || Number(digits) <= LIMIT;
    });
})();
