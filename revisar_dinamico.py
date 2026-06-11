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

import ledger

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
    # Achados sem trecho_original são sugestões globais — tratados separadamente.
    return [a for a in achados
            if (a.get("trecho_original") or "").strip()
            and (a.get("trecho_original") or "").strip() in paragrafo]


def _trecho_sobrepos(trecho: str, processados: set) -> bool:
    """True se o trecho se sobrepõe a algum trecho já exibido ao usuário.
    Cobre: (a) trecho idêntico, (b) trecho contido em outro, (c) outro contido neste."""
    t = (trecho or "").strip()
    if not t:
        return False
    return any(t in p or p in t for p in processados)


def _minimizar_trecho(trecho: str, correcao: str, min_anchor: int = 20) -> tuple[str, str]:
    """Encurta o par (trecho, correcao) ao segmento mínimo contendo a diferença real.
    Preserva pelo menos min_anchor chars de âncora para evitar falsos matches no doc."""
    if not trecho or not correcao or trecho == correcao:
        return trecho, correcao

    # Prefixo comum
    pref = 0
    while pref < min(len(trecho), len(correcao)) and trecho[pref] == correcao[pref]:
        pref += 1

    # Sufixo comum nos restos
    t_rest = trecho[pref:]
    c_rest = correcao[pref:]
    suf = 0
    while suf < min(len(t_rest), len(c_rest)) and t_rest[-(suf + 1)] == c_rest[-(suf + 1)]:
        suf += 1

    # Núcleo: parte que realmente muda
    t_core = t_rest[: len(t_rest) - suf] if suf else t_rest
    c_core = c_rest[: len(c_rest) - suf] if suf else c_rest

    # Contexto de sufixo (âncora de fechamento) — primeiros chars do SUFFIX comum
    suf_ctx = min(suf, 10)
    sufixo_ancora = t_rest[len(t_core) : len(t_core) + suf_ctx]

    # Contexto de prefixo (âncora de abertura) — últimos chars do PREFIX comum
    ctx = max(0, min_anchor - len(t_core) - suf_ctx)
    pref_start = max(0, pref - ctx)
    # Snap ao limite de palavra para não cortar no meio de token
    while pref_start > 0 and trecho[pref_start - 1] not in (" ", "\n", "\t", ".", ",", ";"):
        pref_start -= 1

    prefixo_ancora = trecho[pref_start:pref]
    novo_t = prefixo_ancora + t_core + sufixo_ancora
    novo_c = prefixo_ancora + c_core + sufixo_ancora

    # Sanidade: se ficaram iguais (caso degenerado), retorna originais
    return (novo_t, novo_c) if novo_t != novo_c else (trecho, correcao)


def _e_substituicao_direta(trecho: str, correcao: str) -> bool:
    """Detecta se correcao é de fato um texto para substituir o trecho.
    Instrução editorial tem ratio de comprimento muito maior que a substituição."""
    if not trecho:
        return False
    # Se correcao for >3x o trecho E >150 chars, é quase certamente instrução editorial.
    if len(correcao) > max(150, 3 * len(trecho)):
        return False
    return True

# ─── Aplicação no Google Doc ─────────────────────────────────────────────────

def contar_ocorrencias(texto_doc, trecho):
    return texto_doc.count(trecho)

def aplicar_correcoes(url, correcoes, interativo=True):
    """Aplica as correções no Google Doc. Retorna dict {"aplicadas": n, "avisos": [...]}.

    interativo=True  → pergunta no terminal antes de trocar trechos com múltiplas ocorrências.
    interativo=False → nunca chama input() (uso em handler HTTP); devolve os avisos no dict.
    """
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
    for trecho_orig, novo_orig in correcoes:
        if not trecho_orig or not trecho_orig.strip():
            ignorados.append(f"sem trecho: «{novo_orig[:60]}»")
            continue

        # Minimiza ao segmento mínimo que ancora a mudança — menos riscado no doc.
        trecho, novo = _minimizar_trecho(trecho_orig, novo_orig)

        # Se o trecho minimizado não está no doc, tenta o original como fallback.
        if trecho not in texto_doc:
            if trecho_orig not in texto_doc:
                ignorados.append(f"trecho não encontrado no doc: «{trecho_orig[:60]}»")
                continue
            trecho, novo = trecho_orig, novo_orig

        n = contar_ocorrencias(texto_doc, trecho)
        if n > 1:
            avisos.append(f"«{trecho[:50]}» aparece {n}x no doc: todas serão trocadas")
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

    if avisos and interativo:
        print("\n" + "\n".join(f"  ⚠️  {a}" for a in avisos))
        resp = input("Continuar mesmo assim? [s/n] → ").strip().lower()
        if resp != "s":
            return {"aplicadas": 0, "avisos": avisos}

    if not requests:
        return {"aplicadas": 0, "avisos": avisos}

    result = docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()

    aplicadas = sum(
        r.get("replaceAllText", {}).get("occurrencesChanged", 0)
        for r in result.get("replies", [])
    )
    return {"aplicadas": aplicadas, "avisos": avisos}

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
    trechos_processados: set = set()  # trava: trechos já exibidos (impede duplicatas e sobrepostos)
    # Contexto fixo dos eventos do ledger nesta sessão (memória permanente de decisões)
    _led = dict(
        cliente=roteiro.get("cliente") or "",
        roteiro_titulo=titulo,
        estrutura=(roteiro.get("contexto") or {}).get("estrutura", ""),
        origem="dinamica",
    )

    for i, par in enumerate(paragrafos, 1):
        achados_par = achados_do_paragrafo(par, achados)
        # Remove achados cujo trecho se sobrepõe a um já exibido (mesmo exato ou contido/contém).
        achados_par = [a for a in achados_par
                       if not _trecho_sobrepos(a.get("trecho_original", ""), trechos_processados)]
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

            # Filtra sugestões subjetivas de baixa confiança — ruído imperceptível ao
            # espectador. Ainda aparecem no relatório; só omitidos no fluxo interativo.
            if (achado.get("natureza") == "subjetivo"
                    and achado.get("severidade") in ("sugestao", "aviso")
                    and achado.get("confianca", 0) < 75):
                continue

            # Marca como processado ANTES de exibir — garante que a trava já valha
            # para qualquer achado sobreposto que venha logo depois no mesmo parágrafo.
            if trecho:
                trechos_processados.add(trecho)

            substituicao_direta = _e_substituicao_direta(trecho, correcao)

            if obrig:
                print(vermelho(f"⛔ Correção obrigatória  [{camada} · {conf}%]"))
            else:
                print(amarelo(f"✨ Otimização opcional   [{camada} · {conf}%]"))

            print(f"   Antes:  {negrito(trecho)}")

            if substituicao_direta:
                print(f"   Depois: {negrito(correcao)}")
            else:
                print(amarelo("   ⚠️  Sugestão editorial (não é substituição direta):"))
                print(f"   {correcao}")

            print(cinza(f"   Por quê: {porque}"))

            if not substituicao_direta:
                # Só pode editar ou pular — não tem como aplicar automaticamente.
                while True:
                    resp = input("\n   [e]ditar texto substituto  [p]ular  [q]sair → ").strip().lower()
                    if resp == "e":
                        novo = input(f"   Novo texto (vai substituir «{trecho}»): ").strip()
                        if novo:
                            correcoes_aprovadas.append((trecho, novo))
                            print(verde("   ✅ Editado"))
                            ensinamentos.append({
                                **achado,
                                "_tipo_decisao": "editar",
                                "_correcao_original": correcao,
                                "_versao_usuario": novo,
                                "_motivo": "",
                            })
                            ledger.registrar_decisao(achado, "editado", versao_usuario=novo, **_led)
                        else:
                            print(cinza("   Pulado (texto vazio)"))
                            ensinamentos.append({**achado, "_tipo_decisao": "pular", "_motivo": ""})
                            ledger.registrar_decisao(achado, "pulado", **_led)
                        break
                    elif resp == "p":
                        motivo = input(cinza("   Motivo (opcional, Enter pra pular): ")).strip()
                        ensinamentos.append({**achado, "_tipo_decisao": "pular", "_motivo": motivo})
                        ledger.registrar_decisao(achado, "pulado", motivo=motivo, **_led)
                        print(cinza("   Pulado"))
                        break
                    elif resp == "q":
                        print("\nRevisão interrompida.")
                        return correcoes_aprovadas, ensinamentos
                    else:
                        print(cinza("   Digite e, p ou q."))
            else:
                while True:
                    resp = input("\n   [a]plicar  [e]ditar  [p]ular  [q]sair → ").strip().lower()
                    if resp == "a":
                        correcoes_aprovadas.append((trecho, correcao))
                        print(verde("   ✅ Aprovado"))
                        # Reforço positivo: o agente acertou — sinal valioso no ledger
                        ledger.registrar_decisao(achado, "aplicado", **_led)
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
                            ledger.registrar_decisao(achado, "editado",
                                                     versao_usuario=novo, motivo=motivo, **_led)
                        else:
                            print(cinza("   Pulado (texto vazio)"))
                            ensinamentos.append({**achado, "_tipo_decisao": "pular", "_motivo": ""})
                            ledger.registrar_decisao(achado, "pulado", **_led)
                        break
                    elif resp == "p":
                        motivo = input(cinza("   Motivo (opcional, Enter pra pular): ")).strip()
                        ensinamentos.append({**achado, "_tipo_decisao": "pular", "_motivo": motivo})
                        ledger.registrar_decisao(achado, "pulado", motivo=motivo, **_led)
                        print(cinza("   Pulado"))
                        break
                    elif resp == "q":
                        print("\nRevisão interrompida.")
                        return correcoes_aprovadas, ensinamentos
                    else:
                        print(cinza("   Digite a, e, p ou q."))

    # ── Sugestões globais (sem trecho) — apenas informativas ─────────────────
    globais = [a for a in achados if not (a.get("trecho_original") or "").strip()]
    if globais:
        print(f"\n{'─' * 62}")
        print(cinza("💡 Sugestões gerais (sem âncora no texto — apenas para leitura):"))
        for a in globais:
            camada = a.get("camada", "")
            conf   = a.get("confianca", 0)
            print(f"\n   [{camada} · {conf}%]  {(a.get('correcao') or '').strip()}")
            print(cinza(f"   Por quê: {(a.get('porque') or '').strip()}"))
        print()

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
            n = aplicar_correcoes(url, correcoes_aprovadas)["aplicadas"]
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
            [sys.executable, "revisar.py", "--gdocs", args.gdocs, "--modo", "relatorio"],
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
