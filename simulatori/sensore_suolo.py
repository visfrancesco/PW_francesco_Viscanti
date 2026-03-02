#!/usr/bin/env python3
"""
Simulatore sensori suolo — Tenuta Ferrante
Ref: UC-02, RF-01, plan.md (Prototipo Minimo)

Pubblica dati per 12 parcelle × 2 profondità (30cm, 60cm) × 5 tipi di sensore
(umidità suolo, temperatura suolo, pH, conducibilità elettrica, tensione).
Ogni sensore ha comportamento indipendente con random walk, jitter e
disconnessioni casuali.

Uso:
    python sensore_suolo.py
    python sensore_suolo.py --stress    # simula tensione > 80 kPa (ALT-02)
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
    AUTH_SUOLO,
    BROKER_HOST,
    BROKER_PORT,
    INTERVALLO_SUOLO,
    PARCELLE,
    QOS_TELEMETRIA,
    TOPIC_SUOLO,
    make_payload,
    read_sim_config,
)

TIPI_SENSORE = {
    "umidita_suolo":    {"unit": "%VWC"},
    "temperatura_suolo": {"unit": "°C"},
    "ph":               {"unit": "pH"},
    "conducibilita":    {"unit": "dS/m"},
    "tensione":         {"unit": "kPa"},
}

PROFONDITA = ["30cm", "60cm"]

# Disconnessione: probabilità per ciclo e durata
P_DISCONNECT = 0.03
DISCONNECT_MIN, DISCONNECT_MAX = 45, 180


class SondaSuoloSim:
    """Stato di un singolo sensore suolo con random walk e disconnessioni."""

    def __init__(self, parcella: dict, profondita: str, tipo: str):
        self.parcella = parcella
        self.profondita = profondita
        self.tipo = tipo
        self.device_id = f"sonda-{parcella['id']}-{profondita}-{tipo}"

        self.value = self._valore_iniziale()
        self.jitter = random.uniform(0, 3.0)
        self.online = True
        self.reconnect_at = 0
        self.buffer = []  # letture accumulate durante offline (RNF-02)

    def _valore_iniziale(self) -> float:
        zona = self.parcella["zona"]
        prof_deep = self.profondita == "60cm"

        if self.tipo == "umidita_suolo":
            # Più umidità in profondità e nelle zone alte
            base = {"alta": 35, "media": 28, "bassa": 22}[zona]
            if prof_deep:
                base += 10
            return base + random.uniform(-5, 5)

        elif self.tipo == "temperatura_suolo":
            # Suolo più caldo nelle zone basse; in profondità più stabile e vicino alla media annua
            base = {"alta": 11.0, "media": 14.0, "bassa": 17.0}[zona]
            if prof_deep:
                base = base * 0.7 + 14.0 * 0.3  # tende verso la media annua (~14°C)
            return base + random.uniform(-1.5, 1.5)

        elif self.tipo == "ph":
            # Terreni vulcanici (zone alte) più acidi, argillosi (basse) più neutri
            base = {"alta": 5.8, "media": 6.5, "bassa": 7.0}[zona]
            return base + random.uniform(-0.3, 0.3)

        elif self.tipo == "conducibilita":
            # EC: terreni vulcanici più ricchi di minerali
            base = {"alta": 1.8, "media": 1.2, "bassa": 0.8}[zona]
            return base + random.uniform(-0.3, 0.3)

        else:  # tensione
            # kPa: 0-10 saturo, 10-30 ottimale, 30-60 secco, >80 stress
            base = {"alta": 20, "media": 30, "bassa": 40}[zona]
            if prof_deep:
                base -= 8
            return base + random.uniform(-10, 10)

    def _genera_valore(self, t: float, stress: bool = False) -> float:
        """Genera il prossimo valore (random walk lento, tipico del suolo)."""
        if stress and self.tipo == "tensione":
            self.value = random.uniform(75.0, 95.0)
            return round(self.value, 1)

        if self.tipo == "umidita_suolo":
            diurno = -1 * math.sin(t / 900 * 2 * math.pi)
            self.value += random.uniform(-0.1, 0.1)
            reading = self.value + diurno
            return round(max(5, min(60, reading)), 1)

        elif self.tipo == "temperatura_suolo":
            attenuazione = 0.3 if self.profondita == "60cm" else 1.0
            diurno = 0.5 * attenuazione * math.sin(t / 900 * 2 * math.pi)
            self.value += random.uniform(-0.02, 0.02)
            reading = self.value + diurno
            return round(max(2, min(30, reading)), 1)

        elif self.tipo == "ph":
            self.value += random.uniform(-0.005, 0.005)
            self.value = max(4.5, min(8.5, self.value))
            return round(self.value, 2)

        elif self.tipo == "conducibilita":
            self.value += random.uniform(-0.01, 0.01)
            self.value = max(0.1, min(4.0, self.value))
            return round(self.value, 2)

        else:  # tensione
            self.value += random.uniform(-0.1, 0.3)
            self.value = max(0, min(100, self.value))
            return round(self.value, 1)

    def tick(self, t: float, stress: bool = False) -> float | None:
        """Aggiorna valore e restituisce il reading, o None se offline."""
        now = time.time()

        # Offline: genera e bufferizza, controlla riconnessione
        if not self.online:
            value = self._genera_valore(t, stress)
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

        return self._genera_valore(t, stress)


def main():
    parser = argparse.ArgumentParser(description="Simulatore sensori suolo")
    parser.add_argument("--stress", action="store_true",
                        help="Simula tensione > 80 kPa (trigger ALT-02)")
    parser.add_argument("--host", default=BROKER_HOST)
    parser.add_argument("--port", type=int, default=BROKER_PORT)
    parser.add_argument("--intervallo", type=int, default=INTERVALLO_SUOLO)
    args = parser.parse_args()

    # Crea un sensore per ogni parcella × profondità × tipo
    sonde = []
    for p in PARCELLE:
        for prof in PROFONDITA:
            for tipo in TIPI_SENSORE:
                sonde.append(SondaSuoloSim(p, prof, tipo))

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"sim-suolo-{int(time.time()) % 100000}",
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(AUTH_SUOLO["username"], AUTH_SUOLO["password"])

    running = True

    def on_connect(client, userdata, connect_flags, reason_code, properties):
        if reason_code == 0:
            print(f"[suolo] Connesso a {args.host}:{args.port} — {len(sonde)} sonde")
        else:
            print(f"[suolo] Connessione fallita: {reason_code}")

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        print(f"[suolo] Disconnesso ({reason_code})")

    def stop(signum, frame):
        nonlocal running
        print("\n[suolo] Arresto...")
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    connect_properties = mqtt.Properties(mqtt.PacketTypes.CONNECT)
    connect_properties.SessionExpiryInterval = 86400

    print(f"[suolo] Connessione a {args.host}:{args.port}...")
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
            stress_map = sim_cfg.get("suolo", {}).get("stress", {})

            for s in sonde:
                time.sleep(s.jitter * 0.005)

                # CLI --stress come override globale, altrimenti config per-parcella
                stress = args.stress or stress_map.get(s.parcella["id"], False)
                value = s.tick(t, stress=stress)
                if value is None:
                    if s.online and s.buffer:
                        topic = TOPIC_SUOLO.format(
                            parcella=s.parcella["id"],
                            profondita=s.profondita,
                            tipo=s.tipo,
                        )
                        for ts, val, qual in s.buffer:
                            payload = make_payload(
                                device_id=s.device_id,
                                tipo=s.tipo,
                                value=val,
                                unit=TIPI_SENSORE[s.tipo]["unit"],
                                quality=qual,
                                metadata={
                                    "parcella": s.parcella["id"],
                                    "zona": s.parcella["zona"],
                                    "profondita": s.profondita,
                                },
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
                    metadata={
                        "parcella": s.parcella["id"],
                        "zona": s.parcella["zona"],
                        "profondita": s.profondita,
                    },
                )
                topic = TOPIC_SUOLO.format(
                    parcella=s.parcella["id"],
                    profondita=s.profondita,
                    tipo=s.tipo,
                )
                client.publish(topic, json.dumps(payload), qos=QOS_TELEMETRIA)

            stress_count = sum(1 for v in stress_map.values() if v)
            flag = " [STRESS]" if args.stress else f" [stress: {stress_count}p]" if stress_count else ""
            print(f"  ciclo {ciclo}: {online_count} online, {offline_count} offline{flag}")
            time.sleep(args.intervallo)
    finally:
        client.loop_stop()
        client.disconnect()
        print("[suolo] Disconnesso.")


if __name__ == "__main__":
    main()
