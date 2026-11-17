import pytest
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.pool import StaticPool
from fj_operacional.models import metadata, demandas, historico
from fj_operacional.repository import DemandasRepository
from fj_operacional.domain import RegraNegocioError, ConflitoVersaoError, SemPermissaoError


@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS operacional")
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS gold")
        metadata.create_all(conn)
        conn.exec_driver_sql("""CREATE TABLE gold.mart_fila_priorizacao
            (cluster_id TEXT PRIMARY KEY, tipo TEXT, area_nome TEXT,
             score_0_100 REAL, run_id TEXT)""")
        conn.exec_driver_sql("INSERT INTO gold.mart_fila_priorizacao VALUES ('c-001','alagamento','Sé',87,'run-1')")
    yield DemandasRepository(engine), engine
    engine.dispose()


def test_criacao_persiste_e_audita(setup):
    repo, eng=setup
    d=repo.criar_manual(ator='g1',perfil='gestor',titulo='Bueiro entupido',area_nome='Sé')
    assert d['status']=='nova' and d['versao']==1 and d['origem']=='manual'
    eventos=repo.historico_da_demanda(d['id'])
    assert len(eventos)==1 and eventos[0]['tipo_evento']=='criacao'
    assert eventos[0]['autor_id']=='g1'


def test_fluxo_completo_e_auditoria(setup):
    repo,_=setup
    d=repo.criar_manual(ator='g',perfil='gestor',titulo='Buraco na rua')
    for destino,perfil,just in [('pendente','gestor',''),('em_andamento','operador',''),
                               ('aguardando_validacao','operador',''),('resolvida','gestor','Foto verificada')]:
        d=repo.mudar_status(demanda_id=d['id'],destino=destino,versao=d['versao'],
                            ator=perfil,perfil=perfil,justificativa=just)
    assert d['status']=='resolvida' and d['versao']==5
    eventos=repo.historico_da_demanda(d['id'])
    assert len(eventos)==5 and eventos[-1]['justificativa']=='Foto verificada'
    assert eventos[-1]['status_anterior']=='aguardando_validacao'


def test_versao_concorrente_nao_altera_nem_audita(setup):
    repo,_=setup
    d=repo.criar_manual(ator='g',perfil='gestor',titulo='Árvore caída')
    d2=repo.mudar_status(demanda_id=d['id'],destino='pendente',versao=1,
                         ator='g',perfil='gestor')
    with pytest.raises(ConflitoVersaoError):
        repo.mudar_status(demanda_id=d['id'],destino='pendente',versao=1,
                          ator='g2',perfil='gestor')
    assert d2['versao']==2 and len(repo.historico_da_demanda(d['id']))==2


def test_nao_pula_etapa(setup):
    repo,_=setup
    d=repo.criar_manual(ator='g',perfil='gestor',titulo='Ajuste da via')
    with pytest.raises(RegraNegocioError):
        repo.mudar_status(demanda_id=d['id'],destino='resolvida',versao=1,
                          ator='g',perfil='gestor',justificativa='OK')
    assert repo.buscar(d['id'])['status']=='nova'


def test_operador_nao_edita(setup):
    repo,_=setup
    d=repo.criar_manual(ator='g',perfil='gestor',titulo='Buraco na via')
    with pytest.raises(SemPermissaoError):
        repo.editar(demanda_id=d['id'],versao=1,ator='oper',perfil='operador',titulo='Outro')


def test_edicao_preserva_status_e_historico(setup):
    repo,_=setup
    d=repo.criar_manual(ator='g',perfil='gestor',titulo='Bueiro interditado')
    e=repo.editar(demanda_id=d['id'],versao=1,ator='g',perfil='gestor',
                 titulo='Bueiro interditado na Sé',prazo_em='2026-12-02T10:00:00-03:00')
    assert e['titulo'].endswith('Sé') and e['versao']==2
    assert e['prazo_em'].startswith('2026-12-02T13:00:00')
    assert repo.historico_da_demanda(d['id'])[-1]['tipo_evento']=='edicao'


def test_importacao_gold_idempotente_preserva_status(setup):
    repo,engine=setup
    d=repo.importar_gold(ator='gestor1',perfil='gestor',cluster_id='c-001')
    assert d['origem']=='gold' and d['score_origem']==87
    d2=repo.mudar_status(demanda_id=d['id'],destino='pendente',versao=1,
                         ator='gestor1',perfil='gestor')
    with engine.begin() as conn:
        conn.execute(text('UPDATE gold.mart_fila_priorizacao SET run_id=:r, score_0_100=:s WHERE cluster_id=:cid'),
                     {'r':'run-2','s':42,'cid':'c-001'})
    importada=repo.importar_gold(ator='gestor2',perfil='gestor',cluster_id='c-001')
    assert importada['id']==d['id'] and importada['status']=='pendente'
    assert importada['versao']==2 and importada['score_origem']==87
    assert importada['run_id_origem']=='run-1'
    assert len(repo.historico_da_demanda(d['id']))==2


def test_nao_importa_automaticamente_a_gold(setup):
    repo,_=setup
    assert sum(col['total'] for col in repo.kanban().values())==0


def test_kanban_limite_e_contagem(setup):
    repo,_=setup
    for i in range(3):
        repo.criar_manual(ator='g',perfil='gestor',titulo=f'Problema no distrito {i}')
    quadro=repo.kanban(limite_por_coluna=2)
    assert quadro['nova']['total']==3
    assert len(quadro['nova']['itens'])==2


def test_operador_nao_cria(setup):
    repo,_=setup
    with pytest.raises(SemPermissaoError):
        repo.criar_manual(ator='oper',perfil='operador',titulo='Demanda não autorizada')


def test_lista_busca_filtro_paginacao(setup):
    repo, _ = setup
    repo.criar_manual(ator='g', perfil='gestor', titulo='Buraco na Sé', area_nome='Sé')
    repo.criar_manual(ator='g', perfil='gestor', titulo='Árvore caída', area_nome='Tucuruvi')
    repo.criar_manual(ator='g', perfil='gestor', titulo='Bueiro obstruído', area_nome='Sé')
    assert repo.listar(busca='Sé')['total'] == 2
    assert repo.listar(busca='não existe')['total'] == 0
    assert repo.listar(pagina=1, por_pagina=2)['paginas'] == 2
    assert len(repo.listar(pagina=2, por_pagina=2)['itens']) == 1
    assert repo.listar(status='nova')['total'] == 3


def test_metricas_operacionais(setup):
    repo, _ = setup
    d = repo.criar_manual(ator='g', perfil='gestor', titulo='Demanda com prazo vencido',
                          prazo_em='2025-01-01T00:00:00+00:00')
    repo.criar_manual(ator='g', perfil='gestor', titulo='Demanda sem prazo')
    assert repo.metricas()['total'] == 2
    assert repo.metricas()['atrasadas'] == 1
    repo.mudar_status(demanda_id=d['id'], destino='pendente', versao=1, ator='g', perfil='gestor')
    assert repo.metricas()['por_status']['pendente'] == 1
