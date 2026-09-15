"""Rule-based cash-flow guard for the PPB graduate assessment."""

from .engine import (
    BALANCE_NOTIFICATION_THRESHOLDS,
    StatementPlan,
    analyse_statement,
    backtest_transactions,
    build_balance_notifications,
    calculate_what_if_closing_balance,
    check_purchase,
    classify_balance_notification,
    evaluate_credit_option,
    load_transactions_json,
    monthly_funds_baseline,
    preview_buffer_reward,
)

__all__ = [
    "BALANCE_NOTIFICATION_THRESHOLDS",
    "StatementPlan",
    "analyse_statement",
    "backtest_transactions",
    "build_balance_notifications",
    "calculate_what_if_closing_balance",
    "check_purchase",
    "classify_balance_notification",
    "evaluate_credit_option",
    "load_transactions_json",
    "monthly_funds_baseline",
    "preview_buffer_reward",
]
