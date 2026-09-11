// Buyer action toolbar: plain inline <form> panels that are always in the
// DOM, toggled visible/hidden client-side (approximates Streamlit's
// st.popover without any modal/htmx machinery - nothing fires until the
// form's real submit).
(function () {
    var toolbar = document.querySelector("[data-action-toolbar]");
    if (!toolbar) return;

    var triggers = toolbar.querySelectorAll("[data-action-trigger]");
    var panels = toolbar.querySelectorAll("[data-action-panel]");

    function closeAll() {
        panels.forEach(function (p) { p.classList.remove("is-open"); });
    }

    triggers.forEach(function (trigger) {
        trigger.addEventListener("click", function (e) {
            e.stopPropagation();
            var name = trigger.getAttribute("data-action-trigger");
            var panel = toolbar.querySelector('[data-action-panel="' + name + '"]');
            var wasOpen = panel && panel.classList.contains("is-open");
            closeAll();
            if (panel && !wasOpen) panel.classList.add("is-open");
        });
    });

    document.addEventListener("click", function (e) {
        if (!toolbar.contains(e.target)) closeAll();
    });
})();
