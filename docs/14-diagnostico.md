# 14. Diagnóstico

O módulo de diagnóstico implementa o processo de consultoria da seção 3.7 do TCC (Quadro 9). O princípio que orienta todas as decisões é: **o sistema propõe e o consultor decide** (AMERSHI et al., 2019).

## 14.1 Etapas e status

| Etapa (Quadro 9) | Onde acontece no Mon | Status do diagnóstico |
|---|---|---|
| 1. Planejamento | Criação do diagnóstico: escopo e requisitos aplicáveis | `planejamento` |
| 2. Coleta | Módulo de documentos (upload ou pasta `data/sources/institucional/<tipo>/`) | — |
| 3. Indexação | Jobs de ingestão (extração, OCR, trechos, embeddings) | — |
| 4. Verificação assistida | Job `diagnostico_verificar` | `verificando` |
| 5. Validação | Tela de revisão: o consultor confirma ou corrige cada proposta | `em_validacao` → `validado` |
| 6. Priorização | Matriz GUT nos itens NC e PC | `priorizado` |
| 7. Relatório | Relatório consolidado | `relatorio_emitido` |
| 8. Devolutiva | Registro da apresentação à coordenação e ao NDE | `concluido` |

Se o job falhar antes de processar os itens (por exemplo, provedor sem chave), o status passa a `falhou` e a verificação pode ser reiniciada.

## 14.2 Planejamento

O escopo (`escopo`) define formato de oferta, próximo ato regulatório e sua data, tipos e grupos de requisito, códigos específicos, inclusão de normas em tramitação, validação cega e exibição do texto normativo. A partir dele e da versão do framework (a ativa, por padrão), o sistema seleciona os requisitos aplicáveis e grava em cada item uma **cópia do requisito**: alterações posteriores no framework não afetam o diagnóstico.

## 14.3 Verificação assistida

Para cada item pendente, `VerificacaoService` (`services/diagnostico/verificacao_service.py`):

1. recupera evidências na coleção institucional do curso ([13.5](13-framework-de-criterios.md#135-recuperação-de-evidências-por-requisito));
2. se nada foi recuperado, classifica como **EI sem consultar o LLM**;
3. caso contrário, monta o prompt (requisito, escopo e trechos numerados [n]) e pede uma proposta com **saída estruturada** (JSON Schema em `domain/diagnostico.py`): classificação, conceito INEP, justificativa, citações e lacunas;
4. aplica as regras de pós-validação:
   - citações fora de [1..n] são descartadas;
   - C, PC ou NC sem nenhuma citação válida é rebaixado para EI (a classificação original fica registrada);
   - conceito INEP só é mantido em requisitos do tipo qualidade;
5. grava o item com commit próprio. Se o worker for interrompido, o job é retomado e só processa os itens que ainda não têm proposta.

**Instrução de sistema:** `DIAGNOSTICO_PROMPT.md`, na raiz do projeto, montado no contêiner como o `SYSTEM_PROMPT.md` (adaptação "e" da seção 3.6.1). O hash SHA-256 da instrução usada fica registrado em cada execução.

**Saída estruturada por provedor:** a porta `LLMProvider` ganhou `generate_structured(prompt, system, schema, name)`. O adaptador do Gemini envia `response_json_schema`; o da OpenAI usa `json_schema` em modo estrito. Respostas inválidas são repetidas de imediato; falhas do provedor (cota, sobrecarga) são repetidas com espera exponencial (2 s, 4 s), até três tentativas. As chamadas têm timeout de 180 s. Persistindo a falha, o item fica com `proposta_status = erro`, a mensagem é guardada e o consultor pode reverificá-lo.

## 14.4 Validação

Na tela de revisão, o consultor vê o requisito, a proposta com justificativa e lacunas, os alertas das regras automáticas e as evidências (as citadas ficam destacadas, com link para o documento original). Ele registra:

- a classificação final (C, PC, NC, EI);
- o conceito de 1 a 5, nos requisitos de qualidade;
- a **causa da divergência**, obrigatória quando discorda da proposta: recuperação, OCR, divisão em trechos, geração ou interpretação normativa;
- um comentário.

A proposta **nunca é sobrescrita** (adaptação "d" da seção 3.6.1): os campos da decisão são separados dos da proposta. Itens validados não podem ser reverificados. Quando todos os itens estão validados, o diagnóstico passa a `validado`.

**Validação cega:** com essa opção no plano, a API omite a proposta e as pontuações das evidências até o consultor registrar sua classificação. Assim a decisão não é ancorada na sugestão do sistema, e o kappa mede concordância real (seção 3.8, nível 2).

## 14.5 Priorização GUT

Depois que todos os itens estão validados, os classificados como **NC** ou **PC** são priorizados pela matriz GUT (seção 3.5), com notas de 1 a 5 e prioridade igual ao produto G × U × T (`domain/gut.py`). O sistema sugere G e U; T e a decisão final são do consultor.

| Nota | Sugestão |
|---|---|
| G (gravidade) | A `gravidade_base` do requisito, quando definida. Sem ela: obrigação legal = 5; indicador de qualidade = 4 em dimensão de peso 40 e 3 nas demais; competência = 3. Itens PC recebem um ponto a menos que os NC |
| U (urgência) | Meses até o prazo mais próximo entre o `prazo_referencia` do requisito e a data do próximo ato informada no plano: até 6 meses (ou vencido) = 5; até 12 = 4; até 24 = 3; mais = 2. Sem prazo, não há sugestão |
| T (tendência) | Sem sugestão |

A ordem é G × U × T decrescente; empates são resolvidos por G, depois U, depois código. Quando todos os itens NC e PC têm prioridade, o diagnóstico passa a `priorizado`. Alterar a validação de um item priorizado limpa a GUT se ele deixar de ser NC ou PC e reabre a priorização se ele passar a ser.

## 14.6 Relatório

`services/diagnostico/relatorio.py` gera o relatório em Markdown:

1. **Identificação:** curso, formato de oferta, próximo ato, versão do framework, modelo e data da verificação, aviso sobre o caráter preliminar dos conceitos;
2. **Resumo:** contagem por classificação, por tipo de requisito e conceito médio estimado por dimensão do INEP;
3. **Prioridades:** tabela GUT;
4. **Achados por requisito:** classificação, conceito, prioridade, análise do consultor, fundamentação (ou a proposta do protótipo, quando corrigida pelo consultor), lacunas e evidências citadas com documento, página e trecho;
5. **Diligências:** requisitos com evidência insuficiente e o que pedir ao curso;
6. **Apêndice:** concordância entre protótipo e consultor.

A definição das ações corretivas fica fora do relatório, pois cabe à gestão do curso. Antes da emissão, `GET /relatorio` devolve uma prévia; a emissão (`POST /relatorio`) congela o conteúdo em `relatorio_md`, registra a data e bloqueia validação e priorização.

## 14.7 Reprodutibilidade

Cada execução da verificação registra em `diagnosticos.config.execucoes`: data, provedor e modelo do LLM, nível de raciocínio, parâmetros de recuperação e rerank, tamanho dos trechos, hash da instrução de sistema e um retrato da base institucional (id, nome, versão, hash e páginas com OCR de cada documento). O job usa o modelo registrado ao ser enfileirado, mesmo que a configuração mude no intervalo. Com isso se respondem às ameaças à validade da seção 3.8 (mudança de versão dos modelos dos provedores) e se preserva a cadeia de evidências (YIN, 2015).

## 14.8 Concordância

Ver [6.8](06-avaliacao.md#68-concordância-diagnóstica-nível-2-da-seção-38-do-tcc). A aba "Concordância" mostra percentual de acordo, κ de Cohen com interpretação, κ ponderado do conceito INEP, matriz de confusão, divergências por causa e acordo por tipo de requisito.

## 14.9 Arquitetura

| Camada | Arquivo |
|---|---|
| Regras (puras) | `domain/diagnostico.py` (escala, schema, pós-validação), `domain/concordancia.py` (métricas), `domain/gut.py` (priorização) |
| Casos de uso | `services/diagnostico/diagnostico_service.py`, `verificacao_service.py`, `prompt.py`, `relatorio.py` |
| Job | `workers/handlers.py` (`DiagnosticoVerificarHandler`) |
| Persistência | Tabelas `diagnosticos` e `diagnostico_itens` (`db/models.py`) |
| API | `api/routers/diagnosticos.py` |
| Interface | `frontend/src/app/features/diagnosticos/` (lista, criação e tela do diagnóstico) |
