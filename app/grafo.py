import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from . import config
from . import roteamento as rt
from .arquivos import extensao_por_assinatura
from .llm import extrair, ler_imagem
from .modelos import Classificacao, Destino, TipoDocumento
from .modelos.destino import DecisaoRoteamento, Notificacao
from .pdf import PDFSemTexto, extrair_texto_pdf, renderizar_paginas
from .resposta import falha_de_processamento, montar_resposta
from .schemas import Extracao
from .validacao import FORA_DAS_CATEGORIAS, validar
from .validacao_obrigatorios import campos_faltantes  # H4.1.2 T2

logger = logging.getLogger(__name__)


# Dicionário compartilhado entre os nós do LangGraph
class Estado(TypedDict, total=False):
    documento_id: str
    texto: str
    pdf_bytes: bytes | None  # na prática: bytes do arquivo (PDF, PNG ou JPG)
    limite_confianca: float  # H1.2.2 T2: carregado uma vez por execução do grafo
    extracao: Extracao | None  # objeto Extracao (None se falhou)
    classificacao: (
        Classificacao | None
    )  # objeto Classificacao montado pelo nó classificar
    erro: str | None
    problemas: list
    score: float
    destino: Destino
    regra: str  # id da regra aplicada (R-URGENCIA, R-RECEITA...)
    requer_revisao: bool
    motivo_revisao: str | None  # motivos unidos por "; " (compatibilidade)
    motivos_revisao: list[str]  # H4.1.2 T3: um item por motivo
    justificativa: str
    notificacao: Notificacao | None
    tipo_arquivo: str  # "TEXTO", "PDF" ou "Imagem"
    ilegivel: bool
    resultado: dict
    decisao_roteamento: (
        DecisaoRoteamento | None
    )  # submodelo DecisaoRoteamento (H2.1.1 T1/T4)


def montar_classificacao(extracao, score) -> Classificacao:
    """T3: a classificação que o analista vê vem da extração JÁ validada.

    O score é o RECALCULADO por app/validacao.py (não o que o LLM deu).
    """
    return Classificacao(
        tipo_documento=extracao.tipo_documento,
        especialidade=extracao.especialidade,
        nivel_prioridade=extracao.nivel_prioridade,
        score_confianca_classificacao=score,
    )


def construir_grafo(extrator=extrair, classificador=montar_classificacao, leitor=None):
    """'extrator', 'classificador' e 'leitor' podem ser trocados por versões falsas nos
    testes (sem LLM, sem rede)."""
    # Resolvido na chamada (e não na assinatura) para que os testes possam trocar
    # app.grafo.ler_imagem com monkeypatch.
    leitor = leitor or ler_imagem

    def n_ler_entrada(s: Estado):
        # H1.2.2 T2: carrega o limite de confiança uma única vez por execução do grafo
        limite = config.limite_confianca()
        dados = s.get("pdf_bytes")
        if not dados:
            return {"tipo_arquivo": "TEXTO", "limite_confianca": limite}
        try:
            if extensao_por_assinatura(dados) == ".pdf":
                try:
                    return {
                        "texto": extrair_texto_pdf(dados),
                        "tipo_arquivo": "PDF",
                        "limite_confianca": limite,
                    }
                except PDFSemTexto:
                    imagens, tipo = renderizar_paginas(dados), "PDF"  # T2: escaneado
            else:
                imagens, tipo = [dados], "Imagem"
            texto, leg = leitor(imagens)  # T4
        except Exception as e:
            logger.exception("Falha ao ler a entrada")
            return {"texto": "", "erro": str(e), "limite_confianca": limite}

        if not leg.legivel or not texto.strip():  # T5
            motivo = leg.motivo or "sem texto reconhecível"
            return {
                "texto": "",
                "tipo_arquivo": tipo,
                "ilegivel": True,
                "extracao": None,
                "score": 0.0,
                "motivos_revisao": ["ilegível"],  # H4.1.5 T1
                "motivo_revisao": "ilegível",
                "problemas": [f"ilegível: {motivo}"],
                "limite_confianca": limite,
            }
        return {"texto": texto, "tipo_arquivo": tipo, "limite_confianca": limite}

    def n_extrair(s: Estado):
        if s.get("erro"):
            return {"extracao": None}
        try:
            return {"extracao": extrator(s["texto"])}
        except Exception as e:
            logger.exception("Falha na extração automática")
            return {"extracao": None, "erro": f"Falha na extração automática: {e}"}

    def n_validar(s: Estado):
        if s.get("erro") or s.get("extracao") is None:
            return {"problemas": [], "score": 0.0}
        extracao, problemas, score = validar(s["extracao"], s["texto"])
        saida = {"extracao": extracao, "problemas": problemas, "score": score}
        # H4.1.2 T2/T3: lista todas as faltas de uma vez
        faltas = campos_faltantes(extracao.tipo_documento, extracao.model_dump())
        if faltas:
            # "problemas" já aparece no JSON e na fila (ResultadoTriagem.problemas)
            saida["problemas"] = list(problemas) + [
                f for f in faltas if f not in problemas
            ]
            saida["motivos_revisao"] = faltas
            saida["motivo_revisao"] = "; ".join(faltas)
        return saida

    def n_classificar(s: Estado):
        if s.get("erro") or s.get("extracao") is None:
            return {"classificacao": None}
        try:
            return {"classificacao": classificador(s["extracao"], s["score"])}
        except Exception:
            logger.exception("Falha na classificação automática")
            return {"classificacao": None}

    def _eh_fora_das_categorias(s: Estado) -> bool:
        cl = s.get("classificacao")
        ext = s.get("extracao")
        tipo = getattr(cl, "tipo_documento", None) or getattr(
            ext, "tipo_documento", None
        )
        return str(tipo or "") == TipoDocumento.NAO_IDENTIFICADO.value

    def _motivos(s: Estado) -> list[str]:
        """H4.1.2 T3: reúne todos os motivos de revisão do estado."""
        motivos = list(s.get("motivos_revisao") or [])
        if not motivos and s.get("motivo_revisao"):
            motivos = [s["motivo_revisao"]]
        if _eh_fora_das_categorias(s) and FORA_DAS_CATEGORIAS not in motivos:
            motivos.append(FORA_DAS_CATEGORIAS)
        return motivos

    def n_decidir(s: Estado):
        """H2.1.1 T3: nó decidir que chama a função pura de roteamento
        aplicando precedência urgência → revisão → tipo.
        """
        limite = (
            s["limite_confianca"]
            if "limite_confianca" in s
            else config.limite_confianca()
        )
        decisao = rt.criar_decisao_roteamento(s, limite_confianca=limite)
        motivos = _motivos(s)
        # H4.1.2: qualquer motivo (ex.: campo faltante) força a revisão, inclusive
        # na decisão que vai para o JSON (a notificação, se houver, é mantida)
        if motivos and decisao.destino_principal != Destino.FILA_REVISAO_HUMANA:
            decisao = decisao.model_copy(
                update={
                    "destino_principal": Destino.FILA_REVISAO_HUMANA,
                    "requer_auditoria_humana": True,
                    "regra_aplicada": "R-REVISAO",
                    "justificativa_roteamento": (
                        "Enviado à revisão humana (regra R-REVISAO): "
                        + "; ".join(motivos)
                    ),
                }
            )
        requer = decisao.requer_auditoria_humana or bool(motivos)
        return {
            "destino": str(decisao.destino_principal),
            "regra": decisao.regra_aplicada,
            "requer_revisao": requer,
            "motivos_revisao": motivos if requer else [],
            "motivo_revisao": "; ".join(motivos) if requer and motivos else None,
            "justificativa": decisao.justificativa_roteamento,
            "notificacao": decisao.notificacao_gerada.model_dump()
            if decisao.notificacao_gerada
            else None,
            "decisao_roteamento": decisao,
        }

    def n_rotear(s: Estado):
        """H2.1.1 T4: grava a decisão no estado e no resultado.
        No MVP, a fila de um setor é a consulta aos resultados com aquele destino."""
        decisao = s.get("decisao_roteamento")
        if decisao is not None:
            return {
                "destino": str(decisao.destino_principal),
                "regra": decisao.regra_aplicada,
                "requer_revisao": decisao.requer_auditoria_humana,
                "motivos_revisao": [],
                "motivo_revisao": None,
                "justificativa": decisao.justificativa_roteamento,
                "notificacao": (
                    decisao.notificacao_gerada.model_dump()
                    if decisao.notificacao_gerada
                    else None
                ),
            }

    def n_enviar_revisao(s: Estado):
        """H1.2.3 T2: envia documentos fora das categorias ou com pendências para revisão humana."""
        decisao = s.get("decisao_roteamento")
        motivos = _motivos(s)
        motivo = "; ".join(motivos) if motivos else None
        if decisao is not None:
            return {
                "destino": str(Destino.FILA_REVISAO_HUMANA),
                "regra": decisao.regra_aplicada,
                "requer_revisao": True,
                "motivos_revisao": motivos,
                "motivo_revisao": motivo,
                "justificativa": decisao.justificativa_roteamento,
                "notificacao": (
                    decisao.notificacao_gerada.model_dump()
                    if decisao.notificacao_gerada
                    else None
                ),
            }
        return {
            "destino": str(Destino.FILA_REVISAO_HUMANA),
            "regra": "R-REVISAO",
            "requer_revisao": True,
            "motivos_revisao": motivos,
            "motivo_revisao": motivo,
        }

    def _aresta_decisao(s: Estado) -> str:
        """H1.2.3 T2: tipo 'Não identificado' (ou qualquer revisão) leva sempre a enviar_revisao."""
        if (
            _eh_fora_das_categorias(s)
            or s.get("requer_revisao")
            or s.get("motivos_revisao")  # H4.1.2
            or s.get("destino") == Destino.FILA_REVISAO_HUMANA.value
        ):
            return "enviar_revisao"
        return "rotear"

    def n_montar_resultado(s: Estado):
        """H2.3.1 T2: último nó. Monta e valida o ResultadoTriagem.

        Se o resultado sair fora do formato (ValidationError), NÃO entrega resposta parcial:
        o documento vai para a revisão com o motivo "falha de processamento".
        """
        doc_id = s.get("documento_id", "")
        try:
            return {"resultado": montar_resposta(doc_id, s).model_dump(mode="json")}
        except Exception as e:
            logger.exception("Resultado fora do formato")
            resultado = falha_de_processamento(doc_id, str(e))
            return {
                "destino": str(Destino.FILA_REVISAO_HUMANA),
                "regra": "R-REVISAO",
                "requer_revisao": True,
                "motivos_revisao": ["falha de processamento"],
                "motivo_revisao": "falha de processamento",
                "classificacao": None,
                "notificacao": None,
                "justificativa": resultado.decisao_roteamento.justificativa_roteamento,
                "resultado": resultado.model_dump(mode="json"),
            }

    g = StateGraph(Estado)
    for nome, fn in [
        ("ler_entrada", n_ler_entrada),
        ("extrair", n_extrair),
        ("validar", n_validar),
        ("classificar", n_classificar),
        ("decidir", n_decidir),
        ("rotear", n_rotear),
        ("enviar_revisao", n_enviar_revisao),
        ("montar_resultado", n_montar_resultado),
    ]:
        g.add_node(nome, fn)

    g.set_entry_point("ler_entrada")
    # T5: ilegível vai direto para a revisão, sem passar por extrair/validar/classificar
    g.add_conditional_edges(
        "ler_entrada",
        lambda s: "decidir" if s.get("ilegivel") else "extrair",
        {"decidir": "decidir", "extrair": "extrair"},
    )
    g.add_edge("extrair", "validar")
    g.add_edge("validar", "classificar")
    g.add_edge("classificar", "decidir")
    g.add_conditional_edges(
        "decidir",
        _aresta_decisao,
        {"rotear": "rotear", "enviar_revisao": "enviar_revisao"},
    )
    g.add_edge("rotear", "montar_resultado")
    g.add_edge("enviar_revisao", "montar_resultado")
    g.add_edge("montar_resultado", END)
    return g.compile()


def triar(
    texto: str,
    extrator=extrair,
    pdf_bytes: bytes | None = None,
    classificador=montar_classificacao,
    leitor=None,
    documento_id: str = "",
) -> dict:
    return construir_grafo(extrator, classificador, leitor).invoke(
        {"texto": texto, "pdf_bytes": pdf_bytes, "documento_id": documento_id}
    )
