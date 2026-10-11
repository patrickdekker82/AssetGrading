# Changelog

## Fase 2 – Grading-engine en crypto (2026-10-11)

### Gebouwd

- **Grading-engine** (`server/app/grading/engine.py`): een zuivere functie van modelconfiguratie en invoer.
  Percentielen binnen de vergelijkingsgroep (met afkappen op 5 en 95%), pijlers met maatstafgewichten en
  terugvalmaatstaven, 80/20-menging van groep en eigen historie bij waardering, herverdeling van
  ontbrekende pijlers, datadekking, gates (vier soorten), hysterese (2 punten of 5 dagen), bandbreedte
  (elk gewicht ±20%), letterschaal in derden, Kwaliteit en Timing apart.
- **Technische score** volgens hoofdstuk 7 met TA-Lib: trendstand (vier toetsen), momentum en afstand tot de
  top als percentiel binnen de klasse, relatieve sterkte tegen Bitcoin, volatiliteit tegen de eigen
  driejaarshistorie. Plus een technische grade ten opzichte van Bitcoin voor altcoins.
- **Zeven cryptosjablonen** actief, met toewijzing op CoinGecko-categorie (`config/model/assignment.yaml`,
  handmatig te overschrijven): Bitcoin, Platform, DeFi, Utility, Stablecoin (pegveiligheid 1–5),
  Memecoin (veiligheidscontrole, hoogstens C, label speculatie) en RWA.
- **Nieuwe data:** funding en open interest met dagelijkse archivering (Binance-futures → Bybit → OKX),
  orderboekdiepte binnen 2% en spread (Coinbase), EUR-volume en notering bij Bitvavo, MiCA-beurscheck
  (Coinbase, Bitvavo), DexScreener-liquiditeit en RugCheck-veiligheidsrapport voor Solana-memecoins,
  totaal stablecoin-aanbod (DefiLlama), ontwikkelaarsactiviteit en volglijsten (CoinGecko), audits en
  uitkering aan houders (DefiLlama).
- **`grade_snapshot`** (migratie `0004`, alleen-toevoegen): per munt, dag en modelversie de grade, alle
  invoer met bron en datum, de groepswaarden achter elk percentiel en de uitkomst per pijler en gate.
  Maandsnapshots zijn de snapshots van de laatste dag van de maand.
- **Herberekenen:** `python -m app.cli verify` rekent elke snapshot opnieuw uit met de modelconfiguratie
  die bij die modelversie is opgeslagen. `set-fact` voor gegevens zonder gratis bron.
- Grading draait automatisch na de nachtelijke cryptorun. De cryptotab toont nu de ranglijst met grade,
  score, Kwaliteit, Timing, datadekking, koers en sterkste en zwakste pijler; stablecoins apart met
  pegveiligheid. Peildatum, modelversie en horizon staan erboven.
- Modelversie **0.2.0** (toewijzingsregels, technische parameters, regels voor vergelijkingsgroepen).

### Acceptatie (live gemeten op 11 oktober 2026, peildatum 10 oktober)

- **Elke crypto in de top 50 heeft een grade of een uitgelegde reden:** 31 met grade (9 volledig,
  18 voorlopig, 4 memecoins met speculatie-oordeel), 19 zonder grade, elk met de reden (datadekking onder
  40%, met de ontbrekende pijlers). De 10 grootste stablecoins hebben een pegveiligheid.
- **Elke grade is exact opnieuw te berekenen uit zijn snapshot:** 60 van 60 snapshots herberekend, 60 exact
  gelijk, inclusief de percentielen uit de opgeslagen groepswaarden.
- **Elke gate heeft een eigen test:** alle 26 gates van de 16 sjablonen worden elk apart getest (geraakt en
  niet geraakt). De productgates van grondstoffen volgen in fase 6 met het productoordeel.
- Een tweede run voegt niets toe (0 feiten, 0 snapshots). Nachtrun crypto inclusief grading: circa
  2,5 minuten; eerste run vanaf een lege database circa 10 minuten.
- Tests: 172 voor de rekenserver, 7 voor de webinterface.

### Keuzes en afwijkingen

- **Datadekking per maatstaf**, niet alleen per pijler: een pijler met 2 van de 8 maatstaven telt voor
  een kwart. Strenger dan de prompt, maar eerlijker; daardoor zijn veel grades nu voorlopig.
- **Ontbrekende gratis bronnen** (en daardoor de meeste grades voorlopig): unlock-schema's, houders zonder
  beurzen, reële stakingopbrengst, incidenten en hacks, beheerderssleutels, L2BEAT-fase, ETF-stromen en
  winst na beloningen. Ze zijn handmatig in te vullen met `set-fact`. RWA-tokens krijgen pas een grade
  als uitgever, juridische aanspraak en bewaring zijn ingevuld.
- **Omzet van echte afnemers** (Utility) wordt benaderd met de protocolomzet van DefiLlama; dat staat bij
  de bron vermeld.
- **Marktregime** volgt in fase 5; tot dan schuift het regime geen grades.
- **Memecoins:** de gate "liquiditeit niet vergrendeld" gebruikt het aandeel verbrande of vergrendelde
  liquiditeit volgens RugCheck, met een instelbare drempel van 50% in het sjabloon.
- **MiCA-check** op basis van notering bij Coinbase en Bitvavo (beide met MiCA-vergunning volgens mijn
  kennis van 2025; controleer bij twijfel het ESMA- of AFM-register).
- **Derivaten:** vanuit de ontwikkelomgeving weigeren Binance-futures en Bybit; OKX levert nu funding en
  open interest (33 munten, circa drie maanden funding-historie). Op de NAS probeert de app eerst Binance
  en Bybit.
- Momentaannames (marktwaarde, orderboek, open interest) worden opgeslagen als waarde van de laatst
  afgesloten dag; de eerste waarde van een dag telt.

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
