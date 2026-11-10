import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # sem override: variável de ambiente real sempre vence o .env

ARQUIVO_REGRAS = Path(__file__).resolve().parents[1] / "config" / "regras.json"
LIMITE_CONFIANCA_PADRAO = 0.80


def carregar_regras(caminho: Path | None = None) -> dict:
    """Lê config/regras.json; devolve {} se o arquivo não existir ou for inválido."""
    try:
        dados = json.loads((caminho or ARQUIVO_REGRAS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def limite_confianca() -> float:
    """Abaixo deste score o documento vai para revisão humana (H1.2.2 T2).

    Precedência: env LIMIAR_CONFIANCA > config/regras.json > 0.80.
    """
    bruto = os.getenv("LIMIAR_CONFIANCA")
    if bruto is None:
        bruto = carregar_regras().get("limite_confianca", LIMITE_CONFIANCA_PADRAO)
    try:
        valor = float(bruto)
    except (TypeError, ValueError):
        return LIMITE_CONFIANCA_PADRAO
    return min(1.0, max(0.0, valor))


def limiar_confianca() -> float:
    """Nome antigo mantido para compatibilidade; use limite_confianca()."""
    return limite_confianca()


def bucket() -> str:
    return os.getenv("OCI_BUCKET", "mediflow-documentos-clinicos")


def pasta_local() -> str:
    return os.getenv("STORAGE_LOCAL_DIR", "storage_local")


def modelo_gemini() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


def modelo_gemini_fallback() -> str:
    """Modelo usado quando o principal devolve 5xx (ex.: 503 por alta demanda)."""
    return os.getenv("GEMINI_MODEL_FALLBACK", "gemini-3.5-flash")


def formatos_aceitos() -> list[str]:
    """Formatos aceitos na rota /triagem/arquivo (H1.1.4 T1)."""
    formatos = carregar_regras().get("formatos_aceitos")
    if isinstance(formatos, list) and formatos:
        return [str(f).upper() for f in formatos]
    return ["PDF", "JPG", "PNG"]


def tamanho_maximo_mb() -> int:
    """Limite máximo de upload em MB (H1.1.4 T1). Precedência: env TAMANHO_MAXIMO_MB > regras.json > 10."""
    bruto = os.getenv("TAMANHO_MAXIMO_MB")
    if bruto is None:
        bruto = carregar_regras().get("tamanho_maximo_mb", 10)
    try:
        return int(bruto)
    except (TypeError, ValueError):
        return 10
