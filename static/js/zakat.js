(function () {
  "use strict";
  const { formatNumber, debounce, postJSON, getJSON, downloadICS } = window.Hasabaty;

  // تبويبات الأصول
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("panel-" + btn.dataset.tab).classList.add("active");
    });
  });

  let nisabBasis = "gold";
  document.querySelectorAll("#nisabSeg button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#nisabSeg button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      nisabBasis = btn.dataset.val;
      runCalc();
    });
  });

  let hawlPassed = true;
  document.querySelectorAll("#hawlSeg button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#hawlSeg button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      hawlPassed = btn.dataset.val === "yes";
      runCalc();
    });
  });

  const excludeWorn = document.getElementById("excludeWorn");
  const wornFields = document.getElementById("wornFields");
  excludeWorn.addEventListener("change", () => {
    wornFields.style.display = excludeWorn.checked ? "block" : "none";
    runCalc();
  });

  const ids = [
    "cashNum", "gold24Num", "gold21Num", "gold18Num", "worn24Num", "worn21Num", "worn18Num",
    "silverNum", "stocksNum", "receivablesNum", "debtsNum",
  ];
  ids.forEach((id) => document.getElementById(id).addEventListener("input", debounce(runCalc, 220)));

  async function loadPrices() {
    try {
      const { prices } = await getJSON("/api/market");
      if (prices.gold) {
        document.getElementById("g24p").textContent = formatNumber(prices.gold["24k"]);
        document.getElementById("g21p").textContent = formatNumber(prices.gold["21k"]);
        document.getElementById("g18p").textContent = formatNumber(prices.gold["18k"]);
      }
      if (prices.silver) document.getElementById("silverP").textContent = formatNumber(prices.silver["999"]);
    } catch (e) {
      /* تجاهل — القيم الأولية من الصفحة نفسها كافية */
    }
  }

  async function runCalc() {
    const v = (id) => Number(document.getElementById(id).value) || 0;
    try {
      const r = await postJSON("/calculate/zakat", {
        cash_egp: v("cashNum"),
        gold_grams_24k: v("gold24Num"),
        gold_grams_21k: v("gold21Num"),
        gold_grams_18k: v("gold18Num"),
        worn_gold_grams_24k: v("worn24Num"),
        worn_gold_grams_21k: v("worn21Num"),
        worn_gold_grams_18k: v("worn18Num"),
        exclude_worn_gold: excludeWorn.checked,
        silver_grams: v("silverNum"),
        stocks_value: v("stocksNum"),
        receivables: v("receivablesNum"),
        debts: v("debtsNum"),
        nisab_basis: nisabBasis,
        hawl_passed: hawlPassed,
      });
      window.__lastZakat = r;
      document.getElementById("rDue").textContent = formatNumber(r.zakat_due);
      document.getElementById("rDueWords").textContent = r.zakat_due > 0 ? window.Hasabaty.tafqeet(r.zakat_due) : "";
      document.getElementById("rTotal").textContent = formatNumber(r.total_wealth);
      document.getElementById("rDebts").textContent = formatNumber(r.debts);
      document.getElementById("rNet").textContent = formatNumber(r.net_wealth);
      document.getElementById("nisabLabel").textContent = "النصاب: " + formatNumber(r.nisab_amount, 0) + " ج.م";
      document.getElementById("progressFill").style.width = Math.round(r.progress_ratio * 100) + "%";

      const statusNote = document.getElementById("statusNote");
      if (!r.meets_nisab) {
        statusNote.textContent = "صافي أموالك لسه تحت النصاب — مفيش زكاة مستحقة عليه حالياً.";
      } else if (!r.hawl_passed) {
        statusNote.textContent = "صافي أموالك فوق النصاب، لكن الزكاة تجب بعد مرور حول (عام هجري) كامل عليه من وقت وصوله للنصاب.";
      } else {
        statusNote.textContent = "صافي أموالك فوق النصاب ومر عليه حول — الزكاة المستحقة موضحة أعلاه.";
      }
    } catch (e) {
      /* تجاهل */
    }
  }

  document.getElementById("printBtn").addEventListener("click", () => window.print());
  document.getElementById("reminderBtn").addEventListener("click", () => {
    const due = window.__lastZakat ? formatNumber(window.__lastZakat.zakat_due) : "—";
    const reminderDate = new Date();
    reminderDate.setDate(reminderDate.getDate() + 354);
    downloadICS({
      title: "موعد حساب الزكاة السنوي",
      description: `تذكير تقريبي بمرور عام هجري على أموالك. آخر حساب كان يقدّر الزكاة المستحقة بـ ${due} ج.م.`,
      date: reminderDate,
    });
  });

  loadPrices();
  runCalc();
})();
