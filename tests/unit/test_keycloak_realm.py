import json
from pathlib import Path


REALM_FILE = Path(__file__).parents[2] / "deploy" / "keycloak" / "realm" / "customer-support-dev-realm.json"


def test_local_keycloak_realm_is_confidential_and_uses_exact_callback():
    realm = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    assert realm["realm"] == "customer-support-dev"
    assert realm["sslRequired"] == "none"  # This realm is only for loopback development.
    client = next(row for row in realm["clients"] if row["clientId"] == "support-dashboard")
    assert client["publicClient"] is False
    assert client["standardFlowEnabled"] is True
    assert client["directAccessGrantsEnabled"] is False
    assert client["redirectUris"] == ["http://localhost:8080/api/bff/auth/callback"]
    assert client["webOrigins"] == ["http://localhost:8080"]
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["secret"] == "overwritten-from-local-environment-on-startup"


def test_local_keycloak_id_token_mappers_and_users_match_application_claim_contract():
    realm = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    client = next(row for row in realm["clients"] if row["clientId"] == "support-dashboard")
    mappers = {row["config"]["claim.name"]: row for row in client["protocolMappers"]}
    assert mappers["roles"]["protocolMapper"] == "oidc-usermodel-realm-role-mapper"
    assert mappers["roles"]["config"]["id.token.claim"] == "true"
    customer_mapper = mappers["customer_ids"]
    assert customer_mapper["protocolMapper"] == "oidc-usermodel-attribute-mapper"
    assert customer_mapper["config"]["jsonType.label"] == "long"
    assert customer_mapper["config"]["multivalued"] == "true"
    assert customer_mapper["config"]["id.token.claim"] == "true"

    users = {user["username"]: user for user in realm["users"]}
    assert users["dev-agent"]["realmRoles"] == ["support_agent"]
    assert users["dev-reviewer"]["realmRoles"] == ["support_reviewer"]
    for user in users.values():
        assert user["attributes"]["customer_ids"]
        assert all(int(value) > 0 for value in user["attributes"]["customer_ids"])
        assert user["credentials"][0]["value"] == "overwritten-from-local-environment"
