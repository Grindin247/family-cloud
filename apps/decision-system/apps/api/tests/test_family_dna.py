from fastapi.testclient import TestClient


def test_family_dna_propose_commit_roundtrip(client: TestClient):
    fam = client.post("/v1/families", json={"name": "TestFam"}).json()
    family_id = fam["id"]

    propose = client.post(
        f"/v1/family/{family_id}/dna/propose",
        json={
            "patch": [
                {"op": "add", "path": "/people", "value": [{"id": "p1", "name": "James"}]},
                {"op": "add", "path": "/goals", "value": [{"id": "g1", "name": "More family time", "weight": 2.0}]},
            ],
            "rationale": "initial dna",
            "confidence": 0.8,
            "sources": [],
        },
    ).json()
    assert "proposal_id" in propose

    commit = client.post(f"/v1/family/{family_id}/dna/commit/{propose['proposal_id']}").json()
    assert commit["family_id"] == family_id
    assert commit["version"] == 1
    assert "event_id" in commit

    snap = client.get(f"/v1/family/{family_id}/dna").json()
    assert snap["family_id"] == family_id
    assert snap["version"] == 1
    assert snap["snapshot"]["people"][0]["name"] == "James"


def test_family_dna_rejects_secrets(client: TestClient):
    fam = client.post("/v1/families", json={"name": "SecretFam"}).json()
    family_id = fam["id"]
    resp = client.post(
        f"/v1/family/{family_id}/dna/propose",
        json={"patch": [{"op": "add", "path": "/policies", "value": [{"name": "oops", "rules": ["password=123"]}]}]},
    )
    assert resp.status_code == 400

