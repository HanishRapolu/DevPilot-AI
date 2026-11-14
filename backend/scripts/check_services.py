"""Explicit live checks. Run: python -m scripts.check_services.

Uses local credentials without printing them. Creates and removes one uniquely
identified verification task. The LLM check consumes a small amount of quota.
Each child process has a deadline, including event-loop initialization.
"""
import argparse
import asyncio
import json
import subprocess
import sys
from uuid import UUID

from pymongo import MongoClient

from app.api.tasks import create_task, get_task
from app.config import Settings
from app.models import TaskCreate
from app.services.llm import OpenRouterService
from scripts.check_llm import SmokeAnswer


def check_database() -> None:
    settings = Settings()
    options = dict(serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
                   socketTimeoutMS=5000, tz_aware=True)
    task_id = None
    with MongoClient(settings.mongodb_uri.get_secret_value(), **options) as client:
        db = client[settings.mongodb_database]
        db.command("ping")
        try:
            task = create_task(TaskCreate(
                title="DevPilot Phase 1 connectivity check",
                repository_url="https://github.com/example/devpilot-verification",
                description="Temporary verification record; removed by the check.",
            ), db)
            task_id = task.id
            with MongoClient(settings.mongodb_uri.get_secret_value(), **options) as reader:
                restored = get_task(UUID(task.id), reader[settings.mongodb_database])
                assert restored.id == task.id
                assert restored.events[0].type == "task.created"
        finally:
            if task_id is not None:
                db.tasks.delete_one({"_id": task_id})


async def check_llm() -> None:
    service = OpenRouterService(Settings())
    try:
        await service.generate("Return a short connectivity confirmation in the message field.", SmokeAnswer)
    finally:
        await service.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=["database", "openrouter"])
    args = parser.parse_args()
    if args.worker:
        try:
            if args.worker == "database":
                check_database()
            else:
                asyncio.run(check_llm())
            print(json.dumps({"check": args.worker, "status": "passed"}))
            return 0
        except Exception as exc:
            # Exception text may include credentials, URIs, or provider content.
            detail = str(exc).lower()
            category = "configuration_or_service_error"
            if any(word in detail for word in ("dns", "nameserver", "getaddrinfo", "resolution lifetime")):
                category = "dns_resolution_failed"
            elif getattr(exc, "code", None) == 18:
                category = "authentication_failed"
            print(json.dumps({"check": args.worker, "status": "failed",
                              "error_type": type(exc).__name__, "category": category}))
            return 1
    failed = False
    for name, timeout in [("database", 35), ("openrouter", 105)]:
        try:
            result = subprocess.run([sys.executable, "-m", "scripts.check_services", "--worker", name],
                                    capture_output=True, text=True, timeout=timeout)
            # Only print the expected sanitized JSON object, never raw stderr.
            report = json.loads(result.stdout)
            print(json.dumps(report), flush=True)
            failed |= result.returncode != 0
        except subprocess.TimeoutExpired:
            print(json.dumps({"check": name, "status": "timeout"}), flush=True)
            failed = True
        except (ValueError, OSError):
            print(json.dumps({"check": name, "status": "failed", "error_type": "CheckProcessError"}), flush=True)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
