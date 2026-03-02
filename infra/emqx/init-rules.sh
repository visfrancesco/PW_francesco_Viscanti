#!/bin/sh
# Configura EMQX rule engine via REST API
# Ref: docs/requisiti.md sez. 7.3 (regole routing), UC-06 (alerting)
#
# Attende che EMQX sia pronto, poi crea:
#   1. Utenti di autenticazione
#   2. Regola ALT-01: alert gelata (T < 2°C)
#   3. Regola ALT-04: alert vento forte (V > 50 km/h)
#   4. Regola ALT-02: alert stress idrico (tensione > 80 kPa)
#
# La persistenza verso InfluxDB e gestita da bridge_influxdb.py
# (EMQX open-source non include il bridge InfluxDB nativo).

EMQX_API="http://emqx:18083/api/v5"
AUTH="admin-api-key:admin-api-secret"

echo "=== Attendo EMQX API... ==="
until curl -sf -u "$AUTH" "$EMQX_API/status" > /dev/null 2>&1; do
  echo "  EMQX non ancora pronto, riprovo tra 3s..."
  sleep 3
done
echo "=== EMQX API raggiungibile ==="

# ── 1. Utenti autenticazione ──────────────────────────────────────────

echo ""
echo "=== Creazione utenti ==="

for user in sensore valvola dashboard bridge suolo; do
  curl -sf -X POST -u "$AUTH" \
    -H "Content-Type: application/json" \
    "$EMQX_API/authentication/password_based%3Abuilt_in_database/users" \
    -d "{\"user_id\": \"$user\", \"password\": \"${user}123\"}" \
    && echo "  Utente '$user' creato" \
    || echo "  Utente '$user' gia esistente o errore"
done

# ── 2. Regola ALT-01: alert gelata ───────────────────────────────────
# T < 2°C → tenuta/alert/critico/gelata

echo ""
echo "=== Regola ALT-01: gelata ==="

curl -sf -X POST -u "$AUTH" \
  -H "Content-Type: application/json" \
  "$EMQX_API/rules" \
  -d '{
    "name": "alert_gelata",
    "sql": "SELECT payload.device_id AS device_id, payload.value AS value, payload.timestamp AS timestamp, nth(3, tokens(topic, '"'"'/'"'"')) AS parcella_id FROM \"tenuta/parcella/+/microclima/temperatura\" WHERE payload.value < 2",
    "enable": true,
    "description": "Alert gelata ALT-01: T < 2°C (UC-06)",
    "actions": [
      {
        "function": "republish",
        "args": {
          "topic": "tenuta/alert/critico/gelata",
          "qos": 1,
          "retain": false,
          "payload": "{\"alert\": \"ALT-01\", \"tipo\": \"gelata\", \"livello\": \"critico\", \"parcella\": \"${parcella_id}\", \"temperatura\": ${value}, \"device_id\": \"${device_id}\", \"timestamp\": \"${timestamp}\", \"messaggio\": \"Temperatura sotto 2°C: rischio gelata\"}"
        }
      }
    ]
  }' && echo "  OK" || echo "  gia esistente o errore"

# ── 3. Regola ALT-04: alert vento forte ──────────────────────────────
# V > 50 km/h → tenuta/alert/medio/vento

echo ""
echo "=== Regola ALT-04: vento forte ==="

curl -sf -X POST -u "$AUTH" \
  -H "Content-Type: application/json" \
  "$EMQX_API/rules" \
  -d '{
    "name": "alert_vento",
    "sql": "SELECT payload.device_id AS device_id, payload.value AS value, payload.timestamp AS timestamp, nth(3, tokens(topic, '"'"'/'"'"')) AS parcella_id FROM \"tenuta/parcella/+/microclima/vento\" WHERE payload.value > 50",
    "enable": true,
    "description": "Alert vento forte ALT-04: V > 50 km/h (UC-06)",
    "actions": [
      {
        "function": "republish",
        "args": {
          "topic": "tenuta/alert/medio/vento",
          "qos": 1,
          "retain": false,
          "payload": "{\"alert\": \"ALT-04\", \"tipo\": \"vento\", \"livello\": \"medio\", \"parcella\": \"${parcella_id}\", \"vento_kmh\": ${value}, \"device_id\": \"${device_id}\", \"timestamp\": \"${timestamp}\", \"messaggio\": \"Vento forte: velocita superiore a 50 km/h\"}"
        }
      }
    ]
  }' && echo "  OK" || echo "  gia esistente o errore"

# ── 4. Regola ALT-02: alert stress idrico ────────────────────────────
# Tensione > 80 kPa → tenuta/alert/alto/stress_idrico

echo ""
echo "=== Regola ALT-02: stress idrico ==="

curl -sf -X POST -u "$AUTH" \
  -H "Content-Type: application/json" \
  "$EMQX_API/rules" \
  -d '{
    "name": "alert_stress_idrico",
    "sql": "SELECT payload.device_id AS device_id, payload.value AS value, payload.timestamp AS timestamp, nth(3, tokens(topic, '"'"'/'"'"')) AS parcella_id FROM \"tenuta/parcella/+/suolo/+/tensione\" WHERE payload.value > 80",
    "enable": true,
    "description": "Alert stress idrico ALT-02: tensione > 80 kPa (UC-06)",
    "actions": [
      {
        "function": "republish",
        "args": {
          "topic": "tenuta/alert/alto/stress_idrico",
          "qos": 1,
          "retain": false,
          "payload": "{\"alert\": \"ALT-02\", \"tipo\": \"stress_idrico\", \"livello\": \"alto\", \"parcella\": \"${parcella_id}\", \"tensione_kpa\": ${value}, \"device_id\": \"${device_id}\", \"timestamp\": \"${timestamp}\", \"messaggio\": \"Stress idrico grave: tensione superiore a 80 kPa\"}"
        }
      }
    ]
  }' && echo "  OK" || echo "  gia esistente o errore"

echo ""
echo "=== Inizializzazione completata ==="
