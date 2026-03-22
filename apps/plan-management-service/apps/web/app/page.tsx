"use client";

import { useEffect, useMemo, useState } from "react";
import { api, GoalOption, Plan, PlanInstance, PlanPreview, ViewerContext, ViewerMeResponse } from "../lib/api";

const PLAN_KIND_OPTIONS = [
  { value: "routine", label: "Routine" },
  { value: "habit", label: "Habit" },
  { value: "program", label: "Program" },
  { value: "fitness_plan", label: "Fitness plan" },
  { value: "meal_plan", label: "Meal plan" },
  { value: "study_plan", label: "Study plan" },
  { value: "custom", label: "Custom" },
] as const;

const WEEKDAY_OPTIONS = [
  { value: "monday", label: "Mon" },
  { value: "tuesday", label: "Tue" },
  { value: "wednesday", label: "Wed" },
  { value: "thursday", label: "Thu" },
  { value: "friday", label: "Fri" },
  { value: "saturday", label: "Sat" },
  { value: "sunday", label: "Sun" },
] as const;

type PlanForm = {
  title: string;
  summary: string;
  plan_kind: string;
  owner_scope: "family" | "person";
  owner_person_id: string;
  participant_person_ids: string[];
  frequency: "daily" | "weekly";
  timezone: string;
  weekdays: string[];
  local_time: string;
  goal_id: string;
  goal_scope: "family" | "person";
  goal_weight: string;
  goal_rationale: string;
  suggestion_title: string;
  suggestion_summary: string;
  feasibility_status: string;
  feasibility_note: string;
};

function initialForm(): PlanForm {
  return {
    title: "",
    summary: "",
    plan_kind: "routine",
    owner_scope: "family",
    owner_person_id: "",
    participant_person_ids: [],
    frequency: "weekly",
    timezone: "America/New_York",
    weekdays: ["monday", "wednesday", "friday"],
    local_time: "07:15:00",
    goal_id: "",
    goal_scope: "family",
    goal_weight: "0.8",
    goal_rationale: "",
    suggestion_title: "",
    suggestion_summary: "",
    feasibility_status: "ready",
    feasibility_note: "",
  };
}

function personName(context: ViewerContext | null, personId: string | null | undefined): string {
  if (!personId) return "Family";
  return context?.persons.find((person) => person.person_id === personId)?.display_name || personId;
}

function statusTone(status: string): string {
  if (status === "active" || status === "done") return "tone-leaf";
  if (status === "draft" || status === "scheduled") return "tone-sky";
  if (status === "paused" || status === "skipped") return "tone-warn";
  if (status === "archived" || status === "missed") return "tone-berry";
  return "tone-muted";
}

function formatLabel(value: string): string {
  return value.replaceAll("_", " ");
}

function formatTimeLabel(value: string | null | undefined): string {
  if (!value) return "time TBD";
  const normalized = value.length === 5 ? `${value}:00` : value;
  const parsed = new Date(`1970-01-01T${normalized}`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

function weekdaySummary(days: string[]): string {
  if (!days.length) return "No days selected";
  return days
    .map((day) => WEEKDAY_OPTIONS.find((option) => option.value === day)?.label || day.slice(0, 3))
    .join(" / ");
}

function scheduleSummaryFromForm(form: PlanForm): string {
  if (form.frequency === "daily") {
    return `Daily at ${formatTimeLabel(form.local_time)}${form.timezone ? ` (${form.timezone})` : ""}`;
  }
  return `${weekdaySummary(form.weekdays)} at ${formatTimeLabel(form.local_time)}${form.timezone ? ` (${form.timezone})` : ""}`;
}

function scheduleSummaryFromPlan(plan: Plan | null): string {
  if (!plan?.schedule.frequency) return "Schedule not set";
  if (plan.schedule.frequency === "daily") {
    return `Daily at ${formatTimeLabel(plan.schedule.local_time)}${plan.schedule.timezone ? ` (${plan.schedule.timezone})` : ""}`;
  }
  return `${weekdaySummary(plan.schedule.weekdays)} at ${formatTimeLabel(plan.schedule.local_time)}${plan.schedule.timezone ? ` (${plan.schedule.timezone})` : ""}`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Not scheduled";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function Page() {
  const [me, setMe] = useState<ViewerMeResponse | null>(null);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [context, setContext] = useState<ViewerContext | null>(null);
  const [goalOptions, setGoalOptions] = useState<GoalOption[]>([]);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<string>("");
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [instances, setInstances] = useState<PlanInstance[]>([]);
  const [preview, setPreview] = useState<PlanPreview | null>(null);
  const [form, setForm] = useState<PlanForm>(initialForm());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dashboard = useMemo(() => {
    const active = plans.filter((plan) => plan.status === "active").length;
    const drafts = plans.filter((plan) => plan.status === "draft").length;
    const familyPlans = plans.filter((plan) => plan.owner_scope === "family").length;
    const completion = plans.reduce((count, plan) => count + plan.adherence_summary.completed_count, 0);
    return { active, drafts, familyPlans, completion };
  }, [plans]);

  const selectedMembership = useMemo(
    () => me?.memberships.find((membership) => membership.family_id === familyId) || me?.memberships[0] || null,
    [familyId, me],
  );

  const selectedParticipants = useMemo(
    () => context?.persons.filter((person) => form.participant_person_ids.includes(person.person_id)) || [],
    [context, form.participant_person_ids],
  );

  const draftIssues = useMemo(() => {
    const issues: string[] = [];
    if (!form.title.trim()) issues.push("Add a plan title.");
    if (form.owner_scope === "person" && !form.owner_person_id) issues.push("Choose an owner for an individual plan.");
    if (form.frequency === "weekly" && !form.weekdays.length) issues.push("Pick at least one weekday for a weekly plan.");
    if (!form.local_time.trim()) issues.push("Set a local time for the schedule.");
    return issues;
  }, [form]);

  const nextScheduledInstance = useMemo(
    () => instances.find((instance) => instance.status === "scheduled") || null,
    [instances],
  );

  const canCreateDraft = Boolean(familyId && context?.planning_enabled && !saving && draftIssues.length === 0);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        setError(null);
        const nextMe = await api.getMe();
        setMe(nextMe);
        const membership = nextMe.memberships[0];
        if (!membership) {
          setFamilyId(null);
          setContext(null);
          return;
        }
        setFamilyId(membership.family_id);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Could not load the planning workspace.");
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  useEffect(() => {
    if (!familyId) return;
    void refreshWorkspace(familyId, selectedPlanId || undefined);
  }, [familyId]);

  useEffect(() => {
    if (!familyId || !selectedPlanId || !context?.planning_enabled) return;
    void loadPlanDetail(familyId, selectedPlanId);
  }, [familyId, selectedPlanId, context?.planning_enabled]);

  async function refreshWorkspace(nextFamilyId: number, preferredPlanId?: string) {
    try {
      setLoading(true);
      setError(null);
      const [nextContext, nextGoals] = await Promise.all([api.getViewerContext(nextFamilyId), api.getGoalOptions(nextFamilyId)]);
      setContext(nextContext);
      setGoalOptions(nextGoals.items);
      if (!nextContext.planning_enabled) {
        setPlans([]);
        setSelectedPlan(null);
        setSelectedPlanId("");
        setInstances([]);
        return;
      }
      const nextPlans = (await api.listPlans(nextFamilyId)).items;
      setPlans(nextPlans);
      const selected = preferredPlanId && nextPlans.some((plan) => plan.plan_id === preferredPlanId) ? preferredPlanId : nextPlans[0]?.plan_id || "";
      setSelectedPlanId(selected);
      if (!selected) {
        setSelectedPlan(null);
        setInstances([]);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not refresh planning data.");
    } finally {
      setLoading(false);
    }
  }

  async function loadPlanDetail(nextFamilyId: number, planId: string) {
    try {
      setLoading(true);
      setError(null);
      const [plan, planInstances] = await Promise.all([api.getPlan(nextFamilyId, planId), api.listInstances(nextFamilyId, planId)]);
      setSelectedPlan(plan);
      setInstances(planInstances.items);
      setPreview(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load the selected plan.");
    } finally {
      setLoading(false);
    }
  }

  async function enablePlanning() {
    if (!familyId) return;
    try {
      setSaving(true);
      setError(null);
      await api.updatePlanningFeature(familyId, true);
      await refreshWorkspace(familyId);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not enable planning.");
    } finally {
      setSaving(false);
    }
  }

  async function createDraftPlan() {
    if (!familyId) return;
    if (draftIssues.length) {
      setError(draftIssues[0]);
      return;
    }
    try {
      setSaving(true);
      setError(null);
      const payload = {
        title: form.title,
        summary: form.summary || null,
        plan_kind: form.plan_kind,
        status: "draft",
        owner_scope: form.owner_scope,
        owner_person_id: form.owner_scope === "person" ? form.owner_person_id || null : null,
        participant_person_ids: form.participant_person_ids,
        schedule: {
          timezone: form.timezone || null,
          frequency: form.frequency,
          interval: 1,
          weekdays: form.frequency === "weekly" ? form.weekdays : [],
          local_time: form.local_time || null,
          excluded_dates: [],
        },
        goal_links: form.goal_id
          ? [
              {
                goal_id: Number(form.goal_id),
                goal_scope: form.goal_scope,
                weight: Number(form.goal_weight || "0.8"),
                rationale: form.goal_rationale || null,
              },
            ]
          : [],
        task_suggestions: form.suggestion_title
          ? [
              {
                title: form.suggestion_title,
                summary: form.suggestion_summary || null,
                status: "suggested",
              },
            ]
          : [],
        feasibility_summary: {
          status: form.feasibility_status,
          notes: form.feasibility_note ? [form.feasibility_note] : [],
        },
      };
      const created = await api.createPlan(familyId, payload);
      setForm(initialForm());
      await refreshWorkspace(familyId, created.plan_id);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not create the draft plan.");
    } finally {
      setSaving(false);
    }
  }

  async function runPreview() {
    if (!familyId || !selectedPlan) return;
    try {
      setPreviewing(true);
      setError(null);
      const nextPreview = await api.previewPlan(familyId, selectedPlan.plan_id);
      setPreview(nextPreview);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not preview the selected plan.");
    } finally {
      setPreviewing(false);
    }
  }

  async function mutatePlan(action: "activate" | "pause" | "archive") {
    if (!familyId || !selectedPlan) return;
    try {
      setSaving(true);
      setError(null);
      const updated =
        action === "activate"
          ? await api.activatePlan(familyId, selectedPlan.plan_id)
          : action === "pause"
            ? await api.pausePlan(familyId, selectedPlan.plan_id)
            : await api.archivePlan(familyId, selectedPlan.plan_id);
      await refreshWorkspace(familyId, updated.plan_id);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not update the plan.");
    } finally {
      setSaving(false);
    }
  }

  async function recordOutcome(status: "done" | "skipped", instanceId: string) {
    if (!familyId || !selectedPlan) return;
    try {
      setSaving(true);
      setError(null);
      const updated = await api.recordCheckin(familyId, selectedPlan.plan_id, {
        plan_instance_id: instanceId,
        status,
        note: status === "done" ? "Completed from the planning workspace." : "Skipped from the planning workspace.",
        confidence: status === "done" ? "high" : "medium",
        blockers: [],
      });
      setSelectedPlan(updated);
      const nextInstances = await api.listInstances(familyId, selectedPlan.plan_id);
      setInstances(nextInstances.items);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not record the check-in.");
    } finally {
      setSaving(false);
    }
  }

  function toggleParticipant(personId: string) {
    setForm((current) => ({
      ...current,
      participant_person_ids: current.participant_person_ids.includes(personId)
        ? current.participant_person_ids.filter((item) => item !== personId)
        : [...current.participant_person_ids, personId],
    }));
  }

  function toggleWeekday(day: string) {
    setForm((current) => ({
      ...current,
      weekdays: current.weekdays.includes(day) ? current.weekdays.filter((item) => item !== day) : [...current.weekdays, day],
    }));
  }

  return (
    <main className="planning-shell">
      <div className="planning-glow planning-glow-left" aria-hidden="true" />
      <div className="planning-glow planning-glow-right" aria-hidden="true" />
      <div className="planning-glow planning-glow-bottom" aria-hidden="true" />

      <section className="hero panel">
        <div className="eyebrow">Planning Workspace</div>
        <div className="hero-grid">
          <div className="hero-copy">
            <h1>Family plans, routines, habits, and programs in one system of record.</h1>
            <p>
              Build family and individual plans, preview the next two weeks, and track what actually happened with
              plan instances and check-ins.
            </p>
            <div className="status-row">
              <span className={`status-chip ${context?.planning_enabled ? "tone-leaf" : "tone-warn"}`}>
                {context?.planning_enabled ? "Planning enabled" : "Planning disabled"}
              </span>
              {selectedPlan?.status ? <span className={`status-chip ${statusTone(selectedPlan.status)}`}>{selectedPlan.status}</span> : null}
              {me?.email ? <span className="status-chip tone-muted">{me.email}</span> : null}
            </div>
          </div>
          <div className="hero-side">
            <article className="meta-card">
              <span>Workspace focus</span>
              <strong>{selectedMembership?.family_name || "No family selected"}</strong>
              <p className="helper">
                {selectedPlan
                  ? `${selectedPlan.title} · ${scheduleSummaryFromPlan(selectedPlan)}`
                  : `Draft cadence: ${scheduleSummaryFromForm(form)}`}
              </p>
            </article>
            <div className="summary-grid">
              <article className="summary-card">
                <span>Active plans</span>
                <strong>{dashboard.active}</strong>
              </article>
              <article className="summary-card">
                <span>Draft plans</span>
                <strong>{dashboard.drafts}</strong>
              </article>
              <article className="summary-card">
                <span>Family plans</span>
                <strong>{dashboard.familyPlans}</strong>
              </article>
              <article className="summary-card">
                <span>Completed check-ins</span>
                <strong>{dashboard.completion}</strong>
              </article>
            </div>
          </div>
        </div>
      </section>

      {error ? <section className="alert panel error">{error}</section> : null}

      {!me?.memberships.length ? (
        <section className="panel empty-state">This account is not attached to a family yet, so there is no planning workspace to open.</section>
      ) : (
      <section className="workspace">
        <aside className="sidebar panel">
          <div className="panel-head">
            <div>
              <h2>Plan library</h2>
              <p className="muted-copy">{selectedMembership?.family_name || `Family ${familyId || "not selected"}`}</p>
            </div>
            {!context?.planning_enabled ? (
              <button className="action-button primary" disabled={saving} onClick={enablePlanning} type="button">
                {saving ? "Enabling..." : "Enable"}
              </button>
            ) : null}
          </div>

          {loading && !context ? <p className="muted-copy">Loading planning context...</p> : null}

          {context?.planning_enabled ? (
            <>
              <div className="family-picker">
                <label className="field">
                  <span>Family</span>
                  <select
                    value={String(familyId || "")}
                    onChange={(event) => {
                      const nextFamilyId = Number(event.target.value);
                      setFamilyId(nextFamilyId);
                      setSelectedPlanId("");
                      setSelectedPlan(null);
                      setInstances([]);
                      setPreview(null);
                    }}
                  >
                    {me?.memberships.map((membership) => (
                      <option key={`${membership.family_id}-${membership.member_id}`} value={membership.family_id}>
                        {membership.family_name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <article className="focus-card">
                <span>Draft snapshot</span>
                <strong>{form.title.trim() || "Untitled draft"}</strong>
                <p className="helper">
                  {scheduleSummaryFromForm(form)} ·{" "}
                  {selectedParticipants.length
                    ? `${selectedParticipants.length} participant${selectedParticipants.length === 1 ? "" : "s"} selected`
                    : "No participants selected yet"}
                </p>
                <div className="status-row">
                  <span className="status-chip tone-sky">{formatLabel(form.plan_kind)}</span>
                  <span className="status-chip tone-muted">{form.owner_scope === "family" ? "Family-owned" : "Individual plan"}</span>
                  {form.goal_id ? <span className="status-chip tone-leaf">Goal linked</span> : null}
                </div>
              </article>

              <div className="plan-list">
                {plans.map((plan) => (
                  <button
                    className={`plan-card ${selectedPlanId === plan.plan_id ? "active" : ""}`}
                    key={plan.plan_id}
                    onClick={() => setSelectedPlanId(plan.plan_id)}
                    type="button"
                  >
                    <div className="plan-card-top">
                      <strong>{plan.title}</strong>
                      <span className={`status-chip ${statusTone(plan.status)}`}>{plan.status}</span>
                    </div>
                    <p>{plan.summary || "No summary yet."}</p>
                    <div className="plan-card-meta">
                      <span>{formatLabel(plan.plan_kind)}</span>
                      <span>{plan.owner_scope === "family" ? "Family" : personName(context, plan.owner_person_id)}</span>
                    </div>
                  </button>
                ))}
                {!plans.length ? <p className="muted-copy">No plans yet. Create the first draft on the right.</p> : null}
              </div>
            </>
          ) : (
            <p className="muted-copy">Enable the planning domain for this family to begin creating plans.</p>
          )}
        </aside>

        <section className="detail-stack">
          <section className="panel editor-panel">
            <div className="panel-head">
              <div>
                <h2>Create Draft</h2>
                <p className="muted-copy">Keep v1 focused: plans own cadence and structure, tasks stay linked suggestions only.</p>
              </div>
              <button className="action-button primary" disabled={!canCreateDraft} onClick={createDraftPlan} type="button">
                {saving ? "Saving..." : "Create draft"}
              </button>
            </div>

            <div className="detail-grid create-detail-grid">
              <article className="detail-card">
                <span>Draft cadence</span>
                <strong>{form.frequency === "daily" ? "Daily" : "Weekly"}</strong>
                <p>{scheduleSummaryFromForm(form)}</p>
              </article>
              <article className="detail-card">
                <span>Participants</span>
                <strong>{selectedParticipants.length}</strong>
                <p>{selectedParticipants.map((person) => person.display_name).join(", ") || "Pick the people this draft is for."}</p>
              </article>
              <article className="detail-card">
                <span>Readiness</span>
                <strong>{draftIssues.length ? `${draftIssues.length} to fix` : "Ready"}</strong>
                <p>{draftIssues[0] || "The draft has the minimum fields needed to save."}</p>
              </article>
            </div>

            {draftIssues.length ? (
              <div className="form-alert">
                <strong>Finish these before creating the draft:</strong>
                <p>{draftIssues.join(" ")}</p>
              </div>
            ) : null}

            <div className="form-grid">
              <label className="field">
                <span>Title</span>
                <input value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} placeholder="Beginner strength block" />
              </label>
              <label className="field">
                <span>Kind</span>
                <select value={form.plan_kind} onChange={(event) => setForm((current) => ({ ...current, plan_kind: event.target.value }))}>
                  {PLAN_KIND_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Scope</span>
                <select value={form.owner_scope} onChange={(event) => setForm((current) => ({ ...current, owner_scope: event.target.value as "family" | "person" }))}>
                  <option value="family">Family plan</option>
                  <option value="person">Individual plan</option>
                </select>
              </label>
              <label className="field">
                <span>Owner</span>
                <select value={form.owner_person_id} onChange={(event) => setForm((current) => ({ ...current, owner_person_id: event.target.value }))}>
                  <option value="">Family-owned</option>
                  {context?.persons.map((person) => (
                    <option key={person.person_id} value={person.person_id}>
                      {person.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field field-wide">
                <span>Summary</span>
                <textarea value={form.summary} onChange={(event) => setForm((current) => ({ ...current, summary: event.target.value }))} placeholder="Short summary of the cadence, checkpoints, and why this matters." />
              </label>
              <label className="field">
                <span>Frequency</span>
                <select value={form.frequency} onChange={(event) => setForm((current) => ({ ...current, frequency: event.target.value as "daily" | "weekly" }))}>
                  <option value="weekly">Weekly</option>
                  <option value="daily">Daily</option>
                </select>
              </label>
              <label className="field">
                <span>Timezone</span>
                <input value={form.timezone} onChange={(event) => setForm((current) => ({ ...current, timezone: event.target.value }))} placeholder="America/New_York" />
              </label>
              <label className="field">
                <span>Local time</span>
                <input
                  onChange={(event) => setForm((current) => ({ ...current, local_time: event.target.value ? `${event.target.value}:00` : "" }))}
                  placeholder="07:15"
                  step={60}
                  type="time"
                  value={form.local_time ? form.local_time.slice(0, 5) : ""}
                />
              </label>
              <div className="field">
                <span>Weekdays</span>
                <div className="chip-grid">
                  {WEEKDAY_OPTIONS.map((option) => (
                    <button
                      className={`chip-button ${form.weekdays.includes(option.value) ? "selected" : ""}`}
                      key={option.value}
                      onClick={() => toggleWeekday(option.value)}
                      type="button"
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="field field-wide field-full">
                <span>Participants</span>
                <div className="person-grid">
                  {context?.persons.map((person) => (
                    <button
                      className={`person-pill ${form.participant_person_ids.includes(person.person_id) ? "selected" : ""}`}
                      key={person.person_id}
                      onClick={() => toggleParticipant(person.person_id)}
                      type="button"
                    >
                      {person.display_name}
                    </button>
                  ))}
                </div>
                <p className="helper">{selectedParticipants.map((person) => person.display_name).join(", ") || "Choose who this plan applies to."}</p>
              </div>
              <label className="field">
                <span>Goal</span>
                <select value={form.goal_id} onChange={(event) => setForm((current) => ({ ...current, goal_id: event.target.value }))}>
                  <option value="">No goal link</option>
                  {goalOptions.map((goal) => (
                    <option key={goal.goal_id} value={goal.goal_id}>
                      {goal.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Goal weight</span>
                <input
                  inputMode="decimal"
                  onChange={(event) => setForm((current) => ({ ...current, goal_weight: event.target.value }))}
                  step="0.1"
                  type="number"
                  value={form.goal_weight}
                />
              </label>
              <label className="field field-wide">
                <span>Goal rationale</span>
                <textarea value={form.goal_rationale} onChange={(event) => setForm((current) => ({ ...current, goal_rationale: event.target.value }))} placeholder="Explain how this plan supports the linked goal." />
              </label>
              <label className="field">
                <span>Task suggestion</span>
                <input value={form.suggestion_title} onChange={(event) => setForm((current) => ({ ...current, suggestion_title: event.target.value }))} placeholder="Buy resistance bands" />
              </label>
              <label className="field">
                <span>Suggestion summary</span>
                <input value={form.suggestion_summary} onChange={(event) => setForm((current) => ({ ...current, suggestion_summary: event.target.value }))} placeholder="Prep/admin work only" />
              </label>
              <label className="field">
                <span>Feasibility status</span>
                <input value={form.feasibility_status} onChange={(event) => setForm((current) => ({ ...current, feasibility_status: event.target.value }))} />
              </label>
              <label className="field field-wide">
                <span>Feasibility note</span>
                <textarea value={form.feasibility_note} onChange={(event) => setForm((current) => ({ ...current, feasibility_note: event.target.value }))} placeholder="Moderate fit for weeknights; prep under 30 minutes." />
              </label>
            </div>
          </section>

          <section className="panel detail-panel">
            <div className="panel-head">
              <div>
                <h2>{selectedPlan?.title || "Selected Plan"}</h2>
                <p className="muted-copy">{selectedPlan?.summary || "Choose a plan to inspect its details, preview, and check-ins."}</p>
              </div>
              {selectedPlan ? (
                <div className="action-row">
                  <button className="action-button ghost" disabled={previewing} onClick={runPreview}>
                    {previewing ? "Previewing..." : "Preview 14 days"}
                  </button>
                  {selectedPlan.status === "draft" || selectedPlan.status === "paused" ? (
                    <button className="action-button primary" disabled={saving} onClick={() => mutatePlan("activate")}>
                      Activate
                    </button>
                  ) : null}
                  {selectedPlan.status === "active" ? (
                    <button className="action-button ghost" disabled={saving} onClick={() => mutatePlan("pause")}>
                      Pause
                    </button>
                  ) : null}
                  {selectedPlan.status !== "archived" ? (
                    <button className="action-button danger" disabled={saving} onClick={() => mutatePlan("archive")}>
                      Archive
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>

            {selectedPlan ? (
              <>
                <div className="status-row">
                  <span className={`status-chip ${statusTone(selectedPlan.status)}`}>{selectedPlan.status}</span>
                  <span className="status-chip tone-muted">{formatLabel(selectedPlan.plan_kind)}</span>
                  <span className="status-chip tone-muted">{selectedPlan.owner_scope === "family" ? "Family plan" : `Owner: ${personName(context, selectedPlan.owner_person_id)}`}</span>
                  <span className="status-chip tone-sky">{scheduleSummaryFromPlan(selectedPlan)}</span>
                </div>

                <div className="detail-grid">
                  <article className="detail-card">
                    <span>Alignment</span>
                    <strong>{selectedPlan.alignment_summary.label}</strong>
                    <p>{selectedPlan.alignment_summary.summary}</p>
                  </article>
                  <article className="detail-card">
                    <span>Adherence</span>
                    <strong>{Math.round(selectedPlan.adherence_summary.adherence_rate * 100)}%</strong>
                    <p>
                      {selectedPlan.adherence_summary.completed_count} done, {selectedPlan.adherence_summary.skipped_count} skipped,{" "}
                      {selectedPlan.adherence_summary.missed_count} missed.
                    </p>
                  </article>
                  <article className="detail-card">
                    <span>Missing fields</span>
                    <strong>{selectedPlan.missing_fields.length}</strong>
                    <p>{selectedPlan.missing_fields.length ? selectedPlan.missing_fields.join(", ") : "Activation-ready."}</p>
                  </article>
                  <article className="detail-card">
                    <span>Next scheduled</span>
                    <strong>{nextScheduledInstance ? formatDateTime(nextScheduledInstance.scheduled_for) : "Not queued"}</strong>
                    <p>{selectedPlan.adherence_summary.upcoming_count} upcoming instance(s) in the current schedule.</p>
                  </article>
                </div>

                <div className="two-column">
                  <section className="subpanel">
                    <h3>Goal links</h3>
                    {selectedPlan.goal_links.length ? (
                      selectedPlan.goal_links.map((goal) => (
                        <article className="list-row" key={goal.goal_id}>
                          <strong>{goal.goal_name_snapshot}</strong>
                          <span>weight {goal.weight}</span>
                          <p>{goal.rationale || "No rationale recorded."}</p>
                        </article>
                      ))
                    ) : (
                      <p className="muted-copy">No goals linked yet.</p>
                    )}
                  </section>

                  <section className="subpanel">
                    <h3>Task suggestions</h3>
                    {selectedPlan.task_suggestions.length ? (
                      selectedPlan.task_suggestions.map((item) => (
                        <article className="list-row" key={item.suggestion_id || item.title}>
                          <strong>{item.title}</strong>
                          <span>{item.status}</span>
                          <p>{item.summary || "Prep or admin support item."}</p>
                        </article>
                      ))
                    ) : (
                      <p className="muted-copy">No linked task suggestions.</p>
                    )}
                  </section>
                </div>

                <section className="subpanel">
                  <h3>Plan instances</h3>
                  <div className="instance-list">
                    {instances.map((instance) => (
                      <article className="instance-row" key={instance.instance_id}>
                        <div>
                          <strong>{formatDateTime(instance.scheduled_for)}</strong>
                          <p>{instance.replacement_summary || "Recorded through the plan instance lifecycle."}</p>
                        </div>
                        <div className="instance-actions">
                          <span className={`status-chip ${statusTone(instance.status)}`}>{instance.status}</span>
                          {instance.status === "scheduled" ? (
                            <>
                              <button className="action-button compact primary" onClick={() => recordOutcome("done", instance.instance_id)} type="button">
                                Done
                              </button>
                              <button className="action-button compact ghost" onClick={() => recordOutcome("skipped", instance.instance_id)} type="button">
                                Skip
                              </button>
                            </>
                          ) : null}
                        </div>
                      </article>
                    ))}
                    {!instances.length ? <p className="muted-copy">No materialized plan instances yet.</p> : null}
                  </div>
                </section>

                {preview ? (
                  <section className="subpanel">
                    <h3>Preview</h3>
                    <div className="instance-list">
                      {preview.items.map((instance) => (
                        <article className="instance-row" key={instance.instance_id}>
                          <div>
                            <strong>{formatDateTime(instance.scheduled_for)}</strong>
                            <p>Projected as a scheduled occurrence.</p>
                          </div>
                          <span className="status-chip tone-sky">scheduled</span>
                        </article>
                      ))}
                    </div>
                    {preview.missing_fields.length ? <p className="helper">Still missing: {preview.missing_fields.join(", ")}</p> : null}
                    {preview.task_suggestions.length ? (
                      <div className="preview-suggestions">
                        {preview.task_suggestions.map((item) => (
                          <article className="list-row" key={item.suggestion_id || item.title}>
                            <div>
                              <strong>{item.title}</strong>
                              <p>{item.summary || "Prep or admin support item."}</p>
                            </div>
                            <span className="status-chip tone-muted">{item.status}</span>
                          </article>
                        ))}
                      </div>
                    ) : null}
                  </section>
                ) : null}
              </>
            ) : (
              <p className="muted-copy">Choose a plan from the left to open its details.</p>
            )}
          </section>
        </section>
      </section>
      )}
    </main>
  );
}
