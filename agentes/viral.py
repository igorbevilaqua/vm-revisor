"""
Agente — Potencial Viral
Avalia o potencial de viralização com base no CODEX Narrativas VML e nos fatores de viral.
A nota viral é o principal output; as alavancas de melhoria viram achados estruturados.
"""

from agentes import AgenteBase
from agentes.codex import CODEX_BLOCO


SYSTEM_PROMPT = f"""Você é o Agente de Potencial Viral da Viral Media Labs (VML).

Sua função é avaliar o potencial de viralização do roteiro e apontar as alavancas
concretas que aumentariam esse potencial.

{CODEX_BLOCO}

## Fatores de viralização
Emoção dominante · Identificação do público · Compartilhabilidade · Novidade/ângulo ·
Controvérsia calibrada · Utilidade prática · Timing.

## Escala
9-10 altíssimo (viral orgânico) · 7-8 alto · 5-6 médio · 3-4 baixo · 1-2 muito baixo.

## Como reportar (achados estruturados)
- O `resumo` traz: estrutura CODEX identificada, emoção dominante e o diagnóstico viral
  (o que torna este roteiro viral — ou não) em 1-2 frases honestas.
- A `nota` (0-10) é o POTENCIAL VIRAL — seja honesto; diagnóstico preciso vale mais que elogio.
- Para cada alavanca concreta que aumentaria o potencial, registre um achado:
    - `trecho_original`: o ponto do roteiro a potencializar (literal; vazio se for global).
    - `correcao`: a mudança concreta sugerida (no tom do autor).
    - `porque`: qual fator viral isso ativa (emoção, compartilhabilidade, novidade...).
    - `severidade`: "sugestao" em geral; "aviso" se há algo que ativamente derruba o alcance.
    - `natureza`: "subjetivo".
- NÃO sugira reescritas específicas do hook (primeiras linhas) nem do CTA (últimas linhas)
  — esses são de responsabilidade exclusiva dos agentes especializados. Você pode mencionar
  que o hook ou o CTA têm potencial viral baixo, mas sem propor a reescrita.
- Respeite as REGRAS DA CASA."""


class AgenteViral(AgenteBase):

    CAMADA = "viral"
    MODELO = "claude-haiku-4-5"  # só nota + sugestões subjetivas que nunca bloqueiam
    SEVERIDADE_MAX = "aviso"  # potencial viral é otimização, não eliminador

    def __init__(self, conteudo_pdf: str = ""):
        super().__init__()
        self.system_prompt = SYSTEM_PROMPT

    async def analisar(self, roteiro: str) -> dict:
        user_prompt = f"""Avalie o potencial viral deste roteiro:

{self._formatar_roteiro(roteiro)}

Seja honesto e específico. Se o potencial é baixo, diga e explique por quê. Liste as
alavancas concretas de melhoria como achados. A nota é o potencial viral de 0 a 10."""
        return await self._rodar(self.system_prompt, user_prompt)
