# Scoring Spec (v1)

## Score Scale
- `1`: harms the goal materially.
- `2`: somewhat harms the goal.
- `3`: neutral/mixed effect.
- `4`: advances the goal.
- `5`: strongly advances the goal.

## Weighted Formula
Given goal weights `w_i` and per-goal scores `s_i`:

- `weighted_avg_1_to_5 = SUM(w_i * s_i) / SUM(w_i)`
- `normalized_0_to_100 = (weighted_avg_1_to_5 - 1) * 25`

Weights should sum to 1.0 by policy but calculation still normalizes by `SUM(w_i)` for resilience.

## Threshold Behavior
- If `weighted_avg_1_to_5 >= threshold`: move to `Queued`.
- If target date exists, optionally create `RoadmapItem` in matching period bucket.
- If below threshold: move to `Needs-Work`, generate 1 to 5 suggestions, allow rescore.

## Example A
- Goals: Financial Stability (0.5), Family Time (0.3), Health (0.2)
- Scores: 4, 5, 3
- Weighted: `(0.5*4 + 0.3*5 + 0.2*3) = 4.1`
- 0-100: `77.5`
- Threshold 4.0 => `Queued`

## Example B
- Scores: 2, 3, 3
- Weighted: `2.5`
- 0-100: `37.5`
- Threshold 4.0 => `Needs-Work` + suggestion flow
