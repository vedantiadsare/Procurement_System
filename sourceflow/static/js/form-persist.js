// Keeps what has been typed into the new-request form across a reload.
//
// The form is long, and losing it to an accidental refresh - or to a
// hard-refresh after a change - means typing the whole thing again. Values are
// saved as they change and restored on load.
//
// Attachments are deliberately not saved: a browser cannot put files back into
// a file input for security reasons, so anything claiming to restore them
// would be lying. The upload list starts empty and says so.
(function () {
    var form = document.querySelector("form[data-conditional-form]");
    if (!form || !window.localStorage) return;

    var KEY = "samagra.newRequest." + (form.getAttribute("action") || "form");
    var SKIP = { "csrf_token": 1 };

    function collect() {
        var state = {};
        Array.prototype.forEach.call(form.elements, function (el) {
            if (!el.name || SKIP[el.name] || el.type === "file" || el.disabled) return;
            if (el.type === "radio") {
                if (el.checked) state[el.name] = el.value;
            } else if (el.type === "checkbox") {
                state[el.name] = el.checked;
            } else {
                state[el.name] = el.value;
            }
        });
        return state;
    }

    function save() {
        try {
            localStorage.setItem(KEY, JSON.stringify({ at: Date.now(), values: collect() }));
        } catch (e) { /* private mode, quota - not worth interrupting anyone over */ }
    }

    function restore() {
        var stored;
        try {
            stored = JSON.parse(localStorage.getItem(KEY) || "null");
        } catch (e) { return; }
        if (!stored || !stored.values) return;

        // A day-old draft is more likely to confuse than help.
        if (Date.now() - (stored.at || 0) > 24 * 60 * 60 * 1000) {
            localStorage.removeItem(KEY);
            return;
        }

        var restoredAny = false;
        Object.keys(stored.values).forEach(function (name) {
            var value = stored.values[name];
            var field = form.elements[name];
            if (!field) return;
            if (field.length && field[0] && field[0].type === "radio") {
                Array.prototype.forEach.call(field, function (radio) {
                    radio.checked = radio.value === value;
                });
                restoredAny = true;
            } else if (field.type === "checkbox") {
                field.checked = !!value;
                restoredAny = true;
            } else if (field.type !== "file" && value !== "") {
                field.value = value;
                restoredAny = true;
            }
        });

        if (restoredAny) {
            // Conditional sections, the currency prefix and the TAT hint all
            // key off these fields, so they have to recompute after a restore.
            form.dispatchEvent(new Event("change", { bubbles: true }));
            var display = form.querySelector("[data-inr-display]");
            var hidden = form.querySelector("[data-fx-value]");
            if (display && hidden && hidden.value) {
                display.dispatchEvent(new Event("input", { bubbles: true }));
            }
        }
    }

    form.addEventListener("input", save);
    form.addEventListener("change", save);
    form.addEventListener("submit", function () {
        try { localStorage.removeItem(KEY); } catch (e) { /* nothing to do */ }
    });

    restore();
})();
