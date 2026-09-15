"""Small local web application for the BalanceGuard proof of concept."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from balance_guard.engine import (
    analyse_statement,
    backtest_transactions,
    build_balance_notifications,
    calculate_what_if_closing_balance,
    check_purchase,
    classify_balance_notification,
    create_demo_plan,
    evaluate_credit_option,
    load_transactions_json,
    monthly_funds_baseline,
)


ROOT = Path(__file__).parent
WEB_ROOT = ROOT / "web"
account, transactions = load_transactions_json(ROOT / "data" / "transactions.json")
plan = create_demo_plan(transactions)
monthly_funds = monthly_funds_baseline(account, transactions)
DEFAULT_WHAT_IF_TRANSACTION_IDS = (
    "TXN-2026082900059",  # R2,500 gaming / crypto-platform debit
    "TXN-2026083000057",  # R60 low-balance notice fee
)


def build_what_if(transaction_ids=DEFAULT_WHAT_IF_TRANSACTION_IDS) -> dict:
    result = calculate_what_if_closing_balance(account, transactions, transaction_ids)
    result["excluded_transactions"] = [
        {
            **transaction,
            "date": transaction["date"].strftime("%d %b"),
        }
        for transaction in result["excluded_transactions"]
    ]
    return result


def build_summary() -> dict:
    analysis = analyse_statement(account, transactions)
    decisions = backtest_transactions(account, transactions, plan)
    notifications = build_balance_notifications(account, transactions, plan)
    warnings = []
    for row in decisions:
        if row["status"] in {"CAUTION", "STOP AND REVIEW"}:
            warnings.append({
                "date": row["date"].strftime("%d %b"),
                "date_value": row["date"].date().isoformat(),
                "narrative": row["narrative"],
                "amount": round(-row["amount"], 2),
                "safe_to_spend": row["safe_to_spend"],
                "status": row["status"],
            })

    stop_warnings = [row for row in warnings if row["status"] == "STOP AND REVIEW"]
    caution_warnings = [row for row in warnings if row["status"] == "CAUTION"]
    first_stop = stop_warnings[0]
    first_negative = next(
        transaction for transaction in transactions if transaction["running_balance"] < 0
    )
    lead_days = (
        first_negative["date"].date()
        - next(row["date"].date() for row in decisions if row["status"] == "STOP AND REVIEW")
    ).days

    # The dashboard shows distinct decision moments instead of a wall of equal
    # alerts: early caution, first budget breach, and largest later impact.
    priority_warnings = []
    for candidate in [
        caution_warnings[0] if caution_warnings else None,
        first_stop,
        max(stop_warnings, key=lambda row: row["amount"]),
    ]:
        if candidate and candidate not in priority_warnings:
            priority_warnings.append(candidate)

    balance_series = [
        {
            "date": transaction["date"].strftime("%d %b"),
            "balance": transaction["running_balance"],
        }
        for transaction in transactions
    ]
    current_notification = classify_balance_notification(
        monthly_funds=monthly_funds,
        current_balance=analysis["closing_balance"],
        remaining_protected=0,
    )
    notification_rows = [
        {
            **notification,
            "date": notification["date"].strftime("%d %b"),
        }
        for notification in notifications
    ]
    return {
        "analysis": analysis,
        "plan": {
            "protected_budget": plan.protected_budget,
            "buffer": plan.buffer,
            "buffer_rate": plan.buffer_rate,
        },
        "headline": {
            "date": first_stop["date"],
            "lead_days": lead_days,
            "safe_to_spend": first_stop["safe_to_spend"],
            "narrative": first_stop["narrative"],
        },
        "warnings": warnings,
        "priority_warnings": priority_warnings,
        "additional_warning_count": len(warnings) - len(priority_warnings),
        "balance_series": balance_series,
        "monthly_funds_baseline": monthly_funds,
        "balance_notifications": notification_rows,
        "current_balance_notification": current_notification,
        "credit_gate": evaluate_credit_option(
            funds_used_percent=current_notification["percent_used"]
        ),
        "what_if": build_what_if(),
    }


class BalanceGuardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/summary":
            self._send_json(build_summary())
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/check", "/api/credit-review", "/api/what-if"}:
            self._send_json({"error": "Not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/what-if":
                transaction_ids = payload.get("transaction_ids", [])
                if not isinstance(transaction_ids, list) or not all(
                    isinstance(transaction_id, str) for transaction_id in transaction_ids
                ):
                    raise ValueError("transaction_ids must be a list of strings")
                result = build_what_if(transaction_ids)
            elif path == "/api/credit-review":
                existing_cardholder = payload.get("existing_cardholder")
                if existing_cardholder not in {True, False, None}:
                    raise ValueError("existing_cardholder must be true, false, or null")
                result = evaluate_credit_option(
                    funds_used_percent=float(payload["funds_used_percent"]),
                    customer_consented=bool(payload.get("customer_consented", False)),
                    affordability_passed=bool(payload.get("affordability_passed", False)),
                    existing_cardholder=existing_cardholder,
                )
            else:
                current_balance = float(payload["current_balance"])
                proposed_amount = float(payload["proposed_amount"])
                remaining_protected = float(payload["remaining_protected"])
                result = check_purchase(
                    current_balance=current_balance,
                    proposed_amount=proposed_amount,
                    remaining_protected=remaining_protected,
                    buffer=float(payload["buffer"]),
                )
                current_notice = classify_balance_notification(
                    monthly_funds=monthly_funds,
                    current_balance=current_balance,
                    remaining_protected=remaining_protected,
                )
                projected_notice = classify_balance_notification(
                    monthly_funds=monthly_funds,
                    current_balance=result["projected_balance"],
                    remaining_protected=remaining_protected,
                )
                result["balance_notification"] = projected_notice
                result["new_balance_notification"] = (
                    projected_notice["threshold"] > current_notice["threshold"]
                )
            self._send_json(result)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._send_json({"error": f"Invalid request: {error}"}, 400)


if __name__ == "__main__":
    address = ("127.0.0.1", 8502)
    print("BalanceGuard is running at http://127.0.0.1:8502")
    ThreadingHTTPServer(address, BalanceGuardHandler).serve_forever()
