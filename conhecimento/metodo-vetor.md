# Base de Conhecimento — Revisão de Roteiros (Extração das REVs 1–4)

> Documento de treinamento para IA revisora de roteiros virais.
> Fonte: 4 revisões reais do revisor humano (Building Vinci V2, Snail Mail, Case Liquidz, Importância da Repetição).
> Objetivo: capturar a metodologia, os critérios, o vocabulário e os padrões de julgamento do revisor para que a IA replique o mesmo nível de análise.

---

## 1. ANATOMIA DE UMA REVISÃO COMPLETA

Toda revisão segue a mesma estrutura, nesta ordem. A IA revisora deve produzir as mesmas seções:

1. **Decupação do Roteiro por Vetores Narrativos** — o texto original é segmentado em blocos, e cada bloco recebe a etiqueta do vetor narrativo dominante (Contraintuitivo, Envolvente, Explicativo, Informativo, Analítico, Sensorial, Sensível, Empático).
2. **Premissa Central do Roteiro** — destilação do roteiro inteiro em UMA frase que captura protagonista + conflito + transformação + resultado. É a unidade primária de avaliação.
3. **Crítica/Validação da Premissa** — se a premissa é fraca, o revisor propõe uma **Sugestão de Nova Premissa** antes de qualquer edição de linha. Mudanças de premissa norteiam todas as mudanças seguintes.
4. **Anotações linha a linha** — mistura de elogios específicos, críticas pontuais e microedições. Sempre apontando o trecho exato.
5. **Anotações Gerais** — diagnóstico macro do roteiro (propósito, tom, equilíbrio emocional).
6. **"O que eu faria…"** — reescrita completa do roteiro pelo revisor, demonstrando as sugestões aplicadas. É a seção mais valiosa: mostra a solução, não só o problema.
7. **Graficonte / Diagrama de Trajetória Narrativa (DTN)** — plotagem da sequência de vetores ao longo do roteiro, no eixo "fazer sentir ↔ fazer sentido".

---

## 2. O SISTEMA DE VETORES NARRATIVOS

### 2.1 Os 8 vetores e suas cargas

O eixo central é **"fazer sentir" vs. "fazer sentido"**. Cada vetor carrega um valor que indica sua posição nesse espectro (escala de −2 a +2):

| Vetor | Carga | Polo |
|---|---|---|
| Envolvente | +2 | fazer sentido (engajamento racional/narrativo) |
| Analítico | +2 | fazer sentido |
| Informativo | +1 | fazer sentido |
| Explicativo | 0 | neutro |
| Contraintuitivo | 0 | neutro (quebra de padrão) |
| Empático | −1 | fazer sentir |
| Sensível | −2 | fazer sentir |
| Sensorial | −2 | fazer sentir |

### 2.2 Como o revisor usa os vetores

- A decupação revela **desequilíbrios**: no Building Vinci V2, o roteiro original era quase todo Envolvente/Explicativo/Informativo (polo "sentido") com zero Empático — daí o diagnóstico "onde o humano entra na história?".
- A correção proposta foi **adicionar o vetor Empático à escrita** ("em busca de dar mais emoção ao vídeo, adicionando o vetor narrativo empático à escrita").
- O DTN serve para visualizar a **trajetória emocional**: um bom roteiro alterna entre os polos; um roteiro plano fica preso em um só lado.
- **Insight de treinamento:** ao revisar, a IA deve (a) classificar cada bloco, (b) verificar se há alternância entre sentir/sentido, (c) sinalizar quando um polo está ausente.

---

## 3. PRINCÍPIOS-MESTRES DO REVISOR (extraídos das 4 revisões)

### P1 — A história só importa se conversar com a história do público
> "Ninguém quer saber da nossa história, a não ser que a minha e a sua história conversem entre si." (REV 1)

A premissa deve ser **universalizável**: "percebe que qualquer um poderia ser essa empreendedora? Afinal, todo empreender começa com uma convicção." Roteiros institucionais autocentrados ("dinheiro e time, dinheiro e time…") não geram alcance.

### P2 — Dinheiro e resultado são consequência, não causa
> "Faltou um propósito melhor ao texto, como uma motivação pessoal, ou algo mais relevante que dinheiro e time, visto que isso deveria ser consequência e não causa. Se for só pra ser um vídeo institucional, tá ok, mas se o intuito for alcance, existem detalhes que podem agregar ao texto." (REV 1)

A IA deve perguntar: **o protagonista tem motivação humana além do resultado financeiro?**

### P3 — Premissa primeiro, edição depois
Quando a premissa é fraca, o revisor a reescreve ANTES de tocar nas linhas, e declara que a nova premissa "vai nortear algumas mudanças que irei sugerir mais pra frente". Exemplo de transformação (REV 1):

- **Original:** "Uma marqueteira sem dinheiro e sem estrutura aposta tudo numa categoria que não existia no Brasil… e transforma uma sala de casa em 36 milhões de reais."
- **Nova:** "Uma marketeira sem dinheiro e sem estrutura, mas que **acredita ter a melhor ideia do mercado**, passa um ano tentando fazer com que outras pessoas acreditem em **sua certeza particular**, e acaba descobrindo que **certeza tem um preço alto e um espaço enorme**."

A nova premissa desloca o foco do RESULTADO (36M) para a CONVICÇÃO (universal), e gera consequências estruturais: "Se ela passou tentando, é porque não foi um caminho fácil nem linear, logo, devemos adicionar desafios na jornada" + "vamos inserir o gatilho no início, e dois rehooks, no meio e fim do texto".

### P4 — Hook contraintuitivo performa melhor (calibrado por apresentador)
> "Excelente, os inícios contraintuitivos performam melhor com a Tay." (REV 2)

O revisor mantém **memória de calibração por cliente/apresentador**. A IA deve aplicar preferências específicas do perfil (equivalente ao `preferencias.md`).

### P5 — Rehook tem posição e função
- Rehook deve **completar/explicar o gancho**, não repetir informação: "Rehook perfeito, o gancho termina de ser explicado aqui." (REV 2)
- **Erro crítico:** rehook imediatamente após o hook sem informação nova: "O rehook foi feito logo após o hook. Uma informação que não acrescentou em nada com o que havia sido dito imediatamente antes. Pra mim esse é o único ponto crítico do texto." (REV 3)
- Estrutura recomendada quando a jornada tem desafios: **gatilho no início + rehook no meio + rehook no fim** (REV 1).

### P6 — Economia de texto (corte sem dó)
- "Dá pra tirar essa parte sem prejudicar o texto." (REV 2 — cortou "caneta e envelope")
- "Não acredito que 'sobrevivência' agregue em algum sentido à frase, pode retirar de boa." (REV 4)
- "Evitar dar essas pausas que não agregam carga à narrativa." (REV 1 — sobre o "Eeeh…")
- Teste implícito: **se a frase/palavra sair e o texto não perder nada, ela deve sair.**

### P7 — Nunca anuncie, simplesmente faça
> "Evite falar que vai iniciar, simplesmente inicie." (REV 1 — sobre "Mas vamos ao início:")

Metacomentários de transição são gordura narrativa.

### P8 — Perguntas retóricas precisam se justificar
> "Eu não acho que é retórico, mas se é, por que foi dito? Essas duas pausas além de desnecessárias ainda ficaram muito próximas." (REV 1 — sobre "Mas isso você já sabe" / "Decidido então?")

Regra adicional: **pausas/quebras não podem ficar próximas demais umas das outras.**

### P9 — Mentira performática (calibragem dramática de números)
> "Sugiro fazer uma mentira performática, diminuindo a meta de 20M pra 10M, pois assim o resultado final parece mais desproporcional." (REV 1)

O contraste expectativa→resultado é um recurso dramático ajustável. Quanto maior a desproporção, maior o impacto. (Aplicado na reescrita: "Esperava faturar alto, 10M no primeiro ano. Mas não foi isso que aconteceu… felizmente. Acabamos fazendo 36M.")

### P10 — Repetição intencional cria sensação
> "Acrescentei esse 'noite e dia' a mais pra dar a ideia de continuidade e exaustão." (REV 1 — "dia e noite, noite e dia…")

Repetição espelhada = recurso sensorial de tempo/esforço.

### P11 — Anáfora e paralelismo sintático enriquecem
> "Adicionei o 'ser' antes de imperfeito e humano pra enriquecer o texto através da anáfora e do paralelismo sintático, deixando essa parte um pouco mais poética." (REV 2)

Antes: "Ser tangível, imperfeito e humano…" → Depois: "Ser tangível, **ser** imperfeito… **ser** humano…"

### P12 — Pesquisa/dado é o pilar da tese e tem posição certa
- "Praticamente toda a tese defendida pelo roteiro gira em torno dessa pesquisa, situada de forma clara e objetiva." (REV 2 — estudo USPS)
- "Pesquisa muito bem posicionada pra sustentar o gancho." (REV 4 — Chartmetric)
- Padrão: **hook → dado que valida o hook → explicação científica/causal → exemplos de marcas → ponte para o negócio do público → CTA.**

### P13 — Simplificação de produto complexo é virtude
> "Bom demais, resumiu um produto complexo em 'água de coco em pó'. Excelente." (REV 3)

E sobre a explicação do modelo DTC: "Modo shark tank, muito bem explicado esse modelo!"

### P14 — Pergunte para quem o roteiro fala
> "Essa parte sublinhada ficou muito boa, mas a parte inicial… apesar de contraintuitivo, pode melhorar um pouco. **Queremos falar com corredores ou com bebedores de água?**" (REV 3)

O hook define o público que para o scroll. Hook errado = audiência errada, mesmo que seja "bom".

### P15 — Mostre o símbolo, não o nome (prova sensorial)
> "O exemplo ficou ótimo, mas dá pra explorar melhor esse lado sensorial… ao invés de falar o nome da empresa, fala o símbolo e deixa que o próprio público interprete, isso vai ajudar ainda mais a comprovar a tese." (REV 4)

Aplicado na reescrita: "na playlist 'filme' o primeiro som da sua lista, deixa eu adivinhar… **TuDuuum**." — o roteiro sobre familiaridade PROVA a familiaridade na própria experiência do espectador. **Meta-insight: o roteiro deve demonstrar a tese, não só enunciá-la.**

### P16 — A premissa define o eixo dual do roteiro
> "O roteiro deve focar nessa dualidade, **original vs inesquecível**, tudo deve girar em torno disso." (REV 4)

Quando a premissa contém uma oposição, toda a estrutura deve orbitar essa oposição.

### P17 — Hook simples demais transfere carga para o audiovisual
> "Eu gostei da ideia, mas achei meio simples demais, não sei se vai cativar o suficiente, **o audiovisual teria que carregar aqui**." (REV 4)

A IA deve sinalizar quando o texto depende da execução visual para funcionar — isso é um risco, não necessariamente um erro.

### P18 — Metáfora estendida como espinha dorsal
Nas reescritas, o revisor escolhe UMA metáfora e a sustenta do hook ao CTA:

- **REV 1 (navio/mar):** abre com Saint-Exupéry ("Pra construir um navio, você não reúne pessoas pra cortar madeira; você faz elas desejarem o mar"), e mantém: "marujos", "fazer a maré virar", "grande remada… pequena marola", e fecha o CTA dentro da metáfora: "chama a gente pra construir esse navio com você".
- **REV 3 (guerra):** "frutinha injetada na veia de soldados durante guerras" → "guerrear com esses vilões artificiais" → "a guerra vem sendo vencida".
- **REV 4 (playlist/música):** abre com contraste musical (40 anos vs 40 dias) → "você não entra na 'playlist' de ninguém" → exemplos como playlists → CTA.

**Regra: a metáfora deve aparecer no hook, costurar o desenvolvimento e fechar no CTA.**

### P19 — Callback / payoff físico
Reescrita REV 3: "Pois é, a água de coco sempre esteve ali. *(segurar água de coco com uma mão)* Mas agora, ela tá aqui também. *(levantar a outra mão com a Liquidz)*"

- O revisor insere **rubricas de gravação** (direções físicas) quando o texto pede materialização visual.
- O fechamento emocional vem de uma frase-síntese humana: "Porque um dia alguém sentiu aquilo que todo mundo fingia não ver."

### P20 — O CTA deve herdar a emoção do roteiro
CTA original (REV 1): "aplique-se no link da bio" (burocrático). CTA reescrito: "se você ainda escuta uma voz dentro de si dizendo que a maré não tá boa, isso é um sinal, chama a gente pra construir esse navio com você, em pouco tempo essa voz será silenciada pelo melhor time de marketing do brasil."

### P21 — Elogiar é parte da revisão (e com a mesma especificidade da crítica)
Exemplos de elogios pontuais e técnicos:
- "O 'por quê' e o 'como' ficou bem direto, sem enrolação, muito bom." (REV 1)
- "A pausa pra respiração ficou muito bem colocada." (REV 1)
- "Feed por papel tá ok já; a construção aqui também ficou muito boa." (REV 2)
- "Ficou muuuuuuuuuito bom!!!" (REV 2 — validação da premissa inteira)
- "Excelente ponte." (REV 4 — sobre a transição "E a mesma lógica vale pro seu negócio")
- "Premissa simples e objetiva, excelente. As pesquisas e os exemplos fizeram com que o texto não ficasse abstrato." (REV 4)

**Insight de treinamento:** a IA deve marcar o que funciona com a mesma precisão com que marca o que falha — isso calibra o roteirista e preserva os acertos nas próximas versões.

### P22 — Sinalize confusão sem resolver à força
> "Gostei da ideia, mas tá meio confuso aqui, não?" (REV 2)

O revisor pode apontar confusão como pergunta, devolvendo a decisão ao roteirista.

---

## 4. CHECKLIST OPERACIONAL PARA A IA REVISORA

### 4.1 Diagnóstico macro (antes das linhas)
- [ ] Extrair a **premissa central** em 1 frase (protagonista + conflito + virada + resultado).
- [ ] Testar universalidade: a história do protagonista conversa com a história do público? (P1)
- [ ] Há motivação humana além de dinheiro/resultado? (P2)
- [ ] Se a premissa contém dualidade, o roteiro inteiro orbita essa dualidade? (P16)
- [ ] Decupar por vetores narrativos e verificar equilíbrio sentir↔sentido; sinalizar polo ausente. (Seção 2)
- [ ] O roteiro demonstra a tese na experiência do espectador, ou só a enuncia? (P15)

### 4.2 Estrutura
- [ ] Hook: contraintuitivo? Forte o suficiente sem depender do audiovisual? (P4, P17)
- [ ] Hook fala com o público certo? (P14)
- [ ] Rehook: existe? Completa o hook com informação nova? Está bem distribuído (meio/fim)? (P5)
- [ ] Dado/pesquisa: existe, está logo após o hook, sustenta a tese? (P12)
- [ ] Ponte exemplo→negócio do público está clara? (P12, "excelente ponte")
- [ ] Metáfora estendida: aparece no hook, costura o meio e fecha no CTA? (P18)
- [ ] Callback/payoff no fechamento? Rubricas físicas quando necessário? (P19)
- [ ] CTA herda a emoção e a metáfora do roteiro? (P20)

### 4.3 Linha a linha
- [ ] Cortar tudo que sai sem perda (palavras, frases, pausas). (P6)
- [ ] Eliminar anúncios de transição ("vamos ao início"). (P7)
- [ ] Questionar perguntas retóricas; impedir pausas próximas demais. (P8)
- [ ] Avaliar oportunidades de mentira performática para ampliar desproporção dramática. (P9)
- [ ] Procurar pontos para repetição intencional (sensação de tempo/exaustão). (P10)
- [ ] Procurar pontos para anáfora/paralelismo sintático. (P11)
- [ ] Verificar se produtos/modelos complexos foram simplificados em imagem concreta. (P13)
- [ ] Elogiar acertos com especificidade técnica. (P21)
- [ ] Corrigir typos e gramática (ex.: "bbio" → "bio", "trabalhararem" → "trabalharem", "mais*?").

### 4.4 Entregável
- [ ] Anotações gerais com diagnóstico de propósito (alcance vs institucional).
- [ ] Reescrita completa "O que eu faria…" aplicando todas as sugestões.

---

## 5. EXEMPLOS COMPLETOS ANTES → DEPOIS (pares de treinamento)

### 5.1 Hook — REV 3 (Liquidz)
**Antes:** "Esse cara bebia 4 litros de água por dia e continuava desidratado. A resposta pra esse problema virou uma empresa de milhões."
**Diagnóstico:** contraintuitivo, mas fala com "bebedores de água", não com o público-alvo; rehook subsequente não acrescentava nada.
**Depois:** "Tem uma frutinha que já foi injetada na veia de soldados durante guerras, usada pra tratar cólera em surtos, e até mesmo prescrita contra pedra no rim em casos de emergência. No Brasil, essa mesma fruta passou décadas sendo vendida com canudinho na praia, até que um cara resolveu transformar isso, nisso, e tá fazendo milhões por causa disso." *(gravar com a Liquidz e com uma água de coco)*
**Técnicas:** curiosity gap escalonado (3 fatos surpreendentes), concretude visual, rubrica de gravação, mistério do produto preservado.

### 5.2 Hook — REV 4 (Repetição)
**Antes:** "Já reparou como você sempre ouve as mesmas músicas?"
**Diagnóstico:** "meio simples demais… o audiovisual teria que carregar aqui."
**Depois:** "Nada do que foi será do jeito que já foi um dia; essa música é ouvida sem parar há mais de 40 anos. Enquanto isso, em menos de 40 dias, ninguém aguentava mais ouvir o funk que foi hit desse carnaval."
**Técnicas:** contraste concreto (40 anos vs 40 dias), referência cultural reconhecível, espelhamento numérico, depois disclaimer ("não é crítica a nenhum gênero") e enunciado da tese: "só ser original não basta; é necessário ser inesquecível."

### 5.3 Abertura — REV 1 (Building Vinci)
**Antes:** "Eu convenci esses 2 caras a trabalharem de graça comigo em um negócio que nem existia no Brasil. Eeeh… minhas expectativas eram altas: Mesmo sem investir nenhum centavo, eu esperava faturar 20M no meu primeiro ano. Mas não faturei. Eu acabei fazendo 36M…"
**Diagnóstico:** revela o resultado cedo demais; sem camada empática; pausas vazias.
**Depois:** "Pra construir um navio, você não reúne pessoas pra cortar madeira; você faz elas desejarem o mar. E esses caras aqui foram os dois marujos que toparam trabalhar de graça comigo, num navio que nunca havia sido feito, e num mar que nunca havia sido tão desejado."
**Técnicas:** citação/aforismo como gatilho, metáfora estendida, suspensão do resultado (36M migra para o FIM como payoff), motivo recorrente "certeza particular".

### 5.4 Fechamento emocional — REV 4
**Antes:** "A Red Bull reforça o mesmo estilo de vida aventureiro… A Netflix criou um som de dois segundos que o mundo inteiro reconhece."
**Depois:** "na playlist 'aventura' a primeira marca da sua lista deve ser um energético. Já na playlist 'filme' o primeiro som da sua lista, deixa eu adivinhar… TuDuuum. Pois é, tanto a Red Bull quanto a Netflix constroem o mesmo ativo: um lugar afetivo na mente do consumidor."
**Técnicas:** o público completa o padrão sozinho (prova vivida da tese), metáfora da playlist mantida, revelação dos nomes só APÓS o reconhecimento.

### 5.5 Microedições exemplares
| Antes | Depois | Técnica |
|---|---|---|
| "dia e noite…" | "dia e noite, noite e dia…" | repetição espelhada → exaustão (P10) |
| "Ser tangível, imperfeito e humano" | "Ser tangível, ser imperfeito… ser humano" | anáfora/paralelismo (P11) |
| "comunicação lenta virou o ato mais radical" | "numa era onde a saturação digital prevalece, demorar virou luxo" | reframe aspiracional |
| "nosso cérebro foi projetado para identificar padrões que facilitam a sobrevivência e ajudam a economizar energia" | "nosso cérebro é preguiçoso, ele foi projetado para identificar padrões que ajudem a economizar nossa energia" | corte de palavra inútil + imagem concreta ("preguiçoso") |
| "esperava faturar 20M" | "esperava faturar alto, 10M" | mentira performática → desproporção (P9) |
| "E sem familiaridade, não tem confiança e sem confiança, não tem venda." | "E sem familiaridade, você não entra na 'playlist' de ninguém." | manter a metáfora-mestre (P18) |
| "decidiu criar um pozinho" | "decidiu guerrear com esses vilões artificiais, desenvolvendo um pozinho" | personificação do conflito (metáfora de guerra) |
| "E os números provam que funcionou" | "E os números provam que a guerra vem sendo vencida" | coerência metafórica (P18) |

---

## 6. TOM E VOZ DO REVISOR (para a IA imitar)

- Direto, coloquial, bem-humorado, sem formalismo ("pode retirar de boa", "bom demais", "tá meio confuso aqui, não?").
- Crítica sempre **localizada e justificada** — nunca "ficou ruim", sempre "X não funciona PORQUE Y".
- Quando muda algo, **explica a técnica usada** (anáfora, paralelismo, mentira performática, vetor empático) — a revisão também é aula.
- Usa pergunta socrática para devolver decisões ("Queremos falar com corredores ou com bebedores de água?").
- Reconhece o que está fora do escopo do texto: "Sobre o audiovisual, nada a acrescentar, foi feito um trabalho incrível."
- Diferencia objetivo do vídeo: **alcance ≠ institucional** — o rigor da revisão muda conforme o objetivo.
- Hipérbole afetiva nos elogios fortes ("Ficou muuuuuuuuuito bom!!!") e sarcasmo leve nas críticas repetitivas ("Dinheiro e time, Dinheiro e time, Dinheiro e time…").

---

## 7. PADRÕES ESTRUTURAIS RECORRENTES (templates implícitos)

### Template A — Roteiro de tendência/tese (Snail Mail, Repetição)
1. Hook contraintuitivo (quebra de expectativa cultural)
2. Rehook que termina de explicar o gancho
3. Dado/pesquisa de autoridade que valida
4. Explicação causal ("e a ciência explica…", "é que a mente humana…")
5. Exemplos de marcas (3–4, em gradação)
6. Síntese da tese em frase forte
7. Ponte: "a mesma lógica vale pro seu negócio"
8. Posicionamento da consultoria + CTA

### Template B — Roteiro de case/jornada (Vinci, Liquidz)
1. Hook com curiosity gap (resultado oculto ou fato improvável)
2. Origem humilde + convicção do protagonista
3. Obstáculo/dor ignorada pelo mercado
4. Decisão/ação corajosa
5. Mecanismo (lançamento, DTC) explicado de forma simples
6. Prova social numérica
7. Payoff emocional/callback (revelação do resultado guardado, gesto físico)
8. Moral universal ("é assim que marcas que crescem de verdade são construídas")
9. CTA dentro da metáfora

---

## 8. ANTIPADRÕES (erros que a IA deve detectar imediatamente)

1. **Rehook redundante** colado no hook sem informação nova. (REV 3 — "único ponto crítico")
2. **Resultado revelado cedo demais**, matando o suspense do payoff. (REV 1)
3. **Roteiro autocentrado** sem ponto de contato com a vida do espectador. (REV 1)
4. **Ausência total do polo "fazer sentir"** (zero Empático/Sensível/Sensorial). (REV 1)
5. **Anúncio de transições** ("vamos ao início", "deixa eu te contar"). (REV 1)
6. **Pausas/perguntas retóricas vazias e próximas demais.** (REV 1)
7. **Palavras que não agregam** ("sobrevivência", "caneta e envelope"). (REV 2, REV 4)
8. **Hook que mira o público errado.** (REV 3)
9. **Hook fraco que terceiriza o trabalho para o audiovisual.** (REV 4)
10. **CTA burocrático** desconectado da emoção construída. (REV 1)
11. **Nomear a marca quando o símbolo provaria mais** (perda de oportunidade sensorial). (REV 4)
12. **Quebra de coerência metafórica** — misturar metáforas ou abandonar a metáfora no meio.
13. **Typos e descuidos** ("bbio", "trabalhararem", concordâncias).

---

## 9. GLOSSÁRIO DO MÉTODO

- **Decupação por Vetores Narrativos:** segmentação do roteiro com etiquetagem do vetor dominante por bloco.
- **Graficonte / DTN (Diagrama de Trajetória Narrativa):** gráfico da sequência de vetores no eixo fazer sentir (−2) ↔ fazer sentido (+2).
- **Premissa Central:** frase única que resume protagonista + conflito + transformação; unidade primária de avaliação e reescrita.
- **Hook / Gancho:** primeira(s) linha(s) que param o scroll; preferência por contraintuitivo.
- **Rehook:** reativação da curiosidade no meio/fim; deve completar o gancho com informação nova.
- **Gatilho:** elemento de abertura que instala a tensão da premissa.
- **Mentira performática:** ajuste dramático de números/fatos para ampliar desproporção narrativa.
- **Ponte:** transição do caso/tese para o negócio do espectador ("a mesma lógica vale pro seu negócio").
- **Payoff / Callback:** recompensa final que retoma elemento plantado no início.
- **Metáfora estendida:** imagem única sustentada do hook ao CTA.
- **Certeza particular:** motivo temático (REV 1) — a convicção do empreendedor antes da validação externa.
- **"O que eu faria…":** reescrita demonstrativa completa do revisor.

---

*Documento gerado a partir das revisões REV 1 (Building Vinci V2), REV 2 (Snail Mail), REV 3 (Case Liquidz) e REV 4 (Importância da Repetição — Educacional).*
