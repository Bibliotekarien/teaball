-- Förvaltningens hantering av medlemmarnas kommentarer (öppen och intern
-- kommentar på bedomning). Förvaltarna går igenom kommentarerna i en egen
-- kommentarsvy, bockar av dem som lästa och arkiverar dem när
-- formuleringarna justerats.
--
-- Hanteringen gäller bara förvaltningens vyer: medlemmens kommentar rörs
-- aldrig, och en arkiverad kommentar syns som förut för medlemmen (och för
-- andra medlemmar, om den är delad).
--
-- En egen tabell i stället för kolumner på bedomning: historiktriggrarna
-- (D2) kopierar raden vid varje UPDATE av bedomning, så kolumner där skulle
-- skriva en historikrad varje gång någon bockar av en kommentar.
--
-- Ingen rad = oläst. status: läst = genomgången men kvar under noden i
-- trädet, arkiverad = hanterad och undanlagd (syns bara i kommentarsvyns
-- filter). falt säger vilken av svarets två kommentarer det gäller. Ändrar
-- medlemmen texten tas raden bort av en trigger i views_triggers.sql, så den
-- ändrade kommentaren blir oläst igen. Ingen förvaltare lagras: vem som
-- hanterat spelar ingen roll (samma hållning som de interna kommentarerna,
-- 0006).
--
-- ON DELETE CASCADE mot bedomning: tar medlemmen bort sitt svar försvinner
-- kommentarerna och därmed hanteringen. OBS för framtida ombyggnads-
-- migrationer av bedomning: bygg om den här tabellen i samma migration,
-- annars kaskadraderas den.
CREATE TABLE medlemskommentar_hantering (
    medlem_id   INTEGER NOT NULL,
    funktion_id INTEGER NOT NULL,
    falt        TEXT NOT NULL CHECK (falt IN ('oppen', 'intern')),
    status      TEXT NOT NULL CHECK (status IN ('läst', 'arkiverad')),
    hanterad    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (medlem_id, funktion_id, falt),
    FOREIGN KEY (medlem_id, funktion_id)
        REFERENCES bedomning (medlem_id, funktion_id) ON DELETE CASCADE
);
