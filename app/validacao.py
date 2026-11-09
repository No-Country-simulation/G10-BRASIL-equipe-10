import csv
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from . import config
from .schemas import Extracao

UFS_VALIDAS = {
    "AC",
    "AL",
    "AP",
    "AM",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MT",
    "MS",
    "MG",
    "PA",
    "PB",
    "PR",
    "PE",
    "PI",
    "RJ",
    "RN",
    "RS",
    "RO",
    "RR",
    "SC",
    "SP",
    "SE",
    "TO",
}

# Quanto cada problema desconta do score (ajustável)
PENALIDADES = {
    "paciente_ausente": 0.30,
    "crm_ausente": 0.25,
    "tipo_desconhecido": 0.40,
    "inconsistencia": 0.20,
    "nome_nao_encontrado": 0.30,
    "medicamento_inventado": 0.30,
    "posologia_incompleta": 0.15,
    "tuss_nao_encontrado": 0.20,
    "cid_invalido": 0.10,
    "posologia_nao_confirmada": 0.15,  # h1.3.4
    "exame_inventado": 0.30,  # h1.3.5
}
# Mensagens de motivo/problema compartilhadas com roteamento.py e grafo.py
FORA_DAS_CATEGORIAS = "documento fora das categorias"
MOTIVO_FALHA_EXTRACAO = "falha na extração automática"
MOTIVO_BAIXA_CONFIANCA = "baixa confiança na classificação"

CID_REGEX = re.compile(r"^[A-Z]\d{2}(\.\d{1,2})?$")
ARQUIVO_CID10 = Path(__file__).resolve().parents[1] / "config" / "cid10.csv"


@lru_cache(maxsize=1)
def carregar_cids_validos(caminho: Path | None = None) -> frozenset[str]:
    """H1.3.3 T2: carrega a tabela CID-10 do CSV uma única vez num conjunto imutável."""
    alvo = caminho or ARQUIVO_CID10
    codigos: set[str] = set()
    with alvo.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f):
            codigo = (linha.get("codigo") or "").strip().upper()
            if codigo:
                codigos.add(codigo)
    return frozenset(codigos)


def _simplificar(texto: str) -> str:
    """Sem acentos, minúsculas e espaços normalizados, para comparar textos."""
    t = unicodedata.normalize("NFD", texto)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(t.lower().split())


def normalizar_crm(crm):
    """'CRM-SP 145892' (e variações) -> '145892-SP'. None se faltar número ou UF válida."""
    if not crm or not isinstance(crm, str):
        return None
    limpo = re.sub(r"(?<=\d)\.(?=\d)", "", crm.strip())
    numeros = re.findall(r"\d+", limpo)
    candidatas = re.findall(r"\b([A-Za-z]{2})\b", limpo.upper().replace("CRM", " "))
    ufs = [c for c in candidatas if c in UFS_VALIDAS]
    if (
        len(numeros) == 1
        and 3 <= len(numeros[0]) <= 7
        and len(ufs) == 1
        and len(candidatas) == 1
    ):
        return f"{numeros[0]}-{ufs[0]}"
    return None


def _nome_aparece_no_texto(nome: str, texto: str) -> bool:
    """TODAS as palavras do nome precisam existir no texto (ignora Dr./Dra.),
    como palavras inteiras (assim 'ana' não casa com 'banana')."""
    palavras_texto = set(re.findall(r"\w+", _simplificar(texto)))
    palavras = [
        p for p in re.findall(r"\w+", _simplificar(nome)) if p not in ("dr", "dra")
    ]
    return all(p in palavras_texto for p in palavras)


# H1.3.4 medicamentos e posologia
CAMPO_FALTANTE = "campo faltante: "
CAMPO_NAO_CONFIRMADO = "campo não confirmado no texto: "
JANELA_MEDICAMENTO = 400


def _achar_frase(frase_s: str, texto_s: str):
    """(inicio, fim) da 1º ocorrência da frase como palavras interias, ou Nome.
    Os dois textos já devem estar simplificados (sem acento, minusculas, espaços simples)."""
    if not frase_s:
        return None
    m = re.search(rf"(?<!\w){re.escape(frase_s)}(?!\w)", texto_s)
    return (m.start(), m.end()) if m else None


def _dose_normalizada(dose: str) -> str:
    return re.sub(r"\s+", "", _simplificar(dose).replace(",", "."))


def _dose_na_janela(dose: str, janela_s: str) -> bool:
    """'500mg' = '500 mg' , mas  '5mg' NÃO casa como '25mg' nem '1.5mg', e não há conversão de unidade."""
    alvo = _dose_normalizada(dose)
    if not alvo:
        return False
    junto = re.sub(r"\s+", "", janela_s.replace(",", "."))
    return bool(re.search(rf"(?<![\d.]){re.escape(alvo)}(?!\d)", junto))


def _numeros(s: str) -> set:
    return set(re.findall(r"\d+(?:\.\d+)?", s.replace(",", ".")))


def _valor_na_janela(valor: str, janela_s: str) -> bool:
    """Via, frequência e duração: a frase escrita aparece na janela ou, se houver números,
    todos os números do valor aparecem nela (aceita '8/8h' para 'de 8 em 8 horas';
    nunca aceita um número que não esteja no documento)."""
    v = _simplificar(valor)
    if not v:
        return False
    if _achar_frase(v, janela_s):
        return True
    nums = _numeros(v)
    return bool(nums) and nums <= _numeros(janela_s)


def _validar_medicamentos(extracao: Extracao, texto_s: str):
    """Um item por medicamento, todos presentes no texto. Dose, via, frequência e duração só ficam
    se confirmadas NA REGIÃO do texto desse medicamento; o resto vira null e é sinalizado.
    Receita sem dose: 'campo faltante: dose'. Devolve (problemas, penalidade)."""
    problemas, pen = [], 0.0
    e_receita = extracao.tipo_documento == "Receituário Médico"

    candidatos, vistos = [], set()
    for m in extracao.medicamentos:
        nome_s = _simplificar(m.nome)
        pos = _achar_frase(nome_s, texto_s)
        if pos is None and nome_s:
            pos = _achar_frase(
                nome_s.split()[0], texto_s
            )  # 'Dipirona sódica' -> 'Dipirona'
        if pos is None:
            problemas.append(f"Medicamento '{m.nome}' não encontrado no texto original")
            pen += PENALIDADES["medicamento_inventado"]
            continue
        chave = (nome_s.split()[0], _dose_normalizada(m.dose or ""))
        if chave in vistos:  # mesmo medicamento repetido
            continue
        vistos.add(chave)
        candidatos.append((m, pos[0]))

    inicios = sorted({ini for _, ini in candidatos})
    mantidos = []
    for m, ini in candidatos:
        seguintes = [i for i in inicios if i > ini]
        fim = min(
            seguintes[0] if seguintes else ini + JANELA_MEDICAMENTO,
            ini + JANELA_MEDICAMENTO,
        )
        janela = texto_s[ini:fim]
        tinha_dose = bool(m.dose)
        for campo, confere in (
            ("dose", _dose_na_janela),
            ("via", _valor_na_janela),
            ("frequencia", _valor_na_janela),
            ("duracao", _valor_na_janela),
        ):
            valor = getattr(m, campo)
            if valor and not confere(valor, janela):
                problemas.append(
                    f"{CAMPO_NAO_CONFIRMADO}{campo} (medicamento '{m.nome}')"
                )
                pen += PENALIDADES["posologia_nao_confirmada"]
                setattr(m, campo, None)
        if e_receita and not tinha_dose:
            problemas.append(
                f"{CAMPO_FALTANTE}dose | Medicamento '{m.nome}' sem dose informada"
            )
            pen += PENALIDADES["posologia_incompleta"]
        mantidos.append(m)
    extracao.medicamentos = mantidos
    return problemas, pen


# h1.3.5 exames e procedimentos
DISTANCIA_MAXIMA_TUSS = 300


def _padrao_tuss(digitos: str) -> str:
    """Os digitos do código, com ponto, hifen ou espaço opicionais entre eles, sem colocar em outro número."""
    return r"(?<!\d)" + r"[.\-\s]?".join(digitos) + r"(?!\d)"


def _distancia(posicao: int, trecho) -> int:
    return max(trecho[0] - posicao, posicao - trecho[1], 0)


def _validar_exames(extracao: Extracao, texto_s: str):
    """Um item por exame, todos presentes no texto, sem duplicatas. O código TUSS só fica se estiver
    escrito no documento, inteiro e junto DESSE exame (não de outro). Devolve (problemas, penalidade)."""
    problemas, pen = [], 0.0

    unicos = {}
    for e in extracao.exames:  # funde duplicatas; o código não se perde
        chave = _simplificar(e.nome)
        if chave in unicos:
            if not unicos[chave].codigo_tuss and e.codigo_tuss:
                unicos[chave].codigo_tuss = e.codigo_tuss
            continue
        unicos[chave] = e

    achados = []
    for chave, e in unicos.items():
        pos = _achar_frase(chave, texto_s)
        if pos is None:
            problemas.append(f"Exame '{e.nome}' não encontrado no texto original")
            pen += PENALIDADES["exame_inventado"]
            continue
        achados.append((e, pos))

    todos = [pos for _, pos in achados]
    for e, pos in achados:
        if not e.codigo_tuss:
            continue
        digitos = re.sub(r"\D", "", e.codigo_tuss)
        ocorrencias = (
            [m.start() for m in re.finditer(_padrao_tuss(digitos), texto_s)]
            if digitos
            else []
        )
        if not ocorrencias:
            problemas.append(
                f"Código TUSS {e.codigo_tuss} não encontrado no texto original"
            )
            pen += PENALIDADES["tuss_nao_encontrado"]
            e.codigo_tuss = None
            continue
        limite = None if len(achados) == 1 else DISTANCIA_MAXIMA_TUSS
        junto = any(
            _distancia(o, pos) <= min(_distancia(o, outro) for outro in todos)
            and (limite is None or _distancia(o, pos) <= limite)
            for o in ocorrencias
        )
        if junto:
            e.codigo_tuss = digitos  # forma canônica: só dígitos
        else:
            problemas.append(
                f"Código TUSS {e.codigo_tuss} não está junto do exame '{e.nome}' no texto"
            )
            pen += PENALIDADES["tuss_nao_encontrado"]
            e.codigo_tuss = None
    extracao.exames = [e for e, _ in achados]
    extracao.exames_solicitados = list(extracao.exames)
    return problemas, pen


def validar(extracao: Extracao, texto: str):
    """Devolve (extracao_corrigida, lista_de_problemas, score_final)."""
    problemas, pen = [], 0.0
    texto_s = _simplificar(texto)
    fora_das_categorias = extracao.tipo_documento == "Não identificado"

    # 1) CRM: normaliza e confere o número no texto (nunca um valor "plausível")
    bruto = extracao.medico_solicitante.crm
    crm = normalizar_crm(bruto)
    erro_crm = None
    if not bruto:
        if not fora_das_categorias:
            erro_crm = "CRM do solicitante não encontrado"
            problemas.append(erro_crm)
            pen += PENALIDADES["crm_ausente"]
    elif not crm:
        erro_crm = f"CRM em formato inválido: '{bruto}'"
        problemas.append(erro_crm)
        pen += PENALIDADES["crm_ausente"]
    elif crm.split("-")[0] not in re.sub(r"[.\s]", "", texto):
        erro_crm = f"CRM {crm} não consta no texto original"
        problemas.append(erro_crm)
        pen += PENALIDADES["crm_ausente"]
        crm = None
    extracao.medico_solicitante.crm = crm

    # 2) Paciente e médico: o nome existe no texto?
    nome = extracao.paciente.nome
    if not nome:
        if not fora_das_categorias:
            problemas.append("Nome do paciente ausente")
            pen += PENALIDADES["paciente_ausente"]
    elif not _nome_aparece_no_texto(nome, texto):
        problemas.append(f"Nome '{nome}' não encontrado no texto original")
        pen += PENALIDADES["nome_nao_encontrado"]
    medico = extracao.medico_solicitante.nome
    if medico and not _nome_aparece_no_texto(medico, texto):
        problemas.append(f"Nome do médico '{medico}' não encontrado no texto original")
        pen += PENALIDADES["nome_nao_encontrado"]

    # 3) Tipo e inconsistências apontadas pelo LLM
    if fora_das_categorias:
        problemas.insert(0, FORA_DAS_CATEGORIAS)
        pen += PENALIDADES["tipo_desconhecido"]
    elif extracao.tipo_documento == "Desconhecido":
        problemas.append("Tipo de documento não identificado")
        pen += PENALIDADES["tipo_desconhecido"]
    for item in extracao.inconsistencias:
        problemas.append(f"Inconsistência: {item}")
        pen += PENALIDADES["inconsistencia"]
    if erro_crm and erro_crm not in extracao.inconsistencias:
        extracao.inconsistencias.append(erro_crm)

    # 4) CID: formato válido e presente na tabela CID-10? Está escrito ou sugerido?
    if extracao.cid_sugerido:
        cid_bruto = extracao.cid_sugerido.strip().upper()
        cid = (
            f"{cid_bruto[:3]}.{cid_bruto[3:]}"
            if re.match(r"^[A-Z]\d{3,4}$", cid_bruto)
            else cid_bruto
        )
        cids_validos = carregar_cids_validos()
        if CID_REGEX.match(cid) and cid in cids_validos:
            extracao.cid_sugerido = cid
            extracao.cid = cid
            texto_lower = texto.lower()
            escrito = (
                cid.lower() in texto_lower
                or cid.replace(".", "").lower() in texto_lower
            )
            origem = "escrito" if escrito else "sugerido"
            extracao.origem_cid = origem
            extracao.cid_origem = origem
        else:
            problemas.append(f"CID inválido: '{extracao.cid_sugerido}'")
            pen += PENALIDADES["cid_invalido"]
            extracao.cid_sugerido = None
            extracao.cid = None
            extracao.origem_cid = None
            extracao.cid_origem = None

    # 5) Medicamentos: descarta inventados, confere posologia na região do medicamento
    p, d = _validar_medicamentos(extracao, texto_s)
    problemas += p
    pen += d

    # 6) Exames: funde duplicatas, descarta inventados, confere TUSS junto do exame
    p, d = _validar_exames(extracao, texto_s)
    problemas += p
    pen += d

    # 7) Evidências: só ficam os trechos que realmente existem no documento
    extracao.evidencias = [
        ev
        for ev in extracao.evidencias
        if ev.trecho and _simplificar(ev.trecho) in texto_s
    ]

    # 8) Score final: base do LLM limitada a 0.95 menos as penalidades
    base = min(extracao.score_confianca_classificacao, 0.95)
    return extracao, problemas, max(0.0, round(base - pen, 2))


def motivo_revisao(
    score: float, problemas: list, limite: float, erro: str | None = None
) -> str:
    """Motivo registrado no estado quando o documento não é roteado sozinho.

    A ordem espelha a decisão do grafo: falha de extração, documento fora das
    categorias, baixa confiança, depois os problemas de validação.
    """
    if erro:
        return f"{MOTIVO_FALHA_EXTRACAO} ({erro[:80]})"
    if FORA_DAS_CATEGORIAS in (problemas or []):
        return FORA_DAS_CATEGORIAS
    if score < limite:
        motivo = MOTIVO_BAIXA_CONFIANCA
        if problemas:
            motivo += f"; {'; '.join(problemas)}"
        return motivo
    return "; ".join(problemas) or "revisão necessária"


# Problemas que o próprio validar() já corrigiu sem risco clínico: só descontam
# do score e aparecem na tela, mas sozinhos não mandam para revisão.
# CID inválido: o código já foi removido (vira null) e o CID é só sugestão.
PREFIXOS_AVISO = ("CID inválido",)


def problemas_bloqueantes(problemas: list) -> list:
    """Problemas que obrigam revisão humana (todos, menos os avisos)."""
    return [p for p in (problemas or []) if not str(p).startswith(PREFIXOS_AVISO)]


def precisa_revisao(score: float, problemas: list, limite: float | None = None) -> bool:
    """Score baixo OU algum problema bloqueante (avisos só descontam do score)."""
    if limite is None:
        limite = config.limite_confianca()
    return score < limite or len(problemas_bloqueantes(problemas)) > 0


def taxa_acerto_por_faixa(avaliacoes: list[dict], limite: float | None = None) -> dict:
    """H1.2.2 T1: calcula a taxa de acerto abaixo e acima do limite de confiança.

    Cada item de 'avaliacoes' deve ter:
      - 'esperado': tipo de documento correto
      - 'obtido': tipo de documento classificado
      - 'score': score de confiança (0 a 1)
    """
    if limite is None:
        limite = config.limite_confianca()
    abaixo = [a for a in avaliacoes if a["score"] < limite]
    acima = [a for a in avaliacoes if a["score"] >= limite]

    def _resumo(itens: list[dict]) -> dict:
        total = len(itens)
        acertos = sum(1 for i in itens if i["esperado"] == i["obtido"])
        return {
            "total": total,
            "acertos": acertos,
            "taxa_acerto": round(acertos / total, 2) if total else 0.0,
        }

    return {
        "limite": limite,
        "abaixo_do_limite": _resumo(abaixo),
        "acima_ou_igual_ao_limite": _resumo(acima),
    }
