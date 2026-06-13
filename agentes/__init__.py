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
import re
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


# Seção do preferencias.md escrita pelo feedback.py (regras aprendidas com rejeições).
MARCADOR_APRENDIDO = "## [10] APRENDIDO COM REJEIÇÕES"

# Tags de camada reconhecidas nas regras da seção [10]. Convenção:
#   - [YYYY-MM-DD] [ortografia] regra...   → só o agente de ortografia recebe
#   - [YYYY-MM-DD] regra...                → geral, todos recebem
_CAMADAS_TAG = {"ortografia", "clareza", "coerencia", "checklist", "storytelling",
                "factcheck", "hook", "cta", "viral"}
_RE_TAG_CAMADA = re.compile(r"^-\s*\[\d{4}-\d{2}-\d{2}\]\s*\[([a-zA-Z]+)\]")


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


_VERBOS_INSTRUCAO = (
    "remover", "remove", "substituir", "substitua", "substituindo",
    "reduzir", "reduza", "reduzindo",
    "verificar", "verifique", "verificando",
    "ajustar", "ajuste", "ajustando",
    "reordenar", "reordene",
    "inserir", "insira", "inserindo",
    "trocar", "troque", "trocando",
    "corrigir", "corrija", "corrigindo",
    "adicionar", "adicione", "adicionando",
    "excluir", "exclua", "excluindo",
    "eliminar", "elimine", "eliminando",
    "incluir", "inclua", "incluindo",
    "reescrever", "reescreva", "reescrevendo",
)


def _e_instrucao_meta(correcao: str) -> bool:
    """True se `correcao` começa com um verbo de instrução editorial (imperativo/infinitivo).
    Detecta o caso em que o agente colocou uma instrução no lugar do texto substituto."""
    if not correcao:
        return False
    primeira = correcao.strip().split()[0].lower().rstrip(".,;:)")
    return primeira in _VERBOS_INSTRUCAO


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
        # Contexto do roteiro em revisão (cliente/tema/estrutura) — setado por
        # processar_roteiro antes de analisar(); filtra os aprendizados injetados.
        self.filtro_aprendizados = {}

    # ── Data atual injetada em todo system prompt (âncora para fact-check) ──────
    def _bloco_data_atual(self) -> str:
        from datetime import date
        hoje = date.today()
        meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                 "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
        return (
            f"\n## DATA ATUAL\n"
            f"Hoje é {hoje.day} de {meses[hoje.month - 1]} de {hoje.year}. "
            f"Use esta data como referência para fact-check e avaliação de atualidade "
            f"dos dados. Sua base de treinamento pode estar desatualizada — sinalize "
            f"com confiança baixa (≤60%) qualquer afirmação que possa ter mudado "
            f"recentemente, em vez de corrigi-la com base em dados do seu treinamento.\n"
        )

    # ── Bloco de preferências injetado em todo system prompt ──────────────────
    def _preferencias_filtradas(self) -> str:
        """Seções [1]-[9] entram inteiras (regras gerais da casa). Na seção [10],
        regras com tag de OUTRA camada são filtradas — só entram as da própria
        camada (self.CAMADA) e as sem tag (gerais). Economiza tokens por chamada."""
        texto = self.preferencias
        if MARCADOR_APRENDIDO not in texto:
            return texto
        cabeca, secao10 = texto.split(MARCADOR_APRENDIDO, 1)
        linhas = []
        for linha in secao10.splitlines():
            m = _RE_TAG_CAMADA.match(linha.strip())
            if m and m.group(1).lower() in _CAMADAS_TAG and m.group(1).lower() != self.CAMADA:
                continue  # regra de outra camada — não gasta tokens aqui
            linhas.append(linha)
        return cabeca + MARCADOR_APRENDIDO + "\n".join(linhas)

    def _bloco_preferencias(self) -> str:
        # Nova estrutura: aprendizados.json indexado por contexto — cada agente
        # recebe só o que é relevante para a camada dele + cliente/tema/estrutura
        # do roteiro atual. Enquanto o arquivo não existir (migração não rodada),
        # cai no legado: preferencias.md inteiro.
        corpo = None
        try:
            import aprendizados
            f = self.filtro_aprendizados or {}
            corpo = aprendizados.corpo_para_prompt(
                camada=self.CAMADA, cliente=f.get("cliente", ""),
                tema=f.get("tema", ""), estrutura=f.get("estrutura", ""))
        except Exception:
            corpo = None  # qualquer falha na nova estrutura nunca derruba o agente
        if corpo is None:
            if not self.preferencias:
                return ""
            corpo = self._preferencias_filtradas()
        if not corpo.strip():
            return ""
        return (
            "\n## REGRAS DA CASA (preferências do editor — prioridade máxima)\n"
            "As regras abaixo foram definidas pelo editor humano e têm prioridade sobre\n"
            "qualquer recomendação genérica. NÃO sugira nada que as contrarie. Se um achado\n"
            "seu seria rejeitado por essas regras, não o inclua.\n\n"
            f"{corpo}\n"
        )

    # ── Bloco de calibração injetado em todo system prompt estruturado ────────
    def _bloco_calibracao(self) -> str:
        return (
            "\n## CALIBRAÇÃO: IMPACTO MÍNIMO, ÂNCORA PRECISA E CORRECAO CONCRETA\n"
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
            "\n### REGRA CRÍTICA: `correcao` é texto que entra no roteiro — nunca instrução\n"
            "`correcao` deve conter APENAS o texto literal pronto para substituir o trecho\n"
            "no roteiro. O leitor vai ver exatamente esse texto no lugar do original.\n"
            "PROIBIDO em `correcao`: frases que começam com 'Remover', 'Substituir',\n"
            "'Reduzir', 'Verificar', 'Ajustar', 'Reordenar', 'Inserir', 'Trocar', ou\n"
            "qualquer outra instrução meta de edição.\n"
            "Instruções de edição vão SEMPRE no campo `porque`, nunca em `correcao`.\n"
            "\nSe você não tem o texto exato de reposição (ex.: não sabe qual data é\n"
            "correta, não sabe quais palavras cortar, ou a mudança é estrutural global):\n"
            "  → Deixe AMBOS `trecho_original` E `correcao` VAZIOS.\n"
            "  → Explique o problema e a direção de correção em `porque`.\n"
            "  → Use o campo `resumo` para observações que não têm substituto concreto.\n"
            "Achado com instrução em `correcao` é INVÁLIDO e será descartado.\n"
        )

    # ── Chamada estruturada (força JSON via tool use) ─────────────────────────
    def _chamar_api_estruturada(self, system_prompt: str, user_prompt: str,
                                schema: dict = SCHEMA_ACHADOS) -> dict:
        resposta = self.client.messages.create(
            model=self.MODELO,
            max_tokens=self.MAX_TOKENS,
            system=[{
                "type": "text",
                "text": system_prompt + self._bloco_data_atual() + self._bloco_preferencias() + self._bloco_calibracao(),
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
                "text": system_prompt + self._bloco_data_atual() + self._bloco_preferencias(),
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
        # O tool use força o nome da tool, mas NÃO valida estritamente o conteúdo:
        # o modelo pode devolver achados como strings (JSON serializado) ou outro
        # formato fora do schema. Recupera o que der e descarta o resto — um achado
        # malformado nunca pode derrubar a camada inteira.
        if not isinstance(resultado, dict):
            return {"achados": [], "resumo": "", "nota": 0}
        achados_brutos = resultado.get("achados", [])
        if not isinstance(achados_brutos, list):
            achados_brutos = []
        achados_validos = []
        descartados = 0
        for achado in achados_brutos:
            if isinstance(achado, str):
                # Achado veio como JSON dentro de string — tenta desserializar
                try:
                    import json as _json
                    achado = _json.loads(achado)
                except (ValueError, TypeError):
                    descartados += 1
                    continue
            if not isinstance(achado, dict):
                descartados += 1
                continue
            # Normaliza campos de texto fora do tipo (o resto do pipeline assume str)
            for campo in ("severidade", "natureza", "trecho_original", "correcao", "porque"):
                v = achado.get(campo)
                if v is not None and not isinstance(v, str):
                    achado[campo] = str(v)
            achado["camada"] = self.CAMADA
            self._limitar_severidade(achado)
            # Limpa travessões dos campos gerados (não no trecho_original, que é citação literal)
            for campo in ("correcao", "porque", "resumo"):
                if isinstance(achado.get(campo), str):
                    achado[campo] = _sem_travessao(achado[campo])
            trecho = (achado.get("trecho_original") or "").strip()
            correcao = (achado.get("correcao") or "").strip()
            if trecho and trecho == correcao:
                continue  # antes == depois: achado inválido, descarta
            if _e_instrucao_meta(correcao):
                # O agente colocou instrução editorial em correcao — move para porque
                # e zera ambos os campos de âncora para tratar como nota global.
                porque_atual = (achado.get("porque") or "").strip()
                achado["porque"] = f"{porque_atual} [Sugestão estrutural: {correcao}]".strip()
                achado["trecho_original"] = ""
                achado["correcao"] = ""
            achados_validos.append(achado)
        if descartados:
            print(f"  🧹 {self.CAMADA}: {descartados} achado(s) malformado(s) descartado(s)")
        resultado["achados"] = achados_validos
        if isinstance(resultado.get("resumo"), str):
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
