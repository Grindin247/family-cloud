"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, Decision, Family, RoadmapItem } from "../../lib/api";

export default function RoadmapPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [items, setItems] = useState<RoadmapItem[]>([]);
  const [form, setForm] = useState({
    decision_id: "",
    bucket: "This Month",
    status: "Scheduled",
    start_date: "",
    end_date: "",
    use_discretionary_budget: false,
  });
  const [error, setError] = useState("");

  async function refresh(targetFamilyId?: number | null) {
    const familyData = await api.listFamilies();
    setFamilies(familyData.items);
    const activeFamilyId = targetFamilyId ?? familyId ?? familyData.items[0]?.id ?? null;
    setFamilyId(activeFamilyId);
    if (!activeFamilyId) return;

    const [decisionData, roadmapData] = await Promise.all([
      api.listDecisions(activeFamilyId, false),
      api.listRoadmap(activeFamilyId),
    ]);
    setDecisions(decisionData.items);
    setItems(roadmapData.items);
    setForm((prev) => ({ ...prev, decision_id: String(decisionData.items[0]?.id ?? "") }));
  }

  useEffect(() => {
    void refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load roadmap"));
  }, []);

  useEffect(() => {
    if (!familyId) return;
    void refresh(familyId).catch((err) => setError(err instanceof Error ? err.message : "Failed to refresh roadmap"));
  }, [familyId]);

  const decisionTitleMap = useMemo(() => {
    return new Map(decisions.map((decision) => [decision.id, decision.title]));
  }, [decisions]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    try {
      await api.createRoadmapItem({
        decision_id: Number(form.decision_id),
        bucket: form.bucket,
        status: form.status,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        dependencies: [],
        use_discretionary_budget: form.use_discretionary_budget,
      });
      await refresh(familyId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create roadmap item");
    }
  }

  async function onStatusChange(item: RoadmapItem, status: string) {
    await api.updateRoadmapItem(item.id, { status });
    await refresh(familyId);
  }

  async function onDelete(itemId: number) {
    await api.deleteRoadmapItem(itemId);
    await refresh(familyId);
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <h2 className="page-title">Roadmap</h2>
          <p className="page-sub">Turn approved decisions into a practical timeline with clear status tracking.</p>
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
          <h3>Add to Roadmap</h3>
          <form className="stack" onSubmit={onCreate}>
            <select value={form.decision_id} onChange={(e) => setForm({ ...form, decision_id: e.target.value })} required>
              {decisions.map((decision) => (
                <option key={decision.id} value={decision.id}>{decision.title}</option>
              ))}
            </select>
            <div className="row">
              <input value={form.bucket} onChange={(e) => setForm({ ...form, bucket: e.target.value })} placeholder="Bucket (e.g. 2026-Q2)" required />
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                <option value="Scheduled">Scheduled</option>
                <option value="In-Progress">In-Progress</option>
                <option value="Done">Done</option>
              </select>
            </div>
            <div className="row">
              <input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
              <input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
            </div>
            <label>
              <input
                type="checkbox"
                checked={form.use_discretionary_budget}
                onChange={(e) => setForm({ ...form, use_discretionary_budget: e.target.checked })}
              />{" "}
              Use discretionary budget if score is below threshold
            </label>
            <button className="btn-primary" type="submit">Create Roadmap Item</button>
          </form>
        </div>

        <div className="card">
          <h3>Current Plan</h3>
          <div className="list">
            {items.map((item) => (
              <div className="item stack" key={item.id}>
                <strong>{decisionTitleMap.get(item.decision_id) ?? `Decision #${item.decision_id}`}</strong>
                <div style={{ color: "#6a645d" }}>Bucket: {item.bucket}</div>
                <div className="row">
                  <select value={item.status} onChange={(e) => void onStatusChange(item, e.target.value)}>
                    <option value="Scheduled">Scheduled</option>
                    <option value="In-Progress">In-Progress</option>
                    <option value="Done">Done</option>
                  </select>
                  <button className="btn-secondary" type="button" onClick={() => void onDelete(item.id)}>Remove</button>
                </div>
              </div>
            ))}
            {items.length === 0 && <div className="item">No roadmap items yet.</div>}
          </div>
        </div>
      </div>
    </section>
  );
}
