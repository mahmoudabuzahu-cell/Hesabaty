(function () {
  "use strict";
  const { formatNumber, debounce, postJSON, bindSlider } = window.Hasabaty;

  const amountNum = document.getElementById("amountNum");
  const amountRange = document.getElementById("amountRange");
  const rateNum = document.getElementById("rateNum");
  const rateRange = document.getElementById("rateRange");
  const yearsNum = document.getElementById("yearsNum");
  const yearsRange = document.getElementById("yearsRange");

  async function runCalc() {
    document.getElementById("amountOut").textContent = formatNumber(amountNum.value, 0);
    document.getElementById("rateOut").textContent = rateNum.value;
    document.getElementById("yearsOut").textContent = yearsNum.value;
    try {
      const r = await postJSON("/calculate/inflation", {
        amount: Number(amountNum.value),
        annual_inflation: Number(rateNum.value),
        years: Number(yearsNum.value),
      });
      document.getElementById("rFuture").textContent = formatNumber(r.future_value_needed);
      document.getElementById("rPower").textContent = formatNumber(r.purchasing_power_remaining);
      document.getElementById("rLost").textContent = r.value_lost_percent + "%";
    } catch (e) {
      /* تجاهل */
    }
  }
  const d = debounce(runCalc, 150);
  bindSlider(amountRange, amountNum, d);
  bindSlider(rateRange, rateNum, d);
  bindSlider(yearsRange, yearsNum, d);
  runCalc();
})();
