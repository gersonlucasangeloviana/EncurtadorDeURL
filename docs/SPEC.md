# Especificação — Encurtador de URL

Atualizada em 07/11/2026. Os requisitos abaixo descrevem a versão atual. As pendências de aceite estão na seção 13 e os comandos de execução estão no [README](../README.md).

## 1. Produto, acesso e tecnologias

O login Google foi considerado, mas removido para facilitar o uso nos testes. O painel é aberto e todos compartilham os dados: qualquer visitante pode consultar e criar links, pastas e paths. Excluir exige senha de administrador; alterações estão desativadas. O redirecionamento também é público.

O backend usa Python e FastAPI. O painel usa React, Vite e Nginx. PostgreSQL guarda os dados operacionais e os eventos de acesso em JSONB. Redis guarda resoluções de links.

A composição da aplicação em `backend/app/main.py` conecta os adaptadores. A camada HTTP está em `backend/app/web.py`; as operações e suas interfaces estão em `backend/app/application/`. O domínio, em `backend/app/core.py` e `backend/app/domain.py`, é independente dos frameworks. Os adaptadores em `backend/app/infrastructure/` implementam as interfaces usadas pela aplicação. No painel, os componentes usam as funções de `frontend/src/api.js` para acessar a API.

A publicação prevista usa uma VPS gerenciada pelo Dokploy. Dockerfiles constroem as imagens e o Docker Compose descreve serviços, volumes e redes. O ambiente fornece domínios e conexões.

## 2. URLs públicas, nomes e pastas

São conceitos diferentes:

| Conceito | Exemplo | Unicidade e finalidade |
| --- | --- | --- |
| Destino | `https://empresa.com/oferta` | Único globalmente; até 250 caracteres |
| Nome/código final | `aB12xY9` ou `OfertaNatal` | Único globalmente, independentemente do path |
| Path público | `MinhaEmpresa` | Pré-cadastrado e exclusivo globalmente |
| Pasta/projeto | `Campanhas` | Organização compartilhada; nome único globalmente |

Formatos públicos:

- Sem path: `https://urlBase.com.br/aB12xY9` ou `https://urlBase.com.br/OfertaNatal`.
- Com path: `https://urlBase.com.br/MinhaEmpresa/aB12xY9` ou `https://urlBase.com.br/MinhaEmpresa/OfertaNatal`.

O path é um segmento antes do código, não um fragmento `#...`. Fragmentos após `#` não chegam ao backend. Uma pasta não cria automaticamente um path público, e ter path não exige pasta.

Um nome final ocupado não fica disponível por mudar de path. A regra é global: se `OfertaNatal` já existe, outro usuário não pode cadastrar `OutroPath/OfertaNatal`.

A comparação de códigos e paths distingue maiúsculas de minúsculas, inclusive na resolução. O nome da pasta é único conforme a representação armazenada. O cadastro remove espaços nas pontas e exige de 1 a 64 caracteres, sem caracteres de controle.

### 2.1. Cadastro

1. Validar e normalizar o destino, validar o nome personalizado quando fornecido e conferir a expiração quando preenchida.
2. Obter um ID da sequência PostgreSQL, inclusive para links com nome personalizado.
3. Usar o nome personalizado ou gerar o código com Feistel e Base62.
4. Inserir em transação. O banco verifica as referências de pasta e path, bem como a unicidade de código e destino.
5. Retornar o link público final sem preencher Redis.

Mensagens distintas para causas distintas:

- Nome/path ocupado: **“Não é possível cadastrar esse nome de encurtamento, escolha outro nome.”** Não identificar o proprietário.
- Destino repetido: **“Esta URL não pode ser encurtada porque já existe.”** Não identificar o proprietário.
- Destino acima do limite configurado: **“A URL deve ter no máximo 250 caracteres.”** A mensagem usa o limite vigente, de 250 caracteres por padrão.

Duplicidades de nome final, path e destino retornam `409`, com o identificador `short_name_unavailable`, `path_unavailable` ou `destination_already_exists` em `detail.code`. Pasta duplicada também retorna `409`. Entradas inválidas e referências a pasta ou path inexistentes retornam `422`. A API distingue conflitos pelas restrições informadas pelo banco. [Códigos de erro do PostgreSQL](https://www.postgresql.org/docs/current/errcodes-appendix.html)

Quando um nome personalizado ocupa um resultado futuro do Feistel, a geração automática usa outro ID e tenta novamente até o limite configurado. O esgotamento das tentativas ou da sequência retorna `503`.

## 3. Modelo operacional e índices

Decisão confirmada: `short_code`, o código público gerado pelo Feistel/Base62 ou nome personalizado escolhido, é a PK textual da tabela de links. A sequência numérica fica separada em `sequence_id`; `destination_url` é um campo com restrição `UNIQUE`. O path não faz parte da PK: o mesmo código não pode existir sob paths diferentes.

| Entidade | Campos e restrições |
| --- | --- |
| Pasta/projeto | `name VARCHAR(64)` como PK global |
| Path público | `path VARCHAR(64)` como PK global |
| Link | `short_code VARCHAR(64)` como PK global, `sequence_id BIGINT UNIQUE NOT NULL`, `destination_url VARCHAR(250) UNIQUE NOT NULL`, referências opcionais de pasta e path, `active`, `deleted`, `expires_at` e `version` |

Cada cadastro recebe seu número incremental, inclusive quando usa nome personalizado. O número alimenta o Feistel apenas na geração automática e nunca é reutilizado; lacunas por falhas, conflitos ou nomes manuais são esperadas. O código público é a identidade externa e a chave das consultas de resolução.

As referências opcionais à pasta e ao path usam chaves estrangeiras. A ausência é representada por `NULL`. Todos os registros são compartilhados.

`PRIMARY KEY` e `UNIQUE` já criam índices únicos no PostgreSQL. A listagem atual usa a sequência em ordem decrescente e omite registros excluídos. [Restrições PostgreSQL](https://www.postgresql.org/docs/current/ddl-constraints.html)

A PK textual evita usar o destino longo como identidade. A PK fornece um índice para a consulta sem determinar a ordem física da tabela. [PostgreSQL CLUSTER](https://www.postgresql.org/docs/current/sql-cluster.html)

O lookup de resolução usa diretamente `WHERE short_code = :code`, aproveitando o índice da PK, tanto para nomes personalizados quanto para códigos automáticos. Não é necessário reverter o Feistel. Em seguida, conferir path, estado e expiração. Não criar outro `UNIQUE` ou índice idêntico para `short_code`.

A API verifica o limite configurado antes e depois da normalização. O esquema impõe um teto de 250 caracteres. O PostgreSQL mede caracteres em `varchar(n)`. [Tipos textuais PostgreSQL](https://www.postgresql.org/docs/current/datatype-character.html)

## 4. Exclusão e expiração

O painel e a API oferecem criação, consulta e exclusão. Na criação pela API, `expires_at` é opcional. Se informado, deve representar uma data e hora futura com fuso horário e ser representável após a conversão para UTC. O painel exibe a expiração como estado da lista quando o link já expirou.

Excluir links, pastas e paths exige senha de administrador validada pela API. A exclusão lógica de um link preserva código e destino e incrementa sua versão. A exclusão de uma pasta ou um path referenciado retorna `409`, inclusive quando o link associado já foi excluído logicamente. Para pastas com caracteres especiais, o painel usa `DELETE /api/projects?name=<nome codificado>`. A API também aceita `DELETE /api/projects/{name}` para nomes que cabem em um segmento de URL.

## 5. Validação de destinos, nomes e configuração de domínio

HTTPS é obrigatório. Rejeitar HTTP e outros esquemas em vez de trocar silenciosamente para HTTPS. A validação vale na criação do destino.

### 5.1. Validações de destino

- Exigir URL absoluta com `https://`, hostname válido e tamanho máximo configurado, com padrão de 250 caracteres.
- Bloquear usuário/senha embutidos, como `https://usuario:senha@site.com`, incluindo entrada com usuário sem senha.
- Rejeitar espaços, controles, NUL, CR/LF e barras invertidas; verificar a entrada antes do parser, pois alguns parsers removem controles.
- Rejeitar escapes percentuais malformados e tentativas de inserir controles CR/LF codificados. Não decodificar o destino inteiro e depois usar o resultado como `Location`.
- Validar hostname, IPv4 e IPv6; rejeitar hostname vazio, colchetes inválidos, porta inválida e identificador de zona IPv6.
- Bloquear `localhost`, nomes locais/internos conhecidos, IPs privados, loopback, link-local, multicast, endereços não especificados e IPs não globais. Rejeitar representações numéricas ambíguas de IP.
- Por padrão, aceitar somente porta HTTPS 443 ou porta omitida; portas adicionais dependem de configuração explícita.
- Bloquear os domínios do próprio encurtador e os nomes internos dos serviços, evitando loops diretos. Comparar host exato ou subdomínio por limite de rótulo, nunca apenas procurar uma substring.
- Normalizar esquema e host usando UTS #46 em modo não transicional. Aplicar a mesma normalização aos hosts bloqueados, sem reordenar parâmetros nem remover UTM, path ou fragmento de destino. Revalidar tamanho após normalização/serialização.
- Manter path, query, ordem dos parâmetros, barra final e fragmento como parte do destino normalizado. Delimitadores vazios `?` e `#` são omitidos na serialização.
- Usar parâmetros SQL e escape normal do frontend; nunca interpolar URL/nome em SQL ou renderizar headers/URLs como HTML arbitrário.

A classificação de IPs literais usa `ipaddress` e verifica multicast e endereços reservados separadamente. [Python urllib.parse](https://docs.python.org/3/library/urllib.parse.html) e [Python ipaddress](https://docs.python.org/3.12/library/ipaddress.html)

A aplicação não acessará o destino para baixar HTML, gerar preview, seguir redirecionamentos ou testar sua disponibilidade. A resolução de link curto também não fará DNS externo nem HTTP para validar o destino; isso evita colocar essas chamadas na meta de 100 ms.

Bloquear IP literal privado e nomes conhecidos não prova que um domínio público continuará resolvendo para IP público. DNS rebinding e redirecionamentos externos permanecem limites dessa política. Se uma versão futura buscar destinos pelo servidor, deverá validar os IPs resolvidos e cada redirecionamento no momento da conexão. [OWASP SSRF](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)

### 5.2. Nomes finais e paths

Nomes personalizados e paths aceitam um segmento de caracteres ASCII alfanuméricos, hífen e sublinhado. O padrão é de 3 a 64 caracteres para nomes personalizados e de 1 a 64 para paths. `api`, `docs`, `redoc`, `health` e `openapi.json` são reservados pela aplicação. `RESERVED_ROUTE_NAMES` acrescenta nomes reservados, por padrão `auth`, `assets` e `admin`. A verificação de reserva ignora maiúsculas e minúsculas.

Path é pré-cadastrado pelo usuário e exclusivo globalmente. A criação do link apenas seleciona um path existente ou deixa o campo nulo. Um código globalmente único não deve permitir aceitar qualquer prefixo arbitrário: conferir o path solicitado contra o path registrado, usando também o valor em cache.

### 5.3. Domínios

`SHORT_BASE_URL` e `FRONTEND_BASE_URL` são origens HTTPS sem credenciais, prefixo de path, query ou fragmento. Os links públicos usam `SHORT_BASE_URL`. `ALLOWED_HOSTS` deve aceitar os dois domínios. O health check usa o host de `SHORT_BASE_URL`.

## 6. Acesso e proteção da API

O login Google foi planejado, mas removido para facilitar os testes. Não há contas, sessão ou propriedade individual; os dados e cadastros são públicos pelo painel; exclusões exigem a senha de administrador.

A API exige `X-API-Key` para `/api` e `/api/…`, com resposta `401` para chave ausente ou inválida. Requisições `DELETE` exigem também `X-Admin-Password`, com resposta `403` para senha ausente ou inválida. O Nginx substitui a chave enviada pelo cliente somente na porta do painel. O painel tem limite de 30 requisições por minuto por IP, com rajada de 20, e limite adicional de 5 exclusões por minuto, com rajada de 2. O domínio curto tem limite de 20 requisições por segundo por IP, com rajada de 50. Os limites globais são independentes. O painel admite 20 por segundo, com rajada de 60. O domínio curto admite 100 por segundo, com rajada de 100. Requisições acima dos limites recebem `429`. O Nginx usa dois buffers grandes de 4 KiB para cabeçalhos e aceita `X-Forwarded-For` para fins de identificação do cliente apenas do proxy configurado em `TRUSTED_PROXY_CIDR`.

## 7. Redis e redirecionamento

O cadastro não preenche o cache. A resolução consulta o Redis primeiro. Se a entrada estiver ausente ou malformada, consulta o PostgreSQL e tenta preencher o cache quando o link pode redirecionar. Quando o Redis está indisponível, o PostgreSQL ainda resolve o link e a aplicação devolve a resposta sem preencher o cache.

O TTL padrão é de 1.800 segundos. A entrada armazena destino, path esperado, expiração e versão. Seu prazo absoluto é o menor entre a expiração do link e a data de preenchimento mais o TTL configurado. A resolução também confere a expiração na leitura. [Comando SET do Redis](https://redis.io/docs/latest/commands/set/)

Excluir um link existente exige invalidar o Redis **antes** de confirmar a alteração no PostgreSQL. Um `DEL` remove a entrada e o marcador de preenchimento, aceitando chaves ausentes. Se a invalidação falhar, a exclusão retorna `503` sem gravar no banco. Se a gravação no PostgreSQL falhar, a aplicação tenta invalidar novamente e retorna `503` com orientação para conferir o estado antes de repetir.

Para coordenar processos, mutações e preenchimentos usam um bloqueio consultivo transacional do PostgreSQL por código. Após obter o bloqueio, o preenchimento registra no Redis um marcador aleatório antes de consultar o banco. A gravação da entrada só acontece se o marcador ainda existir e coincidir. A mesma operação atômica remove o marcador após gravar a entrada. Marcadores expiram em 5 segundos por padrão, e a invalidação também os remove para impedir que um preenchimento anterior volte a publicar dados antigos.

O protocolo coordena dois serviços independentes. O Compose configura um único Redis descartável, que reinicia sem restaurar snapshots e descarta chaves menos usadas ao atingir o limite padrão de 64 MB. A simulação local de perda da conexão antes e depois do `COMMIT` do PostgreSQL confirmou respostas `503` e consistência com o estado gravado no banco. Replicação e failover do Redis ficam fora do escopo.

O backend atende `GET` e `HEAD` nas rotas curtas e inclui `Cache-Control: no-store` nas respostas de resolução. O resultado é `302` com `Location` para um link ativo e válido, `404` para código inexistente, path divergente ou link pausado, e `410` para link excluído ou expirado com path correspondente. [HTTP](https://www.rfc-editor.org/rfc/rfc9110.html)

A gravação de eventos é tentada para os três resultados. Prévias, robôs e ferramentas podem aparecer nos dados. O status HTTP permite distinguir redirecionamentos de tentativas inválidas em análises futuras.

## 8. Meta de desempenho

Meta mantida: resolver o link e responder ao redirecionamento em menos de 100 ms. Referência inicial de carga: até 50 acessos simultâneos. A estimativa informada de 500 acessos simultâneos para a VPS não é uma medição desta aplicação.

Simultaneidade não define sozinha acessos por segundo, cauda de latência ou capacidade de disco. A implementação deverá medir cache preenchido, cache vazio e Redis indisponível. A gravação síncrona do evento no PostgreSQL integra o caminho da resposta e deve ser incluída na medição.

Ainda falta fixar percentil e fronteira de medição. Proposta: p99 abaixo de 100 ms entre chegada ao backend e resposta, sob 50 acessos simultâneos, sem incluir DNS, handshake TLS, rede do visitante ou carregamento do destino. Essa proposta não é uma garantia já comprovada.

## 9. Eventos e coleta de headers

Cada solicitação processada pela rota curta gera uma tentativa de gravação com `event_id`, `schema_version`, `timestamp` em UTC, `short_code` quando o código corresponde a um link, `requested_code`, `requested_path`, `method`, `status` e `headers`. O evento representa a requisição ao encurtador.

Guardar headers como lista de pares ou estrutura equivalente que preserve nomes repetidos; um mapa simples pode perder múltiplos valores. O backend só coleta o que recebe: headers removidos ou alterados pelo proxy não são recuperáveis. IP da conexão é metadado separado, não um header; só confiar em IP encaminhado por proxy conhecido.

**Decisão confirmada:** coletar os headers disponíveis, ocultando valores de credenciais. A sanitização ocorre antes de criar e gravar o evento no PostgreSQL; os valores originais não podem chegar à tabela ou aos logs. Preservar nome e ocorrências repetidas do header, substituindo somente seus valores pelo marcador configurado, com padrão `[REDACTED]`. [OWASP Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

Uma regra obrigatória identifica nomes que contêm `authorization`, `cookie`, `token`, `secret`, `credential`, `password` ou variações de `api-key`. Ela inclui `X-API-Key`, `X-Auth-Token`, `X-Access-Token` e `X-Admin-Password`. A comparação ignora maiúsculas e minúsculas e oculta todas as ocorrências. Use a lista ou a expressão regular configurável para incluir headers adicionais que transportem segredos.

A regra obrigatória se aplica mesmo com a lista e a expressão adicional vazias. A API valida a expressão na inicialização. O marcador é configurável e a sanitização afeta apenas a cópia analítica.

Não registrar o payload completo dos eventos nos logs operacionais. Os eventos ficam no PostgreSQL privado. A aplicação não adiciona body de requisição à coleta de headers. Não calcular geolocalização ou buscar dados externos durante o redirecionamento.

O limite do painel reduz requisições automatizadas; não há filtro de robôs na coleta de acessos.

## 10. Persistência dos eventos

A API insere diretamente cada evento em `access_events`, com uma chave numérica e um campo `payload JSONB` contendo o evento completo sanitizado. A tabela é criada na inicialização se não existir. Os dados são apenas armazenados nesta versão, sem relatórios.

A gravação usa uma transação própria e é síncrona. As gravações de eventos usam até quatro conexões separadas das operações de links, com espera de até 20 ms por uma conexão livre e limite de 100 ms por instrução no servidor. Se a gravação falhar, a API registra um aviso sem o payload e devolve o resultado da resolução. A cada 30 segundos, a API remove até 10.000 registros anteriores à janela dos `ANALYTICS_MAX_EVENTS` IDs mais recentes. A disponibilidade do PostgreSQL continua necessária para resolver cache vazio e gerenciar links. A meta de desempenho deve ser validada com a escrita e a limpeza ativas.

## 11. Configuração pelo ambiente

Parâmetros de implantação e negócio devem estar no `.env`, com nomes documentados e defaults no `.env.example`. Não hardcodar domínios, conexões, chave/alfabeto, TTL. Segredos reais não entram no repositório.

| Grupo | Variáveis e padrões |
| --- | --- |
| Domínios | `SHORT_BASE_URL`, `FRONTEND_BASE_URL`, `ALLOWED_HOSTS`, `TRUSTED_PROXY_CIDR` para o endereço ou CIDR dedicado do Traefik |
| Banco/cache | `POSTGRES_PASSWORD` no Compose, `DATABASE_URL` com a mesma senha, `REDIS_URL`, `REDIS_CACHE_TTL_SECONDS=1800`, `REDIS_FILL_TTL_SECONDS=5`, `REDIS_MAXMEMORY=64mb`, `REDIS_SOCKET_TIMEOUT_SECONDS=0.02`, `CACHE_KEY_PREFIX=shortener` |
| URL | `DESTINATION_MAX_LENGTH=250`, `ALLOWED_HTTPS_PORTS=443`, `BLOCKED_HOSTS`, `BLOCKED_HOST_SUFFIXES` |
| Nomes | `CUSTOM_NAME_MIN_LENGTH=3`, `CUSTOM_NAME_MAX_LENGTH=64`, `PUBLIC_PATH_MAX_LENGTH=64`, `RESERVED_ROUTE_NAMES=auth,assets,admin` para complementar as reservas internas |
| Algoritmo | `SHORT_CODE_KEY` com 32 bytes aleatórios em hexadecimal, `SHORT_CODE_BITS=40`, `FEISTEL_ROUNDS=8`, `ALPHABET=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ`, `SHORT_CODE_LENGTH=7`, `SHORT_CODE_GENERATION_MAX_ATTEMPTS=10`, `SHORT_CODE_ALGORITHM_VERSION=1` |
| Acesso à API | `API_KEY`, segredo de 32 bytes aleatórios em hexadecimal minúsculo, e `ADMIN_PASSWORD`, senha de exclusão com 16 a 128 caracteres ASCII visíveis |
| Captura | `ANALYTICS_REDACTED_HEADERS` e `ANALYTICS_REDACTED_HEADER_PATTERN` vazios por padrão, além de `ANALYTICS_REDACTION_MARKER=[REDACTED]` e `ANALYTICS_MAX_EVENTS=100000` |

Protocolos e algoritmos têm invariantes. Exigir HTTPS e 62 símbolos distintos no Base62, por exemplo, não são detalhes arbitrários que possam ser desativados por uma configuração incoerente. Validar combinações no startup e recusar falhas, em vez de gerar códigos corrompidos.

Na versão 1, Feistel divide os 40 bits em duas metades de 20 bits. A rodada usa BLAKE2b com chave, um byte para o índice da rodada e três bytes em ordem big-endian para a metade direita. Base62 codifica o resultado inteiro. Para 40 bits, `62^6 < 2^40 < 62^7`. O padrão é de sete caracteres e o limite é de 64.

A sequência não cicla nem reutiliza IDs; esgotamento gera falha explícita. A rede Feistel dá unicidade entre IDs distintos sob a mesma configuração, não entre configurações diferentes ou aliases arbitrários. [Feistel](https://crypto.stanford.edu/pbc/notes/crypto/prp.html)

Alterar chave, alfabeto, rounds ou largura exige compatibilidade com códigos já emitidos. Permitir configurar não significa permitir alterar livremente em produção: registrar versão/fingerprint da configuração e recusar uma mudança incompatível sem migração. Código de erro e invariantes de segurança continuam sendo parte do contrato da aplicação, não texto externo interpretado como código.

## 12. Publicação e limites de escopo

A rede externa `dokploy-network` deve existir antes de subir o Compose. O proxy Dokploy encaminha o domínio do painel a `frontend:80` e o domínio curto a `frontend:8080`. Apenas o serviço `frontend` participa dessa rede externa. API, PostgreSQL e Redis ficam na rede privada do projeto, sem publicação de portas. O Nginx resolve o endereço da API dinamicamente pelo DNS do Docker. O volume `postgres_data` preserva os dados do PostgreSQL. O Redis é descartável.

Na inicialização, a API cria tabelas ausentes e compara a impressão digital do gerador registrada no banco. Se detectar `links.owner_id`, interrompe a inicialização para que o esquema anterior seja migrado. Alterações em tabelas já existentes exigem migração separada.

Backups automatizados, alta disponibilidade, filtro de bots e relatórios ficam fora do escopo atual. [Dokploy](https://docs.dokploy.com/docs/core/docker-compose/domains)

## 13. Pendências remanescentes

1. **Publicação:** validar TLS, domínios, redes, volume e health checks no Dokploy.
2. **Aceite de desempenho:** fechar o percentil e a fronteira de medição, e testar os 100 ms com 50 acessos simultâneos no Dokploy.
3. **Evolução:** avaliar relatórios ou alterações futuras de URLs públicas.

## 14. Critérios de aceite

- Painel e redirecionamento públicos; API de gerenciamento exige chave interna e possui limite de requisições no painel. Exclusões exigem senha de administrador.
- URL somente HTTPS, dentro do limite configurado de até 250 caracteres, sem credenciais embutidas e com as validações da seção 5.
- Concorrência não permite duplicar destino, código/nome final ou path exclusivo; mensagens não revelam outro usuário.
- Código/nome público é a PK global; sequência numérica separada; resolução de nomes gerados e personalizados consulta a mesma PK.
- Pastas compartilhadas com nomes únicos; pasta/path opcionais e referências válidas.
- Cadastro não preenche o Redis. Com Redis disponível, o primeiro redirecionamento consulta o banco e preenche o cache. As próximas leituras usam a entrada enquanto estiver válida.
- Alterações são desativadas; exclusões exigem senha e invalidam o cache; expiração é verificada na resolução.
- Cada acesso GET ou HEAD resolvido pela rota pública tenta gravar um JSON sanitizado no PostgreSQL, inclusive para respostas 404 e 410.
- Falha de gravação do evento não altera a resposta da resolução e é observável sem expor headers sensíveis; não há garantia de recuperação do evento.
- Headers de credenciais, inclusive nomes com caixa diferente e ocorrências repetidas, têm valores ocultados antes de criar o evento analítico; demais headers são preservados. A proteção não modifica o fluxo original de redirecionamento.
- A aplicação valida os parâmetros externos e recusa mudanças incompatíveis na configuração do gerador.
- Medição de latência com 50 acessos simultâneos, incluindo cache vazio e Redis fora, antes de afirmar capacidade.
- Publicação Dokploy com volumes, redes, health checks e reinício verificados; backups e filtro de bots analítico permanecem fora do escopo inicial.
