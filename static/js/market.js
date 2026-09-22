(function () {
  "use strict";
  const { formatNumber, getJSON } = window.Hasabaty;
  let history = window.__HISTORY__ || [];
  let latestPrices = null;
  let latestEgx = null;

  function sparkline(values, color) {
    if (!values || values.length < 2) return "";
    const w = 70, h = 24, pad = 2;
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const pts = values
      .map((v, i) => {
        const x = pad + (i / (values.length - 1)) * (w - pad * 2);
        const y = h - pad - ((v - min) / range) * (h - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
    return `<svg class="sparkline" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.8"/></svg>`;
  }

  function renderCurrency(prices) {
    const body = document.getElementById("currencyBody");
    const rows = Object.entries(prices.currency || {});
    body.innerHTML = rows
      .map(([code, c]) => {
        const key = code === "USD" ? "usd_egp" : code === "EUR" ? "eur_egp" : null;
        const spark = key ? sparkline(history.map((h) => h[key]).filter((v) => v !== undefined), "var(--brand-bright)") : "";
        return `<tr><td>${c.name} (${code})</td><td>${formatNumber(c.buy)}</td><td>${formatNumber(c.sell)}</td><td>${spark}</td></tr>`;
      })
      .join("");

    const fromSel = document.getElementById("convFrom");
    if (!fromSel.dataset.filled) {
      fromSel.innerHTML = rows.map(([code, c]) => `<option value="${code}">${c.name} (${code})</option>`).join("");
      fromSel.dataset.filled = "1";
    }
  }

  function renderGold(prices) {
    const g = prices.gold || {};
    const spark = sparkline(history.map((h) => h.gold_21k).filter((v) => v !== undefined), "var(--gold)");
    document.getElementById("goldBody").innerHTML = `
      <tr><td>عيار 24 (جرام)</td><td class="num">${formatNumber(g["24k"])}</td><td>${spark}</td></tr>
      <tr><td>عيار 21 (جرام)</td><td class="num">${formatNumber(g["21k"])}</td><td></td></tr>
      <tr><td>عيار 18 (جرام)</td><td class="num">${formatNumber(g["18k"])}</td><td></td></tr>
      <tr><td>الجنيه الذهب (٨ جم، عيار 21)</td><td class="num">${formatNumber(g.pound_21k)}</td><td></td></tr>
      <tr><td>أوقية عالمية (دولار)</td><td class="num">${formatNumber(g.ounce_usd)}</td><td></td></tr>
    `;
    document.getElementById("goldGauge").textContent =
      "الأسعار محسوبة من السعر العالمي للأوقية × سعر صرف الدولار، فقد تختلف قليلاً عن سعر محل صاغة معين في منطقتك.";
  }

  function renderSilver(prices) {
    const s = prices.silver || {};
    document.getElementById("silverBody").innerHTML = `<tr><td>عيار 999 (جرام)</td><td class="num">${formatNumber(s["999"])}</td></tr>`;
  }

  const EGX_LABELS = { EGX30: "EGX 30", EGX70: "EGX 70", EGX100: "EGX 100" };

  function renderEgx(egx) {
    const indices = egx.indices || {};
    const idxEl = document.getElementById("egxIndices");
    const entries = Object.entries(indices);
    idxEl.innerHTML = entries.length
      ? entries
          .map(([name, v]) => {
            const up = (v.change || 0) >= 0;
            const label = EGX_LABELS[name] || name;
            return `<div class="card"><div class="text-soft" style="font-size:0.8rem;">${label}</div><div class="num" style="font-size:1.4rem; font-weight:700;">${formatNumber(v.value, 0)}</div><div class="${up ? "value-gain" : "value-cost"} num">${up ? "▲" : "▼"} ${Math.abs(v.change || 0)}%</div></div>`;
          })
          .join("")
      : `<p class="text-soft">بيانات المؤشر غير متاحة حالياً.</p>`;

    const moversEl = document.getElementById("egxMovers");
    const groups = [
      { key: "top_gainers", label: "الأعلى ارتفاعاً" },
      { key: "top_losers", label: "الأعلى انخفاضاً" },
      { key: "most_active", label: "الأعلى تداولاً" },
    ];
    const anyMovers = groups.some((g) => (egx[g.key] || []).length);
    moversEl.innerHTML = anyMovers
      ? groups
          .map(
            (g) => `<div><h3 style="font-size:0.95rem;">${g.label}</h3>${(egx[g.key] || [])
              .map((s) => `<div class="result-row"><span class="k">${s.symbol || s.name}</span><span class="v num">${s.change_percent ?? s.value ?? ""}</span></div>`)
              .join("") || '<p class="text-soft" style="font-size:0.8rem;">—</p>'}</div>`
          )
          .join("")
      : "";

    document.getElementById("egxNote").textContent = anyMovers
      ? ""
      : "مؤشر EGX30 يتحدث تلقائياً دايماً بدون إعداد إضافي. مؤشر EGX70 والأعلى ارتفاعاً وانخفاضاً وتداولاً بيانات تحتاج مصدر إضافي (اختياري) — راجع ملف README لتفعيلها؛ لحد ما يتفعّل، القيمة المعروضة هي آخر قيمة معروفة وليست لحظية.";
  }

  function renderFuel(fuel) {
    const el = document.getElementById("fuelBody");
    if (!el || !fuel || !fuel.prices) return;
    const p = fuel.prices;
    const rows = [
      ["بنزين 80", p.gasoline80],
      ["بنزين 92", p.gasoline92],
      ["بنزين 95", p.gasoline95],
      ["سولار", p.diesel],
      ["غاز تموين السيارات (للمتر)", p.cng],
      ["أسطوانة البوتاجاز", p.butane_cylinder],
    ];
    el.innerHTML = rows.map(([label, v]) => `<tr><td>${label}</td><td class="num">${formatNumber(v)} ج.م</td></tr>`).join("");
    const noteEl = document.getElementById("fuelNote");
    if (noteEl) {
      const eff = fuel.effective_from ? new Date(fuel.effective_from).toLocaleDateString("ar-EG", { year: "numeric", month: "long", day: "numeric" }) : null;
      noteEl.textContent = eff
        ? `أسعار حكومية رسمية سارية منذ ${eff}، وليست بيانات لحظية — تتغير فقط عند صدور قرار جديد من لجنة تسعير المنتجات البترولية.`
        : "أسعار حكومية رسمية، وليست بيانات لحظية.";
    }
  }

  async function refresh() {
    try {
      const { prices, egx, fuel } = await getJSON("/api/market");
      latestPrices = prices;
      latestEgx = egx;
      renderCurrency(prices);
      renderGold(prices);
      renderSilver(prices);
      renderEgx(egx);
      renderFuel(fuel);
      if (prices.last_updated) {
        const d = new Date(prices.last_updated);
        document.getElementById("lastUpdatedLine").textContent = "آخر تحديث: " + d.toLocaleString("ar-EG");
      }
      convert();
      checkAlerts(prices);
    } catch (e) {
      /* تجاهل */
    }
  }

  function convert() {
    if (!latestPrices) return;
    const amount = Number(document.getElementById("convAmount").value) || 0;
    const code = document.getElementById("convFrom").value;
    const c = (latestPrices.currency || {})[code];
    if (!c) return;
    document.getElementById("convResult").textContent = `${formatNumber(amount, 0)} ${code} ≈ ${formatNumber(amount * c.sell)} ج.م`;
  }
  document.getElementById("convAmount").addEventListener("input", convert);
  document.getElementById("convFrom").addEventListener("change", convert);

  // تنبيهات الأسعار (محلية في المتصفح فقط)
  const ALERTS_KEY = "hasabaty:price-alerts";
  function loadAlerts() {
    try {
      return JSON.parse(localStorage.getItem(ALERTS_KEY) || "[]");
    } catch (e) {
      return [];
    }
  }
  function saveAlerts(list) {
    localStorage.setItem(ALERTS_KEY, JSON.stringify(list));
  }
  function renderAlerts() {
    const list = loadAlerts();
    const assetLabel = { usd_sell: "الدولار (بيع)", gold_21k: "ذهب عيار 21", silver: "الفضة" };
    document.getElementById("alertsList").innerHTML = list
      .map(
        (a, i) => `<div class="result-row"><span class="k">${assetLabel[a.asset]} ${a.direction === "above" ? "≥" : "≤"} ${a.target} ${a.triggered ? "— تم التنبيه ✓" : ""}</span><button class="btn btn-ghost btn-sm" data-idx="${i}">حذف</button></div>`
      )
      .join("");
    document.getElementById("alertsList").querySelectorAll("button[data-idx]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const list2 = loadAlerts();
        list2.splice(Number(btn.dataset.idx), 1);
        saveAlerts(list2);
        renderAlerts();
      });
    });
  }
  function currentValue(prices, asset) {
    if (!prices) return null;
    if (asset === "usd_sell") return prices.currency && prices.currency.USD ? prices.currency.USD.sell : null;
    if (asset === "gold_21k") return prices.gold ? prices.gold["21k"] : null;
    if (asset === "silver") return prices.silver ? prices.silver["999"] : null;
    return null;
  }
  function checkAlerts(prices) {
    const list = loadAlerts();
    let changed = false;
    list.forEach((a) => {
      if (a.triggered) return;
      const val = currentValue(prices, a.asset);
      if (val === null) return;
      const hit = a.direction === "above" ? val >= a.target : val <= a.target;
      if (hit) {
        a.triggered = true;
        changed = true;
        if (window.Notification && Notification.permission === "granted") {
          new Notification("حساباتى — تنبيه سعر", { body: `${a.asset} وصل ${formatNumber(val)}` });
        }
      }
    });
    if (changed) {
      saveAlerts(list);
      renderAlerts();
    }
  }
  document.getElementById("addAlertBtn").addEventListener("click", () => {
    const asset = document.getElementById("alertAsset").value;
    const direction = document.getElementById("alertDirection").value;
    const target = Number(document.getElementById("alertTarget").value);
    if (!target) return;
    if (window.Notification && Notification.permission === "default") {
      Notification.requestPermission();
    }
    const list = loadAlerts();
    list.push({ asset, direction, target, triggered: false });
    saveAlerts(list);
    renderAlerts();
  });

  renderAlerts();
  refresh();
  setInterval(refresh, 60000);
})();
