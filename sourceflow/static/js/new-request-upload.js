// Unified dropzone + tagged file list for the New Sourcing Request form.
// Visually one drop target, but keeps the real backend contract intact:
// requester_routes.py's _collect_tagged_files() still expects six named
// fields (sc_file/sfo_file/rfq_file/offer_files/regret_files/other_files),
// so every add/remove/retag rebuilds those real hidden inputs via
// DataTransfer rather than requiring a backend contract change. SC/SFO/RFQ
// are single-file slots (last file tagged wins if more than one is tagged
// the same way); offers/regret/other are multi.
(function () {
    var dropzone = document.querySelector("[data-nr-dropzone]");
    var browseInput = document.getElementById("f_doc_intake");
    var list = document.querySelector("[data-nr-doc-list]");
    var checklist = document.querySelector("[data-checklist]");
    if (!dropzone || !browseInput || !list) return;

    var SINGLE_FIELDS = { SC: "sc_file", SFO: "sfo_file", RFQ: "rfq_file" };
    var MULTI_FIELDS = { OFFER: "offer_files", OTHER: "other_files" };
    var TAG_LABELS = { SC: "Approved Cart", SFO: "Deviation Note/SFO", RFQ: "RFQ", OFFER: "Offer", OTHER: "Other" };
    var GUESS_RULES = [
        // (?:^|[^a-z0-9]) / (?:[^a-z0-9]|$) instead of \b: \b treats "_" as
        // a word character, so it doesn't count as a boundary - a filename
        // like "01_SC_1012597812.docx" (underscore-delimited, a common SAP
        // export convention) would never match \bsc\b even though "SC" is
        // clearly its own token there.
        [/shop|cart|(?:^|[^a-z0-9])sc(?:[^a-z0-9]|$)/i, "SC"],
        [/sfo|selection/i, "SFO"],
        [/rfq|quotation/i, "RFQ"],
        [/offer|quote|proposal/i, "OFFER"],
    ];

    var files = []; // {file, tag, id}
    var nextId = 1;

    function guessTag(filename) {
        for (var i = 0; i < GUESS_RULES.length; i++) {
            if (GUESS_RULES[i][0].test(filename)) return GUESS_RULES[i][1];
        }
        return "OTHER";
    }

    // Suppliers file their quotes under their own reference ("CGC-2026-448.pdf",
    // "GMPL-QTN-2026-092.docx"), which tells the filename rules above nothing -
    // those all land as "Other" and get re-tagged by hand. So when the name is
    // uninformative, ask the server to read the first page and say what the
    // document calls itself. Advisory: it only ever fills in an "Other", never
    // overrides a tag the filename or the requester already settled, and a
    // failed/unsupported sniff just leaves the row as it was.
    function sniffTag(entry) {
        if (!window.fetch || !window.FormData) return;
        var body = new FormData();
        body.append("file", entry.file);
        entry.sniffing = true;
        fetch("/requests/doc-type", { method: "POST", body: body, credentials: "same-origin" })
            .then(function (res) { return res.ok ? res.json() : null; })
            .then(function (data) {
                entry.sniffing = false;
                if (data && !entry.userSet && entry.tag === "OTHER" && TAG_LABELS[data.tag]) {
                    entry.tag = data.tag;
                }
                render();
            })
            .catch(function () { entry.sniffing = false; render(); });
    }

    function syncHiddenInputs() {
        var buckets = { SC: [], SFO: [], RFQ: [], OFFER: [], OTHER: [] };
        files.forEach(function (f) { buckets[f.tag].push(f.file); });

        Object.keys(SINGLE_FIELDS).forEach(function (tag) {
            var input = document.getElementById(SINGLE_FIELDS[tag]);
            if (!input) return;
            var dt = new DataTransfer();
            var arr = buckets[tag];
            if (arr.length) dt.items.add(arr[arr.length - 1]);
            input.files = dt.files;
        });
        Object.keys(MULTI_FIELDS).forEach(function (tag) {
            var input = document.getElementById(MULTI_FIELDS[tag]);
            if (!input) return;
            var dt = new DataTransfer();
            buckets[tag].forEach(function (f) { dt.items.add(f); });
            input.files = dt.files;
        });

        if (checklist) {
            checklist.querySelectorAll("[data-checklist-tag]").forEach(function (item) {
                var tag = item.getAttribute("data-checklist-tag");
                item.classList.toggle("is-done", buckets[tag] && buckets[tag].length > 0);
            });
        }
    }

    function fileIcon() {
        return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"></path><path d="M6 3h8l6 6v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"></path></svg>';
    }

    function render() {
        list.innerHTML = "";
        if (!files.length) {
            var p = document.createElement("p");
            p.className = "sf-doc-list__empty";
            p.textContent = "No documents attached yet.";
            list.appendChild(p);
            syncHiddenInputs();
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
                f.userSet = true;
                syncHiddenInputs();
            });
            if (f.sniffing) {
                var hint = document.createElement("span");
                hint.className = "sf-doc-item__hint";
                hint.textContent = "Reading…";
                row.insertBefore(hint, select);
            }
            row.querySelector(".sf-doc-item__remove").addEventListener("click", function () {
                files = files.filter(function (x) { return x.id !== f.id; });
                render();
            });
            list.appendChild(row);
        });
        syncHiddenInputs();
    }

    function addFiles(fileList) {
        var added = [];
        Array.prototype.forEach.call(fileList, function (file) {
            var entry = { file: file, tag: guessTag(file.name), id: nextId++ };
            files.push(entry);
            added.push(entry);
        });
        render();
        added.forEach(function (entry) {
            if (entry.tag === "OTHER") sniffTag(entry);
        });
    }

    browseInput.addEventListener("change", function () {
        if (browseInput.files && browseInput.files.length) addFiles(browseInput.files);
        browseInput.value = "";
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
