# Backlog de Melhorias — Revisor VML

Ideias de melhoria a implementar depois. (Calibração de gosto vive no `preferencias.md`;
dúvidas de calibração no `preferencias_perguntas.md`; aqui ficam melhorias de produto/técnicas.)

## A fazer

### 1. Injetar a data de hoje no contexto dos agentes (fact-check sobretudo)
**Por quê:** o fact-check tratou "junho de 2026" como data futura/erro, porque o modelo
assume um "hoje" do seu limite de conhecimento. Resultado: falso-bloqueio numa data que é
o mês atual. (Caso real, Roteiro 1 do Cadu.)
**Como:** passar a data corrente no system/user prompt dos agentes sensíveis a tempo
(factcheck, coerência), ex.: "Hoje é DD/MM/AAAA — não trate datas até hoje como futuras."

### 2. Documento de preferências POR CLIENTE
**Por quê:** são vários clientes, cada um com voz, público, gatilhos de CTA e regras próprias.
O `preferencias.md` é da casa (geral); falta a camada do cliente específico.
**Como (esboço):** pasta `clientes/<nome>.md` com as regras daquele cliente. O sistema já
detecta o cliente (pelo título do Google Doc → `extrair_cliente_do_titulo`); ao revisar, carrega
`clientes/<cliente>.md` e injeta JUNTO do `preferencias.md` nos agentes. Regra do cliente tem
prioridade sobre a geral quando houver conflito. Cair no genérico se não existir o arquivo.

### 3. Playbook que evolui (sugerido pelo Igor)
Quando um agente (ex.: CTA) vê um padrão eficaz que NÃO está no playbook, sinalizar que pode
valer **adicionar ao playbook** — não só corrigir o roteiro. Hoje o CTA já registra essa sugestão;
falta um fluxo pra revisar essas sugestões e atualizar os `.md` de conhecimento periodicamente.

## Já feitas (referência)
Ver `preferencias_perguntas.md` (itens marcados ✅) e a memória do projeto:
markdown dos playbooks, prompt caching, skill humanizer, ortografia em Haiku, guardrail
anti-fabricação, fact-check com web (flag), skill /revisar-dinamico, regra de contrações faladas.
