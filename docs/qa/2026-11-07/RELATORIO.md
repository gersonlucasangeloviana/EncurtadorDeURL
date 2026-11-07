# Validação do app publicado — 07/11/2026

**Resultado: fluxos funcionais exercitados aprovados; aceite completo ainda pendente.** A publicação não contém as alterações locais de documentação da API. A medição externa não comprova a meta interna de 100 ms, e os critérios de infraestrutura precisam de verificação no Dokploy.

Ambiente: [painel](https://short.vianadev.work) e [domínio curto](https://apishort.vianadev.work). Execução aproximadamente entre 18:10 e 18:17, horário de São Paulo. Os testes usaram apenas registros próprios, identificados com `QA`, e as credenciais locais sem registrá-las nas evidências. Nenhum serviço foi reiniciado ou interrompido.

## Verificações aprovadas

| Área | Resultado observado |
| --- | --- |
| Testes locais | 27 testes automatizados aprovados; build de produção do frontend concluído |
| Publicação externa | Painel HTTP 200, health HTTP 200, certificados HTTPS verificados e HTTP redirecionado para HTTPS nos dois domínios |
| Acesso | API do domínio curto rejeitou chave ausente/incorreta com 401 e aceitou a chave válida; painel substituiu uma chave inválida pela chave interna |
| Cadastro | Links automáticos e personalizados, associação a pasta/path, listagem e criação de catálogos |
| Redirecionamento | GET e HEAD devolveram 302 com destino exato e `Cache-Control: no-store`; HEAD sem corpo |
| Resolução inválida | Código inexistente, path incorreto/omitido e diferença de caixa devolveram 404 |
| Validação | HTTP, localhost, loopback, credenciais embutidas, CR/LF codificado, porta não autorizada, destino longo e domínio do encurtador rejeitados com 422 |
| Referências | Nome reservado, pasta/path inexistente e expiração passada rejeitados com 422 |
| Duplicidades | Destino, código global, pasta e path duplicados rejeitados com 409 |
| Concorrência de cadastro | Três pedidos simultâneos iguais produziram um 201 e dois 409 |
| Edição | PATCH rejeitado com 405 |
| Exclusão | Senha ausente/incorreta rejeitada com 403; senha válida excluiu somente registros próprios; links excluídos devolveram 410 mesmo após redirecionamentos anteriores |
| Reserva após exclusão | Código e destino de link excluído permaneceram indisponíveis, com 409 |
| Catálogos | Pasta/path em uso bloqueados com 409; pasta com caracteres especiais e path sem vínculos foram criados e removidos |
| Expiração | Em ensaio com prazo controlado, link retornou 302 antes do prazo e 410 às 21:15:04 UTC, com `no-store` |
| Interface | Criação, mensagem de URL inválida, bloqueio de senha incorreta e cópia do link confirmada por colagem em campo; recarga e apresentação de registros |
| Tela pequena | Inspeção em 390 × 844: formulário, links e catálogos utilizáveis, sem transbordamento horizontal observado |

O primeiro teste de expiração esperava 410 antes de comprovar que o prazo já tinha transcorrido e recebeu 302. Esse resultado não foi tratado como defeito: a repetição controlada usou o relógio HTTP do servidor e confirmou a transição no prazo. Os dois resultados foram preservados nas evidências.

## Problemas confirmados na publicação

1. No painel, `/docs`, `/redoc` e `/openapi.json` devolvem o HTML do painel com status 200. O OpenAPI deveria ser JSON e as outras duas rotas deveriam abrir a documentação.
2. No domínio curto, a documentação abre, mas o esquema ainda tem título `FastAPI` e não contém os esquemas de segurança `ApiKey` e `AdminPassword`. A autenticação da API funciona; falta sua declaração no Swagger.

As correções correspondentes já estavam presentes em alterações locais de `frontend/nginx.conf` e `backend/app/web.py` antes desta validação. Os testes não modificaram essas alterações e não publicaram uma nova versão. É necessário republicá-las e repetir as quatro verificações de conteúdo/contrato que falharam.

## Rodada de 50 acessos simultâneos

Uma única rodada limitada de 50 GETs concorrentes foi enviada a um link de teste que já havia sido acessado. O cliente liberou as tarefas juntas, usou até 50 conexões e não seguiu o destino.

| Métrica externa | Resultado |
| --- | ---: |
| Respostas 302 com destino correto | 50/50 |
| Erros e respostas 429 | 0 |
| p50 | 375,65 ms |
| p95 | 430,32 ms |
| p99 / máximo | 641,74 ms |

Os tempos incluem agendamento no cliente, conexão, TLS, rede e proxy, além do processamento. A rodada usou um cliente novo, sem pré-aquecer suas conexões. Ela comprova o sucesso dessa rajada específica e não mede capacidade sustentada, p99 interno, cache frio ou Redis indisponível. Não foi inspecionado diretamente se cada resposta usou Redis ou PostgreSQL.

## Critérios ainda não encerrados

- Confirmar percentil e fronteira de medição da meta de 100 ms; a especificação propõe p99 dentro do backend.
- Medir no servidor 50 acessos simultâneos com cache preenchido, cache vazio e Redis indisponível, incluindo gravação e limpeza dos eventos. Requer ambiente controlado e acesso ao Dokploy/servidor.
- Inspecionar eventos persistidos e sanitização de credenciais em produção. Os testes locais cobrem a regra, mas não comprovam o conteúdo do banco publicado.
- Confirmar redes privadas, volume, health checks dos containers, persistência e recuperação após reinício. O health público comprova resposta HTTP da aplicação, não todos esses critérios.
- Validar os limites de requisições e a identificação de IP real atrás do proxy. A rodada de 50 não recebeu 429 e não foi um teste de saturação dos limites.
- Republicar e verificar as correções de documentação acima.

Não foram executados testes destrutivos de infraestrutura ou carga sustentada no ambiente em uso.

## Limpeza e rastreabilidade

Os quatro links da rodada principal e o link adicional de expiração foram excluídos. A consulta final não encontrou links ativos com prefixo `QA`. Códigos e destinos excluídos permanecem reservados por exclusão lógica.

Permaneceram `QA20261107211354 Pasta` e `QA20261107211354Path`: a aplicação bloqueia sua remoção com 409 porque continuam referenciados pelo link excluído logicamente. Não foi feita alteração direta no banco para contornar essa regra. Os catálogos sem vínculos usados em outros testes foram removidos.

Evidências:

- [Resultados HTTP e amostras da rodada concorrente](http-results.json)
- [Revalidação de expiração, documentação e limpeza](followup-results.json)
- [Captura final do painel](painel-final.png)

Os arquivos JSON conservam os resultados brutos, incluindo a tentativa prematura de expiração; a interpretação final está neste relatório. Nenhum segredo foi incluído.

## Investigação adicional de latência

Em resposta à avaliação de possíveis otimizações, foram feitas duas rodadas adicionais limitadas, cada uma com 50 GETs concorrentes para um novo link de teste previamente acessado. O mesmo cliente assíncrono manteve até 50 conexões, com três segundos entre as rodadas. Não houve alteração de código ou configuração da aplicação.

| Cenário | Novas conexões TCP observadas | Sucessos | p50 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Conexões novas | 50 | 50/50 | 383,35 ms | 537,28 ms | 1.536,75 ms |
| Conexões reutilizadas | 0 | 50/50 | 225,77 ms | 331,97 ms | 352,96 ms |

O rastreamento do cliente confirmou a reutilização na segunda rodada. Nas conexões novas, a mediana da fase de conexão TCP foi 56,45 ms e a mediana do TLS foi 91,64 ms; medianas de fases não devem ser somadas para reconstruir percentis totais. Dez pedidos sequenciais ao health, com conexão reutilizada, tiveram mediana de 33,76 ms e máximo de 39,40 ms. Esse cenário sequencial não pode ser subtraído dos percentis concorrentes para estimar tempo interno.

A comparação indica contribuição relevante do estabelecimento de conexões. Uma rodada por cenário não isola variação de rede, agendamento do cliente ou estado do servidor, e não comprova ganho de uma mudança na aplicação. O link adicional foi excluído com HTTP 200. [Amostras e rastreamento da comparação](latency-comparison.json).

Pontos candidatos identificados no código local:

1. A resposta de redirecionamento espera `record_event`, que faz um INSERT e COMMIT no PostgreSQL. Isso ocorre mesmo com acerto no Redis. O pool de eventos tem quatro conexões, sem overflow, e espera máxima configurada de 20 ms por conexão. Medir espera, escrita e falhas de gravação antes de dimensionar esse pool; uma resposta 302 não comprova que o evento foi gravado.
2. O container configura um processo Uvicorn, e a rota é síncrona. Avaliar filas de execução e eventual ajuste de concorrência/processos conforme os recursos da VPS, incluindo o aumento correspondente das conexões ao banco. Apenas mudar a função para `async` sem substituir as operações bloqueantes não resolve o problema.
3. Verificar versão e configuração efetiva do Nginx e a reutilização das conexões internas. O Dockerfile usa `nginx:alpine` sem fixar versão; defaults de keep-alive variam por versão. Não é possível inferir o comportamento publicado apenas da ausência de diretivas explícitas no arquivo local.
4. Se a gravação dos eventos for o custo dominante, considerar processamento fora da resposta e escrita em lote. Isso muda a decisão atual de gravação síncrona e requer definir durabilidade, capacidade da fila, tratamento de falhas e encerramento. O Redis atual é descartável e não deve ser tratado como fila durável sem mudança de arquitetura.

Prioridade sugerida: medir tempos internos por etapa e contagem de eventos perdidos, ajustar recursos e conexões com comparações repetidas e só então avaliar alteração na arquitetura de eventos.

## Inspeção direta da VPS pelo Termius

Inspeção realizada em 07/11/2026, aproximadamente às 18:25–18:32 de São Paulo, na sessão existente do Termius. Os números abaixo foram transcritos da saída observada no terminal. Nenhuma configuração ou serviço foi alterado ou reiniciado.

### Recursos e execução

- VPS com 8 CPUs disponíveis e 11.721 MiB de RAM total; 9.763 MiB disponíveis no momento da inspeção.
- Container da API sem limites explícitos de CPU e memória nos campos Docker consultados. Comando: `uvicorn app.main:app --host 0.0.0.0 --port 8000`, sem opção de múltiplos workers.
- Uso pontual observado: API 63,87 MiB; frontend 8,336 MiB; PostgreSQL 40,33 MiB; Redis 3,348 MiB. Esta observação não representa picos nem capacidade sob carga sustentada.
- Versões no container: Uvicorn 0.34.2, Starlette 0.46.2 e AnyIO 4.16.0. Uma execução separada dentro do container confirmou o limite padrão de 40 tokens para tarefas síncronas; não foi instrumentado o limitador do processo Uvicorn em execução.

### Conexões internas: reutilização confirmada

O frontend executa **Nginx 1.31.8**, com configuração sintaticamente válida, `worker_processes auto` e `worker_connections 1024`. A configuração não define explicitamente keep-alive para o upstream; nessa versão ele já é habilitado por padrão. Isso foi confirmado por comportamento, além da [documentação do Nginx](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#keepalive).

1. **Nginx → API:** 12 chamadas sequenciais a `/health`, feitas pelo serviço frontend na porta 8080, retornaram 200. A inspeção das conexões TCP estabelecidas na porta 8000 da API mostrou uma única conexão, com o mesmo par de endereços e inode em todas as amostras. A primeira chamada levou 9,840 ms; as demais, entre 1,984 e 3,127 ms.
2. **Traefik → Nginx:** 12 chamadas sequenciais a `/health` pela porta HTTPS local 443, preservando o hostname público/SNI e verificando o certificado TLS, retornaram 200. A porta 8080 do frontend manteve uma única conexão estabelecida, com a mesma identidade em todas as amostras. A primeira chamada levou 18,786 ms; as demais, entre 2,652 e 3,425 ms.

O teste usa o health para observar transporte e não mede o custo de consultar Redis ou gravar eventos. Não foi encontrada necessidade de habilitar keep-alive em nenhum dos dois trechos; não foi aplicado ajuste especulativo no proxy. A diferença entre conexões externas novas/reutilizadas das rodadas anteriores não prova falha de reutilização interna.

### Cinquenta redirecionamentos a partir da VPS

Um link próprio `QAInternal20261107212950` foi criado e acessado uma vez antes da medição. Um cliente Python executado no container da API usou 50 threads sincronizadas por barreira, cada uma abrindo uma conexão HTTP ao frontend na porta 8080. A medição inclui conexão interna, Nginx, API, Redis/banco e agendamento do cliente no mesmo host; exclui o Traefik, TLS e a rede externa. Não é instrumentação exclusiva do tempo dentro do backend.

| Métrica | Resultado |
| --- | ---: |
| Redirecionamentos 302 com destino correto | 50/50 |
| p50 | 170,615 ms |
| p95 | 249,659 ms |
| p99 / máximo | 261,025 ms |
| Eventos adicionais encontrados no banco para o código de teste | **36/50** |
| Avisos de evento não gravado nos logs da API nos últimos cinco minutos | **14** |

A contagem no banco foi feita antes e depois da rodada, filtrando o código exclusivo do teste, sem ler headers dos eventos. O aquecimento foi excluído da diferença. A consulta confirma 14 eventos ausentes nessa rodada; os 14 avisos observados na janela de logs são compatíveis com a perda. Os avisos atuais não identificam a causa da falha, portanto não é possível atribuí-la exclusivamente ao timeout do pool sem instrumentação adicional.

O link foi excluído ao final com HTTP 200. A rodada demonstra que o sucesso de 50 redirecionamentos não garante 50 eventos persistidos. Há custo relevante também no caminho interno; não é correto atribuir todo o p95 externo à rede.

### Consequência para a otimização

Priorizar a retirada da gravação individual síncrona do caminho da resposta, com fila limitada e gravação em lotes, acompanhando descarte, atraso e falhas. A escolha entre fila em memória e fila persistente depende da tolerância a perdas e ainda não foi implementada.

A concorrência pode ser ajustada no mesmo container: tornar o limite de threads configurável e avaliar dois processos Uvicorn são opções distintas de criar mais containers. Aumentar threads isoladamente pode apenas elevar a disputa pelas quatro conexões de eventos. Múltiplos processos também multiplicam pools, filas em memória e a tarefa atual de retenção; esses efeitos precisam ser dimensionados e coordenados.

Outra opção de código é migrar as operações de Redis e banco para clientes assíncronos, com limites de concorrência. Trocar somente `def` por `async def` mantendo chamadas bloqueantes não resolve essa espera. Os pontos de partida são a [documentação do limitador do Starlette](https://starlette.dev/threadpool/) e a [execução multiprocesso do Uvicorn](https://uvicorn.dev/deployment/).

Esta inspeção valida a reutilização de conexões e acrescenta uma medição interna com cache previamente acessado. Não encerra os cenários de cache frio, Redis indisponível, reinício/persistência nem o aceite de p99 abaixo de 100 ms.
