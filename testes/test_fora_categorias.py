"""H1.2.3 — Tratar documento fora das categorias.

Cobre T1 a T5:
- T1: "Não identificado" no enum TipoDocumento e no prompt com exemplos negativos;
- T2: Bloqueio do roteamento com motivo "documento fora das categorias";
- T3: st.warning na página de resultado explicando que o documento foi separado para revisão;
- T4: 3 fixtures sintéticas não clínicas (nota fiscal, contrato, cardápio);
- T5: Cada fixture termina em Fila_Revisao_Humana e nenhuma chega a um destino de setor.
"""

from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from app import llm, storage
from app.grafo import construir_grafo, triar
from app.modelos import Classificacao, Destino, TipoDocumento
from app.roteamento import criar_decisao_roteamento, decidir_destino
from app.schemas import Extracao
from app.validacao import motivo_revisao, validar
from testes.conftest import cliente_com, extrator_fixo
from testes.fixtures.nao_clinicos import (
    CARDAPIO,
    CONTRATO,
    DOCUMENTOS_FORA_DAS_CATEGORIAS,
    NOTA_FISCAL,
)

PAGINA_RESULTADO = str(
    Path(__file__).resolve().parents[1] / "ui" / "pages" / "2_Triagem.py"
)

DESTINOS_DE_SETOR = {
    Destino.FARMACIA_HOSPITALAR.value,
    Destino.AUDITORIA_AUTORIZACOES.value,
    Destino.PRONTUARIO_ELETRONICO.value,
    Destino.FILA_EMERGENCIA_MEDICA.value,
}


def _extracao_fora_das_categorias(
    prioridade: str = "Rotina", score: float = 0.95
) -> Extracao:
    return Extracao(
        tipo_documento=TipoDocumento.NAO_IDENTIFICADO.value,
        especialidade=None,
        nivel_prioridade=prioridade,
        score_confianca_classificacao=score,
    )


# ==============================================================================
# T1 — Incluir "Não identificado" no enum e no prompt
# ==============================================================================
def test_t1_enum_tipo_documento_inclui_nao_identificado():
    assert TipoDocumento.NAO_IDENTIFICADO == "Não identificado"
    assert str(TipoDocumento.NAO_IDENTIFICADO) == "Não identificado"
    assert "Não identificado" in [m.value for m in TipoDocumento]

    cl = Classificacao(
        tipo_documento="Não identificado",
        especialidade=None,
        nivel_prioridade="Rotina",
        score_confianca_classificacao=0.90,
    )
    assert cl.tipo_documento == TipoDocumento.NAO_IDENTIFICADO

    ext = _extracao_fora_das_categorias()
    assert ext.tipo_documento == "Não identificado"


def test_t1_prompt_inclui_nao_identificado_e_exemplos_negativos():
    prompt_lower = llm.PROMPT.lower()
    assert '"Não identificado"' in llm.PROMPT
    assert "nota fiscal" in prompt_lower
    assert "contrato" in prompt_lower


# ==============================================================================
# T2 — Bloquear o roteamento com motivo "documento fora das categorias"
# ==============================================================================
@pytest.mark.parametrize(
    "prioridade,score",
    [
        ("Rotina", 0.99),
        ("Rotina", 0.85),
        ("Rotina", 0.40),
        ("Urgente", 0.99),
        ("Urgente", 0.50),
    ],
)
def test_t2_decidir_destino_bloqueia_nao_identificado_em_qualquer_cenario(
    prioridade, score
):
    destino_posicional = decidir_destino(
        "Não identificado", prioridade, False, score=score
    )
    assert destino_posicional == Destino.FILA_REVISAO_HUMANA
    assert str(destino_posicional) not in DESTINOS_DE_SETOR

    estado = {
        "tipo_documento": "Não identificado",
        "prioridade": prioridade,
        "urgencia": prioridade == "Urgente",
        "score": score,
        "pendencia": False,
        "problemas": [],
    }
    destino_estado = decidir_destino(estado)
    assert destino_estado == Destino.FILA_REVISAO_HUMANA
    assert str(destino_estado) not in DESTINOS_DE_SETOR

    decisao = criar_decisao_roteamento(estado)
    assert decisao.destino_principal == Destino.FILA_REVISAO_HUMANA
    assert decisao.requer_auditoria_humana is True
    assert decisao.regra_aplicada == "R-REVISAO"
    assert "documento fora das categorias" in decisao.justificativa_roteamento
    assert decisao.notificacao_gerada is None


def test_t2_validacao_e_grafo_registram_motivo_documento_fora_das_categorias():
    ext = _extracao_fora_das_categorias(prioridade="Rotina", score=0.95)
    _, problemas, score = validar(ext, NOTA_FISCAL)
    assert problemas == ["documento fora das categorias"]
    assert motivo_revisao(score, problemas, 0.80) == "documento fora das categorias"

    grafo = construir_grafo(
        extrator_fixo(_extracao_fora_das_categorias(prioridade="Rotina", score=0.95))
    )
    assert "enviar_revisao" in grafo.nodes

    estado = triar(
        NOTA_FISCAL,
        extrator_fixo(_extracao_fora_das_categorias(prioridade="Rotina", score=0.95)),
    )
    assert estado["destino"] == Destino.FILA_REVISAO_HUMANA.value
    assert estado["requer_revisao"] is True
    assert estado["motivo_revisao"] == "documento fora das categorias"
    assert estado["problemas"] == ["documento fora das categorias"]
    assert (
        estado["justificativa"]
        == "Enviado à revisão humana (regra R-REVISAO): documento fora das categorias."
    )


# ==============================================================================
# T3 — Mostrar o aviso na tela (st.warning em ui/pages/2_Triagem.py)
# ==============================================================================
class _RespFalsa:
    def __init__(self, status: int, corpo: dict):
        self.status_code = status
        self._corpo = corpo
        self.text = ""

    def json(self):
        return self._corpo


def test_t3_pagina_resultado_mostra_warning_quando_documento_fora_das_categorias(
    monkeypatch,
):
    corpo_nao_identificado = {
        "status": "processado",
        "documento_id": "DOC-NF-001",
        "problemas": ["documento fora das categorias"],
        "classificacao": {
            "tipo_documento": "Não identificado",
            "especialidade": None,
            "nivel_prioridade": "Rotina",
            "score_confianca_classificacao": 0.25,
        },
        "decisao_roteamento": {
            "destino_principal": "Fila_Revisao_Humana",
            "requer_auditoria_humana": True,
            "justificativa_roteamento": (
                "Enviado à revisão humana (regra R-REVISAO): documento fora das categorias."
            ),
            "regra_aplicada": "R-REVISAO",
        },
        "dados_extraidos": {},
    }
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, **kw: _RespFalsa(200, corpo_nao_identificado),
    )

    at = AppTest.from_file(PAGINA_RESULTADO, default_timeout=10).run()
    at.text_input[0].set_value("DOC-NF-001")
    at.button[0].click().run()

    assert not at.exception
    assert at.metric[0].value == "Não identificado"
    avisos = [w.value for w in at.warning]
    assert any(
        "fora das categorias" in a and "separado para revisão" in a for a in avisos
    )
    assert any("Destino: Fila_Revisao_Humana" in a for a in avisos)


# ==============================================================================
# T4 e T5 — As 3 fixtures não clínicas terminam em Fila_Revisao_Humana
# e nenhuma chega a um destino de setor
# ==============================================================================
def test_t4_tres_fixtures_nao_clinicas_existem():
    assert set(DOCUMENTOS_FORA_DAS_CATEGORIAS) == {
        "nota_fiscal",
        "contrato",
        "cardapio",
    }
    for texto in (NOTA_FISCAL, CONTRATO, CARDAPIO):
        assert isinstance(texto, str) and len(texto.strip()) > 50


@pytest.mark.parametrize(
    "nome_fixture,texto_fixture",
    [
        ("nota_fiscal", NOTA_FISCAL),
        ("contrato", CONTRATO),
        ("cardapio", CARDAPIO),
    ],
)
def test_t5_cada_fixture_nao_clinica_termina_em_revisao_humana_e_nunca_em_setor(
    nome_fixture, texto_fixture
):
    doc_id = f"DOC-FORA-{nome_fixture.upper().replace('_', '-')}"
    ext = _extracao_fora_das_categorias(prioridade="Rotina", score=0.95)

    # 1) Pelo grafo LangGraph
    estado = triar(texto_fixture, extrator_fixo(ext), documento_id=doc_id)
    assert estado["classificacao"].tipo_documento == TipoDocumento.NAO_IDENTIFICADO
    assert estado["destino"] == Destino.FILA_REVISAO_HUMANA.value
    assert estado["destino"] not in DESTINOS_DE_SETOR
    assert estado["requer_revisao"] is True
    assert estado["motivo_revisao"] == "documento fora das categorias"

    # 2) Pela API FastAPI (POST /triagem + GET /documentos/{id})
    cliente = cliente_com(extrator_fixo(ext))
    resp = cliente.post(
        "/triagem?aguardar=true",
        json={
            "documento_id": doc_id,
            "tipo_arquivo": "TEXTO",
            "documento_texto": texto_fixture,
            "canal_origem": "Operadora",
        },
    )
    assert resp.status_code == 200
    dados = resp.json()

    assert dados["classificacao"]["tipo_documento"] == "Não identificado"
    decisao = dados["decisao_roteamento"]
    assert decisao["destino_principal"] == "Fila_Revisao_Humana"
    assert decisao["destino_principal"] not in DESTINOS_DE_SETOR
    assert decisao["requer_auditoria_humana"] is True
    assert decisao["regra_aplicada"] == "R-REVISAO"
    assert "documento fora das categorias" in decisao["justificativa_roteamento"]
    assert "documento fora das categorias" in dados["problemas"]
    assert (
        dados["armazenamento_oci"]["caminho_objeto"]
        == f"auditoria_humana/{doc_id}.json"
    )
    assert storage.existe(f"auditoria_humana/{doc_id}.json")

    consulta = cliente.get(f"/documentos/{doc_id}")
    assert consulta.status_code == 200
    assert (
        consulta.json()["decisao_roteamento"]["destino_principal"]
        == "Fila_Revisao_Humana"
    )
