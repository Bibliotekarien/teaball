// Progressive enhancement for the roadmap edit mode: drag rows between phase
// groups. The no-JS fallback (the per-row fas select) posts to the same
// endpoint, /roadmap/flytta. Active only when the container carries
// data-redigera — the read view stays inert so nothing moves by accident.
(function () {
  "use strict";
  if (!window.Sortable || !window.htmx) return;

  function init(root) {
    var behallare = root.id === "roadmap-grupper"
      ? root
      : root.querySelector && root.querySelector("#roadmap-grupper");
    if (!behallare || !behallare.dataset.redigera) return;
    behallare.querySelectorAll("ol.fas-lista").forEach(function (lista) {
      if (lista._sortable) return;
      lista._sortable = new Sortable(lista, {
        group: "roadmap",
        handle: ".greppyta",
        draggable: "li[data-nod]",
        animation: 120,
        fallbackOnBody: true,
        onAdd: function (evt) {
          htmx.ajax("POST", "/roadmap/flytta", {
            source: evt.to,
            target: "#roadmap-grupper",
            swap: "outerHTML",
            values: {
              nod_id: evt.item.dataset.nod,
              fas: evt.to.dataset.fas,
              redigera: "1",
              visa_krav: behallare.dataset.visaKrav ? "1" : "",
              dolj_formagor: behallare.dataset.doljFormagor ? "1" : "",
            },
          });
        },
      });
    });
  }

  htmx.onLoad(init);
})();
