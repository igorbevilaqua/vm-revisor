"""
Agente — Checklist
Verifica se o roteiro atende os critérios do checklist da Viral Media Labs.
Cada critério não atendido vira um achado estruturado.

Contagens que são eliminadores objetivos (nº de palavras 150–430, headline ≤9 palavras)
são calculadas EM CÓDIGO e injetadas — a LLM conta mal, então não pedimos que ela conte.
"""

import re

from agentes import AgenteBase


def _e_meta(l: str) -> bool:  # linhas que não são texto falado (não contam no corpo)
    return bool(re.match(
        r"^(fontes?|sources?|\[?\s*fonte|http|cliente|canal|criador|criadora|"
        r"apresentador|apresentadora|locutor|locutora|perfil|voz|talento|"
        r"título|titulo|tema)\s*[:\-–—]",
        l, re.IGNORECASE,
    ))


def bloco_metricas(texto: str) -> str:
    """Contagens determinísticas para os eliminadores de tamanho do checklist.
    A LLM conta mal — então damos os números prontos."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    headline_txt, headline_wc = None, None
    corpo = []
    for l in linhas:
        mh = re.match(r"^headline\s*[:\-–—]\s*(.+)$", l, re.IGNORECASE)
        if mh:  # a headline é separada e NÃO conta no corpo; conta sem o marcador
            headline_txt = mh.group(1).strip()
            headline_wc = len(headline_txt.split())
            continue
        if _e_meta(l):
            continue
        corpo.append(l)

    total = sum(len(l.split()) for l in corpo)
    out = [
        "[ANÁLISE AUTOMÁTICA — contagens EXATAS, use estes números; não conte você mesmo]",
        f"- Corpo (texto falado): {total} palavras. Regra: 150–430 (fora disso elimina).",
    ]
    if headline_txt is not None:
        status = "OK" if headline_wc <= 9 else "EXCEDE o máximo de 9"
        out.append(f'- Headline declarada: "{headline_txt}" — {headline_wc} palavras '
                   f'(regra ≤9: {status}). NÃO conte o marcador "HEADLINE:".')
    else:
        cand = "\n".join(f'    L{i} ({len(l.split())} palavras): "{l[:70]}"'
                         for i, l in enumerate(corpo[:2], 1))
        out.append("- Nenhuma linha 'HEADLINE:' fornecida. Candidatas a headline/título:\n" + cand)
    return "\n".join(out)


CRITERIOS_PADRAO = """Como o PDF do checklist não foi fornecido, use os critérios padrão
para Reels de conteúdo educativo/de negócios:
1. Hook forte nos primeiros 3 segundos
2. Promessa clara do que o espectador vai ganhar
3. Desenvolvimento lógico e fluido
4. Linguagem clara, sem jargão desnecessário
5. CTA ao final
6. Tamanho adequado (30-90 s de vídeo)
7. Dados/exemplos sustentando os pontos
8. Personagem/história identificável (quando aplicável)
9. Ritmo e variação de cadência
10. Encerramento memorável"""


def montar_system(base_conhecimento: str) -> str:
    return f"""Você é o Agente de Checklist da Viral Media Labs (VML).

Sua função é verificar se o roteiro atende TODOS os critérios do checklist oficial da VML.

{base_conhecimento}

## Contagens
Use a ANÁLISE AUTOMÁTICA fornecida no prompt (contagens EXATAS de palavras) para os
critérios de tamanho (corpo 150–430 palavras; Headline ≤9 palavras). NÃO conte manualmente.

## Regra da casa — FONTES (sobrepõe o "eliminação automática" do checklist)
Dado específico SEM fonte indicada no documento → reporte como **`severidade: "aviso"`**
(natureza "objetivo"), NUNCA como "erro". Falta de fonte é aviso de alta prioridade, NÃO
reprova sozinha. Só é "erro" se o dado for comprovadamente FALSO — e isso é o Fact-Check
quem reporta, não o checklist.

## Como reportar (achados estruturados)
- Percorra cada critério do checklist. Para CADA critério NÃO atendido (ou parcial),
  registre um achado:
    - `trecho_original`: a citação literal do roteiro que evidencia a falha (vazio se for
      uma AUSÊNCIA, ex.: "não há CTA").
    - `correcao`: o que precisa entrar/mudar para o critério passar (concreto, aplicável).
    - `porque`: qual critério do checklist está em jogo.
    - `severidade`: "erro" se o critério é obrigatório e está violado; "aviso" se parcial.
    - `natureza`: "objetivo" se o critério é uma regra clara da VML; "subjetivo" se é juízo de qualidade.
- NÃO crie critérios que não estejam no checklist. Critério atendido não vira achado.
- `nota` (0-10): aderência geral ao checklist. `resumo`: X de Y critérios atendidos."""


SYSTEM_SEM_PDF = montar_system(CRITERIOS_PADRAO)


class AgenteChecklist(AgenteBase):

    CAMADA = "checklist"
    MODELO = "claude-haiku-4-5"  # casar critérios + contagens já vêm prontas — Haiku dá conta

    def __init__(self, conteudo_pdf: str = ""):
        super().__init__()
        if conteudo_pdf:
            base = f"## Checklist oficial da VML:\n\n{conteudo_pdf}"
            self.system_prompt = montar_system(base)
        else:
            self.system_prompt = SYSTEM_SEM_PDF

    async def analisar(self, roteiro: str) -> dict:
        user_prompt = f"""Confira este roteiro contra o checklist da VML:

{self._formatar_roteiro(roteiro)}

{bloco_metricas(roteiro)}

Registre um achado para cada critério não atendido, com o trecho (ou ausência) e a correção."""
        return await self._rodar(self.system_prompt, user_prompt)
