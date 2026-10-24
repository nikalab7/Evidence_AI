import json
from unittest.mock import MagicMock

import httpx
import psycopg
import pytest

from app.config import Settings
from app.service_probe import probe_database, probe_gemini


def test_gemini_paginates_and_generates_only_once_with_header_auth():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers['x-goog-api-key'] == 'secret-key'
        assert 'secret-key' not in str(request.url)
        if request.method == 'POST':
            return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': 'OK'}]}}],
                                            'usageMetadata': {'totalTokenCount': 12}})
        if request.url.params.get('pageToken'):
            return httpx.Response(200, json={'models': [{'name': 'models/gemini-2.5-flash-lite',
                'supportedGenerationMethods': ['generateContent']}]})
        return httpx.Response(200, json={'models': [], 'nextPageToken': 'page-two'})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_gemini(Settings(gemini_api_key='secret-key'), client)
    assert result['status'] == 'passed'
    assert len(requests) == 3
    assert result['generation_calls'] == 1
    assert result['usage']['totalTokenCount'] == 12


@pytest.mark.parametrize('code', [401, 403, 429, 500])
def test_gemini_errors_do_not_leak_secrets_or_retry(code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(code, json={'error': 'secret-key: private server details'})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_gemini(Settings(gemini_api_key='secret-key'), client)
    assert result['status'] == 'failed'
    assert result['http_status'] == code
    assert len(calls) == 1
    assert 'secret-key' not in json.dumps(result)


def test_unlisted_configured_model_is_not_called():
    def handler(request):
        assert request.method == 'GET'
        return httpx.Response(200, json={'models': []})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_gemini(Settings(gemini_api_key='key', gemini_model='unlisted'), client)
    assert result['error'] == 'select_available_model'
    assert result['generation_calls'] == 0


def test_gemini_timeout_is_safe():
    def handler(request):
        raise httpx.ReadTimeout('secret-key', request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_gemini(Settings(gemini_api_key='secret-key'), client)
    assert result['error'] == 'timeout'
    assert 'secret-key' not in json.dumps(result)


@pytest.mark.parametrize('payload', [{'candidates': []}, {'candidates': [{'content': {'parts': [{'thought': True, 'text': 'internal'}]}}]}])
def test_http_success_without_answer_does_not_pass(payload):
    def handler(request):
        return httpx.Response(200, json=payload if request.method == 'POST' else {
            'models': [{'name': 'models/gemini-2.5-flash-lite', 'supportedGenerationMethods': ['generateContent']}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = probe_gemini(Settings(gemini_api_key='key'), client)
    assert result['status'] == 'failed'
    assert result['error'] == 'no_text_response'


def test_database_failure_redacts_connection_exception():
    def connect(*args, **kwargs):
        raise psycopg.OperationalError('postgres://secret:password@private-host/db')
    result = probe_database(Settings(database_url='private-dsn'), connect=connect)
    assert result['status'] == 'failed'
    assert result['error'] == 'database_error'
    assert 'password' not in json.dumps(result)
    assert result['capacity_verified'] is False


@pytest.mark.parametrize('message,reason', [
    ('password authentication failed for private-user', 'authentication_failed'),
    ('Tenant or user not found: private-user', 'tenant_or_user_not_found'),
    ('could not translate host private-host', 'dns_failure'),
    ('connection timeout for private-host', 'connection_timeout'),
])
def test_database_diagnostics_classify_without_leaking_identifiers(message, reason):
    def connect(*args, **kwargs):
        raise psycopg.OperationalError(message)
    result = probe_database(Settings(database_url='private-dsn'), connect=connect)
    assert result['reason'] == reason
    assert 'private-' not in json.dumps(result)


@pytest.mark.parametrize('enable_vector', [False, True])
def test_database_missing_extension_is_not_silently_passed(enable_vector):
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [(1,), ('0.8.0', None), None, (123456,)]
    connect = MagicMock()
    connect.return_value.__enter__.return_value = conn
    result = probe_database(Settings(database_url='private-dsn'), connect=connect, enable_vector=enable_vector)
    assert result['status'] == 'incomplete'
    assert result['vector_installed'] is False
    assert result['capacity_verified'] is False
    assert result['database_size_bytes'] == 123456
    statements = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any('CREATE EXTENSION' in query for query in statements) == enable_vector
    assert connect.call_args.kwargs['sslmode'] == 'require'


def test_database_vector_operation_passes_but_capacity_stays_unverified():
    conn = MagicMock()
    conn.execute.return_value.fetchone.side_effect = [(1,), ('0.8.0', '0.8.0'),
                                                     ('0.8.0', 'extensions'), (0.0,), (123456,)]
    connect = MagicMock()
    connect.return_value.__enter__.return_value = conn
    result = probe_database(Settings(database_url='private-dsn'), connect=connect)
    assert result['status'] == 'passed'
    assert result['capacity_verified'] is False
    assert result['cosine_smoke_passed'] is True


def test_database_only_cli_does_not_spend_gemini_quota(monkeypatch, capsys):
    import app.service_probe as probe
    monkeypatch.setattr('sys.argv', ['service_probe', '--only', 'database'])
    monkeypatch.setattr(Settings, 'load', lambda: Settings())
    monkeypatch.setattr(probe, 'probe_gemini', lambda *args: pytest.fail('Unexpected Gemini call'))
    monkeypatch.setattr(probe, 'probe_database', lambda *args, **kwargs: {'status': 'failed'})
    assert probe.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report['gemini']['status'] == 'skipped'
    assert report['full_scale_ingestion_allowed'] is False
