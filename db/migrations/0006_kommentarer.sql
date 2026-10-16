-- Interna kommentarer på noderna: förvaltarnas egna anteckningar ("det här
-- behöver ses över"), aldrig synliga för medlemmar eller extern roll.
-- Medvetet ingen författarkolumn — tjänsten ska vara fri från person-
-- uppgifter, och en kommentar ska läsas som gruppens, inte någons.
-- status: öppen = att åtgärda (kommentarsvyns arbetslista), behandlad =
-- åtgärdad men kvar som historik under noden, dold = åtgärdad och undanlagd
-- (syns bara i kommentarsvyns filter). hanterad stämplas vid varje
-- statusbyte och nollas när kommentaren öppnas igen.
-- ON DELETE CASCADE: kommentarerna följer noden när den tas bort. OBS för
-- framtida ombyggnadsmigrationer av funktion: precis som bedomning måste
-- kommentar byggas om i samma migration, annars kaskadraderas den.
CREATE TABLE kommentar (
    id          INTEGER PRIMARY KEY,
    funktion_id INTEGER NOT NULL REFERENCES funktion(id) ON DELETE CASCADE,
    text        TEXT NOT NULL CHECK (length(trim(text)) > 0),
    status      TEXT NOT NULL DEFAULT 'öppen'
                CHECK (status IN ('öppen', 'behandlad', 'dold')),
    skapad      TEXT NOT NULL DEFAULT (datetime('now')),
    hanterad    TEXT
);
CREATE INDEX kommentar_funktion ON kommentar (funktion_id, status);
