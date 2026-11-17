"""Integração HTTP isolada: exige Flask instalado pelo requirements-dev.txt."""
import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from fj_operacional import criar_blueprint
from fj_operacional.models import metadata


@pytest.fixture
def contexto():
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS operacional")
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS gold")
        metadata.create_all(conn)
        conn.exec_driver_sql('CREATE TABLE gold.mart_fila_priorizacao (cluster_id TEXT, tipo TEXT, area_nome TEXT, score_0_100 REAL, run_id TEXT)')
        conn.exec_driver_sql("INSERT INTO gold.mart_fila_priorizacao VALUES ('teste1','buraco','Sé',90,'runA')")
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test-only-secret')
    estado = {'usuario': None}
    app.add_url_rule('/login', 'login', lambda: 'entrar')
    app.add_url_rule('/logout', 'logout', lambda: 'sair', methods=['POST'])
    app.register_blueprint(criar_blueprint(engine=engine,
        usuario_atual=lambda: estado['usuario'],
        validar_csrf=lambda req: req.headers.get('X-CSRFToken') == 'token-valido',
        token_csrf=lambda: 'token-valido'))
    yield app.test_client(), estado
    engine.dispose()


def test_api_anonima_nao_lista_demandas(contexto):
    client, _ = contexto
    assert client.get('/api/gestao/demandas').status_code == 401
    assert client.post('/api/gestao/demandas', json={'titulo':'Uma demanda'}).status_code == 401
    assert client.get('/gestao/kanban').status_code == 302


def test_csrf_obrigatorio(contexto):
    client, estado = contexto
    estado['usuario'] = {'id':'gestor-id','perfil':'gestor'}
    assert client.post('/api/gestao/demandas', json={'titulo':'Nova demanda'}).status_code == 403


def test_fluxo_http_e_historia(contexto):
    client, estado = contexto
    estado['usuario'] = {'id':'gestor-id','perfil':'gestor'}
    headers = {'X-CSRFToken':'token-valido'}
    criado = client.post('/api/gestao/demandas', json={'titulo':'Bueiro entupido na Sé'}, headers=headers)
    assert criado.status_code == 201
    demanda = criado.json
    assert demanda['versao'] == 1
    assert client.get('/api/gestao/demandas?q=bueiro').json['total'] == 1
    movido = client.post(f'/api/gestao/demandas/{demanda["id"]}/status',
        json={'versao':1, 'status':'pendente'}, headers=headers)
    assert movido.status_code == 200 and movido.json['versao'] == 2
    conflito = client.post(f'/api/gestao/demandas/{demanda["id"]}/status',
        json={'versao':1, 'status':'em_andamento'}, headers=headers)
    assert conflito.status_code == 409
    historia = client.get(f'/api/gestao/demandas/{demanda["id"]}/historico')
    assert historia.status_code == 200 and len(historia.json) == 2
    estado['usuario'] = {'id':'operador-id','perfil':'operador'}
    assert client.post('/api/gestao/demandas', json={'titulo':'Ilegal'}, headers=headers).status_code == 403
    assert client.get('/gestao/dashboard').status_code == 200
