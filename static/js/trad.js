// Progressive enhancement: drag-and-drop for the requirements tree (T3+).
// The no-JS fallback (parent <select> + up/down buttons) uses the same
// endpoints; a drop posts the receiving sibling group's new order to
// /trad/sortera, which reparents incoming nodes and renormalizes the order.
(function () {
  "use strict";
  if (!window.Sortable || !window.htmx) return;

  function initSortables(root) {
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
