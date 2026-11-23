import io

import pytest
from docx import Document

from app.core.exceptions import ConflictError, ValidationError
from app.services.diagnostico.prompt import carregar_instrucao
from app.services.diagnostico.relatorio_docx import markdown_para_docx
from app.services.diagnostico.verificacao_service import VerificacaoService
from app.services.framework.evidence_retrieval_service import EvidenceRetrievalService
from tests.fakes import HashEmbedder, KeywordReranker, MemoryVectorStore, ScriptedLLM
from tests.test_gut_relatorio import HOJE, validado  # noqa: F401  (fixture)


def _emitido(service, diagnostico, itens):
    service.priorizacao(diagnostico.id, hoje=HOJE)
    service.definir_gut(diagnostico.id, itens["EXT-01"].id, 5, 4, 3)
    service.definir_gut(diagnostico.id, itens["INEP-D1"].id, 3, 3, 3)
    service.emitir_relatorio(diagnostico.id)


def test_docx_do_relatorio(validado):  # noqa: F811
    service, diagnostico, itens = validado
    _emitido(service, diagnostico, itens)
    conteudo = service.relatorio_docx(diagnostico.id)
    doc = Document(io.BytesIO(conteudo))
    titulos = [p.text for p in doc.paragraphs if p.style.name.startswith(("Heading", "Title"))]
    assert titulos[0].startswith("Relatório de diagnóstico") and "3. Prioridades (matriz GUT)" in titulos
    assert len(doc.tables) >= 3
    gut = next(t for t in doc.tables if t.rows[0].cells[-1].text == "G×U×T")
    assert gut.rows[1].cells[1].text.startswith("EXT-01") and gut.rows[1].cells[-1].text == "60"
    negritos = [r.text for p in doc.paragraphs for r in p.runs if r.bold]
    assert "Análise do consultor:" in negritos


def test_markdown_para_docx_trata_tabela_lista_e_citacao():
    md = "# Título\n\n> nota\n\n- item **forte**\n\n| A | B \\| C |\n|---|---:|\n| 1 | 2 |\n\nTexto *itálico*."
    doc = Document(io.BytesIO(markdown_para_docx(md)))
    assert doc.tables[0].rows[0].cells[1].text == "B | C" and doc.tables[0].rows[1].cells[0].text == "1"
    assert any(p.style.name == "List Bullet" for p in doc.paragraphs)
    assert any(r.italic and r.text == "itálico" for p in doc.paragraphs for r in p.runs)


def test_devolutiva_aceita_conclui(validado):  # noqa: F811
    service, diagnostico, itens = validado
    with pytest.raises(ConflictError, match="emissão"):
        service.registrar_devolutiva(diagnostico.id, {"resultado": "aceito"}, None)
    _emitido(service, diagnostico, itens)
    with pytest.raises(ValidationError):
        service.registrar_devolutiva(diagnostico.id, {"resultado": "talvez"}, None)
    service.registrar_devolutiva(
        diagnostico.id, {"resultado": "aceito", "data": "2026-12-01", "participantes": ["Coordenação", " NDE ", ""]}, None
    )
    assert diagnostico.status == "concluido"
    assert diagnostico.devolutiva["ultima"]["participantes"] == ["Coordenação", "NDE"]
    assert diagnostico.relatorio_md  # relatório mantido


def test_devolutiva_revisada_reabre_e_arquiva_relatorio(validado):  # noqa: F811
    service, diagnostico, itens = validado
    _emitido(service, diagnostico, itens)
    primeiro = diagnostico.relatorio_md
    service.registrar_devolutiva(diagnostico.id, {"resultado": "revisado", "observacoes": "Rever EXT-01."}, None)
    assert diagnostico.status == "priorizado" and diagnostico.relatorio_md is None
    assert diagnostico.config["relatorios_anteriores"][0]["markdown"] == primeiro

    # Reaberto: a validação volta a ser possível e um novo relatório pode ser emitido.
    service.validar_item(diagnostico.id, itens["EXT-01"].id, "PC", None, "interpretacao", "Revisado na devolutiva.", None)
    service.definir_gut(diagnostico.id, itens["EXT-01"].id, 4, 4, 3)
    service.emitir_relatorio(diagnostico.id)
    assert "Revisado na devolutiva." in diagnostico.relatorio_md
    assert len(diagnostico.devolutiva["registros"]) == 1


def test_clone_com_outro_modelo_e_concordancia_com_referencia(validado, db_session):  # noqa: F811
    service, diagnostico, itens = validado
    with pytest.raises(ValidationError, match="Provedor"):
        service.clonar(diagnostico.id, {"llm_provider": "xyz", "llm_model": "m"}, None)
    clone = service.clonar(diagnostico.id, {"llm_provider": "openai", "llm_model": "gpt-teste", "reasoning_level": "high"}, None)
    db_session.commit()
    assert clone.referencia_id == diagnostico.id and clone.status == "planejamento"
    assert [i.requisito_codigo for i in clone.itens] == [i.requisito_codigo for i in diagnostico.itens]
    assert all(i.classificacao_proposta is None and i.classificacao_final is None for i in clone.itens)

    service.iniciar_verificacao(clone.id, None, None)
    execucao = clone.config["ultima_execucao"]
    assert (execucao["llm_provider"], execucao["llm_model"], execucao["reasoning_level"]) == ("openai", "gpt-teste", "high")

    # Novo modelo propõe C para tudo; decisões de referência: EXT-01 NC, DCN-01 C, INEP-D1 PC, I40-01 EI.
    from app.repositories.framework_repository import SqlFrameworkRepository

    embedder = HashEmbedder()
    store = MemoryVectorStore()
    store.add("x", "Matriz curricular extensão perfil do egresso competências análise de dados", embedder,
              filename="doc.pdf", colecao="institucional", curso="ep")
    retrieval = EvidenceRetrievalService(SqlFrameworkRepository(db_session), embedder, store, KeywordReranker(), top_k=3, top_n=1)
    llm = ScriptedLLM(padrao={"classificacao": "C", "conceito_inep": 4, "justificativa": "[1]", "citacoes": [1], "lacunas": []})
    VerificacaoService(db_session, retrieval, llm, carregar_instrucao(None), espera_base=0).executar(clone.id)

    contra_referencia = service.metricas(clone, service.obter(diagnostico.id))
    assert contra_referencia["n_pares"] == 4 and contra_referencia["percentual_acordo"] == 0.25
    assert contra_referencia["referencia_id"] == str(diagnostico.id)
    assert contra_referencia["divergencias_por_causa"] == {}  # causas valem só para o próprio consultor
    assert service.metricas(clone)["n_pares"] == 0  # o clone ainda não foi validado
