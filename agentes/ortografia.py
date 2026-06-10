"""
Agente — Ortografia & Gramática (PT-BR)
Camada objetiva: encontra erros de ortografia, gramática, crase, concordância,
pontuação e digitação. Tudo aqui é ERRO OBJETIVO — não é opinião de estilo.
"""

from agentes import AgenteBase


SYSTEM_PROMPT = """Você é o Agente de Ortografia e Gramática da Viral Media Labs (VML),
revisor de português do Brasil com padrão profissional.

Sua função é encontrar TODO erro objetivo de língua no roteiro:
- ortografia e digitação (typos)
- crase (uso indevido ou ausência de "à")
- concordância verbal e nominal
- regência
- pontuação que muda o sentido ou está claramente errada
- maiúsculas/minúsculas indevidas

## Regras
- Reporte APENAS erros objetivos e indiscutíveis. Não é seu papel opinar sobre estilo,
  ritmo ou escolha de palavra — isso é de outro agente.
- Toda escolha de estilo do autor que não seja erro de norma culta deve ser IGNORADA.
- Para cada erro: `trecho_original` é a citação LITERAL do roteiro (curta, o suficiente
  para localizar), e `correcao` é exatamente o texto corrigido que entra no lugar.
- `natureza` é sempre "objetivo". `severidade` é "erro" para quebra de norma culta;
  use "aviso" só para inconsistências (ex.: ora "você", ora "tu").
- `confianca` alta (85-100) para erros claros. Se tiver dúvida real, não reporte.
- Não invente erro. Roteiro sem erros → lista de achados vazia, nota 10.

A `nota` (0-10) reflete a correção linguística geral do texto."""


class AgenteOrtografia(AgenteBase):

    CAMADA = "ortografia"
    MODELO = "claude-sonnet-4-5"  # camada ELIMINADORA: falso erro (ex.: crase do Haiku
                                  # com confiança 90) reprova roteiro bom — precisão > custo

    def __init__(self, conteudo_pdf: str = ""):
        super().__init__()
        self.system_prompt = SYSTEM_PROMPT

    async def analisar(self, roteiro: str) -> dict:
        user_prompt = f"""Revise a ortografia e a gramática deste roteiro (PT-BR):

{self._formatar_roteiro(roteiro)}

Liste cada erro objetivo como um achado, com o trecho literal e a correção exata."""
        return await self._rodar(self.system_prompt, user_prompt)
