# Changelog

## Fase 1 – Datalaag (2026-10-11)

### Gebouwd

- Adapterlaag met één gedeelde basis: snelheidslimiet per bron, maandbudget met harde stop, drie pogingen
  bij tijdelijke fouten (met `Retry-After`), en een logboek van elke aanroep (`provider_call_log`) met het
  ruwe antwoord gecomprimeerd ernaast (`provider_response`, opgeruimd na de bewaartermijn per bron).
  API-sleutels komen nooit in het logboek.
- Adapters: Binance (spot), Coinbase, CoinGecko (Demo), DefiLlama, Coin Metrics (Community),
  Frankfurter (ECB-koersen) en FRED. Instellingen in `config/providers.yaml`.
- Migratie `0002`: `asset`, `asset_alias`, `universe_membership`, `price_bar`, `fundamental_fact`,
  `fx_rate`, `macro_observation`, `provider_call_log`, `provider_response`, `job_run`, en de view
  `price_bar_eur` die koersen met ECB-referentiekoersen naar euro omrekent.
- Nachtelijke runs met APScheduler: crypto om 00:05 UTC, wisselkoersen en macro op werkdagen om
  16:30 UTC, opruimen om 03:30 UTC. Een vergrendeling in de database voorkomt dat een taak twee keer
  tegelijk loopt; elke run komt in `job_run` met tellers en meldingen.
- Pagina **Verbruik**: aanroepen, budget, fouten en snelheid per bron; nachtelijke taken met knop
  "Nu draaien"; dekking van de data.
- `scripts/nas-smoketest.sh` controleert nu ook of alle databronnen vanaf de NAS bereikbaar zijn.

### Regels die de data eerlijk houden

- Alleen afgesloten dagen. Een dagkoers is de slotkoers om 00:00 UTC; de lopende dag wordt nooit
  opgeslagen.
- Koersen staan in de oorspronkelijke valuta. Euro komt uit de ECB-koers van die dag (of de laatste
  daarvoor). USDT wordt eerst met de echte USDT/USD-slotkoers van Coinbase omgerekend; ontbreekt die,
  dan blijft de eurowaarde leeg in plaats van 1 USDT = 1 USD aan te nemen.
- Een ticker van een beurs wordt pas aan een munt gekoppeld als de koers binnen 20% van CoinGecko ligt,
  zodat twee munten met dezelfde ticker nooit door elkaar lopen.
- Feiten en macrowaarden zijn alleen-toevoegen. Een herzien cijfer komt als nieuwe rij met het moment
  waarop het bekend werd. Bij het eerste ophalen van historie wordt aangenomen dat een dagwaarde aan het
  eind van die dag publiek was.
- Elke run is veilig te herhalen: een tweede run schrijft niets dubbel (getest en live gecontroleerd).

### Gecontroleerd bij de bronnen (11 oktober 2026)

- **CoinGecko Demo** geeft historie tot 365 dagen terug en per dag alleen een slotkoers, geen
  open/hoog/laag. Ik reken met 25 aanroepen per minuut (de prompt noemde 100) en stop bij 9.000 van de
  10.000 per maand.
- **Coinbase** heeft USDT/USD pas sinds 4 mei 2021. Daarom staat Coinbase (echte USD) eerst in de
  voorkeursvolgorde, dan Binance (USDT), dan CoinGecko (EUR). De app bewaart de koersen van elke
  gekoppelde beurs; de view `price_daily_eur` kiest per dag de bron met de hoogste voorkeur en valt terug
  op de volgende als een dag ontbreekt. Zo telt bijvoorbeeld BNB de Binance-historie sinds 2017 mee,
  terwijl Coinbase BNB pas sinds oktober 2025 noteert. CoinGecko vult alleen aan waar de beurzen samen
  korter dan een jaar teruggaan.
- **Coin Metrics Community** heeft geen gerealiseerde marktwaarde; die volgt in fase 2 uit marktwaarde
  gedeeld door MVRV. On-chain data is er voor 24 van de gevolgde munten.
- **FRED** geeft de high-yield-renteopslag (`BAMLH0A0HYM2`) maar drie jaar terug, door een
  licentiebeperking van ICE. De app archiveert die reeks vanaf nu dagelijks; voor het marktregime in
  fase 5 betekent dit een kortere historie.
- **Bybit en Binance-futures** weigeren verbindingen vanuit de VS (waar de ontwikkelomgeving draait).
  Vanaf een Nederlands IP waarschijnlijk wel bereikbaar; `nas-smoketest.sh` laat het zien. Nodig in fase 2.
- **DefiLlama** koppelt een munt soms aan een treasury of beurs met dezelfde CoinGecko-id; die worden
  overgeslagen en de chain krijgt voorrang.

### Acceptatie (live gemeten op 11 oktober 2026)

- **Top 50 crypto met minstens een jaar dagkoersen in euro: 46 van 50.** Alle 50 hebben koersen tot en
  met gisteren. De vier zonder vol jaar liggen aan de bron, niet aan de app:
  Bitway (sinds maart 2026) en Canton (sinds november 2025) bestaan korter dan een jaar;
  Circle USYC en Figure Heloc (getokeniseerde fondsen) hebben gaten in CoinGecko's eigen dagdata.
  Ontbrekende dagen worden niet ingevuld.
- **Tweede run schrijft niets dubbel:** de tweede cryptorun voegde 0 koersen, 0 lijstregels, 0 feiten
  en 0 wisselkoersen toe; de tweede run wisselkoersen en macro 0 rijen.
- **Verbruik per bron** staat op de pagina Verbruik.
- Eerste volledige run vanaf een lege database: wisselkoersen en macro 18 s, crypto 8 min 50 s
  (139.532 dagkoersen, 639.940 feiten). Een gewone nachtrun crypto duurt daarna ongeveer 2 minuten en
  gebruikt circa 35 CoinGecko-aanroepen.
- Tests: 60 voor de rekenserver (waarvan 23 nieuw voor adapters en ingest), 7 voor de webinterface.

### Bekende beperkingen

- Munten die vóór 4 mei 2021 alleen in USDT op Binance noteerden (bijvoorbeeld BNB, SOL, DOGE) hebben
  pas eurokoersen vanaf die datum, omdat er daarvoor geen USDT/USD-slotkoers is. De ruwe USDT-koersen
  staan wel in de database. Er blijft ruim vijf jaar over, genoeg voor het 200-weeks gemiddelde.
- DefiLlama-zoekpogingen naar munten zonder data tellen in het logboek als fout (HTTP 400). Ze gebeuren
  alleen bij de maandelijkse koppeling en worden in de run niet als fout gemeld.

### Afwijkingen van de prompt

- Geen CCXT: Binance en Coinbase worden rechtstreeks aangesproken, zodat elk ruw antwoord en elke
  aanroep exact vastligt en de USDT-omrekening controleerbaar is.
- Exchange-tokens zoals LEO, OKB en BGB staan niet op Binance of Coinbase; hun koers komt van CoinGecko
  (één jaar historie, alleen slotkoersen).

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
