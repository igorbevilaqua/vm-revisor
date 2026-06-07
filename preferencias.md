# Preferências do Editor — Viral Media Labs

Estas são as **regras da casa**. Todo agente as recebe e tem que respeitá-las —
elas têm prioridade sobre qualquer recomendação genérica da IA. É aqui que o
revisor aprende o *seu* gosto, para você discordar menos das sugestões.

Edite à vontade. Seja específico: a IA segue o que está escrito aqui ao pé da letra.

> As seções **[1]–[9]** são editadas por você (humano). A seção **[10] APRENDIDO COM
> REJEIÇÕES** é a ÚNICA que o `feedback.py` escreve automaticamente — as demais são
> somente-leitura para o código.

---

## [1] ESTRUTURA DO ROTEIRO  ✅ regra ativa
Os roteiros hoje seguem esta estrutura. Os agentes devem identificar cada parte e avaliá-la
no seu papel — não cobrar de uma etapa o que é função de outra:
1. **Título com headline** — texto de tela (≤9 palavras, MGC).
2. **Hook** — o PRIMEIRO parágrafo. Cria a lacuna de curiosidade (ver seção [5] HOOK).
3. **Desenvolvimento da história** — o corpo; aqui a PRECISÃO factual é exigida.
4. **Lição** (opcional) — em algumas estruturas de storytelling, vem ANTES do comando; passa
   percepção de valor (o espectador sente que ganhou algo) antes do pedido. Quando presente,
   é parte legítima — não tratar como enrolação.
5. **Comando** — o CTA ("CTA com Esteróides"), ao final, antes das fontes.
6. **Fontes** — metadado; não conta no nº de palavras nem é texto falado.

---

## [2] FONTES E FACTCHECK

### Fontes dos dados  ✅ regra ativa
- Dado específico SEM fonte indicada no documento é **AVISO de alta prioridade** — **NÃO
  reprova sozinho** o roteiro. (As fontes podem ser conferidas fora do documento.) Apesar de
  o checklist dizer "eliminação automática", aqui ela vale como aviso forte, não eliminador.
- Só vira **erro bloqueante** se o dado for verificavelmente FALSO/incorreto (fake news) — aí
  é o Fact-Check que reporta como erro objetivo.

### Hipérbole retórica vs. precisão factual  ✅ regra ativa
- **Hipérbole e exagero retórico são PERMITIDOS e desejáveis quando o objetivo é CHAMAR
  ATENÇÃO** — tipicamente na headline e no hook (ex.: "a empresa mais valiosa do mundo",
  "ele perdeu tudo", "ninguém viu isso chegando"). **Não trate isso como erro factual.**
- **PRECISÃO é obrigatória no momento de DAR CONTEXTO** — quando o roteiro explica, sustenta
  ou desenvolve no corpo: dados, números, datas, percentuais, relações causais. Aí todo dado
  precisa estar correto e ter fonte; nada de fake news (regra do checklist).
- **Para o Fact-Check:** só reporte como erro imprecisão que aparece em posição de
  CONTEXTO/explicação, ou afirmação verificavelmente falsa. Hipérbole de impacto em
  headline/hook não é erro — é técnica.
- **HOOK = lacuna de curiosidade, NÃO afirmação factual completa.** O gancho cria um gap de
  informação por meio de QUALQUER MGC do Playbook de Hooks — contraste é só um deles (funciona
  bem), mas também: ordem contra-intuitiva, urgência, desafio de crença, elemento controverso,
  superlativo, ultra especificidade, revelação secreta, viés de negatividade, "esse cara"
  (personagem), etc. A afirmação do gancho é resolvida/qualificada pelo CORPO do roteiro. Ex.:
  "o Brasil fez algo diferente" (= mandou médicos pra salvar) é gancho válido, não erro factual.
  Fact-Check e Coerência **não devem** tratar o hook literalmente como afirmação completa, nem
  cobrar a ressalva dentro do próprio gancho — desde que o CORPO não afirme algo comprovadamente
  falso.

---

## [3] REGISTRO FALADO  ✅ regra ativa

### Contrações coloquiais NÃO são erro
- O roteiro é para ser FALADO. Contrações coloquiais — "pra", "pro", "tá", "cê", "tô",
  "né", "da/do" em vez de "de a/de o" na fala — são naturais e desejáveis na locução.
  **Não trate como erro de ortografia/registro.** Trocar por "para a/para o" deixa robótico.
- Ortografia/gramática reporta apenas erro real de norma que atrapalha (crase, concordância,
  regência que muda sentido, typo) — nunca "informalize → formalize".

---

## [4] PROIBIÇÕES ABSOLUTAS

### ⛔ NÃO INVENTAR fato (anti-fake-news)  ✅ regra ativa — vale para TODOS os agentes
- Uma `correcao` **NUNCA** pode introduzir um fato novo (causa, número, data, nome, relação
  causal, estatística) que não esteja no roteiro original. Isso é fabricação — risco de fake news.
- Se um buraco de [Entendimento] exige um fato real para ser preenchido, a `correcao` deve ser
  um **pedido de verificação** ao autor — ex.: "Verificar e inserir a causa real de X (com fonte)"
  — e a `natureza` é "objetivo", `severidade` "aviso". Jamais escreva uma explicação plausível
  inventada como se fosse verdade.
- Prefira **suavizar ou cortar** uma afirmação não sustentada a inventar uma justificativa.
- Reescrita (clareza/hook/cta/storytelling): pode mudar a forma, nunca os fatos. Não acrescente
  dado que o autor não escreveu.

### Cheiro de IA — vícios a evitar  ✅ regra ativa
- **Travessão "—": remover SEMPRE.** Usar vírgula ou conectivo natural ("com", "e", "porque").
  Travessão decorativo é marca registrada de texto de IA.
- **Pergunta retórica formulaica** — "O resultado?" / "Resultado?" é vício de IA. Variar com formas
  vivas: "E adivinha o resultado?", "E o resultado, você não vai acreditar…", "Sabe o que aconteceu?".

### O que NUNCA fazer / sugerir  ✅ regra ativa
- **Não usar CAIXA-ALTA para marcar ênfase** numa reescrita/sugestão — manter capitalização
  normal. A ênfase fica por conta da locução e da pontuação, não de versalete.
- Não remover o conectivo "E" no início de frase só pra buscar "punch" — muitas vezes o "E"
  soa mais natural na fala. Fluência natural pode bater mais que a frase seca (caso a caso).
  (Escopo: vale **fora do hook**. No hook de contraste de dois lados, trocar "E" por "Mas" — ver [5].)

---

## [5] HOOK

### Preferências de hook  ✅ regra ativa
- **Superlativo e exclusividade são OURO no gancho** — "entre os 2% mais inteligentes do planeta",
  "a empresa mais valiosa do mundo", "o único convidado". Dão peso de importância e exclusividade.
  Ao reescrever um hook, **NUNCA jogar fora um superlativo/exclusividade forte que já estava lá** —
  preservar ou potencializar, jamais trocar por contraste genérico.
- Meta declarada do Igor: ficar muito bom de hook. O gancho usa qualquer MGC do Playbook de Hooks.
- Quando o gancho tem dois lados (ex.: "Einstein escolheu ele" × "você nunca ouviu falar dele"),
  usar **"Mas"** pra marcar o contraste — afia a lacuna de curiosidade. Contraste > aditivo ("E").
  (Escopo: vale **no hook de contraste**. Fora do hook, preservar o "E" de fluência — ver [4].)
- **Entidades magnéticas/controversas** (China, Elon Musk, grandes marcas) são ímã de atenção —
  nomear cedo pode POTENCIALIZAR mais do que manter o mistério ("uma potência…"). A atração pelo
  nome supera a curiosidade do "quem?". Avaliar caso a caso (mistério ainda vale quando o "quem?"
  é o gancho).
- **Reconhecibilidade > precisão técnica NO HOOK.** No gancho, escolher o nome MAIS reconhecível
  pelo público amplo, mesmo que menos preciso: "Estados Unidos, Rússia e China" bate mais que
  "NASA, Roscosmos e a Agência Espacial Chinesa". Início de vídeo precisa de elementos reconhecíveis
  pra gerar percepção de relevância. Na maioria das vezes, preferir nomes de **personalidades/
  entidades conhecidas** e, quando couber, **controversas/polarizadoras**. A ultraespecificidade
  (ex.: "uma cidade de 18 mil habitantes") pode somar, mas NÃO troque o nome reconhecível pelo
  técnico — some os dois.

### Números no gancho — caso a caso (NÃO é regra fixa)
- Precisão de número no hook é decisão de ritmo, não regra. Às vezes o valor exato ("10,5 bi") dá
  impacto; às vezes "mais de 10 bilhões" mantém ênfase e fluência de leitura. Julgar caso a caso;
  o valor exato pode ficar no contexto/corpo.

- (exemplo — placeholder, não é regra ativa) Não transformar afirmação em hook de pergunta sem
  necessidade.

---

## [6] CTA

### Preferências de CTA / Comando  ✅ regra ativa
- O CTA pode carregar uma **frase de valor/identidade** que conecta com a missão do roteiro
  (ex.: "os nomes que a história tentou apagar, mas que deveriam ser as verdadeiras inspirações
  brasileiras") — aprofunda o gatilho de propósito.
- **NÃO terminar o CTA com "agora"** — é muleta que enfraquece o fechamento.
- No **pico emocional** de um Herói Esquecido / raiva moral, vale um **"compartilhe esse vídeo"**
  ANTES do CTA de seguir — o compartilhamento é o ato de reparar a injustiça (mecanismo da estrutura).
- Cada roteiro/tema pede um CTA próprio — evitar o mesmo CTA genérico reusado em vários roteiros
  (ver backlog: CTA por cliente/por roteiro).

- (exemplo — placeholder, não é regra ativa) Não sugerir CTA genérico do tipo "segue, curte e
  compartilha".

---

## [7] STORYTELLING E SENTIMENTO
Esta camada cuida da EMOÇÃO: identificar a estrutura CODEX do roteiro e despertar o sentimento dela.
Um roteiro precisa DESPERTAR SENTIMENTO, não só fazer sentido (a parte de fazer sentido é a [8]).

### Foco da análise de SENTIMENTO  ✅ regra ativa
Ao revisar, SEMPRE: (1) identificar a estrutura CODEX do roteiro; (2) saber o mecanismo de emoção
dela; (3) caçar a LACUNA — o beat ausente que potencializaria essa emoção. É o maior ganho possível
(ex.: Herói Esquecido só dói de verdade se o apagamento/injustiça for sentido; Davi-Golias só dá
catarse se o Golias for quantificado).

### Setup e consequência — preservar a tensão  ✅ regra ativa
- Ao plantar um SETUP de tensão, não repetir o dado que aparece na CONSEQUÊNCIA. Ex.: não dizer
  "cinco minutos" no setup E na consequência — o setup cria a expectativa, a consequência entrega o
  número. (Deslize real numa reescrita do eclipse de Sobral.)

---

## [8] COERÊNCIA E COMPREENSÃO
Esta camada cuida do ENTENDIMENTO: clareza de referência, ponte para o que é novo, lógica causal —
que o espectador consiga ACOMPANHAR. (O despertar de emoção é a [7].)

### Ponte didática antes de termo técnico / info "do nada"  ✅ regra ativa
- Em **momentos de contexto inicial** — quando vai introduzir um termo técnico/menos familiar pro
  público médio (ex.: "siderúrgica") ou abrir um contexto que o espectador precisa pra acompanhar —
  use uma **ponte curta**: "pra você entender,", "só pra você ter ideia,", "caso você não saiba,".
  Abre um ciclo de curiosidade e baixa a barreira de compreensão.
- **Quando NÃO usar:** se o próprio texto já explica o elemento logo em seguida (fluxo natural de
  explicação), a ponte vira muleta. Ex.: "quem ajudou foi o Barão X, que era médico e padrinho dele"
  já se explica sozinho — não force a ponte.
- Apontar o personagem central com "**esse/essa** [pessoa]" (em vez de "teve um/uma") quando quiser
  criar expectativa de um indivíduo específico (MGC "Esse Cara" — ver [5]).

### Clareza de referência e concretude  ✅ regra ativa
- Deixar o referente explícito ("a tonelada **do carvão**", não só "a tonelada").
- Preferir o concreto/contável ("**uma** siderúrgica") ao abstrato ("**a** siderurgia").

---

## [9] ESTILO E VOZ

### Precisão humilde — não exagerar  ✅ regra ativa
- NÃO cravar absolutos ("de verdade", "sempre", "nunca") quando não é universal. Hedge com
  "muitas vezes", "boa parte". Ex.: "inovação **muitas vezes** nasce onde ninguém olha" é melhor
  que "inovação **de verdade** nasce onde ninguém olha".
- NÃO picotar frase demais buscando "punch". Preferir fluência natural de leitura — uma frase que
  flui pode bater mais que duas secas. (Vale pra reescritas que eu sugiro: não cortar em pedacinhos.)
- Nem toda palavra "a mais" é gordura: construções enfáticas ("foi tão longe que", "chegou ao ponto
  de") podem ser ÊNFASE intencional. Não cortar ênfase como se fosse enrolação.

### Regras de estilo (o que SEMPRE fazer)
- (exemplo — placeholder, não é regra ativa) Português do Brasil, registro coloquial mas correto.

### Tom e voz
- (exemplo — placeholder, não é regra ativa) Direto, sem floreio acadêmico. Sem clichê de LinkedIn.

---

## [10] APRENDIDO COM REJEIÇÕES

<!-- O sistema (feedback.py) acrescenta aqui as regras derivadas dos achados que você rejeitou,
     no formato: - [YYYY-MM-DD] texto da regra.
     Você pode editar ou apagar qualquer item. Esta é a ÚNICA seção escrita por código. -->
