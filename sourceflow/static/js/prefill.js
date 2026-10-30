// Fill the new-request form from the documents attached in section D.
// The server reads them (/requests/prefill) and returns only values a
// document clearly states, each with its source. This script fills fields
// that are still empty - never one the requester has typed or chosen - marks
// each filled field with where the value came from, and leaves MRM, InfoSec,
// sourcing basis and who the request is for to the requester. It runs once
// by itself when a cart or SFO is attached, and again from the button.
(function () {
    var btn = document.querySelector("[data-prefill-btn]");
    var note = document.querySelector("[data-prefill-note]");
    var list = document.querySelector("[data-nr-doc-list]");
    if (!btn || !note || !window.fetch || !window.FormData) return;

    var defaultNote = note.textContent;
    var lastAuto = "";
    var busy = false;

    // Anything the requester changes by hand is theirs: never overwritten.
    document.addEventListener("input", function (e) { if (e.isTrusted && e.target.name) e.target.dataset.userSet = "1"; }, true);
    document.addEventListener("change", function (e) { if (e.isTrusted && e.target.name) e.target.dataset.userSet = "1"; }, true);

    var SLOTS = [["sc_file", "SC"], ["sfo_file", "SFO"], ["rfq_file", "RFQ"], ["offer_files", "OFFER"]];

    function attached() {
        var out = [];
        SLOTS.forEach(function (s) {
            var input = document.getElementById(s[0]);
            if (input && input.files) Array.prototype.forEach.call(input.files, function (f) { out.push([s[0], s[1], f]); });
        });
        return out;
    }

    function fire(el, type) { el.dispatchEvent(new Event(type, { bubbles: true })); }

    function mark(el, source) {
        var field = el.closest(".sf-field") || el.parentElement;
        if (!field) return;
        field.classList.add("sf-prefilled");
        var tag = field.querySelector(".sf-prefill-src");
        if (!tag) {
            tag = document.createElement("span");
            tag.className = "sf-prefill-src";
            field.appendChild(tag);
        }
        tag.textContent = "Filled from " + (source || "your documents") + " — check it";
    }

    function hasOption(select, value) {
        return Array.prototype.some.call(select.options, function (o) { return o.value === value; });
    }

    function fillText(id, value, source) {
        var el = document.getElementById(id);
        if (!el || el.dataset.userSet || (el.value || "").trim()) return false;
        el.value = value;
        fire(el, "input"); fire(el, "change");
        mark(el, source);
        return true;
    }

    // A dropdown always shows something - its first option - so "empty"
    // can't be the test. It counts as answered only once the requester has
    // picked from it themselves.
    function fillSelect(id, value, source) {
        var el = document.getElementById(id);
        if (!el || el.dataset.userSet || !hasOption(el, value)) return false;
        if (el.value === value) { mark(el, source); return true; }
        el.value = value;
        fire(el, "change");
        mark(el, source);
        return true;
    }

    function apply(fields) {
        var done = [];
        function ok(name, filled) { if (filled) done.push(name); }
        var f = function (k) { return fields[k] || null; };

        if (f("sc_number")) ok("SC number", fillText("f_sc_number", String(f("sc_number").value), f("sc_number").source));
        if (f("requesting_dept")) ok("department", fillSelect("f_requesting_dept", f("requesting_dept").value, f("requesting_dept").source));
        if (f("cost_center")) ok("cost center", fillText("f_cost_center", String(f("cost_center").value), f("cost_center").source));
        if (f("topic_title")) ok("title", fillText("f_topic_title", f("topic_title").value, f("topic_title").source));
        if (f("description")) ok("description", fillText("f_description", f("description").value, f("description").source));
        if (f("expense_commodity")) ok("commodity", fillSelect("f_expense_commodity", f("expense_commodity").value, f("expense_commodity").source));
        if (f("delivery_location")) ok("delivery location", fillSelect("f_delivery_location", f("delivery_location").value, f("delivery_location").source));
        // Currency and tax basis start with a default already chosen, so the
        // document's value replaces the default unless the requester set it.
        if (f("currency")) ok("currency", fillSelect("f_currency", f("currency").value, f("currency").source));
        if (f("topic_value")) {
            var display = document.querySelector("[data-inr-display]");
            var hidden = document.querySelector("[data-fx-value]");
            if (display && hidden && !display.dataset.userSet && !(hidden.value || "").trim()) {
                display.value = String(Math.round(Number(f("topic_value").value)));
                fire(display, "input");
                mark(display, f("topic_value").source);
                done.push("value");
            }
        }
        if (f("tax_basis")) {
            var radios = document.querySelectorAll('input[name="tax_basis"]');
            var touched = Array.prototype.some.call(radios, function (r) { return r.dataset.userSet; });
            var target = Array.prototype.find.call(radios, function (r) { return r.value === f("tax_basis").value; });
            if (target && !touched) {
                target.checked = true;
                fire(target, "change");
                mark(target, f("tax_basis").source);
                done.push("tax basis");
            }
        }
        return done;
    }

    function run(auto) {
        var files = attached();
        var hasRequestDoc = files.some(function (x) { return x[1] === "SC" || x[1] === "SFO"; });
        if (!files.length || !hasRequestDoc) {
            if (!auto) note.textContent = "Attach the approved shopping cart (or, for a frame contract, the SFO) first: the form is filled from it.";
            return;
        }
        if (busy) return;
        busy = true;
        btn.disabled = true;
        note.textContent = "Reading your documents…";
        var body = new FormData();
        files.forEach(function (x) { body.append(x[0], x[2]); });
        fetch("/requests/prefill", { method: "POST", body: body, credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : { fields: {} }; })
            .then(function (data) {
                var done = apply(data.fields || {});
                note.textContent = done.length
                    ? "Filled " + done.length + " field" + (done.length === 1 ? "" : "s") + " from your documents (" + done.join(", ") +
                      "). Check the highlighted fields above. MRM, InfoSec and who this request is for are yours to answer."
                    : "Nothing new to fill: the fields the documents state are already filled in, or the documents don't state them.";
            })
            .catch(function () { note.textContent = defaultNote; })
            .finally(function () { busy = false; btn.disabled = false; });
    }

    btn.addEventListener("click", function () { run(false); });

    // Once by itself when a cart or SFO joins the list - only for a new set
    // of files, so removing or retagging one doesn't re-run it.
    if (list && window.MutationObserver) {
        var timer = null;
        new MutationObserver(function () {
            clearTimeout(timer);
            timer = setTimeout(function () {
                var files = attached();
                var key = files.map(function (x) { return x[1] + ":" + x[2].name + ":" + x[2].size; }).sort().join("|");
                if (key && key !== lastAuto && files.some(function (x) { return x[1] === "SC" || x[1] === "SFO"; })) {
                    lastAuto = key;
                    run(true);
                }
            }, 400);
        }).observe(list, { childList: true, subtree: true });
    }
})();
