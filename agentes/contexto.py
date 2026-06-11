"""
Agente de Contexto Narrativo — roda ANTES dos demais agentes.
Lê o roteiro e extrai um resumo estrutural rápido (estrutura CODEX, emoção-alvo,
audiência, tema) que é injetado no prompt de todos os outros agentes como contexto.

Objetivo: evitar que cada agente "descubra" a estrutura de forma independente e
inconsistente. Com contexto compartilhado, os agentes trabalham coerentemente.

Saída ESTRUTURADA (tool use): como todos os 9 agentes herdam este contexto, um erro
aqui se propaga — o schema força os campos e a confiança da detecção de estrutura,
e o bloco injetado avisa quando a confiança é baixa (agentes não devem cobrar beats
de uma estrutura incerta).

Usa Haiku (rápido e barato) — não gera achados, só contexto informativo.
"""

import asyncio

from agentes import AgenteBase
from agentes.codex import CODEX_BLOCO, CODEX_NOMES


SYSTEM_CONTEXTO = f"""Você é um analisador rápido de contexto narrativo para roteiros de vídeo curto.
Leia o roteiro e extraia as informações estruturais. Seja direto — sua saída será
lida por outros agentes especializados como contexto compartilhado.

{CODEX_BLOCO}

Em `estrutura`, use o nome EXATO de uma estrutura do CODEX acima (a que melhor
descreve o roteiro), ou "Indefinida" se nenhuma se aplica com clareza.
Em `confianca_estrutura`, seja honesto: 90+ só quando os beats da estrutura são
inconfundíveis; abaixo de 60 quando é um palpite."""


SCHEMA_CONTEXTO = {
    "type": "object",
    "properties": {
        "estrutura": {
            "type": "string",
            "description": "Nome EXATO de uma estrutura do CODEX, ou 'Indefinida'.",
        },
        "confianca_estrutura": {"type": "integer", "minimum": 0, "maximum": 100},
        "emocao": {
            "type": "string",
            "description": "Emoção principal que o roteiro tenta despertar (ex.: indignação, inspiração, curiosidade).",
        },
        "audiencia": {
            "type": "string",
            "description": "Público-alvo em 5-8 palavras.",
        },
        "tema": {
            "type": "string",
            "description": "Tema central em 1 frase curta.",
        },
        "diagnostico": {
            "type": "string",
            "description": "Estado narrativo atual em 1 frase (ex.: estrutura sólida mas clímax emocional fraco).",
        },
    },
    "required": ["estrutura", "confianca_estrutura", "emocao", "audiencia",
                 "tema", "diagnostico"],
}


def formatar_contexto(ctx: dict) -> str:
    """Formata o contexto estruturado no bloco de texto injetado nos agentes."""
    if not ctx or not isinstance(ctx, dict):
        return ""
    conf = ctx.get("confianca_estrutura") or 0
    estrutura = (ctx.get("estrutura") or "Indefinida").strip()
    aviso = ""
    if estrutura.lower() == "indefinida":
        aviso = " (nenhuma estrutura CODEX clara — não cobre beats de estrutura específica)"
    elif conf < 60:
        aviso = " (BAIXA CONFIANÇA — confirme antes de cobrar beats desta estrutura)"
    return (
        f"ESTRUTURA: {estrutura} (confiança {conf}%){aviso}\n"
        f"EMOÇÃO: {ctx.get('emocao', '')}\n"
        f"AUDIÊNCIA: {ctx.get('audiencia', '')}\n"
        f"TEMA: {ctx.get('tema', '')}\n"
        f"DIAGNÓSTICO: {ctx.get('diagnostico', '')}"
    )


class AgenteContexto(AgenteBase):

    CAMADA = "contexto"
    MODELO = "claude-haiku-4-5"
    MAX_TOKENS = 500

    def __init__(self):
        super().__init__()

    async def analisar_contexto(self, roteiro: str) -> dict:
        """Retorna o contexto narrativo ESTRUTURADO (dict no SCHEMA_CONTEXTO).
        Use formatar_contexto() para obter o bloco de texto injetável."""
        user_prompt = f"""Analise este roteiro e registre o contexto narrativo:

{self._formatar_roteiro(roteiro)}"""

        loop = asyncio.get_event_loop()
        ctx = await loop.run_in_executor(
            None,
            lambda: self._chamar_api_estruturada(
                SYSTEM_CONTEXTO, user_prompt, schema=SCHEMA_CONTEXTO),
        )
        if not isinstance(ctx, dict):
            return {}
        # Valida o nome da estrutura contra o CODEX canônico: nome fora da lista
        # (alucinação/estrutura antiga) cai para Indefinida com confiança zerada,
        # em vez de propagar um rótulo falso para os 9 agentes.
        estrutura = (ctx.get("estrutura") or "").strip()
        if estrutura and estrutura.lower() != "indefinida" and estrutura not in CODEX_NOMES:
            ctx["estrutura"] = "Indefinida"
            ctx["confianca_estrutura"] = 0
            ctx["diagnostico"] = (ctx.get("diagnostico") or "").strip() + \
                f" [estrutura fora do CODEX descartada: {estrutura}]"
        return ctx

    async def analisar(self, roteiro: str) -> dict:
        # Implementação mínima para satisfazer o contrato de AgenteBase.
        # Use analisar_contexto() em vez disso.
        return {"achados": [], "resumo": "", "nota": 0}
