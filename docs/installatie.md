# Graadmeter installeren: stap voor stap

Deze handleiding brengt je van niets naar een werkende Graadmeter op je Synology DS920+, inclusief alles wat
na de bouw nog openstond. Elke opdracht staat in een grijs blok dat je in zijn geheel in de Terminal kunt
plakken. Waar je iets zelf moet invullen staat dat er vlak boven, en altijd maar op één plek.

> Deze app is een privéhulpmiddel voor onderzoek. Grades zijn een rangorde op basis van een model, geen
> beleggingsadvies en geen voorspelling. Resultaten uit het verleden bieden geen garantie voor de toekomst.

**Hoe lang duurt het?** Ongeveer twee uur werk, plus wachttijd: het bouwen op de Mac (half uur tot een uur),
de eerste keer data ophalen (een uur of meer) en de terugtest (een paar uur, kan 's nachts).

**Waar typ je wat?** Elke stap begint met een van deze drie labels:

- 🖥️ **Mac** – in de app Terminal op je Mac (Finder > Programma's > Hulpprogramma's > Terminal).
- 🗄️ **NAS** – in de Terminal, maar ná inloggen op de NAS met `ssh` (stap D1). Je ziet dan iets als
  `root@DS920:~#` vooraan de regel.
- 🌐 **Browser** – in Safari of Chrome.

## Inhoud

- [A. Sleutels aanvragen](#a-sleutels-aanvragen) (gratis accounts, 20 minuten)
- [B. De Mac klaarmaken en de app bouwen](#b-de-mac-klaarmaken-en-de-app-bouwen)
- [C. De Synology klaarmaken](#c-de-synology-klaarmaken)
- [D. De app op de NAS zetten en starten](#d-de-app-op-de-nas-zetten-en-starten)
- [E. De eerste keer data ophalen en de NAS-controle](#e-de-eerste-keer-data-ophalen-en-de-nas-controle)
- [F. Terugtest en ijking van de lettergrenzen](#f-terugtest-en-ijking-van-de-lettergrenzen)
- [G. Back-up naar buiten de NAS en meldingen](#g-back-up-naar-buiten-de-nas-en-meldingen)
- [H. Wat nog openstond: jouw beslissingen en acties](#h-wat-nog-openstond-jouw-beslissingen-en-acties)
- [I. Een nieuwe versie installeren](#i-een-nieuwe-versie-installeren)
- [J. Problemen oplossen](#j-problemen-oplossen)
- [K. Spiekbriefje](#k-spiekbriefje)

---

## A. Sleutels aanvragen

Zet de sleutels die je krijgt even in een notitie (of beter: je wachtwoordbeheerder). In stap B4 vraagt een
script er één voor één om. Een sleutel die je nog niet hebt kun je overslaan en later toevoegen (zie J7).

| # | Sleutel | Nodig? | Waar aanvragen | Wat je krijgt |
| --- | --- | --- | --- | --- |
| A1 | **CoinGecko Demo** | Ja (cryptolijst) | <https://www.coingecko.com/en/developers/dashboard> → account maken → *Add New Key* (Demo) | Begint met `CG-` |
| A2 | **FRED** | Ja (rentes, VIX, regime) | <https://fredaccount.stlouisfed.org/apikeys> → account maken → *Request API Key* | 32 tekens, letters en cijfers |
| A3 | **Tiingo** | Aanbevolen (VS-koersen) | <https://www.tiingo.com> → *Sign up* → menu *API* → *Token* | Lange reeks letters en cijfers |
| A4 | **EIA** | Aanbevolen (olie en gas) | <https://www.eia.gov/opendata/register.php> → formulier; de sleutel komt per e-mail | Lange reeks letters en cijfers |
| A5 | **SEC** | Ja (aandelen) | Geen account: alleen je naam en e-mailadres | – |
| A6 | **Anthropic** | Optioneel (toelichtingen) | <https://console.anthropic.com> → *Settings* → *Billing*: minimaal tegoed kopen en een *spend limit* zetten → *API keys* → *Create Key* | Begint met `sk-ant-` |
| A7 | **Meldingen via ntfy** | Aanbevolen | Installeer de app **ntfy** op je telefoon → **+** → bedenk een lange, geheime naam (bijv. `graadmeter-k7f2q9xw4m`) → *Subscribe* | Je webhook is `https://ntfy.sh/graadmeter-k7f2q9xw4m` |

Over A1 en A2: de CoinGecko- en FRED-sleutel die je al eerder gaf werken ook; die hoef je niet opnieuw aan te
vragen.

Over A6: de app stopt zelf bij 5 euro per maand (`config/ai.yaml`), maar zet ook in de Anthropic-console een
limiet. Zonder deze sleutel werkt alles, alleen staan er dan vaste sjabloonteksten bij de grades.

---

## B. De Mac klaarmaken en de app bouwen

### B1. Docker Desktop installeren 🖥️

1. Download Docker Desktop: <https://www.docker.com/products/docker-desktop/>. Kies **Apple Silicon** als je
   Mac een M1/M2/M3/M4-chip heeft (Apple-menu > *Over deze Mac* > *Chip*), anders **Intel**.
2. Open het `.dmg`-bestand, sleep Docker naar Programma's en start Docker. Accepteer de voorwaarden; inloggen
   bij Docker is niet nodig (*Skip*).
3. Alleen bij Apple Silicon: Docker > *Settings* (tandwiel) > *General* > zet
   **"Use Rosetta for x86_64/amd64 emulation on Apple Silicon"** aan > *Apply & restart*. Dat maakt het
   bouwen voor de NAS veel sneller.
4. Docker > *Settings* > *Resources*: zet het geheugen op minstens **4 GB** > *Apply & restart*.

Controleer in de Terminal:

```bash
docker version --format 'Docker {{.Server.Version}}' && docker buildx version
```

Je ziet twee regels met versienummers. Een fout betekent dat Docker Desktop nog niet draait: start het en
wacht tot het walvisicoontje in de menubalk stilstaat.

### B2. Git installeren 🖥️

```bash
git --version || xcode-select --install
```

Verschijnt er een venster, klik dan *Installeer* en wacht tot het klaar is. Draai daarna de regel nog eens;
je ziet dan `git version ...`.

### B3. De code ophalen 🖥️

De code staat in je privé-repository op GitHub. Daarvoor heb je een toegangstoken nodig in plaats van je
wachtwoord:

1. 🌐 Ga naar <https://github.com/settings/personal-access-tokens/new>.
2. *Token name*: `Graadmeter Mac`. *Expiration*: 1 jaar.
3. *Repository access*: **Only select repositories** → kies `AssetGrading`.
4. *Permissions* > *Repository permissions* > **Contents**: **Read and write** (schrijven is nodig voor stap F5).
5. *Generate token* en kopieer het token (begint met `github_pat_`). Je ziet het maar één keer.

🖥️ Haal de code op (bij de vraag om *Username* typ je `patrickdekker82`, bij *Password* plak je het token;
je Mac onthoudt het daarna):

```bash
cd ~ && git clone -b claude/laughing-pasteur-kbmar1 https://github.com/patrickdekker82/AssetGrading.git Graadmeter
cd ~/Graadmeter && git log -1 --format='Opgehaald: %h %s'
```

De app staat nu in de map **Graadmeter** in je thuismap (in de Finder: Ga > Thuismap).

### B4. De instellingen maken (.env) 🖥️

Een script vraagt alles wat nodig is en maakt het bestand `.env` aan. Database- en sessiewachtwoorden maakt het
zelf; voor het inlogwachtwoord kun je op Enter drukken om er een te laten maken (schrijf dat dan op!).

```bash
cd ~/Graadmeter && bash scripts/make-env.sh
```

Typ of plak bij elke vraag de sleutel uit stap A en druk op Enter; bij een sleutel die je (nog) niet hebt druk
je alleen op Enter. Bij de SEC-vraag typ je je naam en e-mailadres, bijvoorbeeld `Patrick Dekker
jouw@adres.nl`. Dit adres gaat alleen naar de SEC, die het verplicht stelt.

Controleren (opent het bestand in TextEdit; sluit het zonder te bewaren):

```bash
open -e ~/Graadmeter/.env
```

`.env` bevat je geheimen. Het staat in `.gitignore`, gaat dus nooit naar GitHub, en alleen jij kunt het lezen.

### B5. Eerst op de Mac proberen (aanbevolen, 15 minuten) 🖥️

```bash
cd ~/Graadmeter && docker compose up --build -d && docker compose ps
```

De eerste keer bouwt dit alles (10–20 minuten). Daarna: 🌐 open <http://localhost:3000> en log in met je
inlogwachtwoord. Je ziet de tabs, nog zonder grades (de database is leeg). Rechtsboven moet **Systeem in
orde** staan. Werkt het, zet de proefversie dan weer uit:

```bash
cd ~/Graadmeter && docker compose down
```

### B6. De images voor de NAS bouwen 🖥️

De NAS heeft een Intel-processor (amd64); de Mac bouwt daarvoor. Op een Apple-Mac duurt dit een half uur tot
een uur. Laat de Mac aan staan.

```bash
cd ~/Graadmeter && bash scripts/build-images.sh && ls -lh dist/
```

Klaar als je `Klaar: dist/graadmeter-images.tar.gz` ziet en een bestand van ongeveer 500–700 MB.

---

## C. De Synology klaarmaken

Alles in dit deel doe je in DSM, de beheerpagina van de NAS 🌐 (meestal `http://<ip-adres>:5000`, of via
<https://finds.synology.com>). Log in met een account dat **beheerder** is.

### C1. Container Manager installeren

*Pakketcentrum* → zoek **Container Manager** → *Installeren*. Hierdoor ontstaat ook de gedeelde map
**docker**.

### C2. SSH en SFTP aanzetten

1. *Configuratiescherm* → *Terminal en SNMP* → tab *Terminal* → vink **SSH-service inschakelen** aan (poort 22)
   → *Toepassen*.
2. *Configuratiescherm* → *Bestandsservices* → tab *FTP* → onderaan bij *SFTP*: vink
   **SFTP-service inschakelen** aan → *Toepassen*. (Nodig om bestanden met `scp` te kopiëren.)

### C3. Het adres van de NAS en je gebruikersnaam

- IP-adres: *Configuratiescherm* → *Netwerk* → *Netwerkinterface* → *LAN 1*, bijvoorbeeld `192.168.1.50`.
  Tip: geef de NAS in je router een vast IP-adres, anders kan het veranderen.
- Gebruikersnaam: de naam waarmee je in DSM inlogt (rechtsboven in DSM).

### C4. Eén keer invullen op de Mac 🖥️

Vul hieronder **je eigen** gebruikersnaam en IP-adres in (alleen in deze ene regel) en plak hem. Alle latere
opdrachten op de Mac gebruiken dit.

```bash
echo 'export NAS="jouwnaam@192.168.1.50"' >> ~/.zshrc && source ~/.zshrc && echo "NAS is $NAS"
```

Test de verbinding (de eerste keer vraagt hij of je de NAS vertrouwt: typ `yes`; daarna je DSM-wachtwoord):

```bash
ssh "$NAS" 'echo Verbonden met $(hostname)' && ssh "$NAS" 'mkdir -p /volume1/docker/graadmeter && echo map klaar'
```

Zie je `Verbonden met ...` en `map klaar`, dan kun je verder. (*Permission denied* bij `mkdir`? Zie J1.)

---

## D. De app op de NAS zetten en starten

### D1. Bestanden kopiëren 🖥️

Dit kopieert de images, de instellingen, de configuratie en de scripts. Het NAS-composebestand krijgt op de NAS
de naam `docker-compose.yml`. Je typt een paar keer je DSM-wachtwoord.

```bash
cd ~/Graadmeter && \
scp dist/graadmeter-images.tar.gz .env "$NAS:/volume1/docker/graadmeter/" && \
scp docker-compose.nas.yml "$NAS:/volume1/docker/graadmeter/docker-compose.yml" && \
scp -r config scripts "$NAS:/volume1/docker/graadmeter/" && \
echo "Alles gekopieerd"
```

Krijg je `subsystem request failed`, dan staat SFTP nog uit (C2), of zet `-O` achter elke `scp`.

### D2. Inloggen op de NAS 🖥️ → 🗄️

```bash
ssh "$NAS"
```

Vanaf hier ben je op de NAS. Word daar beheerder (Docker vraagt dat) en ga naar de map; je typt nog één keer je
DSM-wachtwoord:

```bash
sudo -i
```

```bash
cd /volume1/docker/graadmeter && chmod +x scripts/*.sh && chmod 600 .env && ls
```

Je ziet: `config  docker-compose.yml  graadmeter-images.tar.gz  scripts` (`.env` is verborgen maar staat er).

### D3. Docker Compose controleren 🗄️

```bash
docker compose version || { mkdir -p ~/.docker/cli-plugins && ln -sf "$(command -v docker-compose)" ~/.docker/cli-plugins/docker-compose && docker compose version; }
```

Je ziet `Docker Compose version v2.x`. Het composebestand voor de NAS werkt ook met de oudere versie die
Container Manager meelevert (getest met 2.20).

### D4. De images laden 🗄️

```bash
docker load -i graadmeter-images.tar.gz && docker images | grep -E 'graadmeter|postgres'
```

Dit duurt een paar minuten. Je ziet daarna drie regels: `graadmeter-server`, `graadmeter-web` en `postgres`.

### D5. Controleren of de images op deze NAS werken 🗄️

De DS920+ heeft een oudere kernel en een processor zonder AVX. Deze test start elk image één keer leeg:

```bash
scripts/nas-smoketest.sh
```

Alle regels met `OK` of `ok` is goed. `LET OP` bij Binance futures of Bybit is niet erg (alleen extra
cryptodata). Een `FOUT` bij een andere bron betekent meestal dat de NAS die website niet kan bereiken (firewall
of DNS); zie J4.

### D6. Starten 🗄️

```bash
docker compose up -d && sleep 60 && docker compose ps
```

Bij alle drie de containers (`graadmeter-db-1`, `graadmeter-server-1`, `graadmeter-web-1`) moet `Up` staan, bij
de eerste twee met `(healthy)`. Zie je `starting`, wacht dan een minuut en draai `docker compose ps` opnieuw.

🌐 Open `http://192.168.1.50:3000` (met jouw IP-adres) en log in. Zet hem in je bladwijzers.

De containers starten na een herstart van de NAS vanzelf weer op.

---

## E. De eerste keer data ophalen en de NAS-controle

### E1. Alles in één keer ophalen en meteen meten 🗄️

`scripts/nas-check.sh` draait alle nachtelijke taken achter elkaar (wisselkoersen, markten, grondstoffen,
aandelen, crypto, toelichtingen, opruimen, back-up) en meet ondertussen het geheugen per container. De eerste
keer haalt hij ook alle historie op en duurt hij langer dan een gewone nacht. Start hem zo dat hij doorloopt als
je de Terminal sluit:

```bash
cd /volume1/docker/graadmeter && nohup scripts/nas-check.sh > nas-check-1.log 2>&1 &
```

Meekijken (stoppen met meekijken: `Ctrl+C`; de run gaat gewoon door):

```bash
tail -f /volume1/docker/graadmeter/nas-check-1.log
```

Of 🌐 in de app: **Instellingen** (rechtsboven) → *Nachtelijke taken*. Klaar als het logbestand eindigt met `OK`
(of een melding over fouten of tijd). Bekijk de uitkomst:

```bash
tail -25 /volume1/docker/graadmeter/nas-check-1.log
```

### E2. De echte meting, een dag later 🗄️

De eis is dat een gewone nacht binnen een uur klaar is. Meet dat de dag ná E1 nog een keer (de historie is er
dan al):

```bash
cd /volume1/docker/graadmeter && nohup scripts/nas-check.sh > nas-check-2.log 2>&1 &
```

```bash
tail -25 /volume1/docker/graadmeter/nas-check-2.log
```

Goed als je ziet: `Totaal: NN minuten (eis: binnen 60)`, `OK`, en per container een geheugengebruik onder de
plafonds (database 1536 MB, server 2048 MB, web 512 MB). In de ontwikkelomgeving was dat 17 minuten en
500 MB voor de server.

### E3. Controleren in de app 🌐

- **Instellingen** → *Aanroepen per bron*: bij elke bron aanroepen en weinig of geen fouten. Een bron zonder sleutel staat
  er met de melding dat hij is overgeslagen.
- **Instellingen** → *Data*: hoeveel crypto's een jaar aan koersen hebben, aantallen koersen en cijfers.
- De tabs **Crypto**, **Aandelen**, **ETF's**, **Grondstoffen**, **Valuta**, **Obligaties** en **Indices**
  hebben nu grades.

Vanaf nu draait alles elke nacht vanzelf (tijden in UTC; in Nederland 1 uur later in de winter, 2 in de zomer).

---

## F. Terugtest en ijking van de lettergrenzen

De lettergrenzen (vanaf welke score een A, B, ...) zijn nog voorlopig. Een terugtest past het model maand voor
maand toe op het verleden; daaruit komt een **voorstel** voor nieuwe grenzen per sjabloon, dat jij goedkeurt.

### F1. De terugtest starten 🗄️

Dit duurt op de NAS een paar uur; start hem 's avonds:

```bash
cd /volume1/docker/graadmeter && nohup docker compose exec -T server python -m app.cli backtest > backtest.log 2>&1 &
```

Voortgang (een regel per 12 maanden, tot `201/201 months`):

```bash
grep -o 'backtest [0-9]*: [0-9]*/[0-9]* months.*' /volume1/docker/graadmeter/backtest.log | tail -1
```

Of 🌐 **Model** → onderaan *Terugtest*: daar staat "Terugtest N loopt sinds ...".

### F2. Het voorstel bekijken 🌐

Als de terugtest klaar is: **Model** → *Voorstellen*. Per sjabloon zie je de grenzen nu, het voorstel en de
verdeling van de letters (nu → voorstel, doel 10% A, 20% B, 40% C, 20% D, 10% F). Sjablonen met te weinig
data houden hun voorlopige grenzen.

### F3. Goedkeuren 🌐

Klik **Goedkeuren** en onthoud het **nummer** van het voorstel ("Voorstel 4"). Er verandert nog niets: de
server past het model nooit zelf aan.

### F4. Vastleggen als nieuwe modelversie 🗄️

Vervang `4` door het nummer van jouw voorstel:

```bash
cd /volume1/docker/graadmeter && scripts/apply-proposal.sh 4
```

Je ziet `Modelversie 0.7.0 vastgelegd` en `Klaar`. De server is herstart met de nieuwe versie; de grades onder
die versie verschijnen na de volgende nachtrun. Oude grades blijven bewaard onder hun eigen versie.

### F5. De nieuwe versie terugzetten naar GitHub 🖥️

De nieuwe lettergrenzen staan nu alleen op de NAS. Zet ze terug in de code, anders gaan ze verloren bij een
update. **Op de Mac** (open een nieuw Terminal-venster, niet het venster dat op de NAS is ingelogd; vervang
`4`):

```bash
cd ~/Graadmeter && scp -r "$NAS:/volume1/docker/graadmeter/config/model" config/ && git add config/model && git commit -m "Calibrate letter bounds (proposal 4)" && git push
```

---

## G. Back-up naar buiten de NAS en meldingen

### G1. Wat er al vanzelf gebeurt

- Elke nacht om 02:00 UTC een back-up van de database in `/volume1/docker/graadmeter/backups`.
- Elke zondag zet de server de nieuwste back-up terug in een tijdelijke database en controleert hij of elke grade
  exact hetzelfde uitkomt (🌐 **Instellingen** → *Beheer*).

### G2. Een kopie buiten de NAS met Hyper Backup 🌐

Gaat de NAS stuk, dan zijn ook de back-ups weg. Zet daarom een kopie op een USB-schijf of in de cloud:

1. *Pakketcentrum* → installeer **Hyper Backup**.
2. Hyper Backup → **+** → *Gegevensback-uptaak* → kies het doel (USB-schijf, Synology C2, een andere NAS, ...).
3. Bij *Gegevens*: vink **alleen** `docker/graadmeter/backups` en `docker/graadmeter/config` aan. **Niet**
   `data/postgres`: dat zijn de draaiende databasebestanden, die zijn in een kopie niet bruikbaar.
4. Toepassingen: niets aanvinken.
5. Schema: dagelijks om **06:00** (ruim na de back-up van de server).
6. Rotatie: bijvoorbeeld de laatste 30 versies.

Bewaar ook je `.env` op een veilige plek (wachtwoordbeheerder): zonder dat bestand kun je een back-up wel
terugzetten, maar moet je alle sleutels opnieuw invullen.

### G3. Meldingen testen 🗄️

Als je bij B4 een webhook (ntfy) hebt ingevuld:

```bash
cd /volume1/docker/graadmeter && docker compose exec server python -m app.cli notify-test
```

Je telefoon krijgt "Testmelding". Vanaf nu meldt de app zich als een nachtrun mislukt, eindigt met 5 of meer
fouten, of als een taak meer dan een dag niet heeft gedraaid. (Liever e-mail? Vul de `SMTP_...`-regels in, zie
J7.)

### G4. Een terugzetting oefenen (eenmalig, aanbevolen) 🗄️

Dit doet de app al elke zondag automatisch; met de hand:

```bash
cd /volume1/docker/graadmeter && docker compose exec server python -m app.cli restore-test
```

Eindigt met `"snapshots_exact"` gelijk aan `"snapshots_recomputed"`: goed. Echt terugzetten na een ramp: zie J8.

---

## H. Wat nog openstond: jouw beslissingen en acties

Na de bouw bleef een aantal punten over. Dit is wat je per punt doet.

### H1. Acceptatie op de NAS zelf ✅ als je E1–E2 hebt gedaan

De eisen (nachtrun binnen een uur, geheugen binnen de plafonds, herstel geeft dezelfde grades) waren alleen in de
ontwikkelomgeving gemeten. Met D5, E2 en G4 heb je ze op de NAS zelf gecontroleerd. Bewaar
`nas-check-2.log`; stuur me de laatste 25 regels als er iets niet `OK` is.

### H2. Taalmodel met een echte sleutel testen 🗄️

Alleen als je een Anthropic-sleutel hebt ingevuld (A6):

```bash
cd /volume1/docker/graadmeter && docker compose exec server python -m app.cli explain bitcoin
```

Goed als je `"explanations_written": 1` ziet: 🌐 open dan Bitcoin in de app, onder *Toelichting* staat de nieuwe
tekst. Zie je `"explanations_rejected"` of `"explanations_template"`, dan heeft de controle de tekst afgekeurd
(bijvoorbeeld een getal dat niet in de cijfers stond) en toont de app de vaste sjabloontekst; dat is juist de
bedoeling. Een fout over de sleutel betekent dat `ANTHROPIC_API_KEY` ontbreekt of niet klopt (J7). Het verbruik in euro staat onder 🌐 **Instellingen** → *Taalmodel*.

### H3. Beslissing: Yahoo Finance als bron

De app haalt koersen van indices, ETF's, obligatie-ETF's, termijncontracten, ETC's en Europese aandelen bij
Yahoo Finance. Yahoo heeft daar geen officiële API voor en de voorwaarden staan geautomatiseerd ophalen niet
uitdrukkelijk toe. Kies:

1. **Zo laten.** Privégebruik, een paar honderd verzoeken per nacht. Risico: Yahoo blokkeert de NAS of wijzigt
   iets; de app meldt dat dan en toont de laatste grades met hun peildatum.
2. **Betaalde bron.** Met een EODHD-sleutel (vanaf ongeveer $20 per maand) komen de Europese aandelenkoersen
   daarvandaan: vul `EODHD_API_KEY` in (J7). Voor indices, ETF's en termijncontracten moet ik dan nog een
   koppeling bouwen; laat het me weten.

Laat me weten wat je kiest. Bij optie 1 hoef je niets te doen.

### H4. Ontbrekende gratis databronnen

Een aantal maatstaven blijft leeg omdat er geen gratis, toegestane bron voor is. De grades rekenen daar eerlijk
mee: de datadekking is lager en een pijler zonder data telt niet mee.

| Leeg | Gevolg | Wat kan |
| --- | --- | --- |
| Vastgoedfondsen (REIT): bezetting, AFFO, LTV | Geen grade voor REITs | Alleen met een betaalde bron |
| Banken: CET1 en probleemleningen | Pijler kapitaal leeg, gate CET1 "onbekend" | Alleen met een betaalde bron |
| Indices: winstrendement en CAPE | Pijler waardering leeg | Ik kan de gratis CAPE-reeks van Shiller koppelen (alleen S&P 500) |
| Obligaties: plek op de rentecurve | Eén maatstaf leeg | Ik kan dit uit de Amerikaanse rentecurve (FRED/US Treasury) berekenen |
| Aandelen: aankopen door insiders | Eén maatstaf leeg | Ik kan de SEC-formulieren 4 koppelen (gratis) |
| Analistenverwachtingen (revisies) | Pijler revisies leeg | Alleen met een betaalde bron |
| Crypto: unlocks, hacks | Gates "onbekend" | Zelf invullen, zie hieronder |
| Nieuws bij de analyse van missers | Analyse zonder nieuws | Marketaux (gratis sleutel, 100 per dag); ik kan het koppelen |

**Zelf invullen** (voor wat geen bron heeft) 🗄️, bijvoorbeeld het aandeel tokens dat binnen 90 dagen vrijkomt
(4%) of een onopgeloste hack:

```bash
cd /volume1/docker/graadmeter && docker compose exec server python -m app.cli set-fact arbitrum unlock_90d 0.04
```

```bash
cd /volume1/docker/graadmeter && docker compose exec server python -m app.cli set-fact arbitrum flag_unresolved_exploit 1
```

Het eerste woord na `set-fact` is de naam van de asset zoals in de adresbalk van de app
(`.../crypto/arbitrum`). De waarde telt vanaf de volgende nachtrun mee, met "handmatig" als bron.

### H5. Lettergrenzen ijken

Zie deel F. Het oude voorstel (nummer 3) hoort bij modelversie 0.5.0: wijs dat af op de pagina **Model**.

### H6. Fondskenmerken bijwerken (elk kwartaal)

Kosten, omvang en (bij obligaties) rendement, duration en ratings van ETF's komen uit twee bestanden die jij
bijhoudt: `config/etfs.csv` en `config/bond_etfs.csv`. Werk ze op de Mac bij, met de factsheet van de uitgever,
en vul bron en datum in. Obligatiecijfers ouder dan 200 dagen tellen niet meer mee. Daarna kopiëren 🖥️:

```bash
cd ~/Graadmeter && scp config/etfs.csv config/bond_etfs.csv "$NAS:/volume1/docker/graadmeter/config/" && git add config/*.csv && git commit -m "Update ETF facts" && git push
```

---

## I. Een nieuwe versie installeren

Als er een nieuwe versie van de code is:

🖥️ Ophalen en bouwen:

```bash
cd ~/Graadmeter && git pull && bash scripts/build-images.sh
```

🖥️ Kopiëren (de `.env` niet: die staat al op de NAS):

```bash
cd ~/Graadmeter && \
scp dist/graadmeter-images.tar.gz "$NAS:/volume1/docker/graadmeter/" && \
scp docker-compose.nas.yml "$NAS:/volume1/docker/graadmeter/docker-compose.yml" && \
scp -r config scripts "$NAS:/volume1/docker/graadmeter/" && echo "Gekopieerd"
```

Let op: dit overschrijft `config/` op de NAS. Heb je op de NAS een voorstel vastgelegd (F4)? Doe dan eerst F5,
zodat de Mac de nieuwste lettergrenzen heeft.

🗄️ Laden en herstarten (na `ssh "$NAS"` en `sudo -i`):

```bash
cd /volume1/docker/graadmeter && chmod +x scripts/*.sh && docker load -i graadmeter-images.tar.gz && docker compose up -d && sleep 60 && docker compose ps
```

De database wordt bij het starten vanzelf bijgewerkt. Een nieuwe modelversie verschijnt in de app vanaf de
volgende nachtrun. Opruimen van oude, ongebruikte images (maakt ruimte vrij):

```bash
docker image prune -f
```

---

## J. Problemen oplossen

**J1. `Permission denied` of `permission denied while trying to connect to the Docker daemon`.**
Je bent op de NAS geen beheerder: typ `sudo -i` en probeer opnieuw. Bij `mkdir` in C4: maak de map in DSM aan
via *File Station* → `docker` → *Maken* → *Map maken* → `graadmeter`.

**J2. De app laadt niet in de browser.** 🗄️

```bash
cd /volume1/docker/graadmeter && docker compose ps && docker compose logs --tail 50 server web
```

Staat een container op `Restarting` of `Exited`, dan zegt de laatste regel van de logs waarom. Veel voorkomend:
`set POSTGRES_PASSWORD in .env` of `set APP_PASSWORD in .env` (die regel ontbreekt in `.env`), of poort 3000 is
al in gebruik (zet `WEB_PORT=3001` in `.env`, dan `docker compose up -d`, en open poort 3001).

**J3. Rechtsboven staat "Systeem beperkt" of "Server offline".** Houd de muis erop: je ziet de stand van de
database en de planner. Herstart dan 🗄️ `docker compose restart db server` en kijk bij aanhoudende problemen in
de logs (J2).

**J4. Een bron geeft fouten.** 🌐 **Instellingen** → *Aanroepen per bron* toont de laatste fout per bron. `401` of `403`:
sleutel verkeerd of verlopen (J7). `429`: te veel verzoeken; de app wacht en probeert het de volgende nacht
opnieuw. Geen verbinding vanaf de NAS: test met

```bash
docker run --rm --entrypoint python graadmeter-server:latest -c "import httpx; print(httpx.get('https://api.coingecko.com/api/v3/ping', timeout=15).status_code)"
```

(200 is goed). Anders: *Configuratiescherm* → *Netwerk* → *Algemeen*: DNS-server bijvoorbeeld `1.1.1.1`.

**J5. Een taak met de hand opnieuw draaien.** 🌐 **Instellingen** → bij de taak **Nu draaien**. Of 🗄️ (namen:
`crypto`, `stocks`, `markets`, `commodities`, `fx_macro`):

```bash
cd /volume1/docker/graadmeter && docker compose exec server python -m app.cli run crypto
```

**J6. Inlogwachtwoord vergeten.** 🗄️ Bekijk het:

```bash
grep APP_PASSWORD /volume1/docker/graadmeter/.env
```

**J7. Een sleutel toevoegen of wijzigen.** 🗄️ Open `.env` in de editor van de NAS:

```bash
cd /volume1/docker/graadmeter && vi .env
```

In `vi`: ga met de pijltjes naar de regel, druk `i`, typ of plak de waarde tussen de aanhalingstekens
(bijvoorbeeld `TIINGO_API_KEY="abc123"`), druk `Esc`, typ `:wq` en Enter. Makkelijker: pas `.env` op de Mac aan
(`open -e ~/Graadmeter/.env`) en kopieer hem 🖥️ met `scp ~/Graadmeter/.env "$NAS:/volume1/docker/graadmeter/"`.
Daarna altijd 🗄️ (een herstart is niet genoeg, de containers moeten opnieuw worden aangemaakt):

```bash
cd /volume1/docker/graadmeter && docker compose up -d
```

**J8. Terugzetten na een ramp** (nieuwe NAS of een kapotte database). Zet eerst deel C en D1–D5 opnieuw op en
kopieer je back-upbestand (uit Hyper Backup) naar `/volume1/docker/graadmeter/backups/`. Dan 🗄️ (vervang de
bestandsnaam door die van jouw back-up; `ls backups` toont ze):

```bash
cd /volume1/docker/graadmeter && ls backups && scripts/restore.sh backups/graadmeter-20261015T020000Z.dump
```

Het script controleert het bestand, zet de database terug, start de app en rekent elke grade opnieuw uit. Goed
als het eindigt met `N snapshots herberekend, N exact gelijk, 0 afwijkend`.

**J9. De NAS wordt traag of het geheugen raakt op.** 🗄️ `docker stats --no-stream` toont het gebruik per
container. De terugtest (F1) gebruikt het meest; draai die 's nachts. Een DS920+ met 4 GB is genoeg; met een
extra geheugenmodule heb je meer ruimte.

**J10. Alles stoppen of weer starten.** 🗄️

```bash
cd /volume1/docker/graadmeter && docker compose stop
```

```bash
cd /volume1/docker/graadmeter && docker compose up -d
```

`docker compose down` mag ook: de data blijft in `data/postgres` staan. Verwijder die map nooit.

---

## K. Spiekbriefje

| Wat | Waar | Opdracht |
| --- | --- | --- |
| Inloggen op de NAS | 🖥️ | `ssh "$NAS"` en dan `sudo -i` en `cd /volume1/docker/graadmeter` |
| Status | 🗄️ | `docker compose ps` |
| Logboek server | 🗄️ | `docker compose logs --tail 100 server` |
| Taak nu draaien | 🗄️ | `docker compose exec server python -m app.cli run crypto` |
| Back-up nu | 🗄️ | `docker compose exec server python -m app.cli backup` |
| Hersteltest | 🗄️ | `docker compose exec server python -m app.cli restore-test` |
| Alle grades narekenen | 🗄️ | `docker compose exec server python -m app.cli verify` |
| Testmelding | 🗄️ | `docker compose exec server python -m app.cli notify-test` |
| Voorstel vastleggen | 🗄️ | `scripts/apply-proposal.sh <nummer>` |
| Herstarten na `.env`-wijziging | 🗄️ | `docker compose up -d` |

| Wat | Waar op de NAS |
| --- | --- |
| Alles van Graadmeter | `/volume1/docker/graadmeter` (in File Station: `docker` → `graadmeter`) |
| Instellingen en sleutels | `/volume1/docker/graadmeter/.env` |
| Het model, lijsten, bronnen | `/volume1/docker/graadmeter/config/` |
| Databasebestanden (niet aankomen) | `/volume1/docker/graadmeter/data/postgres/` |
| Back-ups | `/volume1/docker/graadmeter/backups/` |

Op de Mac staat alles in `~/Graadmeter` (Finder: Ga > Thuismap > Graadmeter).
