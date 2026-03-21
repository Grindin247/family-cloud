"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, Family, Goal, Person } from "../../lib/api";

type ScopeView = "family" | "mine" | "person";

type GoalFormState = {
  scope_type: "family" | "person";
  owner_person_id: string;
  visibility_scope: "family" | "personal" | "admins";
  name: string;
  description: string;
  weight: string;
  status: Goal["status"];
  priority: string;
  horizon: string;
  target_date: string;
  success_criteria: string;
  review_cadence_days: string;
  next_review_at: string;
  action_types: string;
  tags: string;
};

const EMPTY_FORM: GoalFormState = {
  scope_type: "family",
  owner_person_id: "",
  visibility_scope: "family",
  name: "",
  description: "",
  weight: "0.25",
  status: "active",
  priority: "3",
  horizon: "ongoing",
  target_date: "",
  success_criteria: "",
  review_cadence_days: "",
  next_review_at: "",
  action_types: "",
  tags: "",
};

function toLocalDateTimeInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export default function GoalsPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [view, setView] = useState<ScopeView>("family");
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [currentPersonId, setCurrentPersonId] = useState("");
  const [form, setForm] = useState<GoalFormState>(EMPTY_FORM);
  const [error, setError] = useState("");

  async function loadAll(nextFamilyId?: number | null) {
    const [familyData, me] = await Promise.all([api.listFamilies(), api.getMe().catch(() => ({ authenticated: false, email: null, memberships: [] }))]);
    setFamilies(familyData.items);
    const target = nextFamilyId ?? familyId ?? familyData.items[0]?.id ?? null;
    setFamilyId(target);
    if (!target) {
      setGoals([]);
      setPersons([]);
      return;
    }
    const [personData, goalData] = await Promise.all([
      api.listFamilyPersons(target),
      api.listGoals(target, { include_deleted: false }),
    ]);
    setPersons(personData.items);
    const membership = me.memberships.find((item) => item.family_id === target);
    const inferredCurrentPersonId = membership?.person_id ?? personData.items[0]?.person_id ?? "";
    setCurrentPersonId(inferredCurrentPersonId);
    setSelectedPersonId((prev) => prev || inferredCurrentPersonId);
    setForm((prev) => ({
      ...prev,
      owner_person_id: prev.owner_person_id || inferredCurrentPersonId,
      visibility_scope: prev.scope_type === "person" ? "personal" : "family",
    }));
    setGoals(goalData.items);
  }

  useEffect(() => {
    void loadAll().catch((err) => setError(err instanceof Error ? err.message : "Failed to load goals"));
  }, []);

  useEffect(() => {
    if (!familyId) return;
    void loadAll(familyId).catch((err) => setError(err instanceof Error ? err.message : "Failed to refresh goals"));
  }, [familyId]);

  const visibleGoals = useMemo(() => {
    if (view === "family") return goals.filter((goal) => goal.scope_type === "family");
    if (view === "mine") return goals.filter((goal) => goal.scope_type === "person" && goal.owner_person_id === currentPersonId);
    return goals.filter((goal) => goal.scope_type === "person" && goal.owner_person_id === selectedPersonId);
  }, [goals, view, currentPersonId, selectedPersonId]);

  const personNameMap = useMemo(() => new Map(persons.map((person) => [person.person_id, person.display_name])), [persons]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!familyId) return;
    try {
      await api.createGoal({
        family_id: familyId,
        scope_type: form.scope_type,
        owner_person_id: form.scope_type === "person" ? form.owner_person_id : null,
        visibility_scope: form.scope_type === "person" ? form.visibility_scope : "family",
        name: form.name,
        description: form.description,
        weight: Number(form.weight),
        action_types: form.action_types.split(",").map((item) => item.trim()).filter(Boolean),
        status: form.status,
        priority: form.priority ? Number(form.priority) : null,
        horizon: form.horizon || null,
        target_date: form.target_date || null,
        success_criteria: form.success_criteria || null,
        review_cadence_days: form.review_cadence_days ? Number(form.review_cadence_days) : null,
        next_review_at: form.next_review_at ? new Date(form.next_review_at).toISOString() : null,
        tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
        external_refs: [],
      });
      setForm({
        ...EMPTY_FORM,
        owner_person_id: currentPersonId,
      });
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
          <h2 className="page-title">Goals</h2>
          <p className="page-sub">Manage family and personal goals with review cadence, success criteria, and visibility controls.</p>
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

      <div className="row" style={{ marginBottom: 16 }}>
        <button className={view === "family" ? "btn-primary" : "btn-secondary"} type="button" onClick={() => setView("family")}>Family</button>
        <button className={view === "mine" ? "btn-primary" : "btn-secondary"} type="button" onClick={() => setView("mine")}>Mine</button>
        <button className={view === "person" ? "btn-primary" : "btn-secondary"} type="button" onClick={() => setView("person")}>Person</button>
        {view === "person" && (
          <select value={selectedPersonId} onChange={(e) => setSelectedPersonId(e.target.value)}>
            {persons.map((person) => (
              <option key={person.person_id} value={person.person_id}>{person.display_name}</option>
            ))}
          </select>
        )}
      </div>

      {error && <div className="card">{error}</div>}

      <div className="grid grid-2 panel-grid-top">
        <div className="card">
          <h3>Create Goal</h3>
          <form className="stack" onSubmit={onCreate}>
            <div className="row">
              <select
                value={form.scope_type}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    scope_type: e.target.value as GoalFormState["scope_type"],
                    visibility_scope: e.target.value === "person" ? "personal" : "family",
                    owner_person_id: e.target.value === "person" ? (prev.owner_person_id || currentPersonId) : "",
                  }))
                }
              >
                <option value="family">Family Goal</option>
                <option value="person">Personal Goal</option>
              </select>
              {form.scope_type === "person" && (
                <select value={form.owner_person_id} onChange={(e) => setForm({ ...form, owner_person_id: e.target.value })}>
                  {persons.map((person) => (
                    <option key={person.person_id} value={person.person_id}>{person.display_name}</option>
                  ))}
                </select>
              )}
            </div>
            <div className="row">
              <input placeholder="Goal name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
              <input placeholder="Weight" type="number" step="0.01" min="0.01" value={form.weight} onChange={(e) => setForm({ ...form, weight: e.target.value })} />
            </div>
            <textarea placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required />
            <textarea placeholder="Success criteria" value={form.success_criteria} onChange={(e) => setForm({ ...form, success_criteria: e.target.value })} />
            <div className="row">
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as Goal["status"] })}>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="completed">Completed</option>
                <option value="archived">Archived</option>
              </select>
              <select value={form.horizon} onChange={(e) => setForm({ ...form, horizon: e.target.value })}>
                <option value="immediate">Immediate</option>
                <option value="seasonal">Seasonal</option>
                <option value="annual">Annual</option>
                <option value="long_term">Long term</option>
                <option value="ongoing">Ongoing</option>
              </select>
            </div>
            <div className="row">
              <input placeholder="Priority" type="number" min="1" max="5" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })} />
              <input type="date" value={form.target_date} onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
            </div>
            <div className="row">
              <input placeholder="Review cadence days" type="number" min="1" value={form.review_cadence_days} onChange={(e) => setForm({ ...form, review_cadence_days: e.target.value })} />
              <input type="datetime-local" value={form.next_review_at} onChange={(e) => setForm({ ...form, next_review_at: e.target.value })} />
            </div>
            <div className="row">
              <input placeholder="Action types (comma separated)" value={form.action_types} onChange={(e) => setForm({ ...form, action_types: e.target.value })} />
              <input placeholder="Tags (comma separated)" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
            </div>
            {form.scope_type === "person" && (
              <select value={form.visibility_scope} onChange={(e) => setForm({ ...form, visibility_scope: e.target.value as GoalFormState["visibility_scope"] })}>
                <option value="personal">Owner + admins</option>
                <option value="family">Whole family</option>
                <option value="admins">Admins only</option>
              </select>
            )}
            <button className="btn-primary" type="submit" disabled={!familyId}>Save Goal</button>
          </form>
        </div>

        <div className="card">
          <h3>Current Goals</h3>
          <div className="list">
            {visibleGoals.map((goal) => (
              <GoalRow key={goal.id} goal={goal} personNameMap={personNameMap} onDelete={onDeleteGoal} onSaved={() => void loadAll(familyId)} />
            ))}
            {visibleGoals.length === 0 && <div className="item">No goals yet for this view.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

function GoalRow({
  goal,
  personNameMap,
  onDelete,
  onSaved,
}: {
  goal: Goal;
  personNameMap: Map<string, string>;
  onDelete: (goalId: number) => Promise<void> | void;
  onSaved: () => Promise<void> | void;
}) {
  const [draft, setDraft] = useState<Goal>(goal);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    setDraft(goal);
  }, [goal]);

  async function onSave() {
    await api.updateGoal(goal.id, {
      scope_type: draft.scope_type,
      owner_person_id: draft.scope_type === "person" ? draft.owner_person_id : null,
      visibility_scope: draft.visibility_scope,
      name: draft.name,
      description: draft.description,
      weight: draft.weight,
      action_types: draft.action_types,
      status: draft.status,
      priority: draft.priority,
      horizon: draft.horizon,
      target_date: draft.target_date,
      success_criteria: draft.success_criteria,
      review_cadence_days: draft.review_cadence_days,
      next_review_at: draft.next_review_at,
      tags: draft.tags,
      external_refs: draft.external_refs,
    });
    setSaved("Saved");
    setTimeout(() => setSaved(""), 1200);
    await onSaved();
  }

  return (
    <div className="item stack">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <span className="badge">{draft.scope_type === "family" ? "Family" : `Personal: ${personNameMap.get(draft.owner_person_id ?? "") ?? "Unknown"}`}</span>
        <span className="badge">{draft.status}</span>
      </div>
      <div className="row">
        <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <input type="number" step="0.01" min="0.01" value={draft.weight} onChange={(e) => setDraft({ ...draft, weight: Number(e.target.value) })} />
      </div>
      <textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      <textarea value={draft.success_criteria ?? ""} onChange={(e) => setDraft({ ...draft, success_criteria: e.target.value })} placeholder="Success criteria" />
      <div className="row">
        <select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value as Goal["status"] })}>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="completed">Completed</option>
          <option value="archived">Archived</option>
        </select>
        <select value={draft.horizon ?? ""} onChange={(e) => setDraft({ ...draft, horizon: (e.target.value || null) as Goal["horizon"] })}>
          <option value="immediate">Immediate</option>
          <option value="seasonal">Seasonal</option>
          <option value="annual">Annual</option>
          <option value="long_term">Long term</option>
          <option value="ongoing">Ongoing</option>
        </select>
      </div>
      <div className="row">
        <input type="date" value={draft.target_date ?? ""} onChange={(e) => setDraft({ ...draft, target_date: e.target.value || null })} />
        <input
          type="datetime-local"
          value={toLocalDateTimeInput(draft.next_review_at)}
          onChange={(e) => setDraft({ ...draft, next_review_at: e.target.value ? new Date(e.target.value).toISOString() : null })}
        />
      </div>
      <div className="row">
        <input value={draft.action_types.join(", ")} onChange={(e) => setDraft({ ...draft, action_types: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} />
        <input value={draft.tags.join(", ")} onChange={(e) => setDraft({ ...draft, tags: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ color: "#6a645d" }}>Revision {draft.goal_revision}</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {saved && <span className="badge">{saved}</span>}
          <button className="btn-secondary" type="button" onClick={() => void onSave()}>Update Goal</button>
          <button className="btn-danger" type="button" onClick={() => void onDelete(goal.id)}>Delete Goal</button>
        </div>
      </div>
    </div>
  );
}
