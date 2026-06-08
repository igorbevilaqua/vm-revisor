"""
Agente de Contexto Narrativo — roda ANTES dos demais agentes.
Lê o roteiro e extrai um resumo estrutural rápido (estrutura CODEX, emoção-alvo,
audiência, tema) que é injetado no prompt de todos os outros agentes como contexto.

Objetivo: evitar que cada agente "descubra" a estrutura de forma independente e
inconsistente. Com contexto compartilhado, os agentes trabalham coerentemente.

Usa Haiku (rápido e barato) — não gera achados, só contexto informativo.
"""

import asyncio

from agentes import AgenteBase


SYSTEM_CONTEXTO = """Você é um analisador rápido de contexto narrativo para roteiros de vídeo curto.
Leia o roteiro e extraia as informações estruturais em formato claro e conciso.
Seja direto — sua saída será lida por outros agentes especializados como contexto."""


class AgenteContexto(AgenteBase):

    CAMADA = "contexto"
    MODELO = "claude-haiku-4-5"
    MAX_TOKENS = 350

    def __init__(self):
        super().__init__()

    async def analisar_contexto(self, roteiro: str) -> str:
        """Retorna um bloco de texto com o contexto narrativo do roteiro."""
        user_prompt = f"""Analise este roteiro e responda EXATAMENTE neste formato (5 linhas):
ESTRUTURA: [qual estrutura CODEX está sendo usada, ex: Davi e Golias / Herói Improvável]
EMOÇÃO: [emoção principal que o roteiro tenta despertar, ex: indignação, inspiração, curiosidade]
AUDIÊNCIA: [público-alvo em 5-8 palavras, ex: empreendedores iniciantes interessados em finanças]
TEMA: [tema central em 1 frase curta, ex: estratégias tributárias para pequenas empresas]
DIAGNÓSTICO: [estado narrativo atual em 1 frase, ex: estrutura sólida mas clímax emocional fraco]

{self._formatar_roteiro(roteiro)}"""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._chamar_api(SYSTEM_CONTEXTO, user_prompt),
        )

    async def analisar(self, roteiro: str) -> dict:
        # Implementação mínima para satisfazer o contrato de AgenteBase.
        # Use analisar_contexto() em vez disso.
        return {"achados": [], "resumo": "", "nota": 0}
