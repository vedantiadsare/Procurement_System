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

    function apply() {
        watchers.forEach(function (el) {
            var rule = el.getAttribute("data-show-if");
            var eqIdx = rule.indexOf("=");
            var fieldName = rule.slice(0, eqIdx);
            var accepted = rule.slice(eqIdx + 1).split(",");
            var value = currentValue(fieldName);
            el.classList.toggle("is-visible", accepted.indexOf(value) !== -1);
        });
    }

    form.addEventListener("change", apply);
    apply();
})();
