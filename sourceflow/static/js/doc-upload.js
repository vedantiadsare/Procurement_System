// Single dropzone + tagged file list for the Documents card: every dropped
// or browsed file gets a guessed document-type tag (correctable via the
// row's own dropdown) instead of six separate upload slots. Drives the
// "Before you submit" checklist live, since both read the same in-memory
// file list.
//
// NOTE for real implementation: this keeps one aggregate <input
// id="f_doc_files"> in sync via DataTransfer so the files actually travel
// with the form, but the backend today expects fixed field names
// (sc_file/sfo_file/rfq_file/offer_files/regret_files/other_files). Routing
// a tagged flat list to those slots - or changing the route/validators to
// accept parallel files[]/doc_types[] arrays - is a real contract change to
// make when this stops being a preview.

(function () {
    var dropzone = document.querySelector("[data-dropzone]");
    var input = document.getElementById("f_doc_files");
    var list = document.querySelector("[data-doc-list]");
    var emptyMsg = document.querySelector("[data-doc-list-empty]");
    var checklist = document.querySelector("[data-checklist]");
    if (!dropzone || !input || !list) return;

    var TAG_LABELS = {
        SC: "Approved Cart",
        SFO: "Signed SFO",
        RFQ: "RFQ",
        OFFER: "Offer",
        REGRET: "Regret",
        OTHER: "Other",
    };
    var GUESS_RULES = [
        [/shop|cart|\bsc\b/i, "SC"],
        [/sfo|selection/i, "SFO"],
        [/rfq|quotation/i, "RFQ"],
        [/regret|declin/i, "REGRET"],
        [/offer|quote|proposal/i, "OFFER"],
    ];

    var files = []; // { file, tag, id }
    var nextId = 1;

    function guessTag(filename) {
        for (var i = 0; i < GUESS_RULES.length; i++) {
            if (GUESS_RULES[i][0].test(filename)) return GUESS_RULES[i][1];
        }
        return "OTHER";
    }

    function syncInput() {
        var dt = new DataTransfer();
        files.forEach(function (f) { dt.items.add(f.file); });
        input.files = dt.files;
    }

    function updateChecklist() {
        if (!checklist) return;
        var present = {};
        files.forEach(function (f) { present[f.tag] = true; });
        checklist.querySelectorAll("[data-checklist-tag]").forEach(function (item) {
            var tag = item.getAttribute("data-checklist-tag");
            item.classList.toggle("is-done", !!present[tag]);
        });
    }

    function fileIcon() {
        return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"></path><path d="M6 3h8l6 6v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"></path></svg>';
    }

    function render() {
        list.innerHTML = "";
        if (!files.length) {
            var p = document.createElement("p");
            p.className = "sf-doc-list__empty";
            p.setAttribute("data-doc-list-empty", "");
            p.textContent = "No documents attached yet.";
            list.appendChild(p);
            updateChecklist();
            return;
        }
        files.forEach(function (f) {
            var row = document.createElement("div");
            row.className = "sf-doc-item";
            row.innerHTML =
                '<span class="sf-doc-item__icon">' + fileIcon() + '</span>' +
                '<span class="sf-doc-item__name">' + f.file.name + '</span>' +
                '<select class="sf-doc-item__tag" data-tag-select></select>' +
                '<button type="button" class="sf-doc-item__remove" title="Remove">' +
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>' +
                '</button>';
            var select = row.querySelector("[data-tag-select]");
            Object.keys(TAG_LABELS).forEach(function (tag) {
                var opt = document.createElement("option");
                opt.value = tag;
                opt.textContent = TAG_LABELS[tag];
                if (tag === f.tag) opt.selected = true;
                select.appendChild(opt);
            });
            select.addEventListener("change", function () {
                f.tag = select.value;
                updateChecklist();
            });
            row.querySelector(".sf-doc-item__remove").addEventListener("click", function () {
                files = files.filter(function (x) { return x.id !== f.id; });
                syncInput();
                render();
            });
            list.appendChild(row);
        });
        updateChecklist();
    }

    function addFiles(fileList) {
        Array.prototype.forEach.call(fileList, function (file) {
            files.push({ file: file, tag: guessTag(file.name), id: nextId++ });
        });
        syncInput();
        render();
    }

    input.addEventListener("change", function () {
        if (input.files && input.files.length) addFiles(input.files);
    });

    dropzone.addEventListener("dragover", function (e) {
        e.preventDefault();
        dropzone.classList.add("is-dragover");
    });
    dropzone.addEventListener("dragleave", function () {
        dropzone.classList.remove("is-dragover");
    });
    dropzone.addEventListener("drop", function (e) {
        e.preventDefault();
        dropzone.classList.remove("is-dragover");
        if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
    });

    render();
})();
