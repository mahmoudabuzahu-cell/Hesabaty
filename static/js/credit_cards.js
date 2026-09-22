(function () {
  "use strict";
  const { formatNumber, bindSlider, postJSON } = window.Hasabaty;

  bindSlider(document.getElementById("incomeRange"), document.getElementById("income"), (v) => (document.getElementById("incomeVal").textContent = formatNumber(v, 0)));
  bindSlider(document.getElementById("balanceRange"), document.getElementById("balance"), (v) => (document.getElementById("balanceVal").textContent = formatNumber(v, 0)));
  bindSlider(document.getElementById("rateRange"), document.getElementById("rate"), (v) => (document.getElementById("rateVal").textContent = v));
  bindSlider(document.getElementById("minPercentRange"), document.getElementById("minPercent"), (v) => (document.getElementById("minPercentVal").textContent = v));

  const needSeg = document.getElementById("needSeg");
  needSeg.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      needSeg.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      needSeg.dataset.value = btn.dataset.value;
    });
  });

  function cardHtml(card, best) {
    return `<div class="compare-card ${best ? "best" : ""}">
      <div class="bank">${card.bank}</div>
      <div class="name">${card.name}</div>
      <p class="text-soft" style="font-size:0.85rem;">${card.highlight}</p>
      <div class="stat"><span>الحد الأدنى للدخل</span><b>${formatNumber(card.min_monthly_income, 0)} ج.م</b></div>
      <div class="stat"><span>الرسوم السنوية</span><b>${formatNumber(card.annual_fee, 0)} ج.م</b></div>
      ${best ? '<div class="badges"><span class="badge badge-gold">أقرب ترشيح لاحتياجك</span></div>' : ""}
      ${card.notes ? `<span class="src">${card.notes}</span>` : ""}
      <span class="src">آخر تحقق: ${card.checked_at || "—"}</span>
    </div>`;
  }

  document.getElementById("recommendBtn").addEventListener("click", async () => {
    const errEl = document.getElementById("recError");
    errEl.style.display = "none";
    try {
      const data = await postJSON("/recommend-credit-card", {
        monthly_income: Number(document.getElementById("income").value),
        primary_need: needSeg.dataset.value,
      });
      const wrap = document.getElementById("recResults");
      const note = document.getElementById("recNote");
      if (!data.recommended.length) {
        wrap.innerHTML = "";
        note.textContent = "مفيش بطاقة في قاعدة البيانات الحالية بتناسب الدخل ده. جرب دخل أعلى أو راجع فروع البنوك مباشرة لخيارات دخول أساسية.";
        return;
      }
      wrap.innerHTML = data.recommended.map((c, i) => cardHtml(c, i === 0)).join("");
      note.textContent = `عندك ${data.eligible_count} بطاقة من أصل ${data.total_cards} في قاعدة بياناتنا (لسه في تطوير) مؤهل ليها حسب دخلك. ${data.market_facts.annual_interest_rate_equivalent_note || ""}`;
    } catch (e) {
      errEl.textContent = e.message;
      errEl.style.display = "block";
    }
  });

  document.getElementById("costBtn").addEventListener("click", async () => {
    try {
      const data = await postJSON("/calculate/credit-card-balance-cost", {
        balance: Number(document.getElementById("balance").value),
        monthly_interest_rate_percent: Number(document.getElementById("rate").value),
        min_payment_percent: Number(document.getElementById("minPercent").value),
      });
      const resultEl = document.getElementById("costResult");
      if (data.never_paid_off) {
        document.getElementById("monthsFigure").textContent = "∞";
        document.getElementById("costRows").innerHTML = "";
        document.getElementById("costNote").textContent = data.message;
      } else {
        document.getElementById("monthsFigure").textContent = formatNumber(data.months_to_payoff, 0);
        document.getElementById("costRows").innerHTML = `
          <div class="result-row"><span class="k">إجمالي الفوائد اللي هتدفعها</span><span class="v value-cost">${formatNumber(data.total_interest_paid, 0)} ج.م</span></div>
          <div class="result-row"><span class="k">إجمالي المبلغ المدفوع فعلياً</span><span class="v">${formatNumber(data.total_paid, 0)} ج.م</span></div>
        `;
        document.getElementById("costNote").textContent = data.note + " ولو سددت الرصيد بالكامل بدل الحد الأدنى، الفايدة كانت هتبقى صفر جنيه.";
      }
      resultEl.style.display = "block";
    } catch (e) {
      alert(e.message);
    }
  });
})();
