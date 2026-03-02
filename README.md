# Tenuta Ferrante — Middleware IoT per viticoltura di precisione

Infrastruttura message broker basata su EMQX per la gestione di sensori IoT, attuatori e una dashboard centralizzata su 12 parcelle vitate (80 ettari) nella zona delle Colline del Vulture, Basilicata.

Progetto di tesi di laurea — tutta la documentazione e il codice sono in italiano.

## Architettura

```
Sensori/Dispositivi → MQTT → EMQX Broker → Rule Engine → InfluxDB (serie temporali)
                                                        → Dashboard (WebSocket)
                                                        → Alerting (gelata, vento, stress)
```

**Stack**: EMQX 5.8 (open-source) · InfluxDB 2.7 · Python 3.12 · Nginx · Docker Compose

## Prerequisiti

- [Docker](https://docs.docker.com/get-docker/) e Docker Compose v2+
- Nessun altro requisito: tutto gira nei container

## Avvio rapido

```bash
cd infra
docker compose up -d
```

Questo avvia 5 servizi:

| Servizio | Porta | Descrizione |
|----------|-------|-------------|
| **emqx** | 1883, 8083, 18083 | Broker MQTT (TCP, WebSocket, Dashboard) |
| **influxdb** | 8087 | Database serie temporali |
| **init-rules** | — | Setup regole alert EMQX (one-shot) |
| **simulatori** | 9000 | Simulatori sensori + bridge InfluxDB |
| **dashboard** | **8080** | Interfaccia web |

Al primo avvio, EMQX e InfluxDB devono superare l'healthcheck (~30s), poi i simulatori partono automaticamente.

**Dashboard**: http://localhost:8080

**EMQX Dashboard**: http://localhost:18083 (credenziali: `admin` / `admin_tenuta`)

## Cosa simula

- **12 parcelle** su 3 zone altimetriche (alta 550-600m, media 450-550m, bassa 400-450m)
- **Microclima** (ogni 5s): temperatura, umidita, vento, direzione vento, pioggia, radiazione solare
- **Suolo** (ogni 15s): umidita suolo, temperatura suolo, pH, conducibilita elettrica, tensione — a 2 profondita (30cm, 60cm)
- **Elettrovalvole**: comandi irrigazione con QoS 2 (exactly-once delivery)
- **Disconnessioni casuali** con buffering locale: i sensori accumulano dati offline e li inviano alla riconnessione con `quality: "uncertain"`

## Scenari di alert

I simulatori supportano scenari configurabili dalla dashboard o da CLI:

```bash
# Simula gelata (temperatura < 2°C) — trigger ALT-01
cd simulatori
python sensore_microclima.py --gelata

# Simula stress idrico (tensione > 80 kPa) — trigger ALT-02
python sensore_suolo.py --stress
```

Le regole EMQX generano automaticamente alert su:
- **Gelata** (critico): temperatura < 2°C
- **Vento forte** (medio): vento > 50 km/h
- **Stress idrico** (alto): tensione suolo > 80 kPa

## Struttura del progetto

```
├── infra/
│   ├── docker-compose.yml      # Orchestrazione servizi
│   ├── emqx/
│   │   ├── emqx.conf           # Configurazione broker
│   │   ├── acl.conf            # ACL per topic MQTT
│   │   └── init-rules.sh       # Setup regole alert
│   └── certs/                  # Certificati TLS (sviluppo)
├── simulatori/
│   ├── config.py               # Configurazione condivisa (topic, QoS, parcelle)
│   ├── sensore_microclima.py   # Simulatore sensori clima
│   ├── sensore_suolo.py        # Simulatore sonde suolo
│   ├── elettrovalvola.py       # Simulatore elettrovalvole
│   ├── bridge_influxdb.py      # Bridge MQTT → InfluxDB
│   └── orchestrator.py         # API HTTP per controllo simulatori
├── dashboard/
│   ├── index.html              # Interfaccia web
│   ├── app.js                  # Client MQTT/WebSocket + grafici
│   └── nginx.conf              # Reverse proxy
└── docs/
    ├── requisiti.md            # Specifica requisiti completa
    └── rapporto_implementazione.md
```

## API simulatori

L'orchestrator espone un'API REST su porta 9000 (proxied dal dashboard su `/api/sim/`):

```
GET  /status            — stato dei simulatori
POST /start/{name}      — avvia (microclima, suolo, elettrovalvola)
POST /stop/{name}       — ferma
POST /start-all         — avvia tutti
POST /stop-all          — ferma tutti
GET  /parcelle-config   — configurazione scenari per-parcella
POST /parcelle-config   — toggle scenario (gelata, stress) per singola parcella
```

## Topic MQTT

```
tenuta/parcella/{id}/microclima/{tipo}          # QoS 0 — telemetria clima
tenuta/parcella/{id}/suolo/{profondita}/{tipo}  # QoS 0 — telemetria suolo
tenuta/parcella/{id}/irrigazione/cmd|stato|ack  # QoS 2 — comandi irrigazione
tenuta/alert/{livello}/{tipo}                   # QoS 1 — alert automatici
tenuta/sistema/heartbeat                        # QoS 0 — stato sistema
```

## Comandi utili

```bash
# Avvia tutto
cd infra && docker compose up -d

# Vedi i log dei simulatori
docker compose logs -f simulatori

# Ricostruisci dopo modifiche al codice Python
docker compose up -d --build simulatori

# Ferma tutto
docker compose down

# Ferma e cancella i dati persistenti
docker compose down -v
```
