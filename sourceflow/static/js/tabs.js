// All three tab panels are already in the DOM (server picks the initially
// active one from ?tab=); this just avoids a full reload on click. Without
// JS the links still work as plain navigation to ?tab=...
(function () {
    var tabs = document.querySelectorAll("[data-tab-link]");
    if (!tabs.length) return;

    tabs.forEach(function (link) {
        link.addEventListener("click", function (e) {
            e.preventDefault();
            var name = link.getAttribute("data-tab-link");

            document.querySelectorAll("[data-tab-link]").forEach(function (l) {
                l.classList.toggle("active", l === link);
            });
            document.querySelectorAll("[data-tab-panel]").forEach(function (p) {
                p.classList.toggle("active", p.getAttribute("data-tab-panel") === name);
            });

            var url = new URL(window.location);
            url.searchParams.set("tab", name);
            window.history.replaceState({}, "", url);
        });
    });
})();
