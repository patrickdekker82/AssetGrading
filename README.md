# Graadmeter

Privé-webapp die beleggingsassets per assetklasse rangschikt met een onderbouwde grade
(score 0–100 en een letter van A+ tot F, gesplitst in **Kwaliteit** en **Timing**).

> Deze app is een privéhulpmiddel voor onderzoek. Grades zijn een rangorde op basis van een model,
> geen beleggingsadvies en geen voorspelling. Resultaten uit het verleden bieden geen garantie voor de toekomst.

De app bestaat uit drie Docker-containers:

| Container | Wat | Techniek |
| --- | --- | --- |
| `web` | De webinterface die je in de browser opent | Next.js (React, TypeScript) |
| `server` | Rekenserver: data, berekeningen, planner en API | Python, FastAPI, pandas, TA-Lib, APScheduler |
| `db` | Database | PostgreSQL 16 |

De interface praat alleen met de eigen rekenserver, nooit rechtstreeks met een dataleverancier.

**Installeren stap voor stap: zie [docs/installatie.md](docs/installatie.md). Voor gebruik en beheer: zie de [handleiding](docs/handleiding.md).** Deze README is de technische kant.

## Starten op de Mac

Nodig: [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cp .env.example .env          # vul daarna minstens POSTGRES_PASSWORD en APP_PASSWORD in
docker compose up --build
```

Open daarna <http://localhost:3000> en log in met `APP_PASSWORD`. Rechtsboven staat of het systeem in orde is.
Stoppen: `Ctrl+C`, of `docker compose down` (de data blijft bewaard).

## Op de Synology (DS920+)

Bouw de images **op de Mac**, nooit op de NAS (de NAS is daar te traag voor en heeft een andere processor):

```bash
scripts/build-images.sh       # maakt dist/graadmeter-images.tar.gz (linux/amd64)
```

Op de NAS (via SSH, in een map zoals `/volume1/docker/graadmeter`):

1. Kopieer `dist/graadmeter-images.tar.gz`, `docker-compose.nas.yml` (op de NAS **als `docker-compose.yml`**),
   de map `config/`, de map `scripts/` en je `.env` naar die map.
2. Laad de images: `docker load -i graadmeter-images.tar.gz`
3. Controleer of de images op deze NAS werken: `scripts/nas-smoketest.sh` (alle regels moeten `OK` zijn).
4. Start: `docker compose up -d` (het NAS-bestand is compleet en werkt ook met de oudere Docker Compose van
   Container Manager)
5. Meet geheugen en rekentijd met een volledige nachtrun: `scripts/nas-check.sh` (moet binnen een uur klaar
   zijn; toont het hoogste geheugengebruik per container).

De databasebestanden staan dan in `data/postgres` naast de compose-bestanden.

Aandachtspunten voor deze NAS:

- De Celeron J4125 heeft geen AVX/AVX2. De gebruikte rekenbibliotheken (NumPy, pandas, TA-Lib) kiezen
  hun instructies tijdens het draaien; dat is getest onder een geëmuleerde Atom-processor zonder AVX.
  TensorFlow en MongoDB worden niet gebruikt. Komt Polars erbij, gebruik dan `polars[rtcompat]`.
- PostgreSQL is beperkt tot 512 MB `shared_buffers` en hooguit drie werkprocessen.
- De rekenserver draait met één proces, zodat geplande taken nooit dubbel lopen.

## Configureren

Alles wat het model bepaalt staat in versiebeheerde YAML-bestanden, niet in code:

| Bestand | Inhoud |
| --- | --- |
| `config/model/model.yaml` | Modelversie, letterschaal, datadekking, hysterese, marktregime |
| `config/model/templates/*.yaml` | De 16 sjablonen: pijlers, gewichten, maatstaven en gates |
| `config/model/metrics.yaml` | Alle maatstaven, met of hoger of lager beter is |
| `config/model/technical.yaml` | De technische score en de standaardindicatoren per klasse |
| `config/universes.yaml` | Tabs en lijstgrootte (top 25, 50 of 100) |
| `config/stocks.yaml` | Aandelen: hoe de VS-lijst wordt bepaald, de AEX-fondsen (met ISIN) en de koersbronnen |
| `config/indices.yaml` | De indices, met valuta, rentecurve en (waar gevolgd) de aandelen voor marktbreedte |
| `config/etfs.yaml` | ETF-groepen per index, obligatiecategorieën en de staatsrentes ter vergelijking |
| `config/commodities.yaml` | Grondstoffen (termijncontracten, CFTC-code, EIA-reeks) en valutaparen met per valuta de rente, reële effectieve koers en CFTC-code |
| `config/etcs.csv` | Zelf bijgehouden ETC's per grondstof: structuur, onderpand, kosten, met bron en datum |
| `config/etfs.csv`, `config/bond_etfs.csv` | Zelf bijgehouden fondskenmerken (kosten, domicilie, replicatie, omvang; bij obligaties rendement, duration en ratings), met bron en datum per regel |
| `config/providers.yaml` | Databronnen: adressen, snelheidslimieten, maandbudgetten, planning van de nachtelijke runs |
| `config/glossary.nl.yaml` | De woordenlijst: elke tooltip in de interface komt hiervandaan |
| `.env` | Wachtwoorden en API-sleutels (nooit in git) |

### Modelversie

Elke wijziging aan `config/model/` levert een nieuwe modelversie op. Na een wijziging:

1. Verhoog het middelste getal van `version` in `config/model/model.yaml` (bijvoorbeeld `0.6.0` → `0.7.0`).
   Het laatste getal is voor uitdagers uit de leerlus (`0.6.1`, `0.6.2`, ...).
2. Leg de versie vast: `docker compose run --rm -v ./config:/config server python -m app.cli lock-model`
   (of lokaal in `server/`: `python -m app.cli lock-model`).

Zonder deze stappen weigert de rekenserver te starten en falen de tests. Zo is elke grade later
terug te voeren op precies de instellingen waarmee hij berekend is. Commentaar en opmaak in de YAML
tellen niet als wijziging. Controleren zonder vast te leggen: `python -m app.cli check-config`.

Gewichten, drempels en gates veranderen nooit automatisch; vanaf fase 9 doet de app hooguit een voorstel
dat je zelf goedkeurt.

## Data en nachtelijke runs

De rekenserver haalt elke nacht zelf data op (tijden in UTC, instelbaar in `config/providers.yaml`):

| Taak | Wanneer | Wat |
| --- | --- | --- |
| Crypto | 00:05 | Top 50 van CoinGecko, dagkoersen (Coinbase → Binance → CoinGecko), marktwaarde, TVL en fees (DefiLlama), on-chain data (Coin Metrics) |
| Markten | werkdagen 21:45 | Indices, ETF's en obligatie-ETF's (Yahoo), tien grootste posities (maandelijks), rentes (FRED, ECB) en de Amerikaanse rentecurve (US Treasury), CAPE van de S&P 500 (Shiller, wekelijks), daarna het marktregime en de grades |
| Grondstoffen en valuta | werkdagen 22:00 | Termijncontracten en ETC's (Yahoo), CFTC-posities, EIA-voorraden (met sleutel), Wereldbank, rentes en reële wisselkoersen (FRED), valutaparen uit de ECB-koersen, daarna de grades |
| Aandelen | werkdagen 22:30 | Grootste SEC-registranten met een 10-K en de AEX-fondsen, dagkoersen (Tiingo → Yahoo; EODHD als je die afneemt), SEC-cijfers na elke nieuwe publicatie en minstens maandelijks, transacties van bestuurders (SEC Form 4: de eerste keer de kwartaalbestanden vanaf 2009, daarna per formulier), daarna de grades |
| Wisselkoersen en macro | werkdagen 16:30 | ECB-referentiekoersen (Frankfurter) en rentes, VIX en dollarindex (FRED) |
| Opruimen | 03:30 | Ruwe antwoorden ouder dan de bewaartermijn per bron |

De pagina **Instellingen** (rechtsboven) toont per bron het aantal aanroepen, het maandbudget, fouten,
de laatste runs en hoeveel data er is. Daar kun je een taak ook direct starten. Via de opdrachtregel:
`docker compose exec server python -m app.cli run crypto`.

Sleutels in `.env`:

| Sleutel | Wat | Zonder sleutel |
| --- | --- | --- |
| `COINGECKO_API_KEY` | Gratis Demo-sleutel van CoinGecko | Cryptolijst en marktwaarde ontbreken |
| `FRED_API_KEY` | Gratis sleutel van FRED | Rentes, VIX en dollarindex ontbreken |
| `TIINGO_API_KEY` | Gratis sleutel van Tiingo (VS-koersen) | Koersen komen van Yahoo Finance (onofficieel, kan geblokkeerd raken) |
| `SEC_USER_AGENT` | Verplicht voor SEC: een naam en **jouw** e-mailadres, bijvoorbeeld `"Graadmeter prive naam@voorbeeld.nl"` | SEC weigert de aanvragen |
| `EODHD_API_KEY` | Betaald (EODHD), optioneel: Europese koersen | Europese koersen komen van Yahoo Finance |
| `EIA_API_KEY` | Gratis sleutel van de EIA (Amerikaanse energiecijfers) | Geen voorraadcijfers voor olie en gas; de pijler Fundamentals blijft leeg |
| `MARKETAUX_API_KEY` | Gratis sleutel van Marketaux (nieuws, 100 per dag) | De analyse van grote missers krijgt geen nieuwskoppen |

Zonder sleutel slaat de app die bron over en meldt dat; verder werkt alles door.

### Yahoo Finance

Koersen van indices, ETF's, obligatie-ETF's, termijncontracten, ETC's en Europese aandelen komen van Yahoo
Finance. Yahoo heeft daar geen officiële API voor en zijn voorwaarden staan geautomatiseerd ophalen niet
uitdrukkelijk toe; er is voor die markten ook geen gratis officiële bron. De app blijft daarom Yahoo gebruiken,
voorzichtig en omkeerbaar:

- langzaam (één aanvraag per twee seconden, een paar honderd per nacht) en alleen dagkoersen;
- weigert Yahoo vijf aanvragen op rij (geblokkeerd of te veel verzoeken), dan pauzeert de app Yahoo zes uur en
  meldt dat één keer, in plaats van door te vragen;
- **uitzetten** kan met één regel: `enabled: false` onder `yahoo` (en `yahoo_fund`) in `config/providers.yaml`.
  De app slaat Yahoo dan over en meldt dat als opmerking. Let op: indices, ETF's, obligaties en grondstoffen
  krijgen dan geen nieuwe koersen meer en hun grades verouderen; Amerikaanse aandelen lopen via Tiingo door,
  Europese aandelen alleen met een EODHD-sleutel.

Elke bron kan zo worden uitgezet.

Elke run is veilig te herhalen: bestaande rijen worden nooit dubbel geschreven, en een herzien cijfer
komt als nieuwe rij naast het oude (met het moment waarop het bekend werd).

## Grades

Na elke run berekent de rekenserver voor elke gevolgde asset een grade voor de laatst afgesloten dag
(crypto: gisteren; aandelen: de laatste beursdag) en slaat die op in `grade_snapshot` (nooit overschreven).
Per asset komt er een grade, een pegveiligheid (stablecoins), een speculatie-oordeel (memecoins) of een
reden waarom er geen grade is.

Aandelen worden vergeleken binnen hun sector (uit de SIC-code bij SEC); een sector met minder dan acht
aandelen valt terug op alle aandelen met hetzelfde sjabloon. Banken en verzekeraars hebben een eigen
sjabloon, net als vastgoedfondsen. Europese aandelen zonder SEC-registratie hebben geen gratis bron voor
jaarcijfers en krijgen daarom geen grade, alleen koersen en een technische score.

- **Opnieuw berekenen:** `docker compose exec server python -m app.cli grade 2026-10-10 [crypto|stocks]`
  (een dag die al een grade heeft, wordt niet overschreven).
- **Controleren dat elke grade exact te herleiden is:** `docker compose exec server python -m app.cli verify`.
- **Gegevens invullen die geen gratis bron heeft** (unlock-schema's, audits, hacks, bij RWA-tokens de
  uitgever en bewaring): `docker compose exec server python -m app.cli set-fact <asset> <veld> <waarde>`,
  bijvoorbeeld `set-fact arbitrum unlock_90d 0.04` of `set-fact somecoin flag_unresolved_exploit 1`.
  `<asset>` is de sleutel uit de adresbalk (`arbitrum`, `v`, `abn-as`). Voor een aandeel waarvan SEC
  geen aantal aandelen geeft (Visa, Berkshire Hathaway) kan dat met `set-fact v shares_outstanding <aantal>`.
  Zo'n waarde telt mee vanaf het moment van invullen, nooit met terugwerkende kracht.

### Toelichtingen door een taalmodel (optioneel)

Zonder `ANTHROPIC_API_KEY` in `.env` toont elke assetpagina de vaste sjabloontekst; de app werkt dan
volledig. Met een sleutel schrijft een goedkoop model (`claude-haiku-5-5`, in te stellen in
`config/ai.yaml`) 's nachts via de batch-API een toelichting per asset. Elk getal en elke grade in die
tekst wordt gecontroleerd tegen de berekende cijfers; bij een afwijking volgt één nieuwe poging, daarna
blijft de sjabloontekst staan. Een toelichting wordt alleen opnieuw geschreven als de grade verandert of
een pijler meer dan 5 punten verschuift. Het maandbudget (standaard 5 euro, omgerekend tegen de ECB-koers) is een harde stop; het
verbruik staat onder Instellingen.

- **Eén toelichting nu schrijven:** `docker compose exec server python -m app.cli explain bitcoin`.
- **Alle opgeslagen toelichtingen opnieuw controleren:** `docker compose exec server python -m app.cli check-explanations`.

### Marktregime

Elke week bepaalt de rekenserver het marktregime (risico aan, neutraal of risico uit) uit drie invoeren:
de wereldindex tegenover zijn 10-maandsgemiddelde, de renteopslag op high-yield-obligaties en de VIX. Het
regime staat per dag in de tabel `market_regime`, met de drie invoeren erbij. Bij risico uit gaat de grade
van aandelen en crypto één stapje omlaag (B wordt B-); gates blijven altijd gelden. De drempels staan in
`config/model/model.yaml` onder `regime`. Op de tab Indices staat de huidige stand met de invoeren.

### Grondstoffen en valuta

Een grondstof krijgt twee oordelen: de grondstof zelf (termijncurve, trend, voorraden, macro, posities van
speculanten) en het product waarmee je hem aanhoudt (een ETC: fysiek of via termijncontracten, onderpand,
kosten, rolopbrengst). Een valutapaar krijgt een richtingsscore: lang de eerste en kort de tweede valuta.
Elk paar staat er in beide richtingen; EUR/USD en USD/EUR zijn elkaars spiegelbeeld (de scores tellen op
tot 100).

### Model, terugtest en ijking

De pagina **Model** toont eerst de staat van dienst: alleen live grades, gemeten tegen wat daarna gebeurde
(uitkomsten na 1, 3, 6 en 12 maanden, tegen de benchmark uit `config/evaluation.yaml`). Zolang er minder dan
12 maanden met een uitkomst zijn, staat daar "onvoldoende data". De maandelijkse meting draait op de 2e van
elke maand.

Daaronder, apart en altijd gelabeld, de **terugtest**: het model maand voor maand toegepast op het verleden
met alleen de data die aan het eind van die dag bekend was. Per sjabloon staat erbij hoeveel maanden en
assets hij dekt. Een terugtest is herberekend, geen behaald resultaat.

- **Terugtest draaien** (vanaf 2010, alle klassen; duurt ongeveer een uur):
  `docker compose exec server python -m app.cli backtest` (of `backtest 2015-01 2020-12 stocks`).
  Gestopt? `backtest resume <nummer>`.
- **IJking**: na een terugtest stelt de app per sjabloon nieuwe lettergrenzen voor (10% A, 20% B, 40% C,
  20% D, 10% F). Keur goed of af op de pagina Model. De server verandert het model nooit zelf; een
  goedgekeurd voorstel leg je vast als nieuwe modelversie met `scripts/apply-proposal.sh <nummer>` (de
  configuratie is in de draaiende containers alleen-lezen; het script schrijft hem en herstart de server).

### Leerlus: voorstellen, uitdagers en terugdraaien

Elk kwartaal (de 3e van januari, april, juli en oktober) berekent de app per sjabloon een gewichtsvoorstel uit
de gemeten rangcorrelaties, laat het taalmodel (als er een sleutel is) het rapport beoordelen en analyseert
het nieuwe grote missers. Daar komen alleen **voorstellen** uit:

- Elk gewichtsvoorstel gaat door een vaste controle van de vangrails (5–40% per pijler, 0,5–1,5 keer het
  startgewicht, hoogstens 3 procentpunt per kwartaal, minimaal 120 maanden terugtest, 30 assets per maand en
  12 maanden live). Een voorstel dat een vangrail schendt wordt geweigerd en kan niet worden goedgekeurd.
- **Goedkeuren** start een uitdager: een nieuwe modelversie (het laatste versiegetal omhoog, bijvoorbeeld 0.6.1)
  die elke nacht in de schaduw meedraait en nooit wordt getoond. De wekelijkse taak "Terugtest van uitdagers" maakt de terugtest die de toetsen nodig hebben.
- **Promoveren** kan pas na minstens 6 maanden schaduw en als alle toetsen slagen (t-waarde 3, verbetering
  t 2, Deflated Sharpe boven 0,95, PBO onder 0,2, volgorde, wisselingen, daling, live niet slechter),
  hoogstens één keer per 6 maanden. Dan wordt de uitdager meteen actief, zonder herstart.
- **Terugdraaien** maakt de laatste promotie met één klik ongedaan.
- **Kandidaat-gates** uit de analyse van missers zijn ter informatie: het taalmodel noemt alleen een
  maatstaf en richting, de app toetst zelf elke drempel over de terugtest en telt vals alarm. Een nieuwe gate
  is een modelwijziging in de configuratie.
- **Kwalitatieve kenmerken**: plak op een assetpagina de tekst van een jaarverslag of whitepaper. Het
  taalmodel geeft per onderdeel een oordeel met een letterlijk citaat; een citaat dat niet in de tekst staat
  valt weg. Telt alleen als rode vlag, nooit in de score.

### ETF-kenmerken bijwerken

Er is geen gratis bron met betrouwbare fondskenmerken. Werk daarom `config/etfs.csv` en
`config/bond_etfs.csv` zelf bij (bijvoorbeeld elk kwartaal, met de factsheet van de uitgever) en vul bron
en datum in. Een nieuwe waarde telt mee vanaf het moment dat de nachtrun hem inleest. Obligatiecijfers
(rendement, duration, ratings) ouder dan 200 dagen tellen niet meer mee.

## Inloggen

De interface vraagt één wachtwoord: `APP_PASSWORD` in `.env` (verplicht; zonder start de interface niet).
De sessie is een ondertekend cookie van 30 dagen; een ander wachtwoord logt iedereen uit. Na tien foute
pogingen in een kwartier volgt een pauze. De rekenserver zelf is alleen binnen Docker bereikbaar. Bedoeld
voor het thuisnetwerk: zet poort 3000 niet open naar het internet.

## Back-up en herstel

- **Elke nacht om 02:00 UTC** maakt de server `backups/graadmeter-<tijd>.dump` (PostgreSQL custom format)
  met een `.sha256` ernaast, gecontroleerd door de inhoudsopgave terug te lezen. Bewaard: de laatste 14 en
  de eerste van elk van de laatste 12 maanden (`config/operations.yaml`).
- **Elke zondag** zet de server de nieuwste back-up terug in een lege, tijdelijke database, rekent daar
  elke grade opnieuw uit uit zijn opgeslagen invoer en modelversie, en vergelijkt de grades met de live
  database. De uitkomst staat onder Instellingen > Beheer.
- **Met de hand**: `scripts/backup.sh` (back-up), `docker compose exec server python -m app.cli restore-test`.
- **Herstellen, ook op een schone machine**: `scripts/restore.sh backups/graadmeter-<tijd>.dump` (op de NAS
  gewoon zo, want daar heet het NAS-bestand `docker-compose.yml`). Het script controleert het
  bestand, zet de database terug, start de app en rekent alle grades opnieuw uit.
- Kopieer `backups/` ook naar een andere plek (Hyper Backup naar een externe schijf of de cloud).

## Meldingen en bewaking

Mislukt een geplande taak, of eindigt hij met minstens 5 fouten, dan stuurt de server een melding. Elk uur
controleert hij ook of geen taak is blijven liggen (grenzen in `config/operations.yaml`). Kanalen in
`.env`: `NOTIFY_WEBHOOK_URL` (bijvoorbeeld een ntfy-onderwerp of Synology Chat) en/of SMTP
(`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_FROM`, `NOTIFY_EMAIL_TO`). Testen:
Instellingen > Beheer > Testmelding sturen, of `python -m app.cli notify-test`. Sleutels in URL's worden
uit meldingen weggelaten.

Elke run legt duur, rekentijd en het hoogste geheugengebruik vast (Instellingen > Laatste runs).
`python -m app.cli nightly` draait alle nachtelijke taken achter elkaar en meldt de totale tijd.

## Tests

```bash
scripts/test.sh               # alle tests in containers; geen Python of Node nodig op de Mac
```

Voor ontwikkelaars, lokaal: `cd server && pip install -r requirements-dev.txt && pytest`
(met `TEST_DATABASE_URL` naar een lege PostgreSQL-database voor de databasetests) en
`cd web && npm ci && npm test`.

## Bouwfases

De app wordt in elf fases gebouwd (zie `CHANGELOG.md`). Na elke fase volgt een akkoord van de eigenaar.

| Fase | Inhoud | Status |
| --- | --- | --- |
| 0 | Fundament | Klaar |
| 1 | Datalaag (crypto, wisselkoersen, macro) | Klaar |
| 2 | Grading-engine en crypto | Klaar |
| 3 | Interface en grafiek | Klaar |
| 4 | Aandelen | Klaar |
| 5 | ETF's, obligaties, indices en marktregime | Klaar |
| 6 | Grondstoffen en valuta | Klaar |
| 7 | Toelichting, volglijst en bronnen | Klaar |
| 8 | Uitkomsten, terugtest en pagina Model | Klaar |
| 9 | Leerlus | Klaar |
| 10 | Afronding | Klaar, wacht op akkoord |

## Wat deze app niet doet

Geen orders, geen koppeling met handelsaccounts, geen publiek delen van grades, geen automatische
modelwijzigingen, geen verzonnen cijfers en geen woorden als kopen, verkopen of koersdoel.
