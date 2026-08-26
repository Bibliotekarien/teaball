-- Schema per requirements.md §3 (SQLite dialect).
-- Enums are CHECK constraints, booleans INTEGER 0/1,
-- timestamps ISO 8601 text in UTC (datetime('now')).

CREATE TABLE funktion (
    id             INTEGER PRIMARY KEY,
    namn           TEXT NOT NULL,
    beskrivning    TEXT,
    foralder_id    INTEGER REFERENCES funktion(id) ON DELETE RESTRICT,
    typ            TEXT NOT NULL CHECK (typ IN ('förmåga','funktion','krav')),
    status         TEXT NOT NULL CHECK (status IN ('befintlig','planerad','idé','utgår')),
    fas            TEXT,                            -- roadmap: 'nu' | 'nästa' | 'senare' | free text (quarter)
    synlig_externt INTEGER NOT NULL DEFAULT 1,      -- 0 = never shown to members
    sortering      INTEGER NOT NULL DEFAULT 0       -- order within sibling group
);

CREATE INDEX idx_funktion_foralder ON funktion(foralder_id);
CREATE INDEX idx_funktion_fas ON funktion(fas);

CREATE TABLE medlem (
    id       INTEGER PRIMARY KEY,
    namn     TEXT NOT NULL,
    kategori TEXT,                                  -- universitet, högskola, myndighet, museum ...
    token    TEXT UNIQUE                            -- phase 2: random, revocable access key (stored hashed)
);

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

CREATE INDEX idx_bedomning_funktion ON bedomning(funktion_id);

CREATE TABLE bedomning_historik (
    id          INTEGER PRIMARY KEY,
    medlem_id   INTEGER NOT NULL,
    funktion_id INTEGER NOT NULL,
    svar        TEXT NOT NULL,
    workaround  TEXT,
    workaround_delas INTEGER,
    kommentar   TEXT,
    besvarat_av TEXT,
    besvarat    TEXT,
    ersatt      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_historik_medlem_funktion ON bedomning_historik(medlem_id, funktion_id);

-- Admin accounts (spec S1 allows config or table; a table gives a real identity
-- for 'proxy: <name>' in bedomning.besvarat_av and for the application log).
CREATE TABLE forvaltare (
    id           INTEGER PRIMARY KEY,
    anvandarnamn TEXT NOT NULL UNIQUE,
    losen_hash   TEXT NOT NULL
);
