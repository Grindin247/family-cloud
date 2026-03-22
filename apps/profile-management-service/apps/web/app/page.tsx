"use client";

import { useEffect, useMemo, useState } from "react";
import { api, ProfileDetail, ProfileSummary, Relationship, RelationshipType, ViewerContext, ViewerMeResponse } from "../lib/api";

const RELATIONSHIP_OPTIONS: Array<{ value: RelationshipType; label: string }> = [
  { value: "adult", label: "Adult" },
  { value: "child", label: "Child" },
  { value: "guardian", label: "Guardian" },
  { value: "dependent", label: "Dependent" },
  { value: "spouse", label: "Spouse" },
  { value: "co_parent", label: "Co-parent" },
  { value: "coach", label: "Coach" },
  { value: "tutor", label: "Tutor" },
  { value: "clinician", label: "Clinician" },
  { value: "delegated_caregiver", label: "Delegated caregiver" },
];

type RelationshipDraft = {
  relationship_id: string | null;
  source_person_id: string;
  target_person_id: string;
  relationship_type: RelationshipType;
  status: string;
  is_mutual: boolean;
  notes: string;
  metadata: string;
};

function listToText(values: string[] | undefined): string {
  return (values || []).join("\n");
}

function textToList(value: string): string[] {
  return value
    .split(/\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not reviewed yet";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function roleChips(profile: ProfileSummary): string[] {
  return [...profile.role_tags, ...(profile.role_in_family ? [profile.role_in_family] : [])];
}

function personName(context: ViewerContext | null, personId: string): string {
  return context?.persons.find((person) => person.person_id === personId)?.display_name || personId;
}

function safeJsonInput(value: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) return {};
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function emptyProfile(): RelationshipDraft {
  return {
    relationship_id: null,
    source_person_id: "",
    target_person_id: "",
    relationship_type: "guardian",
    status: "active",
    is_mutual: false,
    notes: "",
    metadata: "",
  };
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </label>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="toggle-row">
      <span>{label}</span>
      <input checked={checked} type="checkbox" onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}

export default function Page() {
  const [me, setMe] = useState<ViewerMeResponse | null>(null);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [context, setContext] = useState<ViewerContext | null>(null);
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [selectedPersonId, setSelectedPersonId] = useState<string>("");
  const [draft, setDraft] = useState<ProfileDetail | null>(null);
  const [relationshipDraft, setRelationshipDraft] = useState<RelationshipDraft>(emptyProfile());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingRelationship, setSavingRelationship] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const summary = useMemo(() => {
    const adults = profiles.filter((profile) => profile.role_tags.includes("adult")).length;
    const children = profiles.filter((profile) => profile.role_tags.includes("child")).length;
    const accessibilityProfiles = profiles.filter((profile) => {
      const detail = draft && draft.person_id === profile.person_id ? draft : null;
      return Boolean(detail?.preferences.accessibility_needs.notes || detail?.preferences.accessibility_needs.accommodations.length);
    }).length;
    const relationships = profiles.reduce((count, profile) => count + profile.relationship_count, 0);
    return { adults, children, accessibilityProfiles, relationships };
  }, [draft, profiles]);

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        setError(null);
        const nextMe = await api.getMe();
        setMe(nextMe);
        const firstMembership = nextMe.memberships[0];
        if (!firstMembership) {
          setFamilyId(null);
          setContext(null);
          setProfiles([]);
          setDraft(null);
          return;
        }
        setFamilyId(firstMembership.family_id);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "Could not load the profile workspace.");
      } finally {
        setLoading(false);
      }
    }

    load();
  }, []);

  useEffect(() => {
    if (!familyId) return;
    void refreshWorkspace(familyId, selectedPersonId);
  }, [familyId]);

  useEffect(() => {
    if (!familyId || !selectedPersonId || !context?.profile_enabled) return;
    void loadProfileDetail(familyId, selectedPersonId);
  }, [familyId, selectedPersonId, context?.profile_enabled]);

  async function refreshWorkspace(nextFamilyId: number, preferredPersonId?: string) {
    try {
      setLoading(true);
      setError(null);
      const nextContext = await api.getViewerContext(nextFamilyId);
      setContext(nextContext);
      if (!nextContext.profile_enabled) {
        setProfiles([]);
        setSelectedPersonId(nextContext.person_id);
        setDraft(null);
        return;
      }
      const nextProfiles = (await api.listProfiles(nextFamilyId)).items;
      setProfiles(nextProfiles);
      const nextSelection = preferredPersonId && nextProfiles.some((item) => item.person_id === preferredPersonId) ? preferredPersonId : nextProfiles[0]?.person_id || nextContext.person_id;
      setSelectedPersonId(nextSelection || "");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not refresh profile data.");
    } finally {
      setLoading(false);
    }
  }

  async function loadProfileDetail(nextFamilyId: number, personId: string) {
    try {
      setLoading(true);
      setError(null);
      const detail = await api.getProfile(nextFamilyId, personId);
      setDraft(detail);
      setRelationshipDraft((current) => ({
        ...emptyProfile(),
        source_person_id: current.relationship_id ? current.source_person_id : personId,
        target_person_id: current.relationship_id ? current.target_person_id : context?.persons.find((person) => person.person_id !== personId)?.person_id || personId,
      }));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Could not load the selected profile.");
    } finally {
      setLoading(false);
    }
  }

  async function enableProfiles() {
    if (!familyId) return;
    try {
      setEnabling(true);
      await api.updateProfileFeature(familyId, true);
      await refreshWorkspace(familyId, context?.person_id);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not enable profile management.");
    } finally {
      setEnabling(false);
    }
  }

  async function saveProfile() {
    if (!familyId || !draft) return;
    try {
      setSaving(true);
      const saved = await api.putProfile(familyId, draft.person_id, {
        account_profile: draft.account_profile,
        person_profile: draft.person_profile,
        preferences: draft.preferences,
      });
      setDraft(saved);
      await refreshWorkspace(familyId, saved.person_id);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not save profile changes.");
    } finally {
      setSaving(false);
    }
  }

  async function saveRelationship() {
    if (!familyId) return;
    try {
      setSavingRelationship(true);
      const payload = {
        source_person_id: relationshipDraft.source_person_id,
        target_person_id: relationshipDraft.target_person_id,
        relationship_type: relationshipDraft.relationship_type,
        status: relationshipDraft.status,
        is_mutual: relationshipDraft.is_mutual,
        notes: relationshipDraft.notes.trim() || null,
        metadata: safeJsonInput(relationshipDraft.metadata),
      };
      if (relationshipDraft.relationship_id) {
        await api.updateRelationship(familyId, relationshipDraft.relationship_id, payload);
      } else {
        await api.createRelationship(familyId, payload);
      }
      setRelationshipDraft({
        ...emptyProfile(),
        source_person_id: selectedPersonId,
        target_person_id: context?.persons.find((person) => person.person_id !== selectedPersonId)?.person_id || selectedPersonId,
      });
      await loadProfileDetail(familyId, selectedPersonId);
      await refreshWorkspace(familyId, selectedPersonId);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not save relationship.");
    } finally {
      setSavingRelationship(false);
    }
  }

  async function deleteRelationship(item: Relationship) {
    if (!familyId) return;
    if (!window.confirm("Remove this relationship from the graph?")) return;
    try {
      await api.deleteRelationship(familyId, item.relationship_id);
      setRelationshipDraft({
        ...emptyProfile(),
        source_person_id: selectedPersonId,
        target_person_id: context?.persons.find((person) => person.person_id !== selectedPersonId)?.person_id || selectedPersonId,
      });
      await loadProfileDetail(familyId, selectedPersonId);
      await refreshWorkspace(familyId, selectedPersonId);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Could not remove relationship.");
    }
  }

  function editRelationship(item: Relationship) {
    setRelationshipDraft({
      relationship_id: item.relationship_id,
      source_person_id: item.source_person_id,
      target_person_id: item.target_person_id,
      relationship_type: item.relationship_type,
      status: item.status,
      is_mutual: item.is_mutual,
      notes: item.notes || "",
      metadata: item.metadata && Object.keys(item.metadata).length ? JSON.stringify(item.metadata, null, 2) : "",
    });
  }

  if (loading && !me) {
    return (
      <main className="profile-shell">
        <section className="profile-stack">
          <div className="panel empty-state">Loading profile workspace...</div>
        </section>
      </main>
    );
  }

  return (
    <main className="profile-shell">
      <section className="profile-stack">
        <header className="panel hero-panel">
          <div className="eyebrow">Family Profile Studio</div>
          <div className="hero-row">
            <div>
              <h1>Account security, human preferences, and relationship context in one place.</h1>
              <p>
                Profile management stays modular from decisions and education: this space keeps MFA posture, legal consents,
                communication style, accessibility notes, dietary needs, and the living relationship graph together.
              </p>
            </div>
            <div className="hero-meta">
              <div className="status-row">
                <span className={context?.profile_enabled ? "status-chip tone-leaf" : "status-chip tone-warn"}>
                  {context?.profile_enabled ? "Profile domain enabled" : "Profile domain disabled"}
                </span>
                {draft?.updated_at ? <span className="status-chip tone-muted">Last saved {formatDate(draft.updated_at)}</span> : null}
              </div>
              <p className="helper">
                {context?.primary_email ? `Signed in as ${context.primary_email}.` : "Sign in through the family identity layer to edit profiles."}
              </p>
            </div>
          </div>
          <div className="summary-grid">
            <div className="summary-card">
              <span>People in scope</span>
              <strong>{profiles.length || context?.persons.length || 0}</strong>
            </div>
            <div className="summary-card">
              <span>Tagged adults / children</span>
              <strong>
                {summary.adults} / {summary.children}
              </strong>
            </div>
            <div className="summary-card">
              <span>Relationship edges</span>
              <strong>{summary.relationships}</strong>
            </div>
            <div className="summary-card">
              <span>Accessibility notes in focus</span>
              <strong>{summary.accessibilityProfiles}</strong>
            </div>
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        {!me?.memberships.length ? (
          <div className="panel empty-state">This account does not have any family memberships yet, so there is no profile workspace to open.</div>
        ) : (
          <section className="workspace">
            <aside className="panel sidebar">
              <div className="panel-head">
                <div>
                  <h2>People</h2>
                  <p className="muted-copy">Choose a family member to view or edit their account and preference profile.</p>
                </div>
              </div>

              <div className="family-picker">
                <SelectField
                  label="Family"
                  value={String(familyId || "")}
                  onChange={(value) => {
                    const nextFamilyId = Number(value);
                    setFamilyId(nextFamilyId);
                    setSelectedPersonId("");
                    setDraft(null);
                  }}
                >
                  {me.memberships.map((membership) => (
                    <option key={`${membership.family_id}-${membership.member_id}`} value={membership.family_id}>
                      {membership.family_name}
                    </option>
                  ))}
                </SelectField>
              </div>

              <div className="person-list">
                {(profiles.length ? profiles : context?.persons.map((person) => ({
                  person_id: person.person_id,
                  family_id: context.family_id,
                  display_name: person.display_name,
                  canonical_name: person.display_name,
                  role_in_family: person.role_in_family,
                  is_admin: person.is_admin,
                  status: person.status,
                  role_tags: [],
                  hobbies: [],
                  interests: [],
                  relationship_count: 0,
                  updated_at: null,
                })) || []
                ).map((profile) => (
                  <button
                    key={profile.person_id}
                    className={selectedPersonId === profile.person_id ? "person-card person-card-active" : "person-card"}
                    onClick={() => setSelectedPersonId(profile.person_id)}
                    type="button"
                  >
                    <strong>{profile.display_name}</strong>
                    <span>{profile.relationship_count} graph links</span>
                    <div className="pill-row">
                      {roleChips(profile).slice(0, 3).map((chip) => (
                        <span className="pill" key={`${profile.person_id}-${chip}`}>
                          {chip}
                        </span>
                      ))}
                      {profile.interests.slice(0, 2).map((interest) => (
                        <span className="pill" key={`${profile.person_id}-${interest}`}>
                          {interest}
                        </span>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
            </aside>

            <section className="panel editor-panel">
              {!context?.profile_enabled ? (
                <div className="empty-state">
                  <p>
                    This family is ready for profile management, but the domain is currently disabled. Enable it here to start tracking
                    relationship context and personal preference data.
                  </p>
                  {context?.is_family_admin ? (
                    <div className="button-row">
                      <button className="button" disabled={enabling} onClick={enableProfiles} type="button">
                        {enabling ? "Enabling..." : "Enable profile management"}
                      </button>
                    </div>
                  ) : (
                    <div className="status-row">
                      <span className="status-chip tone-muted">Ask a family admin to enable the profile domain.</span>
                    </div>
                  )}
                </div>
              ) : !draft ? (
                <div className="empty-state">Choose a person from the left to load their profile.</div>
              ) : (
                <>
                  <div className="editor-toolbar">
                    <div>
                      <h2>{draft.display_name}</h2>
                      <p className="muted-copy">
                        Canonical identity is still owned by the shared family registry. This workspace layers richer person context on top.
                      </p>
                    </div>
                    <div className="button-row">
                      <button className="button" disabled={saving} onClick={saveProfile} type="button">
                        {saving ? "Saving..." : "Save profile"}
                      </button>
                    </div>
                  </div>

                  <div className="section-grid">
                    <section className="section-card">
                      <h3>Account profile</h3>
                      <p>Track authentication posture, passkeys, recovery paths, and recorded legal consents.</p>
                      <Field
                        label="Primary login"
                        value={draft.account_profile.primary_login || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, primary_login: value || null } } : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Auth providers"
                        value={listToText(draft.account_profile.auth_providers)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, auth_providers: textToList(value) } } : current,
                          )
                        }
                        placeholder="keycloak&#10;google"
                      />
                      <TextAreaField
                        label="Auth methods"
                        value={listToText(draft.account_profile.auth_methods)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, auth_methods: textToList(value) } } : current,
                          )
                        }
                        placeholder="password&#10;magic-link"
                      />
                      <TextAreaField
                        label="Passkey labels"
                        value={listToText(draft.account_profile.passkey_labels)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, passkey_labels: textToList(value) } } : current,
                          )
                        }
                        placeholder="iPhone 16&#10;Family laptop"
                      />
                      <TextAreaField
                        label="Recovery methods"
                        value={listToText(draft.account_profile.recovery_methods)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, recovery_methods: textToList(value) } } : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Recovery contacts"
                        value={listToText(draft.account_profile.recovery_contacts)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, recovery_contacts: textToList(value) } } : current,
                          )
                        }
                      />
                      <ToggleField
                        label="MFA enabled"
                        checked={draft.account_profile.mfa_enabled}
                        onChange={(checked) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, mfa_enabled: checked } } : current,
                          )
                        }
                      />
                      <ToggleField
                        label="Passkeys enabled"
                        checked={draft.account_profile.passkeys_enabled}
                        onChange={(checked) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, passkeys_enabled: checked } } : current,
                          )
                        }
                      />
                      <Field
                        label="Last security review"
                        type="date"
                        value={draft.account_profile.last_reviewed_at ? draft.account_profile.last_reviewed_at.slice(0, 10) : ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  account_profile: {
                                    ...current.account_profile,
                                    last_reviewed_at: value ? new Date(`${value}T12:00:00`).toISOString() : null,
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Security notes"
                        value={draft.account_profile.security_notes || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, account_profile: { ...current.account_profile, security_notes: value || null } } : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Legal consents"
                        value={draft.account_profile.legal_consents.map((consent) => `${consent.consent_key}: ${consent.status}`).join("\n")}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  account_profile: {
                                    ...current.account_profile,
                                    legal_consents: textToList(value).map((item) => {
                                      const [consentKey, status] = item.split(":").map((part) => part.trim());
                                      return {
                                        consent_key: consentKey || item,
                                        status: status || "granted",
                                        granted_at: null,
                                        expires_at: null,
                                        notes: null,
                                      };
                                    }),
                                  },
                                }
                              : current,
                          )
                        }
                        placeholder="media-sharing: granted&#10;school-communication: pending"
                      />
                    </section>

                    <section className="section-card">
                      <h3>Person profile</h3>
                      <p>Capture demographics, traits, hobbies, interests, and the preference settings agents should actually honor.</p>
                      <Field
                        label="Birthdate"
                        type="date"
                        value={draft.person_profile.birthdate || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, person_profile: { ...current.person_profile, birthdate: value || null } } : current,
                          )
                        }
                      />
                      <Field
                        label="Pronouns"
                        value={draft.person_profile.pronouns || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, person_profile: { ...current.person_profile, pronouns: value || null } } : current,
                          )
                        }
                      />
                      <Field
                        label="Timezone"
                        value={draft.person_profile.timezone || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, person_profile: { ...current.person_profile, timezone: value || null } } : current,
                          )
                        }
                      />
                      <Field
                        label="Locale"
                        value={draft.person_profile.locale || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, person_profile: { ...current.person_profile, locale: value || null } } : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Languages"
                        value={listToText(draft.person_profile.languages)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, person_profile: { ...current.person_profile, languages: textToList(value) } } : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Adult / child role tags"
                        value={listToText(draft.person_profile.role_tags)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  person_profile: {
                                    ...current.person_profile,
                                    role_tags: textToList(value).filter((item): item is "adult" | "child" => item === "adult" || item === "child"),
                                  },
                                }
                              : current,
                          )
                        }
                        placeholder="adult&#10;child"
                      />
                      <TextAreaField
                        label="Traits"
                        value={listToText(draft.person_profile.traits)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, person_profile: { ...current.person_profile, traits: textToList(value) } } : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Hobbies"
                        value={listToText(draft.preferences.hobbies)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, preferences: { ...current.preferences, hobbies: textToList(value) } } : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Interests"
                        value={listToText(draft.preferences.interests)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, preferences: { ...current.preferences, interests: textToList(value) } } : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Demographic notes"
                        value={draft.person_profile.demographic_notes || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current ? { ...current, person_profile: { ...current.person_profile, demographic_notes: value || null } } : current,
                          )
                        }
                      />
                    </section>

                    <section className="section-card">
                      <h3>Preferences and supports</h3>
                      <p>Track how this person learns, eats, communicates, and stays regulated so the rest of the system can adapt.</p>
                      <TextAreaField
                        label="Learning modalities"
                        value={listToText(draft.preferences.learning_preferences.modalities)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    learning_preferences: { ...current.preferences.learning_preferences, modalities: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <Field
                        label="Learning pace"
                        value={draft.preferences.learning_preferences.pace || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    learning_preferences: { ...current.preferences.learning_preferences, pace: value || null },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Learning supports"
                        value={listToText(draft.preferences.learning_preferences.supports)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    learning_preferences: { ...current.preferences.learning_preferences, supports: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Dietary restrictions"
                        value={listToText(draft.preferences.dietary_preferences.restrictions)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    dietary_preferences: { ...current.preferences.dietary_preferences, restrictions: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Allergies"
                        value={listToText(draft.preferences.dietary_preferences.allergies)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    dietary_preferences: { ...current.preferences.dietary_preferences, allergies: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Accessibility accommodations"
                        value={listToText(draft.preferences.accessibility_needs.accommodations)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    accessibility_needs: { ...current.preferences.accessibility_needs, accommodations: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Assistive tools"
                        value={listToText(draft.preferences.accessibility_needs.assistive_tools)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    accessibility_needs: { ...current.preferences.accessibility_needs, assistive_tools: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Accessibility notes"
                        value={draft.preferences.accessibility_needs.notes || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    accessibility_needs: { ...current.preferences.accessibility_needs, notes: value || null },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                    </section>

                    <section className="section-card">
                      <h3>Motivation and communication</h3>
                      <p>Guide how reminders, encouragement, and conversations should feel so prompts land well instead of causing friction.</p>
                      <TextAreaField
                        label="Encouragements"
                        value={listToText(draft.preferences.motivation_style.encouragements)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    motivation_style: { ...current.preferences.motivation_style, encouragements: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Rewards"
                        value={listToText(draft.preferences.motivation_style.rewards)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    motivation_style: { ...current.preferences.motivation_style, rewards: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Triggers to avoid"
                        value={listToText(draft.preferences.motivation_style.triggers_to_avoid)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    motivation_style: { ...current.preferences.motivation_style, triggers_to_avoid: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Preferred channels"
                        value={listToText(draft.preferences.communication_preferences.preferred_channels)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    communication_preferences: { ...current.preferences.communication_preferences, preferred_channels: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <Field
                        label="Response style"
                        value={draft.preferences.communication_preferences.response_style || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    communication_preferences: { ...current.preferences.communication_preferences, response_style: value || null },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <Field
                        label="Cadence"
                        value={draft.preferences.communication_preferences.cadence || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    communication_preferences: { ...current.preferences.communication_preferences, cadence: value || null },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Boundaries"
                        value={listToText(draft.preferences.communication_preferences.boundaries)}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    communication_preferences: { ...current.preferences.communication_preferences, boundaries: textToList(value) },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                      <TextAreaField
                        label="Communication notes"
                        value={draft.preferences.communication_preferences.notes || ""}
                        onChange={(value) =>
                          setDraft((current) =>
                            current
                              ? {
                                  ...current,
                                  preferences: {
                                    ...current.preferences,
                                    communication_preferences: { ...current.preferences.communication_preferences, notes: value || null },
                                  },
                                }
                              : current,
                          )
                        }
                      />
                    </section>
                  </div>

                  <section className="section-card">
                    <div className="panel-head">
                      <div>
                        <h3>Relationship graph</h3>
                        <p>Model who supports whom and how, from spouses and co-parents to tutors, clinicians, and delegated caregivers.</p>
                      </div>
                    </div>

                    <div className="section-grid">
                      <SelectField
                        label="Source person"
                        value={relationshipDraft.source_person_id}
                        onChange={(value) => setRelationshipDraft((current) => ({ ...current, source_person_id: value }))}
                      >
                        {context?.persons.map((person) => (
                          <option key={`source-${person.person_id}`} value={person.person_id}>
                            {person.display_name}
                          </option>
                        ))}
                      </SelectField>
                      <SelectField
                        label="Target person"
                        value={relationshipDraft.target_person_id}
                        onChange={(value) => setRelationshipDraft((current) => ({ ...current, target_person_id: value }))}
                      >
                        {context?.persons.map((person) => (
                          <option key={`target-${person.person_id}`} value={person.person_id}>
                            {person.display_name}
                          </option>
                        ))}
                      </SelectField>
                      <SelectField
                        label="Relationship type"
                        value={relationshipDraft.relationship_type}
                        onChange={(value) => setRelationshipDraft((current) => ({ ...current, relationship_type: value as RelationshipType }))}
                      >
                        {RELATIONSHIP_OPTIONS.map((item) => (
                          <option key={item.value} value={item.value}>
                            {item.label}
                          </option>
                        ))}
                      </SelectField>
                      <Field
                        label="Status"
                        value={relationshipDraft.status}
                        onChange={(value) => setRelationshipDraft((current) => ({ ...current, status: value }))}
                      />
                      <ToggleField
                        label="Mutual edge"
                        checked={relationshipDraft.is_mutual}
                        onChange={(checked) => setRelationshipDraft((current) => ({ ...current, is_mutual: checked }))}
                      />
                      <div />
                      <TextAreaField
                        label="Notes"
                        value={relationshipDraft.notes}
                        onChange={(value) => setRelationshipDraft((current) => ({ ...current, notes: value }))}
                      />
                      <TextAreaField
                        label="Metadata JSON"
                        value={relationshipDraft.metadata}
                        onChange={(value) => setRelationshipDraft((current) => ({ ...current, metadata: value }))}
                        placeholder='{"context":"weekly piano lessons"}'
                      />
                    </div>

                    <div className="button-row">
                      <button className="button" disabled={savingRelationship} onClick={saveRelationship} type="button">
                        {savingRelationship ? "Saving relationship..." : relationshipDraft.relationship_id ? "Update relationship" : "Add relationship"}
                      </button>
                      <button
                        className="button button-secondary"
                        onClick={() =>
                          setRelationshipDraft({
                            ...emptyProfile(),
                            source_person_id: selectedPersonId,
                            target_person_id: context?.persons.find((person) => person.person_id !== selectedPersonId)?.person_id || selectedPersonId,
                          })
                        }
                        type="button"
                      >
                        Clear draft
                      </button>
                    </div>

                    {!draft.relationships.length ? (
                      <div className="empty-state">No relationship edges recorded for this person yet.</div>
                    ) : (
                      <div className="relationship-list">
                        {draft.relationships.map((item) => (
                          <article className="relationship-card" key={item.relationship_id}>
                            <div className="relationship-title">
                              <strong>
                                {personName(context, item.source_person_id)}
                                {" -> "}
                                {personName(context, item.target_person_id)}
                              </strong>
                              <div className="relationship-meta">
                                <span className="status-chip tone-sky">{item.relationship_type.replace(/_/g, " ")}</span>
                                <span className={item.status === "active" ? "status-chip tone-leaf" : "status-chip tone-muted"}>{item.status}</span>
                                {item.is_mutual ? <span className="status-chip tone-warn">mutual</span> : null}
                              </div>
                            </div>
                            {item.notes ? <p className="muted-copy">{item.notes}</p> : null}
                            <div className="button-row">
                              <button className="button button-secondary" onClick={() => editRelationship(item)} type="button">
                                Edit
                              </button>
                              <button className="button button-danger" onClick={() => deleteRelationship(item)} type="button">
                                Remove
                              </button>
                            </div>
                          </article>
                        ))}
                      </div>
                    )}
                  </section>
                </>
              )}
            </section>
          </section>
        )}
      </section>
    </main>
  );
}
