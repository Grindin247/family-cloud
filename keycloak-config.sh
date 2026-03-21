#!/usr/bin/env bash
set -euo pipefail

say() { printf "[keycloak-config] %s\n" "$*"; }

REALM="${KEYCLOAK_REALM:-familycloud}"
DOMAIN="${FAMILY_DOMAIN:-family.example}"
TRAEFIK_CLIENT_SECRET="${OIDC_CLIENT_SECRET:-}"
NEXTCLOUD_CLIENT_SECRET="${NEXTCLOUD_OIDC_CLIENT_SECRET:-}"
VIKUNJA_CLIENT_SECRET="${VIKUNJA_OIDC_CLIENT_SECRET:-}"
DECISION_SYNC_CLIENT_SECRET="${DECISION_KEYCLOAK_SYNC_CLIENT_SECRET:-}"
LLDAP_BIND_PASSWORD="${LLDAP_ADMIN_PASSWORD:-}"
LLDAP_GROUPS_DN="${LLDAP_GROUPS_DN:-ou=groups,dc=example,dc=com}"
LLDAP_GROUP_OBJECT_CLASSES="${LLDAP_GROUP_OBJECT_CLASSES:-groupOfNames}"
LLDAP_GROUP_NAME_ATTR="${LLDAP_GROUP_NAME_ATTR:-cn}"
LLDAP_GROUP_MEMBER_ATTR="${LLDAP_GROUP_MEMBER_ATTR:-member}"
LLDAP_GROUP_MEMBERSHIP_ATTR_TYPE="${LLDAP_GROUP_MEMBERSHIP_ATTR_TYPE:-DN}"
LLDAP_GROUP_MEMBERSHIP_USER_LDAP_ATTR="${LLDAP_GROUP_MEMBERSHIP_USER_LDAP_ATTR:-uid}"
LLDAP_GROUPS_MAPPER_MODE="${LLDAP_GROUPS_MAPPER_MODE:-READ_ONLY}"

if [[ -z "$TRAEFIK_CLIENT_SECRET" || -z "$NEXTCLOUD_CLIENT_SECRET" ]]; then
  say "Missing OIDC client secret env vars; expected OIDC_CLIENT_SECRET and NEXTCLOUD_OIDC_CLIENT_SECRET"
  exit 1
fi

if [[ -z "$VIKUNJA_CLIENT_SECRET" && -f /run/secrets/vikunja_oidc_client_secret ]]; then
  VIKUNJA_CLIENT_SECRET="$(cat /run/secrets/vikunja_oidc_client_secret | tr -d '\r\n')"
fi

# Wait for LDAP
until echo > /dev/tcp/ldap/3890 2>/dev/null; do
  say "Waiting for LLDAP..."
  sleep 2
done

# Login to Keycloak Admin CLI (Keycloak may open the port before bootstrap/admin is ready)
for i in $(seq 1 60); do
  if /opt/keycloak/bin/kcadm.sh config credentials \
    --server http://localhost:8080 \
    --realm master \
    --user "${KEYCLOAK_ADMIN:-admin}" \
    --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null 2>&1; then
    break
  fi
  say "kcadm login not ready yet (attempt $i/60); retrying..."
  sleep 2
done

if ! /opt/keycloak/bin/kcadm.sh get realms/master >/dev/null 2>&1; then
  say "kcadm login failed after retries; check KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD"
  exit 1
fi

# Create realm if it doesn't exist
/opt/keycloak/bin/kcadm.sh create realms -s realm="$REALM" -s enabled=true >/dev/null 2>&1 || true

upsert_client() {
  local client_id="$1"
  local secret="$2"
  local redirect_uris_json="$3"
  local web_origins_json="$4"
  local existing_id

  # kcadm CSV output may include quotes; extract a UUID robustly.
  existing_id="$(/opt/keycloak/bin/kcadm.sh get clients -r "$REALM" -q clientId="$client_id" --fields id --format csv | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1 | tr 'A-F' 'a-f' || true)"

  if [[ -z "$existing_id" ]]; then
    say "Creating OIDC client: $client_id"
    /opt/keycloak/bin/kcadm.sh create clients -r "$REALM" \
      -s clientId="$client_id" \
      -s enabled=true \
      -s protocol=openid-connect \
      -s publicClient=false \
      -s clientAuthenticatorType=client-secret \
      -s secret="$secret" \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=false \
      -s serviceAccountsEnabled=false \
      -s redirectUris="$redirect_uris_json" \
      -s webOrigins="$web_origins_json" \
      >/dev/null
  else
    say "Updating OIDC client: $client_id"
    /opt/keycloak/bin/kcadm.sh update "clients/$existing_id" -r "$REALM" \
      -s enabled=true \
      -s protocol=openid-connect \
      -s publicClient=false \
      -s clientAuthenticatorType=client-secret \
      -s secret="$secret" \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=false \
      -s serviceAccountsEnabled=false \
      -s redirectUris="$redirect_uris_json" \
      -s webOrigins="$web_origins_json" \
      >/dev/null
  fi
}

upsert_service_client() {
  local client_id="$1"
  local secret="$2"
  local existing_id

  existing_id="$(/opt/keycloak/bin/kcadm.sh get clients -r "$REALM" -q clientId="$client_id" --fields id --format csv | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1 | tr 'A-F' 'a-f' || true)"

  if [[ -z "$existing_id" ]]; then
    say "Creating service-account client: $client_id"
    /opt/keycloak/bin/kcadm.sh create clients -r "$REALM" \
      -s clientId="$client_id" \
      -s enabled=true \
      -s protocol=openid-connect \
      -s publicClient=false \
      -s clientAuthenticatorType=client-secret \
      -s secret="$secret" \
      -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false \
      -s serviceAccountsEnabled=true \
      >/dev/null
  else
    say "Updating service-account client: $client_id"
    /opt/keycloak/bin/kcadm.sh update "clients/$existing_id" -r "$REALM" \
      -s enabled=true \
      -s protocol=openid-connect \
      -s publicClient=false \
      -s clientAuthenticatorType=client-secret \
      -s secret="$secret" \
      -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false \
      -s serviceAccountsEnabled=true \
      >/dev/null
  fi
}

upsert_client \
  "traefik-forward-auth" \
  "$TRAEFIK_CLIENT_SECRET" \
  "[\"http://auth.${DOMAIN}/_oauth\",\"https://auth.${DOMAIN}/_oauth\",\"http://decision.${DOMAIN}/*\",\"https://decision.${DOMAIN}/*\"]" \
  "[\"http://auth.${DOMAIN}\",\"https://auth.${DOMAIN}\"]"

upsert_client \
  "nextcloud" \
  "$NEXTCLOUD_CLIENT_SECRET" \
  "[\"https://nextcloud.${DOMAIN}/apps/user_oidc/code\"]" \
  "[\"https://nextcloud.${DOMAIN}\"]"

# Vikunja OIDC (used by Tasks/Kanban)
if [[ -n "${VIKUNJA_CLIENT_SECRET:-}" ]]; then
  upsert_client \
    "vikunja" \
    "$VIKUNJA_CLIENT_SECRET" \
    "[\"https://tasks.${DOMAIN}/auth/openid/keycloak\",\"https://tasks.${DOMAIN}/auth/openid/keycloak/\"]" \
    "[\"https://tasks.${DOMAIN}\"]"
else
  say "Skipping Vikunja client upsert (missing VIKUNJA_OIDC_CLIENT_SECRET and /run/secrets/vikunja_oidc_client_secret)"
fi

# Decision system Keycloak group sync (service account)
if [[ -n "${DECISION_SYNC_CLIENT_SECRET:-}" ]]; then
  upsert_service_client "decision-system-sync" "$DECISION_SYNC_CLIENT_SECRET"

  # Grant the service account access to query groups and users.
  DECISION_CLIENT_ID="$(/opt/keycloak/bin/kcadm.sh get clients -r "$REALM" -q clientId="decision-system-sync" --fields id --format csv | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1 | tr 'A-F' 'a-f' || true)"
  if [[ -z "$DECISION_CLIENT_ID" ]]; then
    say "Failed to resolve decision-system-sync client id; cannot grant roles"
  else
    SVC_USER_ID="$(/opt/keycloak/bin/kcadm.sh get "clients/$DECISION_CLIENT_ID/service-account-user" -r "$REALM" --fields id --format csv | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1 | tr 'A-F' 'a-f' || true)"
    if [[ -z "$SVC_USER_ID" ]]; then
      say "Failed to resolve service account user id for decision-system-sync; cannot grant roles"
    else
      for role in view-users query-users view-groups query-groups; do
        /opt/keycloak/bin/kcadm.sh add-roles -r "$REALM" --uid "$SVC_USER_ID" --cclientid realm-management --rolename "$role" >/dev/null 2>&1 || true
      done
      say "Granted realm-management roles to decision-system-sync service account"
    fi
  fi
else
  say "Skipping decision-system-sync client upsert (missing DECISION_KEYCLOAK_SYNC_CLIENT_SECRET)"
fi

# Create/update LDAP user federation provider
REALM_ID="$(/opt/keycloak/bin/kcadm.sh get "realms/$REALM" --fields id --format csv | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1 | tr 'A-F' 'a-f' || true)"
LDAP_COMPONENT_ID="$(/opt/keycloak/bin/kcadm.sh get components -r "$REALM" -q name=ldap --fields id --format csv | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1 | tr 'A-F' 'a-f' || true)"
LDAP_CONFIG="{\"enabled\":[\"true\"],\"priority\":[\"0\"],\"editMode\":[\"READ_ONLY\"],\"vendor\":[\"other\"],\"usernameLDAPAttribute\":[\"uid\"],\"rdnLDAPAttribute\":[\"uid\"],\"uuidLDAPAttribute\":[\"entryUUID\"],\"userObjectClasses\":[\"inetOrgPerson\"],\"connectionUrl\":[\"ldap://ldap:3890\"],\"usersDn\":[\"ou=people,dc=example,dc=com\"],\"bindDn\":[\"uid=admin,ou=people,dc=example,dc=com\"],\"bindCredential\":[\"${LLDAP_BIND_PASSWORD}\"],\"searchScope\":[\"2\"]}"

if [[ -z "$LDAP_COMPONENT_ID" ]]; then
  say "Creating LDAP federation component"
  /opt/keycloak/bin/kcadm.sh create components -r "$REALM" \
    -s name=ldap \
    -s providerId=ldap \
    -s providerType=org.keycloak.storage.UserStorageProvider \
    -s parentId="$REALM_ID" \
    -s config="$LDAP_CONFIG" \
    >/dev/null
else
  say "Updating LDAP federation component"
  /opt/keycloak/bin/kcadm.sh update "components/$LDAP_COMPONENT_ID" -r "$REALM" \
    -s name=ldap \
    -s providerId=ldap \
    -s providerType=org.keycloak.storage.UserStorageProvider \
    -s parentId="$REALM_ID" \
    -s config="$LDAP_CONFIG" \
    >/dev/null
fi

# Refresh LDAP component id (create path doesn't update the variable).
LDAP_COMPONENT_ID="$(/opt/keycloak/bin/kcadm.sh get components -r "$REALM" -q name=ldap --fields id --format csv | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1 | tr 'A-F' 'a-f' || true)"
if [[ -z "$LDAP_COMPONENT_ID" ]]; then
  say "Failed to resolve LDAP component id after upsert; cannot configure LDAP group mapper"
  exit 1
fi

# Create/update LDAP groups mapper so LLDAP groups show up in Keycloak.
LDAP_GROUPS_MAPPER_ID="$(/opt/keycloak/bin/kcadm.sh get components -r "$REALM" -q name=ldap-groups -q parentId="$LDAP_COMPONENT_ID" --fields id --format csv | grep -Eo '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1 | tr 'A-F' 'a-f' || true)"
LDAP_GROUPS_MAPPER_CONFIG="{\"groups.dn\":[\"${LLDAP_GROUPS_DN}\"],\"group.name.ldap.attribute\":[\"${LLDAP_GROUP_NAME_ATTR}\"],\"group.object.classes\":[\"${LLDAP_GROUP_OBJECT_CLASSES}\"],\"membership.ldap.attribute\":[\"${LLDAP_GROUP_MEMBER_ATTR}\"],\"membership.attribute.type\":[\"${LLDAP_GROUP_MEMBERSHIP_ATTR_TYPE}\"],\"membership.user.ldap.attribute\":[\"${LLDAP_GROUP_MEMBERSHIP_USER_LDAP_ATTR}\"],\"mode\":[\"${LLDAP_GROUPS_MAPPER_MODE}\"],\"user.roles.retrieve.strategy\":[\"LOAD_GROUPS_BY_MEMBER_ATTRIBUTE\"],\"ignore.missing.groups\":[\"true\"],\"preserve.group.inheritance\":[\"true\"]}"

if [[ -z "$LDAP_GROUPS_MAPPER_ID" ]]; then
  say "Creating LDAP groups mapper component"
  /opt/keycloak/bin/kcadm.sh create components -r "$REALM" \
    -s name=ldap-groups \
    -s providerId=group-ldap-mapper \
    -s providerType=org.keycloak.storage.ldap.mappers.LDAPStorageMapper \
    -s parentId="$LDAP_COMPONENT_ID" \
    -s config="$LDAP_GROUPS_MAPPER_CONFIG" \
    >/dev/null
else
  say "Updating LDAP groups mapper component"
  /opt/keycloak/bin/kcadm.sh update "components/$LDAP_GROUPS_MAPPER_ID" -r "$REALM" \
    -s name=ldap-groups \
    -s providerId=group-ldap-mapper \
    -s providerType=org.keycloak.storage.ldap.mappers.LDAPStorageMapper \
    -s parentId="$LDAP_COMPONENT_ID" \
    -s config="$LDAP_GROUPS_MAPPER_CONFIG" \
    >/dev/null
fi

say "Keycloak realm, clients, and LDAP federation configured"
