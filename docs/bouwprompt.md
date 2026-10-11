# Bouwprompt: Asset Grading App

Oct 11, 2026 · @Patrick

Plak deze pagina vanaf hoofdstuk 1 als opdracht in Claude Code: de agent bouwt de app in elf fases en stopt na elke fase voor jouw akkoord.

## Vooraf: keuzes en kanttekeningen

Dit deel is voor jou, niet voor de bouwagent. Het onderzoek leverde vijf keuzes op die in de prompt zijn verwerkt.

| Onderwerp | Keuze | Waarom |
| --- | --- | --- |
| Grafiek | TradingView Lightweight Charts v5, indicatoren zelf berekend | Gratis (Apache 2.0). De volledige TradingView-bibliotheek mag niet voor privégebruik; de gratis widget kan jouw grades niet tonen. |
| Grade | Score 0–100 plus letter, gesplitst in Kwaliteit en Timing | Eén gemengd cijfer slaat om bij elke koersbeweging. Weiss Ratings verlaagde daarom in 2019 het gewicht van koersgedrag. |
| Model | Per assetklasse een eigen sjabloon, 16 in totaal | Een bank, een REIT, Bitcoin en een memecoin zijn niet met dezelfde maatstaven te beoordelen. |
| Data | Gratis starten, later circa $20–80 per maand (EODHD) | Voor Europese aandelen en UCITS-ETF's bestaat geen betrouwbare gratis bron. |
| Zelflerend | De app meet maandelijks en doet per kwartaal een voorstel; jij keurt goed | Automatisch bijsturen op weinig data leert vooral ruis aan. |

Drie kanttekeningen bij je verwachtingen:

1. **De voorspelkracht is klein.** Goede professionele aandelenmodellen halen een rangcorrelatie tussen score en later rendement van ongeveer 0,02 tot 0,06 (0 is geen verband, 1 is perfect). Een A die daalt is dus normaal. De grade is een ranglijst en zeef, geen voorspelling.
2. **Leren van eigen uitkomsten gaat traag.** Met 50 assets per maand duurt het ongeveer drie jaar voordat je statistisch kunt zien of een model werkt. Daarom leert de app vooral van een historische terugtest en bewaakt hij zichzelf met live data.
3. **Privégebruik valt buiten de regels, publiceren niet.** Een gepubliceerde letter-grade op een aandeel of ETF past plausibel binnen de definitie van een beleggingsaanbeveling (Marktmisbruikverordening), met eisen aan methode, bronnen en eigen posities. Dit is een samenvatting van AFM- en ESMA-bronnen, geen juridisch advies.

Niet alles kon ik op officiële pagina's bevestigen: de prijzen van dataleveranciers, de bereikbaarheid van Binance- en Bybit-futuresdata vanaf een Nederlands IP en de fiscale behandeling van Nederlandse fondsen. De prompt laat de agent die punten tijdens de bouw controleren.

## 1. Rol en werkwijze

Je bouwt een privé-webapp die beleggingsassets beoordeelt met een onderbouwde grade. Je bent de enige ontwikkelaar; de eigenaar is één Nederlandse belegger die in euro's rekent en geen programmeur is.

- **Bouw in fases.** Hoofdstuk 10 beschrijft fase 0 tot en met 10. Voer één fase per keer uit, toon aan dat de acceptatiecriteria gehaald zijn en stop dan voor akkoord.
- **Begin elke fase met een kort plan.** Noem de bestanden die je maakt of wijzigt en de aannames die je doet. Stel alleen een vraag als een keuze later duur is om terug te draaien.
- **Controleer externe feiten zelf.** API-limieten, prijzen, eindpunten en bibliotheekversies in deze prompt zijn van oktober 2026. Lees de officiële documentatie voordat je ertegen bouwt en meld afwijkingen.
- **Verzin nooit data.** Een ontbrekende waarde blijft leeg en verlaagt de datadekking van de grade. Geen voorbeeldcijfers in productiecode.
- **Test wat rekent.** Elke indicator, elke pijlerscore en elke gate krijgt een unittest met vaste invoer en vaste uitkomst.
- **Houd het model in configuratie.** Pijlers, gewichten, drempels en gates staan in versiebeheerde YAML-bestanden, niet in code. Elke wijziging levert een nieuwe modelversie op.
- **Taal.** De interface is Nederlands. Code, commits en databasevelden zijn Engels. Elk vakwoord in de interface krijgt een tooltip met uitleg in gewone taal, gevoed uit één woordenlijstbestand.
- **Documenteer kort.** Houd een README bij met starten, configureren en back-up, en een CHANGELOG per fase.

## 2. Product

De app toont per assetklasse een ranglijst met grades en per asset een pagina die uitlegt waarom de grade zo is.

### Tabs en standaardlijsten

| Tab | Standaardlijst | Opmerking |
| --- | --- | --- |
| Crypto | Top 50 op marktkapitalisatie | Zonder stablecoins en wrapped of staked varianten; die staan in eigen filters |
| Aandelen | Top 50 VS op marktkapitalisatie plus de 25 AEX-fondsen | Filter op sector en land |
| ETF's | Circa 40 UCITS-ETF's, gegroepeerd per index | Vergelijk alleen ETF's op dezelfde index met elkaar |
| Grondstoffen | Circa 20: edelmetalen, energie, industriemetalen, landbouw | Toon naast de grondstof het product waarmee je hem kunt kopen |
| Valuta | Circa 15 paren: EUR-paren en de grote dollarparen | Score is een richtingsscore, geen kwaliteitsoordeel |
| Obligaties | Circa 15 obligatie-ETF's plus staatsrentes |  |
| Indices | Circa 15 wereldwijde indices | Dient ook als marktregime voor de andere tabs |
| Volglijst | Eigen selectie over alle klassen |  |
| Model | Prestaties van het gradingmodel zelf | Zie hoofdstuk 8 |

Elke lijst is instelbaar op top 25, 50 of 100 en staat in een configuratiebestand.

### Ranglijst

Kolommen: rang, naam, ticker, eindgrade, score, Kwaliteit, Timing, verandering sinds vorige maand, datadekking, koers in euro, mini-grafiek van 90 dagen, sterkste pluspunt en zwaarste minpunt in vijf woorden. Sorteerbaar en filterbaar op elke kolom.

### Zoeken

Eén zoekveld accepteert naam, ticker, ISIN of contractadres. Een asset buiten de lijsten wordt op verzoek opgehaald, beoordeeld en kan aan de volglijst worden toegevoegd. Staat een asset in geen enkele bron, zeg dat dan en toon geen grade.

### Assetpagina

1. **Kop:** eindgrade, score, Kwaliteit en Timing apart, datadekking, modelversie, peildatum en horizon.
2. **Pijlers:** per pijler een balk met score, gewicht en bijdrage aan het totaal.
3. **Onderbouwing per maatstaf:** waarde, positie ten opzichte van vergelijkbare assets, of hoger of lager beter is, en bron met datum.
4. **Gates:** welke harde regels de grade begrenzen en waarom.
5. **Toelichting:** een Nederlandse tekst van 120 tot 200 woorden met de drie sterkste en drie zwakste punten en wat de grade zou veranderen.
6. **Grafiek:** zie hoofdstuk 7, met de momenten waarop de grade wijzigde als markering.
7. **Geschiedenis:** het verloop van score en grade in de tijd.

## 3. Architectuur en stack

De app draait als drie Docker-containers: webinterface, rekenserver en database. Ontwikkeling gebeurt op een Mac; het doel is een Synology DS920+.

| Laag | Keuze | Reden |
| --- | --- | --- |
| Interface | Next.js met React en TypeScript, standalone-uitvoer | Snel, goede tabellen, past bij de grafiekbibliotheek |
| Grafiek | TradingView Lightweight Charts 5.x met een eigen dunne React-wrapper | Zie hoofdstuk 7 |
| Rekenserver | Python met FastAPI, pandas en NumPy | Alle berekeningen en de API |
| Indicatoren | TA-Lib 0.8.x (kant-en-klare wheels) plus eigen functies | pandas-ta is onbetrouwbaar onderhouden |
| Planner | APScheduler in het serverproces | Celery met Redis is te zwaar voor één gebruiker |
| Database | PostgreSQL | Dagdata past ruim; TimescaleDB is pas nodig bij intraday |

### Eisen aan de Synology

- De Celeron J4125 heeft geen AVX of AVX2. Gebruik bij Polars de variant `polars[rtcompat]` en vermijd TensorFlow en MongoDB.
- Bouw images op de Mac met `docker buildx --platform linux/amd64` en zet ze daarna op de NAS. Draai `next build` niet op de NAS.
- Beperk PostgreSQL `shared_buffers` tot 512 MB à 1 GB en draai hooguit drie werkprocessen.
- Test in fase 0 een lege container van elk image op de NAS zelf; de kernel van DSM is oud.

### Ontwerpregels

1. **De interface praat nooit met een dataleverancier.** Alles komt uit de eigen database.
2. **Elke leverancier zit achter een adapter** met dezelfde functies (`get_bars`, `get_fundamentals`, `get_meta`), een eigen snelheidslimiet en een maandbudget. Per asset geldt een voorkeursvolgorde met terugval.
3. **Alles is tijdvast.** Elke waarde krijgt `available_at`: het moment waarop hij publiek werd, niet het einde van de verslagperiode. Herziene cijfers overschrijven nooit de oude.
4. **De grade is een zuivere functie** van modelconfiguratie en invoer. Dezelfde invoer geeft altijd dezelfde grade, zodat de geschiedenis onder elke modelversie opnieuw te berekenen is.
5. **Snapshots zijn onveranderlijk.** De tabel `grade_snapshot` is alleen-toevoegen.
6. **Tijd is UTC, geld is euro.** Reken koersen om met ECB-referentiekoersen en toon de oorspronkelijke valuta erbij.
7. **Geheimen staan in `.env`.** De app is alleen op het thuisnetwerk bereikbaar; voeg een eenvoudige inlog toe.

### Kerntabellen

`asset`, `asset_alias`, `universe_membership`, `price_bar`, `fundamental_fact`, `metric_value`, `model_version`, `grade_snapshot`, `forward_label`, `evaluation_report`, `change_request`, `provider_call_log`, `llm_call_log`.

Elke rij met marktdata bevat `source` en `fetched_at`. Maak elke nacht een `pg_dump` naar een map buiten de container.

## 4. Databronnen

Bouw eerst op gratis bronnen en maak elke bron vervangbaar. Het grootste gat van de gratis opzet is Europese koers- en fundamentele data; daar hoort de betaalde upgrade.

| Gebied | Gratis basis | Limiet of aandachtspunt | Betaalde upgrade |
| --- | --- | --- | --- |
| Crypto koersen | CCXT met Binance spot (`data-api.binance.vision`) en Coinbase | Geen sleutel nodig |  |
| Crypto marktdata | CoinGecko Demo | 10.000 calls per maand, 100 per minuut, 1 jaar historie, bronvermelding verplicht | CoinGecko Basic, $35 per maand |
| Crypto fundamenteel | DefiLlama gratis API: TVL, fees, omzet | Unlocks en hacks zitten alleen in Pro ($300 per maand) | Tokenomist Pro, $69 per maand |
| On-chain | Coin Metrics Community | 10 verzoeken per 6 seconden, niet-commerciële licentie |  |
| Derivaten | Bybit en Binance: funding en open interest | Historie is kort, dus dagelijks zelf archiveren; test bereikbaarheid vanaf de NAS |  |
| Solana-tokens | DexScreener en RugCheck | Limieten niet bevestigd | Birdeye Lite, $39 per maand |
| Aandelen VS koersen | Tiingo gratis | 1.000 calls per dag, 500 tickers per maand | Tiingo Power, $30 per maand |
| Aandelen VS fundamenteel | SEC EDGAR `companyfacts` | Gratis, maximaal 10 verzoeken per seconde, User-Agent verplicht |  |
| Europese aandelen en ETF's | yfinance als noodoplossing | Onofficieel, wordt geregeld geblokkeerd | EODHD All-World $19,99 plus Fundamentals $59,99 per maand |
| Tickerkoppeling | OpenFIGI | 25 verzoeken per minuut zonder sleutel |  |
| Macro en rente | FRED, ECB Data Portal, US Treasury | FRED vereist een sleutel en een vermelding in de app |  |
| Wisselkoersen | Frankfurter (ECB-koersen) | Zelf te hosten in Docker |  |
| Positionering | CFTC Commitments of Traders | Wekelijks |  |
| Energie | EIA | Gratis sleutel |  |
| Grondstofprijzen | Wereldbank Pink Sheet | Maandelijks Excel-bestand |  |
| Nieuws | Marketaux gratis | 100 verzoeken per dag |  |

### Bekende gaten

- **Winstverwachtingen van analisten.** Op geen van de gecontroleerde prijspagina's gevonden. Controleer FMP en EODHD bij de bouw; anders blijft de pijler Revisies leeg.
- **Termijncurves van grondstoffen.** Geen gratis bron bevestigd. Gebruik eerstvolgende contracten via yfinance (`=F`) en de rolopbrengst van ETC's als benadering.
- **Unlock-schema's van tokens.** Start met marktkapitalisatie gedeeld door FDV uit CoinGecko en een handmatig invulveld; sluit later een betaalde bron aan.
- **ETF-kenmerken.** justETF heeft geen officiële API. Haal kosten, domicilie en replicatie uit EODHD of uit een eigen onderhouden CSV-bestand.

### Verversen

- Draai per assetklasse één nachtelijke run na de slotkoers; crypto om 00:05 UTC.
- Werk bij vanaf de laatst opgeslagen datum. Haal de hele historie van een aandeel opnieuw op na een splitsing of dividend, omdat gecorrigeerde koersen dan verschuiven.
- Bewaar het ruwe antwoord naast de genormaliseerde rij.
- Toon op een pagina Bronnen de verplichte vermeldingen: CoinGecko, TradingView, FRED en alternative.me.
- De licenties van vrijwel alle bronnen gelden voor persoonlijk gebruik. Bouw geen functie om data of grades publiek te delen.

## 5. Gradingmodel: algemene regels

Elke asset krijgt een score van 0 tot 100 en een letter van A+ tot F, opgebouwd uit gewogen pijlers en begrensd door harde regels. De horizon is 6 tot 12 maanden, tenzij een sjabloon anders zegt.

### Van maatstaf naar score

1. **Rangschik binnen de vergelijkingsgroep.** Elke maatstaf wordt een percentiel van 0 tot 100 ten opzichte van vergelijkbare assets: de sector bij aandelen, het subtype bij crypto, dezelfde index bij ETF's.
2. **Kap uitschieters af** op het 5e en 95e percentiel voordat je rangschikt.
3. **Gebruik rendementen, geen multiples.** Winst gedeeld door koers en EBIT gedeeld door ondernemingswaarde blijven bruikbaar bij negatieve winst; koers-winstverhoudingen niet.
4. **Voeg bij waardering een absoluut deel toe.** 80% positie binnen de groep, 20% positie ten opzichte van de eigen historie. Anders lijkt een dure sector goedkoop.
5. **Pijlerscore** is het gemiddelde van de maatstaven in de pijler, elk even zwaar. Middel meerdere terugkijkperiodes in plaats van er één te kiezen.
6. **Eindscore** is het gewogen gemiddelde van de pijlers volgens hoofdstuk 6.

### Kwaliteit en Timing

Toon naast de eindscore twee deelscores. Kwaliteit bevat alle pijlers behalve trend en momentum. Timing is de technische score uit hoofdstuk 7. Zo ziet de gebruiker het verschil tussen een goede asset op een slecht moment en omgekeerd.

### Letterschaal

| Letter | Voorlopige ondergrens | Doelverdeling na ijking |
| --- | --- | --- |
| A | 75 | Beste 10% |
| B | 62 | Volgende 20% |
| C | 45 | Middelste 40% |
| D | 32 | Volgende 20% |
| F | 0 | Slechtste 10% |

Plus en min verdelen elke letter in drieën. Gemiddelden van percentielen klonteren rond 50; gebruik daarom de voorlopige grenzen tot fase 8 en ijk ze daarna per sjabloon op de doelverdeling in de terugtest. Leg de grenzen vast in de modelversie.

### Ontbrekende data

- Ontbreekt een pijler, herverdeel dan het gewicht over de rest en verlaag de datadekking met dat gewicht.
- Datadekking onder 60%: toon de grade grijs met het label voorlopig.
- Datadekking onder 40%: toon geen grade.

### Gates

Gates zijn harde regels die de grade begrenzen na de weging, bijvoorbeeld hoogstens C. Ze staan per sjabloon in hoofdstuk 6. Toon elke geraakte gate met reden op de assetpagina. Een gate wint altijd van de gewogen score.

### Stabiliteit en onzekerheid

- **Hysterese.** De letter wijzigt pas als de score de grens met minstens 2 punten passeert of er 5 handelsdagen overheen blijft.
- **Bandbreedte.** Bereken de score ook met elk gewicht 20% hoger en lager en toon het bereik, bijvoorbeeld B (B- tot B+).
- **Alleen afgesloten perioden.** Reken nooit op een lopende dag- of weekkoers.

### Marktregime

Bepaal dagelijks één van drie standen: risico aan, neutraal, risico uit. Gebruik drie invoeren: wereldindex boven of onder het 10-maandsgemiddelde, de renteopslag op high-yield-obligaties (FRED `BAMLH0A0HYM2`) en de VIX ten opzichte van de eigen historie. Het regime verschuift de grade van aandelen en crypto hoogstens één stap en past gewichten aan waar hoofdstuk 6 dat noemt. Het zet nooit een gate opzij.

### Woordkeus

Gebruik nergens kopen, verkopen of koersdoel. De grade is een rangorde binnen een assetklasse.

## 6. Pijlers en gewichten per assetklasse

Er zijn 16 sjablonen. De gewichten zijn startwaarden, afgeleid uit de literatuur; ze tellen per sjabloon op tot 100 en mogen alleen verschuiven via hoofdstuk 8.

### Toewijzing

| Tab | Sjabloon | Toewijzen op |
| --- | --- | --- |
| Aandelen | Aandeel algemeen, Bank of verzekeraar, Vastgoedfonds (REIT) | Sectorcode |
| ETF's | ETF | Producttype |
| Obligaties | Obligatie | Producttype |
| Indices | Index | Producttype |
| Crypto | Bitcoin, Platform (L1 en L2), DeFi-protocol, Utility (AI, DePIN en overig), Stablecoin, Memecoin, RWA-token | CoinGecko-categorie, handmatig te overschrijven |
| Grondstoffen | Grondstof, Edelmetaal | Producttype |
| Valuta | Valutapaar | Producttype |

### Aandeel algemeen

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Kwaliteit | 25 | Brutowinst gedeeld door activa, rendement op geïnvesteerd kapitaal, stabiliteit van marges, Piotroski F-score, lage accruals, lage balansgroei |
| Waarde | 20 | EBIT gedeeld door ondernemingswaarde, vrije-kasstroomrendement, verwachte winst gedeeld door koers, aandeelhoudersrendement (dividend plus inkoop min uitgifte) |
| Momentum | 20 | Technische score uit hoofdstuk 7 |
| Veiligheid | 15 | Bèta, volatiliteit, nettoschuld gedeeld door EBITDA, rentedekking, Altman Z-score |
| Revisies en sentiment | 10 | Winstrevisies over 1 en 3 maanden, winstverrassing, short interest, niet-routinematige aankopen door bestuurders |
| Groei | 10 | Omzet- en winstgroei en de bestendigheid daarvan |

Gates:

- Beneish M-score boven -1,78 (signaal van mogelijk geflatteerde cijfers): hoogstens C.
- Altman Z-score onder 1,81 (verhoogd faillissementsrisico): hoogstens C.
- Eén pijler in het laagste vijfde deel van de groep: hoogstens B-.

Kwaliteit en waarde wegen het zwaarst omdat ze het vaakst zijn bevestigd en elkaar versterken. Groei heeft het zwakste bewijs. Winstverrassing telt bij grote bedrijven licht mee; dat effect is daar sinds 2006 verdwenen.

### Bank of verzekeraar

Schuld is hier grondstof, dus ondernemingswaarde, vrije kasstroom en Altman Z zijn onbruikbaar.

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Waardering | 30 | Koers gedeeld door tastbare boekwaarde afgezet tegen rendement op tastbaar eigen vermogen, winst gedeeld door koers, dividendrendement |
| Winstgevendheid | 25 | Rendement op tastbaar eigen vermogen, rentemarge, kosten gedeeld door baten; bij verzekeraars de combined ratio |
| Kapitaal en kredietkwaliteit | 25 | Ruimte van de CET1-ratio boven de eis, probleemleningen, dekking daarvan, leningen gedeeld door deposito's; bij verzekeraars de Solvency II-ratio |
| Momentum en revisies | 20 | Technische score en winstrevisies |

Gate: CET1-ruimte boven de eis kleiner dan 1 procentpunt: hoogstens C.

### Vastgoedfonds (REIT)

Afschrijving vertekent de winst; reken met FFO en AFFO (kasstroom uit verhuur).

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Waardering | 25 | Koers gedeeld door AFFO, korting of premie op intrinsieke waarde, aanvangsrendement minus staatsrente |
| Balans | 25 | Nettoschuld gedeeld door EBITDA, schuld als deel van de vastgoedwaarde, looptijd van de schuld, vastrentend deel, rentedekking |
| Operationeel | 20 | Bezettingsgraad binnen het eigen vastgoedtype, huurgroei op vergelijkbare basis, resterende huurtermijn |
| Dividendveiligheid | 15 | Uitkering als deel van AFFO |
| Momentum | 15 | Technische score |

Gate: uitkering hoger dan 100% van AFFO: hoogstens C.

### ETF

De grade beoordeelt het product, niet de markt erin. Toon de Timing van de onderliggende index los.

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Kosten | 40 | Werkelijk verschil met de index over 3 tot 5 jaar (tracking difference); lopende kosten alleen als terugval |
| Verhandelbaarheid | 20 | Spread, fondsomvang, dagomzet |
| Structuur en fiscaal | 20 | Domicilie, fysiek of synthetisch, uitleenbeleid, uitkerend of herbeleggend |
| Overlevingskans | 10 | Omvang boven 100 miljoen euro, uitgever, leeftijd, instroom |
| Spreiding | 10 | Gewicht van de tien grootste posities, breedte van de index |

Gates en regels:

- Hefboom- of inverse product: hoogstens D.
- Fondsomvang onder 50 miljoen euro: hoogstens C.
- Geen Europees essentiële-informatiedocument, zoals bij de meeste Amerikaanse ETF's: toon als niet verkrijgbaar voor Nederlandse particulieren.
- Ierse fondsen betalen 15% Amerikaanse dividendbelasting, Luxemburgse 30%. Maak de fiscale score instelbaar; de behandeling van Nederlandse fondsen is niet geverifieerd.

Kosten wegen het zwaarst omdat het de best bewezen voorspeller van fondsresultaat is.

### Obligatie

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Rendement | 35 | Effectief rendement min verwacht verlies door wanbetaling en kosten; bij staatsobligaties de reële rente |
| Kredietkwaliteit | 20 | Verdeling over ratings, renteopslag per eenheid wanbetalingsrisico |
| Renterisico | 20 | Duration, rendement per jaar duration, plek op de rentecurve |
| Kosten en liquiditeit | 15 | Tracking difference, spread |
| Spreiding | 10 | Concentratie in uitgevers |

Regel: beoordeel een hoog rendement nooit zonder het verwachte wanbetalingsverlies eraf te trekken. Het aanvangsrendement voorspelt het rendement over vijf jaar goed, over één jaar matig; zet de horizon op 5 jaar.

### Index

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Trend | 30 | Technische score |
| Waardering | 25 | Winstrendement min reële rente, cyclisch gecorrigeerde koers-winstverhouding ten opzichte van de eigen historie |
| Macro | 20 | Marktregime uit hoofdstuk 5, rentecurve |
| Marktbreedte | 15 | Deel van de aandelen boven het 200-daags gemiddelde |
| Volatiliteit | 10 | Volatiliteit ten opzichte van de eigen historie |

Deze gewichten zijn een eigen voorstel; voor indices is geen gepubliceerde weging gevonden.

### Bitcoin

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Trend | 30 | Technische score |
| On-chain waardering | 25 | MVRV Z-score, NUPL, Puell-multiple, koers gedeeld door gerealiseerde prijs |
| Macro | 20 | Marktregime, reële rente, dollarindex |
| Liquiditeit en stromen | 15 | ETF-stromen, aanbod van stablecoins |
| Positionering | 10 | Funding rate, open interest |

Regels:

- Scoor waardering als percentiel ten opzichte van de eigen historie, met zwaarder gewicht op de laatste cyclus. Gebruik geen vaste niveaus.
- Deze indicatoren herkenden bodems (2015, 2018, 2022) beter dan toppen; bij de top van oktober 2025 gaf geen ervan een schoon signaal. Meld dat in de toelichting.
- Gebruik stock-to-flow en Pi Cycle niet als invoer. Het eerste model is weerlegd, het tweede miste de laatste top.

### Platform, DeFi-protocol en Utility

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Tokenomics en aanbod | 25 | Marktkapitalisatie gedeeld door FDV, deel van het aanbod dat binnen 30, 90 en 365 dagen vrijkomt per ontvanger, netto-inflatie, reële stakingopbrengst, aandeel van de 10 en 100 grootste houders zonder beurzen |
| Fundamentals en waardeopbouw | 20 | Platform: actieve adressen, fees, ontwikkelaars. DeFi: omzet, winst na aftrek van beloningen, uitkering aan houders via terugkoop of verbranding. Utility: omzet van echte afnemers |
| Trend | 20 | Technische score |
| Veiligheid en decentralisatie | 10 | Audits, incidenten, beheerderssleutels en upgrademogelijkheid; bij L2's de L2BEAT-fase |
| Waardering | 10 | Marktkapitalisatie gedeeld door actieve adressen en gedeeld door fees, ten opzichte van vergelijkbare tokens |
| Liquiditeit | 10 | Omzet op gereguleerde beurzen, orderboekdiepte binnen 2% |
| Aandacht | 5 | Zoek- en sociale belangstelling |

Bij Utility gaat het gewicht van Aandacht naar Tokenomics (30 en 0), omdat emissies daar het grootste risico zijn.

Gates:

- Meer dan 10% van het aanbod komt binnen 90 dagen vrij voor team of investeerders: hoogstens C.
- Marktkapitalisatie gedeeld door FDV onder 0,2: hoogstens B-.
- Onopgeloste hack of exploit: hoogstens D.
- Niet verhandelbaar bij een aanbieder met MiCA-vergunning: hoogstens C.

Regels:

- Tokenomics weegt het zwaarst: bij ruim 16.000 onderzochte unlocks had ongeveer 90% een negatief koerseffect, het sterkst bij unlocks voor het team.
- Beloon kleine omvang niet. Het size-effect zit in onverhandelbare microcaps.
- Gebruik geen omzet van ongereguleerde beurzen; daar is gemiddeld ruim 70% schijnhandel gemeten.
- Toon naast de grade een grade ten opzichte van Bitcoin, omdat de Bitcoin-beweging anders alles overheerst.

### Memecoin

Geen gewogen grade. Voer een veiligheidscontrole uit en toon liquiditeit en aandacht. De grade is hoogstens C en draagt het label speculatie.

Gates voor Solana-tokens:

- Mint-bevoegdheid actief, freeze-bevoegdheid actief of liquiditeit niet verbrand of vergrendeld: F.
- De tien grootste houders bezitten meer dan 15%: hoogstens D.

### Stablecoin

Geen beleggingsgrade. Toon een pegveiligheid van 1 (sterk) tot 5 (zwak) op basis van kwaliteit van de reserves, inwisselbaarheid, bestuur, MiCA-status en het koersverloop rond 1,00.

### RWA-token

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Uitgever en juridische aanspraak | 30 | Wie geeft uit, welk recht heeft de houder |
| Bewaring en inwisseling | 25 | Bewaarder, inwisselvoorwaarden |
| Kwaliteit van het onderliggende | 25 | Grade van de onderliggende asset uit het eigen model |
| Liquiditeit | 10 | Omzet en spread |
| Kosten | 10 | Beheerkosten |

Deze gewichten zijn een eigen voorstel.

### Grondstof

Een particulier kan geen spot-olie aanhouden. Geef daarom twee oordelen: de grondstof zelf en het product (ETC) waarmee je hem koopt.

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Carry | 30 | Helling van de termijncurve op jaarbasis: backwardation is gunstig, contango ongunstig |
| Trend | 25 | Technische score |
| Fundamentals | 15 | Voorraden ten opzichte van het seizoensgemiddelde |
| Macro | 15 | Dollarindex, reële rente |
| Positionering | 10 | Verandering in posities van speculanten (CFTC) |
| Basis-momentum | 5 | Verschil in momentum tussen het eerste en tweede contract |

Productoordeel voor de ETC: fysiek of op termijncontracten, onderpand, lopende kosten, rolopbrengst over 12 maanden, tracking difference en spread.

Gates voor het product:

- Rolverlies slechter dan 10% per jaar: hoogstens C.
- Hefboom- of inverse product: hoogstens D.
- Schuldpapier zonder onderpand: hoogstens B-.

Toon seizoenspatronen alleen in de grafiek; ze leveren na kosten geen bewezen voordeel op.

### Edelmetaal

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Trend | 30 | Technische score |
| Macro | 25 | Reële rente (FRED `DFII10`), dollarindex |
| Vraag | 25 | Aankopen door centrale banken, ETF-stromen |
| Positionering | 10 | CFTC-posities |
| Carry | 10 | Termijncurve |

Het verband tussen goud en de reële rente is sinds 2022 verzwakt door aankopen van centrale banken. Meld in de toelichting wanneer macro en koers elkaar tegenspreken. De goud-zilververhouding is alleen context.

### Valutapaar

Een valutapaar heeft geen intrinsieke opbrengst behalve het renteverschil. De score is een richtingsscore voor lang de eerste valuta en kort de tweede: een A voor EUR/USD betekent een F voor USD/EUR.

| Pijler | Gewicht | Maatstaven |
| --- | --- | --- |
| Carry | 30 | Renteverschil gedeeld door volatiliteit, gerekend vanuit de euro |
| Momentum | 25 | Rendement over 3 tot 12 maanden |
| Waarde | 25 | Afwijking van de reële effectieve wisselkoers (BIS) ten opzichte van de eigen historie |
| Macro | 10 | Ruilvoet, lopende rekening, rentepad |
| Positionering | 10 | CFTC-posities |

Gates en regels:

- Staat de valutavolatiliteit of de VIX boven het 80e percentiel, halveer dan het gewicht van Carry. Carry verliest juist bij paniek.
- Gekoppelde of gestuurde valuta, of kapitaalbeperkingen: hoogstens C.
- Wijzen minder dan twee pijlers dezelfde kant op: C met het label geen voordeel.
- Toon de horizon per pijler: carry en momentum 1 tot 12 maanden, waarde 1 tot 5 jaar.

## 7. Grafiek en technische analyse

Gebruik TradingView Lightweight Charts 5.x en bereken alle indicatoren op de server. Alleen trend, momentum en volatiliteit tellen mee in de score; oscillatoren zoals RSI zijn context in de grafiek.

### Grafiek

- **Opbouw:** een koersvenster met candlesticks en gemiddelden, daaronder volume en maximaal twee indicatorvensters. Versie 5 ondersteunt meerdere vensters.
- **Bediening:** dag, week en maand; lineaire en logaritmische schaal; kruisdraad met waarden; vergelijken met de benchmark; indicatoren aan en uit per knop.
- **Eigen lagen:** markeer elke gradewijziging op de koerslijn en teken gates en het marktregime als gekleurde zones.
- **Standaard per assetklasse:** laad de indicatorset uit de tabel hieronder. De gebruiker kan zijn eigen set opslaan.
- **Tekenhulp:** de bibliotheek heeft geen ingebouwde tekentools. Neem de trendlijn-plugin uit de officiële voorbeelden over. Blijkt tekenen belangrijker dan uitstraling, meld dan KLineChart als alternatief.
- **Vermelding:** de licentie vereist een link naar TradingView; zet de optie `attributionLogo` aan.
- **Tweede mening:** voeg optioneel een tab toe met de gratis TradingView-widget. Die toont alleen TradingView-data, vaak vertraagd, en kan de eigen grades niet weergeven.

### Technische score

Eén formule per assetklasse, zonder afstemming per asset.

| Blok | Gewicht | Berekening |
| --- | --- | --- |
| Trendstand | 35 | Gemiddelde van vier toetsen: koers boven het 200-daags gemiddelde, 50-daags boven 200-daags, koers boven het 10-maandsgemiddelde, stijgend 200-daags gemiddelde |
| Momentum | 25 | Rendement over 12 maanden zonder de laatste maand en over 6 maanden, gedeeld door volatiliteit, als percentiel binnen de klasse |
| Afstand tot de top | 15 | Koers gedeeld door het hoogste punt van 52 weken, als percentiel |
| Relatieve sterkte | 15 | Rendement ten opzichte van de benchmark over 3, 6 en 12 maanden |
| Volatiliteit | 10 | Aftrek bij hoge volatiliteit ten opzichte van de eigen driejaarshistorie |

Het bewijs: trendvolgen op 6 tot 12 maanden, momentum, nabijheid van de 52-weekse top en schalen op volatiliteit houden stand in onderzoek over meer dan een eeuw. Losse oscillatoren, grafiekpatronen en korte regels doen dat na kosten niet. Een 10-maandsgemiddelde beperkt vooral de verliezen; het verhoogt het rendement nauwelijks.

### Indicatoren per assetklasse

| Klasse | In de score | Context in de grafiek |
| --- | --- | --- |
| Aandelen | 50- en 200-daags gemiddelde, 10- en 40-weeks gemiddelde, 12-1 momentum, afstand tot 52-weekse top, sterkte ten opzichte van index en sector | RSI 14, MACD 12-26-9, volume tegen 50-daags gemiddelde, ATR 14, Bollinger 20-2, VWAP verankerd op de laatste kwartaalcijfers |
| Crypto | 20-weeks SMA en 21-weeks EMA als band, 200-weeks gemiddelde, 50 en 200 dagen, Mayer-multiple, sterkte ten opzichte van Bitcoin | RSI 14 op weekbasis, gerealiseerde volatiliteit over 30 en 90 dagen, ATR in procenten, funding rate, open interest |
| Grondstoffen | Donchian 20 en 55, gemiddelden over 50, 100 en 200 dagen, 12-maands momentum, helling van de termijncurve | ADX 14, ATR 20, seizoenslijn over 10 tot 15 jaar, CFTC-index over 3 jaar |
| Valuta | 50- en 200-daags EMA, momentum over 3 tot 12 maanden, renteverschil op 2 jaar | ADX 14, ATR 14, Ichimoku 9-26-52, CFTC-posities |
| Indices en ETF's | 200-daags en 10-maandsgemiddelde, daling vanaf de top | Marktbreedte, VIX en de verhouding VIX tot VIX3M |
| Obligaties | Trend op de rente (omgekeerd) en op de totaalrendementskoers, momentum gedeeld door duration | Rentecurve 2-10 jaar en 3 maanden-10 jaar, MOVE-index |

### Rekenregels

- **Aandelen:** gebruik koersen gecorrigeerd voor splitsingen en dividend.
- **Crypto:** de markt is elke dag open. Gebruik de dagsluiting om 00:00 UTC, reken met 365 dagen per jaar en met procentuele drempels; de volatiliteit is drie tot vijf keer die van aandelen.
- **Grondstoffen:** reken op doorlopende, voor rollen gecorrigeerde termijnreeksen, nooit op spot.
- **Indices en obligaties:** gebruik totaalrendementsreeksen waar die bestaan.
- **Tijdschalen:** de week bepaalt het regime, de dag de timing. Geen intraday.
- **Niet stapelen:** RSI, stochastics en CCI meten hetzelfde. Toon er standaard één.
- **Valuta:** vergelijk reeksen in euro en dollar nooit zonder omrekening.

## 8. Zelflerende laag

De app meet elke maand hoe goed zijn grades uitpakten, doet elk kwartaal een voorstel voor betere gewichten en past niets aan zonder akkoord van de eigenaar. Leren gebeurt vooral op een historische terugtest; live data bewaakt het model.

### Waarom zo voorzichtig

- Met 50 assets per maand is de meetfout van één maandelijkse rangcorrelatie ongeveer 0,14. Een echte waarde van 0,05 aantonen vraagt ongeveer 36 maanden, en strenger getoetst ongeveer 80.
- Geoptimaliseerde gewichten verslaan gelijke gewichten zelden op nieuwe data (DeMiguel, Garlappi en Uppal 2009; Dawes 1979).
- Gepubliceerde beleggingsfactoren verliezen na publicatie ruim de helft van hun rendement (McLean en Pontiff 2016).

### Vastleggen

1. **Maandsnapshot.** Op de laatste handelsdag van de maand: per asset de invoer met `available_at`, pijlerscores, eindscore, grade, datadekking, koers en modelversie.
2. **Uitkomsten.** Na 1, 3, 6 en 12 maanden: totaalrendement, rendement ten opzichte van de benchmark van de klasse en de grootste tussentijdse daling.
3. **Universum per datum,** inclusief assets die later van de beurs verdwenen of dode coins.
4. **Elke modelconfiguratie die ooit is doorgerekend.** Het aantal pogingen telt mee in de toetsing.

### Maandelijkse meting

Per modelversie, sjabloon en horizon:

- Rangcorrelatie (Spearman) tussen score en later rendement, het gemiddelde ervan, de spreiding en het deel van de maanden boven nul.
- Gemiddeld en mediaan rendement boven de benchmark per letter, het verschil tussen A en F, en een toets of de volgorde A tot F klopt.
- Per letter het deel dat de benchmark versloeg en de grootste daling.
- Rangcorrelatie per pijler en de onderlinge samenhang van de pijlers.
- Hoe vaak grades wisselen.
- Splitsing naar marktregime.

Reken significantie met Newey-West, met een vertraging van minstens de horizon min één maand, omdat overlappende rendementen de steekproef kleiner maken dan hij lijkt. Schrijf de maatstaven zelf in pandas en SciPy; gebruik alphalens-reloaded alleen als controle.

### Terugtest

- Bouw in fase 8 een terugtest die het model maand voor maand toepast met alleen data die op dat moment beschikbaar was.
- Haalbaar: Amerikaanse aandelen over 15 tot 20 jaar via SEC-indieningsdata, en de koerspijlers van alle klassen.
- Zwak: Europese fundamentals, kwaliteitspijlers van crypto, obligaties en valuta. Meld per sjabloon hoeveel maanden en assets de terugtest dekt.
- Label herberekende historie als terugtest. Toon die nooit als behaald resultaat.

### Kwartaalvoorstel voor gewichten

1. Vertrek van de startgewichten w0 uit hoofdstuk 6. Die blijven het anker.
2. Bereken per pijler de gemiddelde rangcorrelatie over 3 maanden, zonder overlap, over terugtest en live data samen.
3. Krimp: IC\_gekrompen = IC\_gemeten × T / (T + 60), met T het aantal onafhankelijke maanden. Negatief wordt nul.
4. Doelgewicht per pijler is evenredig aan IC\_gekrompen gedeeld door de spreiding ervan.
5. Meng: w\_nieuw = (1 - λ) × w0 + λ × w\_doel, met λ = min(0,5; T / (T + 60)).
6. Pas de vangrails toe.

| Vangrail | Waarde |
| --- | --- |
| Gewicht per pijler | Tussen 5% en 40%, en tussen 0,5 en 1,5 keer het startgewicht |
| Wijziging per kwartaal | Hoogstens 3 procentpunten per pijler |
| Minimale data | 120 maanden terugtest, 30 assets per maand, 12 maanden live snapshots |
| Onder het minimum | Sjabloon blijft op startgewichten; dat geldt naar verwachting voor obligaties, valuta en grondstoffen |
| Uitvoer | Een wijzigingsvoorstel, nooit een automatische wijziging |

### Kampioen en uitdager

Een voorgesteld model draait eerst in de schaduw naast het actieve model. Het wordt alleen actief als alles hieronder waar is:

- Minstens 6 maanden schaduwgrades.
- In de terugtest een eigen t-waarde van minstens 3 en een verbetering ten opzichte van de kampioen met t-waarde van minstens 2.
- Deflated Sharpe Ratio boven 0,95, gerekend met het vastgelegde aantal pogingen, en een kans op overfitting (PBO) onder 0,2.
- Volgorde van A tot F niet slechter, wisselingen hooguit 20% hoger, daling van de beste groep niet groter.
- Live schaduwresultaat niet duidelijk slechter dan de kampioen.
- Akkoord van de eigenaar in de app, met één klik terug te draaien, en hoogstens één wissel per 6 maanden.

Een leermodel met beslisbomen (LightGBM met SHAP-uitleg) mag alleen als uitdager op de aandelenterugtest draaien. Train het nooit op de live data van de app; die verzameling is te klein.

### Pagina Model

Toon alleen live resultaten als staat van dienst, los van de terugtest: rendement per letter tegen de benchmark met betrouwbaarheidsinterval, rangcorrelatie per maand, het aantal grote missers en een stand onvoldoende data zolang dat zo is. Toon daaronder openstaande voorstellen met de knoppen goedkeuren en afwijzen.

## 9. AI-componenten

Een taalmodel schrijft toelichtingen, leest documenten en doet voorstellen. Het levert nooit cijfers en verandert nooit zelf een score of een instelling.

| Component | Invoer | Uitvoer | Vangrail |
| --- | --- | --- | --- |
| Toelichting | JSON met de berekende maatstaven, pijlers en gates van één asset | Nederlandse tekst plus een lijst van gebruikte maatstaven | Controleer elk getal in de tekst tegen de invoer; bij een afwijking één nieuwe poging, daarna een vaste sjabloontekst |
| Kwalitatieve kenmerken | Jaarverslag, kwartaalcall, whitepaper of nieuws | Score per rubriek (concurrentievoordeel, bestuur, rode vlaggen in tokenomics) met letterlijk citaat als bewijs | Citaat moet in de bron voorkomen; onvoldoende bewijs is een geldig antwoord; telt alleen als rode vlag of als pijler van hoogstens 5% |
| Kwartaalbeoordeling | Het evaluatierapport uit hoofdstuk 8 | Wijzigingsvoorstel met bewijs, verwacht effect en risico's | Een vaste controle past de vangrails toe; geen schrijfrechten op configuratie |
| Analyse van missers | Snapshot van een A of B die daarna meer dan 30% achterbleef, plus later nieuws | Kandidaat voor een nieuwe gate | De regel wordt in code uitgeschreven en over de hele terugtest getoetst, met telling van vals alarm |

### Regels voor alle componenten

- **Geen terugtest met taalmodellen.** Een model kent de afloop van oude gebeurtenissen uit zijn training. Kwalitatieve scores gelden alleen vanaf de dag dat ze zijn gemaakt.
- **Vastleggen.** Bewaar bij elke aanroep model, versie van de prompt, hash van de invoer en de uitvoer. Genereer nooit stilzwijgend opnieuw.
- **Vast model per component.** Zet de modelnaam in configuratie. Kies een goedkoop model voor toelichtingen en kenmerken en een sterker model voor kwartaalbeoordeling en missers.
- **Kosten.** Draai toelichtingen en kenmerken 's nachts via de batch-API (50% korting) met prompt caching voor de vaste instructie. Stel een maandbudget in met een harde stop en toon het verbruik onder Instellingen.
- **Structuur.** Vraag uitvoer op als JSON volgens een schema en controleer de stopreden; een afgebroken antwoord kan het schema breken.
- **Verversen.** Schrijf een toelichting alleen opnieuw als de grade of een pijler meer dan 5 punten verschuift.
- **Uitval.** De app werkt volledig zonder taalmodel; dan verschijnt de sjabloontekst.

Gebruik de Claude API. Lees de actuele modelnamen, prijzen en de parameters voor gestructureerde uitvoer op docs.claude.com voordat je bouwt.

## 10. Bouwfases

Elf fases, van fundament tot afronding. Crypto komt eerst omdat de gratis data daar het best is; snapshots lopen vanaf fase 2 mee, zodat de staat van dienst meteen begint op te bouwen.

### Fase 0: Fundament

- **Bouw:** repository, Docker Compose met interface, rekenserver en database, databasemigraties, gezondheidscontrole, testopzet, lader voor modelconfiguratie in YAML, woordenlijstbestand, lege tabs.
- **Klaar als:** `docker compose up` op de Mac een lege app met alle tabs toont, dezelfde images op de Synology starten en de tests slagen.

### Fase 1: Datalaag

- **Bouw:** adapterinterface met snelheidslimiet, maandbudget en terugval; adapters voor CCXT, CoinGecko, DefiLlama, Coin Metrics, Frankfurter en FRED; nachtelijke run; tabellen voor assets, aliassen, universum en koersen; logboek van aanroepen.
- **Klaar als:** de top 50 crypto minstens één jaar dagkoersen in euro heeft, een tweede run niets dubbel schrijft en een pagina het verbruik per bron toont.

### Fase 2: Grading-engine en crypto

- **Bouw:** maatstaven, percentielen, pijlers, gates, hysterese en bandbreedte volgens hoofdstuk 5; de technische score uit hoofdstuk 7; de zeven cryptosjablonen; funding en open interest met dagelijkse archivering; DexScreener en RugCheck voor Solana-tokens; de tabel `grade_snapshot` en de maandsnapshot.
- **Klaar als:** elke crypto in de top 50 een grade heeft of een uitgelegde reden waarom niet, elke grade exact opnieuw te berekenen is uit zijn snapshot en elke gate een eigen test heeft.

### Fase 3: Interface en grafiek

- **Bouw:** ranglijst, zoekveld, assetpagina, grafiek met de indicatorset voor crypto, markeringen van gradewijzigingen, tooltips uit de woordenlijst.
- **Klaar als:** de eigenaar van ranglijst naar assetpagina kan klikken, per pijler ziet welke maatstaf de score bepaalt en de grafiek vloeiend schuift en zoomt op de Synology.

### Fase 4: Aandelen

- **Bouw:** adapters voor Tiingo en SEC EDGAR; sectorindeling; fundamentele feiten met `available_at`; de sjablonen Aandeel algemeen, Bank of verzekeraar en Vastgoedfonds; de AEX-fondsen.
- **Vraag eerst:** of de eigenaar EODHD wil afnemen. Zonder betaalde bron krijgen Europese aandelen een lage datadekking.
- **Klaar als:** de 50 Amerikaanse aandelen een volledige grade hebben, een bank aantoonbaar via het banksjabloon loopt en Beneish en Altman tegen een handmatig nagerekend voorbeeld kloppen.

### Fase 5: ETF's, obligaties, indices en marktregime

- **Bouw:** ETF-kenmerken uit bron of CSV, tracking difference, de sjablonen ETF, Obligatie en Index, het marktregime en de koppeling daarvan met de andere sjablonen.
- **Klaar als:** ETF's op dezelfde index naast elkaar staan met een verklaarbaar verschil en het regime per dag in de database staat met zijn drie invoeren.

### Fase 6: Grondstoffen en valuta

- **Bouw:** adapters voor CFTC, EIA en de Wereldbank; termijnreeksen; de sjablonen Grondstof, Edelmetaal en Valutapaar; het productoordeel voor ETC's.
- **Klaar als:** elke grondstof een oordeel over de grondstof en over het product toont, en EUR/USD en USD/EUR elkaars spiegelbeeld zijn.

### Fase 7: Toelichting, volglijst en bronnen

- **Bouw:** de toelichtingscomponent uit hoofdstuk 9 met getalcontrole en sjabloonterugval, het kostenbudget, de volglijst, de pagina Bronnen met verplichte vermeldingen.
- **Klaar als:** in 100 gegenereerde toelichtingen geen getal staat dat niet in de invoer zat, en de app zonder API-sleutel blijft werken.

### Fase 8: Uitkomsten, terugtest en pagina Model

- **Bouw:** uitkomstlabels na 1, 3, 6 en 12 maanden; de maandelijkse meting; de tijdvaste terugtest; ijking van de lettergrenzen; de pagina Model.
- **Klaar als:** de terugtest aantoonbaar geen toekomstige data gebruikt (test met een bewust verschoven feit), het rapport per sjabloon de dekking in maanden en assets noemt en terugtest en live gescheiden worden getoond.

### Fase 9: Leerlus

- **Bouw:** het kwartaalvoorstel met vangrails, kampioen en uitdager in de schaduw, de toetsen voor promotie, goedkeuren en terugdraaien in de app, de kwartaalbeoordeling en de analyse van missers door het taalmodel, kwalitatieve kenmerken als rode vlag.
- **Klaar als:** een voorstel dat een vangrail schendt wordt geweigerd, een goedgekeurde wissel een nieuwe modelversie oplevert en met één klik terug kan, en geen enkel pad gewichten zonder akkoord wijzigt.

### Fase 10: Afronding

- **Bouw:** back-up en bewezen herstel, melding bij een mislukte nachtrun, controle van geheugen en rekentijd op de Synology, inlog, README en handleiding in het Nederlands.
- **Klaar als:** een herstel uit de back-up op een schone machine dezelfde grades geeft en de volledige nachtrun binnen één uur klaar is.

## 11. Wat de app niet mag doen

- Geen automatische wijziging van gewichten, drempels of gates zonder akkoord van de eigenaar.
- Geen grade tonen zonder datadekking, modelversie en peildatum erbij.
- Geen verzonnen of geschatte cijfers, ook niet door het taalmodel.
- Geen terugtest presenteren als behaald resultaat.
- Geen woorden als kopen, verkopen of koersdoel, en geen advies op basis van iemands portefeuille of doelen.
- Geen functie om grades publiek te delen. Wil de eigenaar dat later toch, stop dan en meld dat daarvoor de regels voor beleggingsaanbevelingen en de datalicenties eerst bekeken moeten worden.
- Geen orders plaatsen en geen koppeling met handelsaccounts.
- Geen schrapen van sites die dat in hun voorwaarden verbieden.

Zet onder aan elke pagina: Deze app is een privéhulpmiddel voor onderzoek. Grades zijn een rangorde op basis van een model, geen beleggingsadvies en geen voorspelling. Resultaten uit het verleden bieden geen garantie voor de toekomst.

## Bronnen

Dit deel is weer voor jou. Een selectie van de pagina's waarop de keuzes rusten, geraadpleegd op 11 oktober 2026.

**Gradingmethodes en factoren**

- [Seeking Alpha: Quant Ratings en Factor Grades](https://help.seekingalpha.com/premium/quant-ratings-and-factor-grades-faq)
- [Morningstar: Equity Research Methodology](https://s205.q4cdn.com/437373358/files/doc_downloads/2025/07/Morningstar-Equity-Research-Methodology-2023-06-14.pdf)
- [MSCI: Quality Indexes Methodology](https://www.msci.com/eqb/methodology/meth_docs/MSCI_Quality_Indexes_Methodology_May2022.pdf)
- [AAII: A+ grades](https://www.aaii.com/journal/article/437530-how-the-components-of-a-grades-help-you-analyze-stocks)
- [McLean en Pontiff: verval van factoren na publicatie](https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary)
- [Hou, Xue en Zhang: Replicating Anomalies](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html)
- [Asness, Frazzini en Pedersen: Quality Minus Junk](https://papers.ssrn.com/abstract=2312432)
- [Morningstar: kosten voorspellen fondsresultaat](https://www.morningstar.com/funds/fund-fees-predict-future-success-or-failure)
- [justETF: tracking difference](https://www.justetf.com/at/academy/tracking-difference-vs-tracking-error.html)
- [Janus Henderson: aanvangsrendement en obligatierendement](https://www.janushenderson.com/en-us/institutional/article/can-bond-yields-predict-returns/)

**Crypto, grondstoffen en valuta**

- [Weiss: wijziging van het ratingmodel](https://www.fxstreet.com/amp/cryptocurrencies/news/weiss-crypto-ratings-model-why-weve-made-some-changes-201912042200)
- [Cong e.a.: waarde- en adoptiefactor in crypto](https://pubsonline.informs.org/doi/10.1287/mnsc.2024.05875)
- [Grobys e.a. 2025: momentum in crypto](https://link.springer.com/article/10.1007/s11408-025-00474-9)
- [Keyrock: 16.000 token-unlocks](https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/)
- [Cong e.a.: schijnhandel op cryptobeurzen](https://arxiv.org/abs/2108.10984v1)
- [L2BEAT: risicokader](https://l2beat.com/scaling/risk)
- [Koijen e.a.: Carry](https://research.cbs.dk/da/publications/carry/)
- [Boons en Porras Prado: Basis-Momentum](https://ideas.repec.org/a/bla/jfinan/v74y2019i1p239-279.html)
- [Chicago Fed: goud en reële rente](https://www.chicagofed.org/publications/chicago-fed-letter/2021/464)
- [Menkhoff e.a.: carry en valutavolatiliteit](https://openaccess.city.ac.uk/id/eprint/3391/)

**Grafiek, indicatoren en data**

- [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts)
- [TradingView Advanced Charts: voorwaarden](https://www.tradingview.com/charting-library-docs/latest/introduction)
- [Hurst, Ooi en Pedersen: een eeuw trendvolgen](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing)
- [Faber: tactische assetallocatie](https://papers.ssrn.com/abstract=962461)
- [Detzel e.a.: voortschrijdende gemiddelden bij Bitcoin](https://ideas.repec.org/a/bla/finmgt/v50y2021i1p107-137.html)
- [TA-Lib op PyPI](https://pypi.org/project/TA-Lib/)
- [CoinGecko API-prijzen](https://www.coingecko.com/en/api/pricing)
- [EODHD-prijzen](https://eodhd.com/pricing)
- [Tiingo-prijzen](https://www.tiingo.com/about/pricing)
- [SEC EDGAR API's](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [Intel: Celeron J4125](https://www.intel.com/content/www/us/en/products/sku/197305/intel-celeron-processor-j4125-4m-cache-up-to-2-70-ghz/specifications.html)

**Zelflerend, AI en regels**

- [S&P: prestaties van aandelenselectiemodellen](https://www.spglobal.com/content/dam/spglobal/mi/en/documents/general/us-stock-selection-model-performance-review.pdf)
- [DeMiguel, Garlappi en Uppal: 1/N](https://ideas.repec.org/a/oup/rfinst/v22y2009i5p1915-1953.html)
- [Dawes: improper linear models](https://www.cmu.edu/dietrich/sds/docs/dawes/the-robust-beauty-of-improper-linear-models-in-decision-making.pdf)
- [Harvey, Liu en Zhu: t-waarde boven 3](https://www.nber.org/papers/w20592)
- [Bailey en López de Prado: Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- [Glasserman en Lin: look-ahead bias bij taalmodellen](https://arxiv.org/abs/2309.17322)
- [Claude API: batchverwerking](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
- [AFM: beleggingsaanbevelingen](https://www.afm.nl/en/sector/themas/marktmisbruik/beleggingsaanbevelingen)
- [ESMA: aanbevelingen op sociale media](https://www.esma.europa.eu/press-news/esma-news/requirements-when-posting-investments-recommendations-social-media)
- [AFM: finfluencing](https://www.afm.nl/en/sector/themas/digitalisering/finfluencing)
