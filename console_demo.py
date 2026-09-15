from pathlib import Path

from balance_guard.engine import (
    analyse_statement,
    backtest_transactions,
    build_balance_notifications,
    calculate_what_if_closing_balance,
    create_demo_plan,
    evaluate_credit_option,
    load_transactions_json,
    monthly_funds_baseline,
)


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}R{abs(value):,.2f}"


account, transactions = load_transactions_json(Path(__file__).parent / "data" / "transactions.json")
analysis = analyse_statement(account, transactions)
plan = create_demo_plan(transactions)
results = backtest_transactions(account, transactions, plan)
monthly_funds = monthly_funds_baseline(account, transactions)
notifications = build_balance_notifications(account, transactions, plan)
what_if = calculate_what_if_closing_balance(
    account,
    transactions,
    ["TXN-2026082900059", "TXN-2026083000057"],
)

print("BALANCEGUARD DEMO")
print(f"Inflows: {money(analysis['inflows'])}")
print(f"Outflows: {money(analysis['outflows'])}")
print(f"Closing balance: {money(analysis['closing_balance'])}")
print(f"Protected monthly plan: {money(plan.protected_budget)}")
print(f"Safety buffer: {money(plan.buffer)}")
print(f"Confirmed monthly funds baseline: {money(monthly_funds)}")
warnings = [row for row in results if row["status"] in {"CAUTION", "STOP AND REVIEW"}]
stops = [row for row in warnings if row["status"] == "STOP AND REVIEW"]
first_stop = stops[0]
priority = [
    next(row for row in warnings if row["status"] == "CAUTION"),
    first_stop,
    max(stops, key=lambda row: -row["amount"]),
]
print(
    f"\nHEADLINE: First Stop and Review on {first_stop['date']:%d %b}, "
    f"with {money(first_stop['safe_to_spend'])} safe to spend."
)
print(f"\nPRIORITY EVENTS ({len(warnings) - len(priority)} additional events grouped)")
for row in priority:
    print(
        f"{row['date']:%d %b} | {row['status']:<15} | "
        f"safe {money(row['safe_to_spend']):>11} | "
        f"spend {money(-row['amount']):>11} | {row['narrative']}"
    )

print("\nPROACTIVE BALANCE NOTIFICATIONS")
for row in notifications:
    print(
        f"{row['threshold']:>2}% | {row['date']:%d %b} | "
        f"observed {row['percent_used']:>6.2f}% used | {row['level']}"
    )

credit_gate = evaluate_credit_option(funds_used_percent=notifications[-1]["percent_used"])
print("\n95% RESPONSIBLE-CREDIT GATE")
print(f"{credit_gate['status']}: {credit_gate['next_step']}")

print("\nWHAT-IF PROOF")
print(f"Actual closing balance: {money(what_if['actual_closing_balance'])}")
for transaction in what_if["excluded_transactions"]:
    print(f"Remove {money(-transaction['amount'])}: {transaction['narrative']}")
print(f"Scenario closing balance: {money(what_if['scenario_closing_balance'])}")
print(f"Balance improvement: {money(what_if['balance_improvement'])}")
print(what_if["caveat"])
