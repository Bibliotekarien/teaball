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

  // <input|textarea maxlength data-raknare>: teckenräknare under fältet när
  // det närmar sig gränsen. Utan den slutar webbläsaren bara ta emot tecken
  // (och ett inklistrat värde kapas) utan att säga varför. Opt-in, eftersom
  // räknaren läggs in som syskon direkt efter fältet och då bara passar i
  // formulär där fälten står i en kolumn. Lyssnar på focusin också, så en
  // befintlig lång text visar räknaren redan när man går in i fältet.
  document.addEventListener("input", uppdateraRaknare);
  document.addEventListener("focusin", uppdateraRaknare);

  function uppdateraRaknare(e) {
    var falt = e.target;
    if (!falt.hasAttribute || !falt.hasAttribute("data-raknare")) return;
    var max = falt.maxLength;
    if (!(max > 0)) return;
    var langd = falt.value.length;
    var raknare = falt.nextElementSibling;
    if (!raknare || !raknare.hasAttribute("data-raknare-for")) {
      raknare = document.createElement("span");
      raknare.setAttribute("data-raknare-for", falt.name);
      raknare.className = "text-right text-xs tabular-nums";
      // Siffrorna läses inte upp för varje tangenttryck; skärmläsaren får
      // bara besked när gränsen nås, via den dolda live-regionen.
      raknare.innerHTML =
        '<span aria-hidden="true"></span><span class="sr-only" aria-live="polite"></span>';
      falt.insertAdjacentElement("afterend", raknare);
    }
    var vidGrans = langd >= max;
    raknare.hidden = langd < max * 0.8;
    raknare.classList.toggle("text-stone-400", !vidGrans);
    raknare.classList.toggle("text-rose-700", vidGrans);
    raknare.firstChild.textContent =
      langd + " / " + max + (vidGrans ? " — maxlängd nådd" : "");
    raknare.lastChild.textContent =
      vidGrans ? "Maxlängden " + max + " tecken är nådd." : "";
  }

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
