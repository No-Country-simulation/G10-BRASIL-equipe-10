import os
import time
from pathlib import Path

import pytest

from app.grafo import triar
from app.llm import extrair

FIXTURES = Path(__file__).parent / "fixtures"

import io

from PIL import Image

from app import storage
from app.schemas import Legibilidade
from testes.conftest import (
    LAUDO_TEP,
    cliente_com,
    extracao,
    # extrator_fixo,
    extrator_que_quebra,
    pdf_com_texto,
    pdf_sem_texto,
)

CORPO = {
    "documento_id": "DOC-CLIN-2026-8942",
    "tipo_arquivo": "PDF",
    "documento_texto": LAUDO_TEP,
    "canal_origem": "Pronto_Socorro",
}


# ---- H1.1.1 T4: responde 202 na hora e o grafo roda em segundo plano ----
def test_202_com_documento_id_e_status_recebido(cliente):
    r = cliente.post("/triagem", json=CORPO)
    assert r.status_code == 202
    assert r.json() == {
        "documento_id": "DOC-CLIN-2026-8942",
        "status": "recebido",
    }  # sem resultado ainda


def test_grafo_roda_em_segundo_plano_e_resultado_fica_disponivel(cliente):
    cliente.post("/triagem", json=CORPO)
    r = cliente.get("/triagem/DOC-CLIN-2026-8942")
    assert r.status_code == 200
    assert (
        r.json()["decisao_roteamento"]["destino_principal"] == "Fila_Emergencia_Medica"
    )


def test_202_mesmo_se_o_llm_quebrar_e_original_continua_salvo():
    c = cliente_com(extrator_que_quebra)
    assert c.post("/triagem", json=CORPO).status_code == 202
    assert storage.existe("recebidos/DOC-CLIN-2026-8942.txt")  # H5.1.1
    res = c.get("/triagem/DOC-CLIN-2026-8942").json()
    assert res["decisao_roteamento"]["destino_principal"] == "Fila_Revisao_Humana"
    assert res["status"] == "erro_extracao"


# ---- H1.1.1 T2/T3: validação, duplicidade, original salvo antes ----
def test_texto_vazio_422(cliente):
    r = cliente.post("/triagem", json={**CORPO, "documento_texto": "   "})
    assert r.status_code == 422 and r.json()["detail"] == "documento vazio"


def test_campo_ausente_422(cliente):
    r = cliente.post("/triagem", json={"documento_id": "DOC-1"})
    assert r.status_code == 422 and "campo obrigatório ausente" in r.json()["detail"]


def test_id_com_path_traversal_422(cliente):
    r = cliente.post("/triagem", json={**CORPO, "documento_id": "../../x"})
    assert r.status_code == 422


def test_id_repetido_409(cliente):
    assert cliente.post("/triagem", json=CORPO).status_code == 202
    assert cliente.post("/triagem", json=CORPO).status_code == 409


def test_original_salvo_com_o_id_no_nome(cliente):
    cliente.post("/triagem", json=CORPO)
    ler_doc = storage.ler("recebidos/DOC-CLIN-2026-8942.txt")
    assert ler_doc is not None and ler_doc.decode() == LAUDO_TEP


# ---- H2.3.1 / H5.1.2: contrato do edital ----
def test_resposta_no_formato_do_edital(cliente):
    r = cliente.post("/triagem?aguardar=true", json=CORPO)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "processado"
    assert j["classificacao"] == {
        "tipo_documento": "Laudo de Exame de Imagem",
        "especialidade": "Radiologia / Pneumologia",
        "nivel_prioridade": "Urgente",
        "score_confianca_classificacao": 0.95,
    }
    assert j["dados_extraidos"]["medico_solicitante"]["crm"] == "145892-SP"
    assert j["dados_extraidos"]["cid_sugerido"] == "I26.9"
    assert (
        j["dados_extraidos"]["cid_origem"] == "sugerido"
    )  # H1.3.3: não estava escrito
    d = j["decisao_roteamento"]
    assert (
        d["destino_principal"] == "Fila_Emergencia_Medica"
        and d["requer_auditoria_humana"] is False
    )
    assert d["notificacao_gerada"]["canal"] == "Alerta_Plantao_Medico"
    assert j["armazenamento_oci"] == {
        "bucket": "mediflow-documentos-clinicos",
        "caminho_objeto": "processados/urgentes/DOC-CLIN-2026-8942.json",
        "status_backup": "sucesso",
        "local": "disco",
        "urgente": True,
    }


# ---- H1.1.2: PDF ----
@pytest.mark.parametrize(
    ("arquivo", "marcadores"),
    [
        ("pdf_textual_1_pagina.pdf", ["Página 1"]),
        (
            "pdf_textual_3_paginas.pdf",
            ["Página 1", "Página 2", "Página 3"],
        ),
    ],
)
def test_pdf_textual_le_todas_as_paginas(arquivo, marcadores):
    textos_recebidos = []

    def espiao(texto):
        textos_recebidos.append(texto)
        return extracao()

    estado = triar(
        "",
        extrator=espiao,
        pdf_bytes=(FIXTURES / arquivo).read_bytes(),
    )

    assert estado["tipo_arquivo"] == "PDF"
    assert len(textos_recebidos) == 1
    assert all(marcador in estado["texto"] for marcador in marcadores)
    assert all(marcador in textos_recebidos[0] for marcador in marcadores)


def test_pdf_apenas_imagem_vai_para_fluxo_de_imagem():
    imagens_recebidas = []
    textos_recebidos = []

    def leitor_falso(imagens):
        imagens_recebidas.extend(imagens)
        return (
            "Paciente: Maria Teste. Hemograma sem alterações.",
            Legibilidade(legivel=True),
        )

    def extrator_falso(texto):
        textos_recebidos.append(texto)
        return extracao()

    estado = triar(
        "",
        extrator=extrator_falso,
        pdf_bytes=(FIXTURES / "amostra_escaneada.pdf").read_bytes(),
        leitor=leitor_falso,
    )

    assert estado["tipo_arquivo"] == "PDF"
    assert imagens_recebidas
    assert all(imagem.startswith(b"\x89PNG") for imagem in imagens_recebidas)
    assert textos_recebidos == ["Paciente: Maria Teste. Hemograma sem alterações."]


@pytest.mark.llm
@pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY"),
    reason="sem GEMINI_API_KEY",
)
def test_pdf_de_10_paginas_e_processado_em_ate_30s():
    inicio = time.perf_counter()

    estado = triar(
        "",
        extrator=extrair,
        pdf_bytes=(FIXTURES / "pdf_textual_10_paginas.pdf").read_bytes(),
    )

    duracao_s = time.perf_counter() - inicio

    assert estado["tipo_arquivo"] == "PDF"
    assert "Página 10 de 10" in estado["texto"]
    assert duracao_s < 30, f"processamento levou {duracao_s:.2f}s; limite: 30s"


def test_pdf_sem_texto_vai_para_revisao_humana(cliente, monkeypatch):
    # H1.1.3: o PDF escaneado agora é lido por visão. Leitor falso = sem rede.
    monkeypatch.setattr(
        "app.grafo.ler_imagem",
        lambda imagens: ("", Legibilidade(legivel=False, motivo="sem texto")),
    )
    r = cliente.post(
        "/triagem/pdf?aguardar=true",
        data={"documento_id": "PDF-002", "canal_origem": "X"},
        files={"arquivo": ("scan.pdf", pdf_sem_texto(), "application/pdf")},
    )
    j = r.json()
    assert j["decisao_roteamento"]["destino_principal"] == "Fila_Revisao_Humana"
    assert "ilegível" in j["decisao_roteamento"]["justificativa_roteamento"]


def test_arquivo_que_nao_e_pdf_422(cliente):
    r = cliente.post(
        "/triagem/pdf",
        data={"documento_id": "PDF-003", "canal_origem": "X"},
        files={"arquivo": ("a.pdf", b"nao sou pdf", "application/pdf")},
    )
    assert r.status_code == 422


def test_consulta_de_id_inexistente_404(cliente):
    assert cliente.get("/triagem/NAO-EXISTE").status_code == 404


# ---- H1.1.3: imagem e PDF escaneado em /triagem/arquivo ----
def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), "white").save(buf, "PNG")
    return buf.getvalue()


def _enviar_arquivo(c, doc_id, conteudo, nome="foto.png", tipo="image/png"):
    return c.post(
        "/triagem/arquivo?aguardar=true",
        data={"documento_id": doc_id, "canal_origem": "X"},
        files={"arquivo": (nome, conteudo, tipo)},
    )


def test_imagem_legivel_e_processada_como_documento_digital(cliente, monkeypatch):
    monkeypatch.setattr(
        "app.grafo.ler_imagem", lambda imagens: (LAUDO_TEP, Legibilidade(legivel=True))
    )
    r = _enviar_arquivo(cliente, "IMG-001", _png())
    assert r.status_code == 200
    assert (
        r.json()["decisao_roteamento"]["destino_principal"] == "Fila_Emergencia_Medica"
    )
    assert storage.existe("recebidos/IMG-001.png")  # original com a extensão certa


def test_imagem_ilegivel_vai_para_revisao_humana(cliente, monkeypatch):
    monkeypatch.setattr(
        "app.grafo.ler_imagem",
        lambda imagens: ("", Legibilidade(legivel=False, motivo="borrada")),
    )
    j = _enviar_arquivo(cliente, "IMG-002", _png()).json()
    assert j["decisao_roteamento"]["destino_principal"] == "Fila_Revisao_Humana"
    assert j["decisao_roteamento"]["requer_auditoria_humana"] is True
    assert "ilegível" in j["decisao_roteamento"]["justificativa_roteamento"]


def test_jpg_e_aceito_e_salvo_como_jpg(cliente, monkeypatch):
    monkeypatch.setattr(
        "app.grafo.ler_imagem", lambda imagens: (LAUDO_TEP, Legibilidade(legivel=True))
    )
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 50
    assert (
        _enviar_arquivo(cliente, "IMG-003", jpg, "foto.jpg", "image/jpeg").status_code
        == 200
    )
    assert storage.existe("recebidos/IMG-003.jpg")


def test_formato_nao_suportado_415(cliente):
    r = _enviar_arquivo(
        cliente, "IMG-004", b"isto nao e imagem", "falso.png", "image/png"
    )
    assert r.status_code == 415
    detalhe = r.json()["detail"]
    assert "Formato não aceito" in detalhe or "formato" in detalhe.lower()
    assert "PDF" in detalhe and "JPG" in detalhe and "PNG" in detalhe
    assert not storage.existe("recebidos/IMG-004.png")  # nada foi gravado


def test_arquivo_acima_de_10mb_413(cliente):
    grande = b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024 + 1)
    r = _enviar_arquivo(cliente, "IMG-005", grande)
    assert r.status_code == 413
    assert "10" in r.json()["detail"] and "MB" in r.json()["detail"]
    assert not storage.existe("recebidos/IMG-005.png")  # nada foi gravado


def test_imagem_com_id_repetido_409(cliente, monkeypatch):
    monkeypatch.setattr(
        "app.grafo.ler_imagem", lambda imagens: (LAUDO_TEP, Legibilidade(legivel=True))
    )
    assert _enviar_arquivo(cliente, "IMG-006", _png()).status_code == 200
    assert _enviar_arquivo(cliente, "IMG-006", _png()).status_code == 409


def test_id_usado_por_pdf_tambem_recusa_imagem_409(cliente, monkeypatch):
    monkeypatch.setattr(
        "app.grafo.ler_imagem", lambda imagens: (LAUDO_TEP, Legibilidade(legivel=True))
    )
    cliente.post(
        "/triagem/pdf?aguardar=true",
        data={"documento_id": "MIX-001", "canal_origem": "X"},
        files={
            "arquivo": (
                "a.pdf",
                pdf_com_texto(["Carlos Eduardo Mendes"]),
                "application/pdf",
            )
        },
    )
    assert _enviar_arquivo(cliente, "MIX-001", _png()).status_code == 409
