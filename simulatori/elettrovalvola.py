#!/usr/bin/env python3
"""
Simulatore elettrovalvola irrigazione — Tenuta Ferrante
Ref: UC-03, RF-02, plan.md (Prototipo Minimo)

Sottoscrive i comandi di irrigazione con QoS 2 (exactly-once) per 12 parcelle.
Alla ricezione di un comando:
  1. Pubblica stato "in_esecuzione"
  2. Simula esecuzione (delay 2-3 s)
  3. Pubblica ack con QoS 2
  4. Pubblica stato "completato"

Uso:
    python elettrovalvola.py
"""

import json
import random
import signal
import time

import paho.mqtt.client as mqtt

from config import (
    AUTH_VALVOLA,
    BROKER_HOST,
    BROKER_PORT,
    PARCELLE_IDS,
    QOS_COMANDI,
    TOPIC_IRRIGAZIONE_ACK,
    TOPIC_IRRIGAZIONE_CMD,
    TOPIC_IRRIGAZIONE_STATO,
    make_payload,
)

# Stato corrente delle valvole
_stato_valvole = {pid: "chiusa" for pid in PARCELLE_IDS}


def _pubblica_stato(client, parcella: str, stato: str):
    _stato_valvole[parcella] = stato
    payload = make_payload(
        device_id=f"valvola-{parcella}",
        tipo="stato_irrigazione",
        value=stato,
        unit="",
    )
    topic = TOPIC_IRRIGAZIONE_STATO.format(parcella=parcella)
    client.publish(topic, json.dumps(payload), qos=1, retain=True)
    print(f"  [{parcella}] stato → {stato}")


def _pubblica_ack(client, parcella: str, comando: dict):
    payload = make_payload(
        device_id=f"valvola-{parcella}",
        tipo="ack_irrigazione",
        value={
            "comando_ricevuto": comando.get("value"),
            "esito": "ok",
        },
        unit="",
    )
    topic = TOPIC_IRRIGAZIONE_ACK.format(parcella=parcella)
    client.publish(topic, json.dumps(payload), qos=QOS_COMANDI)
    print(f"  [{parcella}] ack inviato (QoS 2)")


def on_connect(client, userdata, connect_flags, reason_code, properties):
    if reason_code == 0:
        print("[valvola] Connesso al broker")
        # Subscribe a comandi irrigazione per tutte le parcelle
        topic = TOPIC_IRRIGAZIONE_CMD.format(parcella="+")
        client.subscribe(topic, qos=QOS_COMANDI)
        print(f"[valvola] Sottoscritto a {topic} (QoS {QOS_COMANDI})")

        # Pubblica stato iniziale retained per ogni parcella
        for pid in PARCELLE_IDS:
            _pubblica_stato(client, pid, _stato_valvole[pid])
    else:
        print(f"[valvola] Connessione fallita: {reason_code}")


def on_message(client, userdata, msg):
    """Gestisce i comandi di irrigazione ricevuti."""
    try:
        comando = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(f"[valvola] Payload non valido su {msg.topic}")
        return

    # Estrai parcella dal topic: tenuta/parcella/{parcella}/irrigazione/cmd
    parts = msg.topic.split("/")
    parcella = parts[2] if len(parts) >= 5 else "sconosciuta"
    azione = comando.get("value", "sconosciuta")

    print(f"\n[valvola] === COMANDO RICEVUTO ===")
    print(f"  parcella: {parcella}")
    print(f"  azione:   {azione}")
    print(f"  QoS:      {msg.qos}")

    # 1. Stato in_esecuzione
    _pubblica_stato(client, parcella, "in_esecuzione")

    # 2. Simula esecuzione (2-3 secondi)
    delay = random.uniform(2.0, 3.0)
    print(f"  esecuzione in corso ({delay:.1f}s)...")
    time.sleep(delay)

    # 3. Pubblica ack
    _pubblica_ack(client, parcella, comando)

    # 4. Stato finale
    stato_finale = "aperta" if azione == "apri" else "chiusa"
    _pubblica_stato(client, parcella, stato_finale)

    print(f"[valvola] === COMANDO COMPLETATO ===\n")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    print(f"[valvola] Disconnesso ({reason_code})")


def main():
    global client

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"sim-valvola-{int(time.time()) % 100000}",
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(AUTH_VALVOLA["username"], AUTH_VALVOLA["password"])

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    running = True

    def stop(signum, frame):
        nonlocal running
        print("\n[valvola] Arresto in corso...")
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    connect_properties = mqtt.Properties(mqtt.PacketTypes.CONNECT)
    connect_properties.SessionExpiryInterval = 86400  # 24h (RNF-02)

    print(f"[valvola] Connessione a {BROKER_HOST}:{BROKER_PORT}...")
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60, properties=connect_properties)

    client.loop_start()

    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        # Pubblica stato offline prima di disconnettersi
        for pid in PARCELLE_IDS:
            _pubblica_stato(client, pid, "offline")
        client.loop_stop()
        client.disconnect()
        print("[valvola] Disconnesso.")


if __name__ == "__main__":
    main()
