# Changelog

## Fase 0 – Fundament (2026-10-11)

### Gebouwd

- Repository met drie containers in Docker Compose: `web` (Next.js 16, standalone), `server`
  (FastAPI, pandas, NumPy, TA-Lib 0.8.1, APScheduler) en `db` (PostgreSQL 16, afgestemd op de DS920+).
- Databasemigraties met Alembic. Eerste tabel: `model_version`, alleen-toevoegen (een trigger weigert
  `UPDATE` en `DELETE`). De overige kerntabellen volgen in de fase die ze gebruikt.
- Gezondheidscontrole `GET /api/health`: database, planner, modelversie, CPU-kenmerken en een
  rekentest met NumPy en TA-Lib.
- Lader voor de modelconfiguratie in YAML met strikte validatie (onbekende sleutels, gewichten die niet
  op 100 uitkomen, onbekende maatstaven en gates zonder effect worden geweigerd) en een vingerafdruk per
  modelversie in `config/model/versions.lock.yaml`. De server start niet als het model gewijzigd is
  zonder nieuwe versie.
- Alle 16 sjablonen uit hoofdstuk 6 met startgewichten en gates, de technische score uit hoofdstuk 7 en
  een catalogus van 139 maatstaven.
- Woordenlijst `config/glossary.nl.yaml` met elke maatstaf en de kernbegrippen; tooltips in de interface
  komen alleen hieruit.
- Webinterface met alle negen tabs, de lege ranglijst met de kolommen uit hoofdstuk 2, tooltips,
  statusindicator en de verplichte disclaimer onder elke pagina.
- Scripts: `build-images.sh` (linux/amd64 op de Mac), `nas-smoketest.sh`, `backup.sh`, `test.sh`.
- Tests: 35 voor de rekenserver, 5 voor de webinterface.

### Gecontroleerd

- TA-Lib 0.8.1 heeft kant-en-klare wheels voor Python 3.12 op linux/amd64.
- Lightweight Charts is op npm bij versie 5.2.1 (5.x zoals gepland); wordt toegevoegd in fase 3.
- Het serverimage draait onder een geëmuleerde Intel Atom (Denverton, zonder AVX/AVX2): NumPy
  detecteert geen AVX en NumPy, pandas, lineaire algebra en TA-Lib geven correcte uitkomsten.

### Aannames en open punten

- De echte test op de Synology (`scripts/nas-smoketest.sh`) moet de eigenaar zelf draaien; de
  ontwikkelomgeving heeft geen toegang tot de NAS.
- Nog geen inlog: gepland in fase 10. Tot die tijd alleen op het thuisnetwerk draaien.
- Waar de bouwprompt geen gewichten geeft (productoordeel ETC, RWA, Index) staan gelijke gewichten of de
  voorgestelde gewichten, gemarkeerd als eigen voorstel.
