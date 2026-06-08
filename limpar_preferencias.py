#!/usr/bin/env python3
"""
Limpeza do preferencias.md — Viral Media Labs

Lê a seção de regras aprendidas [10] e usa a LLM para identificar regras
redundantes, contraditórias ou mal generalizadas. Exibe o resultado e
pede confirmação antes de sobrescrever.

Uso:
    python3 limpar_preferencias.py
    python3 limpar_preferencias.py --aplicar   # aplica sem pedir confirmação
"""

import sys
from pathlib import Path

from terminal import patch_stdout
patch_stdout()

import anthropic

RAIZ = Path(__file__).parent
PREFERENCIAS_PATH = RAIZ / "preferencias.md"
MARCADOR_SECAO = "## [10] APRENDIDO COM REJEIÇÕES"


def ler_preferencias() -> tuple[str, str]:
    """Retorna (texto_antes_da_secao_10, texto_da_secao_10)."""
    if not PREFERENCIAS_PATH.exists():
        print("❌ preferencias.md não encontrado.")
        sys.exit(1)
    texto = PREFERENCIAS_PATH.read_text(encoding="utf-8")
    if MARCADOR_SECAO not in texto:
        print("ℹ️  Seção [10] não encontrada — nada a limpar.")
        sys.exit(0)
    antes, secao = texto.split(MARCADOR_SECAO, 1)
    return antes, secao.strip()


def extrair_regras(secao: str) -> list[str]:
    """Extrai as linhas de regra da seção [10]."""
    regras = []
    for linha in secao.splitlines():
        s = linha.strip()
        if s.startswith("- ") and "placeholder" not in s:
            regras.append(s)
    return regras


def consolidar_regras(regras: list[str]) -> list[str]:
    """Usa a LLM para identificar e eliminar redundâncias e contradições."""
    if len(regras) < 3:
        print("ℹ️  Menos de 3 regras — nada a consolidar.")
        return regras

    lista = "\n".join(f"{i+1}. {r}" for i, r in enumerate(regras))
    system = (
        "Você é curador de um guia de estilo de revisão de roteiros de vídeo curto. "
        "Recebeu uma lista de regras aprendidas com rejeições do editor. Sua tarefa:\n"
        "1. Identificar regras REDUNDANTES (dizem a mesma coisa de formas diferentes) "
        "   → fundir em uma única, mais clara.\n"
        "2. Identificar regras CONTRADITÓRIAS (uma diz o oposto da outra) → conservar a "
        "   mais recente (data maior no prefixo [YYYY-MM-DD]) e descartar a mais antiga.\n"
        "3. Identificar regras MUITO VAGAS ou INACIONÁVEIS (ex.: 'manter voz do autor') "
        "   → reescrever de forma concreta ou descartar se não for possível.\n"
        "4. Manter intactas as regras que estão boas.\n"
        "Devolva APENAS a lista final de regras consolidadas, uma por linha, começando "
        "com '- [data] ' (mantenha a data da regra mais recente do grupo fundido). "
        "Nada além das regras."
    )
    user = f"Regras atuais:\n{lista}\n\nLista consolidada:"

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    texto = resp.content[0].text.strip()
    consolidadas = [l.strip() for l in texto.splitlines() if l.strip().startswith("- ")]
    return consolidadas


def main():
    aplicar_direto = "--aplicar" in sys.argv

    antes, secao = ler_preferencias()
    regras = extrair_regras(secao)

    if not regras:
        print("ℹ️  Nenhuma regra encontrada na seção [10].")
        sys.exit(0)

    print(f"\n📋 {len(regras)} regra(s) encontrada(s) na seção [10].")
    print("🧹 Consolidando com IA...\n")

    consolidadas = consolidar_regras(regras)

    print("─" * 60)
    print(f"ANTES: {len(regras)} regras  →  DEPOIS: {len(consolidadas)} regras")
    print("─" * 60)

    # Mostra o diff
    antes_set = set(regras)
    depois_set = set(consolidadas)
    removidas = antes_set - depois_set
    adicionadas = depois_set - antes_set

    if removidas:
        print("\n🗑️  Removidas/fundidas:")
        for r in sorted(removidas):
            print(f"  - {r}")
    if adicionadas:
        print("\n✨ Novas (fundidas ou reescritas):")
        for r in sorted(adicionadas):
            print(f"  + {r}")
    if not removidas and not adicionadas:
        print("\n✅ Nenhuma mudança necessária — regras já estão limpas.")
        sys.exit(0)

    if not aplicar_direto:
        resp = input("\nAplicar essas mudanças no preferencias.md? [s/n] → ").strip().lower()
        if resp != "s":
            print("Cancelado.")
            sys.exit(0)

    # Reconstrói a seção [10]
    nova_secao = "\n".join(consolidadas)
    novo_texto = (
        antes
        + MARCADOR_SECAO
        + "\n\n"
        + nova_secao
        + "\n"
    )
    PREFERENCIAS_PATH.write_text(novo_texto, encoding="utf-8")
    print(f"\n✅ preferencias.md atualizado com {len(consolidadas)} regra(s) consolidada(s).")


if __name__ == "__main__":
    main()
