"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  api,
  Assessment,
  Domain,
  EducationSummary,
  FamilyDashboard,
  Goal,
  Journal,
  Learner,
  PracticeRepetition,
  ProgressSnapshot,
  QuizDetail,
  QuizSession,
  Skill,
  ViewerContext,
  ViewerMeResponse,
} from "../lib/api";

type TabKey = "goals" | "activities" | "assignments" | "assessments" | "practice" | "journals" | "quizzes";

type LearnerWorkspace = {
  summary: EducationSummary;
  snapshots: ProgressSnapshot[];
  goals: Goal[];
  activities: Activity[];
  assignments: import("../lib/api").Assignment[];
  assessments: Assessment[];
  practices: PracticeRepetition[];
  journals: Journal[];
  quizzes: QuizSession[];
};

type EditorKind = "learner" | "goal" | "activity" | "assignment" | "assessment" | "practice" | "journal";

type EditorState = {
  kind: EditorKind;
  recordId: string;
  values: Record<string, string>;
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not set";
  const parsed = new Date(value.includes("T") ? value : `${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Not set";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatCompactNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "0";
  return Number(value).toFixed(digits);
}

function toDateInput(value: string | null | undefined): string {
  if (!value) return "";
  if (value.includes("T")) return value.slice(0, 10);
  return value;
}

function toDateTimeInput(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function toIsoDateTime(value: string): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}

function toNullableNumber(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function emptyToNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function scoreSeries(points: Array<{ x: string; y: number | null }>): string {
  const usable = points.filter((point) => point.y !== null).map((point) => point.y as number);
  if (usable.length === 0) return "";
  const min = Math.min(...usable);
  const max = Math.max(...usable);
  const range = max - min || 1;
  return points
    .map((point, index) => {
      const x = points.length === 1 ? 0 : (index / (points.length - 1)) * 100;
      const yValue = point.y ?? min;
      const y = 100 - ((yValue - min) / range) * 100;
      return `${x},${y}`;
    })
    .join(" ");
}

function scoreClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return "tone-muted";
  if (value >= 85) return "tone-leaf";
  if (value >= 70) return "tone-sky";
  if (value >= 50) return "tone-warn";
  return "tone-berry";
}

function statusTone(status: string): string {
  const normalized = status.toLowerCase();
  if (normalized.includes("complete") || normalized.includes("done")) return "tone-leaf";
  if (normalized.includes("progress") || normalized.includes("active")) return "tone-sky";
  if (normalized.includes("paused")) return "tone-warn";
  return "tone-muted";
}

function Sparkline({ points }: { points: Array<{ as_of_date: string; value: number | null }> }) {
  const line = scoreSeries(points.map((point) => ({ x: point.as_of_date, y: point.value })));
  if (!line) return <span className="muted-small">No trend</span>;
  return (
    <svg className="sparkline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={line} fill="none" stroke="currentColor" strokeWidth="6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function MetricChart({
  label,
  points,
  formatter,
}: {
  label: string;
  points: Array<{ as_of_date: string; value: number | null }>;
  formatter?: (value: number | null) => string;
}) {
  const line = scoreSeries(points.map((point) => ({ x: point.as_of_date, y: point.value })));
  const latest = points.at(-1)?.value ?? null;
  return (
    <div className="plot-card">
      <div className="plot-meta">
        <div className="plot-label">{label}</div>
        <div className="plot-value">{formatter ? formatter(latest) : formatCompactNumber(latest, 1)}</div>
      </div>
      {line ? (
        <svg className="plot-chart" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polyline points={line} fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
      ) : (
        <div className="muted-small">Not enough data yet.</div>
      )}
    </div>
  );
}

function TabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button className={active ? "tab-button tab-button-active" : "tab-button"} type="button" onClick={onClick}>
      {label}
    </button>
  );
}

function InputField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

function TextareaField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

export default function EducationPage() {
  const [me, setMe] = useState<ViewerMeResponse | null>(null);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [context, setContext] = useState<ViewerContext | null>(null);
  const [dashboard, setDashboard] = useState<FamilyDashboard | null>(null);
  const [domains, setDomains] = useState<Domain[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [selectedLearnerId, setSelectedLearnerId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<LearnerWorkspace | null>(null);
  const [selectedQuizId, setSelectedQuizId] = useState<string | null>(null);
  const [quizDetail, setQuizDetail] = useState<QuizDetail | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("goals");
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [loadingFamily, setLoadingFamily] = useState(false);
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const domainMap = useMemo(() => new Map(domains.map((domain) => [domain.domain_id, domain])), [domains]);
  const skillMap = useMemo(() => new Map(skills.map((skill) => [skill.skill_id, skill])), [skills]);

  async function loadWorkspace(targetFamilyId: number, learnerId: string, preferredQuizId?: string | null) {
    setLoadingWorkspace(true);
    try {
      const [summary, snapshots, goals, activities, assignments, assessments, practices, journals, quizzes] = await Promise.all([
        api.getEducationSummary(targetFamilyId, learnerId),
        api.listProgressSnapshots(targetFamilyId, learnerId, 30),
        api.listGoals(targetFamilyId, learnerId),
        api.listActivities(targetFamilyId, learnerId, 50),
        api.listAssignments(targetFamilyId, learnerId, 50),
        api.listAssessments(targetFamilyId, learnerId, 50),
        api.listPracticeRepetitions(targetFamilyId, learnerId, 50),
        api.listJournals(targetFamilyId, learnerId, 50),
        api.listQuizzes(targetFamilyId, learnerId, 50),
      ]);
      setWorkspace({ summary, snapshots, goals, activities, assignments, assessments, practices, journals, quizzes });
      const nextQuizId = preferredQuizId && quizzes.some((quiz) => quiz.quiz_id === preferredQuizId) ? preferredQuizId : null;
      setSelectedQuizId(nextQuizId);
      if (nextQuizId) {
        setQuizDetail(await api.getQuiz(targetFamilyId, nextQuizId));
      } else {
        setQuizDetail(null);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load learner workspace.");
      setWorkspace(null);
      setQuizDetail(null);
    } finally {
      setLoadingWorkspace(false);
    }
  }

  async function loadFamily(targetFamilyId: number, preferredLearnerId?: string | null) {
    setLoadingFamily(true);
    setError("");
    setMessage("");
    setEditor(null);
    try {
      const nextContext = await api.getViewerContext(targetFamilyId);
      setContext(nextContext);
      setFamilyId(targetFamilyId);

      if (!nextContext.education_enabled) {
        setDashboard(null);
        setDomains([]);
        setSkills([]);
        setWorkspace(null);
        setSelectedLearnerId(null);
        setSelectedQuizId(null);
        setQuizDetail(null);
        setEditor(null);
        return;
      }

      const [nextDashboard, nextDomains, nextSkills] = await Promise.all([
        api.getFamilyDashboard(targetFamilyId),
        api.listDomains(targetFamilyId),
        api.listSkills(targetFamilyId),
      ]);
      setDashboard(nextDashboard);
      setDomains(nextDomains);
      setSkills(nextSkills);

      const resolvedLearnerId =
        preferredLearnerId && nextDashboard.tracked_learners.some((row) => row.learner.learner_id === preferredLearnerId)
          ? preferredLearnerId
          : nextDashboard.tracked_learners[0]?.learner.learner_id ?? null;

      setSelectedLearnerId(resolvedLearnerId);
      if (resolvedLearnerId) {
        await loadWorkspace(targetFamilyId, resolvedLearnerId, selectedQuizId);
      } else {
        setWorkspace(null);
        setSelectedQuizId(null);
        setQuizDetail(null);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load education workspace.");
    } finally {
      setLoadingFamily(false);
    }
  }

  async function refreshCurrentView(preferredLearnerId?: string | null) {
    if (!familyId) return;
    await loadFamily(familyId, preferredLearnerId ?? selectedLearnerId);
  }

  useEffect(() => {
    void (async () => {
      try {
        const nextMe = await api.getMe();
        setMe(nextMe);
        const firstFamilyId = nextMe.memberships[0]?.family_id ?? null;
        if (firstFamilyId !== null) {
          await loadFamily(firstFamilyId);
        }
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Could not load account context.");
      }
    })();
  }, []);

  async function handleSelectLearner(learnerId: string) {
    if (!familyId) return;
    setSelectedLearnerId(learnerId);
    setEditor(null);
    setMessage("");
    await loadWorkspace(familyId, learnerId);
  }

  async function handleEnableEducation() {
    if (!familyId) return;
    setSubmitting(true);
    try {
      await api.updateEducationFeature(familyId, true, {});
      setMessage("Education tracking enabled for this family.");
      await refreshCurrentView(selectedLearnerId);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not enable education tracking.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCreateLearner(personId: string, displayName: string) {
    if (!familyId) return;
    setSubmitting(true);
    try {
      await api.createLearner({
        family_id: familyId,
        learner_id: personId,
        display_name: displayName,
        status: "active",
      });
      setMessage(`Started tracking ${displayName}.`);
      await refreshCurrentView(personId);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not create learner profile.");
    } finally {
      setSubmitting(false);
    }
  }

  function openLearnerEditor(learner: Learner) {
    setEditor({
      kind: "learner",
      recordId: learner.learner_id,
      values: {
        display_name: learner.display_name,
        birthdate: toDateInput(learner.birthdate),
        timezone: learner.timezone ?? "",
        status: learner.status,
      },
    });
  }

  function openGoalEditor(goal: Goal) {
    setEditor({
      kind: "goal",
      recordId: goal.goal_id,
      values: {
        title: goal.title,
        description: goal.description ?? "",
        status: goal.status,
        start_date: toDateInput(goal.start_date),
        target_date: toDateInput(goal.target_date),
        target_metric_type: goal.target_metric_type ?? "",
        target_metric_value: goal.target_metric_value === null ? "" : String(goal.target_metric_value),
      },
    });
  }

  function openActivityEditor(activity: Activity) {
    setEditor({
      kind: "activity",
      recordId: activity.activity_id,
      values: {
        domain_id: activity.domain_id ?? "",
        skill_id: activity.skill_id ?? "",
        activity_type: activity.activity_type,
        title: activity.title,
        description: activity.description ?? "",
        occurred_at: toDateTimeInput(activity.occurred_at),
        duration_seconds: activity.duration_seconds === null ? "" : String(activity.duration_seconds),
        source_ref: activity.source_ref ?? "",
        source_session_id: activity.source_session_id ?? "",
      },
    });
  }

  function openAssignmentEditor(assignment: import("../lib/api").Assignment) {
    setEditor({
      kind: "assignment",
      recordId: assignment.assignment_id,
      values: {
        title: assignment.title,
        description: assignment.description ?? "",
        assigned_at: toDateTimeInput(assignment.assigned_at),
        due_at: toDateTimeInput(assignment.due_at),
        completed_at: toDateTimeInput(assignment.completed_at),
        source_ref: assignment.source_ref ?? "",
        status: assignment.status,
        max_score: assignment.max_score === null ? "" : String(assignment.max_score),
      },
    });
  }

  function openAssessmentEditor(assessment: Assessment) {
    setEditor({
      kind: "assessment",
      recordId: assessment.assessment_id,
      values: {
        domain_id: assessment.domain_id ?? "",
        skill_id: assessment.skill_id ?? "",
        assignment_id: assessment.assignment_id ?? "",
        activity_id: assessment.activity_id ?? "",
        assessment_type: assessment.assessment_type,
        title: assessment.title,
        occurred_at: toDateTimeInput(assessment.occurred_at),
        score: assessment.score === null ? "" : String(assessment.score),
        max_score: assessment.max_score === null ? "" : String(assessment.max_score),
        percent: assessment.percent === null ? "" : String(assessment.percent),
        confidence_self_report: assessment.confidence_self_report === null ? "" : String(assessment.confidence_self_report),
        graded_by: assessment.graded_by,
        notes: assessment.notes ?? "",
      },
    });
  }

  function openPracticeEditor(practice: PracticeRepetition) {
    setEditor({
      kind: "practice",
      recordId: practice.repetition_id,
      values: {
        domain_id: practice.domain_id ?? "",
        skill_id: practice.skill_id ?? "",
        topic_text: practice.topic_text ?? "",
        occurred_at: toDateTimeInput(practice.occurred_at),
        duration_seconds: practice.duration_seconds === null ? "" : String(practice.duration_seconds),
        attempt_number: practice.attempt_number === null ? "" : String(practice.attempt_number),
        performance_score: practice.performance_score === null ? "" : String(practice.performance_score),
        difficulty_self_report: practice.difficulty_self_report === null ? "" : String(practice.difficulty_self_report),
        confidence_self_report: practice.confidence_self_report === null ? "" : String(practice.confidence_self_report),
        notes: practice.notes ?? "",
      },
    });
  }

  function openJournalEditor(journal: Journal) {
    setEditor({
      kind: "journal",
      recordId: journal.journal_id,
      values: {
        occurred_at: toDateTimeInput(journal.occurred_at),
        title: journal.title ?? "",
        content: journal.content,
        mood_self_report: journal.mood_self_report ?? "",
        effort_self_report: journal.effort_self_report === null ? "" : String(journal.effort_self_report),
      },
    });
  }

  async function handleSaveEditor() {
    if (!editor || !familyId) return;
    setSubmitting(true);
    setError("");
    try {
      if (editor.kind === "learner") {
        await api.updateLearner(editor.recordId, {
          display_name: editor.values.display_name,
          birthdate: emptyToNull(editor.values.birthdate),
          timezone: emptyToNull(editor.values.timezone),
          status: editor.values.status,
        });
      }

      if (editor.kind === "goal") {
        await api.updateGoal(editor.recordId, {
          title: editor.values.title,
          description: emptyToNull(editor.values.description),
          status: editor.values.status,
          start_date: emptyToNull(editor.values.start_date),
          target_date: emptyToNull(editor.values.target_date),
          target_metric_type: emptyToNull(editor.values.target_metric_type),
          target_metric_value: toNullableNumber(editor.values.target_metric_value),
        });
      }

      if (editor.kind === "activity") {
        await api.updateActivity(editor.recordId, {
          domain_id: emptyToNull(editor.values.domain_id),
          skill_id: emptyToNull(editor.values.skill_id),
          activity_type: editor.values.activity_type,
          title: editor.values.title,
          description: emptyToNull(editor.values.description),
          occurred_at: toIsoDateTime(editor.values.occurred_at) ?? new Date().toISOString(),
          duration_seconds: toNullableNumber(editor.values.duration_seconds),
          source_ref: emptyToNull(editor.values.source_ref),
          source_session_id: emptyToNull(editor.values.source_session_id),
        });
      }

      if (editor.kind === "assignment") {
        await api.updateAssignment(editor.recordId, {
          title: editor.values.title,
          description: emptyToNull(editor.values.description),
          assigned_at: toIsoDateTime(editor.values.assigned_at),
          due_at: toIsoDateTime(editor.values.due_at),
          completed_at: toIsoDateTime(editor.values.completed_at),
          source_ref: emptyToNull(editor.values.source_ref),
          status: editor.values.status,
          max_score: toNullableNumber(editor.values.max_score),
        });
      }

      if (editor.kind === "assessment") {
        await api.updateAssessment(editor.recordId, {
          domain_id: emptyToNull(editor.values.domain_id),
          skill_id: emptyToNull(editor.values.skill_id),
          assignment_id: emptyToNull(editor.values.assignment_id),
          activity_id: emptyToNull(editor.values.activity_id),
          assessment_type: editor.values.assessment_type,
          title: editor.values.title,
          occurred_at: toIsoDateTime(editor.values.occurred_at) ?? new Date().toISOString(),
          score: toNullableNumber(editor.values.score),
          max_score: toNullableNumber(editor.values.max_score),
          percent: toNullableNumber(editor.values.percent),
          confidence_self_report: toNullableNumber(editor.values.confidence_self_report),
          graded_by: emptyToNull(editor.values.graded_by),
          notes: emptyToNull(editor.values.notes),
        });
      }

      if (editor.kind === "practice") {
        await api.updatePracticeRepetition(editor.recordId, {
          domain_id: emptyToNull(editor.values.domain_id),
          skill_id: emptyToNull(editor.values.skill_id),
          topic_text: emptyToNull(editor.values.topic_text),
          occurred_at: toIsoDateTime(editor.values.occurred_at) ?? new Date().toISOString(),
          duration_seconds: toNullableNumber(editor.values.duration_seconds),
          attempt_number: toNullableNumber(editor.values.attempt_number),
          performance_score: toNullableNumber(editor.values.performance_score),
          difficulty_self_report: toNullableNumber(editor.values.difficulty_self_report),
          confidence_self_report: toNullableNumber(editor.values.confidence_self_report),
          notes: emptyToNull(editor.values.notes),
        });
      }

      if (editor.kind === "journal") {
        await api.updateJournal(editor.recordId, {
          occurred_at: toIsoDateTime(editor.values.occurred_at) ?? new Date().toISOString(),
          title: emptyToNull(editor.values.title),
          content: editor.values.content,
          mood_self_report: emptyToNull(editor.values.mood_self_report),
          effort_self_report: toNullableNumber(editor.values.effort_self_report),
        });
      }

      setMessage("Saved the correction.");
      const preferredLearnerId = editor.kind === "learner" ? editor.recordId : selectedLearnerId;
      setEditor(null);
      await refreshCurrentView(preferredLearnerId);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save the correction.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleQuizSelect(quizId: string) {
    if (!familyId) return;
    setSelectedQuizId(quizId);
    try {
      setQuizDetail(await api.getQuiz(familyId, quizId));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load quiz detail.");
    }
  }

  const currentLearnerRow = dashboard?.tracked_learners.find((row) => row.learner.learner_id === selectedLearnerId) ?? null;
  const selectedDomainId =
    editor && ["activity", "assessment", "practice"].includes(editor.kind) ? editor.values.domain_id || null : null;
  const filteredSkills = selectedDomainId ? skills.filter((skill) => skill.domain_id === selectedDomainId) : skills;

  const scorePlotPoints =
    workspace?.snapshots
      .slice()
      .reverse()
      .map((snapshot) => ({ as_of_date: snapshot.as_of_date, value: snapshot.avg_score_30d ?? snapshot.latest_score })) ?? [];
  const minutesPlotPoints =
    workspace?.snapshots
      .slice()
      .reverse()
      .map((snapshot) => ({ as_of_date: snapshot.as_of_date, value: snapshot.total_minutes_30d })) ?? [];

  return (
    <div className="education-shell">
      <div className="viewer-orb viewer-orb-left" aria-hidden="true" />
      <div className="viewer-orb viewer-orb-right" aria-hidden="true" />
      <div className="viewer-orb viewer-orb-bottom" aria-hidden="true" />

      <div className="education-stack">
        <header className="education-panel education-header">
          <div className="education-brand">
            <span className="eyebrow">Family Cloud</span>
            <h1>Education Management</h1>
            <p>
              A standalone visibility and correction workspace for what each learner is working on, how they are doing, and
              what the AI may have recorded incorrectly.
            </p>
          </div>

          <div className="education-account">
            <div className="panel-heading">
              <div>
                <h2>Session</h2>
                <p>Family-scoped context comes from the education service and stays modular from decision management.</p>
              </div>
              <span className={me?.authenticated ? "status-chip tone-leaf" : "status-chip tone-muted"}>
                {me?.authenticated ? "Signed in" : "Signed out"}
              </span>
            </div>
            <div className="identity-value">{me?.email ?? "No active session"}</div>
            <div className="chip-row">
              <span className="status-chip tone-muted">{me?.memberships.length ?? 0} families</span>
              {context ? <span className="status-chip tone-muted">{context.is_family_admin ? "Admin view" : "Member view"}</span> : null}
              {context ? (
                <span className={context.education_enabled ? "status-chip tone-leaf" : "status-chip tone-warn"}>
                  {context.education_enabled ? "Education enabled" : "Education disabled"}
                </span>
              ) : null}
            </div>
          </div>
        </header>

        <section className="education-panel toolbar-panel">
          <div className="toolbar-row">
            <label className="field field-inline">
              <span>Family</span>
              <select
                value={familyId ?? ""}
                onChange={(event) => {
                  const nextId = Number(event.target.value);
                  if (nextId) {
                    void loadFamily(nextId);
                  }
                }}
              >
                {me?.memberships.map((membership) => (
                  <option key={membership.family_id} value={membership.family_id}>
                    {membership.family_name}
                  </option>
                ))}
              </select>
            </label>

            <div className="toolbar-actions">
              <button className="action-button action-button-secondary" type="button" onClick={() => void refreshCurrentView()} disabled={loadingFamily || loadingWorkspace}>
                {loadingFamily || loadingWorkspace ? "Refreshing..." : "Refresh"}
              </button>
              {context && !context.education_enabled && context.is_family_admin ? (
                <button className="action-button action-button-primary" type="button" onClick={() => void handleEnableEducation()} disabled={submitting}>
                  {submitting ? "Enabling..." : "Enable Education"}
                </button>
              ) : null}
            </div>
          </div>
        </section>

        {error ? <div className="banner tone-berry">{error}</div> : null}
        {message ? <div className="banner tone-leaf">{message}</div> : null}

        {!me?.memberships.length ? (
          <section className="education-panel empty-card">
            <h3>No linked families</h3>
            <p>This account does not have any family memberships yet, so there is no education workspace to open.</p>
          </section>
        ) : null}

        {context && !context.education_enabled ? (
          <section className="education-panel empty-card">
            <h3>Education tracking is off for this family</h3>
            <p>
              This view is ready, but the education domain is disabled for the selected family. Enable it here to start using
              the standalone education workspace.
            </p>
            {context.is_family_admin ? (
              <button className="action-button action-button-primary" type="button" onClick={() => void handleEnableEducation()} disabled={submitting}>
                {submitting ? "Enabling..." : "Enable education tracking"}
              </button>
            ) : (
              <span className="status-chip tone-muted">Ask a family admin to enable the education domain.</span>
            )}
          </section>
        ) : null}

        {context?.education_enabled && dashboard ? (
          <>
            {dashboard.untracked_persons.length > 0 ? (
              <section className="education-panel section-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Ready To Track</h2>
                    <p>These family people exist in the identity model but do not have learner profiles yet.</p>
                  </div>
                  <span className="status-chip tone-muted">{dashboard.untracked_persons.length} untracked</span>
                </div>
                <div className="person-grid">
                  {dashboard.untracked_persons.map((person) => (
                    <div className="subcard" key={person.person_id}>
                      <div className="subcard-head">
                        <strong>{person.display_name}</strong>
                        <span className="status-chip tone-muted">{person.role_in_family ?? "family"}</span>
                      </div>
                      <div className="muted-small">Person ID {person.person_id}</div>
                      <button
                        className="action-button action-button-primary"
                        type="button"
                        onClick={() => void handleCreateLearner(person.person_id, person.display_name)}
                        disabled={submitting}
                      >
                        {submitting ? "Saving..." : "Create learner profile"}
                      </button>
                    </div>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="stats-grid">
              <div className="stat-card">
                <div className="stat-label">Tracked learners</div>
                <div className="stat-value">{dashboard.kpis.tracked_learner_count}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Active goals</div>
                <div className="stat-value">{dashboard.kpis.active_goal_count}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Open assignments</div>
                <div className="stat-value">{dashboard.kpis.open_assignment_count}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Avg score 30d</div>
                <div className="stat-value">{dashboard.kpis.avg_score_30d === null ? "N/A" : `${dashboard.kpis.avg_score_30d}%`}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">Minutes 30d</div>
                <div className="stat-value">{dashboard.kpis.total_minutes_30d === null ? "N/A" : dashboard.kpis.total_minutes_30d}</div>
              </div>
            </section>

            <section className="education-panel section-panel">
              <div className="panel-heading">
                <div>
                  <h2>Learner Overview</h2>
                  <p>Quickly scan what each learner is up to, how recently they practiced, and whether the data looks right.</p>
                </div>
                <span className="status-chip tone-muted">{dashboard.tracked_learners.length} learners</span>
              </div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Learner</th>
                      <th>Status</th>
                      <th>Current focus</th>
                      <th>Last activity</th>
                      <th>Goals</th>
                      <th>Open work</th>
                      <th>Avg score</th>
                      <th>Latest score</th>
                      <th>Minutes</th>
                      <th>Practice gap</th>
                      <th>Trend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dashboard.tracked_learners.map((row) => (
                      <tr
                        key={row.learner.learner_id}
                        className={row.learner.learner_id === selectedLearnerId ? "is-selected" : ""}
                        onClick={() => void handleSelectLearner(row.learner.learner_id)}
                      >
                        <td>
                          <div className="table-title">{row.learner.display_name}</div>
                          <div className="muted-small">{row.learner.timezone ?? "No timezone"}</div>
                        </td>
                        <td>
                          <span className={`status-chip ${statusTone(row.learner.status)}`}>{row.learner.status}</span>
                        </td>
                        <td>{row.current_focus_text ?? "No current focus"}</td>
                        <td>{formatDateTime(row.last_activity_at)}</td>
                        <td>{row.active_goal_count}</td>
                        <td>{row.open_assignment_count}</td>
                        <td>
                          <span className={`status-chip ${scoreClass(row.avg_score_30d)}`}>
                            {row.avg_score_30d === null ? "N/A" : `${row.avg_score_30d}%`}
                          </span>
                        </td>
                        <td>{row.latest_score === null ? "N/A" : `${row.latest_score}%`}</td>
                        <td>{row.total_minutes_30d ?? "N/A"}</td>
                        <td>{row.days_since_last_practice === null ? "N/A" : `${row.days_since_last_practice}d`}</td>
                        <td className="trend-cell">
                          <Sparkline points={row.score_trend_points} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {currentLearnerRow && workspace ? (
              <>
                <section className="detail-grid">
                  <div className="education-panel section-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>{currentLearnerRow.learner.display_name}</h2>
                        <p>{currentLearnerRow.current_focus_text ?? "No current focus right now."}</p>
                      </div>
                      <button className="action-button action-button-secondary" type="button" onClick={() => openLearnerEditor(currentLearnerRow.learner)}>
                        Edit learner
                      </button>
                    </div>
                    <div className="summary-grid">
                      <div className="summary-item">
                        <span>Latest score</span>
                        <strong>{workspace.summary.stats.latest_score === null ? "N/A" : `${workspace.summary.stats.latest_score}%`}</strong>
                      </div>
                      <div className="summary-item">
                        <span>Avg score 30d</span>
                        <strong>{workspace.summary.stats.avg_score_30d === null ? "N/A" : `${workspace.summary.stats.avg_score_30d}%`}</strong>
                      </div>
                      <div className="summary-item">
                        <span>Minutes 30d</span>
                        <strong>{workspace.summary.stats.total_minutes_30d ?? "N/A"}</strong>
                      </div>
                      <div className="summary-item">
                        <span>Practice gap</span>
                        <strong>
                          {workspace.summary.stats.days_since_last_practice === null ? "N/A" : `${workspace.summary.stats.days_since_last_practice} days`}
                        </strong>
                      </div>
                      <div className="summary-item">
                        <span>Open assignments</span>
                        <strong>{workspace.summary.stats.assignment_open_count}</strong>
                      </div>
                      <div className="summary-item">
                        <span>Journal entries 30d</span>
                        <strong>{workspace.summary.stats.journal_count_30d}</strong>
                      </div>
                    </div>
                  </div>

                  <div className="education-panel section-panel">
                    <div className="panel-heading">
                      <div>
                        <h2>Progress Plots</h2>
                        <p>Snapshot-based trends keep the dashboard fast while still showing recent movement.</p>
                      </div>
                    </div>
                    <div className="plot-grid">
                      <MetricChart label="Score trend" points={scorePlotPoints} formatter={(value) => (value === null ? "N/A" : `${value}%`)} />
                      <MetricChart label="Minutes trend" points={minutesPlotPoints} formatter={(value) => (value === null ? "N/A" : `${value}`)} />
                    </div>
                  </div>
                </section>

                <section className="education-panel section-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Learner Detail</h2>
                      <p>Open a tab to inspect records and correct anything the AI got wrong.</p>
                    </div>
                    <span className="status-chip tone-muted">{loadingWorkspace ? "Loading..." : "Ready"}</span>
                  </div>

                  <div className="tab-row">
                    <TabButton active={activeTab === "goals"} label={`Goals (${workspace.goals.length})`} onClick={() => setActiveTab("goals")} />
                    <TabButton active={activeTab === "activities"} label={`Activities (${workspace.activities.length})`} onClick={() => setActiveTab("activities")} />
                    <TabButton active={activeTab === "assignments"} label={`Assignments (${workspace.assignments.length})`} onClick={() => setActiveTab("assignments")} />
                    <TabButton active={activeTab === "assessments"} label={`Assessments (${workspace.assessments.length})`} onClick={() => setActiveTab("assessments")} />
                    <TabButton active={activeTab === "practice"} label={`Practice (${workspace.practices.length})`} onClick={() => setActiveTab("practice")} />
                    <TabButton active={activeTab === "journals"} label={`Journals (${workspace.journals.length})`} onClick={() => setActiveTab("journals")} />
                    <TabButton active={activeTab === "quizzes"} label={`Quizzes (${workspace.quizzes.length})`} onClick={() => setActiveTab("quizzes")} />
                  </div>

                  {activeTab === "goals" ? (
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Goal</th>
                            <th>Domain</th>
                            <th>Status</th>
                            <th>Window</th>
                            <th>Metric</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {workspace.goals.map((goal) => (
                            <tr key={goal.goal_id}>
                              <td>
                                <div className="table-title">{goal.title}</div>
                                <div className="muted-small">{goal.description ?? "No description"}</div>
                              </td>
                              <td>{domainMap.get(goal.domain_id)?.name ?? "Unknown"}</td>
                              <td><span className={`status-chip ${statusTone(goal.status)}`}>{goal.status}</span></td>
                              <td>{formatDate(goal.start_date)} to {formatDate(goal.target_date)}</td>
                              <td>{goal.target_metric_type ?? "No metric"}{goal.target_metric_value !== null ? ` (${goal.target_metric_value})` : ""}</td>
                              <td><button className="action-link" type="button" onClick={() => openGoalEditor(goal)}>Edit</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {activeTab === "activities" ? (
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Activity</th>
                            <th>Domain</th>
                            <th>Occurred</th>
                            <th>Duration</th>
                            <th>Source</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {workspace.activities.map((activity) => (
                            <tr key={activity.activity_id}>
                              <td>
                                <div className="table-title">{activity.title}</div>
                                <div className="muted-small">{activity.activity_type}</div>
                              </td>
                              <td>{activity.domain_id ? domainMap.get(activity.domain_id)?.name ?? "Unknown" : "Unscoped"}</td>
                              <td>{formatDateTime(activity.occurred_at)}</td>
                              <td>{activity.duration_seconds ?? "N/A"} sec</td>
                              <td>{activity.source}{activity.source_ref ? ` / ${activity.source_ref}` : ""}</td>
                              <td><button className="action-link" type="button" onClick={() => openActivityEditor(activity)}>Edit</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {activeTab === "assignments" ? (
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Assignment</th>
                            <th>Status</th>
                            <th>Due</th>
                            <th>Completed</th>
                            <th>Source</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {workspace.assignments.map((assignment) => (
                            <tr key={assignment.assignment_id}>
                              <td>
                                <div className="table-title">{assignment.title}</div>
                                <div className="muted-small">{assignment.description ?? "No description"}</div>
                              </td>
                              <td><span className={`status-chip ${statusTone(assignment.status)}`}>{assignment.status}</span></td>
                              <td>{formatDateTime(assignment.due_at)}</td>
                              <td>{formatDateTime(assignment.completed_at)}</td>
                              <td>{assignment.source}{assignment.source_ref ? ` / ${assignment.source_ref}` : ""}</td>
                              <td><button className="action-link" type="button" onClick={() => openAssignmentEditor(assignment)}>Edit</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {activeTab === "assessments" ? (
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Assessment</th>
                            <th>Score</th>
                            <th>Occurred</th>
                            <th>Graded by</th>
                            <th>Notes</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {workspace.assessments.map((assessment) => (
                            <tr key={assessment.assessment_id}>
                              <td>
                                <div className="table-title">{assessment.title}</div>
                                <div className="muted-small">{assessment.assessment_type}</div>
                              </td>
                              <td>{assessment.score ?? "N/A"} / {assessment.max_score ?? "N/A"}{assessment.percent !== null ? ` (${assessment.percent}%)` : ""}</td>
                              <td>{formatDateTime(assessment.occurred_at)}</td>
                              <td>{assessment.graded_by}</td>
                              <td>{assessment.notes ?? "No notes"}</td>
                              <td><button className="action-link" type="button" onClick={() => openAssessmentEditor(assessment)}>Edit</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {activeTab === "practice" ? (
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Practice</th>
                            <th>Occurred</th>
                            <th>Duration</th>
                            <th>Performance</th>
                            <th>Confidence</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {workspace.practices.map((practice) => (
                            <tr key={practice.repetition_id}>
                              <td>
                                <div className="table-title">{practice.topic_text ?? "Untitled practice"}</div>
                                <div className="muted-small">{practice.notes ?? "No notes"}</div>
                              </td>
                              <td>{formatDateTime(practice.occurred_at)}</td>
                              <td>{practice.duration_seconds ?? "N/A"} sec</td>
                              <td>{practice.performance_score ?? "N/A"}</td>
                              <td>{practice.confidence_self_report ?? "N/A"}</td>
                              <td><button className="action-link" type="button" onClick={() => openPracticeEditor(practice)}>Edit</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {activeTab === "journals" ? (
                    <div className="table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Journal</th>
                            <th>Occurred</th>
                            <th>Mood</th>
                            <th>Effort</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {workspace.journals.map((journal) => (
                            <tr key={journal.journal_id}>
                              <td>
                                <div className="table-title">{journal.title ?? "Untitled journal"}</div>
                                <div className="muted-small clamp-two">{journal.content}</div>
                              </td>
                              <td>{formatDateTime(journal.occurred_at)}</td>
                              <td>{journal.mood_self_report ?? "N/A"}</td>
                              <td>{journal.effort_self_report ?? "N/A"}</td>
                              <td><button className="action-link" type="button" onClick={() => openJournalEditor(journal)}>Edit</button></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}

                  {activeTab === "quizzes" ? (
                    <div className="quiz-layout">
                      <div className="table-wrap">
                        <table className="data-table">
                          <thead>
                            <tr>
                              <th>Quiz</th>
                              <th>Mode</th>
                              <th>Started</th>
                              <th>Totals</th>
                              <th>Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {workspace.quizzes.map((quiz) => (
                              <tr key={quiz.quiz_id}>
                                <td>
                                  <div className="table-title">{quiz.title}</div>
                                  <div className="muted-small">{quiz.source}{quiz.source_ref ? ` / ${quiz.source_ref}` : ""}</div>
                                </td>
                                <td>{quiz.delivery_mode}</td>
                                <td>{formatDateTime(quiz.started_at ?? quiz.created_at)}</td>
                                <td>{quiz.total_score ?? "N/A"} / {quiz.max_score ?? "N/A"} ({quiz.total_items ?? 0} items)</td>
                                <td>
                                  <button className="action-link" type="button" onClick={() => void handleQuizSelect(quiz.quiz_id)}>
                                    View quiz
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {quizDetail ? (
                        <div className="subcard quiz-detail-card">
                          <div className="subcard-head">
                            <strong>{quizDetail.session.title}</strong>
                            <span className="status-chip tone-muted">{quizDetail.session.delivery_mode}</span>
                          </div>
                          <div className="muted-small">
                            {quizDetail.session.total_score ?? "N/A"} / {quizDetail.session.max_score ?? "N/A"} across {quizDetail.session.total_items ?? 0} items
                          </div>
                          <div className="quiz-items">
                            {quizDetail.items.map((item) => {
                              const response = quizDetail.responses.find((entry) => entry.quiz_item_id === item.quiz_item_id);
                              return (
                                <div className="quiz-item-card" key={item.quiz_item_id}>
                                  <div className="table-title">#{item.position} {item.prompt_text}</div>
                                  <div className="muted-small">Type {item.item_type}</div>
                                  <div className="muted-small">Response {response?.response_json === null || response?.response_json === undefined ? "N/A" : String(response.response_json)}</div>
                                  <div className="muted-small">Score {response?.score ?? "N/A"} / {response?.max_score ?? item.max_score ?? "N/A"}</div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ) : (
                        <div className="subcard quiz-detail-card">
                          <div className="muted-small">Pick a quiz row to inspect the item-by-item detail.</div>
                        </div>
                      )}
                    </div>
                  ) : null}

                  {editor ? (
                    <div className="editor-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Edit {editor.kind}</h2>
                          <p>Make a targeted correction and refresh the learner overview once it saves.</p>
                        </div>
                        <button className="action-button action-button-secondary" type="button" onClick={() => setEditor(null)}>
                          Cancel
                        </button>
                      </div>

                      {editor.kind === "learner" ? (
                        <div className="editor-grid">
                          <InputField label="Display name" value={editor.values.display_name} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, display_name: value } })} />
                          <InputField label="Birthdate" type="date" value={editor.values.birthdate} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, birthdate: value } })} />
                          <InputField label="Timezone" value={editor.values.timezone} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, timezone: value } })} />
                          <InputField label="Status" value={editor.values.status} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, status: value } })} />
                        </div>
                      ) : null}

                      {editor.kind === "goal" ? (
                        <div className="editor-grid">
                          <InputField label="Title" value={editor.values.title} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, title: value } })} />
                          <InputField label="Status" value={editor.values.status} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, status: value } })} />
                          <InputField label="Start date" type="date" value={editor.values.start_date} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, start_date: value } })} />
                          <InputField label="Target date" type="date" value={editor.values.target_date} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, target_date: value } })} />
                          <InputField label="Metric type" value={editor.values.target_metric_type} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, target_metric_type: value } })} />
                          <InputField label="Metric value" type="number" value={editor.values.target_metric_value} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, target_metric_value: value } })} />
                          <TextareaField label="Description" value={editor.values.description} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, description: value } })} />
                        </div>
                      ) : null}

                      {editor.kind === "activity" ? (
                        <div className="editor-grid">
                          <label className="field">
                            <span>Domain</span>
                            <select value={editor.values.domain_id} onChange={(event) => setEditor({ ...editor, values: { ...editor.values, domain_id: event.target.value, skill_id: "" } })}>
                              <option value="">Unscoped</option>
                              {domains.map((domain) => (
                                <option key={domain.domain_id} value={domain.domain_id}>
                                  {domain.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="field">
                            <span>Skill</span>
                            <select value={editor.values.skill_id} onChange={(event) => setEditor({ ...editor, values: { ...editor.values, skill_id: event.target.value } })}>
                              <option value="">No skill</option>
                              {filteredSkills.map((skill) => (
                                <option key={skill.skill_id} value={skill.skill_id}>
                                  {skill.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <InputField label="Activity type" value={editor.values.activity_type} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, activity_type: value } })} />
                          <InputField label="Occurred at" type="datetime-local" value={editor.values.occurred_at} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, occurred_at: value } })} />
                          <InputField label="Duration seconds" type="number" value={editor.values.duration_seconds} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, duration_seconds: value } })} />
                          <InputField label="Source ref" value={editor.values.source_ref} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, source_ref: value } })} />
                          <InputField label="Session id" value={editor.values.source_session_id} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, source_session_id: value } })} />
                          <InputField label="Title" value={editor.values.title} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, title: value } })} />
                          <TextareaField label="Description" value={editor.values.description} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, description: value } })} />
                        </div>
                      ) : null}

                      {editor.kind === "assignment" ? (
                        <div className="editor-grid">
                          <InputField label="Title" value={editor.values.title} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, title: value } })} />
                          <InputField label="Status" value={editor.values.status} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, status: value } })} />
                          <InputField label="Assigned at" type="datetime-local" value={editor.values.assigned_at} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, assigned_at: value } })} />
                          <InputField label="Due at" type="datetime-local" value={editor.values.due_at} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, due_at: value } })} />
                          <InputField label="Completed at" type="datetime-local" value={editor.values.completed_at} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, completed_at: value } })} />
                          <InputField label="Max score" type="number" value={editor.values.max_score} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, max_score: value } })} />
                          <InputField label="Source ref" value={editor.values.source_ref} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, source_ref: value } })} />
                          <TextareaField label="Description" value={editor.values.description} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, description: value } })} />
                        </div>
                      ) : null}

                      {editor.kind === "assessment" ? (
                        <div className="editor-grid">
                          <label className="field">
                            <span>Domain</span>
                            <select value={editor.values.domain_id} onChange={(event) => setEditor({ ...editor, values: { ...editor.values, domain_id: event.target.value, skill_id: "" } })}>
                              <option value="">Unscoped</option>
                              {domains.map((domain) => (
                                <option key={domain.domain_id} value={domain.domain_id}>
                                  {domain.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="field">
                            <span>Skill</span>
                            <select value={editor.values.skill_id} onChange={(event) => setEditor({ ...editor, values: { ...editor.values, skill_id: event.target.value } })}>
                              <option value="">No skill</option>
                              {filteredSkills.map((skill) => (
                                <option key={skill.skill_id} value={skill.skill_id}>
                                  {skill.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <InputField label="Assessment type" value={editor.values.assessment_type} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, assessment_type: value } })} />
                          <InputField label="Occurred at" type="datetime-local" value={editor.values.occurred_at} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, occurred_at: value } })} />
                          <InputField label="Score" type="number" value={editor.values.score} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, score: value } })} />
                          <InputField label="Max score" type="number" value={editor.values.max_score} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, max_score: value } })} />
                          <InputField label="Percent" type="number" value={editor.values.percent} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, percent: value } })} />
                          <InputField label="Confidence" type="number" value={editor.values.confidence_self_report} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, confidence_self_report: value } })} />
                          <InputField label="Graded by" value={editor.values.graded_by} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, graded_by: value } })} />
                          <InputField label="Title" value={editor.values.title} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, title: value } })} />
                          <TextareaField label="Notes" value={editor.values.notes} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, notes: value } })} />
                        </div>
                      ) : null}

                      {editor.kind === "practice" ? (
                        <div className="editor-grid">
                          <label className="field">
                            <span>Domain</span>
                            <select value={editor.values.domain_id} onChange={(event) => setEditor({ ...editor, values: { ...editor.values, domain_id: event.target.value, skill_id: "" } })}>
                              <option value="">Unscoped</option>
                              {domains.map((domain) => (
                                <option key={domain.domain_id} value={domain.domain_id}>
                                  {domain.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="field">
                            <span>Skill</span>
                            <select value={editor.values.skill_id} onChange={(event) => setEditor({ ...editor, values: { ...editor.values, skill_id: event.target.value } })}>
                              <option value="">No skill</option>
                              {filteredSkills.map((skill) => (
                                <option key={skill.skill_id} value={skill.skill_id}>
                                  {skill.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          <InputField label="Occurred at" type="datetime-local" value={editor.values.occurred_at} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, occurred_at: value } })} />
                          <InputField label="Topic" value={editor.values.topic_text} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, topic_text: value } })} />
                          <InputField label="Duration seconds" type="number" value={editor.values.duration_seconds} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, duration_seconds: value } })} />
                          <InputField label="Attempt number" type="number" value={editor.values.attempt_number} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, attempt_number: value } })} />
                          <InputField label="Performance score" type="number" value={editor.values.performance_score} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, performance_score: value } })} />
                          <InputField label="Difficulty self-report" type="number" value={editor.values.difficulty_self_report} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, difficulty_self_report: value } })} />
                          <InputField label="Confidence self-report" type="number" value={editor.values.confidence_self_report} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, confidence_self_report: value } })} />
                          <TextareaField label="Notes" value={editor.values.notes} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, notes: value } })} />
                        </div>
                      ) : null}

                      {editor.kind === "journal" ? (
                        <div className="editor-grid">
                          <InputField label="Occurred at" type="datetime-local" value={editor.values.occurred_at} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, occurred_at: value } })} />
                          <InputField label="Title" value={editor.values.title} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, title: value } })} />
                          <InputField label="Mood" value={editor.values.mood_self_report} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, mood_self_report: value } })} />
                          <InputField label="Effort" type="number" value={editor.values.effort_self_report} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, effort_self_report: value } })} />
                          <TextareaField label="Content" value={editor.values.content} onChange={(value) => setEditor({ ...editor, values: { ...editor.values, content: value } })} />
                        </div>
                      ) : null}

                      <div className="editor-actions">
                        <button className="action-button action-button-primary" type="button" onClick={() => void handleSaveEditor()} disabled={submitting}>
                          {submitting ? "Saving..." : "Save correction"}
                        </button>
                      </div>
                    </div>
                  ) : null}
                </section>
              </>
            ) : context?.education_enabled ? (
              <section className="education-panel empty-card">
                <h3>No tracked learners yet</h3>
                <p>Create a learner profile from the onboarding section above to start using the dashboard.</p>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
