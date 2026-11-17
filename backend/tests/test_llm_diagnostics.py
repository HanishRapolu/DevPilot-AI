from types import SimpleNamespace

import pytest

from app.services.llm import OutputError, validate_response
from app.workflow.models import Development


def response(content=None, reason='stop', refusal=None):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=reason,
        message=SimpleNamespace(content=content, refusal=refusal))])


@pytest.mark.parametrize('value,category', [
    (SimpleNamespace(choices=[]), 'missing_choices'),
    (response(reason='length'), 'output_truncated'),
    (response(reason='content_filter'), 'response_refused'),
    (response(refusal='private refusal'), 'response_refused'),
    (response(reason='tool_calls'), 'unexpected_finish_reason'),
    (response('   '), 'empty_content'),
    (response('```json\n{}\n```'), 'invalid_json'),
    (response('{"patch":123,"explanation":"private source"}'), 'schema_mismatch'),
    (response('{"patch":"x"}'), 'schema_mismatch'),
    (response('{"patch":"x","explanation":"x","private_field":1}'), 'schema_mismatch'),
])
def test_failure_category_and_redaction(value, category):
    with pytest.raises(OutputError, match=category) as caught:
        validate_response(value, Development)
    assert 'private' not in str(caught.value)


def test_valid_developer_response():
    result = validate_response(response('{"patch":"diff","explanation":"Fix mean"}'), Development)
    assert result.patch == 'diff'


def test_missing_field_is_named():
    with pytest.raises(OutputError, match='explanation:missing'):
        validate_response(response('{"patch":"diff"}'), Development)
