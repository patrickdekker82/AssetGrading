# Handleiding Graadmeter

Graadmeter is je eigen app die beleggingsassets per klasse rangschikt met een onderbouwde grade. Deze
handleiding legt uit hoe je hem installeert, gebruikt en onderhoudt. De technische details staan in de
README.

> Deze app is een privéhulpmiddel voor onderzoek. Grades zijn een rangorde op basis van een model, geen
> beleggingsadvies en geen voorspelling. Resultaten uit het verleden bieden geen garantie voor de toekomst.

## Inhoud

1. [Wat de app doet, en wat niet](#1-wat-de-app-doet-en-wat-niet)
2. [Installeren op de Synology](#2-installeren-op-de-synology)
3. [De eerste keer](#3-de-eerste-keer)
4. [Grades lezen](#4-grades-lezen)
5. [De tabs](#5-de-tabs)
6. [Een asset bekijken](#6-een-asset-bekijken)
7. [Zoeken en de volglijst](#7-zoeken-en-de-volglijst)
8. [Toelichtingen en het taalmodel](#8-toelichtingen-en-het-taalmodel)
9. [De pagina Model](#9-de-pagina-model)
10. [Nachtelijke taken](#10-nachtelijke-taken)
11. [Back-up en herstel](#11-back-up-en-herstel)
12. [Meldingen](#12-meldingen)
13. [Onderhoud](#13-onderhoud)
14. [Problemen oplossen](#14-problemen-oplossen)

## 1. Wat de app doet, en wat niet

Elke nacht haalt de app koersen en cijfers op bij gratis bronnen (en betaalde, als je een sleutel invult),
rekent per asset een **score van 0 tot 100** uit en zet die om in een **letter van A+ tot F**. Een grade
zegt waar een asset staat ten opzichte van vergelijkbare assets: een rangorde, geen voorspelling.

De app:

- rekent alles zelf uit met een vast model dat in configuratiebestanden staat; elke wijziging is een nieuwe
  modelversie, en elke oude grade is later exact na te rekenen;
- bewaart elke grade die hij ooit gaf, zodat je kunt zien hoe goed het model het live doet;
- doet nooit zelf een aanpassing aan het model: voorstellen moet jij goedkeuren;
- deelt niets met anderen, plaatst geen orders en heeft geen koppeling met een broker.

## 2. Installeren op de Synology

Je bouwt de app op je Mac en zet hem daarna op de NAS. Op de NAS zelf wordt niets gebouwd.

**Op de Mac** (met Docker Desktop):

```bash
scripts/build-images.sh
```

Dat maakt `dist/graadmeter-images.tar.gz`.

**Op de NAS** (via SSH; zet SSH aan in DSM onder Configuratiescherm > Terminal en SNMP):

1. Maak een map, bijvoorbeeld `/volume1/docker/graadmeter`.
2. Kopieer daarheen: `dist/graadmeter-images.tar.gz`, `docker-compose.yml`, `docker-compose.nas.yml`, de
   mappen `config/` en `scripts/`, en een ingevuld `.env` (zie hoofdstuk 3).
3. Laad de images: `docker load -i graadmeter-images.tar.gz`
4. Controleer dat ze op deze NAS werken: `scripts/nas-smoketest.sh` (alles moet `OK` zijn).
5. Start de app:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.nas.yml up -d
   ```

6. Open `http://<adres-van-je-nas>:3000` en log in.
7. Draai één keer de controle van geheugen en rekentijd: `scripts/nas-check.sh`. Die draait een volledige
   nachtrun, meet het geheugen per container en meldt of alles binnen een uur klaar is.

De database staat in `data/postgres` en de back-ups in `backups`, allebei naast de compose-bestanden.

De app is bedoeld voor je thuisnetwerk. Zet poort 3000 niet open naar het internet.

## 3. De eerste keer

Kopieer `.env.example` naar `.env` en vul in:

| Instelling | Wat |
| --- | --- |
| `POSTGRES_PASSWORD` | Een lang willekeurig wachtwoord voor de database. Je hoeft het nergens te onthouden. |
| `APP_PASSWORD` | Het wachtwoord waarmee je inlogt. Kies een lange zin. Veranderen logt iedereen uit. |
| `COINGECKO_API_KEY` | Gratis Demo-sleutel van CoinGecko (nodig voor de cryptolijst). |
| `FRED_API_KEY` | Gratis sleutel van FRED (rentes, VIX, dollarindex). |
| `SEC_USER_AGENT` | Je naam en **je eigen** e-mailadres, bijvoorbeeld `"Graadmeter prive naam@voorbeeld.nl"`. De SEC eist dit. |
| `TIINGO_API_KEY`, `EIA_API_KEY` | Optioneel, gratis. Zonder valt de app terug op andere bronnen of laat hij dat deel leeg. |
| `EODHD_API_KEY` | Optioneel, betaald: betere Europese koersen. |
| `ANTHROPIC_API_KEY` | Optioneel: toelichtingen en analyses door een taalmodel (hoofdstuk 8). |
| `NOTIFY_WEBHOOK_URL` of `SMTP_...` | Optioneel: meldingen als een nachtrun mislukt (hoofdstuk 12). |

Na het starten is de database nog leeg. Ga naar **Instellingen** (rechtsboven) en klik bij elke taak op
**Nu draaien**, of wacht een nacht. De eerste crypto-run haalt historie op en duurt langer.

## 4. Grades lezen

| Begrip | Betekenis |
| --- | --- |
| **Score** | 0 tot 100: het gewogen gemiddelde van de pijlers, elk een percentiel binnen de vergelijkingsgroep. |
| **Grade** | De letter bij de score. A is de top van de groep, F de onderkant. Plus en min verdelen een letter in drieën. |
| **Kwaliteit** | Alle pijlers behalve trend en momentum: iets over de asset zelf. |
| **Timing** | De technische score: iets over het moment. Een sterke asset kan op een zwak moment staan. |
| **Bandbreedte** | De grade als elk gewicht 20% hoger of lager zou zijn, bijvoorbeeld B (B- tot B+). |
| **Datadekking** | Welk deel van het model echte data had. Onder 60%: grade grijs met "voorlopig". Onder 40%: geen grade. |
| **Harde regel (gate)** | Een regel die de grade begrenst, bijvoorbeeld "hoogstens C" bij een te hoge schuld. Wint altijd van de score. |

Beweeg met de muis over een onderstreept woord voor uitleg; alle uitleg staat in `config/glossary.nl.yaml`.

## 5. De tabs

| Tab | Wat |
| --- | --- |
| Crypto | De grootste munten, per type beoordeeld (Bitcoin, platform, DeFi, memecoin, stablecoin, ...). Stablecoins krijgen een pegveiligheid in plaats van een grade, memecoins alleen een veiligheidscontrole. |
| Aandelen | Grote Amerikaanse bedrijven en de AEX. Banken en vastgoedfondsen hebben een eigen sjabloon. |
| ETF's | Alleen ETF's op dezelfde index worden met elkaar vergeleken. |
| Grondstoffen | Per grondstof de grade, en ernaast het product (ETC) waarmee je hem kunt aanhouden. |
| Valuta | Een richtingsscore: EUR/USD en USD/EUR tellen altijd op tot 100. |
| Obligaties | Obligatie-ETF's en de staatsrentes. |
| Indices | Wereldwijde indices, plus het marktregime (risico aan, neutraal, risico uit). |
| Volglijst | Je eigen selectie over alle klassen. |
| Model | Hoe goed het model zelf presteert, en de voorstellen (hoofdstuk 9). |

Elke lijst is te sorteren en te filteren; de grootte (top 25, 50 of 100) staat in `config/universes.yaml`.

## 6. Een asset bekijken

Klik op een naam. De assetpagina toont van boven naar beneden:

1. de grade met score, Kwaliteit, Timing, bandbreedte en datadekking;
2. de pijlers met elke maatstaf, de waarde, het percentiel, de bron en de vergelijkingsgroep;
3. de harde regels met de reden als er een geraakt is;
4. de toelichting in gewone taal;
5. kwalitatieve kenmerken (hoofdstuk 9);
6. de koersgrafiek (TradingView Lightweight Charts) met de indicatoren van deze klasse;
7. de geschiedenis van de grade.

## 7. Zoeken en de volglijst

Het zoekveld bovenaan accepteert een naam, ticker, ISIN of contractadres. Staat een asset nog niet in de
app, dan kun je hem laten ophalen en beoordelen. Staat hij in geen enkele bron, dan zegt de app dat en
toont hij geen grade. Met **Volgen** zet je een asset op je volglijst.

## 8. Toelichtingen en het taalmodel

Zonder `ANTHROPIC_API_KEY` werkt alles; de toelichting is dan een vaste tekst uit de berekende cijfers.

Met een sleutel:

- schrijft een goedkoop model 's nachts toelichtingen. Elk getal en elke letter in de tekst wordt
  gecontroleerd tegen de berekening; klopt er iets niet, dan volgt één nieuwe poging en anders de vaste
  tekst;
- beoordeelt een sterker model elk kwartaal het evaluatierapport en analyseert het missers;
- kun je op een assetpagina een document laten lezen (kwalitatieve kenmerken).

Een taalmodel levert nooit cijfers voor een grade en verandert nooit iets aan het model. Het maandbudget
(standaard 5 euro, omgerekend tegen de laatste ECB-koers, in `config/ai.yaml`) is een harde stop; het verbruik staat onder **Instellingen**.

## 9. De pagina Model

**Staat van dienst (live)** toont alleen grades die de app op het moment zelf gaf, gemeten tegen wat
daarna gebeurde. Zolang er minder dan 12 maanden met een uitkomst zijn, staat er "onvoldoende data".

**Terugtest** (onderaan, met stippellijn) is het model toegepast op het verleden met alleen de data die
toen bekend was. Dit is herberekend, geen behaald resultaat. Per sjabloon staat erbij hoeveel maanden en
assets hij dekt.

**Voorstellen** ontstaan na een terugtest (nieuwe lettergrenzen) en elk kwartaal (nieuwe gewichten).
Een voorstel dat een vangrail schendt wordt automatisch geweigerd. Je beslist zelf:

- **Goedkeuren** van een gewichtsvoorstel start een **uitdager**: een nieuwe modelversie die in de schaduw
  meedraait en die je niet ziet.
- Na minstens 6 maanden kun je met **Toetsen uitvoeren** zien of hij aan alle eisen voldoet (onder meer
  een t-waarde van 3, een Deflated Sharpe boven 0,95 en een kans op overfitting onder 0,2).
- **Promoveren** kan alleen als alle toetsen gehaald zijn, en hoogstens één keer per 6 maanden. Vanaf dat
  moment worden grades met de nieuwe gewichten berekend.
- **Terugdraaien** maakt de laatste promotie met één klik ongedaan.
- Een goedgekeurd voorstel voor lettergrenzen leg je vast met
  `docker compose run --rm -v ./config:/config server python -m app.cli apply-proposal <nummer>` en
  daarna `docker compose restart server`.

## 10. Nachtelijke taken

Tijden in UTC (in Nederland 1 uur later in de winter, 2 uur in de zomer).

| Taak | Wanneer |
| --- | --- |
| Wisselkoersen en macro | werkdagen 16:30 |
| Indices, ETF's, obligaties en marktregime | werkdagen 21:45 |
| Grondstoffen, ETC's en valuta | werkdagen 22:00 |
| Aandelen | werkdagen 22:30 |
| Toelichtingen | 23:30 en 04:30 |
| Crypto | 00:05 |
| Back-up | 02:00 |
| Opruimen ruwe antwoorden | 03:30 |
| Hersteltest | zondag 05:00 |
| Terugtest van uitdagers | zondag 01:00 |
| Maandelijkse meting | de 2e van de maand, 06:00 |
| Kwartaalronde | de 3e van januari, april, juli en oktober, 07:00 |

Onder **Instellingen** zie je de laatste runs met duur en geheugengebruik, en kun je elke taak direct
starten.

## 11. Back-up en herstel

Elke nacht om 02:00 maakt de server een back-up van de database in de map `backups` naast de
compose-bestanden: een bestand `graadmeter-<datum>.dump` met een controlebestand `.sha256` ernaast. De app
bewaart de laatste 14 en daarnaast de eerste van elk van de laatste 12 maanden.

**Elke zondag** zet de app de nieuwste back-up terug in een lege, tijdelijke database. Daar rekent hij
elke grade opnieuw uit en vergelijkt hij die met het origineel. De uitkomst staat onder **Instellingen**
bij "Laatste hersteltest". Mislukt dat, dan krijg je een melding.

Kopieer de map `backups` ook regelmatig naar een andere plek, bijvoorbeeld met Hyper Backup naar een
externe schijf of de cloud. Een back-up op dezelfde NAS helpt niet als de NAS stukgaat.

**Herstellen**, ook op een nieuwe of andere machine:

1. Installeer de app zoals in hoofdstuk 2, met dezelfde `.env`, maar start hem nog niet.
2. Zet het back-upbestand en het `.sha256`-bestand in de map `backups`.
3. Draai (op de NAS met `COMPOSE_FILES="-f docker-compose.yml -f docker-compose.nas.yml"` ervoor):

   ```bash
   scripts/restore.sh backups/graadmeter-<datum>.dump
   ```

   Het script controleert het bestand, zet de database terug, start de app en rekent elke grade opnieuw
   uit. Het eindigt met bijvoorbeeld `771 snapshots herberekend, 771 exact gelijk, 0 afwijkend`.

Een back-up met de hand maken: `scripts/backup.sh`.

## 12. Meldingen

Mislukt een nachtrun, of eindigt hij met veel fouten, of draait een taak helemaal niet, dan stuurt de app
een melding. Stel minstens één kanaal in via `.env`:

- **Webhook**, bijvoorbeeld met de app ntfy op je telefoon: kies een lange, geheime onderwerpnaam en zet
  `NOTIFY_WEBHOOK_URL=https://ntfy.sh/<die-naam>`. Een webhook van Synology Chat werkt ook.
- **E-mail**: vul `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_FROM` en
  `NOTIFY_EMAIL_TO` in, bijvoorbeeld met de gegevens van je e-mailprovider.

Start daarna opnieuw (`docker compose up -d`) en klik onder **Instellingen** op **Testmelding sturen**.
Meldingen bevatten nooit sleutels of wachtwoorden.

## 13. Onderhoud

- **Nieuwe versie van de app**: bouw de images opnieuw op de Mac, laad ze op de NAS en start opnieuw. Het
  databaseschema wordt bij het starten vanzelf bijgewerkt. Maak vooraf een back-up met de hand.
- **Het model aanpassen**: wijzig de bestanden in `config/model/`, verhoog `version` in `model.yaml` en
  leg de versie vast met `python -m app.cli lock-model`. De oude grades blijven onder hun eigen versie
  bewaard.
- **Gegevens die geen gratis bron heeft** (unlock-schema's, audits, hacks): `python -m app.cli set-fact
  <asset> <veld> <waarde>`. Zo'n waarde telt mee vanaf het moment van invullen, nooit met terugwerkende
  kracht.
- **ETF-kenmerken**: werk `config/etfs.csv` en `config/bond_etfs.csv` bij, met de datum van controle.
- **Opdrachten** op de NAS draai je met `docker compose exec server python -m app.cli <opdracht>`;
  `python -m app.cli` zonder opdracht controleert de configuratie.

## 14. Problemen oplossen

| Wat je ziet | Wat te doen |
| --- | --- |
| "Server offline" rechtsboven | `docker compose ps`; start opnieuw met `docker compose up -d` en kijk in `docker compose logs server`. |
| Inlogpagina zegt dat er geen wachtwoord is | Zet `APP_PASSWORD` in `.env` en `docker compose up -d`. |
| "Te veel pogingen" bij inloggen | Wacht een kwartier. |
| Een tab is leeg | Draai de taak van die klasse onder Instellingen; kijk bij de laatste run naar de meldingen. |
| Een bron geeft veel fouten | Zie Instellingen > Aanroepen per bron; vaak een ontbrekende of verlopen sleutel, of een budget dat op is. |
| Back-up mislukt: map niet schrijfbaar | Controleer dat de map `backups` naast de compose-bestanden bestaat; de server maakt hem bij het starten schrijfbaar. |
| Geen melding ontvangen | Instellingen > Beheer > Testmelding sturen; de reden van een mislukte melding staat bij "Laatste meldingen". |
| De nachtrun duurt te lang | `scripts/nas-check.sh` toont de tijd per taak. Meestal wacht de app op snelheidslimieten van bronnen. |
