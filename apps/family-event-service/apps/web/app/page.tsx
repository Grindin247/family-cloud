"use client";

import { FormEvent, Fragment, useEffect, useId, useRef, useState } from "react";
import {
  api,
  EventFilterOptionsResponse,
  EventMemberScope,
  EventSearchFilters,
  EventSearchResponse,
  EventViewerContextResponse,
  EventViewerMeResponse,
  FamilyEvent,
  ViewerMembership,
} from "../lib/api";

type FilterDraft = {
  member_scope: EventMemberScope;
  person_id: string;
  q: string;
  domain: string;
  event_type: string;
  tag: string;
  actor_id: string;
  subject_id: string;
  start: string;
  end: string;
  limit: number;
  offset: number;
};

type SortKey = "occurred_at" | "domain" | "event_type" | "actor" | "subject" | "tags";
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

const EMPTY_RESULTS: EventSearchResponse = {
  items: [],
  total: 0,
  limit: 100,
  offset: 0,
};

const DEFAULT_SORT: SortState = {
  key: "occurred_at",
  direction: "desc",
};

const EMPTY_FILTER_OPTIONS: EventFilterOptionsResponse = {
  domains: [],
  event_types: [],
  tags: [],
  actor_ids: [],
  subject_ids: [],
};

function formatDateTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function emptyDraft(scope: EventMemberScope, personId: string): FilterDraft {
  return {
    member_scope: scope,
    person_id: personId,
    q: "",
    domain: "",
    event_type: "",
    tag: "",
    actor_id: "",
    subject_id: "",
    start: "",
    end: "",
    limit: 100,
    offset: 0,
  };
}

function normalizeFilterDate(value: string): string | undefined {
  if (!value) return undefined;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return undefined;
  return parsed.toISOString();
}

function buildSearchPayload(familyId: number, filters: FilterDraft): EventSearchFilters {
  return {
    family_id: familyId,
    member_scope: filters.member_scope,
    person_id: filters.member_scope === "person" ? filters.person_id : undefined,
    q: filters.q || undefined,
    domain: filters.domain || undefined,
    event_type: filters.event_type || undefined,
    tag: filters.tag || undefined,
    actor_id: filters.actor_id || undefined,
    subject_id: filters.subject_id || undefined,
    start: normalizeFilterDate(filters.start),
    end: normalizeFilterDate(filters.end),
    limit: filters.limit,
    offset: filters.offset,
  };
}

function buildFilterOptionPayload(familyId: number, filters: FilterDraft): EventSearchFilters {
  return {
    family_id: familyId,
    member_scope: filters.member_scope,
    person_id: filters.member_scope === "person" ? filters.person_id : undefined,
    q: filters.q || undefined,
    domain: filters.domain || undefined,
    event_type: filters.event_type || undefined,
    tag: filters.tag || undefined,
    actor_id: filters.actor_id || undefined,
    subject_id: filters.subject_id || undefined,
    start: normalizeFilterDate(filters.start),
    end: normalizeFilterDate(filters.end),
  };
}

function eventSummary(event: FamilyEvent): string {
  const payload = event.payload || {};
  const title = typeof payload.title === "string" ? payload.title : null;
  const name = typeof payload.name === "string" ? payload.name : null;
  const path = typeof payload.path === "string" ? payload.path : null;
  return title || name || path || event.subject_id;
}

function eventActorLabel(event: FamilyEvent): string {
  return event.actor_id || event.actor_person_id || event.actor_type || "system";
}

function eventActorMeta(event: FamilyEvent): string {
  if (event.actor_person_id && event.actor_person_id !== event.actor_id) return event.actor_person_id;
  return event.actor_type;
}

function eventSubjectMeta(event: FamilyEvent): string {
  const summary = eventSummary(event);
  if (summary !== event.subject_id) return event.subject_id;
  return event.subject_type;
}

function scopeLabel(scope: EventMemberScope): string {
  if (scope === "all") return "All members";
  if (scope === "person") return "Specific member";
  return "Mine";
}

function roleTone(role: string | undefined): string {
  if (role === "admin") return "tone-fire";
  if (role === "viewer") return "tone-ash";
  return "tone-leaf";
}

function sortValue(event: FamilyEvent, key: SortKey): number | string {
  switch (key) {
    case "occurred_at":
      return Date.parse(event.occurred_at) || 0;
    case "domain":
      return event.domain;
    case "event_type":
      return event.event_type;
    case "actor":
      return eventActorLabel(event);
    case "subject":
      return eventSummary(event);
    case "tags":
      return event.tags.join(", ");
  }
}

function sortEvents(items: FamilyEvent[], sort: SortState): FamilyEvent[] {
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
      comparison = collator.compare(left.event_id, right.event_id);
    }

    return comparison * direction;
  });
}

function sortLabel(sort: SortState): string {
  const labelMap: Record<SortKey, string> = {
    occurred_at: "Occurred",
    domain: "Domain",
    event_type: "Event type",
    actor: "Actor",
    subject: "Subject",
    tags: "Tags",
  };
  return `${labelMap[sort.key]} ${sort.direction === "asc" ? "ascending" : "descending"}`;
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
              if (!isOpen) {
                openMenu();
              }
            }}
            onFocus={() => {
              if (!isOpen) {
                openMenu();
              }
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

export default function EventsPage() {
  const [me, setMe] = useState<EventViewerMeResponse | null>(null);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [context, setContext] = useState<EventViewerContextResponse | null>(null);
  const [draft, setDraft] = useState<FilterDraft>(emptyDraft("mine", ""));
  const [applied, setApplied] = useState<FilterDraft>(emptyDraft("mine", ""));
  const [results, setResults] = useState<EventSearchResponse>(EMPTY_RESULTS);
  const [bootLoading, setBootLoading] = useState(true);
  const [searchLoading, setSearchLoading] = useState(false);
  const [pageError, setPageError] = useState("");
  const [searchError, setSearchError] = useState("");
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [expandedEventIds, setExpandedEventIds] = useState<string[]>([]);
  const [filterOptions, setFilterOptions] = useState<EventFilterOptionsResponse>(EMPTY_FILTER_OPTIONS);
  const [filterOptionsLoading, setFilterOptionsLoading] = useState(false);

  async function runSearch(nextFamilyId: number, nextFilters: FilterDraft) {
    setSearchLoading(true);
    setSearchError("");
    setExpandedEventIds([]);
    try {
      const data = await api.searchEvents(buildSearchPayload(nextFamilyId, nextFilters));
      setResults(data);
    } catch (error) {
      setResults(EMPTY_RESULTS);
      setSearchError(error instanceof Error ? error.message : "Could not load events.");
    } finally {
      setSearchLoading(false);
    }
  }

  async function bootstrapFamily(nextFamilyId: number) {
    setPageError("");
    setSearchError("");
    setContext(null);
    setResults(EMPTY_RESULTS);
    setExpandedEventIds([]);
    setFilterOptions(EMPTY_FILTER_OPTIONS);
    try {
      const viewerContext = await api.getViewerContext(nextFamilyId);
      const defaultScope: EventMemberScope = viewerContext.is_family_admin ? "all" : "mine";
      const defaults = emptyDraft(defaultScope, viewerContext.person_id);
      setContext(viewerContext);
      setDraft(defaults);
      setApplied(defaults);
      await runSearch(nextFamilyId, defaults);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Could not load family context.");
    }
  }

  useEffect(() => {
    void (async () => {
      setBootLoading(true);
      setPageError("");
      try {
        const meResponse = await api.getMe();
        setMe(meResponse);
        const firstFamilyId = meResponse.memberships[0]?.family_id ?? null;
        setFamilyId(firstFamilyId);
        if (firstFamilyId !== null) {
          await bootstrapFamily(firstFamilyId);
        } else {
          setPageError("No families are linked to this account yet.");
        }
      } catch (error) {
        setPageError(error instanceof Error ? error.message : "Could not load your event viewer session.");
      } finally {
        setBootLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (familyId === null || context === null) return;
    if (draft.member_scope === "person" && !draft.person_id) {
      setFilterOptions(EMPTY_FILTER_OPTIONS);
      setFilterOptionsLoading(false);
      return;
    }

    let cancelled = false;
    const timeoutId = window.setTimeout(() => {
      void (async () => {
        setFilterOptionsLoading(true);
        try {
          const nextOptions = await api.getEventFilterOptions(buildFilterOptionPayload(familyId, draft));
          if (!cancelled) {
            setFilterOptions(nextOptions);
          }
        } catch {
          if (!cancelled) {
            setFilterOptions(EMPTY_FILTER_OPTIONS);
          }
        } finally {
          if (!cancelled) {
            setFilterOptionsLoading(false);
          }
        }
      })();
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [context, draft.actor_id, draft.domain, draft.end, draft.event_type, draft.member_scope, draft.person_id, draft.q, draft.start, draft.subject_id, draft.tag, familyId]);

  async function handleFamilyChange(nextFamilyId: number) {
    setFamilyId(nextFamilyId);
    await bootstrapFamily(nextFamilyId);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (familyId === null) return;
    const nextFilters = { ...draft, offset: 0 };
    setApplied(nextFilters);
    await runSearch(familyId, nextFilters);
  }

  async function handleReset() {
    if (familyId === null || context === null) return;
    const defaults = emptyDraft(context.is_family_admin ? "all" : "mine", context.person_id);
    setDraft(defaults);
    setApplied(defaults);
    setSort(DEFAULT_SORT);
    await runSearch(familyId, defaults);
  }

  async function paginate(direction: -1 | 1) {
    if (familyId === null) return;
    const nextOffset = Math.max(0, applied.offset + direction * applied.limit);
    const nextFilters = { ...applied, offset: nextOffset };
    setApplied(nextFilters);
    await runSearch(familyId, nextFilters);
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
            direction: key === "occurred_at" ? "desc" : "asc",
          }
    );
  }

  function toggleExpanded(eventId: string) {
    setExpandedEventIds((current) => (current.includes(eventId) ? current.filter((id) => id !== eventId) : [...current, eventId]));
  }

  const activeMembership: ViewerMembership | undefined = me?.memberships.find((item) => item.family_id === familyId);
  const activePerson = context?.persons.find((person) => person.person_id === context?.person_id);
  const focusedPerson =
    applied.member_scope === "person" ? context?.persons.find((person) => person.person_id === applied.person_id) : activePerson;
  const canPageBackward = applied.offset > 0;
  const canPageForward = applied.offset + results.items.length < results.total;
  const showingFrom = results.total === 0 ? 0 : applied.offset + 1;
  const showingTo = results.total === 0 ? 0 : applied.offset + results.items.length;
  const sortedItems = sortEvents(results.items, sort);

  return (
    <main className="viewer-shell">
      <div className="viewer-orb viewer-orb-left" aria-hidden="true" />
      <div className="viewer-orb viewer-orb-right" aria-hidden="true" />
      <div className="viewer-orb viewer-orb-bottom" aria-hidden="true" />

      <div className="viewer-stack">
        <section className="viewer-panel viewer-header">
          <div className="viewer-brand">
            <span className="eyebrow">Family Event Service</span>
            <h1>Event Viewer</h1>
            <p>
              Search canonical family events with wildcard matching, sortable columns, and an expandable raw payload view that
              feels at home beside the portal and decision tools.
            </p>
          </div>

          <aside className="viewer-user">
            <div className="panel-heading panel-heading-tight">
              <div>
                <h2>User Context</h2>
                <p>Identity and family scope for the current search session.</p>
              </div>
            </div>

            <div className="context-email">{me?.email ?? "Waiting for sign-in"}</div>

            <div className="chip-row">
              <span className="status-chip">{bootLoading ? "Loading" : me?.authenticated ? "Signed in" : "Signed out"}</span>
              {activeMembership ? <span className={`status-chip ${roleTone(activeMembership.role)}`}>{activeMembership.role}</span> : null}
            </div>

            <div className="context-facts">
              <article className="fact-card">
                <span>Family</span>
                <strong>{activeMembership?.family_name ?? "Not selected"}</strong>
              </article>
              <article className="fact-card">
                <span>Current person</span>
                <strong>{activePerson?.display_name ?? context?.person_id ?? "Resolving"}</strong>
              </article>
              <article className="fact-card">
                <span>Access</span>
                <strong>{context?.is_family_admin ? "Admin visibility" : "Own events only"}</strong>
              </article>
              <article className="fact-card">
                <span>Scope</span>
                <strong>{scopeLabel(applied.member_scope)}</strong>
              </article>
            </div>
          </aside>
        </section>

        <section className="viewer-panel filter-panel">
          <div className="panel-heading">
            <div>
              <h2>Filter Options</h2>
              <p>Search is case-insensitive. If you omit `*`, the viewer treats the query as a contains match.</p>
            </div>
            <div className="hint-chip">{filterOptionsLoading ? "Refreshing available choices..." : "Known values are selectable in combo fields"}</div>
          </div>

          <form className="filter-form" onSubmit={handleSubmit}>
            <label>
              Family
              <select
                value={familyId ?? ""}
                onChange={(event) => void handleFamilyChange(Number(event.target.value))}
                disabled={bootLoading || !me?.memberships.length}
              >
                {me?.memberships.map((membership) => (
                  <option key={membership.family_id} value={membership.family_id}>
                    {membership.family_name}
                  </option>
                ))}
              </select>
            </label>

            <label className="field-span-2">
              Wildcard search
              <input
                autoComplete="off"
                value={draft.q}
                onChange={(event) => setDraft({ ...draft, q: event.target.value })}
                placeholder="Try note.created, *plumber*, /Notes/"
              />
            </label>

            <label>
              Member scope
              <select
                value={draft.member_scope}
                onChange={(event) => {
                  const nextScope = event.target.value as EventMemberScope;
                  setDraft({
                    ...draft,
                    member_scope: nextScope,
                    person_id: nextScope === "person" ? draft.person_id || context?.person_id || "" : draft.person_id,
                  });
                }}
                disabled={!context}
              >
                <option value="mine">Mine</option>
                {context?.is_family_admin ? <option value="all">All members</option> : null}
                {context?.is_family_admin ? <option value="person">Specific member</option> : null}
              </select>
            </label>

            <label>
              Member
              <select
                value={draft.person_id}
                onChange={(event) => setDraft({ ...draft, person_id: event.target.value })}
                disabled={draft.member_scope !== "person"}
              >
                {(context?.persons || []).map((person) => (
                  <option key={person.person_id} value={person.person_id}>
                    {person.display_name}
                  </option>
                ))}
              </select>
            </label>

            <ComboField
              label="Domain"
              onChange={(value) => setDraft({ ...draft, domain: value })}
              options={filterOptions.domains}
              placeholder="task"
              value={draft.domain}
            />

            <ComboField
              label="Event type"
              onChange={(value) => setDraft({ ...draft, event_type: value })}
              options={filterOptions.event_types}
              placeholder="task.completed"
              value={draft.event_type}
            />

            <ComboField
              label="Tag"
              onChange={(value) => setDraft({ ...draft, tag: value })}
              options={filterOptions.tags}
              placeholder="household"
              value={draft.tag}
            />

            <ComboField
              label="Actor ID"
              onChange={(value) => setDraft({ ...draft, actor_id: value })}
              options={filterOptions.actor_ids}
              placeholder="admin@example.com"
              value={draft.actor_id}
            />

            <ComboField
              className="field-span-2"
              label="Subject ID"
              onChange={(value) => setDraft({ ...draft, subject_id: value })}
              options={filterOptions.subject_ids}
              placeholder="/Notes/church.md"
              value={draft.subject_id}
            />

            <label>
              Start
              <input type="datetime-local" value={draft.start} onChange={(event) => setDraft({ ...draft, start: event.target.value })} />
            </label>

            <label>
              End
              <input type="datetime-local" value={draft.end} onChange={(event) => setDraft({ ...draft, end: event.target.value })} />
            </label>

            <label>
              Page size
              <select value={draft.limit} onChange={(event) => setDraft({ ...draft, limit: Number(event.target.value) })}>
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={250}>250</option>
              </select>
            </label>

            <div className="action-row field-span-full">
              <button className="btn-primary" type="submit" disabled={familyId === null || searchLoading}>
                {searchLoading ? "Searching..." : "Search"}
              </button>
              <button className="btn-secondary" type="button" disabled={familyId === null || searchLoading} onClick={() => void handleReset()}>
                Reset
              </button>
            </div>
          </form>
        </section>

        <section className="viewer-panel highlight-panel">
          <div className="panel-heading panel-heading-tight">
            <div>
              <h2>Result Highlights</h2>
              <p>Fast context before you drill into the event table.</p>
            </div>
          </div>

          <div className="highlight-grid">
            <article className="highlight-card">
              <span>Total matches</span>
              <strong>{results.total}</strong>
              <p>All results for the currently applied search window.</p>
            </article>
            <article className="highlight-card">
              <span>Showing</span>
              <strong>
                {showingFrom}-{showingTo}
              </strong>
              <p>Current page slice across the family event stream.</p>
            </article>
            <article className="highlight-card">
              <span>Scope</span>
              <strong>{scopeLabel(applied.member_scope)}</strong>
              <p>{focusedPerson ? `Focused on ${focusedPerson.display_name}.` : "Using the active family visibility rules."}</p>
            </article>
            <article className="highlight-card">
              <span>Sort</span>
              <strong>{sortLabel(sort)}</strong>
              <p>{applied.q ? `Query: ${applied.q}` : "No wildcard query applied."}</p>
            </article>
          </div>
        </section>

        {pageError ? <section className="banner banner-error">{pageError}</section> : null}
        {searchError ? <section className="banner banner-warn">{searchError}</section> : null}

        <section className="viewer-panel table-panel">
          <div className="panel-heading">
            <div>
              <h2>Event Table</h2>
              <p>Click any sortable column to reorder the current page. Expand a row when you want the untouched JSON.</p>
            </div>

            <div className="table-toolbar">
              {searchLoading ? <span className="status-chip">Refreshing</span> : null}
              <div className="pagination">
                <button className="btn-secondary" type="button" onClick={() => void paginate(-1)} disabled={!canPageBackward || searchLoading}>
                  Previous
                </button>
                <button className="btn-secondary" type="button" onClick={() => void paginate(1)} disabled={!canPageForward || searchLoading}>
                  Next
                </button>
              </div>
            </div>
          </div>

          {results.items.length === 0 && !searchLoading && !pageError ? (
            <article className="empty-card">
              <h3>No matching events</h3>
              <p>Try widening the date range, removing a member filter, or using a broader wildcard like `*task*`.</p>
            </article>
          ) : (
            <div className="table-wrap" aria-live="polite">
              <table className="event-table">
                <thead>
                  <tr>
                    <th scope="col">
                      <button className="sort-button" type="button" onClick={() => handleSort("occurred_at")}>
                        Occurred <span aria-hidden="true">{sortGlyph(sort, "occurred_at")}</span>
                      </button>
                    </th>
                    <th scope="col">
                      <button className="sort-button" type="button" onClick={() => handleSort("domain")}>
                        Domain <span aria-hidden="true">{sortGlyph(sort, "domain")}</span>
                      </button>
                    </th>
                    <th scope="col">
                      <button className="sort-button" type="button" onClick={() => handleSort("event_type")}>
                        Event type <span aria-hidden="true">{sortGlyph(sort, "event_type")}</span>
                      </button>
                    </th>
                    <th scope="col">
                      <button className="sort-button" type="button" onClick={() => handleSort("actor")}>
                        Actor <span aria-hidden="true">{sortGlyph(sort, "actor")}</span>
                      </button>
                    </th>
                    <th scope="col">
                      <button className="sort-button" type="button" onClick={() => handleSort("subject")}>
                        Subject <span aria-hidden="true">{sortGlyph(sort, "subject")}</span>
                      </button>
                    </th>
                    <th scope="col">
                      <button className="sort-button" type="button" onClick={() => handleSort("tags")}>
                        Tags <span aria-hidden="true">{sortGlyph(sort, "tags")}</span>
                      </button>
                    </th>
                    <th scope="col" className="raw-column">
                      Raw view
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedItems.map((event) => {
                    const expanded = expandedEventIds.includes(event.event_id);
                    return (
                      <Fragment key={event.event_id}>
                        <tr className={expanded ? "table-row is-expanded" : "table-row"}>
                          <td>
                            <div className="cell-stack">
                              <span className="cell-primary mono">{formatDateTime(event.occurred_at)}</span>
                              <span className="cell-secondary">Recorded {formatDateTime(event.recorded_at)}</span>
                            </div>
                          </td>
                          <td>
                            <div className="cell-stack">
                              <span className="cell-primary">{event.domain}</span>
                              <span className="cell-secondary">v{event.event_version}</span>
                            </div>
                          </td>
                          <td>
                            <div className="cell-stack">
                              <span className="cell-primary">{event.event_type}</span>
                              <span className="cell-secondary">{event.correlation_id ? `corr ${event.correlation_id}` : "Standalone event"}</span>
                            </div>
                          </td>
                          <td>
                            <div className="cell-stack">
                              <span className="cell-primary">{eventActorLabel(event)}</span>
                              <span className="cell-secondary">{eventActorMeta(event)}</span>
                            </div>
                          </td>
                          <td>
                            <div className="cell-stack">
                              <span className="cell-primary">{eventSummary(event)}</span>
                              <span className="cell-secondary">{eventSubjectMeta(event)}</span>
                            </div>
                          </td>
                          <td>
                            <div className="tag-list">
                              {event.tags.length ? event.tags.map((tag) => <span className="tag-pill" key={tag}>{tag}</span>) : <span className="tag-pill tag-pill-muted">No tags</span>}
                              <span className="tag-pill tag-pill-soft">{event.privacy_classification}</span>
                            </div>
                          </td>
                          <td className="raw-column">
                            <button
                              aria-controls={`raw-${event.event_id}`}
                              aria-expanded={expanded}
                              className="expand-button"
                              type="button"
                              onClick={() => toggleExpanded(event.event_id)}
                            >
                              {expanded ? "Hide raw" : "Show raw"}
                            </button>
                          </td>
                        </tr>

                        {expanded ? (
                          <tr className="raw-row" id={`raw-${event.event_id}`}>
                            <td colSpan={7}>
                              <div className="raw-panel">
                                <div className="raw-topline">
                                  <div>
                                    <span className="raw-label">Event ID</span>
                                    <strong className="mono">{event.event_id}</strong>
                                  </div>
                                  <div className="raw-metadata">
                                    {event.correlation_id ? <span className="raw-meta-chip">corr {event.correlation_id}</span> : null}
                                    {event.causation_id ? <span className="raw-meta-chip">cause {event.causation_id}</span> : null}
                                    <span className="raw-meta-chip">{event.export_policy}</span>
                                  </div>
                                </div>
                                <pre>{JSON.stringify(event, null, 2)}</pre>
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {searchLoading && results.items.length === 0 ? (
            <article className="empty-card">
              <h3>Searching events...</h3>
              <p>Refreshing the current result window.</p>
            </article>
          ) : null}
        </section>
      </div>
    </main>
  );
}
