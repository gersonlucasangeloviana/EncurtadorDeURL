# Migração assíncrona do backend — 07/11/2026

Implementada e validada no repositório local. Não publicada na VPS.

## Alterações

- Todas as rotas do backend usam `async def`.
- Operações de links, pastas, paths, resolução e eventos aguardam os adaptadores com `await`.
- PostgreSQL usa `create_async_engine`, `async_sessionmaker` e psycopg 3 assíncrono. Cada operação tem sua própria sessão.
- Redis usa `redis.asyncio`, incluindo leitura, preenchimento, publicação Lua e invalidação.
- Bloqueios transacionais, commit, rollback, retenção e inicialização do esquema usam entrada/saída assíncrona.
- A inspeção e a criação de metadados usam `AsyncConnection.run_sync`, a adaptação fornecida pelo SQLAlchemy para essas APIs.
- Pools e cliente Redis são encerrados de forma assíncrona, inclusive quando a inicialização falha.
- Validações, serialização, geração de códigos e outras funções sem entrada/saída continuam sendo funções comuns.
- A dependência SQLAlchemy passa a solicitar o extra `asyncio`, garantindo a instalação de greenlet nas plataformas suportadas.

O contrato HTTP, o formato da URL de conexão, as tabelas e as regras de invalidação foram preservados. Esta alteração não adiciona fila, processamento em lotes, novos workers ou novos containers na aplicação de produção. A tentativa de gravar cada acesso ainda é aguardada antes da resposta.

## Validação

| Verificação | Resultado |
| --- | --- |
| Compilação de sintaxe Python | Aprovada |
| Testes unitários com as dependências declaradas, em Docker | 30 aprovados |
| Testes com PostgreSQL 16 e Redis 7 reais, em rede isolada | 7 aprovados |
| Build da imagem de produção do backend | Aprovado |
| Inicialização da imagem de produção com Uvicorn | Aprovada |
| Fluxo HTTP real: health, criação, redirecionamento e exclusão | Aprovado |
| Cinquenta HEADs simultâneos para um link ativo | 50 respostas 302, sem corpo |
| Consulta após exclusão | 410 |
| Encerramento da API | `Application shutdown complete`, sem traceback |
| Verificação de whitespace do diff | Aprovada |

Os testes verificam também 50 leituras pendentes no cache sem bloquear o health, espera assíncrona de eventos, propagação de cancelamento, duplicidades concorrentes, referências inexistentes, sanitização, expiração, Redis indisponível, retenção, recusa de esquema legado/fingerprint incompatível e corrida entre preenchimento do cache e exclusão. O cancelamento de uma operação libera o bloqueio transacional e permite reutilizar o pool.

Para reproduzir a suíte isolada:

```sh
docker compose -p shortener-async-qa -f backend/tests/compose.yml up --build --abort-on-container-exit --exit-code-from tests
docker compose -p shortener-async-qa -f backend/tests/compose.yml down -v
```

## Limitação confirmada: persistência de eventos sob concorrência

O teste HTTP da imagem de produção gerou 52 tentativas de registro: um GET de aquecimento, 50 HEADs concorrentes e um GET após exclusão. Foram encontrados 46 eventos no banco (45 com status 302 e um com 410) e seis avisos de evento não gravado nos logs. Não houve traceback nem falha no redirecionamento.

Esse resultado confirma que a migração para async não elimina a possibilidade de perda do registro de acessos: permanecem o pool de quatro conexões, a espera de 20 ms por conexão e a política atual de responder mesmo se a gravação falhar. O aviso atual não discrimina a causa específica de cada falha. Uma fila com gravação em lotes, discutida anteriormente, é uma mudança separada e ainda não foi implementada.

Não foi feita comparação controlada de latência antes/depois nesta etapa. O teste local não permite afirmar redução de p95 em produção. Os containers temporários foram removidos; nenhum serviço da VPS foi alterado.
