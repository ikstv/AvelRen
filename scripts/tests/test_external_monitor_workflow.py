"""Контракти manual-only запуску та недовірених health-відповідей."""

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.load(
    (ROOT / '.github/workflows/external-health-monitor.yml').read_text(encoding='utf-8'),
    Loader=yaml.BaseLoader,
)


def test_live_monitor_is_manual_only_and_serialized() -> None:
    assert set(WORKFLOW['on']) == {'workflow_dispatch'}
    assert WORKFLOW['concurrency']['cancel-in-progress'] == 'false'
    assert WORKFLOW['permissions'] == {'contents': 'read', 'issues': 'write'}


def test_contract_ci_has_no_issue_write_or_live_health_request() -> None:
    workflow = yaml.load(
        (ROOT / '.github/workflows/external-monitor-checks.yml').read_text(encoding='utf-8'),
        Loader=yaml.BaseLoader,
    )
    assert workflow['permissions'] == {'contents': 'read'}
    for job in workflow['jobs'].values():
        for step in job['steps']:
            assert 'curl' not in step.get('run', '')
            assert 'gh issue' not in step.get('run', '')


@pytest.mark.parametrize('payload', ['{} {}', '[]', 'null', '{}', '{"status":"$(touch sentinel)"}'])
def test_malformed_health_produces_one_safe_status(payload: str) -> None:
    probe = next(step for step in WORKFLOW['jobs']['check']['steps'] if step.get('id') == 'probe')
    matches = re.findall(r"jq (-r[s]?) '([^']+)'", probe['run'])
    flags, expression = matches[0]
    result = subprocess.run(
        [os.environ.get('AVELREN_TEST_JQ', 'jq'), flags, expression],
        input=payload, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0
    assert result.stdout == 'unknown\n'
    assert result.stderr == ''


def test_valid_health_preserves_ok_status() -> None:
    probe = next(step for step in WORKFLOW['jobs']['check']['steps'] if step.get('id') == 'probe')
    flags, expression = re.findall(r"jq (-r[s]?) '([^']+)'", probe['run'])[0]
    result = subprocess.run(
        [os.environ.get('AVELREN_TEST_JQ', 'jq'), flags, expression],
        input='{"status":"ok","age_seconds":27}', text=True,
        capture_output=True, check=False,
    )
    assert result.returncode == 0
    assert result.stdout == 'ok\n'
