# Changelog

## Vier gratis bronnen en Yahoo uitgewerkt (2026-10-15)

### Nieuwe bronnen (geen nieuwe modelversie: alleen nieuwe invoer, elke grade bewaart zijn invoer)

- **US Treasury**: de dagelijkse rentecurve (3 maanden tot 30 jaar, vanaf 1990) rechtstreeks van
  home.treasury.gov, plus vijf extra looptijden van de ECB-curve. Obligatie-ETF's krijgen daarmee de maatstaf
  **plek op de rentecurve**: carry plus roll-down per jaar duration, met de staatscurve van de fondsvaluta.
- **Shiller**: de maandelijkse CAPE en excess CAPE yield van de S&P 500 (wekelijks gelezen; de link naar het
  bestand komt van shillerdata.com). De S&P 500 krijgt zo een pijler **Waardering**, tegen de eigen historie.
  Een maand telt pas een maand na afloop mee (ook in de terugtest).
- **SEC Form 4**: transacties van bestuurders. Historie uit de kwartaalbestanden "Insider Transactions Data
  Sets" (vanaf 2009, eenmalig een paar minuten), daarna per formulier uit de lijst die de aandelenrun al leest.
  Maatstaf **aankopen bestuurders**: aantal bestuurders en directieleden met aankopen op de beurs in zes
  maanden, zonder 10b5-1-plannen en zonder routinematige kopers (Cohen, Malloy en Pomorski). Leeg (niet nul)
  buiten de VS of als de data het venster niet dekt.
- **Marketaux**: met een gratis sleutel krijgt de kwartaalanalyse van grote missers de nieuwskoppen over het
  bedrijf uit de maanden na de grade (prompt `miss-analysis-2`). Zonder sleutel verandert er niets.
- Nieuwe tabellen `insider_filing`, `insider_dataset` en `news_item` (append-only), migratie 0012.
- Grote antwoorden (de kwartaalzips) worden gelogd zonder inhoud (`raw_max_bytes` per bron).

### Yahoo Finance

- Besloten: Yahoo blijft de bron voor indices, ETF's, termijncontracten, ETC's en Europese aandelen (geen
  gratis officieel alternatief), maar omkeerbaar: elke bron kan uit met `enabled: false` in
  `config/providers.yaml`, en na vijf geweigerde aanvragen op rij pauzeert de app een bron zes uur en meldt dat
  één keer in plaats van bij elke asset.

### Controle

- Terugtest 4 (model 0.6.0, 2010–nu) is klaar: 62.310 terugtestgrades, geen fouten, ijkvoorstel 4.
- In de ontwikkelomgeving: Treasury en ECB 118.346 waarnemingen, insiders 67 kwartalen (114.192 rijen) plus
  3.616 losse formulieren. Shiller kon hier alleen met een oude kopie worden getest (shillerdata.com is vanuit
  de ontwikkelomgeving niet bereikbaar); de app markeert die terecht als te oud. Op de NAS haalt hij het actuele
  bestand.

## Installatiehandleiding (2026-10-15)

- **`docs/installatie.md`**: van niets naar een werkende app op de DS920+, met elke opdracht om te plakken
  (sleutels, Mac, Synology, eerste data, NAS-controle, terugtest en ijking, Hyper Backup, meldingen, updates,
  problemen oplossen) en per open punt wat je zelf doet.
- **`scripts/make-env.sh`** maakt `.env` door de sleutels één voor één te vragen; wachtwoorden worden gemaakt.
  Werkt met de bash 3.2 van macOS.
- **`docker-compose.nas.yml` is nu een compleet, zelfstandig bestand** (op de NAS als `docker-compose.yml`).
  De override met `!reset`/`!override` vroeg om Docker Compose 2.24 en de map `server/` op de NAS; het nieuwe
  bestand is getest met Compose 2.20 (de versie van Container Manager), inclusief starten, back-up en herstel.
- **`scripts/apply-proposal.sh`**: het vastleggen van een goedgekeurd ijkvoorstel. De eerder beschreven
  opdracht (`docker compose run -v ./config:/config ...`) werkte niet: de configuratie bleef alleen-lezen.

## Na de bouw – controle en verbeteringen, model 0.6.0 (2026-10-15)

Een controle van alle hoofdstukken van de bouwprompt tegen de code en een doorloop van elke pagina
(12 pagina's, 21 assets, geen fouten). Wat is gerepareerd of toegevoegd:

### Model 0.6.0 (nieuwe versie; 0.5.0 blijft exact herberekenbaar)

- **Winsorizen zonder dubbeltelling**: de grenzen (5e en 95e percentiel) komen alleen uit de vergelijkingsgroep;
  de asset zelf telde eerst twee keer mee.
- **Valuta "geen voordeel" is precies C** (hoofdstuk 6), ook voor een paar dat lager zou scoren; eerst trok de
  gate alleen een betere grade omlaag. In de app staat nu "grade wordt C" in plaats van "hoogstens C".
- **CET1-drempel in de juiste eenheid**: 0,01 (1 procentpunt als ratio) in plaats van 1,0.
- **Indices: relatieve sterkte in euro** tegenover MSCI World (eerst in verschillende valuta's door elkaar).
- **10-maandsgemiddelde over afgesloten maanden**; de lopende maand telde mee.
- **Obligatie-ETF's krijgen Timing** (technische score van de fondskoers); de score verandert niet, want het
  sjabloon heeft geen trendpijler.
- Op 2026-10-14 opnieuw gegradeerd: 310 grades, verschillen vooral bij indices (gemiddeld 3,9 punten).
  `cli verify`: 1.391 van 1.391 grades exact gelijk, over alle versies.

### Overig

- **Snelheid**: de tab Aandelen laadde in 10 s, nu 0,2 s; de dekking op Instellingen van 9 s naar enkele
  seconden en daarna 10 minuten uit het geheugen.
- **Grafieken**: valuta met ADX, ATR, Ichimoku en het renteverschil; obligaties met eigen set (gemiddelden,
  daling vanaf de top, rentecurves VS en eurozone); VIX ook bij indices en ETF's; de gekozen indicatoren
  worden per soort grafiek onthouden in plaats van één gedeelde lijst.
- **Grades altijd met context**: dekking, peildatum en modelversie ook in zoeken, vergelijkbare ETF's, producten
  en het beste product in de ranglijst.
- **Tab Model**: de rangcorrelatie (IC) per maand als staafgrafiek per sjabloon; een voorstel dat op een andere
  modelversie is berekend kan niet meer worden goedgekeurd (alleen afgewezen).
- **Leerlus**: een maand met live grades telt in het kwartaaloverzicht niet nog eens mee uit de terugtest; het
  aantal geprobeerde varianten voor de Deflated Sharpe telt nu exact; uitdagers krijgen een patchnummer
  (0.6.1, 0.6.2, ...) zodat ze nooit botsen met een nieuwe modelversie uit de bestanden.
- **Marktregime**: op de eerste dag van een nieuwe modelversie wordt het regime eerst berekend, zodat ook de
  crypto- en aandelenrun (die vóór de marktenrun draaien) de regimescore hebben.
- **Taalmodel**: het budget staat in euro (5 euro, omgerekend tegen de ECB-koers); de verboden woorden komen
  uit de modelconfiguratie (`forbidden_words_nl`) in plaats van alleen een vaste lijst.
- Het Top-N-keuzemenu staat alleen nog op tabs waar de lijst echt in grootte kan wisselen.

### Bekend, nog niet opgelost

- **Ontbrekende gratis bronnen**: US Treasury, Marketaux (nieuws) en Wereldbank Pink Sheet zijn niet aangesloten.
  Daardoor blijven maatstaven leeg: REIT (geen grade), CET1 en NPL bij banken, waardering van indices,
  insidertransacties, ETF-spread en -instroom, ETF-instroom bij bitcoin en vraag naar edelmetaal.
- **Terugtest met de huidige lijsten** (overlevingsbias): historische samenstellingen zijn niet gratis.
- **Acceptatie op de NAS en met echte sleutels** (taalmodel) is nog niet op de Synology zelf gedaan:
  draai daar `scripts/nas-check.sh`.
- **Yahoo Finance**: de voorwaarden staan geautomatiseerd ophalen niet expliciet toe; jouw beslissing.
- Het open ijkvoorstel van terugtest 3 hoort bij model 0.5.0; terugtest 4 van model 0.6.0 maakt een nieuw voorstel.

## Fase 10 – Afronding (2026-10-15)

### Gebouwd

- **Back-up**: elke nacht om 02:00 UTC een `pg_dump` (custom format) vanuit de server naar `./backups`
  buiten de containers, met een SHA-256-bestand en een controle door de inhoudsopgave terug te lezen.
  Bewaard: de laatste 14 plus de eerste van elk van de laatste 12 maanden. De serverimage bevat nu
  `pg_dump` 16 uit de PostgreSQL-pakketbron; de container maakt de back-upmap bij het starten schrijfbaar
  en draait daarna als gewone gebruiker.
- **Bewezen herstel**: elke zondag zet de server de nieuwste back-up terug in een lege, tijdelijke database,
  rekent daar elke grade opnieuw uit en vergelijkt de grades met de live database. `scripts/restore.sh`
  herstelt een back-up, ook op een nieuwe machine, en eindigt met dezelfde herberekening.
- **Meldingen** bij een mislukte geplande run of een run met minstens 5 fouten, via een webhook (ntfy,
  Synology Chat) en/of e-mail (SMTP), alleen in te stellen in `.env`; sleutels in URL's worden gemaskeerd.
  Een **watchdog** controleert elk uur of een taak is blijven liggen (één melding per dag per taak). Alle
  pogingen staan in een logtabel; testmelding vanuit de app.
- **Geheugen en rekentijd**: elke run legt duur, rekentijd en het hoogste geheugengebruik vast (zichtbaar
  bij de laatste runs). `cli nightly` draait alle nachtelijke taken achter elkaar; `scripts/nas-check.sh`
  doet dat op de Synology en meet intussen het geheugen per container. Geheugenplafonds in
  docker-compose: database 1,5 GB, server 2 GB, interface 512 MB.
- **Inlog**: één wachtwoord (`APP_PASSWORD`), ondertekende sessiecookie van 30 dagen, pauze na tien foute
  pogingen per kwartier, alleen lokale doorverwijzingen na inloggen, `/api` zonder sessie geeft 401.
- **Pagina Instellingen**: kaart Beheer met laatste back-up, hersteltest, meldkanalen en laatste meldingen.
- **Handleiding** in het Nederlands (`docs/handleiding.md`) en een bijgewerkte README.

### Acceptatie

- **Herstel op een schone machine geeft dezelfde grades**: een kopie van de installatie in een lege map
  met een nieuw, leeg databasevolume; `scripts/restore.sh` met de back-up van de ontwikkeldatabase gaf
  "771 snapshots herberekend, 771 exact gelijk, 0 afwijkend". De controlegetallen van alle grades (771),
  terugtestgrades (62.109) en uitkomsten (135.445) waren identiek aan het origineel. In de containers van
  die installatie slaagden daarna ook de nachtelijke back-up en de hersteltest.
- **Volledige nachtrun binnen één uur**: alle nachtelijke taken achter elkaar met echte bronnen (zonder
  taalmodel, want er is geen sleutel): 16,9 minuten (wisselkoersen 10 s, markten 235 s, grondstoffen 216 s,
  aandelen 290 s, crypto 233 s, back-up 31 s), alle runs zonder fouten. Hoogste geheugengebruik van de
  server 497 MB; rekentijd samen onder een minuut: de tijd zit vooral in de snelheidslimieten van de
  bronnen, dus de tragere processor van de DS920+ telt weinig mee. Dit is gemeten in de ontwikkelomgeving,
  niet op de NAS zelf: draai daar `scripts/nas-check.sh` als controle.

### Gevonden en hersteld

- Een melding na een mislukte run maakte het run-object onleesbaar (dezelfde databasesessie); nu een eigen
  sessie.
- Na inloggen verwees de interface door naar het interne adres van de container (0.0.0.0:3000); nu
  relatief.
- `restore.sh` wachtte op de tijdelijke server die PostgreSQL bij een lege database start; nu op de echte.

## Fase 9 – Leerlus (2026-10-15)

### Gebouwd

- **Kwartaalvoorstel voor gewichten** (stap 1 tot 6 van hoofdstuk 8): rangcorrelatie per pijler over 3
  maanden op kwartaaleinden (geen overlap), terugtest en live samen, gekrompen met T / (T + 60), doelgewicht
  evenredig aan gekrompen rangcorrelatie gedeeld door de spreiding, gemengd met de startgewichten
  (λ = min(0,5; T / (T + 60))) en binnen de vangrails gebracht. T telt de maanden in onafhankelijke
  kwartalen.
- **Vangrails als vaste controle** voor elk voorstel, ook van het taalmodel: per pijler 5–40%, 0,5–1,5 keer
  het startgewicht, hoogstens 3 procentpunt per kwartaal, minimale data (120 maanden terugtest, 30 assets per
  maand, 12 maanden live). Een overtreding maakt het voorstel "geweigerd", met de redenen; zo'n voorstel kan
  niet worden goedgekeurd, en ook bij het starten van een uitdager wordt opnieuw gecontroleerd.
- **Kampioen en uitdager**: een goedgekeurd voorstel wordt een volledige modelversie in de database (de
  configuratiebestanden blijven het anker met de startgewichten) en draait elke nacht in de schaduw mee met
  hetzelfde marktregime als de kampioen. Nooit zichtbaar.
- **Toetsen voor promotie**: 6 maanden schaduw, eigen t-waarde ≥ 3 en verbetering ≥ 2 in de terugtest
  (Newey-West), Deflated Sharpe Ratio > 0,95 met het vastgelegde aantal pogingen (alle modelversies), PBO
  < 0,2 (combinatorische kruisvalidatie over alle geteste versies), volgorde A–F niet slechter, wisselingen
  hoogstens 20% hoger, daling van de A-groep niet groter, live schaduw niet duidelijk slechter, hoogstens één
  wissel per 6 maanden. Gemeten op de sjablonen waarvan de gewichten veranderen.
- **Promoveren en terugdraaien in de app**: append-only activatielog; promoveren alleen als alle toetsen slagen
  en de eigenaar klikt, terugdraaien maakt de laatste promotie met één klik ongedaan. Het actieve model wisselt
  zonder herstart; de server laadt bij het starten het actieve model uit dat log.
- **Kwartaalbeoordeling door het taalmodel** (sterker model, `claude-opus-5-5`): het evaluatierapport in,
  voorstellen met bewijs, verwacht effect en risico's uit, door dezelfde vangrailcontrole.
- **Analyse van missers** (live A/B-grades die daarna meer dan 30% achterbleven): het taalmodel verklaart en
  noemt hoogstens een maatstaf en richting; de code toetst elke deciel-drempel over de hele terugtest met
  telling van gevangen missers en vals alarm.
- **Kwalitatieve kenmerken** (goedkoop model): document in, per rubriek oordeel met letterlijk citaat; citaat
  wordt in de bron gecontroleerd, onvoldoende bewijs is geldig, telt alleen als rode vlag op de assetpagina.
- Nieuwe taken: kwartaalronde (3e van elk kwartaal) en wekelijks de terugtest van uitdagers. De maandmeting
  meet ook de uitdagers en voert hun promotietoetsen uit.

### Acceptatie

- **Een voorstel dat een vangrail schendt wordt geweigerd**: getest met een stap van 6 procentpunt, met een
  voorstel van het taalmodel (gelijke gewichten) en met een voorstel dat buiten de controle om op
  "goedgekeurd" is gezet: geweigerd, niet goed te keuren, en geen uitdager.
- **Een goedgekeurde wissel levert een nieuwe modelversie op en kan met één klik terug**: goedkeuren geeft
  een nieuwe versie in de schaduw; promoveren maakt die actief; terugdraaien zet de vorige terug; een tweede
  keer terugdraaien en een tweede wissel binnen 6 maanden worden geweigerd.
- **Geen enkel pad wijzigt gewichten zonder akkoord**: nachtelijke schaduwgrading, maandmeting met
  promotietoetsen en de kwartaalronde met taalmodel lopen allemaal; het actieve model blijft gelijk. Een test
  controleert ook in de broncode dat alleen `promote`, `rollback` en de start met de configuratiebestanden in
  het activatielog schrijven.
- Op de huidige data stelt de kwartaalronde nog niets voor: elk sjabloon zit onder het minimum, vooral omdat
  er nog geen 12 maanden live data zijn. Dat is de bedoeling van de vangrails.

## Fase 8 – Uitkomsten, terugtest en pagina Model (2026-10-15)

### Gebouwd

- **Uitkomstlabels** (`outcome`, append-only): per maandeinde-grade het totaalrendement in euro na 1, 3, 6
  en 12 maanden, het rendement boven de benchmark van de klasse (`config/evaluation.yaml`: Bitcoin voor
  crypto, S&P 500 of AEX voor aandelen, MSCI World voor ETF's en indices, het klassegemiddelde voor
  obligaties en grondstoffen, geen benchmark voor valutaparen) en de grootste tussentijdse daling. Alleen
  afgesloten periodes; een prijs ouder dan 7 dagen aan begin of eind telt niet.
- **Maandelijkse meting** (`evaluation`, append-only), per modelversie, sjabloon en horizon:
  rangcorrelatie per maand (gemiddelde, spreiding, deel boven nul), rendement boven de benchmark per letter
  met 95%-interval, verschil A min F, toets op de volgorde A tot F, deel dat de benchmark versloeg en
  grootste daling per letter, rangcorrelatie per pijler en samenhang tussen pijlers, wisselingen van
  letters, splitsing naar marktregime en het aantal grote missers. Alle t-waarden met Newey-West (vertraging
  horizon min één maand), en pas vanaf 6 maanden. Draait de 2e van elke maand op live grades.
- **Tijdvaste terugtest** (`backtest_run`, `backtest_snapshot`): dezelfde gradingcode als live, maand voor
  maand, met als peilmoment het einde van de maandeinddag. Feiten en macroreeksen tellen alleen als hun
  `available_at` daarvoor ligt (SEC-cijfers vanaf de indieningsdatum), koersen tot en met die dag, en het
  marktregime wordt per maand opnieuw berekend uit wat toen bekend was. Grades van de terugtest staan in een
  eigen tabel en komen nooit in de live staat van dienst. Hervatten na een onderbreking kan.
- **IJking van de lettergrenzen**: per sjabloon grenzen op de doelverdeling (10% A, 20% B, 40% C, 20% D,
  10% F) uit de terugtestscores, alleen met minstens 24 maanden en 300 waarnemingen. Het resultaat is een
  voorstel; de engine kent nu een letterschaal per sjabloon, maar die wordt pas gebruikt als de eigenaar
  het voorstel goedkeurt en de nieuwe modelversie vastlegt (`apply-proposal`).
- **Pagina Model**: bovenaan alleen de live staat van dienst met de stand "onvoldoende data" (minder dan
  12 maanden met uitkomst), daaronder openstaande voorstellen met Goedkeuren en Afwijzen, en daaronder,
  apart en met stippellijn en waarschuwing, de terugtest met per sjabloon de dekking in maanden en assets.
  Horizon kiesbaar (1, 3, 6, 12 maanden).
- Nieuwe begrippen in de woordenlijst: overrendement, t-waarde, ijking, grote misser, wisselingen.

### Acceptatie

- **Geen toekomstige data**: test met een bewust verschoven feit. Alle SEC-cijfers van een aandeel worden
  opnieuw "ingediend" met vijf keer zo hoge waarden, één dag na het maandeinde, plus een koers van tien
  keer zo hoog op de dag erna. De terugtestgrade van die maand blijft exact gelijk (invoer en uitkomst).
  Met een peilmoment na die indiening verandert hij wel, dus het feit telt mee zodra het bekend is.
- **Rapport per sjabloon met dekking in maanden en assets**: terugtest 2010-01 tot 2026-09 (201
  maandeinden, 62.109 grades, 135.445 uitkomsten). Bijvoorbeeld Aandeel algemeen 200 maanden en 76 assets,
  Valutapaar 201 maanden en 30 assets, Platform 110 maanden en 9 assets. Obligaties, REIT's, RWA- en
  utility-tokens, memecoins en stablecoins hebben geen bruikbare terugtest: hun kenmerken zijn pas nu
  ingevoerd (CSV) of de groep is te klein.
- **Terugtest en live gescheiden**: aparte tabellen, en op de pagina Model elk een eigen blok met label.
  Live staat op "onvoldoende data" (0 van 12 maanden).

### Wat de terugtest laat zien (startgewichten, modelversie 0.5.0)

- Bij geen enkel sjabloon voorspelt de score aantoonbaar het latere rendement: geen t-waarde komt boven 3.
- Bij Aandeel algemeen (12 maanden: rangcorrelatie −0,09, t −3,5), Valutapaar (−0,14, t −3,1) en Grondstof
  (−0,08, t −2,7) is het verband omgekeerd. Bij aandelen haalde F een mediaan van +15% boven de S&P 500,
  B −1%. Een deel daarvan is overlevingsbias: de lijst bevat de huidige grote bedrijven, dus de winnaars
  van de afgelopen jaren. Hoe hiermee om te gaan hoort bij fase 9 (leerlus), niet bij een stille aanpassing.
- IJkingsvoorstel 3 staat open voor 9 sjablonen met genoeg data. Het verandert alleen de verdeling van de
  letters, niet de volgorde.

### Gevonden en hersteld

- Crypto: de Coinbase-volumereeks werd ongesorteerd opgebouwd, waardoor een datumselectie kon mislukken
  (in de terugtest: juni 2025). Ook live had dit kunnen gebeuren. Geen invloed op bestaande grades
  (verify: 771/771 exact gelijk).
- Uitkomsten tellen niet bij een koers van nul of lager (WTI april 2020) of, buiten crypto, bij een dagsprong
  groter dan factor 5. Dat laatste vond vijf Londense ETC's met een eenhedenwissel op 3 januari 2012 (en
  HOGS.L in 2017) in de Yahoo-koersen; die koersreeksen zelf zijn nog niet hersteld.

## Fase 7 – Toelichting, volglijst en bronnen (2026-10-14)

### Gebouwd

- **Toelichting door een taalmodel** (hoofdstuk 9): de server stuurt per asset een JSON met de berekende
  grade, pijlers, maatstaven, gates en drempels naar de Claude API en krijgt Nederlandse tekst plus de
  gebruikte maatstaven terug, als JSON volgens een schema. De stopreden wordt gecontroleerd (een afgebroken
  of geweigerd antwoord telt als afgekeurd).
- **Getalcontrole**: elk getal in de tekst (in cijfers, Nederlandse of Engelse notatie, of in woorden) en
  elke grade moet in de invoer staan; daarnaast lengte (110–220 woorden), bekende maatstaven en geen
  woorden als kopen, verkopen of koersdoel. Bij een afwijking één nieuwe poging met de reden erbij, daarna
  de vaste sjabloontekst.
- **Vastleggen**: elke aanroep in `llm_call` (append-only) met model, promptversie, hash van de invoer,
  ruwe uitvoer, tokens en kosten. Toelichtingen in `explanation` (append-only); nooit stil overschreven.
- **Batch en caching**: nachtelijke taak `explanations` (23:30 en 04:30 UTC) haalt klaargezette batches op
  en stuurt nieuwe in via de Message Batches API (50% korting), met prompt caching voor de vaste instructie.
- **Verversen**: alleen bij een andere grade of status, of een pijler (of score) die meer dan 5 punten
  verschuift. Volglijst gaat voor.
- **Kostenbudget**: maandbudget in `config/ai.yaml` met harde stop; lopende batches worden vooraf
  gereserveerd op hun maximale kosten. Verbruik per onderdeel staat onder Instellingen (`/verbruik`;
  `/instellingen` verwijst daarheen).
- **Zonder API-sleutel** werkt alles: de taak meldt alleen dat de sjabloontekst blijft staan.
- **Pagina Bronnen** (`/bronnen`) met de verplichte vermeldingen van CoinGecko, TradingView, FRED en
  alternative.me, plus alle andere bronnen; link in de voetregel van elke pagina.
- **Volglijst**: een gevolgde asset met een oudere grade (eenmalig opgehaald, niet in een lijst) blijft
  zichtbaar, met de datum van die grade.
- Sjabloontekst: de bandbreedte noemt nu de ingestelde gewichtsvariatie en het hoogste memecoin-cijfer uit
  het sjabloon in plaats van vaste waarden.
- Header past nu op telefoonbreedte (liep 105 pixels over de rand).

### Acceptatie

- 100 gegenereerde toelichtingen over alle 16 sjablonen (test met een nep-taalmodel dat bij een deel
  verzonnen getallen, afgebroken JSON of een weigering teruggeeft): geen enkele opgeslagen tekst bevat een
  getal of grade die niet in de invoer stond; elke afgekeurde tekst kreeg precies één nieuwe poging.
- De sjabloontekst zelf komt op alle 309 actuele grades in de ontwikkeldatabase door dezelfde controle.
- Zonder `ANTHROPIC_API_KEY` werken assetpagina, taak en verbruikspagina; getest.
- Nog niet gedaan: een echte run tegen de Claude API, omdat er geen sleutel is ingesteld.

## Fase 6 – Grondstoffen en valuta (2026-10-14)

### Gebouwd

- **Nieuwe bronnen**:
  - CFTC Commitments of Traders: posities van speculanten, wekelijks. Voor grondstoffen managed money,
    voor valuta leveraged funds, als deel van de open interest. Een cijfer telt pas mee vanaf de vrijdag
    van publicatie.
  - EIA: wekelijkse voorraden van ruwe olie, benzine, destillaten en aardgas. Werkt alleen met een gratis
    `EIA_API_KEY`.
  - Wereldbank: lopende rekening en ruilvoet per land. Een jaarcijfer telt pas mee een half jaar na het jaar.
  - FRED: korte rentes (€STR, SOFR, SONIA, OECD) en reële effectieve wisselkoersen (BIS).
- **Termijnreeksen**: per grondstof de koers van het eerstvolgende contract (Yahoo `=F`) en dagelijks de
  eerste twee contracten die handelen. Daaruit volgt de helling van de termijncurve op jaarbasis
  (backwardation is positief). Over een jaar levert dezelfde opslag ook het basis-momentum.
- **20 grondstoffen** (`config/commodities.yaml`): 4 edelmetalen, 5 energie, 2 industriemetalen, 7 landbouw
  en 2 vee. Sjablonen Grondstof en Edelmetaal:
  - de trend wordt gemeten op het ETC in dollar, omdat dat een voor rollen gecorrigeerde reeks is
    (hoofdstuk 7); zonder ETC op het eerstvolgende contract, met een melding;
  - dollarindex en reële rente zijn voor alle grondstoffen gelijk, en tellen daarom tegenover hun eigen
    historie (`own_history_metrics`);
  - bij edelmetalen staat een melding als macro en koerstrend elkaar tegenspreken.
- **Productoordeel voor ETC's** (`config/etcs.csv`, 24 ETC's).
  - De onderzoeksagent controleerde elke waarde op 14 oktober bij de uitgever, justETF of een andere
    opgehaalde bron.
  - Gelijk gewogen: fysiek of termijncontracten, onderpand, kosten, rolopbrengst over 12 maanden (of
    tracking difference bij fysiek).
  - Productgates:
    - rolverlies slechter dan 10% per jaar: hoogstens C;
    - hefboom of invers: hoogstens D;
    - zonder onderpand: hoogstens B-.
  - Producten worden alleen met producten vergeleken.
  - Op de tab staat bij elke grondstof het best beoordeelde product. De grondstofpagina toont alle
    producten, de ETC-pagina het oordeel over de grondstof zelf.
- **15 valutaparen**, elk ook omgekeerd (30 in totaal), berekend uit de ECB-koersen. Sjabloon Valutapaar:
  - carry: renteverschil gedeeld door volatiliteit;
  - momentum over 3 tot 12 maanden;
  - waarde: reële effectieve koers tegenover het 10-jaarsgemiddelde;
  - macro: lopende rekening, ruilvoet en rentepad;
  - CFTC-positie;
  - de regel "carry halveren bij een volatiliteit of VIX boven het 80e percentiel";
  - de gates gestuurde valuta (CNY) en geen voordeel;
  - de horizon per pijler op de pagina.
- **Spiegeling**: het omgekeerde paar krijgt elke maatstaf met tegengesteld teken (de technische score:
  100 min). Beide richtingen staan in één vergelijkingsgroep, zodat de scores samen precies 100 zijn.
- **Grafieken**:
  - grondstoffen: Donchian 20/55, gemiddelden over 50/100/200 dagen, momentum over 12 maanden, ADX 14,
    ATR 20, een seizoenslijn over 15 jaar (alleen context) en een CFTC-index over 3 jaar;
  - valuta: EMA 50/200, momentum en de CFTC-index.
- Koersen in dollarcent (USX, zoals maïs en suiker) worden naar dollar omgerekend.
- **Taak `commodities`** (werkdagen 22:00 UTC).
- **Modelversie 0.5.0**: `own_history_metrics`, `params.commodities` en `params.fx`. De reële rente staat
  nu als verhouding (0,029) in plaats van procent; dat geldt ook voor Bitcoin.

### Acceptatie (live gemeten op 14 oktober 2026, peildatum 13 oktober)

- **Elke grondstof toont een oordeel over de grondstof en over het product:** 20 van 20.
  - Elke grondstof heeft minstens één beoordeeld ETC: 23 met een productoordeel, 1 voorlopig (Heating Oil,
    te dun verhandeld voor een rolopbrengst).
  - De rolopbrengst laat de bekende patronen zien: aardgas −26,8% (contango), maïs, katoen en tarwe onder
    −10% (productgate geraakt), Brent en WTI sterk positief (backwardation, de termijncurve loopt nu 12%
    per jaar af).
- **EUR/USD en USD/EUR zijn elkaars spiegelbeeld:** EUR/USD D (36,9) en USD/EUR B- (63,1). Over alle
  15 paren is de grootste afwijking van "samen 100" 0,00000000000001 punt. Getest per paar en van begin
  tot eind.
- `verify`: 771 van 771 grades zijn exact te herberekenen.
- Tests: 249 voor de rekenserver en 14 voor de webinterface.

### Keuzes en afwijkingen

- **Geen EIA-sleutel:** de pijler Fundamentals (voorraden) is voor energie nog leeg. De adapter is klaar;
  vul `EIA_API_KEY` in.
- **Eurozone bij de Wereldbank:** geen cijfers voor de eurozone als geheel. Bij EUR-paren ontbreken
  lopende rekening en ruilvoet; het rentepad telt wel.
- **Edelmetalen:** aankopen door centrale banken en ETF-stromen hebben geen gratis bron. De pijler Vraag
  blijft leeg, waardoor de datadekking op 75% uitkomt.
- **Basis-momentum** vraagt een jaar historie van het tweede contract. Die wordt vanaf nu dagelijks
  opgeslagen; tot dan is de pijler leeg (5%).
- **Termijncurve:** Yahoo geeft geen gratis curve met historie. De app slaat daarom elke dag de eerste
  twee contracten op en bouwt de curve zelf op.
- **ETC-gegevens:** de WisdomTree-site weigert geautomatiseerde aanvragen.
  - Hun kosten (0,54%) komen van twee onafhankelijke bronnen; justETF noemt 0,49%.
  - Bij Xetra-Gold zijn de kosten leeg gelaten: formeel 0%, maar via de effectenrekening betaal je 0,025%
    bewaarloon per maand.
  - Nikkel en zink zijn weggelaten: Yahoo heeft geen termijnreeks van de LME.
- **Brent en WTI:** de rolopbrengst van +55% en +40% over 12 maanden is groot. De meting is consistent:
  het ETC steeg 98%, het eerstvolgende contract 58%, met een sterk afdalende termijncurve tijdens de
  prijspiek van maart. Controleer dit gerust tegen de factsheet.
- **Goud en zilver** krijgen een F: ze staan 21% en 49% onder hun top van dit jaar (de trend is zwak) en de
  reële rente staat hoog tegenover de eigen historie.

## Fase 5 – ETF's, obligaties, indices en marktregime (2026-10-14)

### Gebouwd

- **Indices** (`config/indices.yaml`): 17 wereldwijde indices.
  - Koersen van Yahoo in de eigen valuta.
  - De euro-omrekening werkt nu voor elke valuta die de ECB publiceert (migratie `0007`; INR toegevoegd).
  - Sjabloon Index, vergeleken met de eigen historie:
    - trend: de technische score, met MSCI World als vergelijking;
    - macro: het marktregime en de rentecurve (VS via FRED, eurozone via de ECB);
    - marktbreedte: deel van de aandelen boven het 200-daags gemiddelde, alleen waar de app de leden
      volgt (S&P 500 met de gevolgde VS-aandelen, AEX);
    - volatiliteit tegenover de eigen historie.
- **Marktregime** (tabel `market_regime`, alleen toevoegen): per dag de stand en de drie invoeren.
  - De drie invoeren: MSCI World tegen zijn 10-maandsgemiddelde, de renteopslag op high-yield-obligaties
    (FRED) en de VIX, de laatste twee tegenover hun eigen historie.
  - Elke invoer stemt +1, 0 of −1, op de afgesloten week. Een som van 2 of hoger is risico aan, −2 of lager
    risico uit.
  - Opgeslagen van 2010 tot vandaag: 6.131 dagen.
  - Koppeling met de andere sjablonen:
    - bij risico uit gaat de grade van aandelen en crypto (sjablonen met `regime_adjust`) één stapje omlaag,
      vóór de gates, zodat een gate altijd wint;
    - de maatstaf `regime_score` (Index en Bitcoin) volgt het regime;
    - het regime staat in de invoer van elke grade, zodat herberekenen exact blijft.
  - Instelbaar in `model.yaml` onder `regime`.
- **ETF's**: 37 UCITS-ETF's op 9 indices.
  - De kenmerken staan in het zelf bijgehouden bestand `config/etfs.csv`: kosten, domicilie, replicatie,
    uitlenen, uitkeringsbeleid, start, fondsomvang en aantal aandelen in de index. Elke waarde is op
    14 oktober gecontroleerd op de pagina van de uitgever (anders justETF), met bron en datum per regel.
  - Tracking difference over 5 jaar (anders 3), in euro:
    - tegen de totaalrendementsreeks van de index waar die gratis is (S&P 500);
    - anders tegen de middelste ETF op dezelfde index.
  - Vergeleken worden alleen ETF's op dezelfde index. De ETF-pagina zet ze naast elkaar en splitst het
    verschil in kosten en de rest (belasting op dividend, uitlenen, replicatie).
  - De Timing van de onderliggende index staat er los bij.
  - De tien grootste posities komen maandelijks van Yahoo.
- **Obligatie-ETF's**: 15 fondsen in `config/bond_etfs.csv`, met rendement, duration, ratingverdeling en
  concentratie (iShares: 9 en 12 oktober; Vanguard: 31 augustus).
  - Verwacht nettorendement = rendement min verwacht verlies door wanbetaling (per rating, in `model.yaml`)
    min kosten.
  - Daarnaast: reële rente bij VS-staatsobligaties, opslag per eenheid wanbetalingsrisico en rendement per
    jaar duration.
  - Staatsrentes (VS en eurozone) staan ter vergelijking op de tab, zonder grade.
- **Interface**:
  - tab Indices met de stand van het regime, de drie invoeren en een balk per week;
  - tabs ETF's en Obligaties met filters op index en categorie;
  - kenmerken op de fondspagina;
  - grafiek met de indicatorset voor indices: 200 dagen, 10 maanden, daling vanaf de top, VIX, VIX tegen
    VIX over 3 maanden en marktbreedte;
  - weken met risico uit blauwgrijs gearceerd in elke grafiek.
- **Taak `markets`** (werkdagen 21:45 UTC), vóór de aandelenrun, zodat die het regime van de dag gebruikt.
- Nieuwe bronnen: ECB Data Portal (rentecurve) en Yahoo-fondsdata (posities).
- `python -m app.cli regime` vult ontbrekende dagen.
- **Modelversie 0.4.0**: regime-instellingen, ETF- en obligatie-instellingen, `params.indices`, en bij het
  sjabloon Obligatie lopende kosten als terugval voor tracking difference.

### Acceptatie (live gemeten op 14 oktober 2026, peildatum 13 oktober)

- **ETF's op dezelfde index staan naast elkaar, met een verklaarbaar verschil.**
  - Voorbeeld S&P 500, per jaar over 5 jaar, tegen de index met bruto dividend:
    - de synthetische Invesco-ETF: +0,08%;
    - de fysieke Ierse ETF's: −0,11% tot −0,12%.
  - Verklaring: de kosten zijn bijna gelijk (0,03 tot 0,07%). Het verschil is de 15% Amerikaanse
    bronbelasting op dividend, die een swap-ETF niet betaalt.
  - Bij MSCI World blijft de Luxemburgse swap-ETF van Amundi 0,30% achter, met 0,38% kosten.
  - De tabel op de ETF-pagina toont dit per fonds: tracking difference = kosten + rest.
- **Het regime staat per dag in de database, met zijn drie invoeren.**
  - 6.131 dagen sinds 2010: 3.345 risico aan, 1.841 neutraal, 637 risico uit, en 308 zonder stand (te
    weinig historie in 2010).
  - Risico uit valt op de bekende momenten: najaar 2011, nazomer 2015, maart 2020, 2022 en april 2025.
  - Vandaag: risico aan (wereldindex boven het gemiddelde +1, VIX laag +1, high-yield-opslag neutraal 0).
- Grades op 13 oktober:
  - indices: 10 met grade en 7 voorlopig (buiten de VS en de eurozone ontbreekt de rentecurve);
  - ETF's: alle 37 met grade;
  - obligatie-ETF's: 14 met grade (de geldmarkt-ETF heeft te weinig gegevens).
- `verify`: 462 van 462 grades zijn exact te herberekenen.
- Tests: 242 voor de rekenserver en 14 voor de webinterface.

### Keuzes en afwijkingen

- **Alleen risico uit verschuift de grade** (één stapje omlaag); risico aan doet niets. De prompt zegt
  "hoogstens één stap" zonder richting. Deze voorzichtige keuze staat in `model.yaml`
  (`regime.grade_shift`) en is daar om te zetten.
- **High-yield-opslag:** FRED levert die maar drie jaar terug (licentie van ICE). Tot oktober 2024 stemmen
  daarom alleen de wereldindex en de VIX. Met twee stemmen moeten beide dezelfde kant op wijzen voor risico
  aan of risico uit.
- **Waardering van indices** (winstrendement, CAPE): geen gratis bron. Die pijler blijft leeg en de
  datadekking van indices is daardoor hooguit 75%.
- **ETF-gegevens:** lege cellen zijn niet geverifieerd (er wordt niets bedacht).
  - Fondsomvang ontbreekt bij Invesco en UBS (hun sites weigeren geautomatiseerde aanvragen). De
    omvang-gate staat daar op *niet te controleren*.
  - Het aantal aandelen ontbreekt voor ACWI, Nasdaq-100 en AEX.
- **Plausibiliteitsgrens:** wijkt een indexfonds meer dan 1,5% per jaar af, dan telt de tracking difference
  niet en tellen de kosten. Dat gebeurde bij Amundi Euro Stoxx 50 (V50A): de Yahoo-reeks liep 3,5% per jaar
  voor op de andere Euro Stoxx 50-ETF's, wat voor een indexfonds niet geloofwaardig is.
- **Amundi Core MSCI Europe** volgde tot voor kort een andere (ESG-)index. Zijn achterstand van 0,8% per
  jaar is echte geschiedenis van dit product en telt mee.
- **Posities van Yahoo:** bij deze run weigerde Yahoo de sessie (HTTP 429). De taak stopt dan meteen en
  probeert het de volgende werkdag opnieuw.
- **Verwacht verlies per rating** is een eigen benadering: langjarige gemiddelde wanbetaling (Moody's)
  maal 60% verlies; obligaties zonder rating tellen als BBB. Het staat in `model.yaml` onder `bond`.
- **Inflatiegekoppelde fondsen:** het rendement is dat van de uitgever (met de inflatieaanname erin).
  Hun reële rente (2,77% en 1,90%) staat in het bestand, maar wordt nog niet apart gebruikt.

## Fase 4 – Aandelen (2026-10-12)

### Gebouwd

- **Databronnen** (`config/providers.yaml`, `config/stocks.yaml`):
  - **SEC EDGAR**: bedrijfslijst, registratiegegevens (SIC-code, land, publicaties) en `companyfacts`.
  - **Tiingo** voor VS-koersen zodra `TIINGO_API_KEY` is ingevuld; tot dan **Yahoo Finance** (de
    noodoplossing uit de prompt).
  - **EODHD** als optionele, betaalde bron: alleen actief met `EODHD_API_KEY`.
  - **OpenFIGI** voor ISIN naar ticker.
- **Koersen** worden opgeslagen gecorrigeerd voor dividend en splitsingen (voor grafiek, momentum, bèta en
  volatiliteit). Daarnaast wordt de slotkoers zoals verhandeld bewaard (voor de beurswaarde).
  - Elke run leest de laatste tien dagen opnieuw. Verandert een oude gecorrigeerde koers, dan was er een
    dividend of splitsing, en wordt de hele reeks opnieuw opgehaald.
- **Fundamentele feiten met `available_at`** = de publicatiedatum bij SEC.
  - Per financiële post staat een lijst XBRL-begrippen op volgorde van voorkeur; per periode wordt het
    eerste begrip gebruikt dat een waarde heeft (bedrijven wisselen van begrip).
  - Elke gepubliceerde versie blijft bewaard. Een herziening staat naast het origineel vanaf de dag dat
    hij gepubliceerd werd.
  - Kwartaalcijfers worden omgerekend naar de laatste twaalf maanden.
- **Lijsten**:
  - VS: de grootste SEC-registranten met een 10-K, gerangschikt op beurswaarde (verwaterd aantal aandelen
    maal de slotkoers); de top 50 staat in de lijst.
  - AEX: de 25 fondsen met ISIN uit `config/stocks.yaml`.
  - Benchmarks: S&P 500 en AEX.
- **Sectorindeling** uit de SIC-code (`config/model/assignment.yaml`), met handmatige uitzonderingen per
  aandeel. Sjabloon:
  - banken (SIC 6020–6036, 6111, 6199, 6211) en verzekeraars (risicodragers) → **Bank of verzekeraar**;
  - SIC 6798 → **Vastgoedfonds (REIT)**;
  - de rest → **Aandeel algemeen**.
  - Vergelijking binnen de sector; een sector met minder dan acht aandelen valt terug op het hele sjabloon.
- **Maatstaven**: brutowinst/activa, ROIC, margestabiliteit, Piotroski F, accruals, balansgroei,
  EBIT/EV, vrije-kasstroomrendement, aandeelhoudersrendement, bèta, volatiliteit, nettoschuld/EBITDA,
  rentedekking, Altman Z, Beneish M, omzet- en winstgroei en groeibestendigheid. Voor banken: ROTCE,
  rentemarge, kosten/baten, leningen/deposito's, winst- en dividendrendement, en koers/tastbare
  boekwaarde afgezet tegen ROTCE (een lijn door de vergelijkingsgroep).
  - Waarderingen tellen voor 20% mee ten opzichte van de eigen historie van drie jaar. Die historie wordt
    dag voor dag gereconstrueerd met alleen de cijfers die op die dag gepubliceerd waren.
- **Technische score voor aandelen** met eigen parameters (`technical.yaml`, `params.stocks`):
  - in de eigen valuta, met 252 handelsdagen per jaar;
  - vergeleken met de index van de eigen markt.
- **Grafiek voor aandelen** in eigen valuta, met de indicatorset uit hoofdstuk 7:
  - in de score: 50/200 dagen, 10/40 weken, momentum 12-1, afstand tot de 52-weekshoogte en sterkte ten
    opzichte van de index;
  - context: RSI 14, MACD, volume ten opzichte van het gemiddelde, ATR en Bollinger.
- **Taak `stocks`**: werkdagen 22:30 UTC, daarna de grades van de laatste beursdag.
- **Interface**:
  - tab Aandelen met de weergaven VS en AEX, VS top 50, AEX en Alle gevolgde, en filters op sector en
    land;
  - op de assetpagina sector, land en opmerkingen bij de data;
  - zoeken op ISIN (OpenFIGI) en op VS-ticker of -naam (SEC);
  - een VS-aandeel buiten de lijst ophalen en beoordelen op verzoek (3M: 21 seconden).
- **Modelversie 0.3.0**:
  - toewijzing en sectoren voor aandelen;
  - `days_per_year` bij de technische parameters;
  - de grades voor crypto zijn identiek aan die van 0.2.0 (gecontroleerd op peildatum 10 oktober).

### Acceptatie (live gemeten op 12 oktober 2026, peildatum 9 oktober)

- **50 VS-aandelen hebben een volledige grade:** 49 van de top 50 hebben een volledige grade.
  - **GE Aerospace** staat op *voorlopig*: datadekking 58,5%, net onder de 60%. GE rapporteert bij SEC
    geen rentelasten en geen brutowinst.
  - Over alle 104 gevolgde aandelen: 81 met een grade, 4 voorlopig en 19 zonder grade (zie hieronder).
- **Een bank loopt aantoonbaar door het banksjabloon:** JPMorgan (SIC 6021) krijgt het sjabloon Bank of
  verzekeraar met het label bank.
  - Op de pagina: ROTCE 19,8%, rentemarge 1,99%, kosten/baten 51,4%, leningen/deposito's 55,9%, en
    koers/tastbare boekwaarde ten opzichte van de lijn door tien financials.
  - De CET1-gate staat op *niet te controleren*: CET1 staat niet in de XBRL-cijfers.
  - Bank of America, Wells Fargo, Citigroup, Goldman Sachs, Morgan Stanley, Schwab en American Express
    gaan ook door het banksjabloon; ING en ABN AMRO via de handmatige toewijzing.
  - Getest in `test_stocks.py`.
- **Beneish en Altman kloppen met een handberekend voorbeeld** (`test_fundamentals.py`; de berekening
  staat stap voor stap in het commentaar):
  - Altman Z = 3,295 (gezond) en 0,466 (in nood, gate geraakt);
  - Beneish M = −1,7813, net onder de drempel, en −1,6877 bij meer winst zonder kasstroom (gate geraakt,
    hoogstens C).
- `verify`: 165 van 165 opgeslagen grades zijn exact te herberekenen, aandelen inbegrepen.
- Tests: 226 voor de rekenserver en 13 voor de webinterface.

### Keuzes en afwijkingen

- **Geen verzonnen cijfers.** Waar een gratis bron ontbreekt, blijft de maatstaf leeg en daalt de
  datadekking:
  - geen analistenverwachtingen, dus geen winstrevisies, verwachte winst of winstverrassing;
  - geen short interest;
  - geen CET1, probleemleningen, Solvency II of combined ratio;
  - voor REITs geen FFO/AFFO, bezetting of huurgroei. Welltower krijgt daarom geen grade (15%).
  - Aankopen door bestuurders (SEC Form 4) zijn wel gratis, maar nog niet gebouwd.
- **Europese aandelen zonder SEC-registratie** (17 van de 25 AEX-fondsen) hebben geen gratis bron voor
  jaarcijfers. Ze krijgen koersen en een technische score, maar geen grade.
  - De acht met SEC-registratie (ASML, ING, Philips, RELX, Shell, Unilever, Aegon, ArcelorMittal) krijgen
    een grade op basis van hun jaarverslag (20-F); bij Aegon en ING is die voorlopig.
  - Dit is het punt waarvoor EODHD bedoeld is.
- **Visa en Berkshire Hathaway** geven bij SEC geen aantal aandelen voor alle klassen samen. Daardoor:
  - geen beurswaarde, en ze staan buiten de rangschikking op beurswaarde;
  - Visa wordt voorlopig beoordeeld, Berkshire niet.
  - Oplossing: `set-fact v shares_outstanding <aantal>`.
- **Conventies** (in `fundamentals.py`):
  - Een balanspost die twee jaar niet gerapporteerd is, telt als nul; XBRL laat posten weg die een bedrijf
    niet heeft.
  - EBIT = winst voor belasting plus rentelasten als er geen bedrijfsresultaat is gerapporteerd.
  - Bij Beneish tellen de afschrijvings- en verkoopkostenindex als 1 als die posten ontbreken.
  - Het aantal aandelen wordt gecontroleerd met nettowinst gedeeld door winst per aandeel. Dat vangt
    McDonald's op, dat aandelen in miljoenen rapporteert.
- **Beneish bij snelle groeiers:** de gate raakt Nvidia, Broadcom, Micron, Lam Research en Sandisk.
  - Hun hoge omzetgroei (SGI) en hogere marges duwen de M-score omhoog; dat is een bekende zwakte van het
    model bij hypergroei.
  - De gate werkt zoals de prompt hem beschrijft. Een aanpassing is een modelkeuze voor jou.
- **Verzekeraars** zijn beperkt tot risicodragers. Zorgverzekeraars (UnitedHealth, SIC 6324) en
  vermogensbeheerders (BlackRock) worden als algemeen aandeel beoordeeld; anders zouden ze vrijwel
  zonder maatstaven blijven.
- **De AEX-samenstelling** is die van 31 december 2024; latere indexherzieningen zijn niet bevestigd.
  - Werk `config/stocks.yaml` bij na elke herziening (mogelijk zijn Euronext en CVC erbij gekomen).
  - De nieuwe ISIN van Unilever na de afsplitsing kon niet worden bevestigd en staat leeg.
- **SEC vraagt een contactadres** in de User-Agent. Vul in `.env` bij `SEC_USER_AGENT` je eigen
  e-mailadres in. Tijdens de bouw is een neutraal voorbeeldadres gebruikt.
- **Ruimte:** de SEC-cijfers van 85 bedrijven en de koersgeschiedenis sinds 2009 zijn samen 625.000 rijen
  (271 MB in `fundamental_fact`). SEC-antwoorden worden 45 dagen bewaard.

## Fase 3 – Interface en grafiek (2026-10-11)

### Gebouwd

- **Ranglijst** op elke kolom sorteerbaar en filterbaar (tekst, minimumwaarden, grade "X of beter",
  sjabloon, gewijzigde grade, gedaald in 90 dagen), met een mini-grafiek van 90 dagen en eigen weergaven
  voor de top 50, stablecoins en alle gevolgde munten. Elke naam linkt naar de assetpagina.
- **Assetpagina** met de zeven onderdelen uit hoofdstuk 2:
  1. de kop met grade, bandbreedte, score, Kwaliteit, Timing, datadekking, modelversie, peildatum,
     horizon, koers in euro en in de oorspronkelijke valuta, en de grade ten opzichte van Bitcoin;
  2. pijlerbalken met gewicht en bijdrage;
  3. per maatstaf de waarde, de positie in de vergelijkingsgroep, de richting en de bron met datum;
  4. de gates met hun status;
  5. de toelichting;
  6. de grafiek;
  7. de geschiedenis.
- **Toelichting** als vaste sjabloontekst: 120 tot 200 woorden bij een grade, met de drie sterkste en drie
  zwakste punten, de gates en wat de grade zou veranderen. Elk getal komt uit de snapshot (getest). Dit
  is ook de terugvaltekst voor de taalmodeltoelichting uit fase 7.
- **Grafiek** met Lightweight Charts 5.2.1:
  - kaarsen met volume en gemiddelden;
  - hooguit twee indicatorvensters, afgedwongen;
  - dag, week en maand, met lineaire of logaritmische schaal;
  - kruisdraad met een legenda van alle waarden;
  - vergelijken met Bitcoin;
  - gradewijzigingen als markering en gate-zones als rode arcering;
  - de indicatorset voor crypto uit hoofdstuk 7, aan en uit per knop; je eigen keuze wordt onthouden;
  - een trendlijn-tekenhulp, naar de officiële plugin;
  - de TradingView-vermelding staat aan;
  - een optionele tab met de gratis TradingView-widget.
- **Indicatoren op de server** (TA-Lib): gemiddelden over 50 en 200 dagen en over 20 en 200 weken, EMA
  over 21 weken, Mayer-multiple, sterkte ten opzichte van Bitcoin, RSI 14 op weekbasis, gerealiseerde
  volatiliteit over 30 en 90 dagen, ATR in procenten, funding en open interest. Ze worden op dagdata
  berekend en per week of maand bemonsterd, zodat een gemiddelde in elke weergave hetzelfde betekent.
- **Zoeken** in de kop: op naam, ticker of contractadres (EVM en Solana); ISIN volgt met fase 4 en 5.
  Een munt buiten de lijsten wordt op verzoek opgehaald en beoordeeld, in circa een halve minuut. Staat
  een munt in geen enkele bron, dan staat dat er en verschijnt er geen grade.
- **Volglijst** (migratie `0005`): volgen vanaf de assetpagina, met een eigen ranglijst op de tab
  Volglijst.
- Woordenlijst-tooltips op elke kolom, pijler, maatstaf en elk begrip.

### Acceptatie

- **Van ranglijst naar assetpagina en per pijler zien welke maatstaf de score bepaalt:** gehaald. Een
  klik op de naam opent de pagina; per pijler staat bij elke maatstaf de waarde, de score, het percentiel
  in de groep (met de groepsgrootte) en de bron met datum.
- **De grafiek schuift en zoomt vloeiend op de Synology:** de grafiek wordt in de browser van je Mac of
  telefoon getekend; de NAS levert alleen de data.
  - Gemeten in headless Chromium zonder grafische kaart: 57 beelden per seconde, en 33 met een 4×
    vertraagde processor (vóór de optimalisaties 18).
  - De dagweergave toont daarom standaard de laatste twee jaar; verder terug kun je schuiven.
  - De server levert de daggrafiek van Bitcoin (9 jaar) gecomprimeerd in 378 KB. Een eerste opvraag
    duurt hier 0,6 s; op de Celeron reken ik op ongeveer 2 s. Daarna komt de grafiek 15 minuten uit
    het geheugen (hier 14 ms).
  - Een echte meting op de NAS staat nog open.
- Tests: 194 voor de rekenserver (indicatoren, toelichting, API), 12 voor de webinterface (sorteren,
  filteren, opmaak).

### Opgemerkt

- Bonk (opgehaald via zoeken) krijgt F: volgens RugCheck is maar circa 15% van de liquiditeit verbrand of
  vergrendeld, en de prompt zegt dan F. Bij grote, oude memecoins met veel liquiditeitsverschaffers is dat
  streng. De drempel staat in `config/model/templates/crypto_memecoin.yaml` (`lp_locked_min_pct`); een
  wijziging is een nieuwe modelversie.

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
