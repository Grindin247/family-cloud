"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, BudgetSummary, Family } from "../../lib/api";

type MemberAllowanceDraft = Record<number, string>;

function fmtDate(value: string): string {
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

export default function BudgetPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [familyId, setFamilyId] = useState<number | null>(null);
  const [summary, setSummary] = useState<BudgetSummary | null>(null);
  const [threshold, setThreshold] = useState("4.0");
  const [periodDays, setPeriodDays] = useState("90");
  const [defaultAllowance, setDefaultAllowance] = useState("2");
  const [memberAllowances, setMemberAllowances] = useState<MemberAllowanceDraft>({});
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  async function refresh(targetFamilyId?: number | null) {
    const familyData = await api.listFamilies();
    setFamilies(familyData.items);
    const activeFamilyId = targetFamilyId ?? familyId ?? familyData.items[0]?.id ?? null;
    setFamilyId(activeFamilyId);
    if (!activeFamilyId) {
      setSummary(null);
      return;
    }

    const budget = await api.getBudgetSummary(activeFamilyId);
    setSummary(budget);
    setThreshold(String(budget.threshold_1_to_5));
    setPeriodDays(String(budget.period_days));
    setDefaultAllowance(String(budget.default_allowance));
    setMemberAllowances(
      budget.members.reduce<MemberAllowanceDraft>((acc, member) => {
        acc[member.member_id] = String(member.allowance);
        return acc;
      }, {}),
    );
  }

  useEffect(() => {
    void refresh().catch((err) => setError(err instanceof Error ? err.message : "Failed to load budget"));
  }, []);

  useEffect(() => {
    if (!familyId) return;
    void refresh(familyId).catch((err) => setError(err instanceof Error ? err.message : "Failed to refresh budget"));
  }, [familyId]);

  async function onSavePolicy(event: FormEvent) {
    event.preventDefault();
    if (!familyId || !summary) return;
    setSaving(true);
    setMessage("");
    try {
      const next = await api.updateBudgetPolicy(familyId, {
        threshold_1_to_5: Number(threshold),
        period_days: Number(periodDays),
        default_allowance: Number(defaultAllowance),
        member_allowances: summary.members.map((member) => ({
          member_id: member.member_id,
          allowance: Number(memberAllowances[member.member_id] ?? defaultAllowance),
        })),
      });
      setSummary(next);
      setMessage("Budget policy saved.");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save policy");
    } finally {
      setSaving(false);
    }
  }

  async function onResetPeriod() {
    if (!familyId) return;
    setMessage("");
    try {
      const next = await api.resetBudgetPeriod(familyId);
      setSummary(next);
      setMessage("Budget period reset. Allowances were reallocated.");
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset budget period");
    }
  }

  const totals = useMemo(() => {
    const members = summary?.members ?? [];
    const totalAllowance = members.reduce((sum, member) => sum + member.allowance, 0);
    const used = members.reduce((sum, member) => sum + member.used, 0);
    const remaining = members.reduce((sum, member) => sum + member.remaining, 0);
    const usedPct = totalAllowance > 0 ? Math.round((used / totalAllowance) * 100) : 0;
    return { totalAllowance, used, remaining, usedPct };
  }, [summary]);

  return (
    <section>
      <div className="page-head">
        <div>
          <h2 className="page-title">Budget</h2>
          <p className="page-sub">Control discretionary scheduling allowance for below-threshold decisions.</p>
        </div>
        <div style={{ minWidth: 220 }}>
          <label>Family</label>
          <select value={familyId ?? ""} onChange={(e) => setFamilyId(Number(e.target.value))}>
            {families.map((family) => (
              <option key={family.id} value={family.id}>
                {family.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="card">{error}</div>}
      {message && <div className="card">{message}</div>}

      {summary && (
        <div className="grid grid-2 panel-grid-top">
          <div className="card">
            <h3>Policy</h3>
            <form className="stack" onSubmit={onSavePolicy}>
              <div className="row">
                <div>
                  <label>Score Threshold (1-5)</label>
                  <input type="number" min="1" max="5" step="0.1" value={threshold} onChange={(e) => setThreshold(e.target.value)} />
                </div>
                <div>
                  <label>Reset Period (days)</label>
                  <input type="number" min="7" max="365" step="1" value={periodDays} onChange={(e) => setPeriodDays(e.target.value)} />
                </div>
              </div>
              <div>
                <label>Default Allowance Per Member (decisions per period)</label>
                <input
                  type="number"
                  min="0"
                  max="50"
                  step="1"
                  value={defaultAllowance}
                  onChange={(e) => setDefaultAllowance(e.target.value)}
                />
              </div>
              <div className="item">
                <strong>Per-Member Allowance Overrides</strong>
                <div className="list" style={{ marginTop: 10 }}>
                  {summary.members.map((member) => (
                    <div className="row" key={member.member_id}>
                      <div>
                        {member.display_name} <span className="badge">{member.role}</span>
                      </div>
                      <input
                        type="number"
                        min="0"
                        max="50"
                        step="1"
                        value={memberAllowances[member.member_id] ?? ""}
                        onChange={(e) =>
                          setMemberAllowances((prev) => ({
                            ...prev,
                            [member.member_id]: e.target.value,
                          }))
                        }
                      />
                    </div>
                  ))}
                </div>
              </div>
              <div className="row">
                <button className="btn-primary" type="submit" disabled={saving}>
                  {saving ? "Saving..." : "Save Budget Policy"}
                </button>
                <button className="btn-secondary" type="button" onClick={() => void onResetPeriod()}>
                  Reset Period Now
                </button>
              </div>
            </form>
          </div>

          <div className="card">
            <h3>Current Period Usage</h3>
            <div style={{ color: "#6a645d", marginBottom: 10 }}>
              {fmtDate(summary.period_start_date)} to {fmtDate(summary.period_end_date)} (no rollover)
            </div>
            <div className="budget-progress">
              <div className="budget-progress-fill" style={{ width: `${Math.min(totals.usedPct, 100)}%` }} />
            </div>
            <div style={{ marginTop: 8, color: "#6a645d" }}>
              Used {totals.used} of {totals.totalAllowance} discretionary slots ({totals.usedPct}%)
            </div>
            <div style={{ marginTop: 4, color: "#6a645d" }}>Remaining {totals.remaining}</div>

            <div className="list" style={{ marginTop: 12 }}>
              {summary.members.map((member) => {
                const usedPct = member.allowance > 0 ? Math.round((member.used / member.allowance) * 100) : 0;
                return (
                  <div className="item" key={member.member_id}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <strong>{member.display_name}</strong>
                      <span className="badge">{member.role}</span>
                    </div>
                    <div className="budget-progress" style={{ marginTop: 8 }}>
                      <div className="budget-progress-fill" style={{ width: `${Math.min(usedPct, 100)}%` }} />
                    </div>
                    <div style={{ marginTop: 8, color: "#6a645d" }}>
                      {member.used} used / {member.allowance} allowance, {member.remaining} remaining
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

