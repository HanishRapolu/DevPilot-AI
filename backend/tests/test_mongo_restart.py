"""Opt-in real MongoDB checkpoint test across two Python processes; no live LLM/GitHub."""
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import pytest


@pytest.mark.skipif(os.getenv('DEVPILOT_TEST_MONGO') != '1', reason='Opt in with a reachable test MongoDB database')
def test_resume_in_second_process():
    from app.config import Settings
    from pymongo import MongoClient
    suffix = uuid4().hex
    script = '''
import sys
from app.config import Settings
from pymongo import MongoClient
from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.types import Command
from tests.test_workflow import setup
s = Settings()
with MongoClient(s.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=5000) as client:
    saver = MongoDBSaver(client, db_name=s.mongodb_database,
        checkpoint_collection_name='verify_cp_' + sys.argv[1],
        writes_collection_name='verify_writes_' + sys.argv[1])
    _, config, state, calls, workflow, _ = setup()
    graph = workflow.build(saver)
    result = graph.invoke(state if sys.argv[2]=='pause' else Command(resume='trusted-no'), config)
    assert result.get('__interrupt__') if sys.argv[2]=='pause' else result['task_status']=='rejected'
    if sys.argv[2]=='resume': assert 'get_issue' not in calls
'''
    settings = Settings()
    try:
        for operation in ('pause', 'resume'):
            done = subprocess.run([sys.executable, '-c', script, suffix, operation],
                cwd=Path(__file__).parents[1], capture_output=True, timeout=45)
            assert done.returncode == 0, 'MongoDB subprocess failed; run sanitized connectivity check'
    finally:
        with MongoClient(settings.mongodb_uri.get_secret_value(), serverSelectionTimeoutMS=5000) as client:
            for prefix in ('verify_cp_', 'verify_writes_'):
                client[settings.mongodb_database].drop_collection(prefix + suffix)
