"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, Decision, Family, Goal } from "../../lib/api";

type DecisionScoreDraft = {
  threshold: string;
  byGoal: Record<number, { score: string; rationale: string }>;
};

export default function DecisionsPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [form, setForm] = useState({ title: "", description: "", urgency: "3", notes: "" });
  const [error, setError] = useState("");

  async function loadData(targetFamilyId?: number | null) {
    const familyData = await api.listFamilies();
    setFamilies(familyData.items);
    const activeFamilyId = targetFamilyId ?? familyId ?? familyData.items[0]?.id ?? null;
    setFamilyId(activeFamilyId);
    if (activeFamilyId) {
      const [goalData, decisionData] = await Promise.all([api.listGoals(activeFamilyId), api.listDecisions(activeFamilyId, true)]);
      setGoals(goalData.items.filter((goal) => goal.active));
      setDecisions(decisionData.items);
    }
  }

  useEffect(() => {
    void loadData().catch((err) => setError(err instanceof Error ? err.message : "Failed to load decisions"));
  }, []);

  useEffect(() => {
    if (!familyId) return;
    void loadData(familyId).catch((err) => setError(err instanceof Error ? err.message : "Failed to refresh"));
  }, [familyId]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!familyId) return;
    try {
      await api.createDecision({
        family_id: familyId,
        title: form.title,
        description: form.description,
        urgency: Number(form.urgency),
        notes: form.notes,
      });
      setForm({ ...form, title: "", description: "", notes: "" });
      await loadData(familyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create decision");
    }
  }

  async function onDeleteDecision(decisionId: number) {
    if (!familyId) return;
    if (!window.confirm("Delete this decision?")) return;
    try {
      await api.deleteDecision(decisionId);
      await loadData(familyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete decision");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h2 className="page-title">Decisions</h2>
          <p className="page-sub">Capture, update, and score decisions directly with per-goal controls.</p>
        </div>
        <div style={{ minWidth: 220 }}>
          <label>Family</label>
          <select value={familyId ?? ""} onChange={(e) => setFamilyId(Number(e.target.value))}>
            {families.map((family) => (
              <option key={family.id} value={family.id}>{family.name}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="card">{error}</div>}

      <div className="grid grid-2 panel-grid-top">
        <div className="card">
          <h3>Create Decision</h3>
          <form className="stack" onSubmit={onCreate}>
            <input placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required />
            <textarea placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required />
            <div className="row">
              <select value={form.urgency} onChange={(e) => setForm({ ...form, urgency: e.target.value })}>
                <option value="1">Urgency 1</option>
                <option value="2">Urgency 2</option>
                <option value="3">Urgency 3</option>
                <option value="4">Urgency 4</option>
                <option value="5">Urgency 5</option>
              </select>
              <button className="btn-primary" type="submit">Save Decision</button>
            </div>
            <textarea placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </form>
        </div>

        <div className="card">
          <h3>Decision Backlog</h3>
          <div className="list">
            {decisions.map((decision) => (
              <DecisionRow
                key={decision.id}
                decision={decision}
                goals={goals}
                onSaved={() => void loadData(familyId)}
                onDelete={onDeleteDecision}
              />
            ))}
            {decisions.length === 0 && <div className="item">No decisions yet for this family.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

function buildInitialScoreDraft(decision: Decision, goals: Goal[]): DecisionScoreDraft {
  const byGoal: DecisionScoreDraft["byGoal"] = {};
  for (const goal of goals) {
    const previous = decision.score_summary?.goal_scores.find((score) => score.goal_id === goal.id);
    byGoal[goal.id] = {
      score: String(previous?.score_1_to_5 ?? 3),
      rationale: previous?.rationale ?? "",
    };
  }
  return {
    threshold: "4.0",
    byGoal,
  };
}

function DecisionRow({
  decision,
  goals,
  onSaved,
  onDelete,
}: {
  decision: Decision;
  goals: Goal[];
  onSaved: () => Promise<void> | void;
  onDelete: (decisionId: number) => Promise<void> | void;
}) {
  const [title, setTitle] = useState(decision.title);
  const [description, setDescription] = useState(decision.description);
  const [notes, setNotes] = useState(decision.notes);
  const [showScoring, setShowScoring] = useState(false);
  const [scoreDraft, setScoreDraft] = useState<DecisionScoreDraft>(() => buildInitialScoreDraft(decision, goals));
  const [saving, setSaving] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setTitle(decision.title);
    setDescription(decision.description);
    setNotes(decision.notes);
    setScoreDraft(buildInitialScoreDraft(decision, goals));
  }, [decision, goals]);

  const scorePreview = useMemo(() => {
    const values = goals.map((goal) => {
      const score = Number(scoreDraft.byGoal[goal.id]?.score ?? 3);
      return { weight: goal.weight, score: Number.isFinite(score) ? score : 3 };
    });
    const totalWeight = values.reduce((sum, value) => sum + value.weight, 0);
    if (!totalWeight) return "0.00";
    const weighted = values.reduce((sum, value) => sum + value.weight * value.score, 0) / totalWeight;
    return weighted.toFixed(2);
  }, [goals, scoreDraft]);

  async function onSaveDecision() {
    setSaving(true);
    setMessage("");
    try {
      await api.updateDecision(decision.id, { title, description, notes });
      setMessage("Decision updated.");
      await onSaved();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to update decision.");
    } finally {
      setSaving(false);
    }
  }

  async function onRunScoring() {
    if (goals.length === 0) {
      setMessage("Create active goals before scoring.");
      return;
    }

    setScoring(true);
    setMessage("");
    try {
      const goalScores = goals.map((goal) => ({
        goal_id: goal.id,
        score_1_to_5: Number(scoreDraft.byGoal[goal.id]?.score ?? 3),
        rationale: scoreDraft.byGoal[goal.id]?.rationale?.trim() || "No rationale provided",
      }));

      const response = await api.scoreDecision(decision.id, {
        goal_scores: goalScores,
        threshold_1_to_5: Number(scoreDraft.threshold || "4.0"),
        computed_by: "human",
      });

      setMessage(`Scored ${response.weighted_total_1_to_5.toFixed(2)} / 5 and routed to ${response.status}.`);
      await onSaved();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to run scoring.");
    } finally {
      setScoring(false);
    }
  }

  return (
    <div className="item stack">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="badge">{decision.status}</span>
        {decision.score_summary ? (
          <span className="score">{decision.score_summary.weighted_total_1_to_5.toFixed(2)} / 5</span>
        ) : (
          <span className="badge">Unscored</span>
        )}
      </div>

      <input value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" />

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn-secondary" type="button" disabled={saving} onClick={() => void onSaveDecision()}>
          {saving ? "Saving..." : "Update Decision"}
        </button>
        <button className="btn-danger" type="button" onClick={() => void onDelete(decision.id)}>
          Delete Decision
        </button>
        <button className="btn-primary" type="button" onClick={() => setShowScoring((value) => !value)}>
          {showScoring ? "Hide Scoring" : "Score Decision"}
        </button>
      </div>

      {showScoring && (
        <div className="card" style={{ marginTop: 4 }}>
          <h3 style={{ marginTop: 0 }}>Scoring Controls</h3>
          <div className="row" style={{ marginBottom: 8 }}>
            <div>
              <label>Threshold (1-5)</label>
              <input
                type="number"
                min="1"
                max="5"
                step="0.1"
                value={scoreDraft.threshold}
                onChange={(e) => setScoreDraft({ ...scoreDraft, threshold: e.target.value })}
              />
            </div>
            <div>
              <label>Preview Total (weighted)</label>
              <input value={scorePreview} readOnly />
            </div>
          </div>

          <div className="list">
            {goals.map((goal) => (
              <div key={goal.id} className="item stack">
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong>{goal.name}</strong>
                  <span className="badge">weight {goal.weight}</span>
                </div>
                <div className="row">
                  <select
                    value={scoreDraft.byGoal[goal.id]?.score ?? "3"}
                    onChange={(e) =>
                      setScoreDraft({
                        ...scoreDraft,
                        byGoal: {
                          ...scoreDraft.byGoal,
                          [goal.id]: {
                            ...(scoreDraft.byGoal[goal.id] ?? { score: "3", rationale: "" }),
                            score: e.target.value,
                          },
                        },
                      })
                    }
                  >
                    <option value="1">1 - Harms goal</option>
                    <option value="2">2 - Slightly harms</option>
                    <option value="3">3 - Neutral</option>
                    <option value="4">4 - Advances</option>
                    <option value="5">5 - Strongly advances</option>
                  </select>
                  <input
                    placeholder="Rationale"
                    value={scoreDraft.byGoal[goal.id]?.rationale ?? ""}
                    onChange={(e) =>
                      setScoreDraft({
                        ...scoreDraft,
                        byGoal: {
                          ...scoreDraft.byGoal,
                          [goal.id]: {
                            ...(scoreDraft.byGoal[goal.id] ?? { score: "3", rationale: "" }),
                            rationale: e.target.value,
                          },
                        },
                      })
                    }
                  />
                </div>
              </div>
            ))}
          </div>

          <button className="btn-primary" type="button" disabled={scoring} onClick={() => void onRunScoring()}>
            {scoring ? "Scoring..." : "Run Scoring"}
          </button>
        </div>
      )}

      {message && <div className="badge">{message}</div>}
    </div>
  );
}
