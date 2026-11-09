"""Integração H4.2.1: a aplicação REAL precisa servir GET /filas/revisao.

Diferente de test_fila_revisao.py — que monta um FastAPI na mão com um duble do índice —
este teste usa criar_app(extrator=...), ou seja, as rotas exatamente como a aplicação sobe
em produção, sem dependency_overrides.

O storage já vem isolado pelo fixture automático de conftest.py (storage_isolado):
STORAGE_LOCAL_DIR aponta para tmp e OCI_NAMESPACE é apagado — nada toca o bucket real.
"""

from testes.conftest import LAUDO_TEP, cliente_com, extracao, extrator_fixo

DOC_ID = "DOC-INTEGRA-FILA-001"


def test_get_filas_revisao_na_aplicacao_real_devolve_200():
    # Score 0.40 < 0.80 (config/regras.json): o documento cai na revisão humana.
    cliente = cliente_com(extrator_fixo(extracao(score_confianca_classificacao=0.40)))

    envio = cliente.post(
        "/triagem?aguardar=true",
        json={
            "documento_id": DOC_ID,
            "tipo_arquivo": "PDF",
            "documento_texto": LAUDO_TEP,
            "canal_origem": "Pronto_Socorro",
        },
    )
    assert envio.status_code == 200  # pré-condição: processou sem erro
    assert (
        envio.json()["decisao_roteamento"]["destino_principal"] == "Fila_Revisao_Humana"
    )  # pré-condição: foi para a fila de revisão

    resp = cliente.get("/filas/revisao")

    assert resp.status_code == 200
    # 200 sozinho não basta: uma implementação que devolve sempre [] também daria 200.
    # O caso precisa aparecer na fila — é o que prova que o índice lê o que processar() gravou.
    ids = [c["documento_id"] for c in resp.json()]
    assert DOC_ID in ids
