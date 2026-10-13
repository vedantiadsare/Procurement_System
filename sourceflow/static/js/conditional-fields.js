// Generic conditional-visibility: any element with data-show-if="field=value"
// (value can be a comma-separated list) is shown only when the named form
// field currently holds one of those values. One delegated listener covers
// every conditional section on the page (on-behalf toggle, sourcing-type
// Service dates, currency!=INR FX rate, MRM-conducted file-vs-reason) -
// plain JS show/hide, no server round-trip.
(function () {
    var form = document.querySelector("form[data-conditional-form]");
    if (!form) return;

    var watchers = form.querySelectorAll("[data-show-if]");
    if (!watchers.length) return;

    function currentValue(name) {
        var checked = form.querySelector('input[type="radio"][name="' + name + '"]:checked');
        if (checked) return checked.value;
        var field = form.elements[name];
        if (!field) return null;
        return field.value;
    }

    // One clause: "field=value" or "field!=value".
    function holds(clause) {
        var negate = clause.indexOf("!=") !== -1;
        var eqIdx = clause.indexOf(negate ? "!=" : "=");
        var fieldName = clause.slice(0, eqIdx);
        var accepted = clause.slice(eqIdx + (negate ? 2 : 1)).split(",");
        var hit = accepted.indexOf(currentValue(fieldName)) !== -1;
        return negate ? !hit : hit;
    }

    // Clauses joined by "|" show the element when ANY holds, by "&" when ALL
    // do - the InfoSec screening shows its upload on any Yes, and its
    // "not needed" note only once every answer is No.
    function apply() {
        watchers.forEach(function (el) {
            var rule = el.getAttribute("data-show-if");
            var shown = rule.indexOf("&") !== -1
                ? rule.split("&").every(holds)
                : rule.split("|").some(holds);
            el.classList.toggle("is-visible", shown);
        });
    }

    form.addEventListener("change", apply);
    apply();
})();
