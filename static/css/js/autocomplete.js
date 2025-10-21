
(() => {
  const DEBOUNCE_MS = 160;

  function debounce(fn, ms) {
    let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }

  function renderItems(panel, items, limit) {
    panel.innerHTML = "";
    const max = Math.max(0, limit || items.length);
    items.slice(0, max).forEach((it, idx) => {
      // it can be string or {label, value, hint}
      const label = typeof it === "string" ? it : (it.label ?? it.value ?? "");
      const value = typeof it === "string" ? it : (it.value ?? label);
      const hint  = typeof it === "object" ? (it.hint ?? "") : "";
      const row = document.createElement("div");
      row.className = "ac-item";
      row.setAttribute("role", "option");
      row.setAttribute("id", `ac-${Math.random().toString(36).slice(2)}`);
      row.dataset.value = value;

      row.innerHTML = `
        <div>
          <div class="ac-label">${escapeHtml(label)}</div>
          ${hint ? `<div class="ac-hint">${escapeHtml(hint)}</div>` : ""}
        </div>
      `;
      if (idx === 0) row.setAttribute("aria-selected", "true");
      panel.appendChild(row);
    });
    panel.hidden = panel.children.length === 0;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  }

  function moveActive(panel, dir) {
    const els = [...panel.querySelectorAll(".ac-item")];
    if (!els.length) return;
    let i = els.findIndex(e => e.getAttribute("aria-selected") === "true");
    els.forEach(e => e.removeAttribute("aria-selected"));
    i = (i + dir + els.length) % els.length;
    els[i].setAttribute("aria-selected", "true");
    // ensure visible
    const el = els[i];
    const top = el.offsetTop, bottom = top + el.offsetHeight;
    if (top < panel.scrollTop) panel.scrollTop = top;
    else if (bottom > panel.scrollTop + panel.clientHeight) panel.scrollTop = bottom - panel.clientHeight;
  }

  async function fetchSuggest(endpoint, q) {
    const url = new URL(endpoint, window.location.origin);
    url.searchParams.set("q", q);
    const r = await fetch(url, { headers: { "Accept": "application/json" }});
    if (!r.ok) throw new Error("suggest failed");
    return r.json();
  }

  function attachAutocomplete(root) {
    const input   = root.querySelector(".ac-input");
    const panel   = root.querySelector(".ac-panel");
    const limit   = Number(root.dataset.limit || "6");
    const endpoint= root.dataset.endpoint;

    let last = "";

    const doQuery = debounce(async () => {
      const q = input.value.trim();
      if (!q || q === last) { panel.hidden = true; panel.innerHTML = ""; return; }
      last = q;
      try {
        const data = await fetchSuggest(endpoint, q);
        // Expected: array of strings or {label, value, hint}
        renderItems(panel, Array.isArray(data) ? data : [], limit);
      } catch {
        panel.hidden = true;
      }
    }, DEBOUNCE_MS);

    input.addEventListener("input", doQuery);
    input.addEventListener("focus", () => { if (panel.children.length) panel.hidden = false; });
    input.addEventListener("blur", () => setTimeout(()=> { panel.hidden = true; }, 120)); // allow click

    input.addEventListener("keydown", (e) => {
      if (panel.hidden && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        panel.hidden = false;
      }
      if (e.key === "ArrowDown") { moveActive(panel, +1); e.preventDefault(); }
      if (e.key === "ArrowUp")   { moveActive(panel, -1); e.preventDefault(); }
      if (e.key === "Escape")    { panel.hidden = true; }
      if (e.key === "Enter") {
        const sel = panel.querySelector('.ac-item[aria-selected="true"]');
        if (sel) {
          input.value = sel.dataset.value || input.value;
          panel.hidden = true;
        }
      }
    });

    panel.addEventListener("mousedown", (e) => {
      const item = e.target.closest(".ac-item");
      if (!item) return;
      input.value = item.dataset.value || input.value;
      panel.hidden = true;
      // submit on click? uncomment if desired:
      // input.form?.submit();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".autocomplete").forEach(attachAutocomplete);
  });
})();

