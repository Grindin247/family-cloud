"use client";

import { useEffect, useMemo, useState } from "react";
import { api, Decision, Family, RoadmapItem } from "../lib/api";

function parseDate(value: string | null): Date | null {
  if (!value) return null;
  const parsed = new Date(`${value}T12:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDate(value: string | null): string {
  if (!value) return "No date";
  const parsed = parseDate(value);
  if (!parsed) return value;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatDateShort(value: Date | null): string {
  if (!value) return "";
  return value.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function statusClass(status: string): string {
  if (status === "Scheduled") return "scheduled";
  if (status === "In-Progress") return "in-progress";
  if (status === "Done") return "done";
  return "default";
}

export default function DashboardPage() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [selectedFamilyId, setSelectedFamilyId] = useState<number | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [roadmap, setRoadmap] = useState<RoadmapItem[]>([]);
  const [error, setError] = useState<string>("");

  async function refresh() {
    try {
      const familyData = await api.listFamilies();
      setFamilies(familyData.items);
      const activeFamilyId = selectedFamilyId ?? familyData.items[0]?.id ?? null;
      setSelectedFamilyId(activeFamilyId);
      if (activeFamilyId) {
        const [decisionData, roadmapData] = await Promise.all([
          api.listDecisions(activeFamilyId, true),
          api.listRoadmap(activeFamilyId),
        ]);
        setDecisions(decisionData.items);
        setRoadmap(roadmapData.items);
      } else {
        setDecisions([]);
        setRoadmap([]);
      }
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    if (selectedFamilyId !== null) {
      void (async () => {
        try {
          const [decisionData, roadmapData] = await Promise.all([
            api.listDecisions(selectedFamilyId, true),
            api.listRoadmap(selectedFamilyId),
          ]);
          setDecisions(decisionData.items);
          setRoadmap(roadmapData.items);
        } catch (err) {
          setError(err instanceof Error ? err.message : "Failed to refresh family data");
        }
      })();
    }
  }, [selectedFamilyId]);

  const metrics = useMemo(() => {
    const queued = decisions.filter((item) => item.status === "Queued").length;
    const inProgress = decisions.filter((item) => item.status === "In-Progress").length;
    const avgScore =
      decisions
        .filter((item) => item.score_summary)
        .reduce((sum, item) => sum + (item.score_summary?.weighted_total_1_to_5 ?? 0), 0) /
      Math.max(decisions.filter((item) => item.score_summary).length, 1);

    return {
      totalDecisions: decisions.length,
      queued,
      inProgress,
      avgScore: Number.isFinite(avgScore) ? avgScore.toFixed(2) : "0.00",
    };
  }, [decisions]);

  const decisionTitleMap = useMemo(() => {
    return new Map(decisions.map((decision) => [decision.id, decision.title]));
  }, [decisions]);

  const timeline = useMemo(() => {
    const scheduled: Array<{
      item: RoadmapItem;
      start: Date;
      end: Date;
      leftPct: number;
      widthPct: number;
      statusKey: string;
    }> = [];
    const unscheduled: RoadmapItem[] = [];

    for (const item of roadmap) {
      const startCandidate = parseDate(item.start_date) ?? parseDate(item.end_date);
      const endCandidate = parseDate(item.end_date) ?? parseDate(item.start_date);
      if (!startCandidate || !endCandidate) {
        unscheduled.push(item);
        continue;
      }

      const start = startCandidate <= endCandidate ? startCandidate : endCandidate;
      const end = startCandidate <= endCandidate ? endCandidate : startCandidate;
      scheduled.push({
        item,
        start,
        end,
        leftPct: 0,
        widthPct: 0,
        statusKey: statusClass(item.status),
      });
    }

    scheduled.sort((a, b) => a.start.getTime() - b.start.getTime());
    if (scheduled.length === 0) {
      return { scheduled, unscheduled, minDate: null as Date | null, maxDate: null as Date | null };
    }

    const minDate = new Date(Math.min(...scheduled.map((entry) => entry.start.getTime())));
    const maxDate = new Date(Math.max(...scheduled.map((entry) => entry.end.getTime())));
    const minTime = minDate.getTime();
    const maxTime = maxDate.getTime() === minTime ? minTime + 24 * 60 * 60 * 1000 : maxDate.getTime();
    const total = maxTime - minTime;

    for (const entry of scheduled) {
      const left = ((entry.start.getTime() - minTime) / total) * 100;
      const width = ((entry.end.getTime() - entry.start.getTime()) / total) * 100;
      entry.leftPct = left;
      entry.widthPct = Math.max(width, 2);
    }

    return { scheduled, unscheduled, minDate, maxDate };
  }, [roadmap]);

  return (
    <section>
      <div className="page-head">
        <div>
          <h2 className="page-title">Family Dashboard</h2>
          <p className="page-sub">The daily view for shared priorities, execution status, and score quality.</p>
        </div>
        <div style={{ minWidth: 220 }}>
          <label htmlFor="family-picker">Family</label>
          <select
            id="family-picker"
            value={selectedFamilyId ?? ""}
            onChange={(event) => setSelectedFamilyId(Number(event.target.value))}
          >
            {families.map((family) => (
              <option key={family.id} value={family.id}>
                {family.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="card">{error}</div>}

      <div className="grid grid-3">
        <div className="card">
          <div>Open Decisions</div>
          <div className="kpi">{metrics.totalDecisions}</div>
        </div>
        <div className="card">
          <div>Queued</div>
          <div className="kpi">{metrics.queued}</div>
        </div>
        <div className="card">
          <div>Average Score (1-5)</div>
          <div className="kpi">{metrics.avgScore}</div>
        </div>
      </div>

      <div className="grid grid-2  panel-grid-top" style={{ marginTop: 16 }}>
        <div className="card">
          <h3>Recent Decisions</h3>
          <div className="list">
            {decisions.slice(0, 6).map((decision) => (
              <div className="item" key={decision.id}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong>{decision.title}</strong>
                  <span className="badge">{decision.status}</span>
                </div>
                <div style={{ marginTop: 6, color: "#6a645d" }}>{decision.description}</div>
                <div style={{ marginTop: 6 }}>
                  {decision.score_summary ? (
                    <span className="score">Score {decision.score_summary.weighted_total_1_to_5}/5</span>
                  ) : (
                    <span className="badge">Unscored</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h3>Roadmap Timeline</h3>
          {timeline.scheduled.length > 0 ? (
            <div className="timeline-chart">
              <div className="timeline-axis">
                <span>{formatDateShort(timeline.minDate)}</span>
                <span>{formatDateShort(timeline.maxDate)}</span>
              </div>
              <div className="timeline-list">
                {timeline.scheduled.slice(0, 8).map((entry) => (
                  <div className="timeline-row" key={entry.item.id}>
                    <div className="timeline-label">
                      <strong>{decisionTitleMap.get(entry.item.decision_id) ?? `Decision #${entry.item.decision_id}`}</strong>
                      <div className="timeline-meta">
                        {formatDate(entry.item.start_date)} to {formatDate(entry.item.end_date)}
                      </div>
                    </div>
                    <div className="timeline-track">
                      <div
                        className={`timeline-bar timeline-bar-${entry.statusKey}`}
                        style={{ left: `${entry.leftPct}%`, width: `${entry.widthPct}%` }}
                        title={`${entry.item.bucket} (${entry.item.status})`}
                      >
                        {entry.item.bucket}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="item">No scheduled roadmap dates yet.</div>
          )}

          {timeline.unscheduled.length > 0 && (
            <div className="list" style={{ marginTop: 12 }}>
              {timeline.unscheduled.slice(0, 4).map((item) => (
                <div className="item" key={item.id}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <strong>{decisionTitleMap.get(item.decision_id) ?? `Decision #${item.decision_id}`}</strong>
                    <span className="badge">{item.status}</span>
                  </div>
                  <div style={{ marginTop: 6, color: "#6a645d" }}>Bucket: {item.bucket}</div>
                  <div style={{ marginTop: 6, color: "#6a645d" }}>Dates not set</div>
                </div>
              ))}
            </div>
          )}

          {roadmap.length === 0 && <div className="item">No roadmap items yet.</div>}
        </div>
      </div>
    </section>
  );
}
