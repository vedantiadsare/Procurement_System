"""The Offer agent: reads quotations and puts them side by side.

Two places quotations turn up. On a case, as OFFER attachments the requester
uploaded - that path already existed as the "Analyze offers" button. And on
a supplier round, as files bidders send back through the portal - that path
is new, and it is the one that makes the agent worth the name: a quotation
arriving fires the agent on its own, so by the time the buyer opens the
round the comparison is already there.

What the model does: reads each document and reports the total, currency and
tax basis it states, and comments on terms. What the code does: strips tax,
converts currencies, ranks, and writes the table. The model is never asked
which offer is cheapest.
"""

import json
from datetime import datetime, timedelta

import comparison
import db
import llm
import parser as sc_parser
import quotation_check
from config import SOURCEFLOW_ROOT

from .base import Agent, RunLog, register


def _latest_submission(files: list, responded_at) -> list:
    """The files that arrived with the supplier's most recent response.
    Falls back to everything if the stamps cannot be compared - a comparison
    that ignores a file is worse than one that reads an old one too."""
    if not files or not responded_at:
        return files
    try:
        cutoff = datetime.fromisoformat(str(responded_at)) - timedelta(seconds=10)
        latest = [f for f in files
                  if f.get("uploaded_at") and datetime.fromisoformat(str(f["uploaded_at"])) >= cutoff]
        return latest or files
    except (TypeError, ValueError):
        return files


@register
class OfferAgent(Agent):
    key = "offer"
    name = "Offer agent"
    tagline = "Reads quotations as they arrive and puts them side by side on one basis."
    perceives = "OFFER documents on a case; files suppliers return through the RFQ portal"
    acts = "Extracts totals, currency and tax basis; normalises and ranks in code; writes the comparison"
    uses_llm = True

    def run(self, log: RunLog, case_id=None, round_id=None, **_):
        if round_id is not None:
            return self._run_round(log, round_id)
        if case_id is not None:
            return self._run_case(log, case_id)
        return self._run_sweep(log)

    # --- a case's uploaded offers --------------------------------------------

    def _run_case(self, log, case_id):
        from routers.buyer_routes import analyze_case_offers
        case = db.get_case(case_id)
        subject = case["ticket_no"] if case else f"case {case_id}"
        result = analyze_case_offers(case_id, actor="Offer agent", log=log)
        if result["stored"]:
            return "ok", (f"Compared {result['offers']} offer(s) in {result['groups']} group(s) "
                          f"on {subject}"), subject
        if result["offers"] == 0:
            return "nothing", result["error"], subject
        return "error", result["error"], subject

    # --- a supplier round's returned quotations -------------------------------

    def _run_round(self, log, round_id):
        round_ = db.get_rfq_round(round_id)
        if round_ is None:
            return "error", "No such round.", f"round {round_id}"
        subject = round_["reference"]

        import supplier_rfq
        quoted = [i for i in db.list_rfq_invitations(round_id) if i["decision"] == "ACCEPTED"]
        docs = []
        superseded = 0
        for inv in quoted:
            who = inv["supplier_name"] or inv["supplier_email"]
            files = db.list_rfq_response_files(inv["id"])
            # A supplier who re-submits has replaced their quotation, not added
            # a second bidder. Only the latest submission - v2 against the
            # others' v1 if they have not revised - is compared; earlier
            # versions stay on the round for the record.
            vers = supplier_rfq.versions(files)
            latest = vers[-1]["files"] if vers else []
            superseded += len(files) - len(latest)
            for f in latest:
                path = SOURCEFLOW_ROOT / f["file_path"]
                if not path.exists():
                    continue
                with open(path, "rb") as fh:
                    text = sc_parser.extract_text(fh, f["file_ext"])
                if text and text.strip():
                    # invitation_id is the stable key back to the bidder. The
                    # supplier name is not: a bare-address invitation gets
                    # renamed to whatever the quotation calls the company.
                    docs.append({"filename": f"{who} — {f['filename']}", "text": text,
                                 "supplier": who, "invitation_id": inv["id"],
                                 "version": len(vers),
                                 "note": inv.get("response_text") or ""})
        log.perceive(f"{subject}: {len(quoted)} supplier(s) have quoted, "
                     f"{len(docs)} readable quotation file(s)"
                     + (f"; {superseded} earlier file(s) superseded by a revision" if superseded else ""))

        if not docs:
            if quoted:
                return "nothing", "Quotations arrived but none had readable text.", subject
            return "nothing", "No quotations yet.", subject

        # One quotation still gets read and recorded - a buyer opening the round
        # should see what the first bidder said, not wait for a second.
        quotes = [comparison.read_quotation(d["text"], d["filename"]) for d in docs]
        # An invitation pasted as a bare address has no name; the document
        # does. Once read, the supplier is called what its quotation says.
        for d, q in zip(docs, quotes):
            if q.get("supplier") and "@" in d["supplier"]:
                d["supplier"] = q["supplier"]
            if not q.get("supplier"):
                q["supplier"] = d["supplier"]
        # Before any ranking: is each submission complete, and does it answer
        # the enquiry? Stored per invitation so the round page can show the
        # requester exactly what to ask each supplier for.
        by_id = {i["id"]: i for i in quoted}
        requirement = quotation_check.requirement_text_for_round(round_)
        pairs_by_inv = {}
        for d, q in zip(docs, quotes):
            pairs_by_inv.setdefault(d["invitation_id"], []).append((d, q))
        flagged = 0
        for inv_id, pairs in pairs_by_inv.items():
            if inv_id not in by_id:
                continue
            supplier = pairs[0][0]["supplier"]
            verdict = quotation_check.check_supplier(pairs, requirement)
            db.set_rfq_invitation_check(inv_id, json.dumps(verdict))
            if quotation_check.needs_a_question(verdict):
                flagged += 1
                log.note(f"{supplier}: "
                         + (f"missing {', '.join(verdict['missing_fields'])}" if verdict["missing_fields"] else "all fields stated")
                         + ("; does not fully cover the enquiry" if verdict["covers"] is False else ""))
        log.act(f"checked {len(pairs_by_inv)} submission(s) for completeness and against the "
                f"enquiry; {flagged} need a question to the supplier")

        table = comparison.compare(quotes)
        log.decide(f"{len(quotes)} quotation(s) read by the model; compared in code on "
                   f"{table.get('target') or 'a common'} basis")

        # The branch that makes this an agent rather than a wrapped function.
        # A quotation that omits its currency or tax basis cannot be ranked
        # fairly - comparing it on an assumption would be the model's guess
        # deciding a supplier's position. So the agent does something else
        # with it: asks. Once per submission, never disclosing the ranking.
        asked = self._ask_for_what_is_missing(log, round_, quoted, docs, quotes)

        from routers.buyer_routes import _comparison_table, _comparison_facts, _tidy_flags
        # "Dell (v2), Orbit (v1)": which submission of each bidder is on the table.
        heads = [f"{d['supplier']} (v{d['version']})" if d.get("version", 1) > 1 else d["supplier"]
                 for d in docs]
        block = [f"COMPARING: {', '.join(heads)}", ""]
        if superseded:
            block.append(f"Latest submission from each supplier; {superseded} earlier file(s) superseded by a revision.")
            block.append("")
        if asked:
            block.append("Awaiting clarification (not ranked on a guess):")
            block += [f"  - {who}: {what}" for who, what in asked]
            block.append("")
        block.append(_comparison_table(table))

        # Anything a supplier typed alongside the file is real context - lead
        # time, validity, a caveat - and belongs in front of the model.
        notes = [f"{d['supplier']}: {d['note']}" for d in docs if d["note"]]
        reference = _comparison_facts(table)
        if notes:
            reference += "\n\nWhat each supplier wrote in their response:\n" + "\n".join(notes)

        pseudo_case = {"topic_title": round_["subject"], "topic_value_inr": None}
        result = llm.analyze_offers(pseudo_case, docs, reference)
        if result["analysis"]:
            block += ["", "Conditions worth flagging:", _tidy_flags(result["analysis"], quotes)]
            log.act("model commented on terms; ranking claims stripped in code")
        elif result["error"]:
            block.append(f"[AI commentary unavailable: {result['error']}]")
            log.note(f"AI commentary unavailable: {result['error']}")

        db.set_rfq_round_analysis(round_id, "\n".join(block))
        log.act(f"wrote the comparison on {subject}")
        return "ok", f"Compared {len(quotes)} quotation(s) on {subject}", subject

    # --- the decision: compare, or ask first ----------------------------------

    def _ask_for_what_is_missing(self, log, round_, invitations, docs, quotes) -> list:
        """For each quotation the model could not fully read, decide whether
        to ask the supplier - and do it. Returns [(supplier, what)] for the
        ones asked, so the comparison can say so.

        Asked once per submission: an invitation carries the stamp of when it
        was last asked, and a supplier is only asked again if they have sent a
        new quotation since. A revision that still omits the tax basis gets
        one more mail; a supplier who has been asked and gone quiet does not
        get nagged every time the agent runs."""
        import notifications
        import supplier_rfq

        by_supplier = {(i["supplier_name"] or i["supplier_email"]): i for i in invitations}
        by_id = {i["id"]: i for i in invitations}
        asked = []
        for doc, quote in zip(docs, quotes):
            if quote.get("error") or quote.get("total") is None:
                # Nothing readable, or no total at all: this is not a gap the
                # supplier can close with one line, it needs a buyer's eye.
                log.decide(f"{doc['supplier']}: {quote.get('error') or 'no total found'} - "
                           f"left for the buyer, not asked")
                continue

            missing = []
            if not quote.get("currency"):
                missing.append("the currency the prices are quoted in")
            if quote.get("tax_included") is None:
                missing.append("whether the prices include tax (GST / VAT), and at what rate")
            if not missing:
                continue

            inv = by_id.get(doc.get("invitation_id")) or by_supplier.get(doc["supplier"])
            if inv is None:
                continue
            responded = str(inv.get("responded_at") or "")
            sent = inv.get("clarified_at")
            drafted = inv.get("clarification_drafted_at")
            if sent and str(sent) >= responded:
                log.decide(f"{doc['supplier']}: quotation still omits "
                           f"{' and '.join(missing)} - buyer asked on {str(sent)[:10]}, waiting")
                asked.append((doc["supplier"], "asked " + str(sent)[:10] + ", awaiting reply"))
                continue
            if drafted and str(drafted) >= responded:
                log.decide(f"{doc['supplier']}: question drafted on {str(drafted)[:10]}, "
                           f"waiting for the buyer to send it")
                asked.append((doc["supplier"], "question drafted - buyer to send"))
                continue

            # The agent writes the question; it does not send it. A supplier
            # hearing from VW is a buyer's act, not the system's - so the draft
            # waits on the round page behind a Send button with a name on it.
            log.decide(f"{doc['supplier']}: quotation does not state {' or '.join(missing)} "
                       f"- cannot be ranked fairly on a guess; drafting a question for the buyer")
            draft = notifications.clarification_text(inv, round_, supplier_rfq.portal_link(inv["token"]), missing)
            db.save_rfq_clarification_draft(inv["id"], "; ".join(missing), draft)
            log.act(f"drafted a clarification to {inv['supplier_email']} asking for "
                    f"{' and '.join(missing)} - awaiting the buyer's send")
            asked.append((doc["supplier"], "question drafted for " + " and ".join(missing) + " - buyer to send"))
        return asked

    # --- no target: look for work -------------------------------------------

    def _run_sweep(self, log):
        """Run now with nothing selected: find rounds where a quotation has
        landed since the last comparison, and do those."""
        done, seen = 0, 0
        for r in db.list_rfq_rounds():
            invs = [i for i in db.list_rfq_invitations(r["id"]) if i["decision"] == "ACCEPTED"]
            if not invs:
                continue
            seen += 1
            latest = max(i["responded_at"] or "" for i in invs)
            if r.get("offer_analysis_at") and str(r["offer_analysis_at"]) >= str(latest):
                continue
            log.decide(f"{r['reference']}: quotation newer than last comparison")
            status, _, _ = self._run_round(log, r["id"])
            if status == "ok":
                done += 1
        log.perceive(f"{seen} round(s) with quotations")
        if not seen:
            return "nothing", "No rounds have quotations yet.", None
        if not done:
            return "nothing", f"{seen} round(s) already up to date.", None
        return "ok", f"Updated the comparison on {done} round(s)", None
