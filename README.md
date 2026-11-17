# Fila Justa — Ficha Técnica do MVP

**Nome:** Fila Justa | **Área:** gestão urbana e priorização territorial | **Cidade inicial:** São Paulo (SP).

**Problema:** demandas urbanas excedem a capacidade de atendimento. **Proposta:** oferecer uma fila de priorização justa, explicável e sensível ao clima e um fluxo separado de gestão das ocorrências selecionadas.

## Arquitetura

- **Big Data:** pipeline Airflow e PostgreSQL com camadas Bronze, Silver e Gold. Snapshot `gold` disponível para consulta no Azure.
- **Camada pública:** aplicativo Flask lê `gold.mart_fila_priorizacao` com usuário `app_reader` somente leitura; exibe as primeiras 30 prioridades.
- **Camada operacional (Fila Justa 2.0):** schema PostgreSQL `operacional`, autenticação de usuários, gestão de demandas com histórico de mudanças e vínculo opcional por `cluster_id`.
- **CI/CD:** GitHub Actions. A aprovação e a publicação em Azure são passos controlados após testes e migração.

**Fontes analíticas:** SP156, IBGE Censo 2022, Open-Meteo e relatos simulados. **ODS:** 9, 10, 11 e 13. **Natureza:** protótipo acadêmico, não oficial da Prefeitura.

## Funcionalidades

A parte pública permanece acessível em `/`. A gestão operacional é habilitada **somente** quando os dois valores `OPERATIONAL_DATABASE_URL` e `FJ_SESSION_SECRET` estão configurados, e após executar as migrações em um banco de testes:

| Tela | Função |
|---|---|
| `/login` | Autenticação de operador, gestor ou administrador |
| `/gestao/demandas` | Lista de demandas com busca, filtro e paginação |
| `/gestao/kanban` | Quadro de seis estados, abrir/editar, arrastar cartão, visualizar histórico |
| `/gestao/dashboard` | Métricas operacionais (demandas, ativas, vencidas, resolvidas) |
| `/` | Fila analítica pública — não cria automaticamente ordens de serviço |

**Estados:** `nova → pendente → em_andamento → aguardando_validacao → resolvida`. Há também `cancelada`. **Situação de prazo** (`em_dia`, `proximo_vencimento`, `atrasada`, `sem_prazo`, `encerrada`) não é estado do workflow. Gestor/administrador validam conclusões. Cada mudança registra autor, horário, versão e justificativa. Alterações concorrentes retornam HTTP 409.

A importação de um `cluster_id` Gold é idempotente: atualizar o pipeline não altera a situação operacional já registrada. O módulo GenAI está em repositório separado e **não foi acoplado** a esta alteração.

## Configurar localmente (antes de Azure)

Python 3.12 recomendado. Em Git Bash no Windows:

```bash
py -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Configure a leitura Gold como anteriormente (`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` e, opcionalmente, `DB_PORT`). O servidor exige conexão SSL.

Para ativar a operação, **não use** `app_reader` como identidade de escrita. No PostgreSQL de testes, com conta administradora de migração e backup feito:

```bash
psql "$OPERATIONAL_MIGRATION_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f migrations/001_operacional.sql
psql "$OPERATIONAL_MIGRATION_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f migrations/002_usuarios.sql
```

Crie um usuário PostgreSQL novo para o app, com os grants mínimos em SQL (executar como admin, depois da criação do papel):

```sql
GRANT USAGE ON SCHEMA operacional TO app_operador;
GRANT SELECT, INSERT, UPDATE ON operacional.demandas TO app_operador;
GRANT SELECT, INSERT ON operacional.historico_status TO app_operador;
GRANT SELECT ON operacional.usuarios TO app_operador;
GRANT USAGE ON SCHEMA gold TO app_operador;
GRANT SELECT ON gold.mart_fila_priorizacao TO app_operador;
```

Configure localmente, **fora do Git**:

- `OPERATIONAL_DATABASE_URL`: `postgresql+psycopg://app_operador:<SENHA>@<HOST>:5432/<BANCO>?sslmode=require`.
- `FJ_SESSION_SECRET`: valor aleatório com pelo menos 32 caracteres, diferente das credenciais do banco.
- `OPERATIONAL_MIGRATION_DATABASE_URL`: conexão temporária de provisionamento, não configurar no Azure App Service.
- `FJ_LOCAL_HTTP=1`: somente para desenvolvimento em `http://localhost`; **não configurar em produção**, onde cookies de sessão exigem HTTPS.

Crie a primeira conta com uma senha forte solicitada interativamente, sem guardar no terminal nem no Git:

```bash
python -m fj_operacional.admin --email gestor@exemplo.org --nome "Gestor de teste" --perfil gestor
flask --app app run
```

**Importante:** a identidade de provisionamento exige INSERT/UPDATE em `operacional.usuarios`. O usuário do site em execução tem apenas SELECT nessa tabela. Nunca usar a identidade de migração no servidor web.

## Verificação antes de publicar

1. Testes unitários, HTTP e de regressão aprovados.
2. PostgreSQL de testes com as duas migrações aplicadas; `app_operador` não altera a Gold.
3. Login, logout, bloqueio de convidados e CSRF verificados.
4. Gestor cria/importa, operador executa, gestor conclui, histórico e HTTP 409 conferidos.
5. Filtragem, paginação, dashboard e Kanban operando com dados reais de teste.
6. Avaliar CI e deploy Azure separadamente, sem publicar automaticamente enquanto houver teste vermelho.

**Limitações:** perfis internos são provisionados por CLI; não há cadastro aberto, notificações ou upload de anexos. O protótipo não inclui integração efetiva ao repositório GenAI e não se apresenta como serviço oficial.
