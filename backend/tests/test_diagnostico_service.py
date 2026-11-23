from pathlib import Path

import pytest

from app.api.routers.diagnosticos import item_out
from app.core.exceptions import ConflictError, ValidationError
from app.db.models import Job, JobType
from app.services.diagnostico.diagnostico_service import DiagnosticoService
from app.services.diagnostico.prompt import carregar_instrucao
from app.services.diagnostico.verificacao_service import VerificacaoService
from app.services.framework.evidence_retrieval_service import EvidenceRetrievalService
from app.services.framework.framework_service import FrameworkService
from tests.fakes import HashEmbedder, KeywordReranker, MemoryVectorStore, ScriptedLLM

SEED = Path(__file__).resolve().parents[2] / "data" / "framework" / "framework-v0.1.json"

EVIDENCIA_EXTENSAO = "Matriz curricular: atividades de extensão somam 360 horas, 10% da carga horária curricular."


def _proposta(classificacao="C", citacoes=(1,), conceito=None):
    return {"classificacao": classificacao, "conceito_inep": conceito, "justificativa": "Ver [1].",
            "citacoes": list(citacoes), "lacunas": []}


@pytest.fixture()
def ambiente(db_session):
    FrameworkService(db_session).carregar_seed(SEED)
    db_session.commit()
    embedder = HashEmbedder()
    store = MemoryVectorStore()
    store.add("m1", EVIDENCIA_EXTENSAO, embedder, document_id="m", filename="matriz.xlsx", version=1,
              colecao="institucional", tipo_documento="matriz", curso="ep")
    store.add("p1", "PPC: perfil do egresso e competências gerais e específicas do engenheiro de produção.",
              embedder, document_id="p", filename="ppc.pdf", version=2, page=12, colecao="institucional",
              tipo_documento="ppc", curso="ep", ocr=True)
    return db_session, embedder, store


def _verificacao(session, embedder, store, llm, min_relevance=0.3):
    from app.repositories.framework_repository import SqlFrameworkRepository

    retrieval = EvidenceRetrievalService(
        SqlFrameworkRepository(session), embedder, store, KeywordReranker(), top_k=5, top_n=3,
        min_relevance=min_relevance,
    )
    return VerificacaoService(session, retrieval, llm, carregar_instrucao(None), espera_base=0)


def _criar(session, **escopo):
    service = DiagnosticoService(session)
    diagnostico = service.criar(
        {"nome": "Teste", "curso": "ep", "curso_nome": "Engenharia de Produção EAD",
         "escopo": {"formato_oferta": "semipresencial", "codigos": ["EXT-01", "DCN-01", "INEP-D1", "I40-01"],
                    **escopo}},
        None,
    )
    session.commit()
    return service, diagnostico


def test_planejamento_filtra_por_escopo(ambiente):
    session, _, _ = ambiente
    service = DiagnosticoService(session)
    presencial = {r.codigo for r in service.requisitos_aplicaveis({"formato_oferta": "presencial"})}
    assert "REG-01" not in presencial and "EXT-01" in presencial and "TEND-01" not in presencial
    semi = {r.codigo for r in service.requisitos_aplicaveis({"formato_oferta": "semipresencial", "incluir_tendencia": True})}
    assert {"REG-01", "TEND-01"} <= semi

    _, diagnostico = _criar(session)
    assert [i.requisito_codigo for i in diagnostico.itens] == ["EXT-01", "DCN-01", "INEP-D1", "I40-01"]
    assert diagnostico.framework_versao == "0.1" and diagnostico.status == "planejamento"
    assert diagnostico.itens[0].requisito["texto"].startswith("Mínimo de 10%")

    with pytest.raises(ValidationError, match="Nenhum requisito"):
        service.criar({"escopo": {"codigos": ["XXX-01"]}}, None)
    with pytest.raises(ValidationError):
        service.criar({"escopo": {"formato_oferta": "hibrido"}}, None)

    atualizado = service.atualizar(diagnostico.id, {"escopo": {"codigos": ["EXT-01"]}})
    assert [i.requisito_codigo for i in atualizado.itens] == ["EXT-01"]


def test_fluxo_verificacao_validacao_e_concordancia(ambiente):
    session, embedder, store = ambiente
    service, diagnostico = _criar(session)

    job = service.iniciar_verificacao(diagnostico.id, None, None)
    session.commit()
    assert job.type == JobType.DIAGNOSTICO_VERIFICAR and diagnostico.status == "verificando"
    execucao = diagnostico.config["ultima_execucao"]
    assert execucao["itens"] == 4 and execucao["prompt_sha256"] and "llm_model" in execucao
    with pytest.raises(ConflictError, match="em andamento"):
        service.iniciar_verificacao(diagnostico.id, None, None)

    llm = ScriptedLLM({
        "EXT-01": _proposta("C"),
        "DCN-01": _proposta("NC", citacoes=[9]),  # citação inválida → rebaixada para EI
        "INEP-D1": _proposta("PC", conceito=3),
    })
    resumo = _verificacao(session, embedder, store, llm).executar(diagnostico.id, job.payload["item_ids"])
    session.refresh(diagnostico)
    itens = {i.requisito_codigo: i for i in diagnostico.itens}

    assert diagnostico.status == "em_validacao"
    assert itens["EXT-01"].classificacao_proposta == "C"
    assert itens["EXT-01"].evidencias[0]["documento"] == "matriz.xlsx" and itens["EXT-01"].evidencias[0]["n"] == 1
    assert itens["DCN-01"].classificacao_proposta == "EI" and "sem_citacao" in itens["DCN-01"].alertas
    assert itens["INEP-D1"].conceito_proposto == 3
    # I40-01 (análise de dados): nenhum trecho relevante → EI sem chamar o LLM.
    assert itens["I40-01"].classificacao_proposta == "EI" and itens["I40-01"].alertas == ["sem_evidencia"]
    assert not any("<codigo>I40-01</codigo>" in c["prompt"] for c in llm.chamadas)
    assert resumo == {"verificados": 4, "erros": 0, "sem_evidencia": 1}
    assert "<evidencias>" in llm.chamadas[0]["prompt"] and llm.chamadas[0]["schema"]["required"]

    # Validação: divergência exige causa; conceito só para qualidade.
    with pytest.raises(ValidationError, match="causa"):
        service.validar_item(diagnostico.id, itens["EXT-01"].id, "PC", None, None, None, None)
    with pytest.raises(ValidationError, match="qualidade"):
        service.validar_item(diagnostico.id, itens["EXT-01"].id, "C", 4, None, None, None)
    service.validar_item(diagnostico.id, itens["EXT-01"].id, "C", None, "geracao", "ok", None)
    assert itens["EXT-01"].divergencia_causa is None  # concordou: causa descartada
    service.validar_item(diagnostico.id, itens["DCN-01"].id, "C", None, "recuperacao", None, None)
    service.validar_item(diagnostico.id, itens["INEP-D1"].id, "PC", 4, None, None, None)
    assert diagnostico.status == "em_validacao"
    service.validar_item(diagnostico.id, itens["I40-01"].id, "EI", None, None, None, None)
    assert diagnostico.status == "validado"

    metricas = diagnostico.metricas
    assert metricas["n_pares"] == 4 and metricas["percentual_acordo"] == 0.75
    assert metricas["divergencias_por_causa"] == {"recuperacao": 1}
    assert metricas["n_sem_evidencia"] == 1 and metricas["kappa"] is not None
    assert metricas["n_pares_conceito"] == 1

    with pytest.raises(ConflictError, match="já validados"):
        service.iniciar_verificacao(diagnostico.id, [itens["EXT-01"].id], None)


def test_erro_do_llm_e_reverificacao(ambiente):
    session, embedder, store = ambiente
    service, diagnostico = _criar(session, codigos=["EXT-01"])
    service.iniciar_verificacao(diagnostico.id, None, None)
    session.commit()

    falho = ScriptedLLM({"EXT-01": RuntimeError("cota excedida")})
    _verificacao(session, embedder, store, falho).executar(diagnostico.id)
    item = diagnostico.itens[0]
    assert item.proposta_status == "erro" and "cota excedida" in item.erro
    assert len(falho.chamadas) == 3  # duas novas tentativas

    # Item com erro pode ser validado pelo consultor sem causa (não há proposta a comparar).
    service.iniciar_verificacao(diagnostico.id, None, None)
    session.commit()
    invalido_depois_valido = ScriptedLLM({"EXT-01": _proposta("C")})
    _verificacao(session, embedder, store, invalido_depois_valido).executar(diagnostico.id)
    assert item.proposta_status == "gerada" and item.classificacao_proposta == "C"


def test_validacao_cega_oculta_proposta(ambiente):
    session, embedder, store = ambiente
    service, diagnostico = _criar(session, codigos=["EXT-01"], validacao_cega=True)
    service.iniciar_verificacao(diagnostico.id, None, None)
    session.commit()
    _verificacao(session, embedder, store, ScriptedLLM(padrao=_proposta("C"))).executar(diagnostico.id)
    item = diagnostico.itens[0]

    oculto = item_out(item, diagnostico.escopo)
    assert oculto.proposta_oculta and oculto.classificacao_proposta is None and oculto.proposta is None
    assert oculto.evidencias and "score" not in oculto.evidencias[0]

    service.validar_item(diagnostico.id, item.id, "PC", None, "interpretacao", None, None)
    revelado = item_out(item, diagnostico.escopo)
    assert not revelado.proposta_oculta and revelado.classificacao_proposta == "C"


def test_validacao_exige_verificacao(ambiente):
    session, _, _ = ambiente
    service, diagnostico = _criar(session, codigos=["EXT-01"])
    with pytest.raises(ConflictError):
        service.validar_item(diagnostico.id, diagnostico.itens[0].id, "C", None, None, None, None)
    assert session.query(Job).count() == 0
