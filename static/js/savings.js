(function () {
  "use strict";
  const { formatNumber, debounce, postJSON, bindSlider } = window.Hasabaty;
  const meta = window.__SAVINGS_META__ || { banks: [], count: 0 };

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("panel-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "compare") runCompare();
    });
  });

  const initialNum = document.getElementById("initialNum");
  const initialRange = document.getElementById("initialRange");
  const contribNum = document.getElementById("contribNum");
  const contribRange = document.getElementById("contribRange");
  const rateNum = document.getElementById("savRateNum");
  const rateRange = document.getElementById("savRateRange");
  const yearsNum = document.getElementById("savYearsNum");
  const yearsRange = document.getElementById("savYearsRange");

  function drawChart(snapshots) {
    const svg = document.getElementById("growthChart");
    if (!snapshots.length) { svg.innerHTML = ""; return; }
    const w = 300, h = 110, pad = 6;
    const maxBalance = Math.max(...snapshots.map((s) => s.balance));
    const pts = (key, color) =>
      snapshots
        .map((s, i) => {
          const x = pad + (i / (snapshots.length - 1 || 1)) * (w - pad * 2);
          const y = h - pad - (s[key] / (maxBalance || 1)) * (h - pad * 2);
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" ");
    svg.innerHTML = `
      <polyline points="${pts("contributed")}" fill="none" stroke="var(--ink-faint)" stroke-width="2" stroke-dasharray="3 3"/>
      <polyline points="${pts("balance")}" fill="none" stroke="var(--brand-bright)" stroke-width="2.5"/>
    `;
  }

  async function runCalc() {
    document.getElementById("initialOut").textContent = formatNumber(initialNum.value, 0);
    document.getElementById("contribOut").textContent = formatNumber(contribNum.value, 0);
    document.getElementById("savRateOut").textContent = rateNum.value;
    document.getElementById("savYearsOut").textContent = yearsNum.value;
    try {
      const r = await postJSON("/calculate/savings", {
        initial: Number(initialNum.value),
        monthly_contribution: Number(contribNum.value),
        annual_rate: Number(rateNum.value),
        years: Number(yearsNum.value),
      });
      document.getElementById("savFinal").textContent = formatNumber(r.final_balance);
      document.getElementById("savContributed").textContent = formatNumber(r.total_contributed);
      document.getElementById("savProfit").textContent = formatNumber(r.total_profit);
      drawChart(r.yearly_snapshots);
    } catch (e) {
      /* تجاهل */
    }
  }
  const debouncedCalc = debounce(runCalc, 180);
  bindSlider(initialRange, initialNum, debouncedCalc);
  bindSlider(contribRange, contribNum, debouncedCalc);
  bindSlider(rateRange, rateNum, debouncedCalc);
  bindSlider(yearsRange, yearsNum, debouncedCalc);

  // المقارنة
  const compareBank = document.getElementById("compareBank");
  (meta.banks || []).forEach((b) => {
    const opt = document.createElement("option");
    opt.value = b;
    opt.textContent = b;
    compareBank.appendChild(opt);
  });

  let lastSavingsCompare = [];

  async function runCompare() {
    const resultsEl = document.getElementById("compareResults");
    const emptyEl = document.getElementById("compareEmpty");
    if (!meta.count) {
      resultsEl.innerHTML = "";
      emptyEl.innerHTML = `<div class="alert alert-info">لسه مفيش بيانات حسابات توفير موثقة بتاريخ تحقق واضح مضافة لهذه المقارنة. جدول شهادات الادخار في صفحة "شهادات الادخار" محدّث ومتاح دلوقتي.</div>`;
      return;
    }
    try {
      const r = await postJSON("/compare-savings", {
        money: Number(initialNum.value) || 1000,
        years: Number(yearsNum.value),
        bank: compareBank.value || null,
      });
      lastSavingsCompare = r.results;
      resultsEl.innerHTML = r.results
        .map(
          (a) => `
        <div class="compare-card ${a.is_best ? "best" : ""}">
          <div class="bank">${a.bank}</div>
          <div class="name">${a.name}</div>
          <div class="rate">${a.rate}%</div>
          <div class="stat"><span>دخل سنوي تقريبي</span><b>${formatNumber(a.annual_income)}</b></div>
          <div class="stat"><span>إجمالي على ${document.getElementById("savYearsNum").value} سنوات</span><b>${formatNumber(a.total_income)}</b></div>
          <span class="src">المصدر بتاريخ ${a.checked_at || "—"}</span>
        </div>`
        )
        .join("");
      emptyEl.innerHTML = !r.results.length ? `<p class="text-soft">مفيش نتائج بالمبلغ ده حالياً.</p>` : "";
    } catch (e) {
      resultsEl.innerHTML = "";
    }
  }
  compareBank.addEventListener("change", runCompare);
  document.getElementById("savYearsNum").addEventListener("input", debounce(runCompare, 300));

  document.getElementById("savingsExcelBtn").addEventListener("click", () => {
    if (!lastSavingsCompare.length) {
      alert("اعمل مقارنة الأول من تبويب «مقارنة ذكية بين البنوك».");
      return;
    }
    const rows = lastSavingsCompare.map((a) => ({
      البنك: a.bank,
      الحساب: a.name,
      "العائد%": a.rate,
      "دخل سنوي تقريبي": a.annual_income,
      "إجمالي المدة": a.total_income,
      "الحد الأدنى": a.min_amount,
      "آخر تحقق": a.checked_at,
      المصدر: a.source_url,
    }));
    window.Hasabaty.exportRowsToExcel(rows, "مقارنة-حسابات-التوفير", "التوفير");
  });

  runCalc();
})();
