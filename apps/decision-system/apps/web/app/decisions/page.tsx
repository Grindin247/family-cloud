"use client";

import { Dispatch, FormEvent, SetStateAction, useEffect, useMemo, useState } from "react";
import { api, Decision, DecisionGoalContext, DecisionScoreRun, Family, Person } from "../../lib/api";

type ScopeView = "all" | "family" | "mine" | "person";

type DecisionFormState = {
  scope_type: "family" | "person";
  owner_person_id: string;
  target_person_id: string;
  visibility_scope: "family" | "personal" | "admins";
  goal_policy: "family_only" | "family_plus_person";
  category: string;
  title: string;
  description: string;
  desired_outcome: string;
  urgency: string;
  confidence_1_to_5: string;
  target_date: string;
  next_review_at: string;
  tags: string;
  notes: string;
};

type ScoreDraft = {
  threshold: string;
  byGoal: Record<number, { score: string; rationale: string }>;
};

const EMPTY_FORM: DecisionFormState = {
  scope_type: "family",
  owner_person_id: "",
  target_person_id: "",
  visibility_scope: "family",
  goal_policy: "family_only",
  category: "",
  title: "",
  description: "",
  desired_outcome: "",
  urgency: "3",
  confidence_1_to_5: "3",
  target_date: "",
  next_review_at: "",
  tags: "",
  notes: "",
};

function toLocalDateTimeInput(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function buildInitialScoreDraft(context: DecisionGoalContext | null, decision: Decision, scoreRuns: DecisionScoreRun[]): ScoreDraft {
  const byGoal: ScoreDraft["byGoal"] = {};
  const latestRun = scoreRuns[0] ?? decision.latest_score_run;
  for (const goal of [...(context?.family_goals ?? []), ...(context?.person_goals ?? [])]) {
    const previous = latestRun?.components.find((component) => component.goal_id === goal.id);
    byGoal[goal.id] = {
      score: String(previous?.score_1_to_5 ?? 3),
      rationale: previous?.rationale ?? "",
    };
  }
  return {
    threshold: String(latestRun?.threshold_1_to_5 ?? 4),
    byGoal,
  };
}

export default function DecisionsPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [persons, setPersons] = useState<Person[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [scopeView, setScopeView] = useState<ScopeView>("all");
  const [selectedPersonId, setSelectedPersonId] = useState("");
  const [currentPersonId, setCurrentPersonId] = useState("");
  const [form, setForm] = useState<DecisionFormState>(EMPTY_FORM);
  const [error, setError] = useState("");

  async function loadData(targetFamilyId?: number | null) {
    const [familyData, me] = await Promise.all([api.listFamilies(), api.getMe().catch(() => ({ authenticated: false, email: null, memberships: [] }))]);
    setFamilies(familyData.items);
    const activeFamilyId = targetFamilyId ?? familyId ?? familyData.items[0]?.id ?? null;
    setFamilyId(activeFamilyId);
    if (!activeFamilyId) {
      setPersons([]);
      setDecisions([]);
      return;
    }
    const [personData, decisionData] = await Promise.all([
      api.listFamilyPersons(activeFamilyId),
      api.listDecisions(activeFamilyId, { include_scores: true }),
    ]);
    setPersons(personData.items);
    setDecisions(decisionData.items);
    const membership = me.memberships.find((item) => item.family_id === activeFamilyId);
    const inferredCurrentPersonId = membership?.person_id ?? personData.items[0]?.person_id ?? "";
    setCurrentPersonId(inferredCurrentPersonId);
    setSelectedPersonId((prev) => prev || inferredCurrentPersonId);
    setForm((prev) => ({
      ...prev,
      owner_person_id: prev.owner_person_id || inferredCurrentPersonId,
      target_person_id: prev.target_person_id || inferredCurrentPersonId,
    }));
  }

  useEffect(() => {
    void loadData().catch((err) => setError(err instanceof Error ? err.message : "Failed to load decisions"));
  }, []);

  useEffect(() => {
    if (!familyId) return;
    void loadData(familyId).catch((err) => setError(err instanceof Error ? err.message : "Failed to refresh"));
  }, [familyId]);

  const personNameMap = useMemo(() => new Map(persons.map((person) => [person.person_id, person.display_name])), [persons]);

  const visibleDecisions = useMemo(() => {
    if (scopeView === "family") return decisions.filter((decision) => decision.scope_type === "family");
    if (scopeView === "mine") return decisions.filter((decision) => decision.target_person_id === currentPersonId || decision.owner_person_id === currentPersonId);
    if (scopeView === "person") return decisions.filter((decision) => decision.target_person_id === selectedPersonId || decision.owner_person_id === selectedPersonId);
    return decisions;
  }, [decisions, scopeView, currentPersonId, selectedPersonId]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!familyId) return;
    try {
      await api.createDecision({
        family_id: familyId,
        scope_type: form.scope_type,
        owner_person_id: form.scope_type === "person" ? (form.owner_person_id || currentPersonId) : form.owner_person_id || null,
        target_person_id: form.scope_type === "person" ? (form.target_person_id || currentPersonId) : form.target_person_id || null,
        visibility_scope: form.scope_type === "person" ? form.visibility_scope : "family",
        goal_policy: form.scope_type === "person" ? "family_plus_person" : form.goal_policy,
        category: form.category || null,
        title: form.title,
        description: form.description,
        desired_outcome: form.desired_outcome || null,
        cost: null,
        urgency: Number(form.urgency),
        confidence_1_to_5: Number(form.confidence_1_to_5),
        target_date: form.target_date || null,
        next_review_at: form.next_review_at ? new Date(form.next_review_at).toISOString() : null,
        tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
        notes: form.notes,
        constraints: [],
        options: [],
        attachments: [],
        links: [],
        context_snapshot: {},
      });
      setForm({
        ...EMPTY_FORM,
        owner_person_id: currentPersonId,
        target_person_id: currentPersonId,
      });
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
          <p className="page-sub">Capture family and personal decisions, score them against live goal context, and review score history over time.</p>
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

      <div className="row" style={{ marginBottom: 16 }}>
        <button className={scopeView === "all" ? "btn-primary" : "btn-secondary"} type="button" onClick={() => setScopeView("all")}>All</button>
        <button className={scopeView === "family" ? "btn-primary" : "btn-secondary"} type="button" onClick={() => setScopeView("family")}>Family</button>
        <button className={scopeView === "mine" ? "btn-primary" : "btn-secondary"} type="button" onClick={() => setScopeView("mine")}>Mine</button>
        <button className={scopeView === "person" ? "btn-primary" : "btn-secondary"} type="button" onClick={() => setScopeView("person")}>Person</button>
        {scopeView === "person" && (
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
          <h3>Create Decision</h3>
          <form className="stack" onSubmit={onCreate}>
            <div className="row">
              <select
                value={form.scope_type}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    scope_type: e.target.value as DecisionFormState["scope_type"],
                    visibility_scope: e.target.value === "person" ? "personal" : "family",
                    goal_policy: e.target.value === "person" ? "family_plus_person" : "family_only",
                    owner_person_id: e.target.value === "person" ? (prev.owner_person_id || currentPersonId) : "",
                    target_person_id: e.target.value === "person" ? (prev.target_person_id || currentPersonId) : "",
                  }))
                }
              >
                <option value="family">Family Decision</option>
                <option value="person">Personal Decision</option>
              </select>
              <input placeholder="Category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
            </div>
            {form.scope_type === "person" && (
              <div className="row">
                <select value={form.owner_person_id} onChange={(e) => setForm({ ...form, owner_person_id: e.target.value })}>
                  {persons.map((person) => (
                    <option key={person.person_id} value={person.person_id}>{person.display_name} owns</option>
                  ))}
                </select>
                <select value={form.target_person_id} onChange={(e) => setForm({ ...form, target_person_id: e.target.value })}>
                  {persons.map((person) => (
                    <option key={person.person_id} value={person.person_id}>{person.display_name} affected</option>
                  ))}
                </select>
              </div>
            )}
            <input placeholder="Title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required />
            <textarea placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} required />
            <textarea placeholder="Desired outcome" value={form.desired_outcome} onChange={(e) => setForm({ ...form, desired_outcome: e.target.value })} />
            <div className="row">
              <select value={form.visibility_scope} onChange={(e) => setForm({ ...form, visibility_scope: e.target.value as DecisionFormState["visibility_scope"] })}>
                <option value="family">Whole family</option>
                <option value="personal">Owner + admins</option>
                <option value="admins">Admins only</option>
              </select>
              <select value={form.goal_policy} onChange={(e) => setForm({ ...form, goal_policy: e.target.value as DecisionFormState["goal_policy"] })}>
                <option value="family_only">Family goals only</option>
                <option value="family_plus_person">Family + personal goals</option>
              </select>
            </div>
            <div className="row">
              <input type="number" min="1" max="5" value={form.urgency} onChange={(e) => setForm({ ...form, urgency: e.target.value })} placeholder="Urgency" />
              <input type="number" min="1" max="5" value={form.confidence_1_to_5} onChange={(e) => setForm({ ...form, confidence_1_to_5: e.target.value })} placeholder="Confidence" />
            </div>
            <div className="row">
              <input type="date" value={form.target_date} onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
              <input type="datetime-local" value={form.next_review_at} onChange={(e) => setForm({ ...form, next_review_at: e.target.value })} />
            </div>
            <input placeholder="Tags (comma separated)" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} />
            <textarea placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
            <button className="btn-primary" type="submit">Save Decision</button>
          </form>
        </div>

        <div className="card">
          <h3>Decision Backlog</h3>
          <div className="list">
            {visibleDecisions.map((decision) => (
              <DecisionRow
                key={decision.id}
                decision={decision}
                persons={persons}
                currentPersonId={currentPersonId}
                onSaved={() => void loadData(familyId)}
                onDelete={onDeleteDecision}
              />
            ))}
            {visibleDecisions.length === 0 && <div className="item">No decisions yet for this view.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

function DecisionRow({
  decision,
  persons,
  currentPersonId,
  onSaved,
  onDelete,
}: {
  decision: Decision;
  persons: Person[];
  currentPersonId: string;
  onSaved: () => Promise<void> | void;
  onDelete: (decisionId: number) => Promise<void> | void;
}) {
  const [draft, setDraft] = useState<Decision>(decision);
  const [showScoring, setShowScoring] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [context, setContext] = useState<DecisionGoalContext | null>(null);
  const [scoreRuns, setScoreRuns] = useState<DecisionScoreRun[]>([]);
  const [scoreDraft, setScoreDraft] = useState<ScoreDraft>({ threshold: "4", byGoal: {} });
  const [saving, setSaving] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    setDraft(decision);
    setScoreRuns(decision.latest_score_run ? [decision.latest_score_run] : []);
    setContext(null);
    setScoreDraft({ threshold: String(decision.latest_score_run?.threshold_1_to_5 ?? 4), byGoal: {} });
  }, [decision]);

  const personNameMap = useMemo(() => new Map(persons.map((person) => [person.person_id, person.display_name])), [persons]);

  async function ensureScoringData() {
    if (context) return;
    const [goalContext, scoreHistory] = await Promise.all([
      api.getDecisionGoalContext(decision.id),
      api.listDecisionScoreRuns(decision.id).then((response) => response.items),
    ]);
    setContext(goalContext);
    setScoreRuns(scoreHistory);
    setScoreDraft(buildInitialScoreDraft(goalContext, decision, scoreHistory));
  }

  async function onSaveDecision() {
    setSaving(true);
    setMessage("");
    try {
      await api.updateDecision(decision.id, {
        scope_type: draft.scope_type,
        owner_person_id: draft.scope_type === "person" ? draft.owner_person_id : null,
        target_person_id: draft.scope_type === "person" ? draft.target_person_id : draft.target_person_id,
        visibility_scope: draft.visibility_scope,
        goal_policy: draft.goal_policy,
        category: draft.category,
        title: draft.title,
        description: draft.description,
        desired_outcome: draft.desired_outcome,
        urgency: draft.urgency,
        confidence_1_to_5: draft.confidence_1_to_5,
        target_date: draft.target_date,
        next_review_at: draft.next_review_at,
        tags: draft.tags,
        notes: draft.notes,
        constraints: draft.constraints,
        options: draft.options,
        attachments: draft.attachments,
        links: draft.links,
        context_snapshot: draft.context_snapshot,
      });
      setMessage("Decision updated.");
      await onSaved();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to update decision.");
    } finally {
      setSaving(false);
    }
  }

  async function onRunScoring() {
    if (!context) {
      await ensureScoringData();
    }
    const goalContext = context ?? (await api.getDecisionGoalContext(decision.id));
    const goals = [...goalContext.family_goals, ...goalContext.person_goals];
    if (goals.length === 0) {
      setMessage("Add active goals before scoring.");
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
        threshold_1_to_5: Number(scoreDraft.threshold || "4"),
        computed_by: "human",
        scored_by_person_id: currentPersonId || null,
        context_snapshot: {
          scored_from: "web_client",
          scored_at: new Date().toISOString(),
        },
      });

      setScoreRuns((prev) => [response.score_run, ...prev]);
      setMessage(`Scored ${response.weighted_total_1_to_5.toFixed(2)} / 5 and routed to ${response.status}.`);
      await onSaved();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to run scoring.");
    } finally {
      setScoring(false);
    }
  }

  const groupedGoals = {
    family: context?.family_goals ?? [],
    person: context?.person_goals ?? [],
  };

  return (
    <div className="item stack">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <span className="badge">{draft.status}</span>
        {draft.latest_score_run ? (
          <span className="score">{draft.latest_score_run.weighted_total_1_to_5.toFixed(2)} / 5</span>
        ) : (
          <span className="badge">Unscored</span>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <span className="badge">{draft.scope_type === "family" ? "Family" : "Personal"}</span>
        {draft.owner_person_id && <span className="badge">Owner: {personNameMap.get(draft.owner_person_id) ?? "Unknown"}</span>}
        {draft.target_person_id && <span className="badge">For: {personNameMap.get(draft.target_person_id) ?? "Unknown"}</span>}
      </div>

      <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
      <textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
      <textarea value={draft.desired_outcome ?? ""} onChange={(e) => setDraft({ ...draft, desired_outcome: e.target.value })} placeholder="Desired outcome" />
      <div className="row">
        <select value={draft.scope_type} onChange={(e) => setDraft({ ...draft, scope_type: e.target.value as Decision["scope_type"] })}>
          <option value="family">Family</option>
          <option value="person">Personal</option>
        </select>
        <select value={draft.goal_policy} onChange={(e) => setDraft({ ...draft, goal_policy: e.target.value as Decision["goal_policy"] })}>
          <option value="family_only">Family only</option>
          <option value="family_plus_person">Family + personal</option>
        </select>
      </div>
      <div className="row">
        <select value={draft.owner_person_id ?? ""} onChange={(e) => setDraft({ ...draft, owner_person_id: e.target.value || null })}>
          <option value="">No owner</option>
          {persons.map((person) => (
            <option key={person.person_id} value={person.person_id}>{person.display_name}</option>
          ))}
        </select>
        <select value={draft.target_person_id ?? ""} onChange={(e) => setDraft({ ...draft, target_person_id: e.target.value || null })}>
          <option value="">No target</option>
          {persons.map((person) => (
            <option key={person.person_id} value={person.person_id}>{person.display_name}</option>
          ))}
        </select>
      </div>
      <div className="row">
        <input type="number" min="1" max="5" value={draft.urgency ?? ""} onChange={(e) => setDraft({ ...draft, urgency: e.target.value ? Number(e.target.value) : null })} />
        <input type="number" min="1" max="5" value={draft.confidence_1_to_5 ?? ""} onChange={(e) => setDraft({ ...draft, confidence_1_to_5: e.target.value ? Number(e.target.value) : null })} />
      </div>
      <div className="row">
        <input type="date" value={draft.target_date ?? ""} onChange={(e) => setDraft({ ...draft, target_date: e.target.value || null })} />
        <input
          type="datetime-local"
          value={toLocalDateTimeInput(draft.next_review_at)}
          onChange={(e) => setDraft({ ...draft, next_review_at: e.target.value ? new Date(e.target.value).toISOString() : null })}
        />
      </div>
      <input value={draft.tags.join(", ")} onChange={(e) => setDraft({ ...draft, tags: e.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} />
      <textarea value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} placeholder="Notes" />

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn-secondary" type="button" disabled={saving} onClick={() => void onSaveDecision()}>
          {saving ? "Saving..." : "Update Decision"}
        </button>
        <button className="btn-danger" type="button" onClick={() => void onDelete(decision.id)}>
          Delete Decision
        </button>
        <button className="btn-primary" type="button" onClick={() => void ensureScoringData().then(() => setShowScoring((value) => !value))}>
          {showScoring ? "Hide Scoring" : "Score Decision"}
        </button>
        <button className="btn-secondary" type="button" onClick={() => void ensureScoringData().then(() => setShowHistory((value) => !value))}>
          {showHistory ? "Hide History" : "Recent Activity"}
        </button>
      </div>

      {showScoring && context && (
        <div className="card" style={{ marginTop: 4 }}>
          <h3 style={{ marginTop: 0 }}>Goal Context Scoring</h3>
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
              <label>Goal Policy</label>
              <input value={context.goal_policy} readOnly />
            </div>
          </div>

          {groupedGoals.family.length > 0 && <GoalScoreGroup title="Family Goals" goals={groupedGoals.family} scoreDraft={scoreDraft} setScoreDraft={setScoreDraft} />}
          {groupedGoals.person.length > 0 && <GoalScoreGroup title="Personal Goals" goals={groupedGoals.person} scoreDraft={scoreDraft} setScoreDraft={setScoreDraft} />}

          <button className="btn-primary" type="button" disabled={scoring} onClick={() => void onRunScoring()}>
            {scoring ? "Scoring..." : "Run Score"}
          </button>
        </div>
      )}

      {showHistory && (
        <div className="card" style={{ marginTop: 4 }}>
          <h3 style={{ marginTop: 0 }}>Recent Activity</h3>
          <div className="list">
            {scoreRuns.slice(0, 5).map((run) => (
              <div className="item" key={run.id}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong>{new Date(run.created_at).toLocaleString()}</strong>
                  <span className="badge">{run.status_after_run}</span>
                </div>
                <div style={{ marginTop: 6, color: "#6a645d" }}>
                  {run.weighted_total_1_to_5.toFixed(2)} / 5, threshold {run.threshold_1_to_5.toFixed(1)}, {run.routed_to}
                </div>
                <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {run.components.map((component) => (
                    <span key={component.id} className="badge">
                      {component.goal_name}: {component.score_1_to_5}
                    </span>
                  ))}
                </div>
              </div>
            ))}
            {scoreRuns.length === 0 && <div className="item">No score history yet.</div>}
          </div>
        </div>
      )}

      {message && <div className="badge">{message}</div>}
    </div>
  );
}

function GoalScoreGroup({
  title,
  goals,
  scoreDraft,
  setScoreDraft,
}: {
  title: string;
  goals: DecisionGoalContext["family_goals"];
  scoreDraft: ScoreDraft;
  setScoreDraft: Dispatch<SetStateAction<ScoreDraft>>;
}) {
  return (
    <div className="list" style={{ marginBottom: 12 }}>
      <strong>{title}</strong>
      {goals.map((goal) => (
        <div key={goal.id} className="item stack">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <strong>{goal.name}</strong>
            <span className="badge">weight {goal.weight}</span>
          </div>
          <div style={{ color: "#6a645d" }}>{goal.description}</div>
          <div className="row">
            <select
              value={scoreDraft.byGoal[goal.id]?.score ?? "3"}
              onChange={(e) =>
                setScoreDraft((prev) => ({
                  ...prev,
                  byGoal: {
                    ...prev.byGoal,
                    [goal.id]: {
                      ...(prev.byGoal[goal.id] ?? { score: "3", rationale: "" }),
                      score: e.target.value,
                    },
                  },
                }))
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
                setScoreDraft((prev) => ({
                  ...prev,
                  byGoal: {
                    ...prev.byGoal,
                    [goal.id]: {
                      ...(prev.byGoal[goal.id] ?? { score: "3", rationale: "" }),
                      rationale: e.target.value,
                    },
                  },
                }))
              }
            />
          </div>
        </div>
      ))}
    </div>
  );
}
