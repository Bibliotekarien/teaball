-- Status vocabulary change plus requirement links, in one rebuild (a CHECK
-- constraint can only be changed by recreating the table):
--
--   * 'befintlig' becomes 'driftsatt'. During the rewrite "befintlig" was
--     ambiguous (exists in Classic? in the new platform?); the go-live
--     analysis needs "deployed on the new platform", so say exactly that.
--   * New status 'utreds': exists in DiVA Classic, identified but not yet
--     decided. Treated like 'idé' by the N2 warning in the analysis.
--   * New columns lank_dokumentation and lank_jira on funktion.
--
-- bedomning is rebuilt alongside: dropping the old funktion while bedomning
-- still references it would cascade-delete every assessment.

-- Defer FK checks to COMMIT so funktion's self-references can be copied in
-- arbitrary row order. (RESTRICT actions stay immediate regardless — hence
-- the foralder_id clearing right before the old table is dropped.)
PRAGMA defer_foreign_keys = ON;

-- Views and triggers are recreated from db/views_triggers.sql on every
-- startup; drop them here so the renames below don't rewrite their bodies
-- to point at the doomed *_gammal tables.
DROP TRIGGER IF EXISTS funktion_cykel_insert;
DROP TRIGGER IF EXISTS funktion_cykel_update;
DROP TRIGGER IF EXISTS bedomning_hist_update;
DROP TRIGGER IF EXISTS bedomning_hist_delete;
DROP VIEW IF EXISTS funktion_trad;
DROP VIEW IF EXISTS bedomning_direkt;
DROP VIEW IF EXISTS bedomning_effektiv;

ALTER TABLE bedomning RENAME TO bedomning_gammal;
-- This rename also rewrites bedomning_gammal's FK to follow along:
ALTER TABLE funktion RENAME TO funktion_gammal;

CREATE TABLE funktion (
    id             INTEGER PRIMARY KEY,
    namn           TEXT NOT NULL,
    beskrivning    TEXT,
    foralder_id    INTEGER REFERENCES funktion(id) ON DELETE RESTRICT,
    typ            TEXT NOT NULL CHECK (typ IN ('förmåga','funktion','krav')),
    status         TEXT NOT NULL CHECK (status IN ('driftsatt','planerad','idé','utreds','utgår')),
    fas            TEXT,                            -- roadmap: 'nu' | 'nästa' | 'senare' | free text (quarter)
    synlig_externt INTEGER NOT NULL DEFAULT 1,      -- 0 = never shown to members
    sortering      INTEGER NOT NULL DEFAULT 0,      -- order within sibling group
    lank_dokumentation TEXT,                        -- URL to requirement documentation
    lank_jira      TEXT                             -- URL to the Jira issue
);

INSERT INTO funktion (id, namn, beskrivning, foralder_id, typ, status, fas,
                      synlig_externt, sortering)
SELECT id, namn, beskrivning, foralder_id, typ,
       CASE status WHEN 'befintlig' THEN 'driftsatt' ELSE status END,
       fas, synlig_externt, sortering
FROM funktion_gammal;

CREATE TABLE bedomning (
    medlem_id   INTEGER NOT NULL REFERENCES medlem(id) ON DELETE CASCADE,
    funktion_id INTEGER NOT NULL REFERENCES funktion(id) ON DELETE CASCADE,
    svar        TEXT NOT NULL CHECK (svar IN ('golive_krav','kan_vanta','behovs_ej')),
    workaround  TEXT,                               -- only meaningful for 'kan_vanta'
    workaround_delas INTEGER NOT NULL DEFAULT 0,    -- 1 = other members may see the workaround
    kommentar   TEXT,                               -- always private: member themselves + admins only
    besvarat_av TEXT,                               -- free text: name/role, or 'proxy: <admin>'
    besvarat    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (medlem_id, funktion_id)
);

INSERT INTO bedomning (medlem_id, funktion_id, svar, workaround, workaround_delas,
                       kommentar, besvarat_av, besvarat)
SELECT medlem_id, funktion_id, svar, workaround, workaround_delas,
       kommentar, besvarat_av, besvarat
FROM bedomning_gammal;

DROP TABLE bedomning_gammal;
-- Disarm the self-FK before DROP: the implicit DELETE FROM in DROP TABLE
-- honours ON DELETE RESTRICT, which is checked immediately even under
-- deferred FKs and would abort on any parent-before-child deletion order.
UPDATE funktion_gammal SET foralder_id = NULL;
DROP TABLE funktion_gammal;

-- The old tables carried the original index names with them; recreate on the
-- new tables now that the drops have freed the names.
CREATE INDEX idx_funktion_foralder ON funktion(foralder_id);
CREATE INDEX idx_funktion_fas ON funktion(fas);
CREATE INDEX idx_bedomning_funktion ON bedomning(funktion_id);
