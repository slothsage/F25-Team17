document.addEventListener("DOMContentLoaded", () => {
    const selectEl = document.querySelector("#sponsors");
    if (!selectEl) return;

    // Hide <select>
    selectEl.style.display = "none";

    // Create visual checkbox list container
    const wrapper = document.createElement("div");
    wrapper.className = "checkbox-multiselect-wrapper";
    wrapper.style.maxHeight = "300px";
    wrapper.style.overflowY = "auto";
    wrapper.style.border = "1px solid #ccc";
    wrapper.style.borderRadius = "6px";
    wrapper.style.padding = "12px";
    wrapper.style.width = "400px";
    wrapper.style.background = "#fafafa";

    // Build checkboxes based on <select> options
    Array.from(selectEl.options).forEach(option => {
        const row = document.createElement("label");
        row.style.display = "flex";
        row.style.alignItems = "center";
        row.style.gap = "8px";
        row.style.padding = "4px 0";
        row.style.cursor = "pointer";

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = option.value;
        cb.checked = option.selected;
        cb.dataset.optionValue = option.value;

        row.appendChild(cb);
        row.appendChild(document.createTextNode(option.text));
        wrapper.appendChild(row);
    });

    selectEl.insertAdjacentElement("afterend", wrapper);

    // Sync checkbox → <select>
    function syncToSelect() {
        const selectedValues = Array.from(
            wrapper.querySelectorAll("input[type=checkbox]:checked")
        ).map(cb => cb.value);

        Array.from(selectEl.options).forEach(opt => {
            opt.selected = selectedValues.includes(opt.value);
        });
    }

    wrapper.addEventListener("change", syncToSelect);

    // === Select All ===
    const btnSelectAll = document.querySelector("#select-all-sponsors");
    if (btnSelectAll) {
        btnSelectAll.addEventListener("click", () => {
            wrapper.querySelectorAll("input[type=checkbox]").forEach(cb => cb.checked = true);
            syncToSelect();
        });
    }

    // === Clear All ===
    const btnClearAll = document.querySelector("#clear-all-sponsors");
    if (btnClearAll) {
        btnClearAll.addEventListener("click", () => {
            wrapper.querySelectorAll("input[type=checkbox]").forEach(cb => cb.checked = false);
            syncToSelect();
        });
    }
});