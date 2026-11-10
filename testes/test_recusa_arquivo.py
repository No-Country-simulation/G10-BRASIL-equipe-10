"""Testes da história H1.1.4 — Saber por que um arquivo foi recusado.

Critérios de aceite:
- Dado um formato não suportado (ex.: .docx), quando eu envio, então a mensagem lista os formatos aceitos.
- Dado um arquivo acima do tamanho máximo, quando eu envio, então a mensagem informa o limite.

Tarefas validadas:
- T1: formatos_aceitos e tamanho_maximo_mb em config/regras.json e app.config
- T2: validação de formato (extensão e assinatura) e tamanho antes de gravar (HTTP 415 e 413)
- T3: mensagens curtas em português sem termos técnicos
- T4: exibição com st.error no Streamlit e server.maxUploadSize alinhado
- T5: cenários de recusa mantêm o armazenamento vazio
"""

import json
import tomllib
from pathlib import Path

from PIL import Image

from app import config, storage
from app.arquivos import (
    montar_mensagem_formato_invalido,
    montar_mensagem_tamanho_excedido,
)

RAIZ = Path(__file__).resolve().parents[1]
REGRAS_PATH = RAIZ / "config" / "regras.json"
CONFIG_TOML_PATH = RAIZ / ".streamlit" / "config.toml"


# ---- T1: Configuração de formatos e limite ----
def test_regras_json_contem_formatos_aceitos_e_tamanho_maximo():
    dados = json.loads(REGRAS_PATH.read_text(encoding="utf-8"))
    assert "formatos_aceitos" in dados
    assert "tamanho_maximo_mb" in dados
    assert dados["tamanho_maximo_mb"] == 10
    assert set(dados["formatos_aceitos"]) >= {"PDF", "JPG", "PNG"}


def test_app_config_le_formatos_e_limite():
    formatos = config.formatos_aceitos()
    limite = config.tamanho_maximo_mb()
    assert isinstance(formatos, list)
    assert set(formatos) >= {"PDF", "JPG", "PNG"}
    assert limite == 10


# ---- T3: Mensagens em português sem jargões técnicos ----
def test_mensagens_sao_claras_e_em_portugues():
    msg_formato = montar_mensagem_formato_invalido(["PDF", "JPG", "PNG"])
    assert msg_formato == "Formato não aceito. Envie PDF, JPG ou PNG."
    assert "PDF" in msg_formato and "JPG" in msg_formato and "PNG" in msg_formato

    msg_tamanho = montar_mensagem_tamanho_excedido(10)
    assert msg_tamanho == "Arquivo acima do limite de 10 MB."
    assert "10 MB" in msg_tamanho


# ---- T2 & T5: Testes de API e armazenamento vazio ----
def _enviar(
    cliente, doc_id, conteudo, nome_arquivo, tipo_mime="application/octet-stream"
):
    return cliente.post(
        "/triagem/arquivo?aguardar=true",
        data={"documento_id": doc_id, "canal_origem": "Pronto_Socorro"},
        files={"arquivo": (nome_arquivo, conteudo, tipo_mime)},
    )


def test_docx_devolve_415_com_lista_e_armazenamento_vazio(cliente):
    conteudo_docx = b"PK\x03\x04" + b"simulando_conteudo_docx_zip"
    r = _enviar(
        cliente,
        "DOC-REC-001",
        conteudo_docx,
        "laudo.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert r.status_code == 415
    detalhe = r.json()["detail"]
    assert "Formato não aceito" in detalhe
    assert "PDF" in detalhe and "JPG" in detalhe and "PNG" in detalhe
    assert not storage.existe("recebidos/DOC-REC-001.docx")
    assert storage.listar("recebidos/") == []


def test_extensao_invalida_com_bytes_falsos_devolve_415_e_armazenamento_vazio(cliente):
    r = _enviar(cliente, "DOC-REC-002", b"dados aleatorios", "planilha.xlsx")

    assert r.status_code == 415
    detalhe = r.json()["detail"]
    assert "Formato não aceito" in detalhe
    assert "PDF" in detalhe and "JPG" in detalhe and "PNG" in detalhe
    assert storage.listar("recebidos/") == []


def test_extensao_png_mas_sem_assinatura_valida_devolve_415(cliente):
    r = _enviar(
        cliente, "DOC-REC-003", b"isto nao tem assinatura png", "foto.png", "image/png"
    )

    assert r.status_code == 415
    detalhe = r.json()["detail"]
    assert "Formato não aceito" in detalhe
    assert "PDF" in detalhe and "JPG" in detalhe and "PNG" in detalhe
    assert not storage.existe("recebidos/DOC-REC-003.png")
    assert storage.listar("recebidos/") == []


def test_extensao_pdf_mas_sem_assinatura_valida_devolve_415(cliente):
    r = _enviar(
        cliente,
        "DOC-REC-004",
        b"isto nao comeca com %PDF",
        "laudo.pdf",
        "application/pdf",
    )

    assert r.status_code == 415
    detalhe = r.json()["detail"]
    assert "Formato não aceito" in detalhe
    assert "PDF" in detalhe and "JPG" in detalhe and "PNG" in detalhe
    assert not storage.existe("recebidos/DOC-REC-004.pdf")
    assert storage.listar("recebidos/") == []


def test_arquivo_acima_do_limite_devolve_413_e_informa_limite(cliente):
    limite_mb = config.tamanho_maximo_mb()
    tamanho_excedido = limite_mb * 1024 * 1024 + 1024
    conteudo_grande = b"%PDF" + b"0" * (tamanho_excedido - 4)

    r = _enviar(
        cliente, "DOC-REC-005", conteudo_grande, "grande.pdf", "application/pdf"
    )

    assert r.status_code == 413
    detalhe = r.json()["detail"]
    assert f"{limite_mb} MB" in detalhe
    assert "Arquivo acima do limite" in detalhe
    assert not storage.existe("recebidos/DOC-REC-005.pdf")
    assert storage.listar("recebidos/") == []


def test_arquivo_valido_e_gravado_no_armazenamento(cliente, monkeypatch):
    from app.schemas import Legibilidade
    from testes.conftest import LAUDO_TEP

    monkeypatch.setattr(
        "app.grafo.ler_imagem",
        lambda imagens: (LAUDO_TEP, Legibilidade(legivel=True)),
    )
    import io

    buf = io.BytesIO()
    Image.new("RGB", (60, 30), "white").save(buf, "PNG")
    conteudo_valido = buf.getvalue()

    r = _enviar(cliente, "DOC-OK-001", conteudo_valido, "foto.png", "image/png")
    assert r.status_code == 200
    assert storage.existe("recebidos/DOC-OK-001.png")
    assert "recebidos/DOC-OK-001.png" in storage.listar("recebidos/")


# ---- T4: Alinhamento de server.maxUploadSize e exibição no Streamlit ----
def test_streamlit_config_toml_alinha_max_upload_size():
    conteudo = tomllib.loads(CONFIG_TOML_PATH.read_text(encoding="utf-8"))
    assert "server" in conteudo
    assert "maxUploadSize" in conteudo["server"]
    assert conteudo["server"]["maxUploadSize"] == config.tamanho_maximo_mb()


def test_openapi_documenta_413_e_415_na_rota_de_arquivo(cliente):
    esquema = cliente.get("/openapi.json").json()
    respostas = esquema["paths"]["/triagem/arquivo"]["post"]["responses"]
    assert "413" in respostas
    assert "415" in respostas


def test_streamlit_exibe_erro_no_envio_de_arquivo_recusado_pelo_servidor(monkeypatch):
    import requests
    from streamlit.testing.v1 import AppTest

    class _ArquivoFalso:
        name = "laudo.docx"
        type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        size = 512

        def getvalue(self):
            return b"PK\x03\x04conteudo_docx"

    class _RespFalsa:
        status_code = 415

        def json(self):
            return {"detail": "Formato não aceito. Envie PDF, JPG ou PNG."}

    chamadas = []

    def _falso_post(url, **kw):
        chamadas.append((url, kw))
        return _RespFalsa()

    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.setattr(requests, "post", _falso_post)

    pagina = str(RAIZ / "ui" / "pages" / "1_Documentos.py")
    at = AppTest.from_file(pagina, default_timeout=10).run()
    at.session_state["arquivo_0"] = _ArquivoFalso()
    at.text_input(key="documento_id").set_value("DOC-UI-415")
    at.checkbox(key="confirmo_sintetico").check()
    at.button[0].click().run()

    assert len(chamadas) == 1
    assert chamadas[0][0].endswith("/triagem/arquivo")
    assert at.error[0].value == "Formato não aceito. Envie PDF, JPG ou PNG."
    assert not at.success


def test_streamlit_bloqueia_arquivo_acima_do_limite_localmente(monkeypatch):
    import requests
    from streamlit.testing.v1 import AppTest

    class _ArquivoGrande:
        name = "exame.pdf"
        type = "application/pdf"
        size = (config.tamanho_maximo_mb() * 1024 * 1024) + 1

        def getvalue(self):
            return b"%PDF"

    chamadas = []
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.setattr(requests, "post", lambda url, **kw: chamadas.append(url))

    pagina = str(RAIZ / "ui" / "pages" / "1_Documentos.py")
    at = AppTest.from_file(pagina, default_timeout=10).run()
    at.session_state["arquivo_0"] = _ArquivoGrande()
    at.text_input(key="documento_id").set_value("DOC-UI-413")
    at.checkbox(key="confirmo_sintetico").check()
    at.button[0].click().run()

    assert chamadas == []
    assert (
        at.error[0].value
        == f"Arquivo acima do limite de {config.tamanho_maximo_mb()} MB."
    )
