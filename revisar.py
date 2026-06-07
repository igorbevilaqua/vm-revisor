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

    # Agentes na ordem em que aparecem no painel
    agentes = {
        "ortografia":   AgenteOrtografia(),
        "clareza":      AgenteClareza(),
        "coerencia":    AgenteCoerencia(pdfs.get("storytelling", "")),
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
        *(ag.analisar(texto_agentes) for ag in agentes.values()),
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
        roteiro=texto_agentes,
        titulo=titulo,
        numero=numero,
        analises=analises,
    )

    return {
        "numero": numero,
        "titulo": titulo,
        "texto": texto,
        "cliente": cliente,
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
    payload = [
        {
            "numero": r["numero"],
            "titulo": r["titulo"],
            "texto": r.get("texto", ""),
            "cliente": r.get("cliente"),
            "consolidado": r["consolidado"],
        }
        for r in resultados
    ]
    arquivo_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return arquivo, arquivo_json


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
    args = parser.parse_args()

    verbose = not args.silencioso

    # Carrega PDFs
    print("\n📚 Carregando base de conhecimento...")
    pdfs = carregar_pdfs()

    # Coleta texto ou roteiros já separados (Google Docs)
    texto, roteiros_gdoc = coletar_texto(args)

    if roteiros_gdoc is not None:
        # Veio do Google Docs — já separado
        roteiros = roteiros_gdoc
        print(f"\n🎬 {len(roteiros)} roteiro(s) carregado(s) do Google Docs")
    elif texto:
        # Veio de texto — separa aqui
        roteiros = separar_roteiros(texto)
        print(f"\n🎬 {len(roteiros)} roteiro(s) detectado(s)")
    else:
        print("❌ Nenhum texto fornecido.")
        sys.exit(1)

    # Pula roteiros já revisados (marcados com "(revisado)" no título, após a headline)
    marcados = [r for r in roteiros if re.search(r"revisad[oa]", r.get("titulo", ""), re.IGNORECASE)]
    if marcados:
        roteiros = [r for r in roteiros if r not in marcados]
        print(f"⏭️  {len(marcados)} roteiro(s) marcado(s) '(revisado)' — pulando.")
    if not roteiros:
        print("✅ Todos os roteiros já estão marcados como revisados. Nada a revisar.")
        return

    # Processa cada roteiro. Prioridade do cliente:
    # --cliente  >  título do Google Doc (roteiro["cliente"])  >  rótulo no texto
    resultados = []
    for roteiro in roteiros:
        cliente = args.cliente or roteiro.get("cliente") or detectar_cliente(roteiro["texto"])
        resultado = await processar_roteiro(roteiro, pdfs, verbose=verbose, cliente=cliente,
                                            verificar_web=args.verificar_web)
        resultados.append(resultado)

        # Mostra resumo inline
        print(f"\n{'─'*60}")
        print(resultado["relatorio"])

    # Salva relatório
    pasta_relatorios = Path(__file__).parent / "relatorios"
    pasta_relatorios.mkdir(exist_ok=True)
    arquivo_txt, arquivo_json = salvar_relatorio(resultados, pasta_relatorios)

    print(f"\n\n✅ Revisão concluída!")
    print(f"📁 Relatório:  {arquivo_txt}")
    print(f"🧩 Achados (JSON): {arquivo_json}")

    # Relatório de correções em lista — tenta Google Docs, cai para .md local
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


if __name__ == "__main__":
    asyncio.run(main())
