#!/usr/bin/env python3
"""
Writeback no Google Docs — Viral Media Labs

Pega os achados estruturados de uma revisão (o .json salvo em relatorios/) e os
escreve no Google Doc, ancorados no TRECHO EXATO, para você aplicar com facilidade.

Como a API do Google NÃO permite criar "sugestões" (controle de alterações)
programaticamente, a entrega é segura e no lugar certo:
  - cria uma CÓPIA do documento (o original nunca é tocado);
  - insere cada correção como uma NOTA inline logo após o trecho:
      【REVISOR · camada · severidade · conf%】 trocar por: "..." — porquê
  - achados globais (sem trecho) vão para uma seção no fim.

Uso:
    python3 aplicar_gdocs.py <link_do_doc> <caminho_do_json>
    python3 aplicar_gdocs.py <link_do_doc> relatorios/revisao_AAAAMMDD_HHMMSS.json

Você abre a cópia, lê as notas no lugar exato e aceita/ajusta cada uma.
"""

import re
import sys
import json
from pathlib import Path

from terminal import patch_stdout
patch_stdout()

from google_docs import extrair_doc_id, autenticar

# Escrita exige escopos amplos e um token próprio (não mexe no token de leitura).
SCOPES_WRITE = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]
TOKEN_WRITE = Path(__file__).parent / "credentials" / "token_write.pickle"

MARCADOR = "【REVISOR"  # prefixo das notas, fácil de localizar/remover depois


# ─── Mapa de texto → índices do documento ────────────────────────────────────

def construir_mapa(doc) -> tuple[str, list[int]]:
    """Concatena o texto do doc e guarda, para cada caractere, seu índice real
    no documento (necessário para inserir no ponto exato via batchUpdate)."""
    plain = []
    indices = []
    for elemento in doc.get("body", {}).get("content", []):
        paragrafo = elemento.get("paragraph")
        if not paragrafo:
            continue
        for run in paragrafo.get("elements", []):
            tr = run.get("textRun")
            if not tr:
                continue
            conteudo = tr.get("content", "")
            inicio = run.get("startIndex", 0)
            for i, ch in enumerate(conteudo):
                plain.append(ch)
                indices.append(inicio + i)
    return "".join(plain), indices


def fim_do_documento(doc) -> int:
    """Índice de inserção no final do corpo."""
    fim = 1
    for elemento in doc.get("body", {}).get("content", []):
        if "endIndex" in elemento:
            fim = elemento["endIndex"]
    return max(1, fim - 1)


def localizar(plain: str, indices: list[int], trecho: str):
    """Acha o trecho no texto (tolerante a diferenças de espaço/quebra de linha).
    Retorna o índice do documento logo APÓS o trecho, ou None."""
    t = (trecho or "").strip()
    if not t:
        return None
    pos = plain.find(t)
    if pos != -1:
        return indices[pos + len(t) - 1] + 1
    # Tolerante a espaços/quebras: casa os tokens com \s+ entre eles.
    tokens = [re.escape(tok) for tok in t.split()]
    if not tokens:
        return None
    m = re.search(r"\s+".join(tokens), plain)
    if m:
        return indices[m.end() - 1] + 1
    return None


# ─── Texto das notas ─────────────────────────────────────────────────────────

def texto_nota(a: dict) -> str:
    camadas = "+".join(dict.fromkeys(a.get("camadas", [a.get("camada", "geral")])))
    tag = f"{MARCADOR} · {camadas} · {a.get('severidade')} · {a.get('confianca')}%】"
    correcao = (a.get("correcao") or "").strip()
    porque = (a.get("porque") or "").strip()
    return f"  {tag} trocar por: «{correcao}» — {porque}"


def texto_nota_global(a: dict) -> str:
    camadas = "+".join(dict.fromkeys(a.get("camadas", [a.get("camada", "geral")])))
    return (f"• [{camadas} · {a.get('severidade')} · {a.get('confianca')}%] "
            f"{(a.get('correcao') or '').strip()} — {(a.get('porque') or '').strip()}")


# ─── Aplicação ───────────────────────────────────────────────────────────────

def aplicar(url: str, json_path: str):
    from googleapiclient.discovery import build

    dados = json.loads(Path(json_path).read_text(encoding="utf-8"))

    # Reúne todos os achados de todos os roteiros do documento.
    achados = []
    for roteiro in dados:
        cons = roteiro.get("consolidado", {})
        achados.extend(cons.get("achados", []))
    if not achados:
        print("Nenhum achado no JSON — nada a aplicar.")
        return

    doc_id = extrair_doc_id(url)
    creds = autenticar(scopes=SCOPES_WRITE, token_path=TOKEN_WRITE)
    docs = build("docs", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    # 1. Copia o documento (original intocado)
    original = docs.documents().get(documentId=doc_id).execute()
    titulo = original.get("title", "Documento")
    copia = drive.files().copy(
        fileId=doc_id, body={"name": f"[REVISADO] {titulo}"}
    ).execute()
    copia_id = copia["id"]
    print(f"📄 Cópia criada: [REVISADO] {titulo}")

    # 2. Lê a cópia e monta o mapa de índices
    doc = docs.documents().get(documentId=copia_id).execute()
    plain, indices = construir_mapa(doc)

    # 3. Monta as inserções (notas ancoradas) e separa os achados globais
    insercoes = []       # (indice_doc, texto)
    globais = []
    nao_localizados = []
    for a in achados:
        trecho = (a.get("trecho_original") or "").strip()
        if not trecho:
            globais.append(a)
            continue
        idx = localizar(plain, indices, trecho)
        if idx is None:
            nao_localizados.append(a)
            globais.append(a)  # vira nota global para não se perder
            continue
        insercoes.append((idx, texto_nota(a)))

    # Notas globais no fim do documento
    if globais:
        bloco = ["", "", "──────────  NOTAS GERAIS DO REVISOR  ──────────"]
        bloco += [texto_nota_global(a) for a in globais]
        insercoes.append((fim_do_documento(doc), "\n".join(bloco)))

    # 4. Inserções da maior para a menor (índices baixos não se deslocam)
    insercoes.sort(key=lambda x: x[0], reverse=True)
    requests = [
        {"insertText": {"location": {"index": idx}, "text": "\n" + texto}}
        for idx, texto in insercoes
    ]
    if requests:
        docs.documents().batchUpdate(
            documentId=copia_id, body={"requests": requests}
        ).execute()

    ancoradas = len(insercoes) - (1 if globais else 0)
    link = f"https://docs.google.com/document/d/{copia_id}/edit"
    print(f"✅ {ancoradas} nota(s) ancorada(s) no trecho exato"
          + (f" · {len(globais)} nota(s) geral(is) no fim" if globais else ""))
    if nao_localizados:
        print(f"   ℹ️  {len(nao_localizados)} trecho(s) não localizado(s) no doc "
              f"(viraram notas gerais).")
    print(f"\n🔗 Abra a cópia revisada:\n   {link}")
    print(f"\n   Procure por “{MARCADOR}” para saltar de nota em nota.")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 aplicar_gdocs.py <link_do_doc> <caminho_do_json>")
        sys.exit(1)
    aplicar(sys.argv[1], sys.argv[2])
