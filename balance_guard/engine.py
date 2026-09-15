"""Transparent, rule-based cash-flow calculations.

The module intentionally uses no machine-learning models. Each recommendation can
be traced back to a balance, a customer-approved reserve, and a buffer rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable


# Categories we ring-fence to prevent the customer from spending their rent/grocery money.
# In production, the customer would select these during onboarding.
PROTECTED_CATEGORIES = {
    "Fixed Commitments",
    "Debit Order",
    "Groceries",
    "Transport",
}

# Transactions that hit the account but aren't initiated at a card machine. 
# We can't throw a "Stop and Review" screen for a bank fee because the customer 
# cannot decline it. These are bypassed by the rule engine.
NON_ACTIONABLE_CATEGORIES = {"Bank Fees"}

WEEKLY_BUFFER_REWARD_POINTS = 25

# Curveball requirement: notify once as the customer's confirmed monthly funds
# are spent down. The tuple order is intentional and is used for the timeline.
BALANCE_NOTIFICATION_THRESHOLDS = (
    (50, "INFORMATIONAL"),
    (75, "WARNING"),
    (90, "CRITICAL"),
    (95, "CRITICAL"),
)


@dataclass(frozen=True)
class StatementPlan:
    salary: float
    protected_budget: float
    buffer: float
    buffer_rate: float = 0.05


def _money(value: Any) -> float:
    """Helper to safely extract float amounts, handling nested dicts from the raw JSON."""
    if isinstance(value, dict):
        value = value.get("amount", 0)
    return round(float(value), 2)


def load_transactions_json(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load the assessment JSON and return normalized transactions.
    
    Sorts everything chronologically to ensure the backtest replays 
    the month exactly as it happened.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    transactions: list[dict[str, Any]] = []
    for item in payload["statementLines"]:
        transactions.append(
            {
                "date": datetime.fromisoformat(item["transactionDate"]),
                "narrative": item["narrative"],
                "category": item["transactionCategory"]["transactionCategoryName"],
                "type": item["transactionType"],
                "amount": _money(item["amount"]),
                "running_balance": _money(item["runningBalance"]),
                "transaction_id": item["transactionId"],
            }
        )
    transactions.sort(key=lambda transaction: transaction["date"])
    return payload["account"], transactions


def is_protected(transaction: dict[str, Any]) -> bool:
    """Check if spending belongs to the customer's protected plan.
    
    Catches specific edge cases like 'Family Support' transfers which 
    aren't standard retail categories but are essential commitments.
    """
    if transaction["category"] in PROTECTED_CATEGORIES:
        return True
    if transaction["category"] == "Transfers":
        narrative = transaction["narrative"].upper()
        return "FAMILY SUPPORT" in narrative or "SAVINGS POCKET" in narrative
    return False


def is_non_actionable(transaction: dict[str, Any]) -> bool:
    """Return whether a debit should affect cash flow without creating an alert."""
    return transaction["category"] in NON_ACTIONABLE_CATEGORIES


def preview_buffer_reward(
    *,
    current_balance: float,
    proposed_amount: float,
    remaining_protected: float,
    buffer: float,
    checkpoint_points: int = WEEKLY_BUFFER_REWARD_POINTS,
) -> dict[str, Any]:
    """Calculate potential gamification rewards for the Buffer Builder program.

    Points are awarded only at a weekly checkpoint. We preview eligibility 
    before the transaction goes through. If we rewarded points per-transaction, 
    users would split a R100 purchase into ten R10 purchases just to farm points.
    """
    proposed_amount = abs(float(proposed_amount))
    required_balance = max(float(remaining_protected), 0.0) + max(float(buffer), 0.0)
    projected_balance = float(current_balance) - proposed_amount
    
    eligible_before = float(current_balance) >= required_balance
    eligible_after = projected_balance >= required_balance
    headroom_after = projected_balance - required_balance
    shortfall_after = max(-headroom_after, 0.0)

    if eligible_after:
        message = (
            f"This payment keeps the full plan and buffer covered. "
            f"You remain eligible for {checkpoint_points} weekly points."
        )
    elif eligible_before:
        message = (
            f"This payment would put {checkpoint_points} weekly points at risk "
            "because it moves the account below the protected threshold."
        )
    else:
        message = (
            "The account is already below the protected threshold. "
            "No weekly points are currently projected."
        )

    return {
        "program": "BUFFER BUILDER",
        "eligible_before": eligible_before,
        "eligible_after": eligible_after,
        "projected_points": checkpoint_points if eligible_after else 0,
        "points_at_risk": checkpoint_points if eligible_before and not eligible_after else 0,
        "required_balance": round(required_balance, 2),
        "headroom_after": round(headroom_after, 2),
        "shortfall_after": round(shortfall_after, 2),
        "message": message,
    }


def create_demo_plan(transactions: Iterable[dict[str, Any]], buffer_rate: float = 0.05) -> StatementPlan:
    """Build the baseline financial plan from the supplied complete month.

    Production would use known debit orders plus the median of the previous three
    complete months. Because the assessment dataset only provides one month, 
    we use its observed protected spend as the backtest plan.
    """
    transactions = list(transactions)
    salary = sum(
        transaction["amount"]
        for transaction in transactions
        if transaction["category"] == "Income / Salary" and transaction["amount"] > 0
    )
    protected_budget = sum(
        -transaction["amount"]
        for transaction in transactions
        if transaction["amount"] < 0 and is_protected(transaction)
    )
    return StatementPlan(
        salary=round(salary, 2),
        protected_budget=round(protected_budget, 2),
        buffer=round(salary * buffer_rate, 2), # Buffer scales safely with income
        buffer_rate=buffer_rate,
    )


def monthly_funds_baseline(
    account: dict[str, Any], transactions: Iterable[dict[str, Any]]
) -> float:
    """Establish the total confirmed liquidity at the start of the salary cycle.

    The baseline contains the opening balance and salary credits. We intentionally 
    exclude later refunds from this forecast so we don't artificially inflate 
    the customer's perceived monthly budget.
    """
    opening = _money(account["openingBalance"])
    salary_credits = sum(
        transaction["amount"]
        for transaction in transactions
        if transaction["category"] == "Income / Salary" and transaction["amount"] > 0
    )
    return round(max(opening + salary_credits, 0.0), 2)


def classify_balance_notification(
    *,
    monthly_funds: float,
    current_balance: float,
    remaining_protected: float = 0.0,
) -> dict[str, Any]:
    """Calculate the pacing of discretionary spend (Curveball Addendum).
    
    Dynamically tracks the percentage of the monthly budget used and locks 
    into predefined thresholds (50/75/90/95) to give progressive warnings.
    """
    monthly_funds = max(float(monthly_funds), 0.0)
    current_balance = float(current_balance)
    
    if monthly_funds == 0:
        percent_used = 0.0
        used_amount = 0.0
    else:
        used_amount = max(monthly_funds - current_balance, 0.0)
        percent_used = used_amount / monthly_funds * 100

    threshold = 0
    level = "NORMAL"
    for candidate, candidate_level in BALANCE_NOTIFICATION_THRESHOLDS:
        if percent_used >= candidate:
            threshold = candidate
            level = candidate_level

    remaining_funds = max(current_balance, 0.0)
    protected = max(float(remaining_protected), 0.0)
    
    if threshold == 0:
        title = "Monthly funds on track"
        message = "Less than half of confirmed monthly funds have been used."
    elif threshold == 50:
        title = "50% of monthly funds used"
        message = (
            f"Informational update: {percent_used:.1f}% of confirmed monthly funds "
            f"has been used and R{remaining_funds:,.2f} remains."
        )
    elif threshold == 75:
        title = "75% of monthly funds used"
        message = (
            f"Spending warning: {percent_used:.1f}% has been used. "
            f"R{protected:,.2f} is still reserved for upcoming commitments."
        )
    elif threshold == 90:
        title = "90% of monthly funds used"
        message = (
            f"Critical spending alert: {percent_used:.1f}% has been used. "
            "Review non-essential payments before continuing."
        )
    else:
        title = "Only 5% of monthly funds remains"
        message = (
            f"Critical balance alert: {percent_used:.1f}% has been used. "
            "Review upcoming commitments and choose whether to explore support options."
        )

    return {
        "threshold": threshold,
        "level": level,
        "percent_used": round(percent_used, 2),
        "used_amount": round(used_amount, 2),
        "remaining_funds": round(remaining_funds, 2),
        "remaining_protected": round(protected, 2),
        "title": title,
        "message": message,
        "credit_review_available": threshold >= 95,
    }


def build_balance_notifications(
    account: dict[str, Any],
    transactions: Iterable[dict[str, Any]],
    plan: StatementPlan,
) -> list[dict[str, Any]]:
    """State tracker to emit monthly pacing alerts without spamming the user.

    If a massive transaction pushes the user past both the 50% and 75% thresholds 
    simultaneously, this logic ensures we only emit the highest severity alert (75%).
    This prevents alert fatigue.
    """
    transactions = list(transactions)
    monthly_funds = monthly_funds_baseline(account, transactions)
    has_salary = any(
        transaction["category"] == "Income / Salary" and transaction["amount"] > 0
        for transaction in transactions
    )
    cycle_started = not has_salary
    protected_spent = 0.0
    sent_thresholds: set[int] = set()
    notifications: list[dict[str, Any]] = []

    for transaction in transactions:
        if transaction["category"] == "Income / Salary" and transaction["amount"] > 0:
            cycle_started = True
        if transaction["amount"] < 0 and is_protected(transaction):
            protected_spent += -transaction["amount"]
        if not cycle_started:
            continue

        remaining = max(plan.protected_budget - protected_spent, 0.0)
        notice = classify_balance_notification(
            monthly_funds=monthly_funds,
            current_balance=transaction["running_balance"],
            remaining_protected=remaining,
        )
        
        newly_crossed = [
            threshold
            for threshold, _ in BALANCE_NOTIFICATION_THRESHOLDS
            if notice["percent_used"] >= threshold and threshold not in sent_thresholds
        ]
        if not newly_crossed:
            continue

        emitted_threshold = max(newly_crossed)
        sent_thresholds.update(newly_crossed)
        emitted = classify_balance_notification(
            monthly_funds=monthly_funds,
            current_balance=transaction["running_balance"],
            remaining_protected=remaining,
        )
        emitted["threshold"] = emitted_threshold
        emitted["date"] = transaction["date"]
        emitted["narrative"] = transaction["narrative"]
        emitted["balance"] = transaction["running_balance"]
        notifications.append(emitted)

    return notifications


def evaluate_credit_option(
    *,
    funds_used_percent: float,
    customer_consented: bool = False,
    affordability_passed: bool = False,
    existing_cardholder: bool | None = None,
) -> dict[str, Any]:
    """Ethical gatekeeper for the 95% credit curveball.

    Deliberately refuses to push automated credit to a financially distressed 
    customer. Enforces responsible lending principles (e.g., NCA affordability 
    checks) before a credit UI pathway can even be activated.
    """
    percent = float(funds_used_percent)
    result = {
        "offer_credit": False,
        "status": "NOT_TRIGGERED",
        "next_step": "Continue balance guidance.",
    }
    if percent < 95:
        return result
        
    if not customer_consented:
        return {
            **result,
            "status": "CONSENT_REQUIRED",
            "next_step": "Show support first and let the customer choose whether to review credit options.",
        }
        
    if not affordability_passed:
        return {
            **result,
            "status": "AFFORDABILITY_CHECK_REQUIRED",
            "next_step": "Complete affordability and responsible-lending checks before showing a product.",
        }
        
    if existing_cardholder is None:
        return {
            **result,
            "status": "CARD_STATUS_REQUIRED",
            "next_step": "Confirm whether the customer already holds a card before selecting a pathway.",
        }
        
    return {
        "offer_credit": True,
        "status": "LIMIT_INCREASE_ELIGIBLE" if existing_cardholder else "NEW_CARD_ELIGIBLE",
        "next_step": (
            "Present an eligible limit-review option with costs and terms; do not auto-increase."
            if existing_cardholder
            else "Present an eligible card option with costs and terms; do not auto-apply."
        ),
    }


def calculate_what_if_closing_balance(
    account: dict[str, Any],
    transactions: Iterable[dict[str, Any]],
    excluded_transaction_ids: Iterable[str],
) -> dict[str, Any]:
    """Recalculate the closing balance with named transactions excluded.

    Used by the UI to show the customer the pure math of avoiding a bad purchase.
    This is a transparent arithmetic scenario, not a prediction that a customer
    would actually cancel a transaction after seeing a warning.
    """
    excluded_ids = set(excluded_transaction_ids)
    selected = [
        transaction
        for transaction in transactions
        if transaction["transaction_id"] in excluded_ids
    ]
    found_ids = {transaction["transaction_id"] for transaction in selected}
    missing_ids = sorted(excluded_ids - found_ids)
    if missing_ids:
        raise ValueError(f"Unknown transaction IDs: {', '.join(missing_ids)}")

    actual_closing = _money(account["closingBalance"])
    adjustment = -sum(transaction["amount"] for transaction in selected)
    scenario_closing = actual_closing + adjustment
    
    return {
        "actual_closing_balance": round(actual_closing, 2),
        "scenario_closing_balance": round(scenario_closing, 2),
        "balance_improvement": round(adjustment, 2),
        "crosses_zero": actual_closing < 0 <= scenario_closing,
        "excluded_transactions": [
            {
                "transaction_id": transaction["transaction_id"],
                "date": transaction["date"],
                "narrative": transaction["narrative"],
                "amount": round(transaction["amount"], 2),
            }
            for transaction in selected
        ],
        "caveat": (
            "Arithmetic scenario only. It does not assume the customer would "
            "cancel a payment after receiving an alert."
        ),
    }


def check_purchase(
    *,
    current_balance: float,
    proposed_amount: float,
    remaining_protected: float,
    buffer: float,
) -> dict[str, Any]:
    """Core Point-of-Sale (POS) intercept logic.
    
    Evaluates a single discretionary transaction against the real-time ring-fenced 
    budget. Returns the action state (WITHIN PLAN, CAUTION, STOP AND REVIEW) to the UI.
    """
    proposed_amount = abs(float(proposed_amount))
    raw_safe_to_spend = current_balance - remaining_protected - buffer
    safe_to_spend = max(raw_safe_to_spend, 0.0)
    projected_balance = current_balance - proposed_amount
    
    reward = preview_buffer_reward(
        current_balance=current_balance,
        proposed_amount=proposed_amount,
        remaining_protected=remaining_protected,
        buffer=buffer,
    )

    if proposed_amount > safe_to_spend or projected_balance < 0:
        status = "STOP AND REVIEW"
        explanation = (
            "This payment uses money reserved for remaining essentials or the safety buffer."
        )
    elif safe_to_spend > 0 and proposed_amount >= 0.5 * safe_to_spend:
        # A single purchase is eating 50%+ of their remaining true disposable cash
        status = "CAUTION"
        explanation = "This payment uses at least half of the amount currently safe to spend."
    else:
        status = "WITHIN PLAN"
        explanation = "This payment fits within the amount currently safe to spend."

    return {
        "status": status,
        "safe_to_spend": round(safe_to_spend, 2),
        "raw_safe_to_spend": round(raw_safe_to_spend, 2),
        "projected_balance": round(projected_balance, 2),
        "remaining_protected": round(remaining_protected, 2),
        "buffer": round(buffer, 2),
        "explanation": explanation,
        "reward": reward,
    }


def analyse_statement(account: dict[str, Any], transactions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Generate high-level cash flow metrics for the dashboard summary."""
    transactions = list(transactions)
    opening = _money(account["openingBalance"])
    closing = _money(account["closingBalance"])
    inflows = sum(transaction["amount"] for transaction in transactions if transaction["amount"] > 0)
    outflows = -sum(transaction["amount"] for transaction in transactions if transaction["amount"] < 0)
    salary = sum(
        transaction["amount"]
        for transaction in transactions
        if transaction["category"] == "Income / Salary"
    )
    
    # Identify non-essential spending areas where behavior can actually be modified
    controllable_categories = {
        "Once-off Large Purchase",
        "Online Purchases",
        "Discretionary Spending",
        "Cash Withdrawal",
        "Subscriptions",
        "Uncategorised / Unusual",
    }
    controllable = -sum(
        transaction["amount"]
        for transaction in transactions
        if transaction["amount"] < 0 and transaction["category"] in controllable_categories
    )
    
    return {
        "opening_balance": round(opening, 2),
        "closing_balance": round(closing, 2),
        "inflows": round(inflows, 2),
        "outflows": round(outflows, 2),
        "net_cash_flow": round(inflows - outflows, 2),
        "salary": round(salary, 2),
        "controllable_spend": round(controllable, 2),
        "controllable_share_of_salary": round(controllable / salary if salary else 0, 4),
        "reconciled_closing": round(opening + inflows - outflows, 2),
    }


def backtest_transactions(
    account: dict[str, Any],
    transactions: Iterable[dict[str, Any]],
    plan: StatementPlan,
) -> list[dict[str, Any]]:
    """Replay loop used for the presentation demo.
    
    Applies the purchase check to every historical debit to prove how the 
    engine would have intervened if it had been active during the month.
    """
    results: list[dict[str, Any]] = []
    protected_spent = 0.0
    previous_balance = _money(account["openingBalance"])

    for transaction in transactions:
        amount = transaction["amount"]
        
        if amount < 0:
            remaining = max(plan.protected_budget - protected_spent, 0.0)
            
            # Route 1: System-generated debits (bypassed)
            if is_non_actionable(transaction):
                decision = {
                    "status": "NON_ACTIONABLE",
                    "safe_to_spend": round(max(previous_balance - remaining - plan.buffer, 0.0), 2),
                    "raw_safe_to_spend": round(previous_balance - remaining - plan.buffer, 2),
                    "projected_balance": transaction["running_balance"],
                    "remaining_protected": round(remaining, 2),
                    "buffer": plan.buffer,
                    "explanation": "This system charge affects the balance but is not a customer payment decision.",
                }
                
            # Route 2: Ring-fenced essential payments (auto-cleared)
            elif is_protected(transaction):
                decision = {
                    "status": "PROTECTED",
                    "safe_to_spend": round(max(previous_balance - remaining - plan.buffer, 0.0), 2),
                    "raw_safe_to_spend": round(previous_balance - remaining - plan.buffer, 2),
                    "projected_balance": transaction["running_balance"],
                    "remaining_protected": round(remaining, 2),
                    "buffer": plan.buffer,
                    "explanation": "This payment belongs to the customer's protected plan.",
                }
                protected_spent += -amount
                
            # Route 3: Discretionary spending (evaluated against safety limits)
            else:
                decision = check_purchase(
                    current_balance=previous_balance,
                    proposed_amount=-amount,
                    remaining_protected=remaining,
                    buffer=plan.buffer,
                )
                
            results.append({**transaction, **decision, "balance_before": round(previous_balance, 2)})
            
        previous_balance = transaction["running_balance"]
        
    return results