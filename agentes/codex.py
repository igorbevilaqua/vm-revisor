"""
CODEX Narrativas VML — FONTE ÚNICA para todos os agentes.

Derivado de conhecimento/storytelling.md (Playbook Storytelling, a fonte da verdade):
14 estruturas VALIDADAS (com exemplos confirmados no dataset) + 5 SUGERIDAS
(identificadas por análise de padrões), organizadas em 6 macrogrupos.

Não duplique esta lista em prompts de agentes — importe daqui. Quando o playbook
mudar, atualizar APENAS este arquivo realinha todos os agentes.
"""

# Bloco pronto para injeção em system prompts
CODEX_BLOCO = """## CODEX Narrativas VML — 6 macrogrupos (✅ validada · 🔶 sugerida)
GRUPO A · Arquétipos de Herói: Jornada do Herói ✅ | Herói Improvável ✅ | Herói Esquecido ✅
GRUPO B · Batalha e Poder: Davi e Golias ✅ | Conflito Imprevisível ✅ | Queda do Gigante 🔶
GRUPO C · Revelação e Segredo: O Iconoclasta ✅ | Estratégia Oculta ✅ | Investigação & Escândalo ✅
GRUPO D · Alarme e Impacto: Urgência & Alerta ✅ | Evento Global ✅ | Efeito Dominó 🔶
GRUPO E · Insight e Contradição: Paradoxo Contraintuitivo ✅ | Inovação & Sacada Genial ✅ | Narrativa Filosófica ✅
GRUPO F · Ruptura e Consequência Pessoal: Erro Fatal ✅ | Dois Mundos 🔶 | O Profeta Ignorado 🔶 | Transformação de Identidade 🔶
(14 validadas + 5 sugeridas. Prefira as validadas; as sugeridas valem quando o material pede.)"""

# Nomes canônicos (para validação do contexto e matching no ledger)
CODEX_NOMES = [
    "Jornada do Herói", "Herói Improvável", "Herói Esquecido",
    "Davi e Golias", "Conflito Imprevisível", "Queda do Gigante",
    "O Iconoclasta", "Estratégia Oculta", "Investigação & Escândalo",
    "Urgência & Alerta", "Evento Global", "Efeito Dominó",
    "Paradoxo Contraintuitivo", "Inovação & Sacada Genial", "Narrativa Filosófica",
    "Erro Fatal", "Dois Mundos", "O Profeta Ignorado", "Transformação de Identidade",
]
