// Custom-styled file pickers: hides each native <input type=file>'s own
// "Choose File / No file chosen" chrome behind a themed button + filename
// readout, and lets every named document slot accept a direct
// drag-and-drop instead of one big shared dropzone.
(function () {
    document.querySelectorAll(".sf-file-picker").forEach(function (picker) {
        var input = picker.querySelector(".sf-file-picker__input");
        var nameEl = picker.querySelector("[data-file-name]");
        if (!input || !nameEl) return;

        function describe() {
            if (!input.files || !input.files.length) {
                nameEl.textContent = "No file chosen";
            } else if (input.files.length === 1) {
                nameEl.textContent = input.files[0].name;
            } else {
                nameEl.textContent = input.files.length + " files selected";
            }
        }
        input.addEventListener("change", describe);
        describe();
    });

    document.querySelectorAll("[data-file-slot]").forEach(function (slot) {
        var input = slot.querySelector(".sf-file-picker__input");
        if (!input) return;

        slot.addEventListener("dragover", function (e) {
            e.preventDefault();
            slot.classList.add("is-dragover");
        });
        slot.addEventListener("dragleave", function () {
            slot.classList.remove("is-dragover");
        });
        slot.addEventListener("drop", function (e) {
            e.preventDefault();
            slot.classList.remove("is-dragover");
            if (!e.dataTransfer || !e.dataTransfer.files.length) return;
            input.files = e.dataTransfer.files;
            input.dispatchEvent(new Event("change", { bubbles: true }));
        });
    });
})();
