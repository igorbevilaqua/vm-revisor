"""
Agente — Fact-Check
Verifica fatos, dados, datas, valores e nomes do roteiro.
Cada afirmação incorreta ou imprecisa vira um achado OBJETIVO (alta prioridade).

Modo `verificar_web` (opcional): faz uma 1ª fase com busca na web (server-side) para
conferir as afirmações com fonte, e depois estrutura os achados. Off por padrão (custo).
"""

import asyncio
import re

from agentes import AgenteBase


def tem_fato_verificavel(texto: str) -> bool:
    """Heurística barata (sem LLM): o roteiro tem algo verificável que justifique o
    fact-check? Números, %, valores, datas/anos, quantidades. Se não tiver nada disso,
    pula o fact-check e economiza uma chamada."""
    if re.search(r"\d", texto):  # qualquer dígito (ano, valor, %, estatística...)
        return True
    if re.search(r"\b(por cento|bilh|milh|trilh|metade|dobro|triplo|maioria|"
                 r"primeiro|maior|menor|único|recorde)\b", texto, re.IGNORECASE):
        return True
    return False


SYSTEM_PROMPT = """Você é o Agente de Fact-Check da Viral Media Labs (VML).

Sua função é identificar e verificar todos os fatos, dados, datas, valores, nomes e
afirmações verificáveis do roteiro, e reportar os que estão incorretos, imprecisos ou
exagerados a ponto de prejudicar a credibilidade.

## Como reportar (achados estruturados)
- Reporte um achado SOMENTE para afirmações com problema (incorretas, imprecisas,
  desatualizadas ou exageradas). Fato correto NÃO vira achado.
    - `trecho_original`: a citação LITERAL da afirmação problemática no roteiro.
    - `correcao`: SEMPRE uma frase pronta para entrar no roteiro — nunca uma instrução meta.
      · Se você SABE o dado correto: substitua o dado errado pelo correto na frase.
        Ex.: trecho "fundada em 1923" → correcao "fundada em 1919"
      · Se você NÃO tem certeza do valor exato: mantenha a frase intacta mas substitua o
        dado suspeito por "[verificar: X]", onde X é o que precisa ser conferido.
        Ex.: trecho "lucro de R$ 4 bilhões" → correcao "lucro de [verificar: valor exato]"
      · NUNCA copie o trecho_original no campo correcao — antes=depois é inválido.
    - `porque`: qual é o erro e por que importa para a credibilidade. Se usou
      "[verificar: X]", explique por que o dado parece incorreto/impreciso.
    - `severidade`: "erro" para fato falso/incorreto; "aviso" para impreciso/desatualizado/exagerado.
    - `natureza`: SEMPRE "objetivo" — fato é fato.
    - `confianca`: alta só quando você tem certeza do dado correto. Se usou "[verificar: X]",
      use confianca <= 60 (sinal de checagem manual).
- Não invente erro. Não trate opinião do autor como fato a verificar.
- `nota` (0-10): confiabilidade factual geral. `resumo`: nº de afirmações checadas e nº de problemas."""


class AgenteFactCheck(AgenteBase):

    CAMADA = "factcheck"

    def __init__(self, conteudo_pdf: str = "", verificar_web: bool = False):
        super().__init__()
        self.system_prompt = SYSTEM_PROMPT
        self.verificar_web = verificar_web

    # ── Fase 1 (opcional): conferir as afirmações na web (server-side tool) ───
    def _verificar_na_web(self, roteiro: str) -> str:
        prompt = f"""Liste as afirmações factuais verificáveis deste roteiro (datas, números,
nomes, estatísticas, relações causais) e CONFIRA cada uma buscando na web. Para cada uma,
diga: a afirmação, se está correta/incorreta/imprecisa, o dado correto e a fonte (URL).

{self._formatar_roteiro(roteiro)}"""
        mensagens = [{"role": "user", "content": prompt}]
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
        resp = None
        try:
            for _ in range(4):  # trata pause_turn do loop server-side
                resp = self.client.messages.create(
                    model=self.MODELO,
                    max_tokens=2500,
                    system=[{"type": "text", "text": self.system_prompt,
                             "cache_control": {"type": "ephemeral"}}],
                    tools=tools,
                    messages=mensagens,
                )
                if resp.stop_reason == "pause_turn":
                    mensagens = [mensagens[0], {"role": "assistant", "content": resp.content}]
                    continue
                break
        except Exception as e:
            return f"[Busca na web indisponível: {e.__class__.__name__}. Verifique de memória.]"
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    async def analisar(self, roteiro: str) -> dict:
        loop = asyncio.get_event_loop()
        evidencia = ""
        if self.verificar_web:
            evidencia = await loop.run_in_executor(None, lambda: self._verificar_na_web(roteiro))

        bloco_web = f"""

EVIDÊNCIA DA WEB (resultado de busca real — use para classificar e cite a fonte no `correcao`/`porque`):
{evidencia}
""" if evidencia else ""

        user_prompt = f"""Verifique os fatos deste roteiro:

{self._formatar_roteiro(roteiro)}
{bloco_web}
Seja rigoroso — o público confia na VML para conteúdo preciso. Reporte cada afirmação
incorreta ou imprecisa com o trecho literal e a correção factual. Sinalize com confiança
baixa o que você não consegue confirmar com certeza (precisa de checagem manual)."""
        return await self._rodar(self.system_prompt, user_prompt)
