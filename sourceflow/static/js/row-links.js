/* Makes a whole row or card open its case, not just the button at the end
   of it. Anything carrying data-href becomes clickable; the real <a> stays
   where it is, both because it is what a keyboard and a screen reader follow
   and because "Open" is the thing a buyer's eye goes to when they are
   skimming for the action rather than the content.

   Delegated from the document so rows added or re-rendered later (the queue
   tabs hide and show rows rather than replacing them, but the dashboard does
   rebuild its tables) need no re-binding. */
(function () {
    "use strict";

    // A click that lands on something that already does something of its own
    // belongs to that control, not to the row around it.
    var INTERACTIVE = "a, button, input, select, textarea, label, summary, [role='button']";

    function target(el) {
        var host = el.closest("[data-href]");
        if (!host) return null;
        var hit = el.closest(INTERACTIVE);
        // An <a> inside the row wins; an <a> that IS the row does not exist.
        if (hit && host.contains(hit) && hit !== host) return null;
        return host;
    }

    document.addEventListener("click", function (e) {
        if (e.button !== 0) return;
        var host = target(e.target);
        if (!host) return;
        // Someone highlighting a ticket number to copy it is not clicking through.
        var sel = window.getSelection();
        if (sel && sel.toString().length > 2) return;
        var href = host.getAttribute("data-href");
        if (e.metaKey || e.ctrlKey || e.shiftKey) window.open(href, "_blank");
        else window.location.href = href;
    });

    document.addEventListener("keydown", function (e) {
        if (e.key !== "Enter" && e.key !== " ") return;
        var host = e.target.closest && e.target.closest("[data-href]");
        if (!host || host !== e.target) return;
        e.preventDefault();
        window.location.href = host.getAttribute("data-href");
    });
}());
