(function () {
  "use strict";
  const { formatNumber, debounce, postJSON, bindSlider } = window.Hasabaty;

  const netNum = document.getElementById("netNum");
  const netRange = document.getElementById("netRange");

  async function runCalc() {
    document.getElementById("netOut").textContent = formatNumber(netNum.value, 0);
    const errorBox = document.getElementById("errorBox");
    try {
      const r = await postJSON("/calculate/salary", { net_monthly: Number(netNum.value) });
      errorBox.style.display = "none";
      document.getElementById("rGross").textContent = formatNumber(r.gross_monthly);
      document.getElementById("rGrossWords").textContent = window.Hasabaty.tafqeet(r.gross_monthly);
      document.getElementById("rIns").textContent = formatNumber(r.insurance_monthly);
      document.getElementById("rTax").textContent = formatNumber(r.tax_monthly);
      document.getElementById("rNet").textContent = formatNumber(r.net_monthly);
      document.getElementById("rSource").textContent = r.rules_source ? "المصدر: " + r.rules_source : "";
    } catch (e) {
      errorBox.style.display = "block";
      errorBox.textContent = e.message;
    }
  }
  bindSlider(netRange, netNum, debounce(runCalc, 180));
  runCalc();
})();
