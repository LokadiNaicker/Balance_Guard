from pathlib import Path
import unittest

from balance_guard.engine import (
    analyse_statement,
    backtest_transactions,
    build_balance_notifications,
    calculate_what_if_closing_balance,
    check_purchase,
    create_demo_plan,
    evaluate_credit_option,
    load_transactions_json,
    monthly_funds_baseline,
)


DATA = Path(__file__).parents[1] / "data" / "transactions.json"


class BalanceGuardTests(unittest.TestCase):
    def test_statement_reconciles_to_declared_closing_balance(self):
        account, transactions = load_transactions_json(DATA)
        result = analyse_statement(account, transactions)
        self.assertEqual(result["reconciled_closing"], result["closing_balance"])
        self.assertEqual(result["closing_balance"], -2270.74)
        self.assertEqual(result["outflows"], 53534.14)
        self.assertEqual(result["inflows"], 49388.00)


    def test_first_stop_warning_occurs_on_21_august(self):
        account, transactions = load_transactions_json(DATA)
        plan = create_demo_plan(transactions)
        results = backtest_transactions(account, transactions, plan)
        first_stop = next(row for row in results if row["status"] == "STOP AND REVIEW")
        self.assertEqual(first_stop["date"].date().isoformat(), "2026-08-21")
        self.assertEqual(first_stop["narrative"], "CARD PURCHASE - BAR / NIGHT OUT")
        self.assertEqual(first_stop["safe_to_spend"], 8.26)
        self.assertEqual(first_stop["reward"]["points_at_risk"], 25)
        stop_rows = [row for row in results if row["status"] == "STOP AND REVIEW"]
        bank_fee_rows = [row for row in results if row["category"] == "Bank Fees"]
        self.assertEqual(len(stop_rows), 8)
        self.assertTrue(bank_fee_rows)
        self.assertTrue(all(row["status"] == "NON_ACTIONABLE" for row in bank_fee_rows))


    def test_purchase_that_causes_negative_balance_is_stopped(self):
        result = check_purchase(
            current_balance=381.26,
            proposed_amount=2500.00,
            remaining_protected=92.00,
            buffer=2410.00,
        )
        self.assertEqual(result["status"], "STOP AND REVIEW")
        self.assertEqual(result["projected_balance"], -2118.74)
        self.assertFalse(result["reward"]["eligible_after"])
        self.assertEqual(result["reward"]["projected_points"], 0)


    def test_small_purchase_with_headroom_is_allowed(self):
        result = check_purchase(
            current_balance=20000.00,
            proposed_amount=250.00,
            remaining_protected=5000.00,
            buffer=2000.00,
        )
        self.assertEqual(result["status"], "WITHIN PLAN")
        self.assertEqual(result["safe_to_spend"], 13000.00)
        self.assertTrue(result["reward"]["eligible_after"])
        self.assertEqual(result["reward"]["projected_points"], 25)


    def test_four_balance_thresholds_are_emitted_once(self):
        account, transactions = load_transactions_json(DATA)
        plan = create_demo_plan(transactions)
        self.assertEqual(monthly_funds_baseline(account, transactions), 50075.40)
        notifications = build_balance_notifications(account, transactions, plan)
        self.assertEqual([row["threshold"] for row in notifications], [50, 75, 90, 95])
        self.assertEqual(
            [row["date"].date().isoformat() for row in notifications],
            ["2026-08-06", "2026-08-14", "2026-08-21", "2026-08-26"],
        )
        self.assertEqual([row["percent_used"] for row in notifications], [50.86, 75.26, 91.03, 95.04])


    def test_credit_path_requires_consent_and_affordability(self):
        no_consent = evaluate_credit_option(funds_used_percent=95.04)
        self.assertEqual(no_consent["status"], "CONSENT_REQUIRED")
        self.assertFalse(no_consent["offer_credit"])

        no_affordability = evaluate_credit_option(
            funds_used_percent=95.04,
            customer_consented=True,
        )
        self.assertEqual(no_affordability["status"], "AFFORDABILITY_CHECK_REQUIRED")
        self.assertFalse(no_affordability["offer_credit"])

        eligible = evaluate_credit_option(
            funds_used_percent=95.04,
            customer_consented=True,
            affordability_passed=True,
            existing_cardholder=True,
        )
        self.assertEqual(eligible["status"], "LIMIT_INCREASE_ELIGIBLE")
        self.assertTrue(eligible["offer_credit"])


    def test_what_if_scenario_reconciles_to_positive_close(self):
        account, transactions = load_transactions_json(DATA)
        result = calculate_what_if_closing_balance(
            account,
            transactions,
            ["TXN-2026082900059", "TXN-2026083000057"],
        )
        self.assertEqual(result["actual_closing_balance"], -2270.74)
        self.assertEqual(result["balance_improvement"], 2560.00)
        self.assertEqual(result["scenario_closing_balance"], 289.26)
        self.assertTrue(result["crosses_zero"])


if __name__ == "__main__":
    unittest.main()
