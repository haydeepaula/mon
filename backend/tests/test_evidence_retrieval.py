from app.domain.framework import requisito_de_dict
from app.services.framework.evidence_retrieval_service import EvidenceRetrievalService, consulta_normativa
from tests.fakes import HashEmbedder, KeywordReranker, MemoryFrameworkRepository, MemoryVectorStore

EXT = {
    "codigo": "EXT-01",
    "fonte_documento": "Resolução CNE/CES nº 7/2018",
    "texto": "Mínimo de 10% da carga horária curricular em extensão",
    "tipo": "legal",
    "evidencia_esperada": "Componentes de extensão na matriz",
    "documentos_provaveis": ["matriz", "regulamento"],
    "consulta_padrao": "atividades de extensão na matriz curricular e sua carga horária",
}


def _store(embedder):
    store = MemoryVectorStore()
    base = {"document_id": "d", "version": 1, "sha256": "abc"}
    store.add("matriz-1", "Matriz curricular: atividades de extensão com carga horária de 360 horas.", embedder,
              **{**base, "document_id": "m", "filename": "matriz.xlsx", "colecao": "institucional",
                 "tipo_documento": "matriz", "curso": "ep", "page": None, "sheet": "Matriz"})
    store.add("ata-1", "Ata do NDE discute a carga horária de extensão e atividades curriculares.", embedder,
              **{**base, "document_id": "a", "filename": "ata.pdf", "colecao": "institucional",
                 "tipo_documento": None, "curso": "ep", "page": 2, "ocr": True})
    store.add("outro-curso", "Extensão na matriz curricular do curso de Administração, carga horária.", embedder,
              **{**base, "document_id": "o", "filename": "outro.pdf", "colecao": "institucional", "curso": "adm"})
    store.add("norma-1", "Art. 4º As atividades de extensão devem compor no mínimo 10% da carga horária.", embedder,
              **{**base, "document_id": "n", "filename": "res-7-2018.pdf", "colecao": "normativa",
                 "tipo_documento": "resolucao", "page": 1})
    return store


def _service(store, embedder, **kwargs):
    return EvidenceRetrievalService(
        MemoryFrameworkRepository([EXT]), embedder, store, KeywordReranker(), top_k=10, **kwargs
    )


def test_busca_somente_institucional_com_tipos_provaveis_e_geral():
    embedder = HashEmbedder()
    store = _store(embedder)
    resultado = _service(store, embedder).recuperar_detalhado("ext-01", curso="ep")

    assert store.searches == [
        {"colecao": "institucional", "curso": "ep", "tipo_documento": ["matriz", "regulamento"]},
        {"colecao": "institucional", "curso": "ep"},
    ]
    documentos = [e.documento for e in resultado.evidencias]
    assert set(documentos) == {"matriz.xlsx", "ata.pdf"}  # sem duplicatas, sem normativo, sem outro curso
    assert documentos[0] == "matriz.xlsx"
    assert resultado.consulta == EXT["consulta_padrao"]
    assert resultado.config["candidatos"] == 2 and resultado.config["curso"] == "ep"
    assert resultado.normativos == []

    ata = next(e for e in resultado.evidencias if e.documento == "ata.pdf")
    assert ata.ocr is True and ata.pagina == 2 and ata.localizacao == "ata.pdf, página 2"
    assert ata.score == ata.rerank_score and ata.versao == 1 and ata.sha256 == "abc"


def test_sem_documentos_provaveis_faz_so_a_busca_geral():
    embedder = HashEmbedder()
    store = _store(embedder)
    requisito = requisito_de_dict({**EXT, "documentos_provaveis": []})
    _service(store, embedder).recuperar_para(requisito)
    assert store.searches == [{"colecao": "institucional"}]


def test_normativa_e_min_relevance_e_top_n():
    embedder = HashEmbedder()
    store = _store(embedder)
    service = _service(store, embedder)
    resultado = service.recuperar_detalhado("EXT-01", top_n=1, incluir_normativa=True)
    assert len(resultado.evidencias) == 1
    assert [n.documento for n in resultado.normativos] == ["res-7-2018.pdf"]
    assert store.searches[-1] == {"colecao": "normativa"}
    assert "Resolução CNE/CES nº 7/2018" in consulta_normativa(resultado.requisito)

    exigente = _service(store, embedder, min_relevance=1.01)
    assert exigente.recuperar("EXT-01") == []


def test_base_vazia_nao_chama_reranker():
    embedder = HashEmbedder()
    resultado = _service(MemoryVectorStore(), embedder).recuperar_detalhado("EXT-01", incluir_normativa=True)
    assert resultado.evidencias == [] and resultado.normativos == []
