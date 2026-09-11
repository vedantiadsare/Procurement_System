// Local LLM inference takes real time (~30s+ on a laptop CPU, no GPU) - with
// no feedback the "Analyze offers" button looks broken/frozen even though
// it's genuinely working in the background. Disable it and show a waiting
// hint on submit so that's clear, instead of the user thinking nothing
// happened and clicking away before the redirect comes back.
(function () {
    var form = document.querySelector("[data-analyze-offers-form]");
    if (!form) return;
    var button = form.querySelector("button[type=submit]");
    var hint = form.querySelector("[data-analyze-offers-hint]");

    form.addEventListener("submit", function () {
        if (button) {
            button.disabled = true;
            button.textContent = "Analyzing…";
        }
        if (hint) hint.hidden = false;
    });
})();
