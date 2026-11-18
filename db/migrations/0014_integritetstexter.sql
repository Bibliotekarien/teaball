-- Integritetssidans rättsliga grund, lagringsplats och gallring (#105). De
-- stod tidigare fast i integritet.html och stämde för DiVA-konsortiet, men
-- inte självklart för en annan organisation på samma installation: en som
-- inte är eller företräder myndigheter kan ha en annan rättslig grund, och
-- "servrar inom EU" gäller en viss drift. Nu redigerar admin dem under
-- Inställningar, som personuppgiftsansvarig.
--
-- Tomt = inte angivet; integritetssidan visar då den gula markeringen i
-- stället för ett påstående som kanske inte stämmer.
ALTER TABLE instans ADD COLUMN rattslig_grund TEXT NOT NULL DEFAULT '';
ALTER TABLE instans ADD COLUMN lagringsplats TEXT NOT NULL DEFAULT '';
ALTER TABLE instans ADD COLUMN gallring TEXT NOT NULL DEFAULT '';

-- En databas som redan är i bruk har visat den fasta texten för sina
-- användare. Den får texten som värde, så att dess integritetssida ser
-- likadan ut efter uppgraderingen. Samma villkor för "i bruk" som
-- instans.fyll_fran_miljon. En ny, tom databas får inget: dess admin anger
-- vad som gäller för just den organisationen.
UPDATE instans SET
    rattslig_grund = 'Den rättsliga grunden är uppgift av allmänt intresse respektive berättigat intresse (artikel 6.1 e och f i dataskyddsförordningen).',
    lagringsplats = 'Tjänsten och dess säkerhetskopior driftas på servrar inom EU. Ingen överföring av personuppgifter sker till land utanför EU/EES.',
    gallring = 'Rutiner för hur länge historiken sparas är under utformning.'
WHERE id = 1
  AND (EXISTS (SELECT 1 FROM forvaltare) OR EXISTS (SELECT 1 FROM funktion));
