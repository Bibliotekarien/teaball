-- Lås från rankning: en nod kan synas för medlemmarna utan att gå att
-- bedöma — t.ex. när beslutet redan är fattat men noden ska stå kvar som
-- kontext. Kommentaren visas vid de utgråade knapparna och säger varför.
-- Oberoende av status (driftsatt/utgår spärras redan via statusen) och
-- ärvs inte: barnen till en låst nod går fortfarande att bedöma.
-- Befintliga svar på en nod som låses ligger kvar (historik, analys) men
-- kan inte ändras förrän låset tas bort.
ALTER TABLE funktion ADD COLUMN rankning_last INTEGER NOT NULL DEFAULT 0
    CHECK (rankning_last IN (0, 1));
ALTER TABLE funktion ADD COLUMN rankning_last_kommentar TEXT;
