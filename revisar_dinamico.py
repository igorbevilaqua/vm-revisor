#!/usr/bin/env python3
"""
Revisão Dinâmica:Viral Media Labs
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

from terminal import patch_stdout
patch_stdout()

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
    ignorados = []
    for trecho, novo in correcoes:
        if not trecho or not trecho.strip():
            ignorados.append(f"sem trecho: «{novo[:60]}»")
            continue
        if trecho not in texto_doc:
            ignorados.append(f"trecho não encontrado no doc: «{trecho[:60]}»")
            continue
        n = contar_ocorrencias(texto_doc, trecho)
        if n > 1:
            avisos.append(f"  ⚠️  «{trecho[:50]}» aparece {n}x no doc:todas serão trocadas")
        requests.append({
            "replaceAllText": {
                "containsText": {"text": trecho, "matchCase": True},
                "replaceText": novo,
            }
        })
    if ignorados:
        print(cinza(f"   {len(ignorados)} correção(ões) ignorada(s) (sem âncora no doc):"))
        for msg in ignorados:
            print(cinza(f"   • {msg}"))

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
    ensinamentos = []  # decisões com contexto para o loop de aprendizado

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

            if trecho == correcao:
                continue

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
                        motivo = input(cinza("   Registrar motivo da edição? (Enter pra pular): ")).strip()
                        ensinamentos.append({
                            **achado,
                            "_tipo_decisao": "editar",
                            "_correcao_original": correcao,
                            "_versao_usuario": novo,
                            "_motivo": motivo,
                        })
                    else:
                        print(cinza("   Pulado (texto vazio)"))
                        ensinamentos.append({**achado, "_tipo_decisao": "pular", "_motivo": ""})
                    break
                elif resp == "p":
                    motivo = input(cinza("   Motivo (opcional, Enter pra pular): ")).strip()
                    ensinamentos.append({**achado, "_tipo_decisao": "pular", "_motivo": motivo})
                    print(cinza("   Pulado"))
                    break
                elif resp == "q":
                    print("\nRevisão interrompida.")
                    return correcoes_aprovadas, ensinamentos
                else:
                    print(cinza("   Digite a, e, p ou q."))

    # ── Fim do roteiro: aplicar ───────────────────────────────────────────────
    print(f"\n{'═' * 62}")

    if not correcoes_aprovadas:
        print(verde("✅ Nenhuma correção aprovada neste roteiro."))
        return correcoes_aprovadas, ensinamentos

    print(negrito(f"Fim do roteiro:{len(correcoes_aprovadas)} correção(ões) aprovada(s):"))
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
        print(cinza("(Sem link do doc:correções não foram gravadas)"))

    return correcoes_aprovadas, ensinamentos


# ─── Loop de aprendizado ────────────────────────────────────────────────────

def loop_aprendizado(ensinamentos):
    """Processa decisões com contexto e gera regras no preferencias.md.

    Suporta dois tipos de ensinamento:
    - 'pular': agente sugeriu X, usuário rejeitou (com motivo opcional)
    - 'editar': agente sugeriu X, usuário preferiu Y (com motivo opcional)
    """
    # Filtra só os ensinamentos que têm sinal suficiente para gerar regra
    uteis = [
        e for e in ensinamentos
        if e.get("_motivo") or e.get("_tipo_decisao") == "editar"
    ]
    if not uteis:
        return

    n_pular  = sum(1 for e in uteis if e.get("_tipo_decisao") == "pular")
    n_editar = sum(1 for e in uteis if e.get("_tipo_decisao") == "editar")

    print(f"\n{'═' * 62}")
    print(negrito(f"🧠 Aprendizado: {len(uteis)} ensinamento(s) registrado(s)"))
    if n_pular:  print(cinza(f"   {n_pular} rejeição(ões) com motivo"))
    if n_editar: print(cinza(f"   {n_editar} edição(ões) (preferência do editor)"))
    print("Incorporar ao preferencias.md para as próximas revisões?")

    resp = input("[s/n] → ").strip().lower()
    if resp != "s":
        return

    # Monta contexto rico para gerar_regras
    achados_para_regra = []
    for e in uteis:
        a = {k: v for k, v in e.items() if not k.startswith("_")}
        tipo   = e.get("_tipo_decisao", "pular")
        motivo = e.get("_motivo", "")
        orig   = e.get("_correcao_original", "")
        versao = e.get("_versao_usuario", "")

        if tipo == "editar" and orig and versao:
            contexto = f"Editor PREFERIU «{versao}» em vez de «{orig}»"
            if motivo:
                contexto += f". Motivo: {motivo}"
        else:
            contexto = f"Editor REJEITOU. Motivo: {motivo}" if motivo else "Editor rejeitou sem motivo explícito"

        a["porque"] = f"{e.get('porque', '')} | {contexto}"
        achados_para_regra.append(a)

    from feedback import gerar_regras, carregar_regras_existentes, detectar_conflitos, acrescentar_preferencias
    from datetime import datetime

    print(f"\n🧠 Destilando {len(achados_para_regra)} ensinamento(s) em regras...")
    novas = gerar_regras(achados_para_regra)
    if not novas:
        print("Não foi possível destilar regras.")
        return

    existentes = carregar_regras_existentes()
    conflitos  = detectar_conflitos(novas, existentes)
    data = datetime.now().strftime("%Y-%m-%d")
    a_gravar = []

    for regra, conflito in zip(novas, conflitos):
        if conflito:
            print(f"\n⚠️  Possível conflito com regra existente: {conflito}")
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
        print("🔍 Analisando o roteiro com 9 agentes em paralelo...")
        print("   Aguarde, isso leva cerca de 1-2 minutos.\n")
        resultado = subprocess.run(
            [sys.executable, "revisar.py", "--gdocs", args.gdocs],
            cwd=Path(__file__).parent,
            stdout=subprocess.DEVNULL
        )
        if resultado.returncode != 0:
            print("❌ Erro na revisão. Tente rodar revisar.py separadamente para ver o erro.")
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

    todos_ensinamentos = []
    for i, roteiro in enumerate(roteiros):
        _, ensinamentos = revisar_roteiro(roteiro, args.gdocs)
        todos_ensinamentos.extend(ensinamentos)
        if i + 1 < len(roteiros):
            resp = input(f"\n▶ Próximo roteiro ({i + 2}/{len(roteiros)})? [s/n] → ").strip().lower()
            if resp != "s":
                break

    loop_aprendizado(todos_ensinamentos)
    print("\n🎉 Revisão dinâmica concluída.")


if __name__ == "__main__":
    main()
