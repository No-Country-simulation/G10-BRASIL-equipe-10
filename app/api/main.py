import logging
import re
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app import config, storage
from app.api.ligacao_fila import ligar_fila_revisao
from app.api.tempo import MedirTempoMiddleware, configurar_log
from app.arquivos import (
    MAPA_EXTENSAO_FORMATO,
    MAPA_FORMATO_EXTENSOES,
    extensao_aceita,
    extensao_por_assinatura,
    montar_mensagem_formato_invalido,
    montar_mensagem_tamanho_excedido,
)
from app.eventos import servico_padrao, status_do_documento
from app.resposta import carregar_resultado
from app.schemas import DocumentoEntrada, ResultadoTriagem, validar_id
from app.servico import processar
from app.status import StatusDocumento
from app.storage import ObjetoJaExisteError

logger = logging.getLogger(__name__)

MAX_PDF = 10 * 1024 * 1024
MAX_ARQUIVO = 10 * 1024 * 1024
# H2.3.1 T3: documenta o formato combinado no OpenAPI (/docs). Usamos "responses" e não
# response_model porque estas rotas também devolvem 202 {"documento_id","status"}.
# RESPOSTA_RESULTADO = {200: {"model": ResultadoTriagem, "description": "Resultado da triagem"}}
RESPOSTA_RESULTADO = {"model": ResultadoTriagem, "description": "Resultado da triagem"}
RESPOSTAS_ERRO_ARQUIVO = {
    413: {"description": "Arquivo acima do limite permitido em MB"},
    415: {"description": "Formato de arquivo não aceito"},
}
# T4: charset limpo para o ID da rota /documentos — sem "/", "\" nem "." (e
# portanto sem ".."). A checagem acontece ANTES de montar qualquer caminho.
ID_LIMPO = re.compile(r"^[A-Za-z0-9_-]+$")


def _validar_id_limpo(documento_id: str):
    """Devolve None se o ID é limpo, ou 400 com o motivo (nunca monta caminho)."""
    if not ID_LIMPO.fullmatch(documento_id or ""):
        return JSONResponse(
            status_code=400,
            content={
                "detail": "documento_id inválido: use apenas letras, números, "
                "'-' e '_', sem '/', '\\', '..' ou espaços."
            },
        )
    return None


def _recebido(documento_id: str) -> bool:
    """True se o original já está em recebidos/ (em qualquer formato aceito)."""
    return any(
        storage.existe(f"recebidos/{documento_id}{e}") for e in storage.EXTENSOES
    )


def _responder_consulta(documento_id: str):
    """Resultado no formato combinado (validado), 202 se ainda processa, 404 se não existe."""
    try:
        resultado = carregar_resultado(documento_id)
    except ValidationError:
        logger.exception("Resultado salvo fora do formato: %s", documento_id)
        return JSONResponse(
            status_code=500,
            content={"detail": "resultado armazenado fora do formato combinado"},
        )
    if resultado is not None:
        resultado["status_documento"] = status_do_documento(documento_id, resultado)
        return JSONResponse(status_code=200, content=resultado)
    if _recebido(documento_id):
        return JSONResponse(
            status_code=202,
            content={"documento_id": documento_id, "status": "processando"},
        )
    return JSONResponse(status_code=404, content={"detail": "documento não encontrado"})


def criar_app(extrator=None) -> FastAPI:
    if extrator is None:
        from app.llm import extrair as extrator
    app = FastAPI(title="MediFlow", version="0.1")
    configurar_log()
    app.add_middleware(MedirTempoMiddleware)  # T8: log da duração de cada requisição

    @app.exception_handler(RequestValidationError)
    async def _422(request: Request, exc: RequestValidationError):
        erro = exc.errors()[0]
        campo = ".".join(str(p) for p in erro["loc"] if p != "body")
        msg = erro["msg"].replace("Value error, ", "")
        if erro["type"] == "missing":
            msg = f"campo obrigatório ausente: {campo}"
        return JSONResponse(status_code=422, content={"detail": msg})

    def _aceitar(
        documento_id: str, conteudo: bytes, extensao: str
    ) -> tuple[str | None, JSONResponse | None]:
        """H5.1.1: grava o original ANTES de qualquer processamento.

        Devolve (caminho_do_original, None) se aceito, ou (None, resposta_409) se o ID já foi
        recebido. A gravação é condicional (if_none_match="*"): dois envios simultâneos com o
        mesmo ID não passam os dois, e o original nunca é trocado.
        """
        try:
            salvo = storage.salvar_original(documento_id, conteudo, extensao)
        except ObjetoJaExisteError:
            return None, JSONResponse(
                status_code=409,
                content={"detail": f"documento_id já recebido: {documento_id}"},
            )
        try:  # H2.3.2: o 1º evento é a chegada (horário usado pela fila de revisão)
            servico_padrao().registrar(documento_id, StatusDocumento.RECEBIDO)
        except (OSError, ValueError):
            logger.exception("Não foi possível registrar o evento de status")
        return salvo["caminho_objeto"], None

    def _processar_original(
        documento_id: str, caminho: str, background: BackgroundTasks, aguardar: bool
    ):
        """H5.1.1 T3: o grafo recebe o CAMINHO do original (já gravado), não o arquivo."""
        if aguardar:
            return JSONResponse(
                status_code=200,
                content=processar(
                    documento_id, "", None, extrator, caminho_original=caminho
                ),
            )
        background.add_task(
            processar, documento_id, "", None, extrator, caminho_original=caminho
        )
        return {"documento_id": documento_id, "status": "recebido"}

    @app.post("/triagem", status_code=202, responses={200: RESPOSTA_RESULTADO})
    def enviar_texto(
        doc: DocumentoEntrada, background: BackgroundTasks, aguardar: bool = False
    ):
        caminho, recusa = _aceitar(
            doc.documento_id, doc.documento_texto.encode("utf-8"), ".txt"
        )
        if recusa or caminho is None:
            return recusa
        return _processar_original(doc.documento_id, caminho, background, aguardar)

    @app.post("/triagem/pdf", status_code=202, responses={200: RESPOSTA_RESULTADO})
    async def enviar_pdf(
        background: BackgroundTasks,
        documento_id: Annotated[str, Form()],
        canal_origem: Annotated[str, Form()],
        arquivo: Annotated[UploadFile, File()],
        aguardar: bool = False,
    ):
        try:
            documento_id = validar_id(documento_id)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"detail": str(e)})
        conteudo = await arquivo.read()
        if not conteudo.startswith(b"%PDF"):
            return JSONResponse(
                status_code=422, content={"detail": "o arquivo enviado não é um PDF"}
            )
        if len(conteudo) > MAX_PDF:
            return JSONResponse(
                status_code=413, content={"detail": "PDF acima de 10 MB"}
            )
        caminho, recusa = _aceitar(documento_id, conteudo, ".pdf")
        if recusa or caminho is None:
            return recusa
        return _processar_original(documento_id, caminho, background, aguardar)

    @app.post(
        "/triagem/arquivo",
        status_code=202,
        responses={200: RESPOSTA_RESULTADO, **RESPOSTAS_ERRO_ARQUIVO},
    )
    async def enviar_arquivo(
        background: BackgroundTasks,
        documento_id: Annotated[str, Form()],
        canal_origem: Annotated[str, Form()],
        arquivo: Annotated[UploadFile, File()],
        aguardar: bool = False,
    ):
        """H1.1.4 T2: validação de formato e tamanho antes de qualquer persistência.

        Formato não aceito devolve HTTP 415 com os formatos aceitos.
        Arquivo acima do limite devolve HTTP 413 com o limite em MB.
        """
        try:
            documento_id = validar_id(documento_id)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"detail": str(e)})

        limite_mb = config.tamanho_maximo_mb()
        max_bytes = limite_mb * 1024 * 1024
        formatos = config.formatos_aceitos()
        msg_formato = montar_mensagem_formato_invalido(formatos)
        msg_tamanho = montar_mensagem_tamanho_excedido(limite_mb)

        # 1. Validação de extensão informada no nome do arquivo
        if arquivo.filename:
            ext_nome = Path(arquivo.filename).suffix.lower()
            if ext_nome and not extensao_aceita(arquivo.filename, formatos):
                return JSONResponse(status_code=415, content={"detail": msg_formato})

        # 2. Validação de tamanho (lê no máximo limite + 1 byte para não estourar memória)
        conteudo = await arquivo.read(max_bytes + 1)
        if len(conteudo) > max_bytes:
            return JSONResponse(status_code=413, content={"detail": msg_tamanho})

        # 3. Validação de assinatura do arquivo (bytes iniciais de PDF, PNG e JPEG)
        extensao = extensao_por_assinatura(conteudo)
        if extensao is None:
            return JSONResponse(status_code=415, content={"detail": msg_formato})

        # Confere se o formato detectado pela assinatura está na lista de formatos aceitos
        formato_detectado = MAPA_EXTENSAO_FORMATO.get(extensao)
        if formato_detectado not in formatos:
            return JSONResponse(status_code=415, content={"detail": msg_formato})

        # Se o nome do arquivo tinha extensão aceita, confere se bate com a assinatura real
        if arquivo.filename:
            ext_nome = Path(arquivo.filename).suffix.lower()
            if ext_nome and ext_nome not in MAPA_FORMATO_EXTENSOES.get(
                formato_detectado, set()
            ):
                return JSONResponse(status_code=415, content={"detail": msg_formato})

        caminho, recusa = _aceitar(documento_id, conteudo, extensao)
        if recusa or caminho is None:
            return recusa
        return _processar_original(documento_id, caminho, background, aguardar)

    @app.get("/triagem/{documento_id}", responses={200: RESPOSTA_RESULTADO})
    def consultar(documento_id: str):
        try:
            validar_id(documento_id)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"detail": str(e)})
        return _responder_consulta(documento_id)

    @app.get("/documentos/{documento_id}", responses={200: RESPOSTA_RESULTADO})
    def consultar_documento(documento_id: str):
        """H2.3.1 T3: mesmo formato combinado de GET /triagem/{id} (resultado validado)."""
        recusa = _validar_id_limpo(documento_id)
        if recusa:
            return recusa
        return _responder_consulta(documento_id)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    ligar_fila_revisao(app)  # H4.2.1: GET /filas/revisao
    return app


try:
    app = criar_app()
except Exception:
    # Mostra o erro real no terminal em vez de subir uma aplicação vazia sem explicação.
    logger.exception("Falha ao criar a aplicação")
    app = None
