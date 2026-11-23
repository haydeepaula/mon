# 12. Plano de expansão: framework de critérios e método de diagnóstico

Este documento planeja a evolução do Mon de um sistema genérico de consulta a documentos para o protótipo do **modelo de diagnóstico** descrito no TCC (seções 3.5 a 3.8). O artefato do TCC tem três partes, e o Mon original implementava apenas a terceira:

1. **Framework de critérios** (seção 3.5): requisitos normativos e de competências decompostos em itens verificáveis.
2. **Método de consultoria** (seção 3.7, Quadro 9): verificação assistida, validação pelo consultor, priorização GUT, relatório e devolutiva.
3. **Protótipo RAG** (seção 3.6): já existente.

Princípio que guia todas as decisões: **o sistema propõe e o consultor decide** (AMERSHI et al., 2019).

## 12.1 Contrato entre os dois módulos

| Elemento | Definição |
|---|---|
| `Requisito` | Chave `codigo` única dentro de uma versão do framework. Campos: grupo, fonte (documento e dispositivo), texto, tipo (`legal`, `qualidade`, `competencia`), dimensão e indicador INEP, evidência esperada, documentos prováveis, consulta padronizada, termos-chave, gravidade base, peso da dimensão, aplicabilidade, situação normativa (`vigente`, `tendencia`), `prazo_referencia`, status de validação. |
| `FrameworkRepository` | Porta com `listar(filtros)`, `obter(codigo, versao=None)`, `versao_ativa()`. |
| `EvidenceRetrievalService` | `recuperar(requisito_codigo, curso=None, top_n=None) -> list[Evidencia]` e `recuperar_detalhado(...)` para auditoria. |
| `Evidencia` | `documento`, `document_id`, `versao`, `sha256`, `pagina`, `trecho`, `score`, `chunk_id`, `ocr`, `colecao`, `tipo_documento`. |
| `curso` | Texto (slug), pois o Mon não tem entidade Curso. |
| Versão do framework | Tabela `framework_versoes`; versão validada é imutável; o diagnóstico registra a versão usada. |

## 12.2 Ordem de implementação

| # | Entrega | Seção do TCC | Situação |
|---|---|---|---|
| 1 | Coleções lógicas `normativa` e `institucional`: filtros na busca vetorial, campos `colecao`, `tipo_documento` e `curso` nos documentos, organização por subpasta em `data/sources/`, reclassificação sem reindexar | 3.6.1 a | concluída |
| 2 | Domínio e persistência do framework: `Requisito`, versões, seed do Quadro 6, importação e exportação JSON/CSV | 3.5, Quadro 6 | concluída |
| 3 | Recuperação de evidências por requisito (só institucional, normativo opcional) | 3.6.1 b | concluída |
| 4 | Diagnóstico: job de verificação com saída estruturada C/PC/NC/EI, regras de EI, validação do consultor, percentual de acordo e kappa de Cohen | 3.6.1 c/d/e; Quadro 9 etapas 4-5; 3.8 nível 2 | concluída |
| 5 | Priorização GUT com sugestões de G e U; relatório em Markdown | Quadro 9 etapas 6-7 | concluída |
| 6 | Tela do framework: edição e aprovação pelo orientador | 3.5 c | concluída |
| 7 | Avaliação por requisito: hit rate e MRR por requisito e por tipo | 3.8 nível 1 | concluída |
| 8 | DOCX, devolutiva, validação cega, comparação entre modelos | Quadro 9 etapa 8; ablação | concluída |

Os passos 1 a 4 formam o núcleo para o Projeto Final II: diagnóstico preliminar e medida de concordância.

## 12.3 Decisões de projeto

- **Coleções lógicas, não físicas.** A separação normativa/institucional é um campo `colecao` no payload de cada ponto do Qdrant, na mesma coleção física. As dimensões são iguais e o versionamento e a exclusão por `document_id` continuam valendo.
- **Migração leve.** O projeto não usa Alembic; tabelas novas são criadas por `create_all`. Colunas novas em tabelas existentes são adicionadas por `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` em `init_db.py`, sob o mesmo advisory lock.
- **Regras determinísticas do EI.** Sem evidência recuperada, o item é classificado como EI sem chamar o LLM. Classificação C, PC ou NC sem citação válida é rebaixada para EI. Ausência de evidência não é não conformidade.
- **Proposta preservada.** A classificação do LLM nunca é sobrescrita; a decisão do consultor fica em campos próprios, com causa obrigatória quando diverge (recuperação, OCR, chunking, geração, interpretação).
- **Validação cega opcional.** O consultor registra sua classificação antes de ver a proposta, reduzindo o viés de ancoragem que inflaria o kappa.
- **Reprodutibilidade.** Cada diagnóstico registra modelo, provedor, data, parâmetros de recuperação, hash do prompt, versão do framework e snapshot da base (id, versão e hash de cada documento).
- **Normas em tramitação** (ex.: minuta da quarta dimensão do INEP) ficam com `situacao_normativa = tendencia` e fora do diagnóstico por padrão.

## 12.4 Riscos

- A consulta padronizada usa vocabulário normativo e pode não encontrar a evidência nos documentos do curso. Mitigação: termos-chave e segunda busca restrita aos `documentos_provaveis`, medidas no passo 7.
- Suporte a saída estruturada varia entre provedores e modelos. Mitigação: validação com Pydantic e uma nova tentativa; persistindo o erro, o item fica marcado e a resposta bruta é guardada.
- Documentos da coleção institucional devem entrar anonimizados (LGPD, seção 3.4).
