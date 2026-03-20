#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


DEFAULT_CONTAINER = "family-cloud-decision-api-1"


def run_in_container(source: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["docker", "exec", "-i", DEFAULT_CONTAINER, "python", "-"],
        input=source,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"docker exec failed with {proc.returncode}")
    text = proc.stdout.strip()
    if not text:
        return {}
    return json.loads(text)


def resolve_context(*, family_id: int, actor: str, target_person_id: str | None = None) -> dict[str, Any]:
    query = ""
    if target_person_id:
        query = f"?target_person_id={target_person_id}"
    inner = json.dumps({"family_id": family_id, "actor": actor, "query": query})
    return run_in_container(
        f"""
import json, urllib.request

req = json.loads({inner!r})
http_req = urllib.request.Request(
    f"http://127.0.0.1:8000/v1/families/{{req['family_id']}}/context{{req['query']}}",
    headers={{"X-Dev-User": req["actor"], "Accept": "application/json"}},
)
with urllib.request.urlopen(http_req, timeout=20) as response:
    print(response.read().decode() or "{{}}")
"""
    )


def emit_task_operation(
    *,
    op: str,
    family_id: int,
    actor: str,
    session_id: str | None,
    payload: dict[str, Any],
    target_person_id: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_context(family_id=family_id, actor=actor, target_person_id=target_person_id)
    inner = json.dumps(
        {
            "op": op,
            "family_id": family_id,
            "actor": actor,
            "session_id": session_id,
            "payload": payload,
            "resolved": resolved,
        }
    )
    return run_in_container(
        f"""
import json, pathlib, urllib.request

req = json.loads({inner!r})
token = pathlib.Path('/run/secrets/vikunja_api_token').read_text(encoding='utf-8').strip()
headers = {{
    'Authorization': f'Bearer {{token}}',
    'Accept': 'application/json',
    'Content-Type': 'application/json',
}}

def request_json(method, url, body=None, extra_headers=None):
    hdrs = dict(headers)
    if extra_headers:
        hdrs.update(extra_headers)
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode() or '{{}}'
        return json.loads(raw)

payload = req['payload']
op = req['op']

if op == 'create-task':
    task = request_json('PUT', f"http://vikunja:3456/api/v1/projects/{{payload['project_id']}}/tasks", {{
        'title': payload['title'],
        'description': payload.get('description') or '',
        'done': bool(payload.get('done', False)),
        'due_date': payload.get('due_date'),
    }})
    event = {{
        'domain': 'task',
        'source_agent': 'TaskAgent',
        'event_type': 'task_created',
        'summary': f"Task created: {{task.get('title') or payload['title']}}",
        'topic': task.get('title') or payload['title'],
        'payload': {{
            'task_id': task.get('id'),
            'title': task.get('title') or payload['title'],
            'project_id': task.get('project_id') or payload['project_id'],
            'due_date': task.get('due_date'),
            'done': bool(task.get('done')),
            'actor_person_id': req.get('resolved', {{}}).get('actor_person_id'),
            'target_person_id': req.get('resolved', {{}}).get('target_person_id'),
            'session_id': req.get('session_id'),
        }},
    }}
elif op == 'update-task':
    task = request_json('POST', f"http://vikunja:3456/api/v1/tasks/{{payload['task_id']}}", payload['patch'])
    event = {{
        'domain': 'task',
        'source_agent': 'TaskAgent',
        'event_type': 'task_updated',
        'summary': f"Task updated: {{task.get('title') or payload.get('title') or payload['task_id']}}",
        'topic': task.get('title') or payload.get('title'),
        'payload': {{
            'task_id': task.get('id') or payload['task_id'],
            'title': task.get('title') or payload.get('title'),
            'project_id': task.get('project_id'),
            'due_date': task.get('due_date'),
            'done': bool(task.get('done')),
            'actor_person_id': req.get('resolved', {{}}).get('actor_person_id'),
            'target_person_id': req.get('resolved', {{}}).get('target_person_id'),
            'session_id': req.get('session_id'),
        }},
    }}
elif op == 'complete-task':
    task = request_json('POST', f"http://vikunja:3456/api/v1/tasks/{{payload['task_id']}}", {{
        'done': True,
    }})
    event = {{
        'domain': 'task',
        'source_agent': 'TaskAgent',
        'event_type': 'task_completed',
        'summary': f"Task completed: {{task.get('title') or payload.get('title') or payload['task_id']}}",
        'topic': task.get('title') or payload.get('title'),
        'payload': {{
            'task_id': task.get('id') or payload['task_id'],
            'title': task.get('title') or payload.get('title'),
            'project_id': task.get('project_id'),
            'due_date': task.get('due_date'),
            'done': bool(task.get('done')),
            'completed_by': req['actor'],
            'actor_person_id': req.get('resolved', {{}}).get('actor_person_id'),
            'target_person_id': req.get('resolved', {{}}).get('target_person_id'),
            'session_id': req.get('session_id'),
        }},
    }}
elif op == 'move-task':
    task = request_json('POST', f"http://vikunja:3456/api/v1/tasks/{{payload['task_id']}}", {{
        'project_id': payload['project_id'],
    }})
    event = {{
        'domain': 'task',
        'source_agent': 'TaskAgent',
        'event_type': 'task_updated',
        'summary': f"Task moved: {{task.get('title') or payload.get('title') or payload['task_id']}}",
        'topic': task.get('title') or payload.get('title'),
        'payload': {{
            'task_id': task.get('id') or payload['task_id'],
            'title': task.get('title') or payload.get('title'),
            'project_id': task.get('project_id') or payload['project_id'],
            'due_date': task.get('due_date'),
            'done': bool(task.get('done')),
            'actor_person_id': req.get('resolved', {{}}).get('actor_person_id'),
            'target_person_id': req.get('resolved', {{}}).get('target_person_id'),
            'session_id': req.get('session_id'),
        }},
    }}
elif op == 'delete-task':
    task = request_json('GET', f"http://vikunja:3456/api/v1/tasks/{{payload['task_id']}}")
    request_json('DELETE', f"http://vikunja:3456/api/v1/tasks/{{payload['task_id']}}")
    event = {{
        'domain': 'task',
        'source_agent': 'TaskAgent',
        'event_type': 'task_deleted',
        'summary': f"Task deleted: {{task.get('title') or payload.get('title') or payload['task_id']}}",
        'topic': task.get('title') or payload.get('title'),
        'payload': {{
            'task_id': task.get('id') or payload['task_id'],
            'title': task.get('title') or payload.get('title'),
            'project_id': task.get('project_id'),
            'actor_person_id': req.get('resolved', {{}}).get('actor_person_id'),
            'target_person_id': req.get('resolved', {{}}).get('target_person_id'),
            'session_id': req.get('session_id'),
        }},
    }}
else:
    raise SystemExit(f'unsupported op: {{op}}')

telemetry_headers = {{
    'X-Dev-User': req['actor'],
    'Accept': 'application/json',
    'Content-Type': 'application/json',
}}
telemetry_req = urllib.request.Request(
    f"http://127.0.0.1:8000/v1/family/{{req['family_id']}}/ops/events",
    data=json.dumps(event).encode('utf-8'),
    headers=telemetry_headers,
    method='POST',
)
with urllib.request.urlopen(telemetry_req, timeout=20) as response:
    telemetry = json.loads((response.read().decode() or '{{}}'))

print(json.dumps({{'task': task if op != 'delete-task' else task, 'telemetry': telemetry}}, separators=(',', ':')))
"""
    )


def simple_query(source: str) -> dict[str, Any]:
    return run_in_container(source)


def cmd_health(_: argparse.Namespace) -> None:
    result = simple_query(
        """
import json, pathlib, urllib.request
token = pathlib.Path('/run/secrets/vikunja_api_token').read_text(encoding='utf-8').strip()
req = urllib.request.Request('http://vikunja:3456/api/v1/info', headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode())
"""
    )
    print(json.dumps(result, indent=2))


def cmd_list_projects(_: argparse.Namespace) -> None:
    result = simple_query(
        """
import json, pathlib, urllib.request
token = pathlib.Path('/run/secrets/vikunja_api_token').read_text(encoding='utf-8').strip()
req = urllib.request.Request('http://vikunja:3456/api/v1/projects', headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode())
"""
    )
    print(json.dumps(result, indent=2))


def cmd_find_project(args: argparse.Namespace) -> None:
    projects = simple_query(
        """
import json, pathlib, urllib.request
token = pathlib.Path('/run/secrets/vikunja_api_token').read_text(encoding='utf-8').strip()
req = urllib.request.Request('http://vikunja:3456/api/v1/projects', headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode())
"""
    )
    needle = args.name.strip().lower()
    exact = [p for p in projects if str(p.get("title") or "").strip().lower() == needle]
    candidates = exact or [p for p in projects if needle in str(p.get("title") or "").strip().lower()]
    print(json.dumps(candidates, indent=2))


def cmd_list_tasks(args: argparse.Namespace) -> None:
    result = simple_query(
        f"""
import json, pathlib, urllib.request
token = pathlib.Path('/run/secrets/vikunja_api_token').read_text(encoding='utf-8').strip()
req = urllib.request.Request('http://vikunja:3456/api/v1/projects/{args.project_id}/tasks', headers={{'Authorization': f'Bearer {{token}}', 'Accept': 'application/json'}})
with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode())
"""
    )
    print(json.dumps(result, indent=2))


def cmd_find_task(args: argparse.Namespace) -> None:
    tasks: list[dict[str, Any]] = []
    if args.project_id is not None:
        tasks = simple_query(
            f"""
import json, pathlib, urllib.request
token = pathlib.Path('/run/secrets/vikunja_api_token').read_text(encoding='utf-8').strip()
req = urllib.request.Request('http://vikunja:3456/api/v1/projects/{args.project_id}/tasks', headers={{'Authorization': f'Bearer {{token}}', 'Accept': 'application/json'}})
with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode())
"""
        )
    else:
        projects = simple_query(
            """
import json, pathlib, urllib.request
token = pathlib.Path('/run/secrets/vikunja_api_token').read_text(encoding='utf-8').strip()
req = urllib.request.Request('http://vikunja:3456/api/v1/projects', headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode())
"""
        )
        for project in projects:
            project_id = project.get("id")
            if project_id is None:
                continue
            tasks.extend(
                simple_query(
                    f"""
import json, pathlib, urllib.request
token = pathlib.Path('/run/secrets/vikunja_api_token').read_text(encoding='utf-8').strip()
req = urllib.request.Request('http://vikunja:3456/api/v1/projects/{project_id}/tasks', headers={{'Authorization': f'Bearer {{token}}', 'Accept': 'application/json'}})
with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode())
"""
                )
            )
    needle = args.title.strip().lower()
    matches = [task for task in tasks if needle in str(task.get("title") or "").strip().lower()]
    print(json.dumps(matches, indent=2))


def cmd_create_task(args: argparse.Namespace) -> None:
    result = emit_task_operation(
        op="create-task",
        family_id=args.family_id,
        actor=args.actor,
        session_id=args.session_id,
        target_person_id=args.target_person_id,
        payload={
            "project_id": args.project_id,
            "title": args.title,
            "description": args.description,
            "due_date": args.due_date,
            "done": False,
        },
    )
    print(json.dumps(result, indent=2))


def cmd_update_task(args: argparse.Namespace) -> None:
    patch = json.loads(args.patch_json)
    result = emit_task_operation(
        op="update-task",
        family_id=args.family_id,
        actor=args.actor,
        session_id=args.session_id,
        target_person_id=args.target_person_id,
        payload={"task_id": args.task_id, "patch": patch, "title": args.title},
    )
    print(json.dumps(result, indent=2))


def cmd_complete_task(args: argparse.Namespace) -> None:
    result = emit_task_operation(
        op="complete-task",
        family_id=args.family_id,
        actor=args.actor,
        session_id=args.session_id,
        target_person_id=args.target_person_id,
        payload={"task_id": args.task_id, "title": args.title},
    )
    print(json.dumps(result, indent=2))


def cmd_delete_task(args: argparse.Namespace) -> None:
    result = emit_task_operation(
        op="delete-task",
        family_id=args.family_id,
        actor=args.actor,
        session_id=args.session_id,
        target_person_id=args.target_person_id,
        payload={"task_id": args.task_id, "title": args.title},
    )
    print(json.dumps(result, indent=2))


def cmd_move_task(args: argparse.Namespace) -> None:
    result = emit_task_operation(
        op="move-task",
        family_id=args.family_id,
        actor=args.actor,
        session_id=args.session_id,
        target_person_id=args.target_person_id,
        payload={"task_id": args.task_id, "project_id": args.project_id, "title": args.title},
    )
    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TasksAgent Vikunja helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    health = sub.add_parser("health")
    health.set_defaults(func=cmd_health)

    lp = sub.add_parser("list-projects")
    lp.set_defaults(func=cmd_list_projects)

    fp = sub.add_parser("find-project")
    fp.add_argument("--name", required=True)
    fp.set_defaults(func=cmd_find_project)

    lt = sub.add_parser("list-tasks")
    lt.add_argument("--project-id", type=int, required=True)
    lt.set_defaults(func=cmd_list_tasks)

    ft = sub.add_parser("find-task")
    ft.add_argument("--title", required=True)
    ft.add_argument("--project-id", type=int)
    ft.set_defaults(func=cmd_find_task)

    create = sub.add_parser("create-task")
    create.add_argument("--family-id", type=int, required=True)
    create.add_argument("--actor", required=True)
    create.add_argument("--project-id", type=int, required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--due-date")
    create.add_argument("--session-id")
    create.add_argument("--target-person-id")
    create.set_defaults(func=cmd_create_task)

    update = sub.add_parser("update-task")
    update.add_argument("--family-id", type=int, required=True)
    update.add_argument("--actor", required=True)
    update.add_argument("--task-id", type=int, required=True)
    update.add_argument("--patch-json", required=True)
    update.add_argument("--title")
    update.add_argument("--session-id")
    update.add_argument("--target-person-id")
    update.set_defaults(func=cmd_update_task)

    complete = sub.add_parser("complete-task")
    complete.add_argument("--family-id", type=int, required=True)
    complete.add_argument("--actor", required=True)
    complete.add_argument("--task-id", type=int, required=True)
    complete.add_argument("--title")
    complete.add_argument("--session-id")
    complete.add_argument("--target-person-id")
    complete.set_defaults(func=cmd_complete_task)

    move = sub.add_parser("move-task")
    move.add_argument("--family-id", type=int, required=True)
    move.add_argument("--actor", required=True)
    move.add_argument("--task-id", type=int, required=True)
    move.add_argument("--project-id", type=int, required=True)
    move.add_argument("--title")
    move.add_argument("--session-id")
    move.add_argument("--target-person-id")
    move.set_defaults(func=cmd_move_task)

    delete = sub.add_parser("delete-task")
    delete.add_argument("--family-id", type=int, required=True)
    delete.add_argument("--actor", required=True)
    delete.add_argument("--task-id", type=int, required=True)
    delete.add_argument("--title")
    delete.add_argument("--session-id")
    delete.add_argument("--target-person-id")
    delete.set_defaults(func=cmd_delete_task)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
