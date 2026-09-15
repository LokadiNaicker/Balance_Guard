# BalanceGuard

BalanceGuard is a small rule-based proof of concept for the Standard Bank PPB
Technology Graduate Assessment Centre. It converts an account balance into an
explainable **safe-to-spend** amount.

## Problem

The statement shows R49,388.00 of inflows and R53,534.14 of outflows. The
customer's balance remained positive until 29 August, but spending had already
started consuming money needed for the rest of the month. The account closed at
-R2,270.74. The data does not say whether this was an authorised overdraft, so
the solution does not label the customer wrong or assume the payment was
prohibited. It treats the negative balance as cash-flow pressure worth explaining.

## Rule

```text
safe_to_spend = max(current_balance - remaining_protected_spend - buffer, 0)

STOP AND REVIEW if payment > safe_to_spend or projected_balance < 0
CAUTION if payment >= 50% of safe_to_spend
WITHIN PLAN otherwise
```

Protected spending includes fixed commitments, debit orders, groceries,
transport, family support, and the transfer to the customer's savings pocket.
The demo buffer is 5% of salary.

Bank fees still reduce the running balance, but they are classified as
non-actionable system charges and never generate a customer payment alert. The
dashboard leads with the first Stop and Review event and shows three priority
decision moments rather than presenting every late-month warning equally.

## Optional Buffer Builder reward

The payment checker also previews an opt-in weekly reward. A customer remains
eligible for 25 points when the proposed discretionary payment leaves enough
money to cover both the remaining protected plan and the full safety buffer.
Points are awarded at a weekly checkpoint, not per transaction, so customers
cannot gain extra points by splitting one purchase into many smaller payments.
Protected payments and non-actionable bank fees do not run through the reward
preview.

The assessment provides only one month. For a transparent backtest, the demo
uses that month's observed protected spending as its plan. In production, the
plan would use known debit orders and the median of the previous three complete
months, with customer edits allowed. This remains rule-based and does not use
machine learning.

## Curveball: proactive monthly-funds notifications

The addendum is implemented inside the same rule engine. For this statement,
confirmed monthly funds are defined as:

```text
opening balance + confirmed salary received
= R1,875.40 + R48,200.00
= R50,075.40
```

Later refunds are not forecast into this baseline; they improve the running
balance only when received. Tracking begins when salary lands. The engine emits
each level once per cycle, which avoids repeating the same alert after every
transaction:

| Threshold | First crossed | Actual use | Behaviour |
|---:|---|---:|---|
| 50% | 6 Aug | 50.86% | Informational update |
| 75% | 14 Aug | 75.26% | Stronger warning and remaining commitments |
| 90% | 21 Aug | 91.03% | Critical spending alert |
| 95% | 26 Aug | 95.04% | Critical alert and customer-controlled support path |

The 95% level does **not** automatically market, approve, or increase credit.
The default result is `CONSENT_REQUIRED`. Only after the customer chooses to
review credit, an affordability assessment passes, and card status is known may
the interface present an eligible new-card or limit-review option. Costs and
terms must still be disclosed, and no credit is auto-granted.

## What-if proof

The dashboard also links the warning to a concrete month-end scenario. It
recalculates the closing balance after excluding two named statement rows:

```text
Actual closing balance                       -R2,270.74
Exclude 29 Aug gaming / crypto debit         +R2,500.00
Exclude 30 Aug low-balance notice fee           +R60.00
What-if closing balance                         R289.26
Balance improvement                           R2,560.00
```

The customer or assessor can untick either transaction and recalculate. This
proves the arithmetic effect of the selected transactions. It does not assume
that an alert would cause the customer to cancel a payment.

## Run the web application

Use Python 3.11 or later. The application has no third-party dependencies.

On Windows, extract the submission ZIP and double-click
`run_balanceguard.bat`. The server starts in a Command Prompt window and the
browser opens automatically.

Alternatively, open a terminal in the extracted folder and run:

```bash
python app.py
```

Then open `http://127.0.0.1:8501`.

## Run the console demonstration

```bash
python console_demo.py
```

## Run the tests

```bash
python -m unittest discover -s tests -v
```

## Project structure

- `app.py`: local web server and JSON endpoints
- `web/`: responsive browser interface
- `console_demo.py`: simple terminal demonstration
- `balance_guard/engine.py`: calculation and decision rules
- `tests/test_engine.py`: seven reconciliation, decision, notification, credit-gate and what-if tests
- `data/transactions.json`: supplied synthetic assessment data
- `RUN_ME_FIRST.txt`: beginner-friendly Windows instructions
- `run_balanceguard.bat`: Windows one-click launcher

## MVP trade-offs

- The engine warns and explains. It does not block a customer payment.
- The customer can change protected amounts and the buffer.
- One month cannot establish a stable spending baseline.
- The assessment data cannot establish consent, affordability, card status or
  an authorised overdraft limit.
- A production pilot would add multiple accounts, scheduled payments, and
  customer feedback when a category is wrong.
