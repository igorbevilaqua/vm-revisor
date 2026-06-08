"""
Agente — Coerência & Continuidade
Auditor da coesão do roteiro em DUAS dimensões:

  1. ENTENDIMENTO (lógica/referencial) — personagem/premissa usado antes de ser
     introduzido, falta de contexto, salto causal/temporal, referência pendurada,
     setup sem payoff. Em geral OBJETIVO (gap verificável).

  2. SENTIMENTO (emoção) — segundo o Playbook de Storytelling VML, cada estrutura
     do CODEX só dispara sua emoção se certos BEATS existirem e na ordem certa.
     Quando falta um beat exigido, a emoção não se constrói — o roteiro fica
     "correto" mas frio. Aqui o gap quebra o SENTIMENTO, não a lógica.

É separado do agente de Storytelling de propósito: storytelling julga o que é
magnético (subjetivo); coerência audita o que está faltando para entender e sentir.
"""

from agentes import AgenteBase


# Conhecimento destilado do Playbook de Storytelling — modos de falha que QUEBRAM
# o sentimento (o beat ausente impede o mecanismo emocional de disparar).
MECANISMOS_EMOCIONAIS = """## Como o sentimento se constrói (Playbook de Storytelling VML)

Cada estrutura do CODEX tem um MECANISMO EMOCIONAL que só dispara se seus beats
estiverem presentes e na ordem certa. Beat ausente ou fora de ordem = sentimento não vem.
Modos de falha conhecidos (use-os para detectar quebra de SENTIMENTO):

- Jornada do Herói: SEM a decisão contraintuitiva ("todos chamaram de louco"), vira
  história de sucesso comum — inspira mas não emociona nem viraliza.
- Herói Improvável: adversidade SEM número/fato concreto → a vitória não é sentida como
  extraordinária (o cérebro não calibra adversidade abstrata).
- Herói Esquecido: feito SEM comparação com algo famoso → a escala da injustiça não é
  sentida; a "raiva moral" (motor de compartilhamento) não acende.
- Davi e Golias: escala do Golias NÃO declarada/quantificada e absurda → sem tensão, a
  vitória do Davi não é catártica. O Golias precisa intimidar.
- Conflito Imprevisível: se o espectador não consegue torcer por NENHUM dos dois lados
  (motivações humanas), a paridade não gera suspense.
- Queda do Gigante: colapso que não é total/irreversível → não é schadenfreude, é recuperação.
- Iconoclasta: a crença atacada NÃO é genuinamente popular/enraizada → sem ameaça ao ego
  epistêmico, não há tensão; o vídeo não tem motivo para existir.
- Estratégia Oculta / Investigação: revelação sem o "o que ninguém sabe" ou sem payoff
  verificável → quebra a promessa de acesso privilegiado.
- Urgência & Alerta: SEM saída prática no fim → espectador paralisado, não engaja.
- Evento Global / Efeito Dominó: conexão com o Brasil ausente/forçada, ou um elo causal
  com "talvez/pode ser" → quebra a inevitabilidade (o "dread") que é o motor.
- Erro Fatal: grandeza do sucesso e fragilidade do erro NÃO estão no mesmo quadro → sem a
  ironia explícita, não há descarga emocional.
- Paradoxo Contraintuitivo: se depois de explicado parece óbvio → a dissonância não existia.
- Narrativa Filosófica: virada de perspectiva ausente ou depois dos 30s → não há "aha".

## Regra de ouro dos 3 eixos
Todo roteiro forte toca pelo menos um eixo: (1) ameaça ao status quo do espectador,
(2) expansão da crença sobre o possível, (3) acesso a informação que reorganiza a visão
de mundo. 1 eixo = sólido · 2 = viraliza · 3 = 10M+. Emoção difusa, sem eixo dominante
claro, é sinal de quebra de sentimento.

## Setup → Payoff
Toda tensão, pergunta em aberto, promessa ("vou te mostrar...") ou elemento plantado
PRECISA ter resolução. Setup sem payoff frustra; payoff sem setup confunde."""


# Regra nomeada de coesão lógica entre frases consecutivas (dimensão ENTENDIMENTO).
REGRA_COESAO_FRASES = """## COESÃO_ENTRE_FRASES (regra de ENTENDIMENTO)

Quando duas frases CONSECUTIVAS têm CARGA SEMÂNTICA OPOSTA (uma positiva e a outra
negativa, ou vice-versa) e NÃO há um conectivo de oposição ligando-as, o texto soa como
uma lista de fatos soltos, sem lógica narrativa. Nesse caso é OBRIGATÓRIO um conectivo
adversativo no início da segunda frase.

Conectivos de oposição válidos: "mas", "porém", "mesmo assim", "no entanto",
"apesar disso", "ainda assim", "contudo".

COMO DETECTAR (faça par a par):
1. Para cada par de frases consecutivas (A, B), avalie a carga de cada uma: positiva,
   negativa ou neutra.
2. Se A e B têm cargas OPOSTAS (uma positiva, outra negativa) E não existe conectivo de
   oposição entre elas → SINALIZE. A `correcao` apenas INSERE o conectivo adequado no
   início de B (ou junta as frases com vírgula + "mas"); nunca reescreva a voz do autor
   nem invente fato novo.

EXEMPLOS DE REFERÊNCIA:
- ERRADO: "A Inditex fechou 136 lojas ao redor do mundo. A receita chegou a 8,27 bilhões
  de euros só no primeiro trimestre."  (fechar lojas = negativo; receita alta = positivo)
  CERTO: "A Inditex fechou 136 lojas ao redor do mundo. Mesmo assim, a receita chegou a
  8,27 bilhões de euros só no primeiro trimestre."
- ERRADO: "A Maria é gente boa. Bate em velhinho na rua."
  CERTO: "A Maria é gente boa, mas bate em velhinho na rua."

NÃO CONFUNDIR COM SOMA (NÃO sinalizar):
Quando B REFORÇA, JUSTIFICA ou apenas ADICIONA na MESMA direção semântica de A (mesma
carga), não há quebra. Ex.: "A Maria é gente boa. Gosta de video game." → OK, ignore.

CLASSIFICAÇÃO: achado de [Entendimento], severidade "aviso" + natureza "objetivo" — a
oposição de cargas é verificável, mas a falta do conectivo não IMPEDE a compreensão (é
coesão narrativa), então NÃO bloqueia o veredicto. Comece o `porque` com "[Entendimento] "."""


def montar_system(base_conhecimento: str) -> str:
    return f"""Você é o Agente de Coerência & Continuidade da Viral Media Labs (VML).

Você audita se o roteiro é coeso e coerente em DUAS dimensões: ENTENDIMENTO (lógica) e
SENTIMENTO (a emoção se constrói?). Trabalhe de forma METÓDICA, não holística.

{base_conhecimento}

{MECANISMOS_EMOCIONAIS}

{REGRA_COESAO_FRASES}

## Procedimento (siga nesta ordem, mentalmente)
1. Identifique a estrutura CODEX em uso (ou a pretendida) e a emoção-alvo.
2. INVENTÁRIO: liste cada personagem, entidade, premissa e termo técnico, e onde cada um
   é introduzido pela primeira vez.
3. ENTENDIMENTO — para cada referência, verifique: foi introduzida ANTES de ser usada?
   tem contexto suficiente? Há salto causal/temporal (um passo lógico pulado)? Referência
   pendurada (pronome/“isso” sem antecedente claro)? Setup sem payoff? Ordem confusa?
   Aplique também a regra COESÃO_ENTRE_FRASES: varra os pares de frases consecutivas e
   sinalize oposição de carga semântica sem conectivo adversativo (respeitando a exceção
   de SOMA/reforço).
4. SENTIMENTO — dada a estrutura, os BEATS exigidos para a emoção disparar estão presentes
   e na ordem certa? Aplique os modos de falha acima. A emoção tem um eixo dominante claro?

## Como reportar (achados estruturados)
- Um achado por gap. Comece o campo `porque` com "[Entendimento] " ou "[Sentimento] "
  para deixar claro qual coesão quebra.
- `trecho_original`: a citação LITERAL onde o gap aparece (ex.: a linha que cita algo não
  introduzido, ou o clímax sem preparo). Vazio se for um beat AUSENTE no roteiro todo.
- `correcao`: texto concreto pronto para entrar no roteiro — nunca uma instrução meta.
  · Se é substituição: o trecho reescrito (ex.: "Mesmo assim, a receita chegou a 8,27 bi.").
  · Se é adição (beat ausente): o texto novo a inserir (ex.: "Todos chamaram Jensen de louco.").
  · Se não tem substituição concreta possível: deixe `trecho_original` vazio e use `correcao`
    para o texto a adicionar. A justificativa e o onde inserir vão no campo `porque`.
  · NUNCA copie o trecho_original no campo correcao — achado com antes=depois é inválido.
- `severidade`/`natureza`:
    · [Entendimento] que IMPEDE o espectador de entender (referência sem introdução, salto
      causal que perde o leitor, 2+ blocos sem conexão lógica) = "erro" + "objetivo".
    · [Sentimento] beat que FORTALECERIA a emoção mas está ausente (decisão contraintuitiva,
      Golias não quantificado, setup sem payoff) = "aviso" + "objetivo" — NÃO reprova sozinho,
      pois o roteiro já ativa emoção; é otimização forte. Use "erro" SÓ se o roteiro não ativa
      NENHUMA emoção identificável (aí viola o checklist).
    · Ajuste de intensidade/tom emocional = "sugestao"/"aviso" + "subjetivo".
- Respeite as REGRAS DA CASA. Não reescreva a voz do autor; aponte o que falta.
- `nota` (0-10): coesão geral (entendimento + sentimento). `resumo`: estrutura identificada,
  emoção-alvo, e o diagnóstico de coesão em 1-2 frases."""


SYSTEM_SEM_PDF = montar_system("")


class AgenteCoerencia(AgenteBase):

    CAMADA = "coerencia"

    def __init__(self, conteudo_pdf: str = ""):
        super().__init__()
        if conteudo_pdf:
            base = f"## Playbook de Storytelling VML (íntegra):\n\n{conteudo_pdf}"
            self.system_prompt = montar_system(base)
        else:
            self.system_prompt = SYSTEM_SEM_PDF

    async def analisar(self, roteiro: str) -> dict:
        user_prompt = f"""Audite a coerência (entendimento E sentimento) deste roteiro:

{self._formatar_roteiro(roteiro)}

Faça o inventário de entidades/premissas e verifique introdução antes do uso, contexto,
saltos e setups sem payoff (entendimento). Varra também os pares de frases consecutivas
aplicando a regra COESÃO_ENTRE_FRASES (oposição de carga sem conectivo adversativo; não
sinalize quando a segunda frase apenas soma/reforça a primeira). Depois, dada a estrutura
CODEX, verifique se os beats exigidos para a emoção disparar estão presentes e na ordem
(sentimento). Marque cada achado com [Entendimento] ou [Sentimento] no campo 'porque'."""
        resultado = await self._rodar(self.system_prompt, user_prompt)
        # [Sentimento] nunca bloqueia (fortalece a emoção, não elimina). Só [Entendimento].
        for a in resultado.get("achados", []):
            if a.get("porque", "").lstrip().lower().startswith("[sentimento]") and a.get("severidade") == "erro":
                a["severidade"] = "aviso"
        return resultado
