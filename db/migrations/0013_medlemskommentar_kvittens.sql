-- Läskvittens för medlemmarnas kommentarer (öppen och intern kommentar på
-- bedomning). Förvaltarna går igenom kommentarerna i en egen kommentarsvy
-- och bockar av dem som lästa när formuleringarna justerats.
--
-- En egen tabell i stället för kolumner på bedomning: historiktriggrarna
-- (D2) kopierar raden vid varje UPDATE av bedomning, så en kvittens-
-- kolumn där skulle skriva en historikrad varje gång någon läskvitterar.
--
-- Raden finns = kommentaren är läst. falt säger vilken av radens två
-- kommentarer det gäller. Ändrar medlemmen texten tas kvittensen bort av en
-- trigger i views_triggers.sql, så den ändrade kommentaren blir oläst igen.
-- Ingen förvaltare lagras: vem som läst spelar ingen roll, bara att någon
-- gjort det (samma hållning som de interna kommentarerna, 0006).
--
-- ON DELETE CASCADE mot bedomning: tar medlemmen bort sitt svar försvinner
-- kommentarerna och därmed kvittenserna. OBS för framtida ombyggnads-
-- migrationer av bedomning: bygg om den här tabellen i samma migration,
-- annars kaskadraderas kvittenserna.
CREATE TABLE medlemskommentar_kvittens (
    medlem_id   INTEGER NOT NULL,
    funktion_id INTEGER NOT NULL,
    falt        TEXT NOT NULL CHECK (falt IN ('oppen', 'intern')),
    kvitterad   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (medlem_id, funktion_id, falt),
    FOREIGN KEY (medlem_id, funktion_id)
        REFERENCES bedomning (medlem_id, funktion_id) ON DELETE CASCADE
);
