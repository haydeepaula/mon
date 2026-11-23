from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.db.models import EvalCase
from app.repositories.framework_repository import SqlFrameworkRepository
from app.services.eval_service import EvalService, aggregate
from app.services.framework.evidence_retrieval_service import EvidenceRetrievalService
from app.services.framework.framework_service import FrameworkService
from tests.fakes import HashEmbedder, KeywordReranker, MemoryVectorStore

SEED = Path(__file__).resolve().parents[2] / "data" / "framework" / "framework-v0.1.json"


@pytest.fixture()
def avaliacao(db_session):
    FrameworkService(db_session).carregar_seed(SEED)
    embedder = HashEmbedder()
    store = MemoryVectorStore()
    store.add("m1", "Matriz curricular com atividades de extensão e carga horária.", embedder, filename="matriz.xlsx",
              document_id="m", colecao="institucional", tipo_documento="matriz", curso="ep")
    store.add("p1", "PPC: perfil do egresso e competências gerais.", embedder, filename="ppc.pdf",
              document_id="p", colecao="institucional", tipo_documento="ppc", curso="ep")
    retrieval = EvidenceRetrievalService(SqlFrameworkRepository(db_session), embedder, store, KeywordReranker(),
                                         top_k=5, top_n=2)
    return EvalService(db_session), retrieval


def test_casos_gerados_do_framework_sem_duplicar(avaliacao, db_session):
    service, _ = avaliacao
    criados = service.cases_from_framework(tipos=["legal"])
    assert criados > 0
    casos = service.list_cases()
    assert all(c.requisito_codigo and "framework" in c.tags and c.expected_documents == [] for c in casos)
    assert service.cases_from_framework(tipos=["legal"]) == 0  # já existem
    assert service.cases_from_framework() > 0  # demais tipos


def test_execucao_por_requisito_exige_casos_vinculados(avaliacao, db_session):
    service, _ = avaliacao
    db_session.add(EvalCase(question="Qual a carga do estágio?", expected_documents=[], tags=[]))
    db_session.flush()
    with pytest.raises(ValidationError, match="requisito"):
        service.start_run(None, None, None, modo="requisito")
    service.cases_from_framework(tipos=["legal"])
    run = service.start_run("por requisito", None, None, modo="requisito", curso="ep")
    assert run.config["modo"] == "requisito" and run.config["curso"] == "ep"
    assert run.case_count == len([c for c in service.list_cases() if c.requisito_codigo])


def test_metricas_por_requisito_e_por_tipo(avaliacao, db_session):
    service, retrieval = avaliacao
    ext = EvalCase(question="extensão", requisito_codigo="EXT-01", expected_documents=["matriz.xlsx"], tags=[])
    dcn = EvalCase(question="perfil", requisito_codigo="DCN-01", expected_documents=["ppc.pdf"], tags=[])
    i40 = EvalCase(question="dados", requisito_codigo="I40-01", expected_documents=[], tags=[])
    for caso in (ext, dcn, i40):
        db_session.add(caso)
    db_session.flush()

    resultados = [service._evaluate_requirement(retrieval, c, n, "ep") for n, c in enumerate((ext, dcn, i40), 1)]
    r_ext, r_dcn, r_i40 = resultados
    assert r_ext.metrics["hit_rate"] == 1.0 and r_ext.metrics["mrr"] == 1.0 and r_ext.metrics["tipo"] == "legal"
    assert r_dcn.metrics["hit_rate"] == 1.0
    assert "hit_rate" not in r_i40.metrics and "Sem documentos esperados" in r_i40.judge_reason
    assert r_ext.retrieved[0]["filename"] == "matriz.xlsx" and r_ext.question.startswith("EXT-01:")

    resumo = aggregate(resultados)
    assert resumo["hit_rate"] == 1.0
    assert resumo["por_tipo"]["legal"]["n"] == 2 and resumo["por_tipo"]["legal"]["mrr"] == 1.0
    assert resumo["por_tipo"]["competencia"]["hit_rate"] is None

    inexistente = EvalCase(question="x", requisito_codigo="XXX-99", expected_documents=[], tags=[])
    assert "não encontrado" in service._evaluate_requirement(retrieval, inexistente, 4, None).error
