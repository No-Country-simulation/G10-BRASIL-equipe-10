"""Regras de roteamento de documentos clínicos (H2.1.1).

Precedência estrita do edital: urgência → revisão → tipo.
Funções puras, determinísticas e sem chamadas a LLM.
"""

import unicodedata
from collections.abc import Mapping
from typing import Any, NamedTuple

from . import config
from .modelos.classificacao import TipoDocumento
from .modelos.destino import DecisaoRoteamento, Destino, Notificacao
from .validacao import (
    FORA_DAS_CATEGORIAS,
    MOTIVO_BAIXA_CONFIANCA,
    MOTIVO_FALHA_EXTRACAO,
    problemas_bloqueantes,
)

# ---------- Identificadores das regras (H2.2.1) ----------
R_RECEITA = "R-RECEITA"
R_GUIA = "R-GUIA"
R_PRONTUARIO = "R-PRONTUARIO"
R_URGENCIA = "R-URGENCIA"
R_REVISAO = "R-REVISAO"

# id -> descrição curta de CADA regra de decisão (fonte única dos textos)
REGRAS = {
    R_REVISAO: "qualquer dúvida na leitura ou na classificação exige revisão humana",
    R_URGENCIA: "urgência tem precedência sobre a rota de rotina",
    R_RECEITA: "receitas de rotina seguem para a farmácia",
    R_GUIA: "guias de rotina seguem para a auditoria de autorizações",
    R_PRONTUARIO: "laudos, altas e atestados de rotina seguem para o prontuário",
}

# ---------- Prioridade e notificações ----------
PRIORIDADE_URGENTE = "Urgente"
PRIORIDADE_ROTINA = "Rotina"
CANAL_PLANTAO = "Alerta_Plantao_Medico"
MSG_URGENCIA_AMBIGUA = "Possível urgência com dados ambíguos: revisar com prioridade."
TAMANHO_MAX_ERRO = 80  # caracteres do erro citados no motivo
MAX_MOTIVOS = 4

# ---------- Rotas de rotina por tipo de documento ----------
ROTA_RECEITA = (Destino.FARMACIA_HOSPITALAR, R_RECEITA)
ROTA_GUIA = (Destino.AUDITORIA_AUTORIZACOES, R_GUIA)
ROTA_PRONTUARIO = (Destino.PRONTUARIO_ELETRONICO, R_PRONTUARIO)
PADRAO = Destino.PRONTUARIO_ELETRONICO

# Tipos que sempre vão para revisão humana
TIPOS_REVISAO = (TipoDocumento.DESCONHECIDO.value, TipoDocumento.NAO_IDENTIFICADO.value)

# ---------- Leitura dos atributos (_extrair_atributos) ----------
ACHADO_PADRAO = "Achado crítico"
SCORE_PADRAO = 1.0
# nomes aceitos em kwargs, na ordem de preferência
NOMES_SCORE = ("score", "score_confianca_classificacao")
NOMES_URGENCIA = ("urgencia", "urgente", "prioridade", "nivel_prioridade")
NOMES_PENDENCIA = ("pendencia", "pendencias", "requer_revisao", "revisao")


def _normalizar(texto: Any) -> str:
    """Sem acentos e em minúsculas: 'Relatório de Alta' == 'relatorio de alta'."""
    t = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in t if unicodedata.category(c) != "Mn").strip().lower()


# Grafias aceitas para cada rota. Maiúsculas e acentos não importam, então
# basta listar cada nome uma vez (o enum é a grafia oficial; o resto são
# variações que já chegaram em documentos reais / testes).
_GRAFIAS_POR_ROTA = {
    ROTA_RECEITA: (TipoDocumento.RECEITUARIO_MEDICO,),
    ROTA_GUIA: (TipoDocumento.GUIA_PROCEDIMENTO, "Guia"),
    # H2.1.3 T1: laudos de exame, relatórios de alta e atestados -> Prontuario_Eletronico
    ROTA_PRONTUARIO: (
        TipoDocumento.LAUDO_IMAGEM,
        TipoDocumento.LAUDO_LABORATORIAL,
        "Laudo de Exame",
        "Laudo",
        TipoDocumento.RELATORIO_ALTA,
        "Relatório de Alta/Internação",
        "Relatório de Internação",
        "Alta",
        TipoDocumento.ATESTADO_MEDICO,
        "Atestado",
    ),
}
ROTA_POR_TIPO = {
    _normalizar(grafia): rota
    for rota, grafias in _GRAFIAS_POR_ROTA.items()
    for grafia in grafias
}


def _rota_do_tipo(tipo: Any) -> tuple[Destino, str] | None:
    """(destino, regra) de rotina do tipo, ou None se o tipo não tiver rota própria."""
    return ROTA_POR_TIPO.get(_normalizar(tipo))


def _eh_urgente(valor: Any) -> bool:
    """'Urgente' em qualquer caixa (não aceita True: booleanos são tratados à parte)."""
    return isinstance(valor, str) and _normalizar(valor) == _normalizar(
        PRIORIDADE_URGENTE
    )


def _motivo_falha(erro: Any) -> str:
    return f"{MOTIVO_FALHA_EXTRACAO} ({str(erro)[:TAMANHO_MAX_ERRO]})"


def descricao_regra(regra: str) -> str:
    """Descrição curta da regra (ex.: 'R-RECEITA' -> 'receitas de rotina seguem para a farmácia')."""
    return REGRAS.get(regra, "")


def decidir_destino(
    estado_ou_tipo: Mapping[str, Any] | str, *args, **kwargs
) -> Destino:
    """Função pura que devolve o destino aplicando estritamente a precedência:
    urgência → revisão → tipo (H2.1.1 T2).

    Retorna uma instância de Destino (que também é str).
    """
    a = _extrair_atributos(estado_ou_tipo, *args, **kwargs)

    limite = float(kwargs.get("limite_confianca") or config.limiar_confianca())
    tipo_str = str(a.tipo) if a.tipo else ""

    # Precedência de Segurança: Revisão humana caso haja erro, pendência,
    # problemas de validação, score abaixo do limite ou tipo Desconhecido / Não identificado.
    if (
        a.tem_pendencia
        or bool(a.erro)
        or len(problemas_bloqueantes(a.problemas)) > 0
        or a.score < limite
        or tipo_str in TIPOS_REVISAO
    ):
        return Destino.FILA_REVISAO_HUMANA

    # Precedência de Urgência: casos críticos sem pendência vão imediatamente para a emergência
    if a.urgente:
        return Destino.FILA_EMERGENCIA_MEDICA

    # Precedência de Tipo: encaminhamento por tipo de documento clínico
    rota = _rota_do_tipo(tipo_str)
    return rota[0] if rota else PADRAO


def _motivos(motivo, problemas, erro, score) -> list:
    """H2.2.1 T3: motivos acumulados no estado, sem repetir (ex.: 'ilegível' + 'ilegível: borrada')."""
    partes = []
    if motivo:
        partes.append(str(motivo).strip().rstrip("."))
    for p in problemas or []:
        p = str(p).strip().rstrip(".")
        if not p:
            continue
        if motivo and p.lower().startswith(partes[0].lower()):
            partes[0] = p  # a versão com detalhe substitui o motivo curto
        elif p not in partes:
            partes.append(p)
    if not partes and erro:
        partes.append(_motivo_falha(erro))
    if not partes:
        partes.append(f"{MOTIVO_BAIXA_CONFIANCA} ({score})")
    return partes[:MAX_MOTIVOS]


def justificativa(
    tipo: str | None,
    prioridade: str | None,
    score: float,
    destino: Destino | str,
    regra: str,
    achado: str | None = None,
    problemas: list | None = None,
    erro: str | None = None,
) -> str:
    """Gera a justificativa textual explicativa da rota decidida."""
    destino_str = str(destino)
    if regra == R_REVISAO or destino_str == Destino.FILA_REVISAO_HUMANA.value:
        motivo = (
            _motivo_falha(erro)
            if erro
            else "; ".join(problemas or []) or f"score baixo ({score})"
        )
        return f"Enviado à revisão humana (regra {R_REVISAO}): {motivo}."

    if regra == R_URGENCIA or destino_str == Destino.FILA_EMERGENCIA_MEDICA.value:
        return (
            f"{tipo or 'Documento'} com prioridade {PRIORIDADE_URGENTE} "
            f"(achado crítico: {achado or 'urgência clínica'}); "
            f"regra {R_URGENCIA}: {REGRAS[R_URGENCIA]} → {destino_str}."
        )

    tipo_str = str(tipo) if tipo else ""
    rota = _rota_do_tipo(tipo_str)
    descricao = REGRAS[rota[1] if rota else R_PRONTUARIO]
    prio_str = prioridade or PRIORIDADE_ROTINA
    return (
        f"{tipo_str} com prioridade {prio_str} e confiança {score}; "
        f"regra {regra}: {descricao} → {destino_str}."
    )


gerar_justificativa = justificativa  # nome do card H2.2.1 T2


class Atributos(NamedTuple):
    """O que o roteamento precisa saber de um documento."""

    tipo: str | None
    score: float
    urgente: bool
    tem_pendencia: bool
    problemas: list
    erro: str | None
    achado: str | None
    paciente: str | None


def _extrair_atributos(
    estado_ou_tipo: Mapping[str, Any] | str, *args, **kwargs
) -> Atributos:
    """Aceita o estado do grafo (dict) ou o tipo seguido de argumentos soltos."""
    if isinstance(estado_ou_tipo, dict):
        return _atributos_do_estado(estado_ou_tipo)
    return _atributos_dos_argumentos(estado_ou_tipo, args, kwargs)


# ---------- A partir do estado do grafo ----------
def _valor(enum_ou_valor: Any) -> Any:
    return getattr(enum_ou_valor, "value", enum_ou_valor)


def _primeiro_definido(*valores: Any) -> Any:
    return next((v for v in valores if v is not None), None)


def _atributos_do_estado(s: Mapping[str, Any]) -> Atributos:
    ext = s.get("extracao")
    cla = s.get("classificacao")

    # o estado manda; depois a extração; depois a classificação
    tipo = _valor(
        s.get("tipo")
        or s.get("tipo_documento")
        or getattr(ext, "tipo_documento", None)
        or getattr(cla, "tipo_documento", None)
    )
    score = _primeiro_definido(
        s.get("score"),
        getattr(cla, "score_confianca_classificacao", None),
        getattr(ext, "score_confianca_classificacao", None),
    )
    urgente = s.get("urgencia") is True or any(
        _eh_urgente(p)
        for p in (
            s.get("prioridade"),
            s.get("nivel_prioridade"),
            getattr(ext, "nivel_prioridade", None),
            getattr(cla, "nivel_prioridade", None),
        )
    )
    tem_pendencia, problemas = _pendencia_do_estado(s)
    paciente = getattr(ext, "paciente", None)

    return Atributos(
        tipo=tipo,
        score=SCORE_PADRAO if score is None else float(score),
        urgente=urgente,
        tem_pendencia=tem_pendencia,
        problemas=problemas,
        erro=s.get("erro"),
        achado=getattr(ext, "diagnostico_principal", None) or tipo or ACHADO_PADRAO,
        paciente=getattr(paciente, "nome", None),
    )


def _pendencia_do_estado(s: Mapping[str, Any]) -> tuple[bool, list]:
    """(tem_pendencia, problemas). Uma pendência escrita no estado (lista ou
    texto) também entra na lista de problemas, para aparecer no motivo."""
    problemas = list(s.get("problemas") or [])
    if s.get("requer_revisao") is True or s.get("erro"):
        return True, problemas

    pendencia = s.get("pendencia") if "pendencia" in s else s.get("pendencias")
    if isinstance(pendencia, bool):
        return pendencia, problemas
    if isinstance(pendencia, str) and pendencia:
        return True, [*problemas, pendencia]
    if isinstance(pendencia, list) and pendencia:
        return True, [*problemas, *pendencia]
    if isinstance(pendencia, tuple) and pendencia:
        return True, problemas  # comportamento herdado: tupla não entra nos problemas
    return bool(problemas_bloqueantes(problemas)), problemas


# ---------- A partir de argumentos soltos ----------
def _arg(args: tuple, posicao: int, kwargs: Mapping, nomes: tuple, padrao: Any) -> Any:
    """args[posicao], se foi passado; senão o 1º nome presente em kwargs; senão o padrão."""
    if len(args) > posicao:
        return args[posicao]
    return next((kwargs[n] for n in nomes if n in kwargs), padrao)


def _atributos_dos_argumentos(tipo: Any, args: tuple, kwargs: Mapping) -> Atributos:
    """decidir_destino(tipo, score, urgente, pendencia, problemas=..., erro=...)
    ou a assinatura clássica decidir_destino(tipo, prioridade, requer_revisao)."""
    tipo = _valor(tipo)
    if len(args) == 2 and isinstance(args[1], bool):  # assinatura clássica
        prioridade, requer_revisao = args
        score = kwargs.get("score", SCORE_PADRAO)
        urgente = _eh_urgente(prioridade)
        tem_pendencia = requer_revisao
    else:
        score = _arg(args, 0, kwargs, NOMES_SCORE, SCORE_PADRAO)
        urgencia = _arg(args, 1, kwargs, NOMES_URGENCIA, False)
        urgente = urgencia is True or _eh_urgente(urgencia)
        tem_pendencia = bool(_arg(args, 2, kwargs, NOMES_PENDENCIA, False))

    return Atributos(
        tipo=tipo,
        score=float(score),
        urgente=urgente,
        tem_pendencia=tem_pendencia,
        problemas=list(kwargs.get("problemas") or []),
        erro=kwargs.get("erro"),
        achado=kwargs.get("achado", tipo),
        paciente=kwargs.get("paciente"),
    )


# destino -> (regra aplicada, requer auditoria humana)
REGRA_POR_DESTINO = {
    Destino.FILA_EMERGENCIA_MEDICA: (R_URGENCIA, False),
    Destino.FILA_REVISAO_HUMANA: (R_REVISAO, True),
    Destino.FARMACIA_HOSPITALAR: (R_RECEITA, False),
    Destino.AUDITORIA_AUTORIZACOES: (R_GUIA, False),
    Destino.PRONTUARIO_ELETRONICO: (R_PRONTUARIO, False),
}


def criar_decisao_roteamento(
    estado_ou_tipo: Mapping[str, Any] | str,
    *args,
    **kwargs,
) -> DecisaoRoteamento:
    """Monta a DecisaoRoteamento completa (destino, auditoria, justificativa, notificacao)."""
    a = _extrair_atributos(estado_ou_tipo, *args, **kwargs)
    tipo, urgente, problemas = a.tipo, a.urgente, a.problemas

    destino = decidir_destino(estado_ou_tipo, *args, **kwargs)
    fora_das_categorias = str(tipo or "") == TipoDocumento.NAO_IDENTIFICADO.value
    if fora_das_categorias and FORA_DAS_CATEGORIAS not in problemas:
        problemas = [FORA_DAS_CATEGORIAS, *problemas]

    regra, requer_auditoria = REGRA_POR_DESTINO.get(destino, (R_PRONTUARIO, False))

    notificacao = None
    if destino == Destino.FILA_EMERGENCIA_MEDICA:
        msg_paciente = f" paciente {a.paciente}" if a.paciente else ""
        notificacao = Notificacao(
            canal=CANAL_PLANTAO,
            mensagem=f"ALERTA URGENTE: {a.achado}{msg_paciente}.",
        )
    elif destino == Destino.FILA_REVISAO_HUMANA and urgente and not fora_das_categorias:
        notificacao = Notificacao(canal=CANAL_PLANTAO, mensagem=MSG_URGENCIA_AMBIGUA)

    prioridade_str = PRIORIDADE_URGENTE if urgente else PRIORIDADE_ROTINA
    just = justificativa(
        tipo=tipo,
        prioridade=prioridade_str,
        score=a.score,
        destino=destino,
        regra=regra,
        achado=a.achado,
        problemas=problemas,
        erro=a.erro,
    )

    return DecisaoRoteamento(
        destino_principal=destino,
        requer_auditoria_humana=requer_auditoria,
        justificativa_roteamento=just,
        regra_aplicada=regra,
        notificacao_gerada=notificacao,
    )
