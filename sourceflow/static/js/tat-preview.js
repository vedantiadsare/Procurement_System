// Live "Estimated TAT: N working days" hint under the topic value field -
// mirrors tat.get_tat_band()'s bands so the requester sees the TAT
// consequence of what they're typing, not just at submission. Pure
// arithmetic display, no server round-trip.
(function () {
    var valueInput = document.querySelector("[data-fx-value]");
    var out = document.querySelector("[data-tat-preview]");
    if (!valueInput || !out) return;

    var SMALL_MAX = 350000;
    var SMALL_DAYS = 15;
    var MEDIUM_MAX = 4000000;
    var MEDIUM_DAYS = 30;

    function update() {
        var value = parseFloat(valueInput.value);
        if (!value || value <= 0) {
            out.textContent = "";
            return;
        }
        if (value <= SMALL_MAX) {
            out.textContent = "Estimated TAT: " + SMALL_DAYS + " working days once your documents are confirmed complete.";
        } else if (value <= MEDIUM_MAX) {
            out.textContent = "Estimated TAT: " + MEDIUM_DAYS + " working days once your documents are confirmed complete.";
        } else {
            out.textContent = "Above the standard TAT bands — your buyer will handle timelines manually.";
        }
    }

    valueInput.addEventListener("input", update);
    update();
})();
