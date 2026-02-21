from datetime import date

from agents.decision_agent.agent import _merge_drafts
from agents.decision_agent.schemas import DecisionDraft


def test_merge_preserves_title_and_description_on_short_followup():
    base = DecisionDraft(
        title="Trip to San Diego",
        description="We are planning a 3-day trip with the kids.",
        options=["Drive", "Fly"],
        participants=["Alex", "Sam", "Kids"],
        constraints=["No red-eye flights"],
        assumptions=[],
        budget=None,
        target_date=None,
        decision_type="travel",
    )
    # Follow-up message like "$500" should not override title/description with junk.
    delta = DecisionDraft(
        title="$500",
        description="500",
        options=[],
        participants=[],
        constraints=[],
        assumptions=[],
        budget=500.0,
        target_date=None,
        decision_type="other",
    )
    merged = _merge_drafts(base, delta)
    assert merged.title == "Trip to San Diego"
    assert merged.description == "We are planning a 3-day trip with the kids."
    assert merged.budget == 500.0


def test_merge_appends_new_description_details():
    base = DecisionDraft(
        title="Buy a laptop",
        description="Need a laptop for school.",
        options=[],
        participants=[],
        constraints=[],
        assumptions=[],
        budget=None,
        target_date=None,
        decision_type="purchase",
    )
    delta = DecisionDraft(
        title="Buy a laptop for college",  # long enough to be accepted
        description="Prefer 16GB RAM and 512GB SSD. Must be under 4 lbs.",
        options=["MacBook Air", "ThinkPad X1"],
        participants=[],
        constraints=["Under 4 lbs"],
        assumptions=[],
        budget=1400.0,
        target_date=date(2026, 3, 1),
        decision_type="purchase",
    )
    merged = _merge_drafts(base, delta)
    assert merged.title == "Buy a laptop for college"
    assert "Need a laptop for school." in merged.description
    assert "Prefer 16GB RAM" in merged.description
    assert merged.options == ["MacBook Air", "ThinkPad X1"]
    assert merged.constraints == ["Under 4 lbs"]
    assert merged.budget == 1400.0
    assert merged.target_date == date(2026, 3, 1)

