#!/usr/bin/env python3
"""
Revisão Dinâmica — Viral Media Labs
Revisão interativa parágrafo a parágrafo, sem precisar do Claude Code.

Uso:
    python3 revisar_dinamico.py --gdocs "https://docs.google.com/document/d/..."
    python3 revisar_dinamico.py --json relatorios/revisao_X.json --gdocs "https://..."
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# ─── Cores no terminal ───────────────────────────────────────────────────────

def negrito(s): return f"\033[1m{s}\033[0m"
def vermelho(s): return f"\033[91m{s}\033[0m"
def amarelo(s): return f"\033[93m{s}\033[0m"
def verde(s): return f"\033[92m{s}\033[0m"
def cinza(s): return f"\033[90m{s}\033[0m"

# ─── Classificação de achados ────────────────────────────────────────────────

def eh_obrigatorio(achado):
    return (
        achado.get("severidade") == "erro"
        and achado.get("natureza") == "objetivo"
        and achado.get("confianca", 0) >= 70
    )

def eh_linha_metadata(linha):
    return bool(re.match(
        r"^(Fonte|Fontes|http|Cliente:|###\s|---)",
        linha.strip(), re.IGNORECASE
    ))

# ─── Divisão em parágrafos ───────────────────────────────────────────────────

def dividir_paragrafos(texto):
    paragrafos = []
    bloco = []
    for linha in texto.splitlines():
        if not linha.strip():
            if bloco:
                paragrafos.append("\n".join(bloco))
                bloco = []
        elif not eh_linha_metadata(linha):
            bloco.append(linha)
    if bloco:
        paragrafos.append("\n".join(bloco))
    return [p for p in paragrafos if p.strip()]

def achados_do_paragrafo(paragrafo, achados):
    return [a for a in achados if (a.get("trecho_original") or "").strip() in paragrafo]

# ─── Aplicação no Google Doc ─────────────────────────────────────────────────

def contar_ocorrencias(texto_doc, trecho):
    return texto_doc.count(trecho)

def aplicar_correcoes(url, correcoes):
    from google_docs import extrair_doc_id, autenticar, ler_documento
    from googleapiclient.discovery import build

    SCOPES_WRITE = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ]
    TOKEN_WRITE = Path(__file__).parent / "credentials" / "token_write.pickle"

    doc_id = extrair_doc_id(url)
    creds = autenticar(scopes=SCOPES_WRITE, token_path=TOKEN_WRITE)
    docs = build("docs", "v1", credentials=creds)

    # Lê o doc pra checar ocorrências múltiplas
    _, texto_doc = ler_documento(doc_id, creds)

    requests = []
    avisos = []
    for trecho, novo in correcoes:
        n = contar_ocorrencias(texto_doc, trecho)
        if n > 1:
            avisos.append(f"  ⚠️  «{trecho[:50]}» aparece {n}x no doc — todas serão trocadas")
        requests.append({
            "replaceAllText": {
                "containsText": {"text": trecho, "matchCase": True},
                "replaceText": novo,
            }
        })

    if avisos:
        print("\n" + "\n".join(avisos))
        resp = input("Continuar mesmo assim? [s/n] → ").strip().lower()
        if resp != "s":
            return 0

    result = docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()

    return sum(
        r.get("replaceAllText", {}).get("occurrencesChanged", 0)
        for r in result.get("replies", [])
    )

# ─── Loop interativo por roteiro ─────────────────────────────────────────────

def revisar_roteiro(roteiro, url):
    cons = roteiro.get("consolidado", {})
    achados = cons.get("achados", [])
    texto = roteiro.get("texto", "")
    titulo = roteiro.get("titulo", f"Roteiro {roteiro.get('numero', '?')}")

    print("\n" + "═" * 62)
    print(negrito(f"📄 {titulo}"))
    print("═" * 62)

    # Contexto rápido
    diagnostico = cons.get("diagnostico", "")
    if diagnostico:
        linhas = [l for l in diagnostico.splitlines() if l.strip()][:5]
        for l in linhas:
            print(cinza(l))

    veredicto = cons.get("veredicto", "")
    nota = cons.get("nota_geral", "")
    if veredicto:
        print(f"\nVeredicto: {negrito(veredicto)}  |  Nota: {nota}/10")

    n_obrig = sum(1 for a in achados if eh_obrigatorio(a))
    n_opcio = len(achados) - n_obrig
    print(cinza(f"Achados: {n_obrig} obrigatório(s) · {n_opcio} opcional(is)"))

    input(cinza("\n[Enter para começar] "))

    paragrafos = dividir_paragrafos(texto)
    correcoes_aprovadas = []
    pulados = []  # achados rejeitados/pulados para o loop de aprendizado

    for i, par in enumerate(paragrafos, 1):
        achados_par = achados_do_paragrafo(par, achados)
        if not achados_par:
            continue

        print(f"\n{'─' * 62}")
        print(cinza(f"Parágrafo {i}/{len(paragrafos)}"))
        print(f"\n{par}\n")

        for achado in achados_par:
            trecho  = (achado.get("trecho_original") or "").strip()
            correcao = (achado.get("correcao") or "").strip()
            porque  = (achado.get("porque") or "").strip()
            camada  = achado.get("camada", "")
            conf    = achado.get("confianca", 0)
            obrig   = eh_obrigatorio(achado)

            if obrig:
                print(vermelho(f"⛔ Correção obrigatória  [{camada} · {conf}%]"))
            else:
                print(amarelo(f"✨ Otimização opcional   [{camada} · {conf}%]"))

            print(f"   Antes:  {negrito(trecho)}")
            print(f"   Depois: {negrito(correcao)}")
            print(cinza(f"   Por quê: {porque}"))

            while True:
                resp = input("\n   [a]plicar  [e]ditar  [p]ular  [q]sair → ").strip().lower()
                if resp == "a":
                    correcoes_aprovadas.append((trecho, correcao))
                    print(verde("   ✅ Aprovado"))
                    break
                elif resp == "e":
                    novo = input(f"   Novo texto (vai substituir «{trecho}»): ").strip()
                    if novo:
                        correcoes_aprovadas.append((trecho, novo))
                        print(verde("   ✅ Editado"))
                    else:
                        pulados.append(achado)
                        print(cinza("   Pulado (texto vazio)"))
                    break
                elif resp == "p":
                    motivo = input(cinza("   Motivo (opcional, Enter pra pular): ")).strip()
                    a_registrar = dict(achado)
                    if motivo:
                        a_registrar["_motivo_rejeicao"] = motivo
                    pulados.append(a_registrar)
                    print(cinza("   Pulado"))
                    break
                elif resp == "q":
                    print("\nRevisão interrompida.")
                    return correcoes_aprovadas, pulados
                else:
                    print(cinza("   Digite a, e, p ou q."))

    # ── Fim do roteiro: aplicar ───────────────────────────────────────────────
    print(f"\n{'═' * 62}")

    if not correcoes_aprovadas:
        print(verde("✅ Nenhuma correção aprovada neste roteiro."))
        return correcoes_aprovadas, pulados

    print(negrito(f"Fim do roteiro — {len(correcoes_aprovadas)} correção(ões) aprovada(s):"))
    for trecho, novo in correcoes_aprovadas:
        print(f"  • «{trecho[:55]}»")
        print(f"    → «{novo[:55]}»")

    if url:
        resp = input(f"\nGravar no Google Doc original? [s/n] → ").strip().lower()
        if resp == "s":
            print("Aplicando...")
            n = aplicar_correcoes(url, correcoes_aprovadas)
            print(verde(f"✅ {n} substituição(ões) aplicada(s) no doc."))
            print(cinza("   (Arquivo → Histórico de versões para reverter, se precisar)"))
    else:
        print(cinza("(Sem link do doc — correções não foram gravadas)"))

    return correcoes_aprovadas, pulados


# ─── Loop de aprendizado ────────────────────────────────────────────────────

def loop_aprendizado(todos_pulados):
    """Oferece transformar os achados pulados em regras no preferencias.md."""
    if not todos_pulados:
        return

    print(f"\n{'═' * 62}")
    print(negrito(f"🧠 Aprendizado — {len(todos_pulados)} sugestão(ões) pulada(s)"))
    print("Quer ensinar o sistema sobre suas rejeições?")
    print(cinza("Isso gera regras novas no preferencias.md para as próximas revisões."))

    resp = input("[s/n] → ").strip().lower()
    if resp != "s":
        return

    # Enriquece os achados com motivo se o usuário quiser adicionar agora
    for i, a in enumerate(todos_pulados, 1):
        trecho = (a.get("trecho_original") or "[global]")[:60]
        motivo_existente = a.get("_motivo_rejeicao", "")
        if motivo_existente:
            print(cinza(f"\n{i}. «{trecho}» — motivo já registrado: {motivo_existente}"))
        else:
            print(f"\n{i}. [{a.get('camada')}] «{trecho}»")
            print(cinza(f"   Sugestão: {(a.get('correcao') or '')[:60]}"))
            motivo = input(cinza("   Motivo da rejeição (Enter pra pular): ")).strip()
            if motivo:
                a["_motivo_rejeicao"] = motivo

    # Enriquece o campo "porque" com o motivo do usuário para a geração de regras
    achados_para_regra = []
    for a in todos_pulados:
        enriquecido = dict(a)
        motivo = a.get("_motivo_rejeicao", "")
        if motivo:
            enriquecido["porque"] = f"{a.get('porque', '')} | Editor rejeitou: {motivo}"
        achados_para_regra.append(enriquecido)

    from feedback import gerar_regras, carregar_regras_existentes, detectar_conflitos, acrescentar_preferencias
    from datetime import datetime

    print(f"\n🧠 Destilando {len(achados_para_regra)} rejeição(ões) em regras...")
    novas = gerar_regras(achados_para_regra)
    if not novas:
        print("Não foi possível destilar regras.")
        return

    existentes = carregar_regras_existentes()
    conflitos = detectar_conflitos(novas, existentes)
    data = datetime.now().strftime("%Y-%m-%d")
    a_gravar = []

    for regra, conflito in zip(novas, conflitos):
        if conflito:
            print(f"\n⚠️  Possível conflito: {conflito}")
            print(f"   Regra nova: {regra}")
            resp = input("   Adicionar mesmo assim? [s/n] → ").strip().lower()
            if resp != "s":
                continue
        a_gravar.append(f"- [{data}] {regra}")

    if a_gravar:
        acrescentar_preferencias(a_gravar)
        print(verde(f"\n✅ {len(a_gravar)} regra(s) adicionada(s) ao preferencias.md:"))
        for r in a_gravar:
            print(f"   {r}")
        print(cinza("   Nas próximas revisões os agentes já respeitam essas regras."))
    else:
        print("Nenhuma regra adicionada.")


# ─── Ponto de entrada ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Revisão dinâmica parágrafo a parágrafo"
    )
    parser.add_argument("--gdocs", help="Link do Google Doc")
    parser.add_argument("--json", dest="json_path",
                        help="JSON já gerado (pula a revisão dos 9 agentes)")
    args = parser.parse_args()

    if not args.gdocs and not args.json_path:
        parser.print_help()
        sys.exit(1)

    # ── 1. Obter o JSON ───────────────────────────────────────────────────────
    if args.json_path:
        json_path = Path(args.json_path)
        if not json_path.exists():
            print(f"❌ JSON não encontrado: {json_path}")
            sys.exit(1)
    else:
        print("🔍 Rodando revisão completa (9 agentes em paralelo)...")
        print("   Isso leva cerca de 1-2 minutos.\n")
        resultado = subprocess.run(
            [sys.executable, "revisar.py", "--gdocs", args.gdocs],
            cwd=Path(__file__).parent
        )
        if resultado.returncode != 0:
            print("❌ Erro na revisão. Verifique a saída acima.")
            sys.exit(1)
        jsons = sorted(Path("relatorios").glob("revisao_*.json"))
        if not jsons:
            print("❌ Nenhum JSON encontrado em relatorios/")
            sys.exit(1)
        json_path = jsons[-1]
        print(f"\n✅ Revisão concluída → {json_path.name}\n")

    # ── 2. Carregar e revisar ─────────────────────────────────────────────────
    roteiros = json.loads(json_path.read_text(encoding="utf-8"))
    print(f"📋 {len(roteiros)} roteiro(s) encontrado(s).")

    todos_pulados = []
    for i, roteiro in enumerate(roteiros):
        _, pulados = revisar_roteiro(roteiro, args.gdocs)
        todos_pulados.extend(pulados)
        if i + 1 < len(roteiros):
            resp = input(f"\n▶ Próximo roteiro ({i + 2}/{len(roteiros)})? [s/n] → ").strip().lower()
            if resp != "s":
                break

    loop_aprendizado(todos_pulados)
    print("\n🎉 Revisão dinâmica concluída.")


if __name__ == "__main__":
    main()
