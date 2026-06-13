"""
Agente Bob — reescritor sob demanda do sistema de revisão.

Acionado pelo botão ✦ Bob na tabela: quando uma sugestão não serviu, o revisor
diz em uma linha o que está errado e o Bob entrega uma reescrita melhor, já
incorporando o feedback. Sempre exige feedback (não reescreve no escuro).

Diferente dos 9 agentes analíticos, o Bob:
  - é interativo (1 chamada por clique, sob demanda do humano);
  - recebe trecho + sugestão rejeitada + feedback + agente de origem;
  - injeta os aprendizados da casa (globais + do cliente) na reescrita;
  - NUNCA deixa travessão na reescrita (regra da casa, via _sem_travessao);
  - se o feedback for vago, faz UMA pergunta em vez de chutar.

Saída via tool use (schema validado), no padrão do projeto — não JSON em texto.
"""

from __future__ import annotations

from agentes import AgenteBase, _sem_travessao


SCHEMA_BOB = {
    "type": "object",
    "properties": {
        "precisa_esclarecer": {
            "type": "boolean",
            "description": "true se o feedback do revisor é vago demais para reescrever com "
                           "segurança. Nesse caso, bob_comment traz a PERGUNTA e reescrita fica vazia.",
        },
        "bob_comment": {
            "type": "string",
            "description": "UMA linha curta, direta, levemente debochada sobre o problema (ou a "
                           "pergunta, se precisa_esclarecer). Sem saudação, sem começar com 'Eu', "
                           "sem 'Olá'/'Claro'. É sobre o problema, não sobre você.",
        },
        "reescrita": {
            "type": "string",
            "description": "O trecho reescrito, já corrigindo o que o feedback apontou, na voz do "
                           "autor. Vazio se precisa_esclarecer=true.",
        },
    },
    "required": ["precisa_esclarecer", "bob_comment", "reescrita"],
}


SYSTEM_BOB = """Você é o Bob, o reescritor do sistema de revisão de roteiros de Reels da Viral Media Labs. Quando uma sugestão não serviu, você entra, entende o que deu errado e entrega algo melhor.

## TOM
Irreverente, direto, levemente debochado, nunca grosseiro. Energia de redator sênior que já viu de tudo e não tem paciência pra enrolação, mas quer ajudar de verdade.
- Faça UMA observação curta e afiada sobre o problema, depois entregue a reescrita limpa.
- Não filosofe, não explique demais, não peça desculpa. Humor seco quando cabe, sem sacrificar a qualidade.
- Trate o revisor como colega criativo, não como chefe nem aluno.

Exemplos de comentário (o campo bob_comment):
- problema "palavra difícil pro público": "Bonobo é primo do chimpanzé e de vocabulário difícil. Tirei o jargão:"
- problema "ficou longo": "Tava com gordura extra. Cortei a frescura:"
- problema "hook não prende": "Esse gancho tava mais pra sonífero. Tentei outro:"
- problema "formal demais": "Tava cheirando a relatório corporativo. Destravei:"

## O QUE VOCÊ RECEBE
TRECHO ORIGINAL, SUGESTÃO ANTERIOR (a que não serviu), FEEDBACK DO REVISOR, e CONTEXTO DO AGENTE (qual camada gerou a sugestão: Clareza, Hook, CTA, etc.).

## REGRAS INEGOCIÁVEIS
1. SEMPRE corrija o que o feedback apontou. O problema é o centro da reescrita.
2. Mantenha a VOZ e o estilo do roteiro original. Você corrige, não substitui o autor.
3. Não alongue. Se o trecho original tem 3 linhas, a reescrita tem no máximo 4.
4. Sem jargão técnico, a menos que o original já use.
5. PROIBIDO travessão (—) na reescrita E no comentário. Use vírgula, dois pontos ou conectivo natural. É a regra mais forte da casa.
6. Não invente fato (número, data, causa, nome) que não esteja no original. Se o feedback exige um fato que você não tem, sinalize no comentário em vez de inventar.
7. O comentário (bob_comment) é sobre o PROBLEMA, em UMA linha. Sem saudação, sem começar com "Eu".
8. Se o feedback for vago demais (ex.: "não gostei", "tá ruim"), NÃO chute: marque precisa_esclarecer=true e use bob_comment para uma pergunta curta e específica (ex.: "Vago demais pra eu trabalhar. O que não serviu, o tom, a palavra ou o tamanho?"). Deixe reescrita vazia.

Respeite as REGRAS DA CASA (preferências do editor) que vierem no contexto: a reescrita não pode contrariá-las."""


class AgenteBob(AgenteBase):
    """Reescritor interativo. Síncrono (chamado por rota Flask, sob demanda)."""

    CAMADA = ""  # transversal: recebe aprendizados de todas as camadas + do cliente

    def reescrever(self, trecho_original: str, sugestao_anterior: str, feedback: str,
                   agente_origem: str = "", cliente: str = "", tema: str = "",
                   estrutura: str = "") -> dict:
        """Uma reescrita do Bob. Retorna {bob_comment, reescrita, precisa_esclarecer}."""
        # Aprendizados da casa + do cliente entram via _bloco_preferencias (CAMADA="")
        self.filtro_aprendizados = {"cliente": cliente, "tema": tema, "estrutura": estrutura}
        system = SYSTEM_BOB + self._bloco_data_atual() + self._bloco_preferencias()
        user = (
            f"TRECHO ORIGINAL:\n{trecho_original}\n\n"
            f"SUGESTÃO ANTERIOR:\n{sugestao_anterior or '(nenhuma)'}\n\n"
            f"FEEDBACK DO REVISOR:\n{feedback}\n\n"
            f"CONTEXTO DO AGENTE:\n{agente_origem or '(não informado)'}"
        )
        resposta = self.client.messages.create(
            model=self.MODELO,
            max_tokens=1500,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=[{"name": "responder", "description": "Resposta do Bob (comentário + reescrita).",
                    "input_schema": SCHEMA_BOB}],
            tool_choice={"type": "tool", "name": "responder"},
            messages=[{"role": "user", "content": user}],
        )
        bruto = {}
        for bloco in resposta.content:
            if bloco.type == "tool_use":
                bruto = bloco.input
                break
        precisa = bool(bruto.get("precisa_esclarecer"))
        comment = _sem_travessao((bruto.get("bob_comment") or "").strip())
        reescrita = _sem_travessao((bruto.get("reescrita") or "").strip())
        # Se disse que reescreveu mas veio vazio, trata como pedido de esclarecimento
        if not precisa and not reescrita:
            precisa = True
            comment = comment or "Não consegui trabalhar com isso. Me diz com mais precisão o que ajustar?"
        return {"bob_comment": comment,
                "reescrita": "" if precisa else reescrita,
                "precisa_esclarecer": precisa}
