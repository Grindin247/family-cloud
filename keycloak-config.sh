#!/bin/bash

# Wait for LDAP
until echo > /dev/tcp/ldap/3890 2>/dev/null; do
  echo "Waiting for LLaDAP..."
  sleep 2
done

# Login to Keycloak Admin CLI
/opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 \
  --realm master \
  --user $KEYCLOAK_ADMIN \
  --password $KEYCLOAK_ADMIN_PASSWORD

# Create realm if it doesn't exist
/opt/keycloak/bin/kcadm.sh create realms -s realm=familycloud -s enabled=true || true

# Create OIDC traefik client
/opt/keycloak/bin/kcadm.sh create clients -r familycloud \
  -s clientId=traefik-forward-auth \
  -s enabled=true \
  -s clientAuthenticatorType=client-secret \
  -s secret=secret123 \
  -s redirectUris='["https://auth.callender434.fam/_oauth/*"]' \
  -s standardFlowEnabled=true \
  -s serviceAccountsEnabled=true || true

# Create OIDC traefik client
/opt/keycloak/bin/kcadm.sh create clients -r familycloud \
  -s clientId=nextcloud \
  -s enabled=true \
  -s clientAuthenticatorType=client-secret \
  -s secret=secret123 \
  -s redirectUris='["*"]' \
  -s standardFlowEnabled=true \
  -s serviceAccountsEnabled=true || true

# Create LDAP user federation provider
REALM_ID=$(/opt/keycloak/bin/kcadm.sh get realms/familycloud --fields id --format csv | tail -n1)

/opt/keycloak/bin/kcadm.sh create components -r familycloud \
  -s name=ldap \
  -s providerId=ldap \
  -s providerType=org.keycloak.storage.UserStorageProvider \
  -s parentId=$REALM_ID \
  -s config='{
    "enabled": ["true"],
    "priority": ["0"],
    "editMode": ["READ_ONLY"],
    "vendor": ["other"],
    "usernameLDAPAttribute": ["uid"],
    "rdnLDAPAttribute": ["uid"],
    "uuidLDAPAttribute": ["entryUUID"],
    "userObjectClasses": ["inetOrgPerson"],
    "connectionUrl": ["ldap://ldap:3890"],
    "usersDn": ["ou=people,dc=example,dc=com"],
    "bindDn": ["uid=admin,ou=people,dc=example,dc=com"],
    "bindCredential": ["adminpasswordchangeit"],
    "searchScope": ["2"]
  }' || true
