from unittest.mock import patch
import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    return app.test_client()


def test_health_healthy(client):
    with patch('app.check_database', return_value=True):
        response = client.get('/health')
    assert response.status_code == 200
    assert response.json == {'status': 'healthy'}


def test_health_degraded(client):
    with patch('app.check_database', return_value=False):
        response = client.get('/health')
    assert response.status_code == 503
    assert response.json == {'status': 'degraded'}


def test_index_renders_priorities(client):
    data = [{'rank':1,'tipo':'buraco','area_nome':'Tucuruvi','score_0_100':51.55}]
    with patch('app.fetch_priorities', return_value=data):
        response = client.get('/')
    assert response.status_code == 200
    assert 'Tucuruvi' in response.get_data(as_text=True)
    assert '51.55' in response.get_data(as_text=True)


def test_index_handles_database_failure(client):
    with patch('app.fetch_priorities', side_effect=RuntimeError('Banco indisponível')):
        response = client.get('/')
    assert response.status_code == 503
    assert 'temporariamente indisponíveis' in response.get_data(as_text=True)


def test_login_indisponivel_sem_config(client):
    if not app.config.get('OP_ENGINE'):
        assert client.get('/login').status_code == 503
