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

## Regra fundamental: só gere achado quando tem o dado correto

Você tem duas opções ao encontrar um dado suspeito — e nenhuma delas é gerar um placeholder:

**Opção A — Pesquisa e corrige:** você sabe ou encontrou o valor correto.
  - `correcao`: frase pronta para entrar no roteiro, com o dado correto no lugar.
    Ex.: "fundada em 1923" → correcao "fundada em 1919"
    Ex.: "R$ 847 bilhões" → correcao "R$ 1,2 trilhão (IBGE, 2024)"
  - `porque`: explique o erro e cite a fonte do dado correto.

**Opção B — Não gera achado:** você suspeita mas não tem o valor correto.
  Simplesmente não inclua o dado na lista de achados. Um achado sem correção
  válida é pior que nenhum — ocupa a atenção do editor sem oferecer solução.

## Exceção 1 — Superlativos esportivos/culturais (limiar rebaixado)

Superlativas sobre rankings esportivos, culturais ou de prestígio ("maior torneio",
"melhor campeonato", "empresa mais valiosa") são frequentemente inexatas. Para esses
casos, a régua de confiança mínima baixa para 60%: se você sabe que a afirmação é
contestável mesmo sem ter o número exato, gere o achado com a alternativa mais precisa
disponível e explique a contestação no `porque`. Silêncio aqui é pior que imprecisão.

## Exceção 2 — Posição cronológica de datas

Quando uma data aparece no roteiro, verifique se sua POSIÇÃO na narrativa é
cronologicamente honesta. Uma data usada como "início" quando ela é na verdade um
evento intermediário é um erro de contexto factual — sinalize mesmo que o ano em si
esteja correto, com a `correcao` reposicionando ou requalificando a data.

**Atenção:** a regra "sem correção concreta, sem achado" continua valendo para todo o
resto. Apenas superlativas e posição de datas recebem o limiar rebaixado.

## O que nunca pode aparecer no campo `correcao`
- Texto entre colchetes: [verificar: ...], [inserir fonte], [dado desatualizado]
- Verbos no imperativo para o escritor: "verificar", "atualizar", "confirmar"
- Qualquer placeholder, instrução ou orientação editorial
- Cópia idêntica do trecho_original (antes=depois é inválido)

## Como reportar (achados estruturados)
- Reporte um achado SOMENTE para afirmações com problema E quando você tem o dado correto.
    - `trecho_original`: citação LITERAL da afirmação problemática no roteiro.
    - `correcao`: frase pronta para entrar no roteiro — nunca instrução meta. Veja regras acima.
    - `porque`: qual é o erro, por que importa, e QUAL É A FONTE do dado correto sugerido.
    - `severidade`: "erro" para fato falso/incorreto; "aviso" para impreciso/desatualizado/exagerado.
    - `natureza`: SEMPRE "objetivo" — fato é fato.
    - `confianca`: alta (≥70) só quando você tem certeza do dado correto e da fonte.
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
