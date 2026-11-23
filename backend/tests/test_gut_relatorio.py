from datetime import date
from pathlib import Path

import pytest

from app.core.exceptions import ConflictError, ValidationError
from app.domain import gut
from app.services.diagnostico.diagnostico_service import DiagnosticoService
from app.services.diagnostico.prompt import carregar_instrucao
from app.services.diagnostico.verificacao_service import VerificacaoService
from app.services.framework.evidence_retrieval_service import EvidenceRetrievalService
from app.services.framework.framework_service import FrameworkService
from tests.fakes import HashEmbedder, KeywordReranker, MemoryVectorStore, ScriptedLLM

SEED = Path(__file__).resolve().parents[2] / "data" / "framework" / "framework-v0.1.json"
HOJE = date(2026, 11, 22)


# --- regras da GUT ---------------------------------------------------------------------------
def test_gravidade_sugerida():
    assert gut.sugerir_g({"tipo": "legal"}, "NC") == (5, "obrigação legal")
    assert gut.sugerir_g({"tipo": "legal"}, "PC")[0] == 4
    assert gut.sugerir_g({"tipo": "qualidade", "peso_dimensao": 40}, "NC")[0] == 4
    assert gut.sugerir_g({"tipo": "qualidade", "peso_dimensao": 30}, "NC")[0] == 3
    assert gut.sugerir_g({"tipo": "competencia"}, "PC")[0] == 2
    assert gut.sugerir_g({"tipo": "legal", "gravidade_base": 2}, "NC")[0] == 2
    assert gut.sugerir_g({"tipo": "legal", "gravidade_base": 1}, "PC")[0] == 1


@pytest.mark.parametrize(
    ("prazo", "esperado"),
    [(date(2026, 12, 30), 5), (date(2027, 5, 22), 5), (date(2027, 11, 1), 4), (date(2028, 6, 1), 3),
     (date(2030, 1, 1), 2), (date(2026, 1, 1), 5)],
)
def test_urgencia_por_prazo(prazo, esperado):
    assert gut.sugerir_u(prazo, None, HOJE)[0] == esperado


def test_urgencia_usa_o_prazo_mais_proximo_e_sem_prazo():
    nota, motivo = gut.sugerir_u(date(2030, 1, 1), date(2027, 3, 1), HOJE)
    assert nota == 5 and "próximo ato" in motivo
    assert gut.sugerir_u(None, None, HOJE)[0] is None
    sugestao = gut.sugerir({"tipo": "legal", "prazo_referencia": "2027-02-01"}, "NC", None, HOJE)
    assert (sugestao.g, sugestao.u) == (5, 5)


def test_ranking_e_validacao_de_notas():
    itens = [(60, 5, 4, "B"), (60, 5, 4, "A"), (80, 4, 5, "C"), (60, 3, 5, "D"), (None, None, None, "E")]
    ordem = sorted(itens, key=lambda i: gut.chave_ranking(*i))
    assert [i[3] for i in ordem] == ["C", "A", "B", "D", "E"]
    with pytest.raises(ValueError):
        gut.validar_nota("G", 6)


# --- fluxo: priorização e relatório -------------------------------------------------------------
@pytest.fixture()
def validado(db_session):
    FrameworkService(db_session).carregar_seed(SEED)
    embedder = HashEmbedder()
    store = MemoryVectorStore()
    store.add("m1", "Matriz curricular: extensão com 200 horas de 3600 horas totais.", embedder,
              document_id="m", filename="matriz.xlsx", version=1, colecao="institucional",
              tipo_documento="matriz", curso="ep")
    store.add("p1", "PPC: perfil do egresso e competências do engenheiro de produção.", embedder,
              document_id="p", filename="ppc.pdf", version=1, page=3, colecao="institucional",
              tipo_documento="ppc", curso="ep", ocr=True)
    service = DiagnosticoService(db_session)
    diagnostico = service.criar(
        {"nome": "Teste", "curso": "ep", "curso_nome": "Engenharia de Produção",
         "escopo": {"codigos": ["EXT-01", "DCN-01", "INEP-D1", "I40-01"], "data_ato": "2027-09-01",
                    "proximo_ato": "renovacao"}},
        None,
    )
    service.iniciar_verificacao(diagnostico.id, None, None)
    db_session.commit()
    from app.repositories.framework_repository import SqlFrameworkRepository

    retrieval = EvidenceRetrievalService(SqlFrameworkRepository(db_session), embedder, store, KeywordReranker(),
                                         top_k=5, top_n=2, min_relevance=0.3)
    llm = ScriptedLLM({
        "EXT-01": {"classificacao": "NC", "conceito_inep": None, "justificativa": "200 h de 3600 h = 5,6% [1].",
                   "citacoes": [1], "lacunas": ["Regulamento de extensão"]},
        "DCN-01": {"classificacao": "C", "conceito_inep": None, "justificativa": "Perfil descrito [1].",
                   "citacoes": [1], "lacunas": []},
        "INEP-D1": {"classificacao": "PC", "conceito_inep": 3, "justificativa": "Perfil sem demandas [1].",
                    "citacoes": [1], "lacunas": []},
    })
    VerificacaoService(db_session, retrieval, llm, carregar_instrucao(None), espera_base=0).executar(diagnostico.id)
    itens = {i.requisito_codigo: i for i in diagnostico.itens}
    service.validar_item(diagnostico.id, itens["EXT-01"].id, "NC", None, None, "Abaixo de 10%.", None)
    service.validar_item(diagnostico.id, itens["DCN-01"].id, "C", None, None, None, None)
    service.validar_item(diagnostico.id, itens["INEP-D1"].id, "PC", 3, None, None, None)
    service.validar_item(diagnostico.id, itens["I40-01"].id, "EI", None, None, None, None)
    db_session.commit()
    return service, diagnostico, itens


def test_priorizacao_e_emissao_do_relatorio(validado):
    service, diagnostico, itens = validado
    assert diagnostico.status == "validado"

    with pytest.raises(ConflictError, match="priorize"):
        service.emitir_relatorio(diagnostico.id)

    priorizados = service.priorizacao(diagnostico.id, hoje=HOJE)
    assert [i.requisito_codigo for i in priorizados] == ["EXT-01", "INEP-D1"]
    assert itens["EXT-01"].gut_sugestao["g"] == 5 and itens["EXT-01"].gut_sugestao["u"] == 4
    assert itens["INEP-D1"].gut_sugestao["g"] == 2  # gravidade base 3, PC (−1)

    with pytest.raises(ValidationError, match="NC"):
        service.definir_gut(diagnostico.id, itens["DCN-01"].id, 3, 3, 3)
    service.definir_gut(diagnostico.id, itens["INEP-D1"].id, 4, 4, 4)
    assert diagnostico.status == "validado"
    service.definir_gut(diagnostico.id, itens["EXT-01"].id, 5, 4, 3)
    assert diagnostico.status == "priorizado" and itens["EXT-01"].prioridade == 60
    assert [i.requisito_codigo for i in service.priorizacao(diagnostico.id, hoje=HOJE)] == ["INEP-D1", "EXT-01"]

    # Mudar a validação de um item priorizado para C limpa a GUT; para NC, reabre a priorização.
    service.validar_item(diagnostico.id, itens["DCN-01"].id, "PC", None, "interpretacao", None, None)
    assert diagnostico.status == "validado"
    service.definir_gut(diagnostico.id, itens["DCN-01"].id, 5, 4, 2)
    assert diagnostico.status == "priorizado"

    previa = service.relatorio(diagnostico.id)
    assert previa.startswith("# Relatório de diagnóstico — Engenharia de Produção") and "Prévia" in previa

    service.emitir_relatorio(diagnostico.id)
    assert diagnostico.status == "relatorio_emitido" and diagnostico.relatorio_emitido_em
    relatorio = service.relatorio(diagnostico.id)
    assert "Prévia" not in relatorio
    assert "renovação de reconhecimento (previsto para 01/09/2027)" in relatorio
    assert "| 1 | **INEP-D1**" in relatorio and "| 2 | **EXT-01**" in relatorio
    assert "**Análise do consultor:** Abaixo de 10%." in relatorio
    assert "Regulamento de extensão" in relatorio
    assert "*matriz.xlsx*" in relatorio
    assert "## 5. Diligências" in relatorio and "**I40-01**" in relatorio
    assert "Kappa de Cohen" in relatorio
    assert "corrigida pelo consultor" in relatorio  # DCN-01: proposta C, decisão PC

    # Emitido: relatório congelado, validação e GUT bloqueadas.
    with pytest.raises(ConflictError):
        service.validar_item(diagnostico.id, itens["EXT-01"].id, "PC", None, "geracao", None, None)
    with pytest.raises(ConflictError):
        service.definir_gut(diagnostico.id, itens["EXT-01"].id, 1, 1, 1)
    assert service.relatorio(diagnostico.id) == relatorio


def test_relatorio_sem_nc_pc_pode_ser_emitido(validado):
    service, diagnostico, itens = validado
    service.validar_item(diagnostico.id, itens["EXT-01"].id, "C", None, "interpretacao", None, None)
    service.validar_item(diagnostico.id, itens["INEP-D1"].id, "C", 4, "interpretacao", None, None)
    service.emitir_relatorio(diagnostico.id)
    assert "Nenhum requisito foi classificado como não conforme" in diagnostico.relatorio_md
