/* Attachments on the reply composer. The requester picks files; each one is
   tagged from its filename, then - when the name says nothing - by asking the
   server to read its first page (the same rules the new-request form uses).
   The tag is a chip with a menu behind it, so a wrong guess is one click to
   fix, and every file's tag posts as reply_doc_type in file order. Without
   JS the bare multi-file input still posts and the server tags on arrival. */
(function () {
    "use strict";

    var wrap = document.querySelector("[data-reply-files]");
    if (!wrap) return;
    var input = wrap.querySelector('input[type="file"]');
    var list = wrap.querySelector("[data-reply-list]");
    var tpl = wrap.querySelector("[data-reply-types]");
    if (!input || !list || !tpl || !window.DataTransfer) return;

    var LABELS = {};
    Array.prototype.forEach.call(tpl.content.querySelectorAll("option"), function (o) { LABELS[o.value] = o.textContent; });
    var RULES = [
        [/shop|cart|(?:^|[^a-z0-9])sc(?:[^a-z0-9]|$)/i, "SC"],
        [/sfo|deviation|selection/i, "SFO"],
        [/rfq|enquiry|request[ _-]*for[ _-]*quot/i, "RFQ"],
        [/quotation|quote|offer|proposal|angebot|offerta/i, "OFFER"],
        [/budget|controlling|kostenstelle/i, "BUDGET_APPROVAL"],
        [/mrm/i, "MRM_APPROVAL"]
    ];
    var files = []; // {file, tag, sniffing, userSet}

    function guess(name) {
        for (var i = 0; i < RULES.length; i++) if (RULES[i][0].test(name)) return RULES[i][1];
        return "OTHER";
    }
    function sniff(entry) {
        if (!window.fetch) return;
        var body = new FormData();
        body.append("file", entry.file);
        entry.sniffing = true;
        fetch("/requests/doc-type", { method: "POST", body: body, credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { entry.sniffing = false; if (d && !entry.userSet && LABELS[d.tag]) entry.tag = d.tag; render(); })
            .catch(function () { entry.sniffing = false; render(); });
    }
    function sync() {
        var dt = new DataTransfer();
        files.forEach(function (f) { dt.items.add(f.file); });
        input.files = dt.files;
    }
    function fsize(n) { return n < 1024 ? n + " B" : n < 1048576 ? Math.round(n / 1024) + " KB" : (n / 1048576).toFixed(1) + " MB"; }
    function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
    function render() {
        list.hidden = !files.length;
        list.innerHTML = "";
        files.forEach(function (f, i) {
            var li = document.createElement("li");
            li.className = "sf-reply__file";
            li.innerHTML = '<span class="sf-reply__name" title="' + esc(f.file.name) + '">' + esc(f.file.name) + '</span>'
                + '<span class="sf-reply__size">' + fsize(f.file.size) + '</span>'
                + '<span class="sf-reply__tag' + (f.sniffing ? ' is-sniffing' : '') + '"></span>'
                + '<button type="button" class="sf-reply__rm" aria-label="Remove ' + esc(f.file.name) + '">&times;</button>';
            var sel = tpl.content.firstElementChild.cloneNode(true);
            sel.value = f.tag;
            sel.title = f.sniffing ? "Reading the document…" : "Change the type if the guess is wrong";
            sel.addEventListener("change", function () { f.tag = sel.value; f.userSet = true; render(); });
            li.querySelector(".sf-reply__tag").appendChild(sel);
            li.querySelector(".sf-reply__rm").addEventListener("click", function () { files.splice(i, 1); sync(); render(); });
            list.appendChild(li);
        });
    }

    input.addEventListener("change", function () {
        Array.prototype.forEach.call(input.files, function (file) {
            if (files.some(function (f) { return f.file.name === file.name && f.file.size === file.size; })) return;
            var entry = { file: file, tag: guess(file.name), sniffing: false, userSet: false };
            files.push(entry);
            if (entry.tag === "OTHER") sniff(entry);
        });
        sync(); render();
    });
}());
