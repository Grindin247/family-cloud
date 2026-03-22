"use client";

import { FormEvent, Fragment, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  api,
  QuestionAttempt,
  QuestionEvent,
  QuestionHistoryResponse,
  QuestionItem,
  QuestionViewerContextResponse,
  QuestionViewerMeResponse,
  ViewerMembership,
} from "../lib/api";

type FilterState = {
  status: string;
  domain: string;
  category: string;
  urgency: string;
  source_agent: string;
  include_inactive: boolean;
};

type SortKey = "updated_at" | "topic" | "domain" | "category" | "urgency" | "status" | "due_at" | "source_agent";
type SortDirection = "asc" | "desc";
type SortState = {
  key: SortKey;
  direction: SortDirection;
};

type ComboFieldProps = {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
};

const EMPTY_FILTERS: FilterState = {
  status: "",
  domain: "",
  category: "",
  urgency: "",
  source_agent: "",
  include_inactive: false,
};

const DEFAULT_SORT: SortState = {
  key: "updated_at",
  direction: "desc",
};

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function uniqueOptions(items: QuestionItem[], key: keyof QuestionItem): string[] {
  return Array.from(new Set(items.map((item) => String(item[key] ?? "")).filter(Boolean))).sort((left, right) =>
    left.localeCompare(right, undefined, { sensitivity: "base" })
  );
}

function toneClass(value: string): string {
  if (value === "critical" || value === "resolved") return "tone-fire";
  if (value === "high" || value === "asked") return "tone-sun";
  if (value === "dismissed" || value === "expired") return "tone-ash";
  return "tone-sky";
}

function roleTone(role: string | undefined): string {
  if (role === "admin") return "tone-fire";
  if (role === "viewer") return "tone-ash";
  return "tone-leaf";
}

function sortValue(question: QuestionItem, key: SortKey): number | string {
  switch (key) {
    case "updated_at":
      return Date.parse(question.updated_at) || 0;
    case "topic":
      return question.topic;
    case "domain":
      return question.domain;
    case "category":
      return question.category;
    case "urgency":
      return question.urgency;
    case "status":
      return question.status;
    case "due_at":
      return question.due_at ? Date.parse(question.due_at) || 0 : 0;
    case "source_agent":
      return question.source_agent;
  }
}

function sortQuestions(items: QuestionItem[], sort: SortState): QuestionItem[] {
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
  const direction = sort.direction === "asc" ? 1 : -1;

  return [...items].sort((left, right) => {
    const leftValue = sortValue(left, sort.key);
    const rightValue = sortValue(right, sort.key);

    let comparison = 0;
    if (typeof leftValue === "number" && typeof rightValue === "number") {
      comparison = leftValue - rightValue;
    } else {
      comparison = collator.compare(String(leftValue), String(rightValue));
    }

    if (comparison === 0) {
      comparison = collator.compare(left.id, right.id);
    }

    return comparison * direction;
  });
}

function sortGlyph(sort: SortState, key: SortKey): string {
  if (sort.key !== key) return "↕";
  return sort.direction === "asc" ? "↑" : "↓";
}

function ComboField({ label, value, options, onChange, placeholder, disabled = false, className }: ComboFieldProps) {
  const inputId = useId();
  const listboxId = `${inputId}-options`;
  const containerRef = useRef<HTMLLabelElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [editingValue, setEditingValue] = useState(value);
  const [filterText, setFilterText] = useState("");

  useEffect(() => {
    if (!isOpen) {
      setEditingValue(value);
      setFilterText("");
    }
  }, [isOpen, value]);

  useEffect(() => {
    if (!isOpen) return undefined;

    function handlePointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    function handleFocusIn() {
      const activeElement = document.activeElement;
      if (activeElement && !containerRef.current?.contains(activeElement)) {
        setIsOpen(false);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("focusin", handleFocusIn);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("focusin", handleFocusIn);
    };
  }, [isOpen]);

  const normalizedFilter = filterText.trim().toLowerCase();
  const visibleOptions = normalizedFilter
    ? options.filter((option) => option.toLowerCase().includes(normalizedFilter))
    : options;

  function openMenu() {
    if (disabled) return;
    setEditingValue(value);
    setFilterText("");
    setIsOpen(true);
  }

  function closeMenu() {
    setIsOpen(false);
    setEditingValue(value);
    setFilterText("");
  }

  function handleSelect(option: string) {
    onChange(option);
    setEditingValue(option);
    setFilterText("");
    setIsOpen(false);
    inputRef.current?.focus();
  }

  return (
    <label className={className} ref={containerRef}>
      {label}
      <div className={isOpen ? "combo-box is-open" : "combo-box"}>
        <div className="combo-input-wrap">
          <input
            aria-autocomplete="list"
            aria-controls={listboxId}
            aria-expanded={isOpen}
            autoComplete="off"
            className="combo-input"
            disabled={disabled}
            id={inputId}
            onChange={(event) => {
              const nextValue = event.target.value;
              setEditingValue(nextValue);
              setFilterText(nextValue);
              setIsOpen(true);
              onChange(nextValue);
            }}
            onClick={() => {
              if (!isOpen) openMenu();
            }}
            onFocus={() => {
              if (!isOpen) openMenu();
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                openMenu();
              }
              if (event.key === "Escape") {
                event.preventDefault();
                closeMenu();
                inputRef.current?.blur();
              }
            }}
            placeholder={placeholder}
            ref={inputRef}
            role="combobox"
            value={isOpen ? editingValue : value}
          />
          <button
            aria-label={`${isOpen ? "Close" : "Open"} ${label} options`}
            className="combo-toggle"
            disabled={disabled}
            onClick={() => {
              if (isOpen) {
                closeMenu();
                return;
              }
              inputRef.current?.focus();
              openMenu();
            }}
            type="button"
          >
            <span aria-hidden="true">{isOpen ? "▲" : "▼"}</span>
          </button>
        </div>

        {isOpen ? (
          <div className="combo-menu" id={listboxId} role="listbox">
            {visibleOptions.length ? (
              visibleOptions.map((option) => (
                <button
                  className={option === value ? "combo-option is-selected" : "combo-option"}
                  key={option}
                  onClick={() => handleSelect(option)}
                  type="button"
                >
                  <span>{option}</span>
                  {option === value ? <span className="combo-option-badge">Selected</span> : null}
                </button>
              ))
            ) : (
              <div className="combo-empty">No matching known values</div>
            )}
          </div>
        ) : null}
      </div>
    </label>
  );
}

export default function QuestionsPage() {
  const [me, setMe] = useState<QuestionViewerMeResponse | null>(null);
  const [viewerContext, setViewerContext] = useState<QuestionViewerContextResponse | null>(null);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [appliedFilters, setAppliedFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [questions, setQuestions] = useState<QuestionItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expandedQuestionIds, setExpandedQuestionIds] = useState<string[]>([]);
  const [history, setHistory] = useState<QuestionHistoryResponse | null>(null);
  const [answerDraft, setAnswerDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);

  async function loadQuestions(nextFamilyId: number, nextFilters: FilterState) {
    setLoading(true);
    try {
      const response = await api.listQuestions({
        family_id: nextFamilyId,
        ...nextFilters,
      });
      setQuestions(response.items);
      setSelectedId((current) => (current && response.items.some((item) => item.id === current) ? current : response.items[0]?.id ?? null));
      setExpandedQuestionIds((current) => current.filter((id) => response.items.some((item) => item.id === id)));
      setAppliedFilters(nextFilters);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load questions");
    } finally {
      setLoading(false);
    }
  }

  async function refreshAll(nextFamilyId?: number, nextFilters?: FilterState) {
    const resolvedFamilyId = nextFamilyId ?? familyId;
    const resolvedFilters = nextFilters ?? appliedFilters;
    if (!resolvedFamilyId) return;
    await loadQuestions(resolvedFamilyId, resolvedFilters);
  }

  async function bootstrapFamily(nextFamilyId: number) {
    setLoading(true);
    setQuestions([]);
    setHistory(null);
    setExpandedQuestionIds([]);
    try {
      const [contextResponse] = await Promise.all([api.getViewerContext(nextFamilyId)]);
      setViewerContext(contextResponse);
      setFilters(EMPTY_FILTERS);
      setAppliedFilters(EMPTY_FILTERS);
      setSort(DEFAULT_SORT);
      await loadQuestions(nextFamilyId, EMPTY_FILTERS);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load question workspace");
      setLoading(false);
    }
  }

  useEffect(() => {
    async function boot() {
      try {
        const meResponse = await api.getMe();
        setMe(meResponse);
        const nextFamilyId = meResponse.memberships[0]?.family_id ?? null;
        setFamilyId(nextFamilyId);
        if (nextFamilyId) {
          await bootstrapFamily(nextFamilyId);
        } else {
          setLoading(false);
          setError("No families are linked to this account yet.");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load question workspace");
        setLoading(false);
      }
    }
    void boot();
  }, []);

  useEffect(() => {
    async function loadHistory() {
      if (!familyId || !selectedId) {
        setHistory(null);
        return;
      }
      try {
        const response = await api.getHistory(familyId, selectedId);
        setHistory(response);
        const selected = questions.find((item) => item.id === selectedId);
        setAnswerDraft(selected?.answer_text ?? "");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load question history");
      }
    }
    void loadHistory();
  }, [familyId, selectedId, questions]);

  const selectedQuestion = useMemo(() => questions.find((item) => item.id === selectedId) ?? null, [questions, selectedId]);
  const domains = useMemo(() => uniqueOptions(questions, "domain"), [questions]);
  const categories = useMemo(() => uniqueOptions(questions, "category"), [questions]);
  const sourceAgents = useMemo(() => uniqueOptions(questions, "source_agent"), [questions]);
  const sortedQuestions = useMemo(() => sortQuestions(questions, sort), [questions, sort]);
  const activeMembership: ViewerMembership | undefined = me?.memberships.find((item) => item.family_id === familyId);
  const activePerson = viewerContext?.persons?.find((person) => person.person_id === activeMembership?.person_id);

  const pendingCount = questions.filter((question) => ["pending", "asked", "answered_partial"].includes(question.status)).length;
  const criticalCount = questions.filter((question) => question.urgency === "critical").length;
  const dueSoonCount = questions.filter((question) => {
    if (!question.due_at) return false;
    const dueAt = Date.parse(question.due_at);
    return Number.isFinite(dueAt) && dueAt - Date.now() <= 24 * 60 * 60 * 1000;
  }).length;
  const answeredCount = questions.filter((question) => question.answer_text?.trim()).length;

  async function handleFamilyChange(nextFamilyId: number) {
    setFamilyId(nextFamilyId || null);
    if (nextFamilyId) {
      await bootstrapFamily(nextFamilyId);
    }
  }

  async function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!familyId) return;
    await refreshAll(familyId, filters);
  }

  async function handleResetFilters() {
    if (!familyId) return;
    setFilters(EMPTY_FILTERS);
    await refreshAll(familyId, EMPTY_FILTERS);
  }

  async function submitAnswer(status: "resolved" | "answered_partial") {
    if (!familyId || !selectedQuestion || !answerDraft.trim()) return;
    setSaving(true);
    try {
      await api.answerQuestion(familyId, selectedQuestion.id, answerDraft.trim(), status);
      await refreshAll();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save answer");
    } finally {
      setSaving(false);
    }
  }

  async function resolveSelected(status: "resolved" | "dismissed" | "expired" | "answered_partial") {
    if (!familyId || !selectedQuestion) return;
    setSaving(true);
    try {
      await api.resolveQuestion(familyId, selectedQuestion.id, status);
      await refreshAll();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update question");
    } finally {
      setSaving(false);
    }
  }

  async function purgeFiltered(all: boolean) {
    if (!familyId) return;
    setSaving(true);
    try {
      await api.purgeQuestions(familyId, all ? { all: true } : { ...appliedFilters });
      await refreshAll();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to purge questions");
    } finally {
      setSaving(false);
    }
  }

  async function deleteSelected() {
    if (!familyId || !selectedQuestion) return;
    setSaving(true);
    try {
      await api.deleteQuestion(familyId, selectedQuestion.id);
      await refreshAll();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete question");
    } finally {
      setSaving(false);
    }
  }

  function handleSort(key: SortKey) {
    setSort((current) =>
      current.key === key
        ? {
            key,
            direction: current.direction === "asc" ? "desc" : "asc",
          }
        : {
            key,
            direction: key === "updated_at" || key === "due_at" ? "desc" : "asc",
          }
    );
  }

  function toggleExpanded(questionId: string) {
    setExpandedQuestionIds((current) => (current.includes(questionId) ? current.filter((id) => id !== questionId) : [...current, questionId]));
  }

  return (
    <main className="viewer-shell">
      <div className="viewer-orb viewer-orb-left" aria-hidden="true" />
      <div className="viewer-orb viewer-orb-right" aria-hidden="true" />
      <div className="viewer-orb viewer-orb-bottom" aria-hidden="true" />

      <div className="viewer-stack">
        <section className="viewer-panel viewer-header">
          <div className="viewer-brand">
            <span className="eyebrow">Question Management</span>
            <h1>Question Viewer</h1>
            <p>
              Review queued questions in the same polished workflow as the event viewer, with table-first scanning, guided filters,
              and a clean detail workspace for fast answers.
            </p>
          </div>

          <aside className="viewer-user">
            <div className="panel-heading panel-heading-tight">
              <div>
                <h2>User Context</h2>
                <p>Identity, family scope, and response permissions for the current review session.</p>
              </div>
            </div>

            <div className="context-email">{me?.email ?? "Waiting for sign-in"}</div>

            <div className="chip-row">
              <span className="status-chip">{loading ? "Loading" : me?.authenticated ? "Signed in" : "Signed out"}</span>
              {activeMembership ? <span className={`status-chip ${roleTone(activeMembership.role)}`}>{activeMembership.role}</span> : null}
            </div>

            <div className="context-facts">
              <article className="fact-card">
                <span>Family</span>
                <strong>{activeMembership?.family_name ?? "Not selected"}</strong>
              </article>
              <article className="fact-card">
                <span>Current person</span>
                <strong>{activePerson?.display_name ?? activeMembership?.person_id ?? "Unknown"}</strong>
              </article>
              <article className="fact-card">
                <span>Access</span>
                <strong>{viewerContext?.is_family_admin ? "Admin visibility" : "Question review"}</strong>
              </article>
              <article className="fact-card">
                <span>Selected</span>
                <strong>{selectedQuestion?.topic ?? "Choose a row"}</strong>
              </article>
            </div>
          </aside>
        </section>

        <section className="viewer-panel filter-panel">
          <div className="panel-heading">
            <div>
              <h2>Filter Options</h2>
              <p>Use guided combo boxes where the service already knows likely values, then refine the table below.</p>
            </div>
            <div className="hint-chip">Known domains, categories, and source agents are selectable in combo fields</div>
          </div>

          <form className="filter-form" onSubmit={submitFilters}>
            <label>
              Family
              <select value={familyId ?? ""} onChange={(event) => void handleFamilyChange(Number(event.target.value))} disabled={!me?.memberships.length}>
                {(me?.memberships ?? []).map((membership) => (
                  <option key={membership.family_id} value={membership.family_id}>
                    {membership.family_name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Status
              <select value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}>
                <option value="">Any status</option>
                {["pending", "asked", "answered_partial", "resolved", "dismissed", "expired"].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Urgency
              <select value={filters.urgency} onChange={(event) => setFilters((current) => ({ ...current, urgency: event.target.value }))}>
                <option value="">Any urgency</option>
                {["low", "medium", "high", "critical"].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>

            <label className="checkbox-field">
              Include inactive
              <div className="toggle-row">
                <input
                  checked={filters.include_inactive}
                  onChange={(event) => setFilters((current) => ({ ...current, include_inactive: event.target.checked }))}
                  type="checkbox"
                />
                <span>Show resolved, dismissed, and expired records in table results</span>
              </div>
            </label>

            <ComboField
              label="Domain"
              onChange={(value) => setFilters((current) => ({ ...current, domain: value }))}
              options={domains}
              placeholder="Choose or type a domain"
              value={filters.domain}
            />

            <ComboField
              label="Category"
              onChange={(value) => setFilters((current) => ({ ...current, category: value }))}
              options={categories}
              placeholder="Choose or type a category"
              value={filters.category}
            />

            <ComboField
              label="Source agent"
              onChange={(value) => setFilters((current) => ({ ...current, source_agent: value }))}
              options={sourceAgents}
              placeholder="Choose or type an agent id"
              value={filters.source_agent}
            />

            <div className="action-row field-span-full">
              <button type="submit" className="btn-primary" disabled={!familyId || loading}>
                Apply filters
              </button>
              <button type="button" className="btn-secondary" onClick={() => void handleResetFilters()} disabled={!familyId || loading}>
                Reset
              </button>
              <button type="button" className="btn-secondary" onClick={() => void refreshAll()} disabled={!familyId || loading}>
                Refresh
              </button>
              <button type="button" className="btn-secondary" onClick={() => void purgeFiltered(false)} disabled={!familyId || saving}>
                Purge filtered
              </button>
              <button type="button" className="btn-danger" onClick={() => void purgeFiltered(true)} disabled={!familyId || saving}>
                Purge all
              </button>
            </div>
          </form>
        </section>

        <section className="viewer-panel highlight-panel">
          <div className="panel-heading">
            <div>
              <h2>Question Snapshot</h2>
              <p>A quick read on the current queue after the active filters were applied.</p>
            </div>
          </div>

          <div className="highlight-grid">
            <article className="highlight-card">
              <span>Visible questions</span>
              <strong>{questions.length}</strong>
              <p>Rows currently loaded into the management table.</p>
            </article>
            <article className="highlight-card">
              <span>Needs attention</span>
              <strong>{pendingCount}</strong>
              <p>Still pending, asked, or only partially answered.</p>
            </article>
            <article className="highlight-card">
              <span>Critical urgency</span>
              <strong>{criticalCount}</strong>
              <p>Items tagged as critical in the visible result set.</p>
            </article>
            <article className="highlight-card">
              <span>Due within 24h</span>
              <strong>{dueSoonCount}</strong>
              <p>Questions likely to need a response soon.</p>
            </article>
          </div>
        </section>

        {error ? <section className="banner banner-error">{error}</section> : null}

        <section className="viewer-panel table-panel">
          <div className="panel-heading">
            <div>
              <h2>Questions Table</h2>
              <p>Rows behave like the event viewer: sort columns, expand for structured data, and open a record in the detail editor.</p>
            </div>
            <div className="table-toolbar">
              <span className="hint-chip">{loading ? "Loading latest queue..." : `${questions.length} rows loaded`}</span>
              <span className="hint-chip">{answeredCount} with saved answers</span>
            </div>
          </div>

          <div className="table-wrap">
            <table className="event-table question-table">
              <thead>
                <tr>
                  <th>
                    <button type="button" className="sort-button" onClick={() => handleSort("updated_at")}>
                      Updated <span>{sortGlyph(sort, "updated_at")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => handleSort("topic")}>
                      Topic <span>{sortGlyph(sort, "topic")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => handleSort("domain")}>
                      Domain <span>{sortGlyph(sort, "domain")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => handleSort("urgency")}>
                      Urgency <span>{sortGlyph(sort, "urgency")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => handleSort("status")}>
                      Status <span>{sortGlyph(sort, "status")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => handleSort("due_at")}>
                      Due <span>{sortGlyph(sort, "due_at")}</span>
                    </button>
                  </th>
                  <th>
                    <button type="button" className="sort-button" onClick={() => handleSort("source_agent")}>
                      Source <span>{sortGlyph(sort, "source_agent")}</span>
                    </button>
                  </th>
                  <th className="raw-column">Details</th>
                </tr>
              </thead>

              <tbody>
                {sortedQuestions.map((question) => {
                  const isExpanded = expandedQuestionIds.includes(question.id);
                  const isSelected = selectedId === question.id;

                  return (
                    <Fragment key={question.id}>
                      <tr className={`table-row ${isExpanded ? "is-expanded" : ""} ${isSelected ? "is-selected" : ""}`}>
                        <td>
                          <div className="cell-stack">
                            <span className="cell-primary mono">{formatDateTime(question.updated_at)}</span>
                            <span className="cell-secondary">Created {formatDateTime(question.created_at)}</span>
                          </div>
                        </td>
                        <td>
                          <button type="button" className="row-link" onClick={() => setSelectedId(question.id)}>
                            <span className="cell-primary">{question.topic}</span>
                            <span className="cell-secondary">{question.prompt}</span>
                          </button>
                        </td>
                        <td>
                          <div className="cell-stack">
                            <span className="cell-primary">{question.domain || "—"}</span>
                            <span className="cell-secondary">{question.category || "Uncategorized"}</span>
                          </div>
                        </td>
                        <td>
                          <span className={`tag-pill ${toneClass(question.urgency)}`}>{question.urgency}</span>
                        </td>
                        <td>
                          <span className={`tag-pill ${toneClass(question.status)}`}>{question.status}</span>
                        </td>
                        <td>
                          <div className="cell-stack">
                            <span className="cell-primary">{formatDateTime(question.due_at)}</span>
                            <span className="cell-secondary">Asked {question.asked_count} times</span>
                          </div>
                        </td>
                        <td>
                          <div className="cell-stack">
                            <span className="cell-primary mono">{question.source_agent || "—"}</span>
                            <span className="cell-secondary">{question.last_delivery_channel || "No delivery channel"}</span>
                          </div>
                        </td>
                        <td className="raw-column">
                          <div className="raw-actions">
                            <button type="button" className="expand-button" onClick={() => setSelectedId(question.id)}>
                              Open
                            </button>
                            <button type="button" className="expand-button" onClick={() => toggleExpanded(question.id)}>
                              {isExpanded ? "Hide" : "Expand"}
                            </button>
                          </div>
                        </td>
                      </tr>

                      {isExpanded ? (
                        <tr className="raw-row">
                          <td colSpan={8}>
                            <div className="raw-panel">
                              <div className="raw-topline">
                                <div>
                                  <span className="raw-label">Question Snapshot</span>
                                  <strong>{question.summary || question.topic}</strong>
                                </div>
                                <div className="raw-metadata">
                                  <span className="raw-meta-chip">ID {question.id}</span>
                                  <span className="raw-meta-chip">Topic type {question.topic_type || "—"}</span>
                                  <span className="raw-meta-chip">Delivery {question.last_delivery_agent || "—"}</span>
                                </div>
                              </div>
                              <div className="raw-grid">
                                <div>
                                  <span className="raw-label">Summary</span>
                                  <p className="raw-copy">{question.summary || "No summary available."}</p>
                                </div>
                                <div>
                                  <span className="raw-label">Answer state</span>
                                  <p className="raw-copy">{question.answer_sufficiency_state || "Unknown"}</p>
                                </div>
                              </div>
                              <div className="raw-json-grid">
                                <div>
                                  <span className="raw-label">Context</span>
                                  <pre>{JSON.stringify(question.context, null, 2)}</pre>
                                </div>
                                <div>
                                  <span className="raw-label">Artifact refs</span>
                                  <pre>{JSON.stringify(question.artifact_refs, null, 2)}</pre>
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>

            {!loading && questions.length === 0 ? (
              <div className="empty-card">
                <h3>No matching questions</h3>
                <p>Try widening the filters, including inactive records, or switching to a different family workspace.</p>
              </div>
            ) : null}
          </div>
        </section>

        <section className="viewer-panel detail-layout">
          <div className="detail-card">
            <div className="panel-heading">
              <div>
                <h2>Question Details</h2>
                <p>Inspect the selected item, review delivery state, and answer inline without leaving the queue.</p>
              </div>
              <div className="hint-chip">{selectedQuestion ? selectedQuestion.source_agent : "Select a question row"}</div>
            </div>

            {selectedQuestion ? (
              <>
                <div className="detail-hero">
                  <div>
                    <span className="eyebrow">Selected Question</span>
                    <h3>{selectedQuestion.topic}</h3>
                    <p>{selectedQuestion.summary}</p>
                  </div>
                  <div className="tag-list">
                    <span className={`tag-pill ${toneClass(selectedQuestion.urgency)}`}>{selectedQuestion.urgency}</span>
                    <span className={`tag-pill ${toneClass(selectedQuestion.status)}`}>{selectedQuestion.status}</span>
                    <span className="tag-pill">{selectedQuestion.category || "Uncategorized"}</span>
                  </div>
                </div>

                <div className="context-facts detail-facts">
                  <article className="fact-card">
                    <span>Prompt</span>
                    <strong>{selectedQuestion.prompt}</strong>
                  </article>
                  <article className="fact-card">
                    <span>Delivery</span>
                    <strong>
                      {selectedQuestion.last_delivery_agent ?? "—"} / {selectedQuestion.last_delivery_channel ?? "—"}
                    </strong>
                  </article>
                  <article className="fact-card">
                    <span>Due</span>
                    <strong>{formatDateTime(selectedQuestion.due_at)}</strong>
                  </article>
                  <article className="fact-card">
                    <span>Expires</span>
                    <strong>{formatDateTime(selectedQuestion.expires_at)}</strong>
                  </article>
                  <article className="fact-card">
                    <span>Asked count</span>
                    <strong>{selectedQuestion.asked_count}</strong>
                  </article>
                  <article className="fact-card">
                    <span>Answered at</span>
                    <strong>{formatDateTime(selectedQuestion.answered_at)}</strong>
                  </article>
                </div>

                <label className="answer-field">
                  <span className="raw-label">Answer Draft</span>
                  <textarea
                    rows={6}
                    value={answerDraft}
                    onChange={(event) => setAnswerDraft(event.target.value)}
                    placeholder="Type an answer, clarification, or summary here."
                  />
                </label>

                <div className="action-row">
                  <button type="button" className="btn-primary" onClick={() => void submitAnswer("resolved")} disabled={saving || !answerDraft.trim()}>
                    Answer & resolve
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => void submitAnswer("answered_partial")}
                    disabled={saving || !answerDraft.trim()}
                  >
                    Save partial answer
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => void resolveSelected("dismissed")} disabled={saving}>
                    Dismiss
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => void resolveSelected("expired")} disabled={saving}>
                    Expire
                  </button>
                  <button type="button" className="btn-danger" onClick={() => void deleteSelected()} disabled={saving}>
                    Delete
                  </button>
                </div>
              </>
            ) : (
              <div className="empty-card">
                <h3>No selection yet</h3>
                <p>Pick a row from the questions table to review its prompt, context, and resolution workflow.</p>
              </div>
            )}
          </div>

          <div className="detail-card">
            <div className="panel-heading">
              <div>
                <h2>History</h2>
                <p>Delivery attempts and event history for the currently selected question.</p>
              </div>
            </div>

            {selectedQuestion ? (
              <div className="history-columns">
                <div className="history-section">
                  <span className="raw-label">Events</span>
                  {(history?.events ?? []).length ? (
                    (history?.events ?? []).map((event: QuestionEvent) => (
                      <article key={event.id} className="history-card">
                        <strong>{event.event_type}</strong>
                        <span>{formatDateTime(event.created_at)}</span>
                        <p>{event.actor}</p>
                      </article>
                    ))
                  ) : (
                    <div className="empty-inline">No events recorded yet.</div>
                  )}
                </div>

                <div className="history-section">
                  <span className="raw-label">Delivery attempts</span>
                  {(history?.attempts ?? []).length ? (
                    (history?.attempts ?? []).map((attempt: QuestionAttempt) => (
                      <article key={attempt.id} className="history-card">
                        <strong>{attempt.agent_id}</strong>
                        <span>
                          {attempt.channel} • {attempt.outcome}
                        </span>
                        <p>
                          Sent {formatDateTime(attempt.sent_at)}
                          {attempt.responded_at ? ` • Responded ${formatDateTime(attempt.responded_at)}` : ""}
                        </p>
                      </article>
                    ))
                  ) : (
                    <div className="empty-inline">No delivery attempts recorded yet.</div>
                  )}
                </div>
              </div>
            ) : (
              <div className="empty-card">
                <h3>History follows selection</h3>
                <p>The timeline panel will populate once a question is selected from the table above.</p>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
