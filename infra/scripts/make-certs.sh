#!/usr/bin/env bash
# I4 E27 (docs/hld/71-i4-wave4.md §71.4, D32; scheme puml/i4-tls-edge-topology.puml): the local CA
# and the server certificate the `edge` service (Caddy, `infra/edge/Caddyfile`) serves on 443.
#
# Browsers grant the microphone only in a secure context, so a classroom PC opening
# http://<server-LAN-IP> gets no microphone; https with a certificate the PC trusts fixes that.
# There is no public CA inside a closed classroom contour, so this script makes a private one:
#
#   <out>/ca.crt      the local CA certificate — the ONE file the teacher installs on every
#                     classroom PC (docs/RUNBOOK.md, «HTTPS в классе»)
#   <out>/ca.key      the CA private key (0600). Never leaves this machine, never enters a container
#   <out>/server.crt  the server certificate, followed by ca.crt (the chain Caddy serves)
#   <out>/server.key  the server private key (0600), mounted read-only into `edge`
#
# SANs: localhost, 127.0.0.1, ::1, every --ip (default: this host's primary LAN IPv4, the source
# address of its default route) and every --host (default: `hostname`, plus `hostname -f` when it
# differs). A re-run KEEPS an existing CA and re-issues only the server certificate, so the
# classroom PCs never have to re-install anything when the server's address changes; --new-ca
# replaces the CA too (and then every PC must install the new ca.crt).
#
# <out> defaults to infra/certs/, which is git-ignored (infra/certs/.gitignore) — a private key is
# never committed (SPEC §41). Needs only `openssl` (1.1.1+ for `-addext`).
#
# Usage:
#   infra/scripts/make-certs.sh [--ip A.B.C.D]... [--host NAME]... [--out DIR] [--days N] [--new-ca]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT_DIR="${SCRIPT_DIR}/../certs"
# 825 days: the longest validity Apple platforms accept for a certificate from a private CA;
# Chrome and Firefox apply no shorter limit to a locally-installed root.
SERVER_DAYS=825
CA_DAYS=3650
NEW_CA=0
IPS=()
HOSTS=()

usage() {
  sed -n '/^# Usage:/,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip) IPS+=("${2:?--ip needs a value}"); shift 2 ;;
    --host) HOSTS+=("${2:?--host needs a value}"); shift 2 ;;
    --out) OUT_DIR="${2:?--out needs a value}"; shift 2 ;;
    --days) SERVER_DAYS="${2:?--days needs a value}"; shift 2 ;;
    --new-ca) NEW_CA=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "make-certs: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v openssl >/dev/null 2>&1 || { echo "make-certs: openssl not found on PATH" >&2; exit 1; }

if [[ ${#IPS[@]} -eq 0 ]]; then
  # The address other machines on the LAN reach this one at: the source of the default route.
  lan_ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}' | head -n 1 || true)"
  if [[ -n "${lan_ip}" ]]; then
    IPS+=("${lan_ip}")
  else
    echo "make-certs: could not detect the LAN IP; pass it with --ip" >&2
  fi
fi
if [[ ${#HOSTS[@]} -eq 0 ]]; then
  short_name="$(hostname 2>/dev/null || true)"
  full_name="$(hostname -f 2>/dev/null || true)"
  [[ -n "${short_name}" ]] && HOSTS+=("${short_name}")
  [[ -n "${full_name}" && "${full_name}" != "${short_name}" ]] && HOSTS+=("${full_name}")
fi

for ip in "${IPS[@]}"; do
  if ! [[ "${ip}" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ || "${ip}" == *:* ]]; then
    echo "make-certs: not an IP address: ${ip}" >&2
    exit 2
  fi
done

san="DNS:localhost,IP:127.0.0.1,IP:::1"
for host in "${HOSTS[@]}"; do
  [[ "${host}" == "localhost" ]] || san="${san},DNS:${host}"
done
for ip in "${IPS[@]}"; do
  [[ "${ip}" == "127.0.0.1" ]] || san="${san},IP:${ip}"
done

umask 077
mkdir -p "${OUT_DIR}"
OUT_DIR="$(cd "${OUT_DIR}" && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

if [[ "${NEW_CA}" == 1 || ! -s "${OUT_DIR}/ca.crt" || ! -s "${OUT_DIR}/ca.key" ]]; then
  openssl req -x509 -new -newkey rsa:3072 -nodes -sha256 -days "${CA_DAYS}" \
    -keyout "${OUT_DIR}/ca.key" -out "${OUT_DIR}/ca.crt" \
    -subj "/O=sim112 training simulator/CN=sim112 local CA" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" 2>/dev/null
  echo "make-certs: created a new local CA: ${OUT_DIR}/ca.crt"
else
  echo "make-certs: reusing the existing local CA: ${OUT_DIR}/ca.crt"
fi

cat >"${work}/server.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
subjectAltName=${san}
EOF

openssl req -new -newkey rsa:2048 -nodes -sha256 \
  -keyout "${work}/server.key" -out "${work}/server.csr" \
  -subj "/O=sim112 training simulator/CN=${HOSTS[0]:-localhost}" 2>/dev/null
openssl x509 -req -sha256 -days "${SERVER_DAYS}" \
  -in "${work}/server.csr" -CA "${OUT_DIR}/ca.crt" -CAkey "${OUT_DIR}/ca.key" \
  -set_serial "0x$(openssl rand -hex 16)" -extfile "${work}/server.ext" \
  -out "${work}/server-leaf.crt" 2>/dev/null
openssl verify -CAfile "${OUT_DIR}/ca.crt" "${work}/server-leaf.crt" >/dev/null

cat "${work}/server-leaf.crt" "${OUT_DIR}/ca.crt" >"${OUT_DIR}/server.crt"
mv "${work}/server.key" "${OUT_DIR}/server.key"
chmod 600 "${OUT_DIR}/ca.key" "${OUT_DIR}/server.key"
chmod 644 "${OUT_DIR}/ca.crt" "${OUT_DIR}/server.crt"

echo "make-certs: server certificate ${OUT_DIR}/server.crt"
echo "make-certs:   subjectAltName ${san}"
echo "make-certs:   valid ${SERVER_DAYS} days"
echo "make-certs: CA fingerprints (compare one on each classroom PC when installing ca.crt;"
echo "make-certs: the Windows certificate dialog shows the SHA-1 one as «Отпечаток»):"
openssl x509 -in "${OUT_DIR}/ca.crt" -noout -fingerprint -sha256 | sed 's/^/make-certs:   /'
openssl x509 -in "${OUT_DIR}/ca.crt" -noout -fingerprint -sha1 | sed 's/^/make-certs:   /'
