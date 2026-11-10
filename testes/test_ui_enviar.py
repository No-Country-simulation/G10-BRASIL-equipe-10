import json
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parents[1]
PAGINA = str(RAIZ / "ui" / "pages" / "1_Documentos.py")
REGRAS = json.loads((RAIZ / "config" / "regras.json").read_text(encoding="utf-8"))
TEXTO = "RECEITUARIO sintetico. Paciente: Fulano de Tal. Amoxicilina 500mg."


class Resp:
    def __init__(self, status, corpo=None):
        self.status_code, self._corpo = status, corpo

    def json(self):
        if self._corpo is None:
            raise ValueError("sem json")
        return self._corpo


@pytest.fixture(autouse=True)
def _sem_api_url(monkeypatch):
    monkeypatch.delenv("API_URL", raising=False)


@pytest.fixture
def api(monkeypatch):
    """Substitui requests.post: nenhum teste chama a rede de verdade."""
    reg = {
        "chamadas": [],
        "resposta": Resp(202, {"documento_id": "DOC-TESTE1", "status": "recebido"}),
    }

    def falso_post(url, **kw):
        reg["chamadas"].append((url, kw))
        if isinstance(reg["resposta"], Exception):
            raise reg["resposta"]
        return reg["resposta"]

    monkeypatch.setattr(requests, "post", falso_post)
    return reg


def abrir():
    return AppTest.from_file(PAGINA, default_timeout=10).run()


def enviar(at, texto=TEXTO, doc_id="DOC-TESTE1", confirmar=True):
    at.text_input(key="documento_id").set_value(doc_id)
    at.text_area(key="texto_documento").set_value(texto)
    if confirmar:
        at.checkbox(key="confirmo_sintetico").check()
    at.button[0].click().run()
    return at


# ---- T5: a tela ----
def test_tela_abre_sem_erro():
    at = abrir()
    assert not at.exception and not at.error


def test_elementos_do_card():
    at = abrir()
    assert at.text_input(key="documento_id").label == "ID do documento"
    assert at.selectbox(key="canal_origem").label == "Canal de origem"
    assert at.text_area(key="texto_documento").label == "Texto do documento"
    assert at.button[0].label == "Enviar"


def test_canais_vem_do_regras_json():
    at = abrir()
    assert list(at.selectbox(key="canal_origem").options) == REGRAS["canais_origem"]
    assert "Pronto_Socorro" in at.selectbox(key="canal_origem").options


def test_id_ja_vem_preenchido():
    assert abrir().text_input(key="documento_id").value.startswith("DOC-")


def test_aviso_de_dados_sensiveis_e_exibido():
    assert any("LGPD" in i.value for i in abrir().info)


# ---- T6: ligação com o endpoint ----
def test_sucesso_mostra_id_e_status_e_chama_a_api_do_jeito_certo(api):
    at = enviar(abrir())
    assert not at.error
    assert "DOC-TESTE1" in at.success[0].value and "recebido" in at.success[0].value
    url, kw = api["chamadas"][0]
    assert url == "http://localhost:8000/triagem"
    assert kw["json"] == {
        "documento_id": "DOC-TESTE1",
        "tipo_arquivo": "TEXTO",
        "documento_texto": TEXTO,
        "canal_origem": "Pronto_Socorro",
    }
    assert isinstance(kw["timeout"], tuple)  # sem timeout a tela poderia travar
    assert kw["allow_redirects"] is False


def test_apos_sucesso_o_texto_e_apagado_da_sessao(api):
    at = enviar(abrir())
    assert at.text_area(key="texto_documento").value == ""
    assert at.checkbox(key="confirmo_sintetico").value is False
    novo = at.text_input(key="documento_id").value
    assert novo != "DOC-TESTE1" and novo.startswith("DOC-")


def test_url_da_api_vem_de_variavel_de_ambiente(api, monkeypatch):
    monkeypatch.setenv("API_URL", "https://api.exemplo.com/")
    at = enviar(abrir())
    assert api["chamadas"][0][0] == "https://api.exemplo.com/triagem"
    assert not at.warning  # https: sem aviso


def test_http_fora_do_local_mostra_aviso(monkeypatch):
    monkeypatch.setenv("API_URL", "http://api.exemplo.com")
    assert any("HTTPS" in w.value for w in abrir().warning)


def test_http_em_rede_interna_do_container_nao_mostra_aviso(monkeypatch):
    # Nome de container na rede do Podman: host sem ponto, tráfego interno.
    monkeypatch.setenv("API_URL", "http://mediflow-app:8000")
    at = abrir()
    assert not at.exception
    assert not any("HTTPS" in w.value for w in at.warning)


def test_url_invalida_bloqueia_a_tela(monkeypatch):
    monkeypatch.setenv("API_URL", "ftp://x")
    at = abrir()
    assert at.error and not at.button


@pytest.mark.parametrize(
    "status,detalhe",
    [
        (409, "documento_id já recebido: DOC-TESTE1"),
        (413, "Arquivo acima do limite de 10 MB."),
        (415, "Formato não aceito. Envie PDF, JPG ou PNG."),
        (422, "documento vazio"),
    ],
)
def test_erro_mostra_a_mensagem_do_servidor(api, status, detalhe):
    api["resposta"] = Resp(status, {"detail": detalhe})
    at = enviar(abrir())
    assert at.error[0].value == detalhe
    assert not at.success
    assert at.text_area(key="texto_documento").value == TEXTO  # não perde o que digitou


def test_erro_do_servidor_sem_detalhe_mostra_mensagem_generica(api):
    api["resposta"] = Resp(500)
    at = enviar(abrir())
    assert "HTTP 500" in at.error[0].value


def test_falha_de_rede_nao_vaza_detalhes_internos(api):
    api["resposta"] = requests.ConnectionError(
        "HTTPConnectionPool(host='10.0.0.5', port=8000)"
    )
    at = enviar(abrir())
    assert (
        "10.0.0.5" not in at.error[0].value
        and "HTTPConnectionPool" not in at.error[0].value
    )


# ---- validações locais: nada é enviado ----
@pytest.mark.parametrize(
    "texto,confirmar,esperado",
    [
        pytest.param("   ", True, "documento vazio", id="texto-vazio"),
        pytest.param(TEXTO, False, "dados sintéticos", id="sem-confirmacao"),
        pytest.param("x" * 200_001, True, "acima de", id="texto-grande"),
    ],
)
def test_validacao_local_nao_chama_a_api(api, texto, confirmar, esperado):
    at = enviar(abrir(), texto=texto, confirmar=confirmar)
    assert esperado in at.error[0].value
    assert api["chamadas"] == []


def test_id_vazio_nao_chama_a_api(api):
    at = enviar(abrir(), doc_id="  ")
    assert at.error[0].value == "Informe o ID do documento."
    assert api["chamadas"] == []


def test_texto_no_limite_e_enviado_inteiro_sem_cortar(api):
    texto = "x" * 200_000
    enviar(abrir(), texto=texto)
    assert (
        api["chamadas"][0][1]["json"]["documento_texto"] == texto
    )  # nada foi truncado
