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

  // Sortable för ett globalt register över alla listor det initierats på,
  // och stryker en lista först vid destroy(). Utan destroy pekade registret
  // via föräldrakedjan på hela det utbytta trädet efter varje swap av
  // #trad-rot (spara, flytta, dölj, filtrera …) — en komplett trädkopia per
  // åtgärd blev kvar i minnet, gigabyte efter en längre session, och
  // skräpsamlingen gjorde allt trögt. htmx skickar beforeCleanupElement för
  // varje element en swap tar bort (rekursivt): destroya där.
  document.addEventListener("htmx:beforeCleanupElement", function (h) {
    var lista = h.target;
    if (!lista || !lista._sortable) return;
    lista._sortable.destroy();
    lista._sortable = null;
  });

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
    // Sätt open bara när det ändras: en tilldelning av samma värde räknas
    // ändå som attributändring, och med details[open] i stilmallen tvingar
    // den en stilomräkning av hela grenen — för varje gren, varje gång.
    detaljer().forEach(function (d) {
      var oppen = !kompakterade.has(nodId(d));
      if (d.open !== oppen) d.open = oppen;
    });

    // Efter vissa åtgärder scrollas en rad högst upp i viewporten (scrollMal,
    // se nedan) — swappen byter ut hela trädet och blicken tappar annars sin
    // plats. Körs här, efter att minnet applicerats, så kompakterade grenar
    // ovanför inte förskjuter målet. Avvisades åtgärden (felbannern renderas)
    // lämnas scrollen ifred så felmeddelandet syns.
    var mal = scrollMal;
    scrollMal = null;
    if (mal && !document.getElementById("trad-fel")) {
      var rad = oppnaGrenTill(mal.id) && document.getElementById("rad-" + mal.id);
      if (rad) {
        rad.scrollIntoView({ block: "start" });
        if (mal.blink) {
          rad.classList.add("nyss-sparad");
          rad.addEventListener("animationend", function () {
            rad.classList.remove("nyss-sparad");
          }, { once: true });
        }
      }
    }
  }

  // Vilken rad nästa aterstall ska scrolla till: { id, blink }. Sätts av
  // lyssnarna nedan och nollställs inför varje nytt anrop, så ett misslyckat
  // eller orelaterat anrop aldrig ärver ett gammalt mål.
  var scrollMal = null;

  // Raden närmast ovanför en nod, i den ordning trädet visas: syskonets
  // sista öppna ättling, eller föräldern om noden är första barn. Rader i
  // kompakterade grenar räknas inte — de är inte vad ögat ser. null om noden
  // är trädets första rad.
  function radOvanfor(id) {
    var rader = document.querySelectorAll("[data-kompaktminne] [id^='rad-']");
    var ovanfor = null;
    for (var i = 0; i < rader.length; i++) {
      var rad = rader[i];
      var traff = /^rad-(\d+)$/.exec(rad.id);
      if (!traff) continue;
      if (traff[1] === id) return ovanfor;
      var synlig = rad.checkVisibility ? rad.checkVisibility() : rad.offsetParent !== null;
      if (synlig) ovanfor = traff[1];
    }
    return null;
  }

  // Ta bort och dölj/visa: noden försvinner (eller byter skepnad) och raden
  // ovanför den hamnar högst upp, så ögat landar där noden nyss var. Raden
  // måste hittas innan svaret swappar in — därav beforeRequest.
  document.addEventListener("htmx:beforeRequest", function (h) {
    scrollMal = null;
    var cfg = h.detail.requestConfig;
    var traff = cfg && cfg.verb === "post"
      && /^\/trad\/nod\/(\d+)\/(ta-bort|synlighet)$/.exec(cfg.path);
    if (!traff) return;
    var ovanfor = radOvanfor(traff[1]);
    if (ovanfor) scrollMal = { id: ovanfor, blink: false };
  });

  // Sparad redigering: den redigerade raden själv högst upp, med blink —
  // noden byter aldrig plats men formuläret försvinner. POST /trad/nod/<id>
  // är redigeringsformuläret (skapande postar utan id, ordna/synlighet/
  // ta-bort har egna suffix).
  document.addEventListener("htmx:afterSwap", function (h) {
    var cfg = h.detail.requestConfig;
    var traff = cfg && cfg.verb === "post" && /^\/trad\/nod\/(\d+)$/.exec(cfg.path);
    if (traff) scrollMal = { id: traff[1], blink: true };
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
    // htmx:load kommer för varje inswappat element — även dubblettkollens
    // lilla span vid varje tangentpaus i skapa-formuläret. Bara innehåll som
    // bär grenar (hela trädet, en enskild gren i bedömningen) behöver
    // återställas; ett väntande scrollmål körs alltid, det hör till en
    // trädswap. Övrigt (formulär, varningar, OOB-fragment) hoppas över så
    // skrivandet inte betalar en trädgenomgång per anrop.
    htmx.onLoad(function (el) {
      var barGrenar = el && el.querySelector
        && (el.matches("details") || !!el.querySelector("details"));
      if (barGrenar || scrollMal) aterstall();
    });
  } else {
    document.addEventListener("DOMContentLoaded", aterstall);
  }
})();
