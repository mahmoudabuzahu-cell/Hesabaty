(function () {
  "use strict";
  const { formatNumber, debounce, postJSON, bindSlider } = window.Hasabaty;

  const salaryNum = document.getElementById("salaryNum");
  const salaryRange = document.getElementById("salaryRange");
  const yearsNum = document.getElementById("yearsNum");
  const yearsRange = document.getElementById("yearsRange");

  async function runCalc() {
    document.getElementById("salaryOut").textContent = formatNumber(salaryNum.value, 0);
    document.getElementById("yearsOut").textContent = yearsNum.value;
    try {
      const r = await postJSON("/calculate/end-of-service", {
        salary: Number(salaryNum.value),
        uncovered_years: Number(yearsNum.value),
      });
      document.getElementById("rTotal").textContent = formatNumber(r.total_gratuity);
      document.getElementById("rHalf").textContent = r.years_at_half_month + " سنوات";
      document.getElementById("rFull").textContent = r.years_at_full_month + " سنوات";
    } catch (e) {
      /* تجاهل */
    }
  }
  const d = debounce(runCalc, 150);
  bindSlider(salaryRange, salaryNum, d);
  bindSlider(yearsRange, yearsNum, d);
  runCalc();
})();
