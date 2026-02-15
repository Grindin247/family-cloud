from __future__ import annotations

from dataclasses import dataclass

from agents.common.events import EventPublisher, Subjects
from agents.common.observability import new_correlation_id
from agents.common.settings import settings

from .costs import CostEstimator
from .deconflict import DeconflictAdvisor
from .ai import DecisionAi
from .requirements import missing_fields
from .schemas import (
    DecisionAgentResponse,
    DecisionDraft,
    DecisionExplanation,
    DecisionIntakeRequest,
)
from .scoring import Scorer
from .tools import decision_tools


@dataclass
class DecisionAgent:
    name: str = "decision"

    def run(self, req: DecisionIntakeRequest) -> DecisionAgentResponse:
        cid = new_correlation_id()
        tools = decision_tools()
        publisher = EventPublisher()

        msg = req.message.strip()
        ai = DecisionAi()
        draft = ai.extract_draft(msg)

        goals = tools.get_family_goals(req.family_id, actor_email=req.actor)
        if not goals:
            return DecisionAgentResponse(
                draft=draft,
                explanation=DecisionExplanation(
                    decision_definition="Goal-aware decision management request",
                    key_facts_and_assumptions=[f"family_id={req.family_id}"],
                    followups_asked=["Please add at least one family goal in the decision system, then retry."],
                    scoring_notes="No goals available; scoring skipped.",
                ),
            )

        missing = missing_fields(draft)
        followups = ai.generate_followups(
            draft=draft,
            missing=missing,
            max_questions=settings.decision_max_followup_questions,
        )

        cost_estimator = CostEstimator()
        cost_est = cost_estimator.estimate(draft)

        scorer = Scorer(threshold_1_to_5=settings.decision_threshold_1_to_5)
        scoring, scoring_notes = scorer.score(goals, draft.title, draft.description, draft_obj=draft)

        alignment_suggestions: list[str] = []
        alignment_questions: list[str] = []
        if not scoring.pass_threshold:
            alignment = ai.alignment_help(
                draft=draft,
                goals=goals,
                goal_scores=scoring.goal_scores,
                weighted_total_1_to_5=scoring.weighted_total_1_to_5,
                threshold_1_to_5=scoring.threshold_1_to_5,
                max_questions=settings.decision_max_alignment_questions,
            )
            alignment_suggestions = alignment.suggestions or []
            alignment_questions = alignment.questions or []

        # If minimum fields are missing, return scoring + AI followups but don't persist yet.
        if missing:
            return DecisionAgentResponse(
                draft=draft,
                cost_estimate=cost_est,
                scoring=scoring,
                alignment_suggestions=alignment_suggestions,
                explanation=DecisionExplanation(
                    decision_definition=draft.title,
                    key_facts_and_assumptions=[f"family_id={req.family_id}", f"actor={req.actor}"] + (cost_est.assumptions if cost_est else []),
                    followups_asked=followups,
                    scoring_notes=(
                        "Scoring is provisional because required details are missing. "
                        f"Notes: {scoring_notes}".strip()
                    ),
                ),
            )

        created_decision = tools.create_decision(
            {
                "family_id": req.family_id,
                "title": draft.title,
                "description": draft.description,
                "cost": cost_est.estimate if cost_est else None,
                "tags": ["agent:decision"],
            },
            actor_email=req.actor,
        )

        tools.score_decision(
            int(created_decision["id"]),
            {
                "goal_scores": [
                    {"goal_id": gs.goal_id, "score_1_to_5": gs.score_1_to_5, "rationale": gs.rationale}
                    for gs in scoring.goal_scores
                ],
                "threshold_1_to_5": scoring.threshold_1_to_5,
                "computed_by": "ai",
            },
            actor_email=req.actor,
        )

        roadmap_items: list[dict] = []
        if scoring.pass_threshold:
            # Minimal: create one roadmap item to "plan next steps".
            roadmap_items.append(
                tools.add_to_roadmap(
                    {
                        "family_id": req.family_id,
                        "title": f"Plan next steps: {draft.title}",
                        "description": "Created by decision agent after passing threshold.",
                        "decision_id": int(created_decision["id"]),
                    },
                    actor_email=req.actor,
                )
            )
        else:
            # For decisions below threshold, ask targeted questions to improve alignment.
            followups = (followups + alignment_questions)[: settings.decision_max_followup_questions + settings.decision_max_alignment_questions]

        advisor = DeconflictAdvisor()
        collisions = advisor.detect_collisions(draft.target_date, tools.list_roadmap_items(req.family_id, actor_email=req.actor))

        # Write semantic memory (best-effort).
        try:
            tools.write_memory(
                req.family_id,
                "rationale",
                f"Decision agent result for decision_id={created_decision.get('id')}. Draft={draft.model_dump(mode='json')} Scoring={scoring.model_dump(mode='json')} Cost={cost_est.model_dump(mode='json') if cost_est else None}",
                actor_email=req.actor,
            )
        except Exception:
            pass

        # Publish events (best-effort).
        try:
            publisher.publish_sync(
                Subjects.DECISION_CREATED,
                {"decision_id": int(created_decision["id"]), "scoring": scoring.model_dump()},
                actor=req.actor,
                family_id=req.family_id,
                source="agents.decision_agent",
                correlation_id=cid,
            )
            if collisions:
                publisher.publish_sync(
                    Subjects.DECISION_DECONFLICT_SUGGESTED,
                    {"decision_id": int(created_decision["id"]), "suggestions": collisions},
                    actor=req.actor,
                    family_id=req.family_id,
                    source="agents.decision_agent",
                    correlation_id=cid,
                )
        except Exception:
            # Don't fail the agent response on event bus issues.
            pass

        # Agent audit event (tool calls, redacted).
        try:
            publisher.publish_sync(
                Subjects.agent_audit(self.name),
                {
                    "tools": [
                        {"name": "create_decision", "decision_id": int(created_decision["id"])},
                        {"name": "score_decision", "decision_id": int(created_decision["id"])},
                        *(
                            [{"name": "add_to_roadmap", "roadmap_item_id": int(item["id"])} for item in roadmap_items if "id" in item]
                        ),
                    ]
                },
                actor=req.actor,
                family_id=req.family_id,
                source="agents.decision_agent",
                correlation_id=cid,
            )
        except Exception:
            pass

        return DecisionAgentResponse(
            draft=draft,
            cost_estimate=cost_est,
            scoring=scoring,
            created_decision=created_decision,
            created_roadmap_items=roadmap_items,
            deconflicts=collisions,
            alignment_suggestions=alignment_suggestions,
            explanation=DecisionExplanation(
                decision_definition=draft.title,
                key_facts_and_assumptions=[f"family_id={req.family_id}", f"actor={req.actor}"] + (cost_est.assumptions if cost_est else []),
                followups_asked=followups,
                scoring_notes=f"AI-based classification scoring. Notes: {scoring_notes}".strip(),
            ),
        )
