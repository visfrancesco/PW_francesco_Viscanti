"""
Parametri condivisi per i simulatori della Tenuta Ferrante.
Ref: docs/requisiti.md sez. 2.2 (parcelle), 7.1 (topic), RI-04 (formato JSON)
"""

import json
import os
from datetime import datetime, timezone

# ── Broker ────────────────────────────────────────────────────────────

BROKER_HOST = os.environ.get("MQTT_HOST", "localhost")
BROKER_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# ── 12 Parcelle della Tenuta Ferrante (sez. 2.2) ─────────────────────
# Alte (550-600m): esposizione nord, terreni vulcanici, microclima fresco
# Medie (450-550m): esposizione variabile, terreni misti
# Basse (400-450m): esposizione sud, terreni argillosi, microclima caldo

PARCELLE = [
    {"id": "vigna_alta_01",    "nome": "Vigna Alta 1",    "zona": "alta",  "altitudine": 590, "vitigno": "Aglianico"},
    {"id": "vigna_alta_02",    "nome": "Vigna Alta 2",    "zona": "alta",  "altitudine": 570, "vitigno": "Aglianico"},
    {"id": "vigna_alta_03",    "nome": "Vigna Alta 3",    "zona": "alta",  "altitudine": 555, "vitigno": "Aglianico"},
    {"id": "vigna_alta_04",    "nome": "Vigna Alta 4",    "zona": "alta",  "altitudine": 560, "vitigno": "Moscato"},
    {"id": "vigna_media_01",   "nome": "Vigna Media 1",   "zona": "media", "altitudine": 520, "vitigno": "Aglianico"},
    {"id": "vigna_media_02",   "nome": "Vigna Media 2",   "zona": "media", "altitudine": 500, "vitigno": "Malvasia"},
    {"id": "vigna_media_03",   "nome": "Vigna Media 3",   "zona": "media", "altitudine": 480, "vitigno": "Aglianico"},
    {"id": "vigna_media_04",   "nome": "Vigna Media 4",   "zona": "media", "altitudine": 460, "vitigno": "Malvasia"},
    {"id": "vigna_bassa_01",   "nome": "Vigna Bassa 1",   "zona": "bassa", "altitudine": 440, "vitigno": "Aglianico"},
    {"id": "vigna_bassa_02",   "nome": "Vigna Bassa 2",   "zona": "bassa", "altitudine": 430, "vitigno": "Moscato"},
    {"id": "vigna_bassa_03",   "nome": "Vigna Bassa 3",   "zona": "bassa", "altitudine": 415, "vitigno": "Aglianico"},
    {"id": "vigna_bassa_04",   "nome": "Vigna Bassa 4",   "zona": "bassa", "altitudine": 405, "vitigno": "Malvasia"},
]

PARCELLE_IDS = [p["id"] for p in PARCELLE]

# Temperature base per zona (le alte sono piu fresche, le basse piu calde)
TEMP_BASE = {"alta": 12.0, "media": 16.0, "bassa": 20.0}

# ── Intervalli di pubblicazione (secondi) ─────────────────────────────
# In produzione: 300s (5 min) per microclima, 900s (15 min) per suolo.
# Per la demo si usa un intervallo accelerato.

INTERVALLO_MICROCLIMA = 5
INTERVALLO_SUOLO = 15

# ── Topic patterns (sez. 7.1) ────────────────────────────────────────

TOPIC_MICROCLIMA = "tenuta/parcella/{parcella}/microclima/{tipo}"
TOPIC_SUOLO = "tenuta/parcella/{parcella}/suolo/{profondita}/{tipo}"
TOPIC_IRRIGAZIONE_CMD = "tenuta/parcella/{parcella}/irrigazione/cmd"
TOPIC_IRRIGAZIONE_ACK = "tenuta/parcella/{parcella}/irrigazione/ack"
TOPIC_IRRIGAZIONE_STATO = "tenuta/parcella/{parcella}/irrigazione/stato"
TOPIC_ALERT = "tenuta/alert/{livello}/{tipo}"

# ── QoS per categoria (sez. 7.2) ─────────────────────────────────────

QOS_TELEMETRIA = 0
QOS_COMANDI = 2
QOS_ALERT = 1

# ── Autenticazione (dev) ─────────────────────────────────────────────

AUTH_SENSORE = {"username": "sensore", "password": "sensore123"}
AUTH_SUOLO = {"username": "suolo", "password": "suolo123"}
AUTH_VALVOLA = {"username": "valvola", "password": "valvola123"}
AUTH_DASHBOARD = {"username": "dashboard", "password": "dashboard123"}
AUTH_BRIDGE = {"username": "bridge", "password": "bridge123"}


# ── Config condiviso per scenari per-parcella ──────────────────────

SIM_CONFIG_PATH = os.environ.get("SIM_CONFIG_PATH", "/tmp/sim_config.json")


def read_sim_config() -> dict:
    """Legge la config per-parcella. Se il file non esiste o è corrotto, ritorna {}."""
    try:
        with open(SIM_CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def make_payload(device_id: str, tipo: str, value, unit: str,
                 quality: str = "good", metadata: dict | None = None) -> dict:
    """
    Costruisce un payload conforme a RI-04.
    """
    return {
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": tipo,
        "value": value,
        "unit": unit,
        "quality": quality,
        "metadata": metadata or {},
    }
