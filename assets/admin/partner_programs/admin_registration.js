"use strict";
document.addEventListener("DOMContentLoaded", () => {
  const editor = document.getElementById("registration-editor");
  let dirty = false;
  editor?.addEventListener("input", () => { dirty = true; });
  editor?.addEventListener("change", () => { dirty = true; });
  editor?.addEventListener("submit", () => { dirty = false; });
  window.addEventListener("beforeunload", event => {
    if (dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  const add = document.getElementById("add-registration-field");
  const total = document.getElementById("id_fields-TOTAL_FORMS");
  function updateField(row, changed) {
    const type = row.querySelector('[name$="-type"]');
    const source = row.querySelector('[name$="-source"]');
    const list = ["select", "multiselect"].includes(type.value);
    if (changed === type && !list) {
      source.value = "own";
      row.querySelector('[name$="-allow_other"]').checked = false;
    }
    if ((changed === type && !list) || (changed === source && source.value !== "own")) {
      row.querySelector('[name$="-options"]').value = "";
      row.querySelector('[name$="-options_file"]').value = "";
    }
    for (const name of ["source", "options", "options_file", "allow_other"]) {
      const ownOnly = ["options", "options_file"].includes(name);
      row.querySelector(`[name$="-${name}"]`).closest(".form-row").hidden =
        !list || (ownOnly && source.value !== "own");
    }
  }
  document.querySelectorAll(".registration-field").forEach(row => updateField(row));
  editor?.addEventListener("change", event => {
    const row = event.target.closest(".registration-field");
    if (row) updateField(row, event.target);
  });
  add?.addEventListener("click", event => {
    event.preventDefault();
    const count = Number(total.value);
    if (count >= 100) {
      alert("В анкете может быть не более 100 полей.");
      return;
    }
    const template = document.getElementById("registration-empty-field");
    const wrapper = document.createElement("div");
    wrapper.innerHTML = template.innerHTML.replaceAll("__prefix__", String(count));
    const row = wrapper.firstElementChild;
    row.querySelector('[name$="-ORDER"]').value = count + 1;
    document.querySelector("[data-empty-fields]")?.remove();
    document.getElementById("registration-fields").append(row);
    updateField(row);
    total.value = count + 1;
    dirty = true;
    row.querySelector('[name$="-label"]').focus();
  });
  document.querySelector("[data-copy-link]")?.addEventListener("click", async () => {
    const link = document.getElementById("registration-link");
    const status = document.querySelector("[data-copy-status]");
    try {
      await navigator.clipboard.writeText(link.value);
      status.textContent = "Ссылка скопирована.";
    } catch {
      link.focus();
      link.select();
      status.textContent = "Скопируйте выделенную ссылку.";
    }
  });
  document.querySelector("[data-mobile-preview]")?.addEventListener("change", event => {
    document.querySelector(".registration-preview-body").classList.toggle("mobile", event.target.checked);
  });
  const preview = document.getElementById("registration-preview");
  if (preview) {
    preview.focus();
  }
});
