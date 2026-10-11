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

## Starten op de Mac

Nodig: [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
cp .env.example .env          # vul daarna minstens POSTGRES_PASSWORD in
docker compose up --build
```

Open daarna <http://localhost:3000>. Rechtsboven staat of het systeem in orde is.
Stoppen: `Ctrl+C`, of `docker compose down` (de data blijft bewaard).

## Op de Synology (DS920+)

Bouw de images **op de Mac**, nooit op de NAS (de NAS is daar te traag voor en heeft een andere processor):

```bash
scripts/build-images.sh       # maakt dist/graadmeter-images.tar.gz (linux/amd64)
```

Op de NAS (via SSH, in een map zoals `/volume1/docker/graadmeter`):

1. Kopieer `dist/graadmeter-images.tar.gz`, `docker-compose.yml`, `docker-compose.nas.yml`,
   de map `config/`, de map `scripts/` en je `.env` naar die map.
2. Laad de images: `docker load -i graadmeter-images.tar.gz`
3. Controleer of de images op deze NAS werken: `scripts/nas-smoketest.sh` (alle regels moeten `OK` zijn).
4. Start: `docker compose -f docker-compose.yml -f docker-compose.nas.yml up -d`

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
| `config/providers.yaml` | Databronnen: adressen, snelheidslimieten, maandbudgetten, planning van de nachtelijke runs |
| `config/glossary.nl.yaml` | De woordenlijst: elke tooltip in de interface komt hiervandaan |
| `.env` | Wachtwoorden en API-sleutels (nooit in git) |

### Modelversie

Elke wijziging aan `config/model/` levert een nieuwe modelversie op. Na een wijziging:

1. Verhoog `version` in `config/model/model.yaml` (bijvoorbeeld `0.1.0` → `0.1.1`).
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
| Wisselkoersen en macro | werkdagen 16:30 | ECB-referentiekoersen (Frankfurter) en rentes, VIX en dollarindex (FRED) |
| Opruimen | 03:30 | Ruwe antwoorden ouder dan de bewaartermijn per bron |

De pagina **Verbruik** (rechtsboven) toont per bron het aantal aanroepen, het maandbudget, fouten,
de laatste runs en hoeveel data er is. Daar kun je een taak ook direct starten. Via de opdrachtregel:
`docker compose exec server python -m app.cli run crypto`.

Sleutels in `.env`: `COINGECKO_API_KEY` (gratis Demo-sleutel) en `FRED_API_KEY` (gratis). Zonder
sleutel slaat de app die bron over en meldt dat; verder werkt alles door.

Elke run is veilig te herhalen: bestaande rijen worden nooit dubbel geschreven, en een herzien cijfer
komt als nieuwe rij naast het oude (met het moment waarop het bekend werd).

## Back-up

```bash
scripts/backup.sh             # schrijft backups/graadmeter-<datum>.sql.gz, bewaart de laatste 14
```

Vanaf fase 10 draait dit elke nacht automatisch, met een geteste herstelprocedure.

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
| 1 | Datalaag (crypto, wisselkoersen, macro) | Klaar, wacht op akkoord |
| 2 | Grading-engine en crypto | |
| 3 | Interface en grafiek | |
| 4 | Aandelen | |
| 5 | ETF's, obligaties, indices en marktregime | |
| 6 | Grondstoffen en valuta | |
| 7 | Toelichting, volglijst en bronnen | |
| 8 | Uitkomsten, terugtest en pagina Model | |
| 9 | Leerlus | |
| 10 | Afronding | |

## Wat deze app niet doet

Geen orders, geen koppeling met handelsaccounts, geen publiek delen van grades, geen automatische
modelwijzigingen, geen verzonnen cijfers en geen woorden als kopen, verkopen of koersdoel.
