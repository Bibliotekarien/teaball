"""Roadmap grouping (spec 5.4): nodes grouped by fas, ordered by the tree
within each fas. The named phases come first, then free-text phases
(quarters etc.) alphabetically, then nodes without a fas."""

FASTA_FASER = ["nu", "nästa", "senare"]
UTAN_FAS = "utan fas"


def roadmap_data(conn, visa_krav: bool = False, endast_synliga: bool = False):
    typer = ("förmåga", "funktion", "krav") if visa_krav else ("förmåga", "funktion")
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

    grupper: dict[str, list[dict]] = {}
    for r in rows:
        grupper.setdefault(r["fas"] or UTAN_FAS, []).append(dict(r))

    ordning = [f for f in FASTA_FASER if f in grupper]
    ordning += sorted(k for k in grupper if k not in FASTA_FASER and k != UTAN_FAS)
    if UTAN_FAS in grupper:
        ordning.append(UTAN_FAS)
    return [(fas, grupper[fas]) for fas in ordning]
