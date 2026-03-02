#!/usr/bin/env python3
"""
Simulatore sensori microclima — Tenuta Ferrante
Ref: UC-01, RF-01, plan.md (Prototipo Minimo)

Pubblica dati per 12 parcelle × 6 tipi di sensore (temperatura, umidita,
vento, direzione vento, pioggia, radiazione solare). Ogni sensore ha
comportamento indipendente: jitter temporale, possibilita di disconnessione
e riconnessione casuale.

Uso:
    python sensore_microclima.py              # pubblicazione normale
    python sensore_microclima.py --gelata     # simula temperatura < 2°C (ALT-01)
"""

import argparse
import json
import math
import random
import signal
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from config import (
    AUTH_SENSORE,
    BROKER_HOST,
    BROKER_PORT,
    INTERVALLO_MICROCLIMA,
    PARCELLE,
    PARCELLE_IDS,
    QOS_TELEMETRIA,
    TEMP_BASE,
    TOPIC_MICROCLIMA,
    make_payload,
    read_sim_config,
)

TIPI_SENSORE = {
    "temperatura":     {"unit": "°C"},
    "umidita":         {"unit": "%"},
    "vento":           {"unit": "km/h"},
    "direzione_vento": {"unit": "°"},
    "pioggia":         {"unit": "mm"},
    "radiazione":      {"unit": "W/m²"},
}

# Probabilita che un singolo sensore si disconnetta ad ogni ciclo
P_DISCONNECT = 0.04
# Durata disconnessione: tra 30 e 120 secondi
DISCONNECT_MIN, DISCONNECT_MAX = 30, 120


class SensoreSim:
    """Stato di un singolo sensore con random walk e disconnessioni."""

    def __init__(self, parcella: dict, tipo: str):
        self.parcella = parcella
        self.tipo = tipo
        self.device_id = f"sensor-{parcella['id']}-{tipo}"

        # Valore iniziale realistico per zona/altitudine
        self.value = self._valore_iniziale()
        # Jitter: ogni sensore ha un offset casuale nel ciclo
        self.jitter = random.uniform(0, 2.0)
        # Stato connessione
        self.online = True
        self.reconnect_at = 0  # timestamp di riconnessione
        self.buffer = []  # letture accumulate durante offline (RNF-02)

    def _valore_iniziale(self) -> float:
        zona = self.parcella["zona"]
        alt = self.parcella["altitudine"]
        if self.tipo == "temperatura":
            base = TEMP_BASE[zona]
            # Variazione con altitudine: -0.6°C ogni 100m
            return base - (alt - 400) * 0.006 + random.uniform(-3, 3)
        elif self.tipo == "umidita":
            return {"alta": 70, "media": 60, "bassa": 50}[zona] + random.uniform(-10, 10)
        elif self.tipo == "vento":
            # Piu vento in quota
            return 5 + (alt - 400) * 0.05 + random.uniform(0, 10)
        elif self.tipo == "direzione_vento":
            # Venti prevalenti da ovest-sud-ovest sulle colline del Vulture
            return 225 + random.uniform(-45, 45)
        elif self.tipo == "radiazione":
            # Radiazione solare: zone basse (esposizione sud) piu irradiate
            base = {"alta": 400, "media": 550, "bassa": 650}[zona]
            return base + random.uniform(-100, 100)
        else:  # pioggia
            return random.uniform(0, 2)

    def _genera_valore(self, t: float, gelata: bool = False) -> float:
        """Genera il prossimo valore (random walk, ciclo diurno, ecc.)."""
        if gelata and self.tipo == "temperatura":
            self.value = random.uniform(-4.0, 1.5)
            return round(self.value, 1)

        if self.tipo == "temperatura":
            diurno = 2 * math.sin(t / 600 * 2 * math.pi)
            self.value += random.uniform(-0.08, 0.08)
            reading = self.value + diurno
            return round(max(-5, min(42, reading)), 1)
        elif self.tipo == "umidita":
            self.value += random.uniform(-0.3, 0.3)
            self.value = max(25, min(98, self.value))
            return round(self.value, 1)
        elif self.tipo == "vento":
            if random.random() < 0.02:
                return round(random.uniform(40, 65), 1)
            self.value += random.uniform(-0.4, 0.4)
            self.value = max(0, min(60, self.value))
            return round(self.value, 1)
        elif self.tipo == "direzione_vento":
            self.value += random.uniform(-1.0, 1.0)
            self.value = self.value % 360
            return round(self.value, 0)
        elif self.tipo == "radiazione":
            diurno = max(0, math.sin(t / 600 * 2 * math.pi))
            self.value += random.uniform(-5, 5)
            self.value = max(0, min(1000, self.value))
            reading = self.value * (0.3 + 0.7 * diurno)
            return round(max(0, reading), 0)
        else:  # pioggia
            if random.random() < 0.05:
                return round(random.uniform(0.2, 3), 1)
            self.value *= 0.95
            self.value += random.uniform(0, 0.1)
            return round(max(0, self.value), 1)

    def tick(self, t: float, gelata: bool = False) -> float | None:
        """Aggiorna valore e restituisce il reading, o None se offline."""
        now = time.time()

        # Offline: genera e bufferizza, controlla riconnessione
        if not self.online:
            value = self._genera_valore(t, gelata)
            ts = datetime.now(timezone.utc).isoformat()
            self.buffer.append((ts, value, "uncertain"))
            if now >= self.reconnect_at:
                self.online = True
            return None

        if random.random() < P_DISCONNECT:
            duration = random.uniform(DISCONNECT_MIN, DISCONNECT_MAX)
            self.online = False
            self.reconnect_at = now + duration
            return None

        return self._genera_valore(t, gelata)


def main():
    parser = argparse.ArgumentParser(description="Simulatore sensori microclima")
    parser.add_argument("--gelata", action="store_true",
                        help="Simula temperature sotto 2°C (trigger ALT-01)")
    parser.add_argument("--host", default=BROKER_HOST)
    parser.add_argument("--port", type=int, default=BROKER_PORT)
    parser.add_argument("--intervallo", type=int, default=INTERVALLO_MICROCLIMA)
    args = parser.parse_args()

    # Crea un oggetto sensore per ogni parcella × tipo
    sensori = []
    for p in PARCELLE:
        for tipo in TIPI_SENSORE:
            sensori.append(SensoreSim(p, tipo))

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"sim-microclima-{int(time.time()) % 100000}",
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(AUTH_SENSORE["username"], AUTH_SENSORE["password"])

    running = True

    def on_connect(client, userdata, connect_flags, reason_code, properties):
        if reason_code == 0:
            print(f"[microclima] Connesso a {args.host}:{args.port} — {len(sensori)} sensori")
        else:
            print(f"[microclima] Connessione fallita: {reason_code}")

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        print(f"[microclima] Disconnesso ({reason_code})")

    def stop(signum, frame):
        nonlocal running
        print("\n[microclima] Arresto...")
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    connect_properties = mqtt.Properties(mqtt.PacketTypes.CONNECT)
    connect_properties.SessionExpiryInterval = 86400  # 24h session persistence (RNF-02)

    print(f"[microclima] Connessione a {args.host}:{args.port}...")
    client.connect(args.host, args.port, keepalive=60, properties=connect_properties)
    client.loop_start()

    t_start = time.time()
    ciclo = 0

    try:
        while running:
            t = time.time() - t_start
            ciclo += 1
            online_count = 0
            offline_count = 0

            # Legge config per-parcella una volta per ciclo
            sim_cfg = read_sim_config()
            gelata_map = sim_cfg.get("microclima", {}).get("gelata", {})

            for s in sensori:
                # Jitter: piccolo ritardo casuale per non pubblicare tutti insieme
                time.sleep(s.jitter * 0.01)

                # CLI --gelata come override globale, altrimenti config per-parcella
                gelata = args.gelata or gelata_map.get(s.parcella["id"], False)
                value = s.tick(t, gelata=gelata)
                if value is None:
                    if s.online and s.buffer:
                        topic = TOPIC_MICROCLIMA.format(parcella=s.parcella["id"], tipo=s.tipo)
                        for ts, val, qual in s.buffer:
                            payload = make_payload(
                                device_id=s.device_id,
                                tipo=s.tipo,
                                value=val,
                                unit=TIPI_SENSORE[s.tipo]["unit"],
                                quality=qual,
                                metadata={"parcella": s.parcella["id"], "zona": s.parcella["zona"]},
                            )
                            payload["timestamp"] = ts
                            client.publish(topic, json.dumps(payload), qos=QOS_TELEMETRIA)
                        print(f"    [BUFFER] {s.device_id}: flush {len(s.buffer)} letture")
                        online_count += 1
                        s.buffer.clear()
                    else:
                        offline_count += 1
                    continue

                online_count += 1
                payload = make_payload(
                    device_id=s.device_id,
                    tipo=s.tipo,
                    value=value,
                    unit=TIPI_SENSORE[s.tipo]["unit"],
                    quality="good" if s.online else "uncertain",
                    metadata={"parcella": s.parcella["id"], "zona": s.parcella["zona"]},
                )
                topic = TOPIC_MICROCLIMA.format(parcella=s.parcella["id"], tipo=s.tipo)
                client.publish(topic, json.dumps(payload), qos=QOS_TELEMETRIA)

            gelata_count = sum(1 for v in gelata_map.values() if v)
            flag = " [GELATA]" if args.gelata else f" [gelata: {gelata_count}p]" if gelata_count else ""
            print(f"  ciclo {ciclo}: {online_count} online, {offline_count} offline{flag}")
            time.sleep(args.intervallo)
    finally:
        client.loop_stop()
        client.disconnect()
        print("[microclima] Disconnesso.")


if __name__ == "__main__":
    main()
