const money = value => `${value < 0 ? "-" : ""}R${Math.abs(value).toLocaleString("en-ZA", {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;

function renderChart(points) {
  const svg = document.querySelector("#balance-chart");
  const width = 760, height = 260, left = 54, right = 18, top = 16, bottom = 34;
  const values = points.map(point => point.balance);
  const min = Math.min(...values, 0), max = Math.max(...values, 0);
  const x = index => left + index * (width - left - right) / (points.length - 1);
  const y = value => top + (max - value) * (height - top - bottom) / (max - min);
  const path = points.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(point.balance).toFixed(1)}`).join(" ");
  const zeroY = y(0);
  const labels = [0, 9, 19, 29].map(index => `<text x="${x(index)}" y="248" text-anchor="middle">${points[index].date}</text>`).join("");
  svg.innerHTML = `
    <line x1="${left}" y1="${zeroY}" x2="${width-right}" y2="${zeroY}" stroke="#c53a45" stroke-dasharray="6 5"/>
    <text x="8" y="${zeroY+4}" fill="#c53a45">R0</text>
    <path d="${path}" fill="none" stroke="#00a7d8" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${x(points.length-1)}" cy="${y(values.at(-1))}" r="6" fill="#c53a45"/>
    <text x="${x(points.length-1)-8}" y="${y(values.at(-1))-12}" text-anchor="end" fill="#c53a45" font-weight="700">${money(values.at(-1))}</text>
    <g fill="#617086" font-size="12">${labels}</g>`;
}

function renderWhatIf(result, buildChoices = false) {
  if (buildChoices) {
    document.querySelector("#what-if-transactions").innerHTML = result.excluded_transactions.map(row => `
      <label class="what-if-choice">
        <input type="checkbox" data-transaction-id="${row.transaction_id}" checked>
        <span><strong>${row.date}: ${money(-row.amount)}</strong>${row.narrative}</span>
      </label>`).join("");
  }
  document.querySelector("#what-if-actual").textContent = money(result.actual_closing_balance);
  document.querySelector("#what-if-improvement").textContent = `+${money(result.balance_improvement)}`;
  document.querySelector("#what-if-scenario").textContent = money(result.scenario_closing_balance);
  document.querySelector("#what-if-caveat").textContent = result.caveat;
}

async function loadSummary() {
  const response = await fetch("/api/summary");
  const data = await response.json();
  document.querySelector("#inflows").textContent = money(data.analysis.inflows);
  document.querySelector("#outflows").textContent = money(data.analysis.outflows);
  document.querySelector("#net").textContent = money(data.analysis.net_cash_flow);
  document.querySelector("#closing").textContent = money(data.analysis.closing_balance);
  document.querySelector("#headline-date").textContent = data.headline.date;
  document.querySelector("#headline-lead").textContent = `${data.headline.lead_days} days`;
  document.querySelector("#headline-safe").textContent = money(data.headline.safe_to_spend);
  document.querySelector("#monthly-funds").textContent = money(data.monthly_funds_baseline);
  const used = data.current_balance_notification.percent_used;
  document.querySelector("#funds-used").textContent = `${used.toFixed(2)}%`;
  document.querySelector("#funds-progress-bar").style.width = `${Math.min(used, 100)}%`;
  document.querySelector("#notifications").innerHTML = data.balance_notifications.map(row => `
    <tr>
      <td><span class="threshold-badge level-${row.threshold}">${row.threshold}% ${row.level}</span></td>
      <td>${row.date}</td>
      <td>${row.percent_used.toFixed(2)}%</td>
      <td>${row.message}</td>
    </tr>`).join("");
  renderCreditDecision(data.credit_gate);
  renderWhatIf(data.what_if, true);
  renderChart(data.balance_series);
  const createWarningRow = row => {
  const statusClass = row.status.startsWith("STOP")
    ? "stop"
    : "caution";

  return `
    <tr>
      <td>${row.date}</td>
      <td>${row.narrative}</td>
      <td>${money(row.amount)}</td>
      <td>${money(row.safe_to_spend)}</td>
      <td>
        <span class="status ${statusClass}">
          ${row.status}
        </span>
      </td>
    </tr>
  `;
};

document.querySelector("#warnings").innerHTML =
  data.priority_warnings
    .map(createWarningRow)
    .join("");

document.querySelector("#all-warnings").innerHTML =
  data.warnings
    .map(createWarningRow)
    .join("");

document.querySelector("#all-warnings-summary").textContent =
  `View all ${data.warnings.length} actionable events`;

document.querySelector("#grouped-warning-note").textContent =
  `${data.additional_warning_count} additional actionable events are grouped below. Bank fees affect the balance but do not generate customer payment alerts.`;
}

async function checkPayment() {
  const payload = {
    current_balance: Number(document.querySelector("#current").value),
    remaining_protected: Number(document.querySelector("#reserved").value),
    buffer: Number(document.querySelector("#buffer").value),
    proposed_amount: Number(document.querySelector("#payment").value),
  };
  const response = await fetch("/api/check", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  const box = document.querySelector("#decision");
  const cssClass = result.status.startsWith("STOP") ? "stop" : result.status === "CAUTION" ? "caution" : "within";
  box.className = `decision show ${cssClass}`;
  box.innerHTML = `<strong>${result.status}</strong>Safe to spend: ${money(result.safe_to_spend)}<br>Balance after payment: ${money(result.projected_balance)}<br><small>${result.explanation}</small>`;
  const notice = result.balance_notification;
  const thresholdBox = document.querySelector("#threshold-preview");
  thresholdBox.className = `threshold-preview show level-${notice.threshold}`;
  thresholdBox.innerHTML = `<strong>${notice.title}</strong><small>${notice.message}${result.new_balance_notification ? " This payment crosses a new notification level." : ""}</small>`;
  const reward = result.reward;
  const rewardBox = document.querySelector("#reward-preview");
  rewardBox.className = `reward-preview show ${reward.eligible_after ? "earned" : "missed"}`;
  rewardBox.innerHTML = `
    <div><span>BUFFER BUILDER</span><strong>${reward.projected_points} projected points</strong></div>
    <small>${reward.message}<br>Required balance after payment: ${money(reward.required_balance)}</small>`;
}

function renderCreditDecision(result) {
  const box = document.querySelector("#credit-decision");
  box.className = `credit-decision show ${result.offer_credit ? "eligible" : "gated"}`;
  box.innerHTML = `<strong>${result.status.replaceAll("_", " ")}</strong><small>${result.next_step}</small>`;
}

async function evaluateCredit() {
  const value = document.querySelector("#card-status").value;
  const payload = {
    funds_used_percent: Number(document.querySelector("#funds-used").textContent.replace("%", "")),
    customer_consented: document.querySelector("#credit-consent").checked,
    affordability_passed: document.querySelector("#affordability").checked,
    existing_cardholder: value === "unknown" ? null : value === "existing",
  };
  const response = await fetch("/api/credit-review", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  renderCreditDecision(await response.json());
}

async function recalculateWhatIf() {
  const transactionIds = [...document.querySelectorAll("[data-transaction-id]:checked")]
    .map(input => input.dataset.transactionId);
  const response = await fetch("/api/what-if", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({transaction_ids: transactionIds}),
  });
  renderWhatIf(await response.json());
}

document.querySelector("#check-button").addEventListener("click", checkPayment);
document.querySelector("#credit-button").addEventListener("click", evaluateCredit);
document.querySelector("#what-if-button").addEventListener("click", recalculateWhatIf);
loadSummary().then(checkPayment);
