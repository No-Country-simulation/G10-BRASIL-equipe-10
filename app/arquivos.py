from pathlib import Path

ASSINATURAS = (
    (b"%PDF", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
)

MAPA_EXTENSAO_FORMATO = {
    ".pdf": "PDF",
    ".jpg": "JPG",
    ".jpeg": "JPG",
    ".png": "PNG",
}

MAPA_FORMATO_EXTENSOES = {
    "PDF": {".pdf"},
    "JPG": {".jpg", ".jpeg"},
    "PNG": {".png"},
}


def extensao_por_assinatura(conteudo: bytes) -> str | None:
    """Descobre o tipo pelos primeiros bytes (não confia no nome nem no MIME do cliente)."""
    for assinatura, extensao in ASSINATURAS:
        if conteudo.startswith(assinatura):
            return extensao
    return None


def extensao_aceita(nome_arquivo: str | None, formatos: list[str]) -> bool:
    """Confere se a extensão do arquivo (se presente) pertence aos formatos aceitos (H1.1.4 T2)."""
    if not nome_arquivo:
        return True
    ext = Path(nome_arquivo).suffix.lower()
    if not ext:
        return True
    formatos_set = {f.upper() for f in formatos}
    extensoes_permitidas = set()
    for fmt in formatos_set:
        extensoes_permitidas.update(
            MAPA_FORMATO_EXTENSOES.get(fmt, {f".{fmt.lower()}"})
        )
    return ext in extensoes_permitidas


def montar_mensagem_formato_invalido(formatos: list[str]) -> str:
    """Texto curto em português listando os formatos aceitos (H1.1.4 T3)."""
    if not formatos:
        return "Formato não aceito."
    if len(formatos) == 1:
        return f"Formato não aceito. Envie {formatos[0]}."
    return f"Formato não aceito. Envie {', '.join(formatos[:-1])} ou {formatos[-1]}."


def montar_mensagem_tamanho_excedido(limite_mb: int) -> str:
    """Texto curto em português informando o limite máximo (H1.1.4 T3)."""
    return f"Arquivo acima do limite de {limite_mb} MB."
