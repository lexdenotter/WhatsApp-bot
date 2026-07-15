# Huishoudbot 🤖 — Telegram + n8n + Gemini

Een chatbot voor het huishouden, voor twee personen in een Telegram-groepschat. De bot:

- houdt **gedeelde lijstjes** bij (boodschappen, klusjes, …) in gewoon Nederlands: *"zet melk en eieren op de boodschappenlijst"*, *"streep melk maar door"*;
- helpt **bedenken wat je gaat eten**, rekening houdend met jullie voorkeuren en wat je recent al at;
- haalt wekelijks de **aanbiedingen van Albert Heijn en Plus** op, meldt welke van jullie vaste boodschappen in de aanbieding zijn en gebruikt de aanbiedingen bij maaltijdsuggesties.

Alles draait gratis: de officiële Telegram Bot API kost niets, Google Gemini 2.5 Flash heeft een ruime gratis tier (±1.500 requests/dag — zat voor twee personen), n8n (community-editie) is gratis en zelf te hosten, en we draaien hem op een **Oracle Cloud Always Free VM** (blijvend gratis) met een gratis **DuckDNS**-subdomein.

> **Waarom een cloud-VM en geen Raspberry Pi?** Twee redenen: (1) n8n's Telegram-node werkt via een **webhook** — Telegram moet je server via internet met HTTPS kunnen bereiken, wat op een Pi thuis poort-doorschakeling + een geldig certificaat vereist; op een VPS met publiek IP is dat veel eenvoudiger. (2) n8n heeft al gauw een paar GB schijfruimte nodig — kleine SD-kaarten (zoals op een Pi 3) lopen daarmee snel vol. Oracle's Always Free-laag geeft je een ARM-VM met meer geheugen en schijfruimte, voor €0.

> **Waarom Telegram en geen WhatsApp?** WhatsApp vereist voor een bot altijd een extra telefoonnummer (en de onofficiële route kan tot blokkade van je nummer leiden). Telegram heeft een officiële, gratis bot-API zonder nummer.

## Architectuur

```
Telegram groepschat
   │  Telegram Trigger
   ▼
Whitelist + mention-filter (alleen jullie chat, alleen berichten aan de bot)
   ▼
AI Agent (Gemini 2.5 Flash, Nederlands, geheugen per chat)
   ├─ tool: lijsten       → Data Table 'items'
   ├─ tool: maaltijden    → Data Tables 'maaltijden' + 'voorkeuren'
   └─ tool: aanbiedingen  → Data Table 'aanbiedingen'
   ▼
Antwoord in de groep

Wekelijks (ma 08:00): aanbiedingen-workflow
   AH (ah.nl/bonus) + Plus (aggregator) → Data Table 'aanbiedingen'
   → match met vaak gekochte producten → weekbericht in de groep
```

Bestanden in deze repo:

| Bestand | Wat het is |
|---|---|
| `docker-compose.yml` | n8n + Caddy (automatisch HTTPS) op je VPS |
| `Caddyfile` | Reverse-proxy-configuratie voor Caddy |
| `workflows/huishoudbot.json` | Hoofdworkflow: Telegram ↔ AI-agent |
| `workflows/tool-lijsten.json` | Sub-workflow (tool): lijstjes beheren |
| `workflows/tool-maaltijden.json` | Sub-workflow (tool): maaltijdlog + voorkeuren |
| `workflows/tool-aanbiedingen.json` | Sub-workflow (tool): zoeken in aanbiedingen |
| `workflows/aanbiedingen-ophalen.json` | Wekelijkse workflow: AH + Plus ophalen |

---

## Installatie

### Stap 0 — Wat je nodig hebt

1. **Telegram-bot**: praat op Telegram met [@BotFather](https://t.me/BotFather) → `/newbot` → kies een naam en een gebruikersnaam (eindigt op `bot`). Bewaar de **bot-token**.
2. **Belangrijk — privacy mode uitzetten**: stuur BotFather `/setprivacy` → kies je bot → **Disable**. Anders ziet de bot in een groep alléén `/commando's` en geen `@mentions`. (Zit de bot al in de groep? Verwijder hem en voeg hem opnieuw toe, anders geldt de wijziging niet.)
3. **Gemini API-key**: ga naar [Google AI Studio](https://aistudio.google.com) → *Get API key* → maak een gratis key (geen creditcard nodig). Let op: op de gratis tier mag Google je prompts gebruiken voor training — voor boodschappenlijstjes doorgaans geen bezwaar, maar goed om te weten.
4. Een **Oracle Cloud Free Tier**-account met een Always Free VM (zie Stap 1) — de enige plek waar wél een creditcard voor nodig is (voor identiteitsverificatie; er wordt niets afgeschreven op de gratis laag).
5. Een gratis **DuckDNS**-subdomein (zie Stap 1).

### Stap 1 — VM aanmaken op Oracle Cloud

1. Ga naar [cloud.oracle.com/free](https://www.oracle.com/cloud/free/) en maak een account aan (creditcard nodig voor verificatie, kies een regio dicht bij Nederland, bijv. *Germany Central (Frankfurt)* of *Netherlands Northwest (Amsterdam)* als die beschikbaar is).
2. Ga naar **Compute → Instances → Create instance**.
3. Kies bij **Image and shape** → *Change shape* → **Ampere (ARM)** → shape `VM.Standard.A1.Flex` → bijv. **2 OCPU / 12GB RAM** (dit valt binnen de Always Free-limiet van in totaal 4 OCPU/24GB).
4. Kies een Ubuntu-image (bijv. *Canonical Ubuntu 24.04*).
5. Bij **Add SSH keys**: laat Oracle een sleutelpaar genereren en **download de private key** (of upload je eigen publieke sleutel als je die al hebt).
6. Klik **Create**. Wacht tot de instance status "Running" toont en noteer het **publieke IP-adres**.
7. **Maak het IP-adres vast** (voorkomt dat het wijzigt): ga naar je instance → *Attached VNICs* → je VNIC → *IP Management* → de publieke IP → **Edit** → koppel een **Reserved Public IP** (ook onderdeel van de Always Free-laag).
8. **Open de poorten 80 en 443** (nodig voor HTTPS): ga naar je instance → *Subnet* → *Security Lists* → de default security list → **Add Ingress Rules** → tweemaal toevoegen: Source CIDR `0.0.0.0/0`, IP Protocol TCP, Destination Port `80`, en hetzelfde voor poort `443`.

### Stap 2 — Gratis domein via DuckDNS

1. Ga naar [duckdns.org](https://www.duckdns.org) en log in (bijv. met je Google-account).
2. Kies een subdomein, bijv. `huishoudbot` → dit wordt `huishoudbot.duckdns.org`.
3. Vul bij **current ip** het publieke (reserved) IP-adres van je Oracle-VM in en klik **update ip**.

### Stap 3 — Inloggen op de VM en n8n starten

Log in via SSH (vervang het pad naar je private key en het IP):

```bash
chmod 600 ~/Downloads/ssh-key.key
ssh -i ~/Downloads/ssh-key.key ubuntu@<publiek-ip-van-je-vm>
```

Installeer Docker (Ubuntu):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

Clone de repo en configureer:

```bash
git clone https://github.com/lexdenotter/WhatsApp-bot.git
cd WhatsApp-bot
cp .env.example .env
nano .env   # zet N8N_HOST op je eigen DuckDNS-domein, bijv. huishoudbot.duckdns.org
```

Start alles:

```bash
docker compose up -d
docker compose ps
```

Caddy vraagt bij de eerste start automatisch een geldig HTTPS-certificaat aan bij Let's Encrypt voor je domein — dit duurt meestal enkele seconden tot een paar minuten. Open daarna:

```
https://<jouw-domein>.duckdns.org
```

en maak het n8n-beheeraccount aan.

> **Werkt het niet meteen?** Check `docker compose logs caddy` — de meest voorkomende oorzaak is dat het DNS-record van DuckDNS nog niet is doorgevoerd (kan een paar minuten duren) of dat poort 80/443 nog niet openstaat in de security list (stap 1.8).

### Stap 4 — Credentials invoeren in n8n

In n8n: **Credentials → Add credential**:

1. **Telegram API** → plak de bot-token van BotFather. Noem hem bijv. *Telegram Huishoudbot*.
2. **Google Gemini (PaLM) API** → plak de key uit AI Studio. Noem hem bijv. *Google Gemini (gratis tier)*.

### Stap 5 — Data Tables aanmaken

In n8n: **Data tables** (linkermenu) → maak deze vier tabellen aan, alle kolommen van het type *string/tekst*:

| Tabel | Kolommen |
|---|---|
| `items` | `lijst`, `tekst`, `klaar`, `toegevoegd_door`, `datum` |
| `maaltijden` | `gerecht`, `gegeten_op` |
| `voorkeuren` | `sleutel`, `waarde` |
| `aanbiedingen` | `winkel`, `product`, `prijs`, `korting`, `geldig_tot`, `opgehaald_op` |

### Stap 6 — Workflows importeren

**Aanbevolen: via de CLI** (behoudt de onderlinge verwijzingen tussen de workflows):

```bash
docker compose exec n8n n8n import:workflow --separate --input=/workflows
```

Ververs daarna de n8n-pagina; je ziet vijf workflows staan (allemaal nog inactief).

*Alternatief via de UI:* importeer elk bestand uit `workflows/` met **Workflow → Import from file**. Let op: dan krijgen de workflows nieuwe id's en moet je in de hoofdworkflow de drie **Tool:**-nodes openen en daar de juiste sub-workflow opnieuw selecteren.

### Stap 7 — Nodes koppelen (na-import-checklist)

Loop deze lijst af; het zijn klikjes, geen code:

- [ ] **Workflow "Huishoudbot"**: open *Telegram Trigger* en *Stuur antwoord* → selecteer je Telegram-credential. Open *Gemini 2.5 Flash* → selecteer je Gemini-credential.
- [ ] **Alle nodes met de notitie "Selecteer hier de tabel …"** (in de tool-workflows en de aanbiedingen-workflow): open de node en kies de juiste Data Table uit de dropdown.
- [ ] **Workflow "Huishoudbot" → node "Instellingen"**: vul `botUsername` in (de gebruikersnaam van je bot, zonder `@`). `allowedChatIds` mag je nog even leeg laten — zie stap 8.
- [ ] **Workflow "aanbiedingen ophalen"**: selecteer de Telegram- en Gemini-credentials in de betreffende nodes.

### Stap 8 — Groep aanmaken en whitelisten

1. Maak een Telegram-groep met jullie tweeën en voeg de bot toe.
2. **Activeer** de workflow "Huishoudbot" (schuifje rechtsboven).
3. Stuur in de groep een berichtje naar de bot (bijv. `/start`). Omdat de whitelist nog leeg is, antwoordt de bot met het **chat-id** van de groep.
4. Zet dat chat-id in de node **Instellingen** → `allowedChatIds` (meerdere id's scheiden met komma's, bijv. ook je privéchat met de bot) en sla op.
5. Vul hetzelfde chat-id in bij **"aanbiedingen ophalen" → node "Instellingen aanbiedingen"** en activeer ook die workflow.

### Stap 9 — Testen

In de groep (noem de bot met `@botnaam`, of antwoord op een bericht van de bot):

```
@huishoudbot zet melk, eieren en brood op de boodschappenlijst
@huishoudbot wat staat er op de lijst?
@huishoudbot melk is binnen
@huishoudbot wat eten we vandaag? we willen max 30 minuten koken
@huishoudbot we eten vanavond lasagne
@huishoudbot is er kip in de aanbieding?
```

Draai de workflow **"aanbiedingen ophalen"** één keer handmatig (*Execute workflow*) zodat de aanbiedingen-tabel gevuld is; daarna gebeurt dat automatisch elke maandag om 08:00.

---

## Hoe de aanbiedingen werken (en een eerlijke kanttekening)

- **Albert Heijn**: de workflow leest de bonusdata die ah.nl zelf in de pagina insluit (`window.__INITIAL_STATE__`).
- **Plus**: plus.nl rendert client-side, daarom halen we de Plus-aanbiedingen van een server-gerenderde aggregatorpagina en laat de workflow **Gemini** de aanbiedingen uit de tekst halen.

⚠️ Beide bronnen zijn **onofficieel**. Als AH of de aggregator de sitestructuur wijzigt, kan het ophalen breken — de workflow stuurt dan een foutmelding naar jullie groep (hij faalt dus niet stilletjes). De parse-logica zit in de Code-nodes `AH parsen` en `Plus HTML naar tekst`; daar is hij ook aan te passen.

Het **weekbericht** meldt hoeveel aanbiedingen er zijn opgehaald en welke producten die jullie vaak kopen (2+ keer op de boodschappenlijst gestaan) nu in de aanbieding zijn. Bij *"wat eten we deze week?"* betrekt de bot de aanbiedingen bij zijn recepten.

## Kosten & limieten

| Onderdeel | Kosten |
|---|---|
| Telegram Bot API | Gratis, onbeperkt |
| Gemini 2.5 Flash (gratis tier) | Gratis, ±1.500 requests/dag — de bot gebruikt er hooguit een handvol per bericht |
| n8n community-editie (self-hosted) | Gratis |
| Oracle Cloud Always Free VM | Gratis, blijvend (geen verlopende proefperiode) |
| DuckDNS-domein | Gratis |

Als het Gemini-dagquotum op is, krijg je een foutmelding in n8n; de volgende dag doet de bot het weer. (Limieten wijzigen weleens — check [AI Studio](https://aistudio.google.com) voor de actuele waarden.)

## Problemen oplossen

| Symptoom | Oorzaak / oplossing |
|---|---|
| `docker compose up -d` geeft "permission denied" bij de Docker-socket | Je gebruiker zit niet in de `docker`-groep → `sudo usermod -aG docker $USER && newgrp docker` |
| Caddy krijgt geen certificaat / `https://` werkt niet | Check `docker compose logs caddy`. Vaak: DuckDNS-record nog niet doorgevoerd (wacht een paar minuten en check met `nslookup <jouw-domein>.duckdns.org`), of poort 80/443 staat niet open in de Oracle security list (stap 1.8) |
| Bot reageert niet op `@mentions` in de groep | Privacy mode staat nog aan → BotFather `/setprivacy` → Disable → bot uit de groep verwijderen en opnieuw toevoegen |
| Bot reageert helemaal niet | Is de workflow "Huishoudbot" **actief**? Staat het juiste chat-id in `allowedChatIds`? Kijk in n8n bij *Executions* wat er gebeurt |
| Fout in een Data Table-node | Open de node en controleer of de juiste tabel geselecteerd is en de kolomnamen overeenkomen met stap 5 |
| "Tool: …"-node geeft een fout over de workflow | De sub-workflow-verwijzing klopt niet (gebeurt bij import via de UI) → open de node en selecteer de juiste sub-workflow |
| Aanbiedingen ophalen mislukt | Zie de foutmelding in de groep + *Executions*; waarschijnlijk is de sitestructuur gewijzigd → pas de parse-Code-node aan |
| Antwoorden zijn traag | Normaal: elke vraag is 1–3 Gemini-calls. De directe paden (`/help`, chat-id) zijn instant |
| n8n-container crasht steeds opnieuw met een foutmelding over het configbestand | Meestal een gevolg van een eerdere volle schijf (ENOSPC) die het configbestand corrumpeerde → `docker compose down`, verwijder het volume met `docker volume rm whatsapp-bot_n8n_data` (naam kan verschillen, check met `docker volume ls`) en start opnieuw met `docker compose up -d` |

## Ideeën voor later

- Wekelijks automatisch een weekmenu voorstellen (extra Schedule-workflow die de agent aanroept).
- Jumbo/Lidl toevoegen aan de aanbiedingen-workflow.
- Recept gekozen → ingrediënten automatisch op de boodschappenlijst (kan de agent nu al op verzoek; een knop/commando ervan maken).
- Repo hernoemen naar `household-bot` (het is tenslotte geen WhatsApp meer 😄).
