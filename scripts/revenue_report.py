"""Report recorded revenue separately from pending claims and cash received.

Private ledger: build/revenue-private/ledger.json, never in web/ or data/.
An order has one row (update its status; do not append copies).
Cash movements and expenses have separate dated, signed-yen entries.
This is an operating report, not a tax return or an accounting system.
"""
import argparse
import json
from datetime import date
from pathlib import Path


def yen(value):
    if type(value) is not int:
        raise ValueError("Yen amounts must be integers")
    return value


def summarize(ledger):
    if ledger.get("version") != 1:
        raise ValueError("Unsupported ledger version")
    totals = {"inquiries": 0, "pending_yen": 0, "confirmed_gross_yen": 0,
              "confirmed_fee_yen": 0, "expenses_yen": 0, "bank_net_yen": 0,
              "labor_minutes": 0, "confirmed_orders": 0}
    seen = set()
    for collection in ("orders", "expenses", "cash"):
        rows = ledger.get(collection)
        if not isinstance(rows, list):
            raise ValueError(f"{collection} must be a list")
        for row in rows:
            ref = row.get("id")
            if not isinstance(ref, str) or not ref or ref in seen:
                raise ValueError("Missing or duplicate record id")
            seen.add(ref)
            date.fromisoformat(row["date"])
            if collection == "orders":
                status = row["status"]
                if status not in ("inquiry", "pending", "confirmed", "canceled"):
                    raise ValueError("Invalid order status")
                gross, fee, refund = (yen(row.get(k, 0)) for k in ("gross_yen", "fee_yen", "refund_yen"))
                minutes = yen(row.get("labor_minutes", 0))
                if min(gross, fee, refund, minutes) < 0 or refund > gross:
                    raise ValueError("Invalid order amounts")
                if status != "confirmed" and (fee or refund):
                    raise ValueError("Fee/refund belongs to a confirmed order; other expenses go in expenses")
                totals["labor_minutes"] += minutes
                if status == "inquiry":
                    totals["inquiries"] += 1
                elif status == "pending":
                    totals["pending_yen"] += gross
                elif status == "confirmed":
                    totals["confirmed_orders"] += 1
                    totals["confirmed_gross_yen"] += gross - refund
                    totals["confirmed_fee_yen"] += fee
            elif collection == "expenses":
                value = yen(row["yen"])
                if value < 0:
                    raise ValueError("Expenses must be nonnegative")
                totals["expenses_yen"] += value
            else:
                # Bank deposits are positive, paid-out refunds negative.
                # Fees already withheld from deposits must not be subtracted again.
                totals["bank_net_yen"] += yen(row["yen"])
    totals["contribution_yen"] = totals["confirmed_gross_yen"] - totals["confirmed_fee_yen"] - totals["expenses_yen"]
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="build/revenue-private/ledger.json")
    parser.add_argument("--init", action="store_true", help="Create an empty ledger, refusing to overwrite")
    args = parser.parse_args()
    path = Path(args.ledger)
    if args.init:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as f:
            json.dump({"version": 1, "orders": [], "expenses": [], "cash": []}, f, indent=2)
    result = summarize(json.loads(path.read_text(encoding="utf-8-sig")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Recorded totals only. Pending is not revenue. Cash is separate. Fixed costs, tax and labor are excluded unless recorded.")


if __name__ == "__main__":
    main()
