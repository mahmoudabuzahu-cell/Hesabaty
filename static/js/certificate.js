(function () {
  "use strict";
  const { formatNumber, debounce, postJSON, bindSlider } = window.Hasabaty;
  const meta = window.__CERTS_META__ || { terms: [], banks: [] };

  // تبويبات
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("panel-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "compare") runCompare();
      if (btn.dataset.tab === "redeem") runRedeem();
    });
  });

  // المبلغ المشترك
  const amountNum = document.getElementById("amountNum");
  const amountRange = document.getElementById("amountRange");
  bindSlider(amountRange, amountNum, () => {
    document.getElementById("amountOut").textContent = formatNumber(amountNum.value, 0);
    runCalc();
    runCompare();
    runRedeem();
  });
  document.getElementById("amountOut").textContent = formatNumber(amountNum.value, 0);

  // حاسبة الشهادة
  const rateNum = document.getElementById("certRateNum");
  const rateRange = document.getElementById("certRateRange");
  const yearsNum = document.getElementById("certYearsNum");
  const yearsRange = document.getElementById("certYearsRange");
  let payout = "monthly";

  document.querySelectorAll("#payoutSeg button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#payoutSeg button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      payout = btn.dataset.val;
      runCalc();
    });
  });

  const payoutLabels = { monthly: "شهرياً", quarterly: "كل 3 شهور", yearly: "سنوياً", maturity: "عند الاستحقاق" };

  async function runCalc() {
    document.getElementById("certRateOut").textContent = rateNum.value;
    document.getElementById("certYearsOut").textContent = yearsNum.value;
    try {
      const r = await postJSON("/calculate/certificate", {
        principal: Number(amountNum.value),
        annual_rate: Number(rateNum.value),
        years: Number(yearsNum.value),
        payout,
      });
      document.getElementById("certPerPeriod").textContent = payout === "maturity" ? "٠" : formatNumber(r.income_per_period);
      document.getElementById("certCaption").textContent = "العائد " + payoutLabels[payout];
      document.getElementById("certAnnual").textContent = formatNumber(r.annual_income);
      document.getElementById("certTotal").textContent = formatNumber(r.total_income);
      document.getElementById("certMaturity").textContent = formatNumber(r.maturity_value);
    } catch (e) {
      /* تجاهل */
    }
  }
  bindSlider(rateRange, rateNum, debounce(runCalc, 150));
  bindSlider(yearsRange, yearsNum, debounce(runCalc, 150));

  // المقارنة الذكية
  const compareTerm = document.getElementById("compareTerm");
  const compareBank = document.getElementById("compareBank");
  (meta.terms || []).forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t + " سنوات";
    compareTerm.appendChild(opt);
  });
  (meta.banks || []).forEach((b) => {
    const opt = document.createElement("option");
    opt.value = b;
    opt.textContent = b;
    compareBank.appendChild(opt);
  });
  document.getElementById("compareMeta").textContent = meta.checked_at ? `آخر تحقق من الأسعار: ${meta.checked_at}` : "";

  let lastCompareResults = [];

  async function runCompare() {
    if (!compareTerm.value) return;
    try {
      const r = await postJSON("/compare-certificates", {
        money: Number(amountNum.value),
        term_years: Number(compareTerm.value),
        bank: compareBank.value || null,
      });
      lastCompareResults = r.results;
      const resultsEl = document.getElementById("compareResults");
      resultsEl.innerHTML = r.results
        .map(
          (c) => `
        <div class="compare-card ${c.is_best ? "best" : ""}">
          ${c.is_best ? '<span class="badge badge-gold" style="position:absolute; top:14px; left:14px;">الأعلى عائداً</span>' : ""}
          <div class="bank">${c.bank}</div>
          <div class="name">${c.name}</div>
          <div class="rate">${c.rate}%</div>
          <div class="stat"><span>دخل شهري تقريبي</span><b>${formatNumber(c.monthly_income)}</b></div>
          <div class="stat"><span>إجمالي العائد على المدة</span><b>${formatNumber(c.total_profit)}</b></div>
          <div class="stat"><span>الحد الأدنى</span><b>${formatNumber(c.min_amount, 0)}</b></div>
          <div class="badges">
            ${c.loanable ? '<span class="badge badge-neutral">يمكن الاقتراض بضمانها</span>' : ""}
          </div>
          ${c.notes ? `<p class="text-soft" style="font-size:0.78rem; margin-top:8px;">${c.notes}</p>` : ""}
          <span class="src">المصدر بتاريخ ${c.checked_at} — تحقق من السعر الحالي قبل القرار</span>
        </div>`
        )
        .join("");

      const excludedEl = document.getElementById("compareExcluded");
      if (r.excluded_below_minimum && r.excluded_below_minimum.length) {
        excludedEl.innerHTML = `<p class="text-soft" style="font-size:0.8rem; margin-top:14px;">مستبعدة لأن المبلغ أقل من الحد الأدنى: ${r.excluded_below_minimum
          .map((x) => `${x.bank} (${x.name}) — الحد الأدنى ${formatNumber(x.min_amount, 0)} ج.م`)
          .join("، ")}</p>`;
      } else {
        excludedEl.innerHTML = "";
      }
      if (!r.results.length) {
        resultsEl.innerHTML = `<p class="text-soft">مفيش شهادات متاحة بالفلاتر دي حالياً — جرب مدة أو مبلغ مختلف.</p>`;
      }
    } catch (e) {
      /* تجاهل */
    }
  }
  compareTerm.addEventListener("change", runCompare);
  compareBank.addEventListener("change", runCompare);

  // محاكي فك الشهادة
  const monthsHeldNum = document.getElementById("monthsHeldNum");
  async function runRedeem() {
    const box = document.getElementById("redeemResult");
    try {
      const r = await postJSON("/simulate/certificate-redemption", {
        principal: Number(amountNum.value),
        annual_rate: Number(rateNum.value),
        years: Number(yearsNum.value),
        months_held: Number(monthsHeldNum.value) || 1,
      });
      box.innerHTML = `
        <div class="result-row"><span class="k">العائد المكتسب حتى الآن</span><span class="v num">${formatNumber(r.earned_income)}</span></div>
        <div class="result-row"><span class="k">الغرامة المتوقعة</span><span class="v num value-cost">${formatNumber(r.penalty)}</span></div>
        <div class="result-row"><span class="k">المبلغ اللي هيرجعلك</span><span class="v num">${formatNumber(r.redemption_value)}</span></div>
        <p class="text-soft" style="font-size:0.8rem; margin-top:10px;">${r.message}</p>`;
    } catch (e) {
      box.innerHTML = `<p class="text-soft">${e.message}</p>`;
    }
  }
  monthsHeldNum.addEventListener("input", debounce(runRedeem, 250));

  document.getElementById("certExcelBtn").addEventListener("click", () => {
    if (!lastCompareResults.length) {
      alert("اعمل مقارنة الأول من تبويب «مقارنة ذكية بين البنوك».");
      return;
    }
    const rows = lastCompareResults.map((c) => ({
      البنك: c.bank,
      الشهادة: c.name,
      "النوع": c.type,
      "العائد%": c.rate,
      "دخل شهري تقريبي": c.monthly_income,
      "إجمالي العائد": c.total_profit,
      "الحد الأدنى": c.min_amount,
      "آخر تحقق": c.checked_at,
      المصدر: c.source_url,
    }));
    window.Hasabaty.exportRowsToExcel(rows, "مقارنة-شهادات-الادخار", "الشهادات");
  });

  runCalc();
})();
