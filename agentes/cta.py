"""
Agente — CTA (Comando)
Avalia o CTA do roteiro com base no Playbook dos Comandos da VML.
Metodologia: "CTA com Esteróides" — 7 gatilhos psicológicos.
O problema do CTA atual + as versões recomendadas viram achados estruturados.
"""

from agentes import AgenteBase


PLAYBOOK_CTA = """## Os 7 Gatilhos do "CTA com Esteróides" (Playbook VML)

O CTA eficaz da VML não é genérico — usa um dos 7 gatilhos, sempre conectado ao tema:

1. **Exclusividade** — "Se você faz parte da minoria que [valor], segue esse perfil."
2. **Expectativa** — "Eu sou [nome] e [o que faço] todos os dias."
3. **Benefício Percebido** — "Eu sou [nome] e segue meu perfil para [benefício específico]."
4. **Propósito/Altruísmo** — "Se você acredita que mais [audiência] precisam saber disso, segue esse perfil."
5. **Comunicação** — "Se você valoriza [tipo de conteúdo], me deixa saber curtindo esse vídeo."
6. **Inimigo em Comum** — "Infelizmente [o que o inimigo esconde]. Segue para..."
7. **Autoridade** — "Eu sou [nome], [prova de autoridade] e todo dia [promessa]. Me segue."

## Regras do CTA eficaz (VML)
- Sempre ao FINAL, depois da resolução narrativa.
- UMA única ação — nunca "curte, comenta E salva".
- 100% coerente com o tema — CTA genérico desperdiça o contexto emocional construído.
- Linguagem natural, curta (1-3 frases).

## Erros críticos
- CTA ausente · CTA genérico ("curte e segue") · múltiplas ações ·
  CTA no meio do roteiro · gatilho errado para o contexto."""


def bloco_cliente(cliente: str = "") -> str:
    if cliente:
        return (
            f"\n## Cliente / criador deste roteiro\n"
            f"Quem vai performar este roteiro é: **{cliente}**. Use ESTE nome no comando\n"
            f"(gatilhos de Expectativa/Autoridade/Benefício que começam com 'Eu sou ...').\n"
            f"NÃO use 'Igor' nem invente outro nome — este roteiro é deste cliente.\n"
        )
    return (
        "\n## Cliente / criador deste roteiro\n"
        "O nome do criador NÃO foi identificado no documento. Nem todo roteiro é do Igor.\n"
        "Nos comandos que precisam do nome (gatilhos 'Eu sou ...'), use o placeholder\n"
        "[nome do cliente] — NÃO invente um nome e NÃO assuma que é o Igor. Se o roteiro/\n"
        "documento indicar quem vai performar, use esse nome.\n"
    )


def montar_system(complemento: str, cliente: str = "") -> str:
    return f"""Você é o Agente de CTA (Comando) da Viral Media Labs (VML).

Sua função é avaliar o CTA do roteiro pela metodologia "CTA com Esteróides" e propor
versões fortes, 100% adaptadas ao TEMA deste roteiro específico.

{PLAYBOOK_CTA}
{bloco_cliente(cliente)}{complemento}

## Como reportar (achados estruturados)
- Achado PRINCIPAL sobre o CTA atual:
    - `trecho_original`: o CTA atual, citação literal (vazio se AUSENTE).
    - `correcao`: a SUA melhor versão de CTA com Esteróides recomendada para este roteiro.
    - `porque`: o problema do atual (ausente/genérico/múltiplas ações/posição/gatilho errado)
      e qual gatilho a sua versão usa e por que cabe aqui.
    - `severidade`: "erro" se CTA ausente ou genérico/quebrado; "aviso" se ok mas melhorável.
    - `natureza`: "objetivo" para ausência/regra violada (sem CTA, múltiplas ações); "subjetivo"
      para a escolha de gatilho.
- 1-2 achados "sugestao" com versões ALTERNATIVAS de CTA usando gatilhos DIFERENTES.
- Se o comando atual usar um padrão que FUNCIONA mas NÃO está entre os 7 gatilhos do playbook,
  registre um achado "sugestao" sinalizando isso (ex.: "este comando usa um padrão eficaz fora dos
  7 gatilhos — pode valer adicionar ao playbook"). O playbook pode evoluir.
- Respeite as REGRAS DA CASA (gatilhos/estilo de CTA que o editor prefere ou rejeita).
- `nota` (0-10): força do CTA atual."""


class AgenteCTA(AgenteBase):

    CAMADA = "cta"
    SEVERIDADE_MAX = "aviso"  # comando ausente/genérico já é eliminado pelo checklist; aqui é otimização

    def __init__(self, conteudo_pdf: str = "", cliente: str = ""):
        super().__init__()
        complemento = ""
        if conteudo_pdf:
            complemento = f"\n\n## Playbook dos Comandos (íntegra):\n{conteudo_pdf}"
        self.system_prompt = montar_system(complemento, cliente=cliente)

    async def analisar(self, roteiro: str) -> dict:
        user_prompt = f"""Avalie o CTA deste roteiro usando o Playbook dos Comandos da VML:

{self._formatar_roteiro(roteiro)}

Identifique o CTA atual (ou ausência) e registre a sua versão recomendada como achado
principal, mais 1-2 alternativas com gatilhos diferentes. Cada versão 100% adaptada ao
tema deste roteiro — nunca genérica."""
        return await self._rodar(self.system_prompt, user_prompt)
