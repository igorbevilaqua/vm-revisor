#!/usr/bin/env python3
"""
Loop de feedback — Viral Media Labs

Você marca os achados de uma revisão com os quais DISCORDA, e o sistema destila
esses casos em "regras da casa", acrescentadas ao preferencias.md. Nas próximas
revisões, todo agente recebe essas regras e para de sugerir o que você rejeita.

Uso:
    python3 feedback.py                         # usa a revisão .json mais recente
    python3 feedback.py relatorios/revisao_X.json
    python3 feedback.py --rejeitar 3,7,12       # não-interativo (índices a rejeitar)
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

from terminal import patch_stdout
patch_stdout()
from datetime import datetime

import anthropic

RAIZ = Path(__file__).parent
PREFERENCIAS_PATH = RAIZ / "preferencias.md"
PASTA_RELATORIOS = RAIZ / "relatorios"
MARCADOR_SECAO = "## [10] APRENDIDO COM REJEIÇÕES"


def json_mais_recente() -> Path | None:
    arquivos = sorted(PASTA_RELATORIOS.glob("revisao_*.json"))
    return arquivos[-1] if arquivos else None


def carregar_achados(json_path: Path) -> list[dict]:
    """Lista plana de achados, na ordem dos relatórios, com rótulo do roteiro."""
    dados = json.loads(json_path.read_text(encoding="utf-8"))
    achados = []
    for roteiro in dados:
        cons = roteiro.get("consolidado", {})
        for a in cons.get("achados", []):
            a = dict(a)
            a["_roteiro"] = roteiro.get("titulo", "")
            achados.append(a)
    return achados


def imprimir(achados: list[dict]):
    print("\n" + "═" * 70)
    print("  ACHADOS DESTA REVISÃO — marque os que você REJEITA")
    print("═" * 70)
    for i, a in enumerate(achados, 1):
        trecho = (a.get("trecho_original") or "[global]")[:55]
        corr = (a.get("correcao") or "")[:55]
        print(f"\n{i:>2}. [{a.get('camada')} · {a.get('severidade')} · {a.get('natureza')}]")
        print(f'    trecho: "{trecho}"')
        print(f'    sugere: {corr}')


def gerar_regras(rejeitados: list[dict]) -> list[str]:
    """Usa a LLM para transformar os achados rejeitados em regras concisas (PT-BR).

    Devolve uma LISTA de regras individuais (sem '- ' e sem data) — assim cada uma
    pode ser checada contra conflitos e datada separadamente.
    """
    casos = "\n".join(
        f"- [{a.get('camada')}] sugeriu trocar «{(a.get('trecho_original') or '[global]')[:60]}» "
        f"por «{(a.get('correcao') or '')[:80]}» (motivo: {(a.get('porque') or '')[:80]})"
        for a in rejeitados
    )
    system = (
        "Você ajuda a manter o guia de estilo de um editor de roteiros. O editor REJEITOU "
        "as sugestões abaixo de um revisor automático. Generalize cada rejeição em uma REGRA "
        "curta e acionável (1 linha, em português), começando com verbo, que evite sugestões "
        "parecidas no futuro. Não explique. Não numere. Uma regra por linha, com '- ' no início. "
        "Se duas rejeições viram a mesma regra, escreva só uma."
    )
    user = f"Sugestões rejeitadas pelo editor:\n{casos}\n\nEscreva as regras:"
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    texto = resp.content[0].text.strip()
    regras = [l.strip()[2:].strip() for l in texto.splitlines() if l.strip().startswith("- ")]
    if not regras:  # fallback: modelo não usou '- '
        regras = [l.strip() for l in texto.splitlines() if l.strip()]
    return regras


def carregar_regras_existentes() -> list[str]:
    """Regras já gravadas (para a checagem de conflito). Lê da nova estrutura
    (aprendizados.json) quando ela existe; senão, da seção [10] legada."""
    import aprendizados
    if aprendizados.existe():
        return [a["texto"].replace("\n", " ")[:200]
                for a in aprendizados.carregar() if a.get("ativo", True)]
    if not PREFERENCIAS_PATH.exists():
        return []
    texto = PREFERENCIAS_PATH.read_text(encoding="utf-8")
    if MARCADOR_SECAO not in texto:
        return []
    secao = texto.split(MARCADOR_SECAO, 1)[1]
    regras = []
    for linha in secao.splitlines():
        s = linha.strip()
        if s.startswith("- ") and "placeholder" not in s:
            regras.append(s[2:].strip())
    return regras


def detectar_conflitos(novas: list[str], existentes: list[str]) -> list[str | None]:
    """Para cada regra nova, devolve a regra existente que ela CONTRADIZ (ou None).

    Usa a LLM (busca semântica, não keyword). Se a seção [10] está vazia, pula a
    chamada e devolve tudo None — custo zero no caso comum.
    """
    if not existentes or not novas:
        return [None] * len(novas)
    lista_existentes = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(existentes))
    lista_novas = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(novas))
    system = (
        "Você compara regras de um guia de estilo. Para cada REGRA NOVA, diga se ela "
        "CONTRADIZ (orienta o oposto sobre o MESMO tema) alguma REGRA EXISTENTE. "
        "Responda exatamente uma linha por regra nova, na ordem, no formato 'N: X', onde X é "
        "o número da regra existente conflitante, ou 'N: 0' se não há conflito. Nada além disso."
    )
    user = f"REGRAS EXISTENTES:\n{lista_existentes}\n\nREGRAS NOVAS:\n{lista_novas}"
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    mapa: dict[int, str | None] = {}
    for linha in resp.content[0].text.strip().splitlines():
        if ":" not in linha:
            continue
        esq, dir_ = (p.strip() for p in linha.split(":", 1))
        dir_ = dir_.lstrip("-")
        if esq.isdigit() and dir_.isdigit():
            n, x = int(esq), int(dir_)
            if 1 <= n <= len(novas):
                mapa[n - 1] = existentes[x - 1] if 1 <= x <= len(existentes) else None
    return [mapa.get(i) for i in range(len(novas))]


def acrescentar_preferencias(regras_datadas: list[str]):
    """LEGADO: acrescenta linhas '- [YYYY-MM-DD] regra' ao FIM da seção [10]."""
    texto = PREFERENCIAS_PATH.read_text(encoding="utf-8") if PREFERENCIAS_PATH.exists() else ""
    bloco = "\n".join(regras_datadas)
    if MARCADOR_SECAO in texto:
        texto = texto.rstrip() + "\n" + bloco + "\n"
    else:
        texto = texto.rstrip() + f"\n\n{MARCADOR_SECAO}\n\n{bloco}\n"
    PREFERENCIAS_PATH.write_text(texto, encoding="utf-8")


def salvar_regras(regras: list[str], origem: str = "pular") -> str:
    """Grava regras destiladas na nova estrutura (aprendizados.json, escopo
    global). Enquanto a migração não foi rodada (arquivo não existe), mantém o
    comportamento legado: seção [10] do preferencias.md. Retorna o nome do
    arquivo de destino (para as mensagens ao usuário)."""
    import aprendizados
    if aprendizados.existe():
        aprendizados.adicionar([
            {"texto": r, "escopo": "global", "origem": origem} for r in regras
        ])
        try:
            import git_sync
            git_sync.enviar(mensagem=f"aprendizados: +{len(regras)} (feedback)")
        except Exception:
            pass
        return aprendizados.ARQUIVO.name
    data = datetime.now().strftime("%Y-%m-%d")
    acrescentar_preferencias([f"- [{data}] {r}" for r in regras])
    return PREFERENCIAS_PATH.name


def parse_indices(entrada: str, total: int) -> list[int]:
    out = []
    for parte in entrada.replace(" ", "").split(","):
        if parte.isdigit() and 1 <= int(parte) <= total:
            out.append(int(parte) - 1)
    return out


def main():
    args = sys.argv[1:]
    rejeitar_arg = None
    json_path = None
    if "--rejeitar" in args:
        i = args.index("--rejeitar")
        rejeitar_arg = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
    if args:
        json_path = Path(args[0])
    if json_path is None:
        json_path = json_mais_recente()
    if not json_path or not json_path.exists():
        print("❌ Nenhum .json de revisão encontrado. Rode revisar.py primeiro.")
        sys.exit(1)

    achados = carregar_achados(json_path)
    if not achados:
        print("Nenhum achado nessa revisão.")
        return

    interativo = rejeitar_arg is None
    if not interativo:
        indices = parse_indices(rejeitar_arg, len(achados))
    else:
        imprimir(achados)
        print("\n" + "─" * 70)
        entrada = input("Números que você REJEITA (ex: 3,7,12) — ENTER p/ nenhum: ").strip()
        indices = parse_indices(entrada, len(achados)) if entrada else []

    if not indices:
        print("Nada rejeitado. preferencias.md inalterado.")
        return

    rejeitados = [achados[i] for i in indices]
    print(f"\n🧠 Destilando {len(rejeitados)} rejeição(ões) em regras...")
    novas = gerar_regras(rejeitados)
    if not novas:
        print("Não consegui destilar nenhuma regra. preferencias.md inalterado.")
        return

    existentes = carregar_regras_existentes()
    conflitos = detectar_conflitos(novas, existentes)

    a_gravar = []
    for regra, conflito in zip(novas, conflitos):
        if conflito:
            print(f"\n⚠️  Possível conflito com regra existente: {conflito}")
            print(f"    Regra nova: {regra}")
            if interativo:
                resp = input("    Adicionar mesmo assim? (s/n): ").strip().lower()
                if resp != "s":
                    print("    ↪ pulada.")
                    continue
            else:
                print("    ↪ modo não-interativo: gravando mesmo assim "
                      "(rode sem --rejeitar para revisar manualmente).")
        a_gravar.append(regra)

    if not a_gravar:
        print("\nNenhuma regra nova adicionada.")
        return

    destino = salvar_regras(a_gravar, origem="pular")
    print(f"\n✅ Regras adicionadas a {destino}:\n")
    print("\n".join(f"- {r}" for r in a_gravar))
    print("\nNas próximas revisões, os agentes já vão respeitar essas regras.")


if __name__ == "__main__":
    main()
