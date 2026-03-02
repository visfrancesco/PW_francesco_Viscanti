#!/bin/bash
# Generazione certificati TLS per ambiente di sviluppo
# Ref: docs/requisiti.md RNF-05, RI-01
#
# Genera:
#   - CA self-signed (ca.crt, ca.key)
#   - Certificato server EMQX (server.crt, server.key)
#   - Certificato client di esempio (client.crt, client.key)
#
# In produzione i certificati verranno emessi da una CA interna o Let's Encrypt.

set -e

CERT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAYS=365
SUBJ_CA="/C=IT/ST=Basilicata/L=Vulture/O=Tenuta Ferrante/OU=IoT/CN=Tenuta Ferrante CA"
SUBJ_SRV="/C=IT/ST=Basilicata/L=Vulture/O=Tenuta Ferrante/OU=IoT/CN=emqx"
SUBJ_CLI="/C=IT/ST=Basilicata/L=Vulture/O=Tenuta Ferrante/OU=Devices/CN=device-client"

echo "=== Generazione CA ==="
openssl genrsa -out "$CERT_DIR/ca.key" 2048
openssl req -new -x509 -days $DAYS -key "$CERT_DIR/ca.key" \
  -out "$CERT_DIR/ca.crt" -subj "$SUBJ_CA"

echo "=== Generazione certificato server EMQX ==="
openssl genrsa -out "$CERT_DIR/server.key" 2048
openssl req -new -key "$CERT_DIR/server.key" \
  -out "$CERT_DIR/server.csr" -subj "$SUBJ_SRV"
openssl x509 -req -days $DAYS -in "$CERT_DIR/server.csr" \
  -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" -CAcreateserial \
  -out "$CERT_DIR/server.crt"
rm -f "$CERT_DIR/server.csr"

echo "=== Generazione certificato client ==="
openssl genrsa -out "$CERT_DIR/client.key" 2048
openssl req -new -key "$CERT_DIR/client.key" \
  -out "$CERT_DIR/client.csr" -subj "$SUBJ_CLI"
openssl x509 -req -days $DAYS -in "$CERT_DIR/client.csr" \
  -CA "$CERT_DIR/ca.crt" -CAkey "$CERT_DIR/ca.key" -CAcreateserial \
  -out "$CERT_DIR/client.crt"
rm -f "$CERT_DIR/client.csr"

echo ""
echo "=== Certificati generati in $CERT_DIR ==="
ls -la "$CERT_DIR"/*.crt "$CERT_DIR"/*.key
echo ""
echo "CA:     $CERT_DIR/ca.crt"
echo "Server: $CERT_DIR/server.crt + server.key"
echo "Client: $CERT_DIR/client.crt + client.key"
