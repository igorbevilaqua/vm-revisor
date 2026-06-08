"""
Classe base para todos os agentes de revisão.

Cada agente devolve ACHADOS ESTRUTURADOS (não texto livre), ancorados em trechos
literais do roteiro. Isso permite:
  - deduplicar e ordenar achados entre agentes;
  - separar erro objetivo (bloqueante) de opinião subjetiva (opcional);
  - aplicar correções como troca exata / comentário ancorado no Google Doc.

O formato é forçado pela API via "tool use" (a resposta tem que casar com o schema).
"""

import os
import asyncio
from pathlib import Path

import anthropic

# ─── Carrega API key do config.txt se não estiver no ambiente ─────────────────
_RAIZ_CONFIG = Path(__file__).parent.parent
_CONFIG_PATH = _RAIZ_CONFIG / "config.txt"

if not os.environ.get("ANTHROPIC_API_KEY") and _CONFIG_PATH.exists():
    for _linha in _CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        if _linha.startswith("ANTHROPIC_API_KEY="):
            _valor = _linha.split("=", 1)[1].strip()
            if _valor and _valor != "cole-sua-chave-aqui":
                os.environ["ANTHROPIC_API_KEY"] = _valor
            break


# ─── Contrato de saída (schema dos achados) ──────────────────────────────────

# Severidade: erro = quebra/impede; aviso = problema relevante; sugestao = melhoria.
# Natureza:   objetivo = indiscutível (ortografia, fato, fonte); subjetivo = gosto/estilo.
# trecho_original: CITAÇÃO LITERAL do roteiro (para ancorar no documento). Vazio = global.
# correcao: o texto exato que entra no lugar (ou a adição, se trecho_original vazio).

SCHEMA_ACHADOS = {
    "type": "object",
    "properties": {
        "achados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severidade":      {"type": "string", "enum": ["erro", "aviso", "sugestao"]},
                    "natureza":        {"type": "string", "enum": ["objetivo", "subjetivo"]},
                    "confianca":       {"type": "integer", "minimum": 0, "maximum": 100},
                    "trecho_original": {"type": "string", "description": "Citação LITERAL do roteiro. Vazio se for um achado global (ex.: beat ausente, falta CTA)."},
                    "correcao":        {"type": "string", "description": "Texto concreto que entra no lugar do trecho (substituição direta) ou texto a adicionar (se trecho_original vazio). NUNCA repita o trecho_original aqui — se não tiver substituição concreta, deixe trecho_original vazio e use este campo para o texto novo a inserir. Instruções meta ('reordenar', 'introduzir antes de X') vão no campo porque, não aqui."},
                    "porque":          {"type": "string", "description": "Justificativa em 1 frase."},
                },
                "required": ["severidade", "natureza", "confianca", "trecho_original", "correcao", "porque"],
            },
        },
        "resumo": {"type": "string", "description": "1-2 frases de diagnóstico geral desta camada."},
        "nota":   {"type": "integer", "minimum": 0, "maximum": 10},
    },
    "required": ["achados", "resumo", "nota"],
}


# ─── Preferências do editor (guia de estilo / regras da casa) ─────────────────

_RAIZ = Path(__file__).parent.parent
PREFERENCIAS_PATH = _RAIZ / "preferencias.md"


def carregar_preferencias() -> str:
    """Lê o preferencias.md (regras de gosto do editor). Vazio se não existir."""
    if PREFERENCIAS_PATH.exists():
        return PREFERENCIAS_PATH.read_text(encoding="utf-8").strip()
    return ""


# ─── Utilitários ─────────────────────────────────────────────────────────────

def _sem_travessao(texto: str) -> str:
    """Substitui travessão (—) por vírgula ou hífen conforme o contexto."""
    if not texto:
        return texto
    # " — " entre palavras → ", "
    texto = texto.replace(" — ", ", ")
    # Travessão restante (início de frase, colado) → "-"
    texto = texto.replace("—", "-")
    return texto


# ─── Classe base ─────────────────────────────────────────────────────────────

_ORDEM_SEVERIDADE = {"sugestao": 1, "aviso": 2, "erro": 3}


class AgenteBase:
    """Base para todos os agentes. Gerencia o cliente Anthropic e o contrato."""

    MODELO = "claude-sonnet-4-5"
    MAX_TOKENS = 3000
    CAMADA = "geral"  # cada agente sobrescreve

    # Camadas que NÃO são eliminadores capam a severidade aqui (ex.: "aviso").
    # Assim, só ortografia, fato, checklist e coerência-[Entendimento] podem bloquear.
    SEVERIDADE_MAX = None

    def __init__(self):
        self.client = anthropic.Anthropic()
        self.preferencias = carregar_preferencias()

    # ── Bloco de preferências injetado em todo system prompt ──────────────────
    def _bloco_preferencias(self) -> str:
        if not self.preferencias:
            return ""
        return (
            "\n## REGRAS DA CASA (preferências do editor — prioridade máxima)\n"
            "As regras abaixo foram definidas pelo editor humano e têm prioridade sobre\n"
            "qualquer recomendação genérica. NÃO sugira nada que as contrarie. Se um achado\n"
            "seu seria rejeitado por essas regras, não o inclua.\n\n"
            f"{self.preferencias}\n"
        )

    # ── Bloco de calibração injetado em todo system prompt estruturado ────────
    def _bloco_calibracao(self) -> str:
        return (
            "\n## CALIBRAÇÃO: IMPACTO MÍNIMO E ÂNCORA PRECISA\n"
            "Só inclua um achado se a mudança for PERCEPTÍVEL PARA O ESPECTADOR FINAL do\n"
            "vídeo. Teste: se o roteiro fosse gravado com o trecho original e depois com o\n"
            "corrigido, o espectador notaria diferença audível, semântica ou de impacto?\n"
            "Se não → NÃO reporte. Não merecem ser achados: trocar sinônimo sem diferença\n"
            "de ritmo ou impacto, remover pronome sem ganho real de clareza, ajustar\n"
            "pontuação sem efeito na locução, reformular frase mantendo o mesmo sentido e\n"
            "mesmo ritmo.\n"
            "\nCITE O MÍNIMO em `trecho_original`: o menor segmento que ancora a mudança.\n"
            "Nunca a frase inteira quando só uma palavra ou expressão muda. Exemplo:\n"
            "  ERRADO: trecho='Ele fechou em 2008, mas reabriu em 2009.' (frase inteira)\n"
            "  CERTO:  trecho='2008, mas reabriu' correcao='2008, porém reabriu'\n"
        )

    # ── Chamada estruturada (força JSON via tool use) ─────────────────────────
    def _chamar_api_estruturada(self, system_prompt: str, user_prompt: str,
                                schema: dict = SCHEMA_ACHADOS) -> dict:
        resposta = self.client.messages.create(
            model=self.MODELO,
            max_tokens=self.MAX_TOKENS,
            system=[{
                "type": "text",
                "text": system_prompt + self._bloco_preferencias() + self._bloco_calibracao(),
                "cache_control": {"type": "ephemeral"},  # cacheia tools+system (5 min)
            }],
            tools=[{
                "name": "registrar_achados",
                "description": "Registra os achados estruturados desta análise.",
                "input_schema": schema,
            }],
            tool_choice={"type": "tool", "name": "registrar_achados"},
            messages=[{"role": "user", "content": user_prompt}],
        )
        for bloco in resposta.content:
            if bloco.type == "tool_use":
                return bloco.input
        return {"achados": [], "resumo": "", "nota": 0}

    # ── Chamada de texto livre (para o consolidador) ──────────────────────────
    def _chamar_api(self, system_prompt: str, user_prompt: str) -> str:
        resposta = self.client.messages.create(
            model=self.MODELO,
            max_tokens=self.MAX_TOKENS,
            system=[{
                "type": "text",
                "text": system_prompt + self._bloco_preferencias(),
                "cache_control": {"type": "ephemeral"},  # cacheia tools+system (5 min)
            }],
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resposta.content[0].text

    # ── Helper async: roda a chamada e carimba a camada em cada achado ────────
    async def _rodar(self, system_prompt: str, user_prompt: str,
                     schema: dict = SCHEMA_ACHADOS) -> dict:
        loop = asyncio.get_event_loop()
        resultado = await loop.run_in_executor(
            None,
            lambda: self._chamar_api_estruturada(system_prompt, user_prompt, schema),
        )
        achados_validos = []
        for achado in resultado.get("achados", []):
            achado["camada"] = self.CAMADA
            self._limitar_severidade(achado)
            # Limpa travessões dos campos gerados (não no trecho_original, que é citação literal)
            for campo in ("correcao", "porque", "resumo"):
                if campo in achado:
                    achado[campo] = _sem_travessao(achado[campo])
            trecho = (achado.get("trecho_original") or "").strip()
            correcao = (achado.get("correcao") or "").strip()
            if trecho and trecho == correcao:
                continue  # antes == depois: achado inválido, descarta
            achados_validos.append(achado)
        resultado["achados"] = achados_validos
        if "resumo" in resultado:
            resultado["resumo"] = _sem_travessao(resultado["resumo"])
        return resultado

    def _limitar_severidade(self, achado: dict):
        """Capa a severidade de camadas que não são eliminadores (SEVERIDADE_MAX)."""
        if not self.SEVERIDADE_MAX:
            return
        teto = _ORDEM_SEVERIDADE[self.SEVERIDADE_MAX]
        if _ORDEM_SEVERIDADE.get(achado.get("severidade"), 0) > teto:
            achado["severidade"] = self.SEVERIDADE_MAX

    async def analisar(self, roteiro: str) -> dict:
        """Cada agente sobrescreve. Retorna dict no formato SCHEMA_ACHADOS."""
        raise NotImplementedError("Cada agente deve implementar analisar()")

    def _formatar_roteiro(self, roteiro: str) -> str:
        return f"```\n{roteiro}\n```"
