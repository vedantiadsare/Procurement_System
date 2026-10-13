// Live "≈ ₹X at the entered rate" caption - pure arithmetic display update,
// no server round-trip needed.
(function () {
    var valueInput = document.querySelector("[data-fx-value]");
    var rateInput = document.querySelector("[data-fx-rate]");
    var out = document.querySelector("[data-fx-output]");
    if (!valueInput || !rateInput || !out) return;

    function formatINR(n) {
        n = Math.round(n);
        var s = String(Math.abs(n));
        var last3 = s.slice(-3);
        var rest = s.slice(0, -3);
        var groups = [];
        while (rest.length > 2) {
            groups.unshift(rest.slice(-2));
            rest = rest.slice(0, -2);
        }
        if (rest) groups.unshift(rest);
        var formatted = groups.length ? groups.join(",") + "," + last3 : last3;
        return (n < 0 ? "-₹" : "₹") + formatted;
    }

    function update() {
        var value = parseFloat(valueInput.value);
        var rate = parseFloat(rateInput.value);
        if (!value || !rate) {
            out.textContent = "";
            return;
        }
        // "Indicative" is the whole point of the wording: the requester no
        // longer sets this rate, so the figure is a reference-rate estimate
        // for the TAT band, not the number the case will be valued at.
        out.textContent = "Indicative: ≈ " + formatINR(value * rate)
            + " at today's reference rate of " + rate + ".";
    }

    valueInput.addEventListener("input", update);
    rateInput.addEventListener("input", update);
    update();
})();
