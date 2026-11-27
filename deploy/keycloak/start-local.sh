#!/usr/bin/env bash
set -Eeuo pipefail

: "${KC_BOOTSTRAP_ADMIN_USERNAME:?Local Keycloak admin username is required}"
: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?Local Keycloak admin password is required}"
: "${OIDC_CLIENT_SECRET:?Local OIDC client secret is required}"
: "${OIDC_DEV_AGENT_PASSWORD:?Local agent password is required}"
: "${OIDC_DEV_REVIEWER_PASSWORD:?Local reviewer password is required}"
: "${OIDC_DEV_CUSTOMER_IDS:?Local customer ID list is required}"

if [[ ! "$OIDC_DEV_CUSTOMER_IDS" =~ ^[1-9][0-9]*(,[1-9][0-9]*)*$ ]]; then
  echo "OIDC_DEV_CUSTOMER_IDS must be comma-separated positive integer IDs" >&2
  exit 1
fi

/opt/keycloak/bin/kc.sh start-dev --import-realm &
keycloak_pid=$!
echo "$keycloak_pid" > /tmp/keycloak.pid
trap 'kill -TERM "$keycloak_pid" 2>/dev/null || true; wait "$keycloak_pid" || true' TERM INT

authenticated=false
for _ in $(seq 1 90); do
  if /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://127.0.0.1:8080 \
    --realm master \
    --user "$KC_BOOTSTRAP_ADMIN_USERNAME" \
    --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1; then
    authenticated=true
    break
  fi
  if ! kill -0 "$keycloak_pid" 2>/dev/null; then
    wait "$keycloak_pid"
    exit 1
  fi
  sleep 2
done
if [[ "$authenticated" != true ]]; then
  echo "Keycloak did not become ready for local realm configuration" >&2
  exit 1
fi

client_id=$(/opt/keycloak/bin/kcadm.sh get clients -r customer-support-dev \
  -q clientId=support-dashboard --fields id --format csv --noquotes | tail -n 1 | tr -d '\r')
if [[ ! "$client_id" =~ ^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$ ]]; then
  echo "The imported local OIDC client could not be found" >&2
  exit 1
fi
/opt/keycloak/bin/kcadm.sh update "clients/$client_id" -r customer-support-dev \
  -s "secret=$OIDC_CLIENT_SECRET" >/dev/null

customer_ids_json="["
IFS=',' read -r -a customer_ids <<< "$OIDC_DEV_CUSTOMER_IDS"
for i in "${!customer_ids[@]}"; do
  [[ "$i" -gt 0 ]] && customer_ids_json+=","
  customer_ids_json+="${customer_ids[$i]}"
done
customer_ids_json+="]"
for user in dev-agent dev-reviewer; do
  user_id=$(/opt/keycloak/bin/kcadm.sh get users -r customer-support-dev \
    -q "username=$user" --fields id --format csv --noquotes | tail -n 1 | tr -d '\r')
  if [[ ! "$user_id" =~ ^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$ ]]; then
    echo "An imported local support user could not be found" >&2
    exit 1
  fi
  /opt/keycloak/bin/kcadm.sh update "users/$user_id" -r customer-support-dev \
    -s "attributes.customer_ids=$customer_ids_json" >/dev/null
done
/opt/keycloak/bin/kcadm.sh set-password -r customer-support-dev \
  --username dev-agent --new-password "$OIDC_DEV_AGENT_PASSWORD" >/dev/null
/opt/keycloak/bin/kcadm.sh set-password -r customer-support-dev \
  --username dev-reviewer --new-password "$OIDC_DEV_REVIEWER_PASSWORD" >/dev/null

touch /tmp/local-oidc-configured
wait "$keycloak_pid"
