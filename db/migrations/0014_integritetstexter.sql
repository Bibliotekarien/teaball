-- Integritetssidans rättsliga grund, lagringsplats och gallring (#105). De
-- stod tidigare fast i integritet.html och stämde för DiVA-konsortiet, men
-- inte självklart för en annan organisation på samma installation: en som
-- inte är eller företräder myndigheter kan ha en annan rättslig grund, och
-- "servrar inom EU" gäller en viss drift. Nu redigerar admin dem under
-- Inställningar, som personuppgiftsansvarig.
--
-- Tomt = inte angivet; integritetssidan visar då den gula markeringen i
-- stället för ett påstående som kanske inte stämmer.
--
-- integritetstexter_fyllda = 0 betyder att det ännu inte avgjorts om
-- databasen ska få den tidigare fasta texten. app/instans.py gör det en gång
-- vid start (fyll_integritetstexter): en databas i bruk får texten, utom när
-- installationen har flera organisationer. Det avgörs i Python och inte här,
-- eftersom migrationen inte vet hur många organisationer som finns.
ALTER TABLE instans ADD COLUMN rattslig_grund TEXT NOT NULL DEFAULT '';
ALTER TABLE instans ADD COLUMN lagringsplats TEXT NOT NULL DEFAULT '';
ALTER TABLE instans ADD COLUMN gallring TEXT NOT NULL DEFAULT '';
ALTER TABLE instans ADD COLUMN integritetstexter_fyllda INTEGER NOT NULL DEFAULT 0;
