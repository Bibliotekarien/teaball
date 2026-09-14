"""Roadmap grouping (spec 5.4, terminology since renamed fas → "avgång" in the
UI): funktioner (and optionally krav) grouped by fas, ordered by the tree
within each fas. "Medlem 1" comes first, then the other avgångar
alphabetically, then "senare", and last the nodes without an avgång.

Förmågor are hierarchy, not deliverables: they are never grouped under their
own fas but rendered as ancestor context inside every avgång where they have
funktion/krav rows — so each row can be read against its place in the
förmåge-hierarkin. A förmåga without such descendants appears nowhere."""

FASTA_FASER = ["Medlem 1"]
SISTA_FASER = ["senare"]
UTAN_FAS = "utan avgång"


def roadmap_data(conn, visa_krav: bool = False, endast_synliga: bool = False,
                 dolj_formagor: bool = False):
    typer = ("funktion", "krav") if visa_krav else ("funktion",)
    platshallare = ",".join("?" * len(typer))
    synlighet = "AND synlig_stig = 1" if endast_synliga else ""
    rows = conn.execute(
        f"""
        SELECT * FROM funktion_trad
        WHERE typ IN ({platshallare}) {synlighet}
        ORDER BY vag
        """,
        typer,
    ).fetchall()

    # Per group a dict keyed by node id: rows first, then förmåga ancestors —
    # setdefault dedupes ancestors shared between rows.
    grupper: dict[str, dict[int, dict]] = {}
    for r in rows:
        grupper.setdefault(r["fas"] or UTAN_FAS, {})[r["id"]] = dict(r)

    if not dolj_formagor:
        # Ancestors of a visible row are themselves visible (synlig_stig is
        # transitive), so the unfiltered lookup never leaks hidden context.
        alla = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM funktion_trad")}
        for noder in grupper.values():
            for rad in list(noder.values()):
                foralder_id = rad["foralder_id"]
                while foralder_id is not None:
                    anfader = alla[foralder_id]
                    if anfader["typ"] == "förmåga":
                        noder.setdefault(foralder_id, anfader)
                    foralder_id = anfader["foralder_id"]

    ordning = [f for f in FASTA_FASER if f in grupper]
    ordning += sorted(k for k in grupper
                      if k not in FASTA_FASER and k not in SISTA_FASER and k != UTAN_FAS)
    ordning += [f for f in SISTA_FASER if f in grupper]
    if UTAN_FAS in grupper:
        ordning.append(UTAN_FAS)
    # Sorting by vag re-interleaves the ancestors: a förmåga sorts right
    # before its descendants, at its real depth.
    return [(fas, sorted(grupper[fas].values(), key=lambda rad: rad["vag"]))
            for fas in ordning]
