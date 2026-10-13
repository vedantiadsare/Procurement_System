// Live "Estimated TAT: N working days" hint under the topic value field -
// mirrors tat.get_tat_band()'s bands so the requester sees the TAT
// consequence of what they're typing, not just at submission. Pure
// arithmetic display, no server round-trip.
(function () {
    var valueInput = document.querySelector("[data-fx-value]");
    var out = document.querySelector("[data-tat-preview]");
    var rateInput = document.querySelector("[data-fx-rate]");
    var currencySelect = document.getElementById("f_currency");
    if (!valueInput || !out) return;

    var defaultsTag = document.querySelector("[data-fx-defaults]");
    var FX_DEFAULTS = {};
    try { FX_DEFAULTS = defaultsTag ? JSON.parse(defaultsTag.textContent) : {}; } catch (e) { FX_DEFAULTS = {}; }

    // Changing currency has to move the rate with it - otherwise the euro
    // rate stays in the box while the dropdown says USD.
    if (currencySelect && rateInput) {
        currencySelect.addEventListener("change", function () {
            var fallback = FX_DEFAULTS[currencySelect.value];
            if (fallback) rateInput.value = fallback;
        });
    }

    function inRupees(amount) {
        // The bands below are rupee figures. A value entered in another
        // currency is converted at the rate the requester gave before being
        // banded, so the hint matches what the buyer will actually see.
        var code = currencySelect ? currencySelect.value : "INR";
        if (code && code !== "INR" && rateInput) {
            var rate = parseFloat(rateInput.value);
            if (rate > 0) return amount * rate;
        }
        return amount;
    }

    var SMALL_MAX = 350000;
    var SMALL_DAYS = 15;
    var MEDIUM_MAX = 4000000;
    var MEDIUM_DAYS = 30;

    function update() {
        var entered = parseFloat(valueInput.value);
        if (!entered || entered <= 0) {
            out.textContent = "";
            return;
        }
        var value = inRupees(entered);
        if (value <= SMALL_MAX) {
            out.textContent = "Estimated TAT: " + SMALL_DAYS + " working days once your documents are confirmed complete.";
        } else if (value <= MEDIUM_MAX) {
            out.textContent = "Estimated TAT: " + MEDIUM_DAYS + " working days once your documents are confirmed complete.";
        } else {
            out.textContent = "Above the standard TAT bands — your buyer will handle timelines manually.";
        }
    }

    valueInput.addEventListener("input", update);
    if (rateInput) rateInput.addEventListener("input", update);
    if (currencySelect) currencySelect.addEventListener("change", update);
    update();
})();
