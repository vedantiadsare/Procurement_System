"""Supplier RFQ rounds: float an enquiry to a set of bidders, collect their
quotations back through a tokenised page.

The shape of the problem is different from everything else in Samagra. Every
other actor here has an account; a supplier does not, and never will - they
are outside VW's network and will not be given one to quote once. So the
model is:

  * the enquiry and its documents go out by mail, because that is the only
    channel a supplier definitely has;
  * a per-supplier token is the only credential, carried in the link;
  * the token grants access to exactly one invitation - never to a case, a
    queue, or another bidder's response.

Deadlines are enforced on read as well as on write. A round whose date has
passed is closed whether or not anyone pressed a button, so a link that leaks
after the fact opens nothing.
"""

import json
import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

import db
import notifications
from config import (ALLOWED_EXTENSIONS, MAX_FILE_MB, public_base_url,
                    REPO_DIR, RFQ_MAX_SUPPLIERS, SOURCEFLOW_ROOT)

RFQ_DIR = SOURCEFLOW_ROOT / "rfq_rounds"
RFQ_DIR.mkdir(parents=True, exist_ok=True)

# Deliberately permissive: this validates that something is addressable, not
# that it is a real mailbox. Rejecting a supplier's unusual-but-valid address
# is a worse failure than letting the SMTP server bounce it.
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

# "Name <a@b.com>", "a@b.com", or a bare address on its own line.
_NAMED_RE = re.compile(r"^\s*(?P<name>[^<>]+?)\s*<\s*(?P<email>[^<>\s]+)\s*>\s*$")


def new_reference() -> str:
    """RFQ-YYYYMMDD-NNNN. Dated because a buyer refers to "the enquiry we sent
    last Tuesday" far more often than to a row id."""
    stamp = date.today().strftime("%Y%m%d")
    return f"RFQ-{stamp}-{secrets.randbelow(9000) + 1000}"


def parse_recipients(raw: str) -> tuple:
    """Free text to [{"name", "email"}], plus a list of unusable lines.

    Buyers paste this out of Outlook or a spreadsheet, so the separators are
    whatever came with it - newlines, commas, semicolons - and the entries are
    a mix of bare addresses and "Name <addr>". Anything that cannot be read is
    handed back rather than dropped, so nobody discovers a typo by noticing a
    supplier never quoted.
    """
    people, bad, seen = [], [], set()
    for chunk in re.split(r"[\n,;]+", raw or ""):
        entry = chunk.strip()
        if not entry:
            continue
        named = _NAMED_RE.match(entry)
        name, email = (named.group("name"), named.group("email")) if named else (None, entry)
        email = email.strip().strip("<>")
        if not _EMAIL_RE.match(email):
            bad.append(entry)
            continue
        key = email.lower()
        if key in seen:          # the same bidder pasted twice is not two bidders
            continue
        seen.add(key)
        people.append({"name": (name or "").strip() or None, "email": email})
    return people, bad


def validate(subject, recipients, bad, closes_on, files) -> list:
    errors = []
    if not (subject or "").strip():
        errors.append("Give the enquiry a subject - suppliers see it as the mail's subject line.")
    if not recipients:
        errors.append("Add at least one supplier email address.")
    if bad:
        errors.append("These don't look like email addresses: " + ", ".join(bad[:5])
                      + ("..." if len(bad) > 5 else ""))
    if len(recipients) > RFQ_MAX_SUPPLIERS:
        errors.append(f"That's {len(recipients)} addresses. This screen sends to at most "
                      f"{RFQ_MAX_SUPPLIERS} - an enquiry to more than that is a mailing list, "
                      f"not a sourcing round.")
    if not closes_on:
        errors.append("Set the date suppliers must respond by.")
    elif closes_on < date.today():
        errors.append("The response deadline is in the past.")
    for f in files:
        if f["ext"] not in ALLOWED_EXTENSIONS:
            errors.append(f"{f['filename']}: only {', '.join(sorted(ALLOWED_EXTENSIONS))} are accepted.")
        if f["size_bytes"] > MAX_FILE_MB * 1024 * 1024:
            errors.append(f"{f['filename']} is over the {MAX_FILE_MB} MB limit.")

    # The enquiry documents travel with the mail, so the transport's own limit
    # decides what can go out - and Graph's is far below the per-file limit
    # this form otherwise allows. Caught here, while the buyer still has the
    # form in front of them: the alternative is a round that gets created and
    # then fails for every bidder with nothing but a new round to recover by.
    if files and notifications.transport_name() == "graph":
        import mailbox
        total = sum(f["size_bytes"] for f in files)
        if total > mailbox.GRAPH_INLINE_ATTACHMENT_LIMIT:
            errors.append(
                f"These {len(files)} documents come to {total // (1024 * 1024)} MB together. "
                f"Mail can carry about {mailbox.GRAPH_INLINE_ATTACHMENT_LIMIT // (1024 * 1024)} MB "
                f"per enquiry - send fewer or smaller files.")
    return errors


def _round_dir(reference: str) -> Path:
    path = RFQ_DIR / reference
    path.mkdir(parents=True, exist_ok=True)
    return path


def _store(folder: Path, files: list) -> list:
    """Writes uploads to disk, de-duplicating names, and returns what landed.

    Creates its own folder: responses go in a subdirectory of the round, and
    only the round's own directory is made up front."""
    folder.mkdir(parents=True, exist_ok=True)
    stored, used = [], set()
    for f in files:
        name = f["filename"]
        base, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
        candidate, i = name, 1
        while candidate in used:
            candidate = f"{base}_{i}.{ext}" if ext else f"{base}_{i}"
            i += 1
        used.add(candidate)
        (folder / candidate).write_bytes(f["bytes"])
        stored.append({**f, "filename": candidate,
                       "path": str((folder / candidate).relative_to(SOURCEFLOW_ROOT))})
    return stored


def versions(files: list) -> list:
    """Group a supplier's returned files into the submissions they arrived
    in: v1, v2, ... with the last one current.

    A supplier who sends a revision has replaced their quotation, and a
    buyer needs to see that as "v2 - current" beside "v1", not as two files
    of equal standing. Files land within seconds of each other when they are
    one submission; a gap of more than a minute is a new one.
    """
    from datetime import datetime, timedelta
    ordered = sorted(files, key=lambda f: str(f.get("uploaded_at") or ""))
    # Files recorded with their submission number are grouped by it - each
    # send is its own version however quickly it follows the last. Only files
    # from before that was recorded fall back to the time-gap rule below.
    if ordered and all(f.get("submission") for f in ordered):
        groups = []
        for f in ordered:
            if not groups or groups[-1]["_n"] != f["submission"]:
                groups.append({"_n": f["submission"], "version": len(groups) + 1,
                               "at": f.get("uploaded_at"), "files": []})
            groups[-1]["files"].append(f)
        for g in groups:
            g.pop("_n")
            g["current"] = g is groups[-1]
        return groups
    groups = []
    last_at = None
    for f in ordered:
        try:
            at = datetime.fromisoformat(str(f["uploaded_at"]))
        except (TypeError, ValueError):
            at = None
        if not groups or at is None or last_at is None or at - last_at > timedelta(seconds=60):
            groups.append({"version": len(groups) + 1, "at": f.get("uploaded_at"), "files": []})
        groups[-1]["files"].append(f)
        last_at = at or last_at
    for g in groups:
        g["current"] = g is groups[-1]
    return groups


def current_files(files: list) -> list:
    """The files of the latest submission only - what the comparison reads."""
    v = versions(files)
    return v[-1]["files"] if v else []


def portal_link(token: str) -> str:
    return f"{public_base_url()}/rfq/{token}"


def create_round(subject, message, created_by, closes_on, recipients, files,
                 case_id=None, created_by_email=None, infosec_answers=None) -> dict:
    """Creates the round, stores the documents, then mails every bidder.

    The mail loop never raises: one bad address must not stop the other
    nineteen going out. A failure is recorded against that invitation so the
    buyer can see exactly who did not get it and resend."""
    reference = new_reference()
    folder = _round_dir(reference)
    stored = _store(folder, files)

    # End of the chosen day, not the start - "respond by Friday" means Friday
    # is usable, which is not what a bare date would give.
    closes_at = datetime.combine(closes_on, datetime.max.time()).isoformat(timespec="seconds")

    round_id = db.insert_rfq_round(reference, subject, message, created_by, closes_at,
                               case_id, created_by_email,
                               json.dumps(infosec_answers) if infosec_answers else None)
    for f in stored:
        db.insert_rfq_document(round_id, f.get("doc_type"), f["filename"], f["path"],
                               f["ext"], f["size_bytes"])

    attachments = [{"filename": f["filename"], "bytes": f["bytes"]} for f in stored]
    round_ = db.get_rfq_round(round_id)

    # Named once rather than per supplier: the fallback error text below
    # should say which transport was missing, and _graph_available() does
    # file I/O and possibly a token refresh every time it is asked.
    transport = notifications.transport_name()

    sent = failed = 0
    for person in recipients:
        token = secrets.token_urlsafe(32)
        invitation_id = db.insert_rfq_invitation(round_id, person["name"], person["email"], token)
        invitation = {"supplier_name": person["name"], "supplier_email": person["email"]}
        try:
            result = notifications.notify_supplier_invited(
                invitation, round_, portal_link(token), attachments)
            error = None if result.get("sent") else (
                result.get("error") or f"No mail transport configured (transport: {transport})")
        except Exception as exc:                      # noqa: BLE001 - see docstring
            error = str(exc)
        db.mark_rfq_invitation_sent(invitation_id, error)
        if error:
            failed += 1
        else:
            sent += 1

    return {"round_id": round_id, "reference": reference, "sent": sent, "failed": failed,
            "documents": len(stored)}


def extend_round(round_id, closes_on) -> dict:
    """Push the deadline out and tell everyone still invited.

    Suppliers who already quoted are mailed too: the point of an extension is
    usually that the buyer wants more or better quotes, and a bidder who has
    already sent one may want to revise it."""
    closes_at = datetime.combine(closes_on, datetime.max.time()).isoformat(timespec="seconds")
    db.set_rfq_round_deadline(round_id, closes_at)
    round_ = db.get_rfq_round(round_id)

    # Counted on what actually left, not on what was attempted: send_email
    # degrades to sent=False rather than raising, so counting the loop would
    # report "20 suppliers told" on a round where nothing went out.
    told = failed = 0
    for invitation in db.list_rfq_invitations(round_id):
        try:
            result = notifications.notify_supplier_deadline_changed(
                invitation, round_, portal_link(invitation["token"]))
            ok = bool(result.get("sent"))
        except Exception:                             # noqa: BLE001
            ok = False
        if ok:
            told += 1
        else:
            failed += 1
    return {"notified": told, "failed": failed, "closes_at": closes_at}


def is_open(round_: dict) -> bool:
    """A round is open only if it says so AND the date has not passed.

    Checked on every supplier request rather than by a nightly job: nothing
    sweeps expired rounds, so the deadline has to be enforced at the moment
    somebody tries to use the link."""
    if not round_ or round_.get("status") != "OPEN":
        return False
    try:
        return datetime.fromisoformat(str(round_["closes_at"])) >= datetime.now()
    except (TypeError, ValueError):
        return False


def record_response(round_, decision, text, files) -> dict:
    """Store a supplier's reply. Re-submitting is allowed while the round is
    open - a revised quotation is normal - and replaces the previous text but
    adds to the file list rather than deleting what was sent before."""
    stored = _store(_round_dir(round_["reference"]) / "responses", files)
    submission = db.next_rfq_submission(round_["invitation_id"]) if stored else None
    for f in stored:
        db.insert_rfq_response_file(round_["invitation_id"], f["filename"], f["path"],
                                    f["ext"], f["size_bytes"], submission=submission)
    # What they said before this answer - round_ was read before the update -
    # so the requester's mail can say "withdrew" or "changed their mind"
    # rather than describe each answer as if it were the first.
    previous = round_.get("decision")
    db.record_rfq_response(round_["invitation_id"], decision, text, files=len(stored))

    try:
        notifications.notify_buyer_supplier_responded(
            round_, {**round_, "response_text": text}, decision, previous=previous)
    except Exception:                                 # noqa: BLE001
        pass

    # A quotation landing is what the Offer agent exists for. Fired on a
    # thread so the supplier gets their confirmation page at once rather than
    # after the model has finished reading - and a failure in the agent shows
    # up in its run log, never on the supplier's screen.
    if decision == "ACCEPTED" and stored:
        _fire_offer_agent(round_["id"])
    return {"files": len(stored)}


def response_history(invitation) -> list:
    """The supplier's answers in order, each named for what it meant at the
    time: [{"label", "at", "tone"}]. An invitation answered before the
    history was kept has only its latest answer, shown as that."""
    try:
        history = json.loads(invitation.get("response_history") or "[]")
    except (TypeError, ValueError):
        history = []
    if not history and invitation.get("responded_at"):
        history = [{"decision": invitation.get("decision"), "at": invitation["responded_at"]}]

    steps, quoted_before = [], False
    for h in history:
        if h.get("decision") == "ACCEPTED":
            label = "Revised quotation" if quoted_before else "Quoted"
            if not quoted_before and steps:
                label = "Quoted after declining"
            tone, quoted_before = "quoted", True
        else:
            label, tone = ("Withdrew quotation", "withdrew") if quoted_before else ("Declined", "declined")
            quoted_before = False
        steps.append({"label": label, "at": h.get("at"), "tone": tone})
    return steps


def _fire_offer_agent(round_id):
    import threading

    def _go():
        try:
            import agents
            agents.get("offer").execute(trigger="auto", actor="system", round_id=round_id)
        except Exception:                             # noqa: BLE001 - execute() records it
            pass

    threading.Thread(target=_go, name=f"offer-agent-round-{round_id}", daemon=True).start()
