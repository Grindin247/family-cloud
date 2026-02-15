from __future__ import annotations

import json

from agents.decision_agent.agent import DecisionAgent
from agents.decision_agent.schemas import DecisionIntakeRequest


def main() -> None:
    agent = DecisionAgent()
    print("Decision agent CLI. Ctrl-C to exit.")
    actor = input("actor email: ").strip()
    family_id = int(input("family_id: ").strip())
    while True:
        msg = input("> ").strip()
        if not msg:
            continue
        resp = agent.run(DecisionIntakeRequest(message=msg, actor=actor, family_id=family_id))
        print(json.dumps(resp.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()

