FROM quay.io/keycloak/keycloak:26.8.2
COPY realm/customer-support-dev-realm.json /opt/keycloak/data/import/customer-support-dev-realm.json
COPY --chmod=0755 start-local.sh /opt/keycloak/bin/start-local.sh
ENTRYPOINT ["/opt/keycloak/bin/start-local.sh"]
