from __future__ import annotations


class Subjects:
    # Family DNA
    FAMILY_DNA_UPDATED = "family.dna.updated"

    # Decisions
    DECISION_CREATED = "decision.created"
    DECISION_UPDATED = "decision.updated"
    DECISION_SCORED = "decision.scored"
    DECISION_DECONFLICT_SUGGESTED = "decision.deconflict.suggested"

    # Roadmap
    ROADMAP_ITEM_ADDED = "roadmap.item.added"
    ROADMAP_ITEM_UPDATED = "roadmap.item.updated"
    ROADMAP_ITEM_DUE_SOON = "roadmap.item.due_soon"

    # Agent lifecycle
    @staticmethod
    def agent_started(name: str) -> str:
        return f"agent.{name}.started"

    @staticmethod
    def agent_error(name: str) -> str:
        return f"agent.{name}.error"

    @staticmethod
    def agent_audit(name: str) -> str:
        return f"agent.{name}.audit"

