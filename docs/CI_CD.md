# CI/CD do Fila Justa — auditoria e implantação controlada

## Diagnóstico confirmado

No repositório **jorgebooz/fila-justa-mvp**, o único workflow original era `.github/workflows/ci.yml`. Não havia workflow de deploy.

Execuções anteriores, incluindo as verificações dos PRs #1 e #2, retornaram jobs com `runner_id=0`, `runner_name=""` e `steps=[]`, encerrando em poucos segundos. **O Python não chegou a rodar**. Isso é compatível com bloqueio de GitHub Actions na conta, política de execução, faturamento ou indisponibilidade de runner. Ainda não é possível apontar a causa exata.

As versões `actions/checkout@v7` e `actions/setup-python@v7` estão publicadas e não explicam sozinhas a falha.

## CI automático

O workflow `ci.yml` inicia com um job mínimo (`diagnostico-runner`), sem checkout, dependências ou segredos. Em seguida, o job `testes` instala `requirements-dev.txt`, verifica dependências, compila Python e executa todos os testes `pytest`.

Disparos: PR para `main`, push em `main` e manualmente pelo GitHub Actions.

Se o primeiro job falhar **sem chegar ao primeiro passo**, abrir:
- **Actions → CI - Fila Justa → execução recente**: conferir mensagem no cabeçalho.
- **Settings → Actions → General**: confirmar Actions e ações externas permitidas.
- **Settings pessoais → Billing & licensing → Budgets**: conferir bloqueios, limites e avisos de cobrança. Não precisa aumentar limites só para investigar.
- **https://www.githubstatus.com/**: conferir incidentes.
- Se necessário, abrir suporte GitHub com run ID, `runner_id=0` e `steps=[]`.

Se o diagnóstico passar e `testes` falhar, analisar o passo vermelho (instalação, compilação ou `pytest`).

## CD Azure — desativado por padrão

O novo `deploy-azure.yml` permite execução manual em `main`. Em `push main`, ele **não publica nada** até que a variável de repositório `FJ_AUTO_DEPLOY` seja exatamente `true`. Nenhum segredo de produção é usado em PR.

Antes do deploy, o próprio CD instala as dependências e passa os testes. Em seguida, usa login Azure via OpenID Connect, sem publish profile, publica com `azure/webapps-deploy@v3` e verifica a rota `/health`.

### Configurações necessárias

1. Em **Settings → Environments**, criar ambiente `production`, de preferência com aprovação obrigatória.
2. Em **Settings → Secrets and variables → Actions → Variables**, criar `AZURE_WEBAPP_NAME` com o nome **real** do App Service. Por enquanto, deixar `FJ_AUTO_DEPLOY` ausente ou `false`.
3. Em **Secrets** do repositório ou ambiente `production`, criar `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` e `AZURE_SUBSCRIPTION_ID`. Não publicar valores no código.
4. No Microsoft Entra/Azure, criar credencial OIDC federada para a identidade de deploy com `issuer=https://token.actions.githubusercontent.com`, `audience=api://AzureADTokenExchange` e **subject** `repo:jorgebooz/fila-justa-mvp:environment:production`; conceder acesso mínimo ao App Service.
5. No Azure App Service, confirmar runtime Python, comando de inicialização Flask e `SCM_DO_BUILD_DURING_DEPLOYMENT=true` se o deploy publicar código-fonte.

### Atenção aos dois bancos

O workflow **não executa migrações** nem modifica o PostgreSQL. O app público consulta `gold` com o usuário somente leitura. A gestão operacional precisa de conexão separada e schema `operacional` já migrado e testado.

O `/health` atual consulta o banco; se a rede Azure → PostgreSQL continuar falhando, o pós-deploy responderá 503 mesmo após um upload bem-sucedido. Tratar saúde e disponibilidade do banco separadamente da autenticação do deploy.

### Ativação

1. Validar CI verde e o app no PostgreSQL de testes.
2. Configurar ambiente, variáveis, secrets e identidade OIDC.
3. Executar manualmente **Actions → CD - Azure App Service → Run workflow** na `main`.
4. Confirmar deploy e resposta HTTP 200 em `/health`.
5. Só então definir `FJ_AUTO_DEPLOY=true` para publicar automaticamente em futuros pushes em `main`.

## Referências

- https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository
- https://learn.microsoft.com/en-us/azure/app-service/deploy-github-actions?tabs=openid
- https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect
