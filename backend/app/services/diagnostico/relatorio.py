"""Etapa 7 do Quadro 9: relatório de diagnóstico em Markdown.

O relatório consolida achados, evidências e prioridades. A definição das ações corretivas
fica a cargo da gestão do curso e não faz parte do relatório (TCC, seção 3.5).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from app.db.models import Diagnostico, DiagnosticoItem
from app.domain.diagnostico import ROTULOS_CLASSIFICACAO, Classificacao
from app.domain.gut import chave_ranking, priorizavel

ROTULO_TIPO = {"legal": "Obrigação legal", "qualidade": "Indicador de qualidade (INEP)", "competencia": "Competência da Indústria 4.0"}
ROTULO_ATO = {"autorizacao": "autorização", "reconhecimento": "reconhecimento", "renovacao": "renovação de reconhecimento", "outro": "outro"}
ORDEM_CLASSIFICACAO = {"NC": 0, "PC": 1, "EI": 2, "C": 3}
TRECHO_MAX = 400


def _esc(texto: Any) -> str:
    """Escapa o separador de colunas das tabelas Markdown."""
    return str(texto or "").replace("|", "\\|").replace("\n", " ").strip()


def _data(valor: Any) -> str:
    if not valor:
        return "—"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y")
    try:
        return datetime.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except ValueError:
        return str(valor)


def _rotulo(classificacao: str | None) -> str:
    if not classificacao:
        return "não validado"
    return f"{classificacao} — {ROTULOS_CLASSIFICACAO[Classificacao(classificacao)]}"


def _evidencias_citadas(item: DiagnosticoItem) -> list[dict]:
    evidencias = item.evidencias or []
    citacoes = set((item.proposta or {}).get("citacoes") or [])
    citadas = [e for e in evidencias if e.get("n") in citacoes]
    return citadas or evidencias[:2]


def _priorizados(itens: list[DiagnosticoItem]) -> list[DiagnosticoItem]:
    alvo = [i for i in itens if priorizavel(i.classificacao_final)]
    return sorted(alvo, key=lambda i: chave_ranking(i.prioridade, i.gut_g, i.gut_u, i.requisito_codigo))


def gerar_relatorio(
    diagnostico: Diagnostico, emitido_em: datetime | None = None, incluir_concordancia: bool = True
) -> str:
    itens = list(diagnostico.itens)
    escopo = diagnostico.escopo or {}
    execucao = (diagnostico.config or {}).get("ultima_execucao") or {}
    linhas: list[str] = []
    add = linhas.append

    titulo = diagnostico.curso_nome or diagnostico.curso or "curso"
    add(f"# Relatório de diagnóstico — {titulo}")
    add("")
    if emitido_em is None:
        add("> **Prévia.** Este relatório ainda não foi emitido; o conteúdo pode mudar.")
        add("")

    # 1. Identificação
    add("## 1. Identificação")
    add("")
    add(f"- **Diagnóstico:** {diagnostico.nome}")
    add(f"- **Curso:** {titulo}")
    if escopo.get("formato_oferta"):
        add(f"- **Formato de oferta:** {escopo['formato_oferta']}")
    if escopo.get("proximo_ato"):
        ato = ROTULO_ATO.get(escopo["proximo_ato"], escopo["proximo_ato"])
        if escopo.get("data_ato"):
            ato += " (previsto para " + _data(escopo["data_ato"]) + ")"
        add(f"- **Próximo ato regulatório:** {ato}")
    add(f"- **Framework de critérios:** versão {diagnostico.framework_versao} ({(diagnostico.config or {}).get('framework_status', '—')})")
    if execucao:
        add(f"- **Verificação assistida:** {execucao.get('llm_provider')}/{execucao.get('llm_model')}, em {_data(execucao.get('executado_em'))}")
    add(f"- **Emissão:** {_data(emitido_em) if emitido_em else 'prévia'}")
    if escopo.get("observacoes"):
        add(f"- **Observações do plano:** {escopo['observacoes']}")
    add("")
    add(
        "As classificações foram propostas por um protótipo baseado em geração aumentada por recuperação (RAG), "
        "a partir dos documentos institucionais do curso, e validadas pelo consultor responsável. "
        "Os conceitos de 1 a 5 são estimativas preliminares e não substituem a avaliação oficial do INEP."
    )
    add("")

    # 2. Resumo
    add("## 2. Resumo")
    add("")
    contagem = Counter(i.classificacao_final for i in itens if i.classificacao_final)
    add("| Classificação | Requisitos |")
    add("|---|---:|")
    for c in Classificacao:
        add(f"| {_rotulo(c.value)} | {contagem.get(c.value, 0)} |")
    pendentes = sum(1 for i in itens if not i.classificacao_final)
    if pendentes:
        add(f"| Não validados | {pendentes} |")
    add(f"| **Total** | **{len(itens)}** |")
    add("")

    por_tipo: dict[str, Counter] = {}
    for item in itens:
        tipo = (item.requisito or {}).get("tipo", "outro")
        por_tipo.setdefault(tipo, Counter())[item.classificacao_final or "—"] += 1
    add("| Tipo de requisito | C | PC | NC | EI |")
    add("|---|---:|---:|---:|---:|")
    for tipo, cont in sorted(por_tipo.items()):
        add(f"| {ROTULO_TIPO.get(tipo, tipo)} | {cont['C']} | {cont['PC']} | {cont['NC']} | {cont['EI']} |")
    add("")

    dimensoes: dict[int, list[int]] = {}
    for item in itens:
        dim = (item.requisito or {}).get("dimensao_inep")
        if dim and item.conceito_final:
            dimensoes.setdefault(int(dim), []).append(item.conceito_final)
    if dimensoes:
        add("| Dimensão do instrumento INEP | Indicadores | Conceito médio estimado |")
        add("|---|---:|---:|")
        for dim, conceitos in sorted(dimensoes.items()):
            add(f"| Dimensão {dim} | {len(conceitos)} | {sum(conceitos) / len(conceitos):.1f} |")
        add("")

    # 3. Prioridades
    add("## 3. Prioridades (matriz GUT)")
    add("")
    priorizados = _priorizados(itens)
    if priorizados:
        add("Itens não conformes (NC) e parcialmente conformes (PC), ordenados pelo produto Gravidade × Urgência × Tendência.")
        add("")
        add("| # | Requisito | Classificação | G | U | T | G×U×T |")
        add("|---:|---|---|---:|---:|---:|---:|")
        for posicao, item in enumerate(priorizados, start=1):
            texto = _esc((item.requisito or {}).get("texto"))
            add(
                f"| {posicao} | **{item.requisito_codigo}** — {texto} | {item.classificacao_final} | "
                f"{item.gut_g or '—'} | {item.gut_u or '—'} | {item.gut_t or '—'} | {item.prioridade or '—'} |"
            )
        add("")
        add("A definição das ações corretivas cabe à gestão do curso (coordenação, NDE e colegiado).")
    else:
        add("Nenhum requisito foi classificado como não conforme ou parcialmente conforme.")
    add("")

    # 4. Achados
    add("## 4. Achados por requisito")
    add("")
    posicao_gut = {i.id: n for n, i in enumerate(priorizados, start=1)}
    ordenados = sorted(
        itens,
        key=lambda i: (ORDEM_CLASSIFICACAO.get(i.classificacao_final or "", 4), posicao_gut.get(i.id, 999), i.ordem),
    )
    for item in ordenados:
        req = item.requisito or {}
        add(f"### {item.requisito_codigo} — {req.get('texto', '')}")
        add("")
        fonte = req.get("fonte_documento", "")
        if req.get("fonte_dispositivo"):
            fonte += f", {req['fonte_dispositivo']}"
        add(f"- **Fonte:** {fonte}")
        add(f"- **Tipo:** {ROTULO_TIPO.get(req.get('tipo'), req.get('tipo'))}")
        add(f"- **Classificação:** {_rotulo(item.classificacao_final)}")
        if item.conceito_final:
            add(f"- **Conceito estimado:** {item.conceito_final}")
        if item.id in posicao_gut:
            add(f"- **Prioridade:** {posicao_gut[item.id]}º (G×U×T = {item.prioridade or '—'})")
        add(f"- **Evidência esperada:** {req.get('evidencia_esperada', '')}")
        add("")
        if item.comentario:
            add(f"**Análise do consultor:** {item.comentario}")
            add("")
        proposta = item.proposta or {}
        if proposta.get("justificativa"):
            concordou = item.classificacao_final == item.classificacao_proposta
            rotulo = "Fundamentação" if concordou else f"Proposta do protótipo ({item.classificacao_proposta}), corrigida pelo consultor"
            add(f"**{rotulo}:** {proposta['justificativa']}")
            add("")
        if proposta.get("lacunas"):
            add("**Lacunas de evidência:**")
            add("")
            for lacuna in proposta["lacunas"]:
                add(f"- {lacuna}")
            add("")
        evidencias = _evidencias_citadas(item)
        if evidencias:
            add("**Evidências:**")
            add("")
            for evidencia in evidencias:
                trecho = " ".join(str(evidencia.get("trecho") or "").split())
                if len(trecho) > TRECHO_MAX:
                    trecho = trecho[:TRECHO_MAX].rsplit(" ", 1)[0] + "…"
                local = evidencia.get("localizacao") or evidencia.get("documento")
                ocr = " (OCR)" if evidencia.get("ocr") else ""
                add(f"- [{evidencia.get('n', '•')}] *{local}*{ocr}: “{trecho}”")
            add("")

    # 5. Diligências
    diligencias = [i for i in itens if i.classificacao_final == "EI"]
    add("## 5. Diligências")
    add("")
    if diligencias:
        add("Requisitos para os quais os documentos disponíveis não permitiram concluir. Recomenda-se obter junto ao curso:")
        add("")
        for item in diligencias:
            req = item.requisito or {}
            add(f"- **{item.requisito_codigo}** — {req.get('evidencia_esperada', '')}")
    else:
        add("Nenhuma diligência pendente.")
    add("")

    # Apêndice: concordância
    metricas = diagnostico.metricas or {}
    if incluir_concordancia and metricas.get("n_pares"):
        add("## Apêndice — Concordância entre o protótipo e o consultor")
        add("")
        acordo = metricas.get("percentual_acordo")
        kappa = metricas.get("kappa")
        add(f"- Itens comparados: {metricas['n_pares']}")
        if acordo is not None:
            add(f"- Percentual de acordo: {acordo * 100:.1f}%")
        if kappa is not None:
            add(f"- Kappa de Cohen: {kappa:.3f} (concordância {metricas.get('kappa_interpretacao')})")
        causas = metricas.get("divergencias_por_causa") or {}
        if causas:
            add("- Divergências por causa: " + ", ".join(f"{k}: {v}" for k, v in sorted(causas.items())))
        add("")

    return "\n".join(linhas).rstrip() + "\n"
