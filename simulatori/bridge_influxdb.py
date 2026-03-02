#!/usr/bin/env python3
"""
Bridge MQTT → InfluxDB — Tenuta Ferrante
Ref: RF-04, plan.md sez. 7.4 (bridge storage)

Sottoscrive i topic dei sensori e persiste i dati in InfluxDB.
Sostituisce il bridge nativo di EMQX (disponibile solo in Enterprise)
con un microservizio Python equivalente.

Uso:
    python bridge_influxdb.py
"""

import json
import os
import signal
import time

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from config import BROKER_HOST, BROKER_PORT

# ── InfluxDB config ───────────────────────────────────────────────────

INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8087")
INFLUXDB_TOKEN = "dev-token-tenuta-ferrante"
INFLUXDB_ORG = "tenuta-ferrante"
INFLUXDB_BUCKET = "sensori"

# ── MQTT topics da persistere ─────────────────────────────────────────

TOPICS = [
    ("tenuta/parcella/+/microclima/#", 0),
    ("tenuta/parcella/+/suolo/#", 0),
    ("tenuta/parcella/+/irrigazione/stato", 1),
    ("tenuta/alert/#", 1),
]


def main():
    influx = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
    write_api = influx.write_api(write_options=SYNCHRONOUS)

    write_count = 0

    def on_connect(client, userdata, connect_flags, reason_code, properties):
        if reason_code == 0:
            print("[bridge] Connesso al broker EMQX")
            for topic, qos in TOPICS:
                client.subscribe(topic, qos=qos)
                print(f"  sottoscritto: {topic} (QoS {qos})")
        else:
            print(f"[bridge] Connessione fallita: {reason_code}")

    def on_message(client, userdata, msg):
        nonlocal write_count
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        parts = msg.topic.split("/")

        # tenuta/parcella/{id}/microclima/{tipo}
        if len(parts) >= 5 and parts[3] == "microclima":
            parcella = parts[2]
            tipo = parts[4]
            value = payload.get("value")
            if value is None:
                return

            point = (
                Point("microclima")
                .tag("parcella", parcella)
                .tag("tipo", tipo)
                .tag("device", payload.get("device_id", ""))
                .field("value", float(value))
                .time(payload.get("timestamp"))
            )
            write_api.write(bucket=INFLUXDB_BUCKET, record=point)
            write_count += 1

            if write_count % 12 == 0:
                print(f"[bridge] {write_count} punti scritti in InfluxDB")

        # tenuta/parcella/{id}/suolo/{profondita}/{tipo}
        elif len(parts) >= 6 and parts[3] == "suolo":
            parcella = parts[2]
            profondita = parts[4]
            tipo = parts[5]
            value = payload.get("value")
            if value is None:
                return

            point = (
                Point("suolo")
                .tag("parcella", parcella)
                .tag("profondita", profondita)
                .tag("tipo", tipo)
                .tag("device", payload.get("device_id", ""))
                .field("value", float(value))
                .time(payload.get("timestamp"))
            )
            write_api.write(bucket=INFLUXDB_BUCKET, record=point)
            write_count += 1

            if write_count % 12 == 0:
                print(f"[bridge] {write_count} punti scritti in InfluxDB")

        # tenuta/parcella/{id}/irrigazione/stato
        elif len(parts) >= 5 and parts[3] == "irrigazione":
            parcella = parts[2]
            point = (
                Point("irrigazione")
                .tag("parcella", parcella)
                .tag("device", payload.get("device_id", ""))
                .field("stato", str(payload.get("value", "")))
                .time(payload.get("timestamp"))
            )
            write_api.write(bucket=INFLUXDB_BUCKET, record=point)

        # tenuta/alert/{livello}/{tipo}
        elif len(parts) >= 4 and parts[1] == "alert":
            livello = parts[2] if len(parts) > 2 else "sconosciuto"
            tipo_alert = parts[3] if len(parts) > 3 else "sconosciuto"
            point = (
                Point("alert")
                .tag("livello", livello)
                .tag("tipo", tipo_alert)
                .tag("parcella", payload.get("parcella", ""))
                .field("messaggio", payload.get("messaggio", ""))
                .time(payload.get("timestamp"))
            )
            # Valore numerico dal campo specifico dell'alert
            for campo in ("temperatura", "velocita_vento", "tensione"):
                if campo in payload:
                    point = point.field("valore", float(payload[campo]))
                    break
            write_api.write(bucket=INFLUXDB_BUCKET, record=point)

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        print(f"[bridge] Disconnesso ({reason_code})")

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"bridge-influxdb-{int(time.time()) % 100000}",
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set("bridge", "bridge123")

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    running = True

    def stop(signum, frame):
        nonlocal running
        print("\n[bridge] Arresto in corso...")
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    print(f"[bridge] Connessione a {BROKER_HOST}:{BROKER_PORT}...")
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        influx.close()
        print(f"[bridge] Chiuso. Totale punti scritti: {write_count}")


if __name__ == "__main__":
    main()
