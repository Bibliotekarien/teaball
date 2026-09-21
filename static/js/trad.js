// Progressive enhancement för trädvyerna (kravträdet och bedömningen):
// dra-och-släpp (T3+, bara kravträdet — Sortable laddas inte annorstädes)
// samt expand/kompakt-minne med vypanelens alla-knappar. No-JS-fallbacken
// (förälder-<select> + upp/ner-knappar, alltid öppna <details>) använder
// samma endpoints; en släppning postar syskongruppens nya ordning till
// /trad/sortera, som omföräldrar inkommande noder och normaliserar om
// ordningen.
(function () {
  "use strict";
  if (!window.Sortable || !window.htmx) return;

  function initSortables(root) {
    // Läsroller får trädet utan data-skrivbar (och utan greppytor) — samma
    // vakt som roadmap.js: initiera inte Sortable alls.
    var rot = document.getElementById("trad-rot");
    if (!rot || !rot.dataset.skrivbar) return;
    root.querySelectorAll("ul.syskon").forEach(function (lista) {
      if (lista._sortable) return;
      lista._sortable = new Sortable(lista, {
        group: "trad",
        handle: ".greppyta",
        animation: 120,
        fallbackOnBody: true,
        onEnd: function (evt) {
          var till = evt.to;
          var ordning = Array.prototype.filter
            .call(till.children, function (li) { return li.dataset.nod; })
            .map(function (li) { return li.dataset.nod; });
          htmx.ajax("POST", "/trad/sortera", {
            source: till,
            target: "#trad-rot",
            swap: "outerHTML",
            values: { foralder_id: till.dataset.foralder, nod_id: ordning },
          });
        },
      });
    });
  }

  htmx.onLoad(initSortables);
})();

// Expand/kompakt-minne + vypanelens alla-knappar. <details open> är ren
// DOM-status och nollställs varje gång htmx byter ut innehåll — hela trädet
// (sortering, redigering, synlighet, filtrering …) eller en enskild gren
// (bedömningens svar-spar). Därför speglas kompakterade nod-id:n i
// sessionStorage — per flik, överlever omladdning — och återappliceras efter
// varje swap. Behållaren pekas ut med data-kompaktminne, vars värde är
// lagringsnyckeln, så kravträdet och bedömningsvyn får varsitt minne av samma
// skript. Utan JS är alla-knapparna dolda och trädet som förut: allt öppet.
(function () {
  "use strict";
  var start = document.querySelector("[data-kompaktminne]");
  if (!start) return;
  var NYCKEL = start.dataset.kompaktminne;

  function lasKompakterade() {
    try { return new Set(JSON.parse(sessionStorage.getItem(NYCKEL)) || []); }
    catch (fel) { return new Set(); }
  }
  function spara(kompakterade) {
    try { sessionStorage.setItem(NYCKEL, JSON.stringify(Array.from(kompakterade))); }
    catch (fel) { /* fullt/avstängt lagringsutrymme — minnet är bara bekvämlighet */ }
  }
  function nodId(details) {
    var li = details.closest("li[data-nod]");
    return li ? li.dataset.nod : null;
  }
  function detaljer() {
    // Behållaren swappas ut — fråga alltid DOM:en, spara aldrig referensen.
    return document.querySelectorAll("[data-kompaktminne] li[data-nod] > details");
  }

  // Med aktivt filter visas allt öppet och minnet lämnas orört — annars kan
  // en sökträff gömmas inne i en kompakterad gren. Den filtrerade vyn är
  // alltså efemär: varken läser eller skriver minnet. Bedömningsvyn saknar
  // filterform (medlemsväljaren är ingen), så där är detta alltid falskt.
  function filterAktivt() {
    var form = document.querySelector("form[data-tradfilter]");
    return !!form && Array.prototype.some.call(form.elements, function (falt) {
      return falt.type === "checkbox" ? falt.checked : !!(falt.value || "").trim();
    });
  }

  // Öppnar grenen ned till noden och stryker kedjan ur minnet, så noden är
  // synlig både nu och efter nästa swap. Returnerar nodens <li> (eller null).
  function oppnaGrenTill(id) {
    var li = document.getElementById("nod-" + id);
    var kompakterade = lasKompakterade();
    for (var el = li; el; el = el.parentElement && el.parentElement.closest("li[data-nod]")) {
      var d = el.querySelector(":scope > details");
      if (d) d.open = true;
      kompakterade.delete(el.dataset.nod);
    }
    spara(kompakterade);
    return li;
  }

  function aterstall() {
    var kompakterade = filterAktivt() ? new Set() : lasKompakterade();
    detaljer().forEach(function (d) { d.open = !kompakterade.has(nodId(d)); });

    // Efter en sparad redigering scrollas den redigerade nodens rad högst upp
    // i viewporten — noden byter aldrig plats i trädet, men swappen gör att
    // blicken annars tappar den när formuläret försvinner. Körs här, efter att
    // minnet applicerats, så kompakterade grenar ovanför inte förskjuter målet.
    // Avvisades sparandet (felbannern renderas) lämnas scrollen ifred så
    // felmeddelandet syns.
    var mal = sparadNod;
    sparadNod = null;
    if (mal && !document.getElementById("trad-fel")) {
      var rad = oppnaGrenTill(mal) && document.getElementById("rad-" + mal);
      if (rad) {
        rad.scrollIntoView({ block: "start" });
        rad.classList.add("nyss-sparad");
        rad.addEventListener("animationend", function () {
          rad.classList.remove("nyss-sparad");
        }, { once: true });
      }
    }
  }

  // Fångar vilken nod som just sparats: POST /trad/nod/<id> är redigerings-
  // formuläret (skapande postar utan id, ordna/synlighet har egna suffix).
  var sparadNod = null;
  document.addEventListener("htmx:afterSwap", function (h) {
    var cfg = h.detail.requestConfig;
    var traff = cfg && cfg.verb === "post" && /^\/trad\/nod\/(\d+)$/.exec(cfg.path);
    if (traff) sparadNod = traff[1];
  });

  // toggle bubblar inte — lyssna i capture-fasen. Programmatiska växlingar
  // (aterstall, alla-knapparna) går samma väg; att spara om samma värde är
  // ofarligt eftersom läget redan skrivits synkront innan händelsen levereras.
  document.addEventListener("toggle", function (h) {
    if (filterAktivt()) return;
    var id = h.target.matches && h.target.matches("li[data-nod] > details")
      ? nodId(h.target) : null;
    if (!id) return;
    var kompakterade = lasKompakterade();
    if (h.target.open) kompakterade.delete(id); else kompakterade.add(id);
    spara(kompakterade);
  }, true);

  // Expandera nollställer hela minnet (även bortfiltrerade noder öppnas nästa
  // gång de syns); kompaktera lägger de synliga till det som redan var stängt.
  document.addEventListener("click", function (h) {
    var knapp = h.target.closest("[data-trad-alla]");
    if (!knapp) return;
    var oppna = knapp.dataset.tradAlla === "expandera";
    var kompakterade = oppna ? new Set() : lasKompakterade();
    detaljer().forEach(function (d) {
      d.open = oppna;
      if (!oppna) kompakterade.add(nodId(d));
    });
    spara(kompakterade);
  });

  // Sidomenyns ankarlänkar (#rad-<id>): målet kan ligga i en kompakterad
  // gren, och ett ankarhopp till en dold rad blir ingenting. Öppna grenen
  // (och stryk den ur minnet) innan webbläsaren gör själva hoppet — hoppet
  // och :target-blinket i CSS:en lämnas åt webbläsaren.
  document.addEventListener("click", function (h) {
    var lank = h.target.closest("[data-tradmeny] a[href^='#rad-']");
    if (lank) oppnaGrenTill(lank.getAttribute("href").slice("#rad-".length));
  });

  // Efter ett lyckat skapande (OOB-formuläret kommer tillbaka med föräldern
  // vald) öppnas förälderns gren — annars hamnar den nya noden osynlig inne i
  // en kompakterad gren. Både DOM och minne uppdateras så resultatet blir
  // detsamma oavsett om aterstall hinner köra före eller efter OOB-händelsen.
  document.addEventListener("htmx:oobAfterSwap", function (h) {
    if (!h.detail.target || h.detail.target.id !== "ny-nod-plats") return;
    var vald = h.detail.target.querySelector('select[name="foralder_id"]');
    if (vald && vald.value) oppnaGrenTill(vald.value);
  });

  document.querySelectorAll("[data-trad-alla]").forEach(function (knapp) {
    knapp.classList.remove("hidden");
  });

  if (window.htmx) {
    htmx.onLoad(aterstall);
  } else {
    document.addEventListener("DOMContentLoaded", aterstall);
  }
})();
