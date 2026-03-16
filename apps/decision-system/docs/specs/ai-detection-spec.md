# AI Decision Detection Prompt and Extraction Schema

## Prompt
System: You classify family chat messages into decision candidates. Do not invent facts. Mark unknown fields as null and list assumptions.

User Input: {{message}}

Tasks:
1. Decide if this is a decision request (`is_decision`).
2. If yes, extract fields: title, description, cost, urgency (1-5), target_date, beneficiaries, constraints.
3. Ask follow-up questions only for missing high-impact fields (cost, urgency, target date) when needed.

## JSON Schema
```json
{
  "is_decision": true,
  "title": "string",
  "description": "string",
  "cost": null,
  "urgency": null,
  "target_date": null,
  "beneficiaries": [],
  "constraints": [],
  "assumptions": []
}
```
