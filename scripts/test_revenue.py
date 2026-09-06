"""Regressions for revenue reporting and published entry points (no paid API)."""
import copy
import sys
import unittest
from pathlib import Path
from revenue_report import summarize, yen
from generate_archive_pages import render_sitemap


class RevenueTest(unittest.TestCase):
    def setUp(self):
        self.ledger = {"version": 1, "orders": [], "expenses": [], "cash": []}

    def order(self, status="confirmed", **kw):
        row = dict(id="order-1", date="2026-09-06", status=status, gross_yen=3000, fee_yen=0)
        row.update(kw)
        self.ledger["orders"].append(row)

    def test_pending_is_not_revenue_or_cash(self):
        self.order("pending")
        r = summarize(self.ledger)
        self.assertEqual(r["pending_yen"], 3000)
        self.assertEqual((r["contribution_yen"], r["bank_net_yen"]), (0, 0))

    def test_fee_refund_expense_cash_separate(self):
        self.order(fee_yen=660, refund_yen=1000, labor_minutes=90)
        self.ledger["expenses"] = [dict(id="expense-1", date="2026-09-06", yen=100)]
        self.ledger["cash"] = [dict(id="cash-1", date="2026-09-06", yen=1180)]
        r = summarize(self.ledger)
        self.assertEqual(r["contribution_yen"], 1240)
        self.assertEqual(r["bank_net_yen"], 1180)
        self.assertEqual(r["labor_minutes"], 90)

    def test_duplicate_rejected(self):
        self.order()
        self.ledger["orders"].append(copy.deepcopy(self.ledger["orders"][0]))
        with self.assertRaises(ValueError):
            summarize(self.ledger)

    def test_canceled_excluded(self):
        self.order("canceled")
        self.assertEqual(summarize(self.ledger)["contribution_yen"], 0)

    def test_invalid_amounts(self):
        for val in (True, 1.2, "100"):
            with self.assertRaises(ValueError):
                yen(val)
        self.order(refund_yen=3001)
        with self.assertRaises(ValueError):
            summarize(self.ledger)

    def test_pending_fee_rejected(self):
        self.order("pending", fee_yen=660)
        with self.assertRaises(ValueError):
            summarize(self.ledger)

    def test_routes_in_sitemap(self):
        root = Path(__file__).resolve().parents[1]
        sitemap = render_sitemap([], site_root=root / "web")
        for name in ("services.html", "watch-champions-league.html"):
            self.assertIn("https://collespo.com/" + name, sitemap)
            self.assertTrue((root / "web" / name).is_file())


if __name__ == "__main__":
    # run_checks.py は各テストに一時フォルダを argv[1] で渡す。
    # unittest.main() はその argv をテスト名として読むので、
    # 「そんなテストは無い」で必ず落ちる。しかも unittest の出力は
    # stderr なので、stdout の最終行しか見ない検査には
    # 「(出力なし)」としか残らず、赤の理由が分からなかった。
    #
    # このリポジトリのテストは、最後に ALL OK を stdout へ出して
    # 0/1 で終わる形で揃っている。ここも同じにする。
    result = unittest.main(argv=[sys.argv[0]], exit=False,
                           verbosity=0).result
    bad = len(result.failures) + len(result.errors)
    print("\nALL OK" if not bad else "\n%d FAILURES" % bad)
    sys.exit(1 if bad else 0)
