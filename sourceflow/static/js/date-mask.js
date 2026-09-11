// dd.mm.yyyy text-mask date fields: digits-only typing, dots auto-inserted
// after the day and month groups - matches the app-wide DD.MM.YYYY display
// convention (formatting.py's `date` filter) instead of the browser's
// native, locale-dependent date input.
(function () {
    document.querySelectorAll(".sf-date-input").forEach(function (input) {
        input.addEventListener("input", function () {
            var digits = input.value.replace(/\D/g, "").slice(0, 8);
            var parts = [];
            if (digits.length > 0) parts.push(digits.slice(0, 2));
            if (digits.length > 2) parts.push(digits.slice(2, 4));
            if (digits.length > 4) parts.push(digits.slice(4, 8));
            input.value = parts.join(".");
        });
    });
})();
