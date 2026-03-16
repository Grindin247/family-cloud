"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, Family, FamilyMember } from "../../lib/api";

export default function FamiliesPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [selectedFamilyId, setSelectedFamilyId] = useState<number | null>(null);
  const [members, setMembers] = useState<FamilyMember[]>([]);
  const [familyName, setFamilyName] = useState("");
  const [memberForm, setMemberForm] = useState({ email: "", display_name: "", role: "editor" });
  const [error, setError] = useState("");

  async function loadFamilies() {
    const data = await api.listFamilies();
    setFamilies(data.items);
    const nextFamilyId = selectedFamilyId ?? data.items[0]?.id ?? null;
    setSelectedFamilyId(nextFamilyId);
    if (nextFamilyId) {
      const memberData = await api.listFamilyMembers(nextFamilyId);
      setMembers(memberData.items);
    } else {
      setMembers([]);
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        await loadFamilies();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load families");
      }
    })();
  }, []);

  useEffect(() => {
    if (!selectedFamilyId) return;
    void (async () => {
      try {
        const memberData = await api.listFamilyMembers(selectedFamilyId);
        setMembers(memberData.items);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load members");
      }
    })();
  }, [selectedFamilyId]);

  async function onCreateFamily(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createFamily({ name: familyName });
      setFamilyName("");
      await loadFamilies();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create family");
    }
  }

  async function onRenameFamily(familyId: number, name: string) {
    try {
      await api.updateFamily(familyId, { name });
      await loadFamilies();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update family");
    }
  }

  async function onCreateMember(event: FormEvent) {
    event.preventDefault();
    if (!selectedFamilyId) return;
    try {
      await api.createFamilyMember(selectedFamilyId, memberForm);
      setMemberForm({ email: "", display_name: "", role: "editor" });
      const memberData = await api.listFamilyMembers(selectedFamilyId);
      setMembers(memberData.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create member");
    }
  }

  async function onUpdateMember(memberId: number, displayName: string, role: string) {
    if (!selectedFamilyId) return;
    try {
      await api.updateFamilyMember(selectedFamilyId, memberId, { display_name: displayName, role });
      const memberData = await api.listFamilyMembers(selectedFamilyId);
      setMembers(memberData.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update member");
    }
  }

  async function onDeleteMember(memberId: number) {
    if (!selectedFamilyId) return;
    if (!window.confirm("Delete this family member?")) return;
    try {
      await api.deleteFamilyMember(selectedFamilyId, memberId);
      const memberData = await api.listFamilyMembers(selectedFamilyId);
      setMembers(memberData.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete member");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h2 className="page-title">Families</h2>
          <p className="page-sub">Manage households, member roles, and account ownership.</p>
        </div>
      </div>

      {error && <div className="card">{error}</div>}

      <div className="grid grid-2 families-grid">
        <div className="card stack">
          <h3>Create Family</h3>
          <form className="stack" onSubmit={onCreateFamily}>
            <input value={familyName} onChange={(e) => setFamilyName(e.target.value)} placeholder="e.g. Miller Household" required />
            <button className="btn-primary" type="submit">Create Family</button>
          </form>

          <h3 style={{ marginTop: 8 }}>Existing Families</h3>
          <div className="list">
            {families.map((family) => (
              <FamilyRow
                key={family.id}
                family={family}
                selected={selectedFamilyId === family.id}
                onSelect={() => setSelectedFamilyId(family.id)}
                onRename={onRenameFamily}
              />
            ))}
          </div>
        </div>

        <div className="card stack">
          <h3>Family Members</h3>
          <form className="stack" onSubmit={onCreateMember}>
            <div className="row">
              <input
                placeholder="Email"
                type="email"
                value={memberForm.email}
                onChange={(e) => setMemberForm({ ...memberForm, email: e.target.value })}
                required
              />
              <input
                placeholder="Display name"
                value={memberForm.display_name}
                onChange={(e) => setMemberForm({ ...memberForm, display_name: e.target.value })}
                required
              />
            </div>
            <div className="row">
              <select value={memberForm.role} onChange={(e) => setMemberForm({ ...memberForm, role: e.target.value })}>
                <option value="admin">admin</option>
                <option value="editor">editor</option>
                <option value="viewer">viewer</option>
              </select>
              <button className="btn-primary" type="submit" disabled={!selectedFamilyId}>Add Member</button>
            </div>
          </form>

          <div className="list">
            {members.map((member) => (
              <MemberRow key={member.id} member={member} onSave={onUpdateMember} onDelete={onDeleteMember} />
            ))}
            {members.length === 0 && <div className="item">Select or create a family to manage members.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}

function FamilyRow({
  family,
  selected,
  onSelect,
  onRename,
}: {
  family: Family;
  selected: boolean;
  onSelect: () => void;
  onRename: (familyId: number, name: string) => Promise<void>;
}) {
  const [name, setName] = useState(family.name);

  return (
    <div className="item" style={selected ? { borderColor: "#b24f2a" } : undefined}>
      <div style={{ display: "flex", gap: 8 }}>
        <input value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn-secondary" onClick={() => void onRename(family.id, name)} type="button">Save</button>
        <button className="btn-primary" onClick={onSelect} type="button">Open</button>
      </div>
    </div>
  );
}

function MemberRow({
  member,
  onSave,
  onDelete,
}: {
  member: FamilyMember;
  onSave: (memberId: number, displayName: string, role: string) => Promise<void>;
  onDelete: (memberId: number) => Promise<void> | void;
}) {
  const [displayName, setDisplayName] = useState(member.display_name);
  const [role, setRole] = useState(member.role);

  return (
    <div className="item">
      <div style={{ marginBottom: 8 }}>
        <strong>{member.email}</strong>
      </div>
      <div className="row">
        <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        <select value={role} onChange={(e) => setRole(e.target.value as FamilyMember["role"])}>
          <option value="admin">admin</option>
          <option value="editor">editor</option>
          <option value="viewer">viewer</option>
        </select>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <button className="btn-secondary" onClick={() => void onSave(member.id, displayName, role)} type="button">
          Update Member
        </button>
        <button className="btn-danger" onClick={() => void onDelete(member.id)} type="button">
          Delete Member
        </button>
      </div>
    </div>
  );
}
