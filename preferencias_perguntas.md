# Dúvidas de Calibração — questionário para preencher o preferencias.md

Lista viva de dúvidas que percebi rodando os agentes. Quando você quiser preencher o
`preferencias.md`, eu te faço estas perguntas (uma de cada vez, contextualizadas).
A ideia é capturar o SEU julgamento sem generalizar a ponto de deixar o roteiro genérico.

> Como ler: cada item tem a **tensão** (o trade-off real) e por que importa. Não há resposta
> "certa" — depende do contexto VML, que só você tem.

---

## 0. ⛔ PRIORIDADE — Agente não pode INVENTAR fato para tapar buraco (anti-fake-news)
**Problema observado (R1, correção #5):** o agente de Coerência flagrou um salto causal
("técnicas brasileiras eram diferentes das europeias — por quê?") e, em vez de só apontar o
buraco, **inventou uma causa plausível mas sem fonte** ("conhecimento que vinha do clima
brasileiro"). Isso é fabricação — risco direto de fake news. (No caso, a premissa original já
era frágil: cirurgia reconstrutiva facial foi pioneirada na Europa na 1ª Guerra.)

**Regra do Igor:** quando precisar completar uma informação real, NÃO pode inventar — tem
que conferir. Nunca incluir algo não verificado como se fosse fato.

**Possíveis soluções (resolver depois):**
1. **Guardrail em todos os agentes:** uma `correcao` NUNCA pode introduzir um fato novo
   (causa, número, data, nome, relação causal) que não esteja no original. Se o buraco exige
   um fato real, a `correcao` deve ser um PEDIDO ao autor ("verificar e inserir a causa real
   de X"), marcado como `natureza: objetivo` + `severidade: aviso` + nota "requer verificação"
   — jamais uma afirmação fabricada.
2. **Passe de verificação com web search:** dar tool de busca ao Fact-Check; toda `correcao`
   (ou afirmação do roteiro) que contenha um fato verificável passa por checagem com fonte
   antes de virar "obrigatória". Achado factual sem fonte confiável → rebaixa para "requer
   verificação manual", não entra como correção a aplicar.
3. **Separar tipos de gap de [Entendimento]:** "estrutural" (reordenar/suavizar/cortar — pode
   sugerir reescrita) vs "precisa de fato real" (só sinaliza, não preenche).
4. Preferir **suavizar/cortar** a afirmação não sustentada a inventar uma justificativa.

## 1. Fontes nos dados — bloqueia ou avisa?  ✅ RESOLVIDO
O Checklist Codex V1 é explícito: *"Um único dado sem fonte = eliminação automática."*
Então bloquear está CORRETO — é regra oficial VML. O "problema" no teste do Jensen foi
artefato: o .txt não trazia as fontes (que normalmente ficam no doc, e não contam no número
de palavras). Em roteiros reais, as fontes estão presentes.
**Observação:** vale o fact-check/checklist distinguir "dado sem fonte no documento" (eliminador)
de "dado provavelmente errado" — são coisas diferentes.

## 2. Hipérbole retórica vs. precisão factual  ✅ RESOLVIDO
Resposta do Igor: **hipérbole retórica é muito permitida quando o objetivo é chamar atenção
(headline/hook); precisão é necessária no momento de dar contexto.** Gravado em
`preferencias.md` (seção "Hipérbole retórica vs. precisão factual").

## 3. Loop aberto intencional vs. setup sem payoff
Coerência flagou "Jensen enxergou algo diferente" como setup sem payoff. Mas o playbook
de hooks INCENTIVA o loop aberto (curiosidade adiada).
**Tensão:** payoff imediato (clareza) vs. loop aberto deliberado (retenção).
**Dúvida:** como distinguir um gap real de uma curiosidade plantada de propósito? Existe um
limite de "quantas linhas" um loop pode ficar aberto?

## 3b. Quão agressiva deve ser a Coerência no SENTIMENTO?  ✅ RESOLVIDO
Decisão (após teste com a Drielle): coerência **[Sentimento]** = AVISO (otimização forte),
**nunca reprova** sozinha. Só **[Entendimento]** (lacuna que impede entender) bloqueia.

## MODELO DE BLOQUEIO (decidido nos testes) ✅
Só estas camadas podem REPROVAR (erro objetivo): **ortografia, fact-check, checklist,
coerência-[Entendimento]**. As demais (clareza, storytelling, viral, hook, cta,
coerência-[Sentimento]) são otimização e capam em "aviso" — enforced em código
(`AgenteBase.SEVERIDADE_MAX`), não só no prompt.

## 4. Tamanho de frase / quebra para locução
Clareza quebra frases longas em 3. Algumas frases longas são escolha de ritmo.
**Tensão:** legibilidade falada vs. cadência autoral.
**Dúvida:** existe um limite (nº de palavras/segundos) acima do qual quebrar é regra?

## 5. CTA — gatilhos e persona
O `cta.py` traz exemplos com "Igor Beviláqua" em 1ª pessoa.
**Dúvidas:** Os roteiros são sempre na voz do Igor? Quais dos 7 gatilhos a casa usa/evita?
Há um CTA padrão por tipo de conteúdo (negócios, geopolítica, etc.)?

## 6. Hook — tipos preferidos e proibidos
**Dúvidas:** há tipo de hook que você detesta (ex.: pergunta retórica)? Algum que é a cara
da VML? O hook deve sempre declarar o resultado/promessa, ou às vezes só intriga?

## 7. Limiares do veredicto
Hoje: REPROVADO se ≥3 erros objetivos OU nota geral < 5; APROVADO se 0 erros e nota ≥ 8.
**Dúvida:** esses cortes batem com o seu critério de "pronto para produzir"?

## 8. Volume de otimizações
Hoje a tabela mostra TODOS os achados. Você sinalizou que excesso atrapalha.
**Dúvida:** limitar as opcionais a um top-N (ex.: 5 por roteiro)? Ou manter tudo, já que
a tabela organiza?

## 9. Headline declarada  ✅ RESOLVIDO (parcialmente)
O Checklist Codex confirma: Headline declarada, separada, ≤9 palavras, com MGC, é
EXIGÊNCIA (eliminador). Logo, cobrar está certo. Resta só a dúvida operacional: como o
roteiro marca a headline no documento para o agente reconhecê-la (campo separado? prefixo
"HEADLINE:"?) — senão ela é confundida com o primeiro parágrafo.

## 12. (técnico) Checagens determinísticas que o checklist exige  ✅ IMPLEMENTADO
Contagem de palavras (150–430) e tamanho da headline (≤9) agora são calculadas em código
(`agentes/checklist.py: metricas_texto`) e injetadas no prompt. A LLM não conta mais.

## 13. MGC do hook — usar a lista oficial do checklist  ✅ IMPLEMENTADO
Os 15 MGCs oficiais + as aberturas genéricas PROIBIDAS foram embutidos no `agentes/hook.py`.

## 14. Nome do cliente no Comando  ✅ RESOLVIDO
Igor confirmou: **1 cliente por documento**, nome **geralmente no título do doc**.
Implementado: `google_docs.extrair_cliente_do_titulo` puxa o nome do título (limpando
ruído como "Roteiros", "VML", datas, "Semana N"), aplica a todos os roteiros do doc.
Prioridade do cliente: `--cliente` > título do doc > rótulo no texto. Se nada for achado,
o CTA usa [nome do cliente] (nunca assume Igor).

## 10. Tom, voz e palavras proibidas
**Dúvidas:** registro (coloquial/formal)? Palavras/clichês banidos? Jargão permitido?
Uso de gíria/regionalismo? Emojis no roteiro?

## 11. CODEX desatualizado (precisão, não gosto)
Os agentes (`viral`, `storytelling`, `coerencia`) citam uma lista de 15 estruturas que NÃO
bate com as 14 do playbook atual (nomes diferentes: "Geopolítica & Impacto Brasil" vs.
"Evento Global"; faltam "Queda do Gigante", "Dois Mundos", "O Profeta Ignorado",
"Transformação de Identidade", "Efeito Dominó").
**Dúvida (técnica):** alinhar os agentes ao playbook atual? (Recomendo que sim.)
