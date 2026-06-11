#!/usr/bin/env python3
"""
Revisor de Roteiros — Viral Media Labs
Ponto de entrada do sistema multi-agente.

Uso:
    python revisar.py
    python revisar.py --arquivo roteiros/meu_doc.txt
    python revisar.py --roteiro "Cole o roteiro aqui..."
    python revisar.py --gdocs "https://docs.google.com/document/d/SEU_ID/edit"
"""

import argparse
import asyncio
import re
import sys
import os
from datetime import datetime
from pathlib import Path

from terminal import patch_stdout
patch_stdout()

# Adiciona o diretório raiz ao path
sys.path.insert(0, str(Path(__file__).parent))

from agentes.ortografia import AgenteOrtografia
from agentes.clareza import AgenteClareza
from agentes.coerencia import AgenteCoerencia
from agentes.checklist import AgenteChecklist
from agentes.storytelling import AgenteStorytelling
from agentes.factcheck import AgenteFactCheck, tem_fato_verificavel
from agentes.hook import AgenteHook
from agentes.viral import AgenteViral
from agentes.cta import AgenteCTA
from agentes.contexto import AgenteContexto
from agentes.consolidador import AgenteConsolidador


# ─── Separação de roteiros ──────────────────────────────────────────────────

def separar_roteiros(texto: str):
    """
    Detecta automaticamente múltiplos roteiros no texto.
    Suporta dois formatos:
      - Separador explícito: linha com '---', '===', 'ROTEIRO 1', 'Roteiro 2:', etc.
      - Bloco único: retorna como roteiro 1
    """
    import re

    # Padrões de separação entre roteiros
    padroes = [
        r'(?m)^[-=]{3,}\s*$',                           # --- ou ===
        r'(?m)^ROTEIRO\s*\d+[\s:.-]*$',                 # ROTEIRO 1
        r'(?m)^Roteiro\s*\d+[\s:.-]*$',                 # Roteiro 1:
        r'(?m)^#{1,3}\s*Roteiro\s*\d+',                 # ## Roteiro 3
        r'(?m)^\*{3,}\s*$',                             # ***
    ]

    for padrao in padroes:
        partes = re.split(padrao, texto)
        partes = [p.strip() for p in partes if p.strip()]
        if len(partes) > 1:
            roteiros = []
            for i, parte in enumerate(partes, 1):
                # Extrai título da primeira linha não vazia
                linhas = [l for l in parte.splitlines() if l.strip()]
                titulo = linhas[0][:80] if linhas else f"Roteiro {i}"
                roteiros.append({"numero": i, "titulo": titulo, "texto": parte})
            return roteiros

    # Nenhum separador encontrado — trata como roteiro único
    linhas = [l for l in texto.splitlines() if l.strip()]
    titulo = linhas[0][:80] if linhas else "Roteiro"
    return [{"numero": 1, "titulo": titulo, "texto": texto}]


# ─── Processamento de um roteiro ────────────────────────────────────────────

def detectar_cliente(texto: str):
    """Pega o nome do cliente/criador no documento original (quem vai performar o
    roteiro e aparecer no comando). Procura rótulos comuns. Retorna None se não achar."""
    import re
    rotulos = r"(cliente|canal|criador|criadora|apresentador|apresentadora|locutor|locutora|perfil|voz|talento)"
    for linha in texto.splitlines():
        m = re.match(rf"^\s*{rotulos}\s*[:\-–—]\s*(.+)$", linha, re.IGNORECASE)
        if m:
            nome = m.group(2).strip().lstrip("@").split("|")[0].split("(")[0].strip()
            if nome:
                return nome[:60]
    return None


async def processar_roteiro(roteiro, pdfs, verbose=True, cliente=None, verificar_web=False):
    """Roda os agentes em paralelo para um roteiro e depois consolida."""

    numero = roteiro["numero"]
    titulo = roteiro["titulo"]
    texto = roteiro["texto"]
    if cliente is None:
        cliente = detectar_cliente(texto)

    # A headline (heading do doc) é separada do corpo. Mostramos ela aos agentes
    # marcada como HEADLINE, para o checklist avaliá-la (≤9 palavras, MGC) em vez de
    # acusar "ausente". O corpo (texto) segue sendo a base para ancorar as correções.
    headline = roteiro.get("headline")
    texto_agentes = f"HEADLINE: {headline}\n\n{texto}" if headline else texto

    # ── Fase 0: contexto narrativo (Haiku, rápido) ────────────────────────────
    if verbose:
        print("  🔍 Extraindo contexto narrativo...")
    try:
        from agentes.contexto import formatar_contexto
        contexto = await AgenteContexto().analisar_contexto(texto_agentes)
        contexto_str = formatar_contexto(contexto)
    except Exception:
        contexto, contexto_str = {}, ""

    # O contexto é injetado como cabeçalho para todos os agentes lerem.
    if contexto_str:
        texto_com_contexto = (
            "[CONTEXTO NARRATIVO — extraído automaticamente antes da revisão]\n"
            f"{contexto_str}\n"
            "[/CONTEXTO NARRATIVO]\n\n"
            f"{texto_agentes}"
        )
    else:
        texto_com_contexto = texto_agentes

    # Agentes na ordem em que aparecem no painel
    agentes = {
        "ortografia":   AgenteOrtografia(),
        "clareza":      AgenteClareza(),
        # Coerência usa só o destilado MECANISMOS_EMOCIONAIS (interno ao agente) —
        # a íntegra do playbook (~14k tokens) fica com o storytelling, que é quem julga.
        "coerencia":    AgenteCoerencia(""),
        "checklist":    AgenteChecklist(pdfs.get("checklist", "")),
        "storytelling": AgenteStorytelling(pdfs.get("storytelling", "")),
        "factcheck":    AgenteFactCheck(verificar_web=verificar_web),
        "hook":         AgenteHook(pdfs.get("hooks", "")),
        "viral":        AgenteViral(),
        "cta":          AgenteCTA(pdfs.get("cta", ""), cliente=cliente or ""),
    }

    # Fact-check só roda se houver algo verificável (nº, data, %, valor) — economiza chamada
    if "factcheck" in agentes and not tem_fato_verificavel(texto):
        del agentes["factcheck"]
        if verbose:
            print("  ⏭️  fact-check pulado (sem fato verificável neste roteiro)")

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Roteiro {numero}: {titulo}")
        print(f"{'='*60}")
        if cliente:
            print(f"  Cliente/criador: {cliente}")
        print(f"  Rodando {len(agentes)} agentes em paralelo...")

    # Roda em paralelo
    resultados = await asyncio.gather(
        *(ag.analisar(texto_com_contexto) for ag in agentes.values()),
        return_exceptions=True,
    )

    # Mapeia resultados (trata exceções)
    analises = {}
    for nome, resultado in zip(agentes.keys(), resultados):
        if isinstance(resultado, Exception):
            analises[nome] = f"ERRO: {str(resultado)}"
            if verbose:
                print(f"  ⚠️  Agente {nome} falhou: {resultado}")
        else:
            n = len(resultado.get("achados", [])) if isinstance(resultado, dict) else 0
            analises[nome] = resultado
            if verbose:
                print(f"  ✅  {nome}: {n} achado(s)")

    # Consolida
    if verbose:
        print(f"  📋 Consolidando relatório final...")

    consolidador = AgenteConsolidador()
    consolidado = await consolidador.consolidar(
        roteiro=texto_com_contexto,
        titulo=titulo,
        numero=numero,
        analises=analises,
    )

    return {
        "numero": numero,
        "titulo": titulo,
        "texto": texto,
        "cliente": cliente,
        "contexto": contexto,
        "analises": analises,
        "consolidado": consolidado,
        "relatorio": consolidado["relatorio"],
    }


# ─── Entrada de texto ────────────────────────────────────────────────────────

def coletar_texto(args):
    """
    Coleta os roteiros de diferentes fontes.
    Retorna (texto, None) para fontes de texto puro,
    ou (None, lista_de_roteiros) para Google Docs.
    """

    # Google Docs — retorna lista de roteiros diretamente
    if hasattr(args, "gdocs") and args.gdocs:
        from google_docs import carregar_roteiros_do_gdoc
        roteiros = carregar_roteiros_do_gdoc(args.gdocs)
        return None, roteiros

    if args.roteiro:
        return args.roteiro, None

    if args.arquivo:
        caminho = Path(args.arquivo)
        if not caminho.exists():
            print(f"❌ Arquivo não encontrado: {args.arquivo}")
            sys.exit(1)
        return caminho.read_text(encoding="utf-8"), None

    # Modo interativo — lê do stdin
    print("\n" + "━"*60)
    print("  REVISOR DE ROTEIROS — Viral Media Labs")
    print("━"*60)
    print("\nCole o(s) roteiro(s) abaixo e pressione ENTER duas vezes")
    print("seguido de Ctrl+D (Mac/Linux) para iniciar a revisão.\n")
    print("Dica: para múltiplos roteiros, separe com --- entre eles.")
    print("─"*60)

    linhas = []
    try:
        for linha in sys.stdin:
            linhas.append(linha)
    except KeyboardInterrupt:
        print("\n\nCancelado.")
        sys.exit(0)

    return "".join(linhas).strip(), None


# ─── Carregamento de PDFs ────────────────────────────────────────────────────

def carregar_pdfs() -> dict:
    """
    Carrega a base de conhecimento (playbooks) de conhecimento/*.md — markdown limpo,
    sem truncar e sem re-extrair PDF a cada execução. Cai para extração de PDF se algum
    .md faltar.
    Retorna dicionário {checklist, storytelling, hooks, cta}.
    """
    raiz = Path(__file__).parent
    pasta_md = raiz / "conhecimento"
    fontes_md = {
        "checklist":    "checklist.md",
        "storytelling": "storytelling.md",
        "hooks":        "hooks.md",
        "cta":          "comandos.md",
    }
    base = {}
    for chave, arquivo in fontes_md.items():
        caminho = pasta_md / arquivo
        if caminho.exists():
            base[chave] = caminho.read_text(encoding="utf-8").strip()
            print(f"  📄 conhecimento/{arquivo} ({len(base[chave])} chars)")

    # Fallback: extrai do PDF qualquer chave que não tenha markdown
    faltando = [k for k in fontes_md if k not in base]
    if faltando:
        base.update(_extrair_pdfs_fallback(faltando))
    return base


def _extrair_pdfs_fallback(chaves: list) -> dict:
    """Extrai do PDF as chaves sem markdown (compatibilidade)."""
    pasta_pdfs = Path(__file__).parent / "pdfs"
    nomes = {
        "checklist":    "Checklist Codex V1.pdf",
        "storytelling": "Playbook Storytelling.pdf",
        "hooks":        "Playbook Hooks.pdf",
        "cta":          "Playbook Comandos.pdf",
    }
    out = {}
    try:
        import pdfplumber
    except ImportError:
        return out
    for chave in chaves:
        caminho = pasta_pdfs / nomes.get(chave, "")
        if caminho.exists():
            try:
                with pdfplumber.open(caminho) as pdf:
                    out[chave] = "\n\n".join(p.extract_text() or "" for p in pdf.pages).strip()
                print(f"  📄 {nomes[chave]} (PDF, fallback)")
            except Exception as e:
                print(f"  ⚠️  Erro ao ler {nomes[chave]}: {e}")
    return out


# ─── Salvar relatório ────────────────────────────────────────────────────────

def salvar_relatorio(resultados: list[dict], pasta_saida: Path):
    """Salva o relatório .txt e o JSON estruturado dos achados, ambos com timestamp.
    Retorna (arquivo_txt, arquivo_json)."""
    import json

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo = pasta_saida / f"revisao_{timestamp}.txt"
    arquivo_json = pasta_saida / f"revisao_{timestamp}.json"

    linhas = [
        "═"*70,
        f"  RELATÓRIO DE REVISÃO — Viral Media Labs",
        f"  Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}",
        f"  Total de roteiros revisados: {len(resultados)}",
        "═"*70,
        "",
    ]
    for resultado in resultados:
        linhas.append(resultado["relatorio"])
        linhas.append("")
    arquivo.write_text("\n".join(linhas), encoding="utf-8")

    # JSON estruturado — consumido pelo writeback do Google Docs e pelo feedback
    payload = _payload_json(resultados)
    arquivo_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return arquivo, arquivo_json


def _payload_json(resultados: list[dict]) -> list[dict]:
    return [
        {
            "numero": r["numero"],
            "titulo": r["titulo"],
            "texto": r.get("texto", ""),
            "cliente": r.get("cliente"),
            "contexto": r.get("contexto") or {},
            "consolidado": r["consolidado"],
        }
        for r in resultados
    ]


# ─── Menu de entrada ─────────────────────────────────────────────────────────

def mostrar_menu_modo(roteiros, url_gdocs):
    """Mostra sumário do documento carregado e pergunta o tipo de revisão.
    Retorna 'relatorio', 'dinamica' ou 'tabela'."""
    print()
    print("═" * 62)
    n = len(roteiros)
    print(f"  {n} roteiro{'s' if n > 1 else ''} para revisar:")
    for r in roteiros:
        print(f"    {r['numero']}. {r['titulo'][:56]}")
    print("═" * 62)
    print()
    print("  Que tipo de revisão?")
    print()
    print("   [1] Relatório       — relatório em lista no Google Docs")
    print("   [2] Dinâmica        — parágrafo a parágrafo, 1 roteiro por vez")
    print("   [3] Tabela Interativa — interface visual no browser")
    print()
    while True:
        resp = input("  → ").strip()
        if resp == "1":
            return "relatorio"
        elif resp == "2":
            return "dinamica"
        elif resp == "3":
            return "tabela"
        else:
            print("  Digite 1, 2 ou 3.")


# ─── Modo Relatório ──────────────────────────────────────────────────────────

async def modo_relatorio(roteiros, pdfs, args):
    """Processa todos os roteiros e gera o relatório em lista (Google Docs + JSON)."""
    import json as _json

    verbose = not args.silencioso
    resultados = []
    for roteiro in roteiros:
        cliente = args.cliente or roteiro.get("cliente") or detectar_cliente(roteiro["texto"])
        resultado = await processar_roteiro(roteiro, pdfs, verbose=verbose, cliente=cliente,
                                            verificar_web=args.verificar_web)
        resultados.append(resultado)
        print(f"\n{'─'*60}")
        print(resultado["relatorio"])

    pasta_relatorios = Path(__file__).parent / "relatorios"
    pasta_relatorios.mkdir(exist_ok=True)
    arquivo_txt, arquivo_json = salvar_relatorio(resultados, pasta_relatorios)

    print(f"\n\n✅ Revisão concluída!")
    print(f"📁 Relatório:  {arquivo_txt}")
    print(f"🧩 Achados (JSON): {arquivo_json}")

    print(f"\n📋 Gerando relatório de correções em lista...")
    try:
        from relatorio_gdocs import gerar_doc_lista
        link = gerar_doc_lista(arquivo_json)
        print(f"   ✅ Google Doc: {link}")
    except Exception as e:
        from relatorio_correcoes import gerar_relatorio
        saida = gerar_relatorio(arquivo_json)
        print(f"   ⚠️  Google Docs indisponível ({e.__class__.__name__}). Salvo localmente:")
        print(f"   📄 {saida}")


# ─── Modo Dinâmica ───────────────────────────────────────────────────────────

async def modo_dinamica(roteiros, pdfs, args, url_gdocs):
    """9 agentes → revisão interativa → aplica no doc → próximo roteiro.

    Só chama os agentes para 1 roteiro por vez (economia de tokens).
    O JSON é salvo de forma incremental após cada roteiro processado.
    """
    import json as _json
    from revisar_dinamico import revisar_roteiro, loop_aprendizado

    pasta_relatorios = Path(__file__).parent / "relatorios"
    pasta_relatorios.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_json = pasta_relatorios / f"revisao_{timestamp}.json"

    todos_resultados = []
    todos_ensinamentos = []

    for i, roteiro in enumerate(roteiros):
        print(f"\n{'═'*62}")
        print(f"  [{i + 1}/{len(roteiros)}] Analisando: {roteiro['titulo'][:50]}")
        print(f"  Rodando 9 agentes em paralelo... (1-2 min)")
        print(f"{'═'*62}")

        cliente = args.cliente or roteiro.get("cliente") or detectar_cliente(roteiro["texto"])
        resultado = await processar_roteiro(roteiro, pdfs, verbose=True, cliente=cliente,
                                            verificar_web=args.verificar_web)
        todos_resultados.append(resultado)

        # Salva JSON incremental — dados disponíveis mesmo se o usuário interromper
        arquivo_json.write_text(
            _json.dumps(_payload_json(todos_resultados), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Revisão interativa (inclui a pergunta de gravação no Google Doc ao final)
        _, ensinamentos = revisar_roteiro(resultado, url_gdocs)
        todos_ensinamentos.extend(ensinamentos)

        # Pergunta sobre próximo roteiro (exceto no último)
        if i + 1 < len(roteiros):
            proximo_titulo = roteiros[i + 1]["titulo"][:48]
            resp = input(
                f"\n▶ Avançar para [{i + 2}/{len(roteiros)}] «{proximo_titulo}»? [s/n] → "
            ).strip().lower()
            if resp != "s":
                break

    loop_aprendizado(todos_ensinamentos)

    print(f"\n🧩 JSON salvo: {arquivo_json}")
    print("\n🎉 Revisão dinâmica concluída.")


# ─── Modo Tabela Interativa ──────────────────────────────────────────────────

async def modo_tabela(roteiros, pdfs, args, url_gdocs):
    """9 agentes → tabela no browser → próximo roteiro (1 por vez como Dinâmica)."""
    import json as _json

    try:
        import flask  # noqa — verifica disponibilidade
    except ImportError:
        print("\n❌ Flask não instalado. Execute:\n   pip install flask")
        print("   Depois rode novamente e escolha [3] Tabela Interativa.")
        return

    from tabela_interativa import (
        transformar_roteiro, TabelaServer,
        aplicar_decisoes_no_payload, decisoes_para_ensinamentos,
    )

    pasta_relatorios = Path(__file__).parent / "relatorios"
    pasta_relatorios.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    arquivo_json = pasta_relatorios / f"revisao_{timestamp}.json"

    todos_resultados = []
    server = TabelaServer(url_gdocs=url_gdocs or "", porta=_porta_livre(),
                          json_path=arquivo_json)
    loop = asyncio.get_event_loop()
    next_task = None  # análise do próximo roteiro rodando em background

    for i, roteiro in enumerate(roteiros):
        if next_task is not None:
            # resultado já calculado em background — só aguarda a conclusão (geralmente instantâneo)
            print(f"\n{'═'*62}")
            print(f"  [{i+1}/{len(roteiros)}] Carregando: {roteiro['titulo'][:50]}")
            print(f"  (análise em background — sem espera...)")
            print(f"{'═'*62}")
            try:
                resultado = await next_task
            except Exception as e:
                print(f"  ⚠️  Prefetch falhou ({e}), recalculando...")
                cliente = args.cliente or roteiro.get("cliente") or detectar_cliente(roteiro["texto"])
                resultado = await processar_roteiro(roteiro, pdfs, verbose=True,
                                                    cliente=cliente,
                                                    verificar_web=args.verificar_web)
            next_task = None
        else:
            print(f"\n{'═'*62}")
            print(f"  [{i+1}/{len(roteiros)}] Analisando: {roteiro['titulo'][:50]}")
            print(f"  Rodando 9 agentes em paralelo...")
            print(f"{'═'*62}")
            cliente = args.cliente or roteiro.get("cliente") or detectar_cliente(roteiro["texto"])
            resultado = await processar_roteiro(roteiro, pdfs, verbose=True, cliente=cliente,
                                                verificar_web=args.verificar_web)

        todos_resultados.append(resultado)

        # Carimba as decisões já tomadas antes de regravar — a escrita incremental
        # não pode apagar o que /api/decisao já persistiu para roteiros anteriores.
        payload = aplicar_decisoes_no_payload(
            _payload_json(todos_resultados), server.decisoes, server.motivos
        )
        arquivo_json.write_text(
            _json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        meta = {
            "total": len(roteiros),
            "atual": i + 1,
            "proximo_titulo": roteiros[i + 1]["titulo"] if i + 1 < len(roteiros) else None,
        }
        dados = transformar_roteiro(
            _payload_json([resultado])[0],
            url_gdocs=url_gdocs or "",
            meta=meta,
        )

        if i == 0:
            server.iniciar(dados)
        else:
            server.avancar(dados)

        # Dispara a análise do próximo roteiro em background enquanto o usuário revisa este
        if i + 1 < len(roteiros):
            proximo = roteiros[i + 1]
            proximo_cliente = args.cliente or proximo.get("cliente") or detectar_cliente(proximo["texto"])
            print(f"   ⚡ Pré-analisando próximo roteiro em background...")
            next_task = asyncio.create_task(
                processar_roteiro(proximo, pdfs, verbose=False,
                                  cliente=proximo_cliente,
                                  verificar_web=args.verificar_web)
            )

        # run_in_executor libera o event loop para rodar next_task enquanto aguarda o usuário
        await loop.run_in_executor(None, server.esperar_decisao)

    server.finalizar()
    print(f"\n🧩 JSON salvo: {arquivo_json}")
    print("\n🎉 Tabela Interativa concluída.")

    # Decisões da tabela alimentam o loop de aprendizado (igual ao modo dinâmica)
    from revisar_dinamico import loop_aprendizado
    ensinamentos = decisoes_para_ensinamentos(
        _payload_json(todos_resultados), server.decisoes, server.motivos
    )
    if ensinamentos:
        loop_aprendizado(ensinamentos)


def _porta_livre(inicio: int = 7432) -> int:
    import socket
    for p in range(inicio, inicio + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return inicio


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Revisor multi-agente de roteiros — Viral Media Labs"
    )
    parser.add_argument("--arquivo",   "-a", help="Caminho para arquivo .txt com roteiros")
    parser.add_argument("--roteiro",   "-r", help="Roteiro como string direta")
    parser.add_argument("--gdocs",     "-g", help="Link do Google Docs com os roteiros")
    parser.add_argument("--cliente",   "-c", help="Nome do cliente/criador que vai performar (aparece no comando). Se omitido, tenta detectar no documento.")
    parser.add_argument("--verificar-web", action="store_true", help="Fact-check confere as afirmações com busca real na web (mais lento e com custo).")
    parser.add_argument("--silencioso","-s", action="store_true", help="Menos output no terminal")
    parser.add_argument("--modo",      "-m", choices=["relatorio", "dinamica", "tabela"],
                        help="Pula o menu e vai direto para o modo especificado.")
    args = parser.parse_args()

    # Carrega PDFs
    print("\n📚 Carregando base de conhecimento...")
    pdfs = carregar_pdfs()

    # Coleta texto ou roteiros já separados (Google Docs)
    texto, roteiros_gdoc = coletar_texto(args)

    if roteiros_gdoc is not None:
        roteiros = roteiros_gdoc
        print(f"\n🎬 {len(roteiros)} roteiro(s) carregado(s) do Google Docs")
    elif texto:
        roteiros = separar_roteiros(texto)
        print(f"\n🎬 {len(roteiros)} roteiro(s) detectado(s)")
    else:
        print("❌ Nenhum texto fornecido.")
        sys.exit(1)

    # Pula roteiros já marcados como revisados
    marcados = [r for r in roteiros if re.search(r"revisad[oa]", r.get("titulo", ""), re.IGNORECASE)]
    if marcados:
        roteiros = [r for r in roteiros if r not in marcados]
        print(f"⏭️  {len(marcados)} roteiro(s) marcado(s) '(revisado)' — pulando.")
    if not roteiros:
        print("✅ Todos os roteiros já estão marcados como revisados. Nada a revisar.")
        return

    # Modo: usa --modo se fornecido, senão exibe o menu interativo
    modo = args.modo or mostrar_menu_modo(roteiros, args.gdocs)

    if modo == "relatorio":
        await modo_relatorio(roteiros, pdfs, args)

    elif modo == "dinamica":
        await modo_dinamica(roteiros, pdfs, args, args.gdocs)

    elif modo == "tabela":
        await modo_tabela(roteiros, pdfs, args, args.gdocs)


if __name__ == "__main__":
    asyncio.run(main())
