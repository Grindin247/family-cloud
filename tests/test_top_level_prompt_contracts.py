from pathlib import Path


ROOT_PROMPTS = {
    "caleb": Path("/home/luvwrk777/.openclaw/workspace-main/SOUL.md"),
    "amelia_workspace": Path("/home/luvwrk777/.openclaw/workspace-amelia/SOUL.md"),
    "amelia_identity": Path("/home/luvwrk777/.openclaw/agents/amelia/SOUL.md"),
    "event_agent": Path("/home/luvwrk777/.openclaw/workspace-event-agent/SOUL.md"),
}


def _read(name: str) -> str:
    return ROOT_PROMPTS[name].read_text(encoding="utf-8")


def test_caleb_and_amelia_workspace_prompts_define_shared_conversational_support_contract() -> None:
    for prompt_name in ("caleb", "amelia_workspace"):
        text = _read(prompt_name)
        assert "## Conversational Support" in text
        assert "Treat unstructured conversation as real work, not dead air." in text
        assert "respond first with presence, reflection, and gentle encouragement" in text
        assert "stay in conversation mode until there is a natural transition" in text
        assert "extract meaningful insight from every substantive conversation turn" in text
        assert "if confidence is low and the question is not urgent, queue it for later instead of asking immediately" in text
        assert "high confidence: route or record immediately" in text
        assert "medium confidence: record a conservative event and optionally defer richer interpretation" in text
        assert "low confidence: do not guess; create a queued question for later delivery" in text


def test_top_level_workspace_prompts_encode_insight_routing_and_precedence_rules() -> None:
    for prompt_name in ("caleb", "amelia_workspace"):
        text = _read(prompt_name)
        assert "## Insight Extraction And Routing" in text
        assert "Most substantive conversations should produce at least one event-worthy summary unless they are pure greeting or phatic chatter." in text
        assert '"I had a rough time at basketball practice. Only made 5/10 shots"' in text
        assert "learner-specific education records always go to `education-agent`, not `event-agent`" in text
        assert "durable person profile and relationship context goes to `profile-agent`" in text
        assert "structured family or person plans, routines, habits, programs, and plan check-ins go to `planning-agent`" in text
        assert "canonical family conversation or activity summaries go to `record_family_event`" in text
        assert "deferred clarification goes to `create_agent_question`" in text
        assert "do not log pure greetings, one-word acknowledgements, trivial banter, or repeated low-value chatter with no durable insight" in text
        assert "do not ask more than one immediate clarification unless the current turn cannot be handled safely otherwise" in text


def test_top_level_workspace_prompts_route_profile_domain_to_profile_agent() -> None:
    for prompt_name in ("caleb", "amelia_workspace"):
        text = _read(prompt_name)
        assert "Delegate to `profile-agent` for any request about:" in text
        assert "MFA or passkeys" in text
        assert "dietary preferences" in text
        assert "accessibility needs" in text
        assert "relationship mapping" in text or "relationship graph" in text


def test_top_level_workspace_prompts_route_planning_domain_to_planning_agent() -> None:
    for prompt_name in ("caleb", "amelia_workspace"):
        text = _read(prompt_name)
        assert "Delegate to `planning-agent` for any request about:" in text
        assert "plans, routines, habits, or programs" in text
        assert "meal plans, fitness plans, study plans" in text
        assert "plan previews, activation, pause/archive, adherence, or plan check-ins" in text


def test_amelia_identity_prompt_matches_shared_supportive_small_talk_policy() -> None:
    text = _read("amelia_identity")
    assert "# Conversational Support" in text
    assert "Treat unstructured conversation as real work, not dead air." in text
    assert "respond first with presence, reflection, and gentle encouragement" in text
    assert "if confidence is low and the question is not urgent, queue it for later instead of asking immediately" in text
    assert "Use the same supportive small-talk policy as Caleb" in text


def test_event_agent_prompt_allows_explicit_conversation_event_recording() -> None:
    text = _read("event_agent")
    assert "limited write authority when they intentionally delegate canonical event recording" in text
    assert "Stay read-only by default, but if Caleb or Amelia explicitly forward a canonical event to record" in text
    assert "use the shared family event path" in text
