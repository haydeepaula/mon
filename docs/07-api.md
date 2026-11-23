# 7. API REST

Base: `/api`. Documentação interativa (OpenAPI/Swagger) em <http://localhost:8080/api/docs>.
Todas as rotas, exceto login e saúde, exigem `Authorization: Bearer <token>`. Rotas marcadas com **admin**
exigem o papel de administrador.

## Autenticação

| Método | Rota | Descrição |
|---|---|---|
| POST | `/auth/login` | Recebe `{username, password}` e devolve o token JWT e o usuário |
| GET | `/auth/me` | Dados do usuário autenticado |
| POST | `/auth/change-password` | Troca a senha (`current_password`, `new_password`) |

## Conversas e chat

| Método | Rota | Descrição |
|---|---|---|
| GET | `/conversations` | Conversas do usuário (mais recentes primeiro) |
| POST | `/conversations` | Cria conversa |
| PATCH | `/conversations/{id}` | Renomeia |
| DELETE | `/conversations/{id}` | Exclui conversa e mensagens |
| GET | `/conversations/{id}/messages` | Mensagens com fontes e detalhes |
| POST | `/conversations/{id}/messages` | Envia pergunta; resposta em **SSE** (`start`, `sources`, `delta`, `done`, `error`) |

## Documentos

| Método | Rota | Descrição |
|---|---|---|
| GET | `/documents?q=&status_filter=&colecao=` | Lista documentos, com filtro opcional por coleção (**admin**) |
| GET | `/documents/vocabulary` | Coleções lógicas e tipos de documento aceitos em cada uma (**admin**) |
| GET | `/documents/stats` | Totais por status, chunks, vetores e extensões suportadas (**admin**) |
| GET | `/documents/names` | Nomes dos arquivos (para a avaliação) (**admin**) |
| POST | `/documents/upload` | Upload multipart (`files`), um ou vários arquivos; campos opcionais `colecao`, `tipo_documento` e `curso` (**admin**) |
| PATCH | `/documents/{id}` | Reclassifica `colecao`, `tipo_documento` e `curso` sem reindexar (**admin**) |
| GET | `/documents/{id}` | Detalhes, incluindo relatório de extração (**admin**) |
| GET | `/documents/{id}/download` | Baixa o arquivo original (usuário autenticado) |
| POST | `/documents/{id}/reindex` | Agenda reindexação (**admin**) |
| DELETE | `/documents/{id}` | Remove documento, arquivo e vetores (**admin**) |

## Jobs (**admin**)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/jobs?status=&type=&limit=` | Lista jobs |
| GET | `/jobs/stats` | Quantidade por status |
| GET | `/jobs/{id}` | Detalhes com log |
| POST | `/jobs/sync-folder` | Agenda sincronização da pasta `data/sources` |
| POST | `/jobs/reindex-all` | Agenda reindexação de todos os documentos |
| POST | `/jobs/{id}/cancel` | Cancela job na fila |
| POST | `/jobs/{id}/retry` | Reexecuta job com falha ou cancelado |

## Administração de modelos e RAG (**admin**)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/admin/settings` | Configurações do RAG |
| PUT | `/admin/settings` | Atualização parcial (modelo, top-k, rerank, chunking, persona...) |
| GET | `/admin/providers` | Provedores e se têm chave configurada |
| GET | `/admin/models/{provider}` | Modelos disponíveis no provedor (`google` ou `openai`) |
| POST | `/admin/models/test` | Testa um modelo (`{provider, model}`) |
| GET | `/admin/api-keys` | Situação das chaves (`google`, `openai`, `cohere`): configurada, origem (interface, ambiente ou nenhuma) e máscara; nunca a chave completa |
| PUT | `/admin/api-keys/{provider}` | Cadastra ou troca a chave (`{api_key, testar}`); com `testar`, só grava se o provedor aceitar |
| DELETE | `/admin/api-keys/{provider}` | Remove a chave cadastrada; volta a valer a do `.env`, se houver |
| POST | `/admin/api-keys/{provider}/test` | Testa a chave informada (`{api_key}`) ou a chave atual |

## Avaliação (**admin**)

| Método | Rota | Descrição |
|---|---|---|
| GET / POST | `/evals/cases` | Lista / cria casos de teste |
| PUT / DELETE | `/evals/cases/{id}` | Edita / exclui caso |
| POST | `/evals/cases/import` | Importa casos em lote |
| POST | `/evals/cases/from-framework` | Cria um caso por requisito do framework (`{versao?, tipos?}`) |
| POST | `/evals/cases/generate` | Agenda geração de casos sintéticos (`{count}`) |
| GET / POST | `/evals/runs` | Lista / inicia execuções (`{name, case_ids, modo: chat\|requisito, curso}`) |
| GET / DELETE | `/evals/runs/{id}` | Detalhes com resultados / exclui |

## Framework de critérios (**admin**)

Ver [13. Framework de critérios](13-framework-de-criterios.md). O parâmetro `versao` é opcional; sem ele, vale a versão ativa.

| Método | Rota | Descrição |
|---|---|---|
| GET / POST | `/framework/versoes` | Lista versões (com totais de requisitos e aprovados) / cria versão vazia |
| PATCH / DELETE | `/framework/versoes/{id}` | Altera status, ativa, descrição, notas, data de corte / exclui rascunho |
| POST | `/framework/versoes/{id}/clonar` | Cria uma versão editável a partir de outra |
| GET | `/framework/requisitos?versao=&tipo=&grupo=&dimensao=&formato=&status_validacao=&incluir_tendencia=&q=` | Lista requisitos filtrados |
| POST | `/framework/requisitos?versao=` | Cria requisito |
| GET / PUT / DELETE | `/framework/requisitos/{codigo}?versao=` | Consulta / altera parcialmente / exclui |
| GET | `/framework/requisitos/{codigo}/evidencias?versao=&curso=&top_n=&incluir_normativa=` | Evidências candidatas na coleção institucional, com consulta usada, tempos e configuração |
| PATCH | `/framework/requisitos/{codigo}/validacao?versao=` | Revisão do orientador: `{status: pendente\|aprovado\|ajustar, comentario}` |
| POST | `/framework/importar` | Importa JSON `{versao, modo: mesclar\|substituir, requisitos: [...]}` |
| POST | `/framework/importar/csv` | Importa CSV (multipart: `file`, `versao`, `modo`) |
| GET | `/framework/exportar?versao=&formato=json\|csv` | Exporta a versão (apêndice do TCC) |

## Diagnóstico (**admin**)

Ver [14. Diagnóstico](14-diagnostico.md).

| Método | Rota | Descrição | Etapa (Quadro 9) |
|---|---|---|---|
| GET / POST | `/diagnosticos` | Lista / cria a partir do escopo e da versão do framework | 1 |
| POST | `/diagnosticos/requisitos-aplicaveis?versao=` | Prévia dos requisitos que entram com o escopo enviado | 1 |
| GET / PATCH / DELETE | `/diagnosticos/{id}` | Consulta / altera (escopo só no planejamento) / exclui | 1 |
| POST | `/diagnosticos/{id}/verificar` | Agenda a verificação assistida (`{item_ids?}`); retorna o job | 4 |
| GET | `/diagnosticos/{id}/itens`, `/diagnosticos/{id}/itens/{item}` | Itens com requisito, evidências e proposta (oculta na validação cega) | 4-5 |
| PUT | `/diagnosticos/{id}/itens/{item}/validacao` | `{classificacao_final, conceito_final, divergencia_causa, comentario}` | 5 |
| GET | `/diagnosticos/{id}/priorizacao` | Itens NC e PC em ordem de prioridade, com sugestões de G e U | 6 |
| PUT | `/diagnosticos/{id}/itens/{item}/gut` | `{g, u, t}` de 1 a 5 | 6 |
| POST | `/diagnosticos/{id}/relatorio` | Emite e congela o relatório | 7 |
| GET | `/diagnosticos/{id}/relatorio?formato=md\|docx&download=` | Relatório em Markdown ou DOCX (emitido ou prévia) | 7 |
| POST | `/diagnosticos/{id}/devolutiva` | `{data, participantes, resultado: aceito\|revisado, observacoes}` | 8 |
| POST | `/diagnosticos/{id}/clonar` | Mesmo escopo com outro LLM (`{nome, llm_provider, llm_model, reasoning_level}`) | 3.8 |
| GET | `/diagnosticos/{id}/metricas?referencia=` | Concordância: acordo, κ, matriz de confusão, causas | 3.8, nível 2 |

## Saúde

| Método | Rota | Descrição |
|---|---|---|
| GET | `/health` | Estado do banco, do Qdrant e das chaves de API |
