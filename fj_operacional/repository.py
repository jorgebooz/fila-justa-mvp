"""Operações transacionais sobre demandas; Gold é consultada sem escrita.

Somente chamadas explicitamente autorizadas pelo adaptador de autenticação
podem usar estes métodos: o repositório também revalida perfis e transições.
"""
from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, insert, update, func, text, or_
from sqlalchemy.exc import IntegrityError

from .domain import (
    STATUS, RegraNegocioError, ConflitoVersaoError, NaoEncontradoError,
    SemPermissaoError, validar_perfil, validar_transicao,
    situacao_prazo, normalizar_prazo,
)
from .models import demandas, historico


def utcnow():
    return datetime.now(timezone.utc)


def _limpar(v, limite=3000):
    return str(v or "").strip()[:limite]


def _validar_titulo(titulo):
    titulo = _limpar(titulo, 160)
    if len(titulo) < 3:
        raise RegraNegocioError("Título precisa de pelo menos 3 caracteres")
    return titulo


def _json(row):
    obj = dict(row)
    for chave in ("criado_em", "atualizado_em", "prazo_em", "ocorrido_em"):
        valor = obj.get(chave)
        if isinstance(valor, datetime):
            if valor.tzinfo is None:  # sqlite nos testes armazena UTC sem fuso
                valor = valor.replace(tzinfo=timezone.utc)
            obj[chave] = valor.isoformat()
    if "status" in obj:
        prazo = normalizar_prazo(obj.get("prazo_em"))
        obj["situacao_prazo"] = situacao_prazo(obj["status"], prazo)
    return obj


class DemandasRepository:
    def __init__(self, engine):
        self.engine = engine

    def _evento(self, conn, *, demanda_id, tipo_evento, anterior, novo, justificativa, autor_id, versao, agora):
        conn.execute(insert(historico).values(
            id=str(uuid4()), demanda_id=demanda_id, tipo_evento=tipo_evento,
            status_anterior=anterior, status_novo=novo,
            justificativa=justificativa, autor_id=autor_id,
            ocorrido_em=agora, versao_nova=versao,
        ))

    def buscar(self, demanda_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(demandas).where(demandas.c.id == demanda_id)).mappings().first()
        if row is None:
            raise NaoEncontradoError("Demanda não encontrada")
        return _json(row)

    def criar_manual(self, *, ator, perfil, titulo, descricao="", tipo=None, area_nome=None, prazo_em=None):
        validar_perfil(perfil)
        if perfil not in {"gestor", "administrador"}:
            raise SemPermissaoError("Somente gestor ou administrador cadastra demanda")
        titulo = _validar_titulo(titulo)
        agora, identificador = utcnow(), str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(insert(demandas).values(
                id=identificador, origem="manual", cluster_id=None,
                run_id_origem=None, titulo=titulo, descricao=_limpar(descricao),
                tipo=_limpar(tipo, 120) or None,
                area_nome=_limpar(area_nome, 160) or None,
                score_origem=None, status="nova", prazo_em=normalizar_prazo(prazo_em),
                criado_por=str(ator), criado_em=agora, atualizado_em=agora, versao=1,
            ))
            self._evento(conn, demanda_id=identificador, tipo_evento="criacao", anterior=None,
                         novo="nova", justificativa="Cadastro manual", autor_id=str(ator), versao=1, agora=agora)
        return self.buscar(identificador)

    def importar_gold(self, *, ator, perfil, cluster_id):
        validar_perfil(perfil)
        if perfil not in {"gestor", "administrador"}:
            raise SemPermissaoError("Importação exige gestor/administrador")
        cluster_id = _limpar(cluster_id, 300)
        if not cluster_id:
            raise RegraNegocioError("Informe o cluster_id da Gold")
        # Importa uma demanda selecionada, NÃO importa automaticamente 11.163 clusters históricos.
        # Usa a view da rodada atual; não considera os scores/status armazenados na Gold como operacionais.
        with self.engine.connect() as conn:
            existente = conn.execute(select(demandas.c.id).where(demandas.c.cluster_id == cluster_id)).scalar_one_or_none()
            if existente:
                return self.buscar(existente)
            origem = conn.execute(text("""
                SELECT cluster_id, tipo, area_nome, score_0_100, run_id
                FROM gold.mart_fila_priorizacao WHERE cluster_id = :cid
            """), {"cid": cluster_id}).mappings().first()
        if origem is None:
            raise NaoEncontradoError("Cluster não encontrado na Gold atual")
        agora, identificador = utcnow(), str(uuid4())
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(demandas).values(
                    id=identificador, origem="gold", cluster_id=cluster_id,
                    run_id_origem=origem["run_id"],
                    titulo=_validar_titulo(f'{origem["tipo"]} — {origem["area_nome"]}'),
                    descricao="Ocorrência selecionada da fila de priorização; verificar em campo.",
                    tipo=_limpar(origem["tipo"], 120), area_nome=_limpar(origem["area_nome"], 160),
                    score_origem=float(origem["score_0_100"]), status="nova", prazo_em=None,
                    criado_por=str(ator), criado_em=agora, atualizado_em=agora, versao=1,
                ))
                self._evento(conn, demanda_id=identificador, tipo_evento="criacao", anterior=None,
                             novo="nova", justificativa="Importada da Gold", autor_id=str(ator), versao=1, agora=agora)
        except IntegrityError:
            # Corrida entre importações iguais: única linha por cluster. Nenhuma alteração de estado.
            with self.engine.connect() as conn:
                existente = conn.execute(select(demandas.c.id).where(demandas.c.cluster_id == cluster_id)).scalar_one_or_none()
            if existente:
                return self.buscar(existente)
            raise
        return self.buscar(identificador)

    def mudar_status(self, *, demanda_id, destino, versao, ator, perfil, justificativa=""):
        justificativa = _limpar(justificativa, 2000)
        with self.engine.begin() as conn:
            row = conn.execute(select(demandas).where(demandas.c.id == demanda_id)).mappings().first()
            if row is None:
                raise NaoEncontradoError("Demanda não encontrada")
            if int(versao) != row["versao"]:
                raise ConflitoVersaoError("Demanda alterada por outro usuário; atualize a tela")
            validar_transicao(row["status"], destino, perfil, justificativa)
            agora = utcnow()
            alteradas = conn.execute(update(demandas).where(
                demandas.c.id == demanda_id, demandas.c.versao == versao
            ).values(status=destino, versao=versao + 1, atualizado_em=agora)).rowcount
            if alteradas != 1:
                raise ConflitoVersaoError("Versão desatualizada")
            self._evento(conn, demanda_id=demanda_id, tipo_evento="transicao", anterior=row["status"],
                         novo=destino, justificativa=justificativa, autor_id=str(ator),
                         versao=versao + 1, agora=agora)
        return self.buscar(demanda_id)

    def editar(self, *, demanda_id, versao, ator, perfil, titulo, descricao="", tipo=None, area_nome=None, prazo_em=None):
        validar_perfil(perfil)
        if perfil not in {"gestor", "administrador"}:
            raise SemPermissaoError("Somente gestor ou administrador edita demanda")
        titulo = _validar_titulo(titulo)
        with self.engine.begin() as conn:
            row = conn.execute(select(demandas).where(demandas.c.id == demanda_id)).mappings().first()
            if not row:
                raise NaoEncontradoError("Demanda não encontrada")
            if row["versao"] != versao:
                raise ConflitoVersaoError("Versão desatualizada")
            if row["status"] in {"resolvida", "cancelada"}:
                raise RegraNegocioError("Não é possível editar demanda encerrada")
            agora = utcnow()
            alteradas = conn.execute(update(demandas).where(
                demandas.c.id == demanda_id, demandas.c.versao == versao
            ).values(titulo=titulo, descricao=_limpar(descricao),
                tipo=_limpar(tipo, 120) or None, area_nome=_limpar(area_nome, 160) or None,
                prazo_em=normalizar_prazo(prazo_em), versao=versao + 1, atualizado_em=agora)).rowcount
            if alteradas != 1:
                raise ConflitoVersaoError("Versão desatualizada")
            self._evento(conn, demanda_id=demanda_id, tipo_evento="edicao", anterior=row["status"],
                         novo=row["status"], justificativa="Dados da demanda atualizados",
                         autor_id=str(ator), versao=versao + 1, agora=agora)
        return self.buscar(demanda_id)

    def historico_da_demanda(self, demanda_id):
        self.buscar(demanda_id)
        with self.engine.connect() as conn:
            rows = conn.execute(select(historico).where(historico.c.demanda_id == demanda_id)
                    .order_by(historico.c.ocorrido_em, historico.c.versao_nova)).mappings().all()
        return [_json(row) for row in rows]

    def kanban(self, *, limite_por_coluna=30):
        limite_por_coluna = max(1, min(int(limite_por_coluna), 50))
        resultado = {}
        with self.engine.connect() as conn:
            for status in STATUS:
                total = conn.execute(select(func.count()).select_from(demandas)
                                     .where(demandas.c.status == status)).scalar_one()
                rows = conn.execute(select(demandas).where(demandas.c.status == status)
                    .order_by(demandas.c.atualizado_em.desc(), demandas.c.id)
                    .limit(limite_por_coluna)).mappings().all()
                resultado[status] = {"total": total, "itens": [_json(r) for r in rows]}
        return resultado

    def listar(self, *, busca='', status='', pagina=1, por_pagina=20):
        busca = str(busca or '').strip()[:120]
        status = str(status or '').strip()
        if status and status not in STATUS:
            raise RegraNegocioError('Situação inválida')
        pagina = max(1, min(int(pagina), 10000))
        por_pagina = max(1, min(int(por_pagina), 50))
        filtros = []
        if status:
            filtros.append(demandas.c.status == status)
        if busca:
            filtros.append(or_(demandas.c.titulo.icontains(busca, autoescape=True),
                               demandas.c.area_nome.icontains(busca, autoescape=True),
                               demandas.c.tipo.icontains(busca, autoescape=True),
                               demandas.c.cluster_id.icontains(busca, autoescape=True)))
        with self.engine.connect() as conn:
            total = conn.execute(select(func.count()).select_from(demandas).where(*filtros)).scalar_one()
            registros = conn.execute(select(demandas).where(*filtros)
                                     .order_by(demandas.c.atualizado_em.desc(), demandas.c.id)
                                     .limit(por_pagina).offset((pagina - 1) * por_pagina)).mappings().all()
        return {'total': total, 'pagina': pagina, 'por_pagina': por_pagina,
                'paginas': max(1, (total + por_pagina - 1) // por_pagina),
                'itens': [_json(r) for r in registros]}

    def metricas(self):
        with self.engine.connect() as conn:
            linhas = conn.execute(select(demandas.c.status, func.count().label('total'))
                                  .group_by(demandas.c.status)).all()
            atrasadas = conn.execute(select(func.count()).select_from(demandas).where(
                demandas.c.status.in_(STATUS[:4]), demandas.c.prazo_em < utcnow()
            )).scalar_one()
        contagem = {nome: 0 for nome in STATUS}
        contagem.update({nome: total for nome, total in linhas})
        return {'por_status': contagem, 'total': sum(contagem.values()),
                'ativas': sum(contagem[s] for s in STATUS[:4]), 'atrasadas': atrasadas}
