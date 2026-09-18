// Spara-scroll för listvyn (jfr trad.js i kravträdet): efter en sparad
// inline-redigering (POST /lista/nod/<id>) swappas hela listan om, och raden
// kan byta plats — sortering på uppdaterad lyfter den överst. Den redigerade
// raden scrollas därför i sikte och blinkar till, så blicken inte tappar den
// när formuläret försvinner. Avvisades sparandet (felbannern #lista-fel
// renderas) lämnas scrollen ifred så felmeddelandet syns. Skapande postar
// utan id och träffas inte. Utan JS händer inget — listan är ändå omladdad.
(function () {
  "use strict";
  if (!window.htmx) return;
  document.addEventListener("htmx:afterSwap", function (h) {
    var cfg = h.detail.requestConfig;
    var traff = cfg && cfg.verb === "post" && /^\/lista\/nod\/(\d+)$/.exec(cfg.path);
    if (!traff || document.getElementById("lista-fel")) return;
    var rad = document.getElementById("rad-" + traff[1]);
    if (!rad) return;
    rad.scrollIntoView({ block: "start" });
    rad.classList.add("nyss-sparad");
    rad.addEventListener("animationend", function () {
      rad.classList.remove("nyss-sparad");
    }, { once: true });
  });
})();
