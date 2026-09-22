// حساباتى — أدوات مشتركة تُستخدم في كل صفحات الموقع
(function () {
  "use strict";

  // ---------------------------------------------------------------------
  // القوائم: قائمة الجوال + شريط الحاسبات
  // ---------------------------------------------------------------------
  const navToggle = document.getElementById("navToggle");
  const mainNav = document.getElementById("mainNav");
  if (navToggle && mainNav) {
    navToggle.addEventListener("click", () => {
      const open = mainNav.classList.toggle("open");
      navToggle.setAttribute("aria-expanded", String(open));
    });
  }

  const calcToggle = document.getElementById("calcDropdownToggle");
  const calcStrip = document.getElementById("calcStrip");
  if (calcToggle && calcStrip) {
    // الشريط بيتفتح من السيرفر (Jinja) على صفحات الحاسبات، فبنزامن حالة الزر معاه
    if (calcStrip.classList.contains("open")) {
      calcToggle.setAttribute("aria-expanded", "true");
      const active = calcStrip.querySelector("a.active");
      if (active) active.scrollIntoView({ block: "nearest" });
    }
    calcToggle.addEventListener("click", () => {
      const open = calcStrip.classList.toggle("open");
      calcToggle.setAttribute("aria-expanded", String(open));
      if (open) {
        const active = calcStrip.querySelector("a.active");
        if (active) active.scrollIntoView({ block: "nearest" });
      }
    });
  }

  // ---------------------------------------------------------------------
  // أدوات عامة يُعاد استخدامها في سكربتات الصفحات
  // ---------------------------------------------------------------------
  const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
  const fmt0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

  function formatNumber(value, decimals) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return decimals === 0 ? fmt0.format(value) : fmt.format(value);
  }

  function debounce(fn, wait) {
    let t;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), wait);
    };
  }

  async function postJSON(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const message = (data && data.detail) || "تعذر إتمام الحساب، تحقق من القيم المدخلة.";
      throw new Error(message);
    }
    return data;
  }

  async function getJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error("تعذر تحميل البيانات");
    return res.json();
  }

  // يربط شريط تمرير (range) بحقل رقم (number) في الاتجاهين
  function bindSlider(rangeEl, numberEl, onChange) {
    if (!rangeEl || !numberEl) return;
    const sync = (value) => {
      rangeEl.value = value;
      numberEl.value = value;
      if (onChange) onChange(Number(value));
    };
    rangeEl.addEventListener("input", () => sync(rangeEl.value));
    numberEl.addEventListener("input", () => {
      let v = Number(numberEl.value);
      const min = Number(rangeEl.min), max = Number(rangeEl.max);
      if (Number.isNaN(v)) return;
      if (v < min) v = min;
      if (v > max) v = max;
      rangeEl.value = v;
      if (onChange) onChange(v);
    });
  }

  // ومضة لون خفيفة عند تغيّر قيمة خلية سعر
  function flashCell(el, direction) {
    if (!el) return;
    el.classList.remove("flash-up", "flash-down");
    // إعادة تشغيل الأنيميشن
    void el.offsetWidth;
    el.classList.add(direction > 0 ? "flash-up" : "flash-down");
  }

  function waLink(text) {
    return "https://wa.me/?text=" + encodeURIComponent(text);
  }

  // تنزيل ملف تقويم (.ics) بسيط لتذكير بتاريخ مستقبلي — لا يحتاج خادم بريد
  function downloadICS({ title, description, date }) {
    const dt = date.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
    const ics = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "PRODID:-//hasabaty//ar",
      "BEGIN:VEVENT",
      "UID:" + Date.now() + "@hasabaty",
      "DTSTAMP:" + dt,
      "DTSTART;VALUE=DATE:" + date.toISOString().slice(0, 10).replace(/-/g, ""),
      "SUMMARY:" + title,
      "DESCRIPTION:" + description,
      "END:VEVENT",
      "END:VCALENDAR",
    ].join("\r\n");
    const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "تذكير-حساباتى.ics";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  // ---------------------------------------------------------------------
  // تفقيط: تحويل رقم إلى كتابة عربية (جنيه مصري افتراضياً)
  // ---------------------------------------------------------------------
  const TQ_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"];
  const TQ_TEENS = ["عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر"];
  const TQ_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"];
  const TQ_HUNDREDS = ["", "مائة", "مئتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"];
  const TQ_SCALES = [null, ["ألف", "ألفا", "آلاف"], ["مليون", "مليونا", "ملايين"], ["مليار", "مليارا", "مليارات"]];

  function tqThreeDigits(n) {
    if (n === 0) return "";
    const h = Math.floor(n / 100);
    const rem = n % 100;
    const parts = [];
    if (h > 0) parts.push(TQ_HUNDREDS[h]);
    if (rem > 0) {
      if (rem < 10) parts.push(TQ_ONES[rem]);
      else if (rem < 20) parts.push(TQ_TEENS[rem - 10]);
      else {
        const t = Math.floor(rem / 10),
          o = rem % 10;
        parts.push(o === 0 ? TQ_TENS[t] : TQ_ONES[o] + " و" + TQ_TENS[t]);
      }
    }
    return parts.join(" و");
  }

  function tqScaleWord(n, names) {
    if (n === 2) return names[1];
    if (n >= 3 && n <= 10) return names[2];
    return names[0];
  }

  function tqConvertInteger(num) {
    if (num === 0) return "صفر";
    const groups = [];
    let n = num;
    while (n > 0) {
      groups.unshift(n % 1000);
      n = Math.floor(n / 1000);
    }
    const lastIdx = groups.length - 1;
    const parts = [];
    groups.forEach((g, idx) => {
      if (g === 0) return;
      const scalePos = lastIdx - idx;
      let text = tqThreeDigits(g);
      if (scalePos > 0) {
        const names = TQ_SCALES[scalePos];
        if (g === 1) text = names[0];
        else if (g === 2) text = names[1];
        else text = text + " " + tqScaleWord(g, names);
      }
      parts.push(text);
    });
    return parts.join(" و");
  }

  function tqUnitForm(n, forms) {
    // الحكم النحوي على التمييز مبني على باقي القسمة على 100: صفر يعني إضافة (بلا تنوين)، 3-10 جمع، غير ذلك منصوب
    const rem = n % 100;
    if (rem === 0) return forms.one;
    if (rem >= 3 && rem <= 10) return forms.few;
    return forms.many;
  }

  function tafqeetToWords(amount, unit, subUnit) {
    unit = unit || { one: "جنيه", two: "جنيهان", few: "جنيهات", many: "جنيهاً" };
    subUnit = subUnit || { one: "قرش", two: "قرشان", few: "قروش", many: "قرشاً" };
    amount = Math.round(Math.abs(Number(amount) || 0) * 100) / 100;
    const intPart = Math.floor(amount);
    const fraction = Math.round((amount - intPart) * 100);

    let result;
    if (intPart === 0) result = "صفر " + unit.one;
    else if (intPart === 1) result = unit.one + " واحد";
    else if (intPart === 2) result = unit.two;
    else result = tqConvertInteger(intPart) + " " + tqUnitForm(intPart, unit);

    if (fraction > 0) {
      let fracWords;
      if (fraction === 1) fracWords = subUnit.one + " واحد";
      else if (fraction === 2) fracWords = subUnit.two;
      else fracWords = tqConvertInteger(fraction) + " " + tqUnitForm(fraction, subUnit);
      result += " و" + fracWords;
    }
    return result + " فقط لا غير";
  }

  // ---------------------------------------------------------------------
  // سجل محلي لآخر العمليات الحسابية (بدون أي حساب مستخدم أو خادم)
  // ---------------------------------------------------------------------
  const HISTORY_KEY = "hasabaty_history_v1";
  const HISTORY_MAX = 8;

  function getHistory(calculator) {
    try {
      const all = JSON.parse(localStorage.getItem(HISTORY_KEY) || "{}");
      return calculator ? all[calculator] || [] : all;
    } catch (e) {
      return calculator ? [] : {};
    }
  }

  function saveHistory(calculator, label, summary) {
    try {
      const all = JSON.parse(localStorage.getItem(HISTORY_KEY) || "{}");
      const list = all[calculator] || [];
      list.unshift({ label, summary, at: new Date().toISOString() });
      all[calculator] = list.slice(0, HISTORY_MAX);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(all));
    } catch (e) {
      // التخزين المحلي غير متاح (وضع تصفح خاص مثلاً) — تجاهل بصمت
    }
  }

  function clearHistory(calculator) {
    try {
      const all = JSON.parse(localStorage.getItem(HISTORY_KEY) || "{}");
      if (calculator) delete all[calculator];
      else Object.keys(all).forEach((k) => delete all[k]);
      localStorage.setItem(HISTORY_KEY, JSON.stringify(all));
    } catch (e) {
      /* تجاهل */
    }
  }

  // تصدير جدول HTML أو مصفوفة بيانات كملف Excel (يحتاج تحميل SheetJS في الصفحة أولاً)
  function exportTableToExcel(tableEl, filename) {
    if (typeof XLSX === "undefined") {
      alert("تعذر تحميل مكتبة تصدير الإكسل. تحقق من اتصالك بالإنترنت وأعد المحاولة.");
      return;
    }
    const wb = XLSX.utils.table_to_book(tableEl, { sheet: "البيانات" });
    XLSX.writeFile(wb, filename.endsWith(".xlsx") ? filename : filename + ".xlsx");
  }

  function exportRowsToExcel(rows, filename, sheetName) {
    if (typeof XLSX === "undefined") {
      alert("تعذر تحميل مكتبة تصدير الإكسل. تحقق من اتصالك بالإنترنت وأعد المحاولة.");
      return;
    }
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, sheetName || "البيانات");
    XLSX.writeFile(wb, filename.endsWith(".xlsx") ? filename : filename + ".xlsx");
  }

  window.Hasabaty = {
    formatNumber,
    debounce,
    postJSON,
    getJSON,
    bindSlider,
    flashCell,
    waLink,
    downloadICS,
    tafqeet: tafqeetToWords,
    saveHistory,
    getHistory,
    clearHistory,
    exportTableToExcel,
    exportRowsToExcel,
  };

  // ---------------------------------------------------------------------
  // الشريط الحي للأسعار — يظهر أعلى الصفحة الرئيسية وصفحة الأسعار اللحظية
  // ---------------------------------------------------------------------
  const liveStrip = document.querySelector("[data-live-strip]");
  if (liveStrip) {
    const refresh = async () => {
      try {
        const { prices, egx } = await getJSON("/api/market");
        const setVal = (key, value, changeSelector, change) => {
          const el = liveStrip.querySelector(`[data-key="${key}"]`);
          if (!el) return;
          const oldVal = el.textContent.trim();
          const newVal = value;
          if (oldVal && oldVal !== "—" && Number(oldVal.replace(/,/g, "")) !== Number(String(newVal).replace(/,/g, ""))) {
            flashCell(el.closest(".item"), Number(newVal) > Number(oldVal.replace(/,/g, "")) ? 1 : -1);
          }
          el.textContent = value;
          if (changeSelector && change !== undefined && change !== null) {
            const chEl = liveStrip.querySelector(changeSelector);
            if (chEl) {
              chEl.textContent = (change > 0 ? "▲ " : change < 0 ? "▼ " : "") + Math.abs(change) + "%";
              chEl.classList.toggle("up", change > 0);
              chEl.classList.toggle("down", change < 0);
            }
          }
        };
        if (prices && prices.currency && prices.currency.USD) setVal("usd", formatNumber(prices.currency.USD.mid || prices.currency.USD.sell, 2));
        if (prices && prices.gold && prices.gold["21k"]) setVal("gold21", formatNumber(prices.gold["21k"], 0));
        if (egx && egx.indices && egx.indices.EGX30) {
          setVal("egx30", formatNumber(egx.indices.EGX30.value, 0), '[data-key="egx30-chg"]', egx.indices.EGX30.change);
        }
        try {
          const cbeData = await getJSON("/data");
          const deposit = cbeData && cbeData.cbe && cbeData.cbe.policy_rates && cbeData.cbe.policy_rates.overnight_deposit;
          const wrap = liveStrip.querySelector('[data-key-wrap="policy"]');
          if (deposit && wrap) {
            wrap.style.display = "";
            setVal("policy", deposit + "%");
          }
        } catch (e) {
          /* بيانات البنك المركزي غير متاحة بعد — تجاهل بصمت */
        }
        const updatedEl = liveStrip.querySelector("[data-updated]");
        if (updatedEl && prices && prices.last_updated) {
          const d = new Date(prices.last_updated);
          updatedEl.textContent = "آخر تحديث: " + d.toLocaleTimeString("ar-EG", { hour: "2-digit", minute: "2-digit" });
        }
      } catch (e) {
        // تجاهل بصمت — تبقى القيم المعروضة من التحميل الأول
      }
    };
    refresh();
    setInterval(refresh, 60000);
  }
})();
