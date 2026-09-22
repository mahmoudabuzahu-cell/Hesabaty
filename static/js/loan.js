(function () {
  "use strict";
  const { formatNumber, debounce, postJSON, bindSlider, waLink } = window.Hasabaty;

  const principalNum = document.getElementById("principalNum");
  const principalRange = document.getElementById("principalRange");
  const rateNum = document.getElementById("rateNum");
  const rateRange = document.getElementById("rateRange");
  const yearsNum = document.getElementById("yearsNum");
  const yearsRange = document.getElementById("yearsRange");
  const feeNum = document.getElementById("feeNum");
  const feeRange = document.getElementById("feeRange");

  let lastResult = null;
  let fullScheduleShown = false;

  // ---------------------------------------------------------------------
  // سجل آخر عملياتك — محفوظ في متصفحك إنت بس، مبيتبعتش لأي سيرفر
  // ---------------------------------------------------------------------
  const queueHistorySave = debounce((inputs, result) => {
    window.Hasabaty.saveHistory(
      "loan",
      `${formatNumber(inputs.principal, 0)} ج.م، ${inputs.years} سنة، ${inputs.annual_rate}%`,
      `القسط: ${formatNumber(result.monthly_payment)} ج.م/شهرياً`
    );
    renderHistory();
  }, 2000);

  function renderHistory() {
    const panel = document.getElementById("historyPanel");
    const list = document.getElementById("historyList");
    const items = window.Hasabaty.getHistory("loan");
    if (!items.length) {
      panel.style.display = "none";
      return;
    }
    panel.style.display = "block";
    list.innerHTML = items
      .map(
        (it) => `<div style="display:flex; justify-content:space-between; align-items:center; font-size:0.85rem; padding:6px 0; border-bottom:1px solid var(--line);">
          <span>${it.label} — <span class="text-soft">${it.summary}</span></span>
        </div>`
      )
      .join("");
  }

  document.getElementById("clearHistoryBtn").addEventListener("click", () => {
    window.Hasabaty.clearHistory("loan");
    renderHistory();
  });
  renderHistory();

  function currentInputs() {
    return {
      principal: Number(principalNum.value) || 0,
      annual_rate: Number(rateNum.value) || 0,
      years: Number(yearsNum.value) || 1,
      admin_fee_percent: Number(feeNum.value) || 0,
    };
  }

  function renderSchedule(schedule) {
    const body = document.getElementById("scheduleBody");
    const rows = fullScheduleShown ? schedule : schedule.slice(0, 12);
    body.innerHTML = rows
      .map(
        (r) => `<tr><td>${r.month}</td><td>${formatNumber(r.payment)}</td><td>${formatNumber(r.interest)}</td><td>${formatNumber(r.principal)}</td><td>${formatNumber(r.balance)}</td></tr>`
      )
      .join("");
    const toggleBtn = document.getElementById("toggleScheduleBtn");
    if (schedule.length <= 12) {
      toggleBtn.style.display = "none";
    } else {
      toggleBtn.style.display = "inline-flex";
      toggleBtn.textContent = fullScheduleShown ? "إظهار أول سنة فقط" : `إظهار الجدول كاملاً (${schedule.length} شهر)`;
    }
  }

  function setDonut(principal, interest) {
    const total = principal + interest;
    const pct = total > 0 ? (interest / total) * 100 : 0;
    document.getElementById("donutArc").setAttribute("stroke-dasharray", `${pct.toFixed(1)} ${(100 - pct).toFixed(1)}`);
  }

  async function runLoanCalc() {
    const inputs = currentInputs();
    document.getElementById("principalOut").textContent = formatNumber(inputs.principal, 0);
    document.getElementById("rateOut").textContent = inputs.annual_rate;
    document.getElementById("yearsOut").textContent = inputs.years;
    document.getElementById("feeOut").textContent = inputs.admin_fee_percent;

    const errBox = document.getElementById("resultError");
    try {
      const result = await postJSON("/calculate/loan", inputs);
      lastResult = result;
      errBox.style.display = "none";
      document.getElementById("rMonthly").textContent = formatNumber(result.monthly_payment);
      document.getElementById("rMonthlyWords").textContent = window.Hasabaty.tafqeet(result.monthly_payment);
      document.getElementById("rTotalPaid").textContent = formatNumber(result.total_paid);
      document.getElementById("rTotalInterest").textContent = formatNumber(result.total_interest);
      document.getElementById("rFee").textContent = formatNumber(result.admin_fee);
      document.getElementById("rNet").textContent = formatNumber(result.net_disbursed);
      setDonut(inputs.principal, result.total_interest);
      renderSchedule(result.schedule);
      runDTI();
      runSettlement();
      queueHistorySave(inputs, result);
    } catch (e) {
      errBox.style.display = "block";
      errBox.textContent = e.message;
    }
  }

  const debouncedCalc = debounce(runLoanCalc, 180);

  bindSlider(principalRange, principalNum, debouncedCalc);
  bindSlider(rateRange, rateNum, debouncedCalc);
  bindSlider(yearsRange, yearsNum, debouncedCalc);
  bindSlider(feeRange, feeNum, debouncedCalc);

  // نسب عبء الدين
  const incomeNum = document.getElementById("incomeNum");
  const otherDebtsNum = document.getElementById("otherDebtsNum");
  async function runDTI() {
    const box = document.getElementById("dtiResult");
    const income = Number(incomeNum.value);
    if (!lastResult || !income) {
      box.innerHTML = "";
      return;
    }
    try {
      const r = await postJSON("/calculate/debt-burden", {
        monthly_installment: lastResult.monthly_payment,
        monthly_net_income: income,
        existing_monthly_debts: Number(otherDebtsNum.value) || 0,
      });
      const badgeClass = r.within_cbe_guideline ? "badge-gain" : "badge-cost";
      const badgeText = r.within_cbe_guideline ? "ضمن الحد المرشد به" : "أعلى من الحد المرشد به";
      box.innerHTML = `<div class="result-row" style="margin-top:10px;"><span class="k">نسبة العبء</span><span class="v num">${r.ratio_percent}%</span></div>
        <span class="badge ${badgeClass}">${badgeText}</span>`;
    } catch (e) {
      box.innerHTML = "";
    }
  }
  incomeNum.addEventListener("input", debounce(runDTI, 250));
  otherDebtsNum.addEventListener("input", debounce(runDTI, 250));

  // محاكي السداد المبكر
  const monthsPaidNum = document.getElementById("monthsPaidNum");
  async function runSettlement() {
    const box = document.getElementById("settlementResult");
    const inputs = currentInputs();
    const monthsPaid = Number(monthsPaidNum.value);
    const totalMonths = inputs.years * 12;
    if (!monthsPaid || monthsPaid >= totalMonths) {
      box.innerHTML = `<p class="text-soft" style="font-size:0.82rem;">عدد الأقساط لازم يكون أقل من إجمالي عدد أقساط القرض (${totalMonths}).</p>`;
      return;
    }
    try {
      const r = await postJSON("/simulate/loan-early-settlement", {
        principal: inputs.principal,
        annual_rate: inputs.annual_rate,
        years: inputs.years,
        months_paid: monthsPaid,
      });
      box.innerHTML = `
        <div class="result-row"><span class="k">المتبقي من أصل القرض</span><span class="v num">${formatNumber(r.remaining_balance)}</span></div>
        <div class="result-row"><span class="k">غرامة السداد المبكر (${r.penalty_percent}%)</span><span class="v num">${formatNumber(r.penalty)}</span></div>
        <div class="result-row"><span class="k">إجمالي مبلغ الغلق</span><span class="v num">${formatNumber(r.payoff_amount)}</span></div>
        <div class="result-row"><span class="k">فوائد هتوفرها</span><span class="v num value-gain">${formatNumber(r.remaining_interest_saved)}</span></div>
        <p class="text-soft" style="font-size:0.76rem; margin-top:8px;">${r.note}</p>`;
    } catch (e) {
      box.innerHTML = `<p class="text-soft" style="font-size:0.82rem;">${e.message}</p>`;
    }
  }
  monthsPaidNum.addEventListener("input", debounce(runSettlement, 250));

  // الجدول: إظهار/إخفاء
  document.getElementById("toggleScheduleBtn").addEventListener("click", () => {
    fullScheduleShown = !fullScheduleShown;
    if (lastResult) renderSchedule(lastResult.schedule);
  });

  // طباعة / واتساب
  document.getElementById("printBtn").addEventListener("click", () => window.print());
  document.getElementById("waShareBtn").addEventListener("click", () => {
    if (!lastResult) return;
    const inputs = currentInputs();
    const text = `حسبت قرض ${formatNumber(inputs.principal, 0)} ج.م على ${inputs.years} سنوات بفائدة ${inputs.annual_rate}% على حساباتى:\nالقسط الشهري: ${formatNumber(lastResult.monthly_payment)} ج.م\nإجمالي الفوائد: ${formatNumber(lastResult.total_interest)} ج.م`;
    window.open(waLink(text), "_blank");
  });
  document.getElementById("excelBtn").addEventListener("click", () => {
    if (!lastResult) return;
    const rows = lastResult.schedule.map((m) => ({
      الشهر: m.month,
      القسط: m.payment,
      الفائدة: m.interest,
      "سداد الأصل": m.principal,
      "الرصيد المتبقي": m.balance,
    }));
    window.Hasabaty.exportRowsToExcel(rows, "جدول-سداد-القرض", "جدول السداد");
  });

  // القوالب الجاهزة
  document.querySelectorAll(".preset-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".preset-chip").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const years = Number(btn.dataset.years);
      const maxYears = Number(btn.dataset.maxYears);
      yearsRange.max = maxYears;
      yearsNum.max = maxYears;
      yearsNum.value = years;
      yearsRange.value = years;
      runLoanCalc();
    });
  });

  runLoanCalc();
})();
