(function () {
  "use strict";
  const { formatNumber, bindSlider, postJSON } = window.Hasabaty;

  const amountRange = document.getElementById("amountRange");
  const amountInput = document.getElementById("amount");
  const amountVal = document.getElementById("amountVal");
  bindSlider(amountRange, amountInput, (v) => (amountVal.textContent = formatNumber(v, 0)));

  function wireSegmented(id) {
    const el = document.getElementById(id);
    el.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        el.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        el.dataset.value = btn.dataset.value;
      });
    });
  }
  ["liquiditySeg", "incomeSeg", "durationSeg"].forEach(wireSegmented);

  const INSTRUMENT_LABEL = { certificate: "شهادة ادخار", savings: "حساب توفير", gold: "ذهب" };

  function renderScenario(s) {
    const rows = s.allocation
      .map((a) => {
        const parts = [`<div class="stat"><span>${INSTRUMENT_LABEL[a.instrument] || a.instrument} — ${a.percent}%</span><b>${formatNumber(a.amount, 0)} ج.م</b></div>`];
        if (a.rate !== null && a.rate !== undefined) {
          parts.push(`<div class="stat"><span>العائد</span><b>${a.rate}%</b></div>`);
        }
        if (a.expected_total !== null && a.expected_total !== undefined) {
          parts.push(`<div class="stat"><span>إجمالي متوقع للمدة</span><b class="value-gain">${formatNumber(a.expected_total, 0)} ج.م</b></div>`);
        }
        if (a.grams !== null && a.grams !== undefined) {
          parts.push(`<div class="stat"><span>الوزن التقريبي</span><b>${formatNumber(a.grams, 2)} جم</b></div>`);
        }
        return `<div style="margin-bottom:10px; padding-bottom:10px; border-bottom:1px dashed var(--line);"><div style="font-weight:600; font-size:0.88rem; margin-bottom:4px;">${a.label}</div>${parts.join("")}</div>`;
      })
      .join("");

    return `<div class="compare-card ${s.id === "A" ? "best" : ""}">
      <div class="bank">سيناريو ${s.id}</div>
      <div class="name">${s.title}</div>
      <p class="text-soft" style="font-size:0.85rem;">${s.strategy}</p>
      ${rows}
    </div>`;
  }

  document.getElementById("planBtn").addEventListener("click", async () => {
    const errEl = document.getElementById("planError");
    errEl.style.display = "none";
    const payload = {
      amount: Number(amountInput.value),
      liquidity_need: document.getElementById("liquiditySeg").dataset.value,
      needs_income: document.getElementById("incomeSeg").dataset.value === "true",
      duration_years: Number(document.getElementById("durationSeg").dataset.value),
    };
    try {
      const data = await postJSON("/calculate/money-plan", payload);
      document.getElementById("scenarioCards").innerHTML = data.scenarios.map(renderScenario).join("");
      document.getElementById("goldNote").textContent = data.gold_note;
      document.getElementById("disclaimerText").textContent = data.disclaimer;
      document.getElementById("planResults").style.display = "block";
      document.getElementById("planResults").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      errEl.textContent = e.message;
      errEl.style.display = "block";
    }
  });
})();
