// Small progressive enhancements, hooked via data attributes so templates
// carry no inline event handlers (keeps script-src 'self' in the CSP).
// Every control this touches also works without JS (visible/noscript buttons).
(function () {
  "use strict";

  // <select data-autosubmit> / <input data-autosubmit>: submit on change.
  document.addEventListener("change", function (e) {
    if (e.target.hasAttribute("data-autosubmit") && e.target.form) {
      e.target.form.requestSubmit();
    }
  });

  // <input data-markera>: select the whole value on click (copy-friendly).
  document.addEventListener("click", function (e) {
    if (e.target.hasAttribute("data-markera")) {
      e.target.select();
    }
  });

  // <form data-bekrafta="fråga">: confirm before submitting.
  document.addEventListener("submit", function (e) {
    var fraga = e.target.getAttribute("data-bekrafta");
    if (fraga && !window.confirm(fraga)) {
      e.preventDefault();
    }
  });

  // <details data-ordlista>: Esc or a click outside closes the glossary
  // panel. Without JS the tab itself still toggles it.
  document.addEventListener("keydown", function (e) {
    var ordlista = document.querySelector("details[data-ordlista][open]");
    if (e.key === "Escape" && ordlista) {
      ordlista.open = false;
      ordlista.querySelector("summary").focus();
    }
  });
  document.addEventListener("click", function (e) {
    var ordlista = document.querySelector("details[data-ordlista][open]");
    if (ordlista && !ordlista.contains(e.target)) {
      ordlista.open = false;
    }
  });

  // htmx swallows non-2xx responses silently — without this banner a member
  // whose save failed (expired session, network hiccup) believes it succeeded.
  document.addEventListener("htmx:responseError", visaFelbanner);
  document.addEventListener("htmx:sendError", visaFelbanner);

  function visaFelbanner() {
    var banner = document.getElementById("htmx-felbanner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "htmx-felbanner";
      banner.setAttribute("role", "alert");
      banner.className =
        "fixed inset-x-0 top-0 z-50 border-b border-rose-200 bg-rose-50 " +
        "px-4 py-2 text-center text-sm text-rose-800";
      document.body.appendChild(banner);
    }
    banner.textContent =
      "Något gick fel — ändringen sparades inte. Ladda om sidan och försök igen.";
    clearTimeout(banner._timer);
    banner._timer = setTimeout(function () { banner.remove(); }, 8000);
  }
})();
