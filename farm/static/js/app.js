(function () {
  const app = document.getElementById("app");

  // ---- sidebar collapse (remembered per browser) and mobile drawer
  try { if (localStorage.getItem("zf-mini") === "1" && window.innerWidth >= 992) app.classList.add("mini"); } catch (e) {}
  const toggle = document.getElementById("sidebarToggle");
  if (toggle) toggle.addEventListener("click", () => {
    app.classList.toggle("mini");
    try { localStorage.setItem("zf-mini", app.classList.contains("mini") ? "1" : "0"); } catch (e) {}
  });
  const mobile = document.getElementById("mobileMenu");
  if (mobile) mobile.addEventListener("click", () => app.classList.add("mobile-open"));
  const backdrop = document.getElementById("sidebarBackdrop");
  if (backdrop) backdrop.addEventListener("click", () => app.classList.remove("mobile-open"));

  document.querySelectorAll(".side-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (app && app.classList.contains("mini")) { app.classList.remove("mini"); }
      btn.parentElement.classList.toggle("open");
    });
  });

  // ---- confirm destructive forms
  document.addEventListener("submit", (e) => {
    const msg = e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // ---- line-item tables (purchases, invoices, feed formulas)
  document.querySelectorAll(".lines-table").forEach((table) => {
    const body = table.querySelector("tbody");
    const template = body.querySelector(".line-row").cloneNode(true);
    const totalCols = (table.dataset.totalCols || "").split(",").filter(Boolean);

    function recompute() {
      if (totalCols.length !== 2) return;
      let total = 0;
      body.querySelectorAll(".line-row").forEach((row) => {
        const a = parseFloat(row.querySelector(`[name="l_${totalCols[0]}"]`).value) || 0;
        const b = parseFloat(row.querySelector(`[name="l_${totalCols[1]}"]`).value) || 0;
        const amt = a * b;
        total += amt;
        row.querySelector(".line-amount").textContent = amt.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      });
      table.querySelector(".lines-total").textContent = total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    table.querySelector(".add-line").addEventListener("click", () => {
      const row = template.cloneNode(true);
      row.querySelectorAll("input, select, textarea").forEach((el) => {
        if (el.tagName === "SELECT") el.selectedIndex = 0; else el.value = "";
      });
      body.appendChild(row);
      recompute();
    });
    body.addEventListener("click", (e) => {
      const btn = e.target.closest(".remove-line");
      if (!btn) return;
      const rows = body.querySelectorAll(".line-row");
      if (rows.length > 1) btn.closest(".line-row").remove();
      else btn.closest(".line-row").querySelectorAll("input, select").forEach((el) => (el.value = ""));
      recompute();
    });
    body.addEventListener("input", recompute);
    recompute();
  });
})();
