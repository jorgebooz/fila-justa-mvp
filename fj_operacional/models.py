"""Metadados SQLAlchemy para testes e instalações novas.

Em produção, aplique a migração SQL explícita de migrations/ antes de subir o app.
"""
from sqlalchemy import (
    MetaData, Table, Column, Text, Integer, Float, DateTime, ForeignKey,
    CheckConstraint, Index, Boolean
)

metadata = MetaData(schema="operacional")

demandas = Table(
    "demandas", metadata,
    Column("id", Text, primary_key=True),
    Column("origem", Text, nullable=False),
    Column("cluster_id", Text, unique=True),
    Column("run_id_origem", Text),
    Column("titulo", Text, nullable=False),
    Column("descricao", Text, nullable=False),
    Column("tipo", Text),
    Column("area_nome", Text),
    Column("score_origem", Float),
    Column("status", Text, nullable=False),
    Column("prazo_em", DateTime(timezone=True)),
    Column("criado_por", Text, nullable=False),
    Column("criado_em", DateTime(timezone=True), nullable=False),
    Column("atualizado_em", DateTime(timezone=True), nullable=False),
    Column("versao", Integer, nullable=False),
    CheckConstraint("origem IN ('manual','gold')", name="origem_valida"),
    CheckConstraint("status IN ('nova','pendente','em_andamento','aguardando_validacao','resolvida','cancelada')", name="status_valido"),
    CheckConstraint("versao >= 1", name="versao_valida"),
)

historico = Table(
    "historico_status", metadata,
    Column("id", Text, primary_key=True),
    Column("demanda_id", Text, ForeignKey("operacional.demandas.id", ondelete="RESTRICT"), nullable=False),
    Column("tipo_evento", Text, nullable=False),
    Column("status_anterior", Text),
    Column("status_novo", Text, nullable=False),
    Column("justificativa", Text, nullable=False),
    Column("autor_id", Text, nullable=False),
    Column("ocorrido_em", DateTime(timezone=True), nullable=False),
    Column("versao_nova", Integer, nullable=False),
    CheckConstraint("tipo_evento IN ('criacao','transicao','edicao')", name="evento_valido"),
)
Index("idx_demandas_status", demandas.c.status, demandas.c.atualizado_em)
Index("idx_historico_demanda", historico.c.demanda_id, historico.c.ocorrido_em)

usuarios = Table(
    'usuarios', metadata,
    Column('id', Text, primary_key=True),
    Column('email', Text, nullable=False, unique=True),
    Column('nome', Text, nullable=False),
    Column('perfil', Text, nullable=False),
    Column('senha_hash', Text, nullable=False),
    Column('ativo', Boolean, nullable=False),
    Column('criado_em', DateTime(timezone=True), nullable=False),
    CheckConstraint("perfil IN ('operador','gestor','administrador')", name='perfil_valido'),
)
