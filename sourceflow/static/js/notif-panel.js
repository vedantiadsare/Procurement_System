(function () {
    var wrap = document.querySelector("[data-notif]");
    if (!wrap) return;
    var trigger = wrap.querySelector("[data-notif-trigger]");
    var panel = wrap.querySelector("[data-notif-panel]");

    trigger.addEventListener("click", function (e) {
        e.stopPropagation();
        panel.classList.toggle("is-open");
    });
    document.addEventListener("click", function (e) {
        if (!wrap.contains(e.target)) panel.classList.remove("is-open");
    });
})();
