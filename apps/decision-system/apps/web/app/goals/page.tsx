"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, Family, Goal } from "../../lib/api";

export default function GoalsPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [form, setForm] = useState({ name: "", description: "", weight: "0.25", action_types: "", active: true });
  const [error, setError] = useState("");

  async function loadAll(nextFamilyId?: number | null) {
    const familyData = await api.listFamilies();
    setFamilies(familyData.items);
    const target = nextFamilyId ?? familyId ?? familyData.items[0]?.id ?? null;
    setFamilyId(target);
    if (target) {
      const goalData = await api.listGoals(target);
      setGoals(goalData.items);
    } else {
      setGoals([]);
    }
  }

  useEffect(() => {
    void loadAll().catch((err) => setError(err instanceof Error ? err.message : "Failed to load goals"));
  }, []);

  useEffect(() => {
    if (!familyId) return;
    void api
      .listGoals(familyId)
      .then((data) => setGoals(data.items))
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to refresh goals"));
  }, [familyId]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!familyId) return;
    try {
      await api.createGoal({
        family_id: familyId,
        name: form.name,
        description: form.description,
        weight: Number(form.weight),
        action_types: form.action_types.split(",").map((item) => item.trim()).filter(Boolean),
        active: form.active,
      });
      setForm({ name: "", description: "", weight: "0.25", action_types: "", active: true });
      await loadAll(familyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create goal");
    }
  }

  async function onDeleteGoal(goalId: number) {
    if (!familyId) return;
    if (!window.confirm("Delete this goal?")) return;
    try {
      await api.deleteGoal(goalId);
      await loadAll(familyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete goal");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h2 className="page-title">Goals and Weights</h2>
          <p className="page-sub">Define what matters and tune the scoring model over time.</p>
        </div>
        <div style={{ minWidth: 220 }}>
          <label htmlFor="family-select">Family</label>
          <select id="family-select" value={familyId ?? ""} onChange={(e) => setFamilyId(Number(e.target.value))}>
            {families.map((family) => (
              <option key={family.id} value={family.id}>{family.name}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="card">{error}</div>}

      <div className="grid grid-2 panel-grid-top">
        <div className="card">
          <h3>Create Goal</h3>
          <form className="stack" onSubmit={onCreate}>
            <input placeholder="Goal name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            <textarea placeholder="Goal description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required />
            <div className="row">
              <input placeholder="Weight" type="number" step="0.01" min="0.01" value={form.weight} onChange={(e) => setForm({ ...form, weight: e.target.value })} />
              <input placeholder="Action types (comma separated)" value={form.action_types} onChange={(e) => setForm({ ...form, action_types: e.target.value })} />
            </div>
            <label><input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Active</label>
            <button className="btn-primary" type="submit" disabled={!familyId}>Save Goal</button>
          </form>
        </div>

        <div className="card">
          <h3>Current Goals</h3>
          <div className="list">
            {goals.map((goal) => (
              <GoalRow key={goal.id} goal={goal} onDelete={onDeleteGoal} />
            ))}
            {goals.length === 0 && <div className="item">No goals yet for this family.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

function GoalRow({ goal, onDelete }: { goal: Goal; onDelete: (goalId: number) => Promise<void> | void }) {
  const [name, setName] = useState(goal.name);
  const [description, setDescription] = useState(goal.description);
  const [weight, setWeight] = useState(String(goal.weight));
  const [active, setActive] = useState(goal.active);
  const [actionTypes, setActionTypes] = useState(goal.action_types.join(", "));
  const [saved, setSaved] = useState("");

  async function onSave() {
    await api.updateGoal(goal.id, {
      name,
      description,
      weight: Number(weight),
      active,
      action_types: actionTypes.split(",").map((item) => item.trim()).filter(Boolean),
    });
    setSaved("Saved");
    setTimeout(() => setSaved(""), 1000);
  }

  return (
    <div className="item stack">
      <div className="row">
        <input value={name} onChange={(e) => setName(e.target.value)} />
        <input type="number" step="0.01" min="0.01" value={weight} onChange={(e) => setWeight(e.target.value)} />
      </div>
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
      <input value={actionTypes} onChange={(e) => setActionTypes(e.target.value)} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <label><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Active</label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {saved && <span className="badge">{saved}</span>}
          <button className="btn-secondary" type="button" onClick={() => void onSave()}>Update Goal</button>
          <button className="btn-danger" type="button" onClick={() => void onDelete(goal.id)}>Delete Goal</button>
        </div>
      </div>
    </div>
  );
}
