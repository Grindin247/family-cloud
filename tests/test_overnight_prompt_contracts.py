from __future__ import annotations

import json
from pathlib import Path


TOP_LEVEL_PROMPTS = {
    "caleb": Path("/home/luvwrk777/.openclaw/workspace-main/SOUL.md"),
    "amelia": Path("/home/luvwrk777/.openclaw/workspace-amelia/SOUL.md"),
}

DOMAIN_PROMPTS = {
    "planning": Path("/home/luvwrk777/.openclaw/agents/planning-agent/SOUL.md"),
    "profile": Path("/home/luvwrk777/.openclaw/agents/profile-agent/SOUL.md"),
    "education": Path("/home/luvwrk777/.openclaw/agents/education-agent/SOUL.md"),
    "decision": Path("/home/luvwrk777/.openclaw/agents/decision-agent/SOUL.md"),
    "tasks": Path("/home/luvwrk777/.openclaw/agents/tasks-agent/SOUL.md"),
    "event": Path("/home/luvwrk777/.openclaw/agents/event-agent/SOUL.md"),
    "file": Path("/home/luvwrk777/.openclaw/agents/file-agent/SOUL.md"),
}

CRON_JOBS_PATH = Path("/home/luvwrk777/.openclaw/cron/jobs.json")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _jobs() -> list[dict]:
    payload = json.loads(CRON_JOBS_PATH.read_text(encoding="utf-8"))
    return payload["jobs"]


def _job_by_name(name: str) -> dict:
    for job in _jobs():
        if job.get("name") == name:
            return job
    raise AssertionError(f"cron job not found: {name}")


def test_caleb_prompt_defines_overnight_ops_and_morning_brief_contract() -> None:
    text = _read(TOP_LEVEL_PROMPTS["caleb"])
    assert "## Overnight Ops Mode" in text
    assert "family `2` / Callender family" in text
    assert "return exactly `NO_REPLY` after archival is complete" in text
    assert "`tasks-agent`, `decision-agent`, `file-agent`, and `event-agent`" in text
    assert "/Notes/Areas/Family Cloud/Overnight Briefings/YYYY-MM-DD_caleb-overnight-ops.md" in text
    assert "## Morning Brief Mode" in text
    assert "`What Matters Today`" in text
    assert "`Plan And Life Optimization`" in text
    assert "`Upcoming / Travel / Calendar`" in text
    assert "`Relevant News`" in text
    assert "`Open Questions`" in text
    assert "`System Gaps`" in text
    assert "/Notes/Areas/Family Cloud/Overnight Briefings/YYYY-MM-DD_morning-brief.md" in text


def test_amelia_prompt_defines_overnight_research_contract() -> None:
    text = _read(TOP_LEVEL_PROMPTS["amelia"])
    assert "## Overnight Research Mode" in text
    assert "family relevance profile" in text
    assert "last 7 days of relevant email" in text
    assert "next 30 days of calendar" in text
    assert "`planning-agent`, `profile-agent`, and `education-agent`" in text
    assert "/Notes/Areas/Family Cloud/Overnight Briefings/YYYY-MM-DD_amelia-overnight-discovery.md" in text
    assert "return exactly `NO_REPLY`" in text


def test_domain_prompts_define_overnight_safe_write_boundaries() -> None:
    planning = _read(DOMAIN_PROMPTS["planning"])
    assert "## Overnight Research Mode" in planning
    assert "updating `task_suggestions`" in planning
    assert "updating `feasibility_summary`" in planning
    assert "do not auto-activate, pause, archive, create, or delete canonical plans during overnight runs" in planning
    assert "`anomalies`, `gaps`, `safe_updates`, `queued_questions`, and `sources`" in planning

    profile = _read(DOMAIN_PROMPTS["profile"])
    assert "safe writes are limited to queued questions only during overnight runs" in profile
    assert "do not create or change canonical profile facts" in profile

    education = _read(DOMAIN_PROMPTS["education"])
    assert "safe writes are limited to queued questions only during overnight runs" in education
    assert "do not create or change canonical assignments, journals, assessments, quiz records, or learner facts overnight" in education

    decision = _read(DOMAIN_PROMPTS["decision"])
    assert "safe writes are limited to creating or updating queued questions only during overnight runs" in decision
    assert "do not create, archive, close, reopen, or mutate canonical goals or decisions overnight" in decision

    tasks = _read(DOMAIN_PROMPTS["tasks"])
    assert "safe writes are limited to creating or updating queued questions only during overnight runs" in tasks
    assert "do not auto-create, complete, move, delete, or status-mutate canonical tasks or projects overnight" in tasks

    event = _read(DOMAIN_PROMPTS["event"])
    assert "## Overnight Ops Mode" in event
    assert "remain read-only" in event
    assert "do not record new family events during overnight runs" in event

    file_prompt = _read(DOMAIN_PROMPTS["file"])
    assert "## Overnight Briefing Mode" in file_prompt
    assert "same-day reruns must update the same archived path instead of creating duplicate daily files" in file_prompt
    assert "`/Notes/Areas/Family Cloud/Overnight Briefings/...`" in file_prompt


def test_cron_config_contains_three_overnight_jobs_with_expected_delivery_rules() -> None:
    amelia_job = _job_by_name("Amelia overnight research and discovery")
    assert amelia_job["agentId"] == "amelia"
    assert amelia_job["schedule"]["expr"] == "30 22 * * *"
    assert amelia_job["schedule"]["tz"] == "America/New_York"
    assert amelia_job["sessionTarget"] == "isolated"
    assert amelia_job["wakeMode"] == "next-heartbeat"
    assert amelia_job["delivery"]["mode"] == "none"
    assert "NO_REPLY" in amelia_job["payload"]["message"]

    caleb_ops_job = _job_by_name("Caleb overnight ops audit")
    assert caleb_ops_job["agentId"] == "main"
    assert caleb_ops_job["schedule"]["expr"] == "30 1 * * *"
    assert caleb_ops_job["schedule"]["tz"] == "America/New_York"
    assert caleb_ops_job["sessionTarget"] == "isolated"
    assert caleb_ops_job["wakeMode"] == "next-heartbeat"
    assert caleb_ops_job["delivery"]["mode"] == "none"
    assert "NO_REPLY" in caleb_ops_job["payload"]["message"]

    morning_job = _job_by_name("Caleb morning brief")
    assert morning_job["agentId"] == "main"
    assert morning_job["schedule"]["expr"] == "5 8 * * *"
    assert morning_job["schedule"]["tz"] == "America/New_York"
    assert morning_job["sessionTarget"] == "isolated"
    assert morning_job["wakeMode"] == "next-heartbeat"
    assert morning_job["delivery"] == {
        "mode": "announce",
        "channel": "discord",
        "accountId": "default",
        "to": "525687139737010177",
    }
