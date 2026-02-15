# Decision Management Agent

Workflow:
- parse intent (new decision vs update vs question)
- load Family DNA + goals
- ask follow-ups (bounded)
- estimate costs (bounded)
- score vs goals
- persist decision + score + roadmap actions
- publish NATS events
- write semantic memory

