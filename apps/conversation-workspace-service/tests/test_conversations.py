def _headers(email: str = "admin@example.com") -> dict[str, str]:
    return {"X-Dev-User": email}


def _conversation_with_assistant(items: list[dict], assistant_id: str) -> dict:
    return next(
        item
        for item in items
        if any(participant.get("top_level_assistant") == assistant_id for participant in item["participants"])
    )


def test_assistant_inboxes_seed_per_actor(client, reset_db):
    admin_list = client.get("/v1/families/2/conversations", headers=_headers("admin@example.com"))
    partner_list = client.get("/v1/families/2/conversations", headers=_headers("partner@example.com"))

    assert admin_list.status_code == 200
    assert partner_list.status_code == 200

    admin_items = admin_list.json()["items"]
    partner_items = partner_list.json()["items"]

    assert len(admin_items) == 2
    assert len(partner_items) == 2
    assert _conversation_with_assistant(admin_items, "caleb")["conversation_id"] != _conversation_with_assistant(partner_items, "caleb")["conversation_id"]
    assert _conversation_with_assistant(admin_items, "amelia")["conversation_id"] != _conversation_with_assistant(partner_items, "amelia")["conversation_id"]


def test_family_chat_upgrades_to_hybrid_and_passive_assistant_stays_silent(client, reset_db):
    created = client.post(
        "/v1/families/2/conversations",
        headers=_headers(),
        json={
            "kind": "family",
            "title": "Dinner crew",
            "human_participants": [{"person_id": "person-partner", "display_name": "Partner User"}],
        },
    )
    assert created.status_code == 201
    conversation = created.json()

    invited = client.post(
        f"/v1/families/2/conversations/{conversation['conversation_id']}/participants/assistants",
        headers=_headers(),
        json={"assistant_id": "caleb", "assistant_mode": "passive", "set_primary": True},
    )
    assert invited.status_code == 200
    invited_payload = invited.json()
    assert invited_payload["kind"] == "hybrid"

    first_message = client.post(
        f"/v1/families/2/conversations/{conversation['conversation_id']}/messages",
        headers=_headers(),
        json={"body_text": "We should figure out dinner for this week.", "invoke_assistant": True},
    )
    assert first_message.status_code == 200
    payload = first_message.json()
    assert [message["sender_kind"] for message in payload["messages"]][-1] == "human"
    assert reset_db["runtime_calls"] == []

    second_message = client.post(
        f"/v1/families/2/conversations/{conversation['conversation_id']}/messages",
        headers=_headers(),
        json={"body_text": "@Caleb help us plan dinner for this week."},
    )
    assert second_message.status_code == 200
    second_payload = second_message.json()
    assert second_payload["messages"][-1]["sender_kind"] == "assistant"
    assert second_payload["messages"][-1]["top_level_assistant"] == "caleb"
    assert any(activity["agent_name"] == "PlanningAgent" for activity in second_payload["domain_activity"])


def test_active_primary_assistant_handles_untargeted_requests_and_quick_action_prefix(client, reset_db):
    created = client.post(
        "/v1/families/2/conversations",
        headers=_headers(),
        json={
            "kind": "hybrid",
            "title": "Family planning",
            "space_type": "planning",
            "assistant_ids": ["amelia"],
            "primary_assistant": "amelia",
        },
    )
    assert created.status_code == 201
    conversation = created.json()

    invited = client.post(
        f"/v1/families/2/conversations/{conversation['conversation_id']}/participants/assistants",
        headers=_headers(),
        json={"assistant_id": "caleb", "assistant_mode": "passive"},
    )
    assert invited.status_code == 200
    activated = client.post(
        f"/v1/families/2/conversations/{conversation['conversation_id']}/participants/assistants",
        headers=_headers(),
        json={"assistant_id": "amelia", "assistant_mode": "active", "set_primary": True},
    )
    assert activated.status_code == 200

    response = client.post(
        f"/v1/families/2/conversations/{conversation['conversation_id']}/messages",
        headers=_headers(),
        json={
            "body_text": "pack lunches and review school supplies",
            "quick_action_prefix": "Add new tasks for the following:",
            "invoke_assistant": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["top_level_assistant"] == "amelia"
    assert reset_db["runtime_calls"][-1]["assistant_id"] == "amelia"
    assert "Add new tasks for the following: pack lunches and review school supplies" in reset_db["runtime_calls"][-1]["transport_message"]


def test_summary_convert_share_and_action_lifecycle(client, reset_db):
    assistant_list = client.get("/v1/families/2/conversations", headers=_headers())
    assert assistant_list.status_code == 200
    caleb_chat = _conversation_with_assistant(assistant_list.json()["items"], "caleb")

    assistant_turn = client.post(
        f"/v1/families/2/conversations/{caleb_chat['conversation_id']}/messages",
        headers=_headers(),
        json={"body_text": "Help me plan dinner this week."},
    )
    assert assistant_turn.status_code == 200
    assistant_payload = assistant_turn.json()
    assistant_message_id = assistant_payload["messages"][-1]["message_id"]

    family_chat = client.post(
        "/v1/families/2/conversations",
        headers=_headers(),
        json={"kind": "family", "title": "Family thread"},
    )
    assert family_chat.status_code == 201
    family_conversation_id = family_chat.json()["conversation_id"]

    shared = client.post(
        f"/v1/families/2/messages/{assistant_message_id}/share",
        headers=_headers(),
        json={"target_conversation_id": family_conversation_id, "note": "Sharing Caleb's draft"},
    )
    assert shared.status_code == 200
    assert shared.json()["messages"][-1]["blocks"][0]["block_type"] == "summary_card"

    summary = client.post(
        f"/v1/families/2/conversations/{family_conversation_id}/summaries",
        headers=_headers(),
        json={},
    )
    assert summary.status_code == 200
    assert summary.json()["latest_summary"]

    converted = client.post(
        f"/v1/families/2/conversations/{family_conversation_id}/convert",
        headers=_headers(),
        json={"target": "tasks", "title": "Dinner task draft"},
    )
    assert converted.status_code == 200
    proposal = converted.json()["proposal"]
    assert proposal["status"] == "proposed"
    assert proposal["action_type"] == "convert:tasks"

    confirmed = client.post(f"/v1/families/2/actions/{proposal['action_id']}/confirm", headers=_headers())
    assert confirmed.status_code == 200
    assert confirmed.json()["proposal"]["status"] == "confirmed"

    committed = client.post(f"/v1/families/2/actions/{proposal['action_id']}/commit", headers=_headers())
    assert committed.status_code == 200
    assert committed.json()["proposal"]["status"] == "committed"
    assert committed.json()["proposal"]["result"]["source_conversation_id"] == family_conversation_id

    canceled = client.post(
        f"/v1/families/2/conversations/{family_conversation_id}/convert",
        headers=_headers(),
        json={"target": "note", "title": "Dinner note draft"},
    )
    cancel_id = canceled.json()["proposal"]["action_id"]
    canceled_action = client.post(f"/v1/families/2/actions/{cancel_id}/cancel", headers=_headers())
    assert canceled_action.status_code == 200
    assert canceled_action.json()["proposal"]["status"] == "canceled"


def test_realtime_socket_requires_visible_conversation_and_answers_ping(client, reset_db):
    listing = client.get("/v1/families/2/conversations", headers=_headers())
    assert listing.status_code == 200
    amelia_chat = _conversation_with_assistant(listing.json()["items"], "amelia")

    with client.websocket_connect(
        f"/v1/families/2/realtime/ws?conversation_id={amelia_chat['conversation_id']}",
        headers=_headers(),
    ) as websocket:
        websocket.send_json({"type": "ping"})
        assert websocket.receive_json() == {"type": "pong"}

    with pytest.raises(Exception):
        with client.websocket_connect(
            f"/v1/families/2/realtime/ws?conversation_id={amelia_chat['conversation_id']}",
            headers=_headers("partner@example.com"),
        ):
            pass
import pytest
