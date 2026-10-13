"""Re-run the offer analysis on every case that has offers.

For when the analysis format or logic changes: an analysis stored last week
is in last week's shape, and a buyer opening that case sees the old one. This
brings every case up to the current version, one at a time, printing as it
goes so a long run can be watched.

    python tools/reanalyze_all.py            # every case with OFFER documents
    python tools/reanalyze_all.py 16 9       # just these case ids
    python tools/reanalyze_all.py --stale    # only cases analysed before today
"""

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db                                   # noqa: E402
from routers.buyer_routes import analyze_case_offers   # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only_stale = "--stale" in sys.argv

    if args:
        cases = [db.get_case(int(a)) for a in args]
        cases = [c for c in cases if c]
    else:
        cases = db.list_cases()

    todo = []
    for c in cases:
        if not any(a["doc_type"] == "OFFER" for a in db.list_attachments(c["id"])):
            continue
        if only_stale and str(c.get("offer_analysis_at") or "")[:10] == date.today().isoformat():
            continue
        todo.append(c)

    print(f"{len(todo)} case(s) to analyse\n")
    ok = failed = 0
    started = time.time()
    for n, c in enumerate(todo, 1):
        t0 = time.time()
        print(f"[{n}/{len(todo)}] {c['ticket_no']}  {c['topic_title'][:48]:<48} ", end="", flush=True)
        try:
            r = analyze_case_offers(c["id"], actor="Offer agent (batch)")
        except Exception as exc:                      # noqa: BLE001
            r = {"stored": False, "error": f"{type(exc).__name__}: {exc}"}
        secs = int(time.time() - t0)
        if r["stored"]:
            ok += 1
            print(f"ok  {r['offers']} offer(s), {r['groups']} group(s)  {secs}s")
        else:
            failed += 1
            print(f"FAILED  {r.get('error')}  {secs}s")

    mins = int((time.time() - started) / 60)
    print(f"\n{ok} analysed, {failed} failed, {mins} min")


if __name__ == "__main__":
    main()
