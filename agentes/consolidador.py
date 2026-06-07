"""
Agente Consolidador — Final
Recebe os ACHADOS ESTRUTURADOS de todos os agentes e produz o resultado final.

Diferente dos agentes, o consolidador é MAJORITARIAMENTE DETERMINÍSTICO:
  - deduplica e ordena os achados (Python, não LLM);
  - calcula o veredicto POR REGRA — só ERRO OBJETIVO de alta confiança bloqueia;
  - monta o painel e o relatório.
Uma única chamada à LLM gera apenas a síntese executiva (prose), ancorada nos dados.

Retorna um dict estruturado (consumido pelo revisar.py e pelo writeback do Google Docs).
"""

import asyncio
from datetime import datetime

from agentes import AgenteBase


# Confiança mínima para um erro objetivo ser tratado como bloqueante.
CONFIANCA_BLOQUEIO = 70

# Ordem de severidade para ordenação (maior = mais urgente).
PESO_SEVERIDADE = {"erro": 3, "aviso": 2, "sugestao": 1}

NOMES_CAMADA = {
    "ortografia":   "Ortografia/Gramática",
    "clareza":      "Clareza/Ritmo",
    "coerencia":    "Coerência/Continuidade",
    "checklist":    "Checklist",
    "storytelling": "Storytelling",
    "factcheck":    "Fact-Check",
    "hook":         "Hook",
    "cta":          "CTA",
    "viral":        "Potencial Viral",
}

# Ordem de exibição do painel.
ORDEM_PAINEL = ["ortografia", "clareza", "coerencia", "checklist", "storytelling",
                "factcheck", "hook", "cta", "viral"]


def _norm(texto: str) -> str:
    return " ".join((texto or "").lower().split())


def _e_bloqueante(achado: dict) -> bool:
    return (
        achado.get("severidade") == "erro"
        and achado.get("natureza") == "objetivo"
        and achado.get("confianca", 0) >= CONFIANCA_BLOQUEIO
    )


def _dominancia(a: dict):
    """Quão 'forte' é um achado — usado para escolher qual motivo exibir ao fundir."""
    return (PESO_SEVERIDADE.get(a.get("severidade"), 0),
            a.get("natureza") == "objetivo",
            a.get("confianca", 0))


def _deduplicar(achados: list[dict]) -> list[dict]:
    """Funde achados que apontam o mesmo trecho. O motivo/correção exibidos são os do
    achado DOMINANTE (o que justifica a severidade), não os do primeiro encontrado."""
    grupos: dict[str, list[dict]] = {}
    soltos: list[dict] = []  # achados globais (sem trecho) não são fundidos por trecho
    for a in achados:
        chave = _norm(a.get("trecho_original", ""))
        if not chave:
            soltos.append(dict(a, camadas=[a.get("camada", "geral")]))
            continue
        grupos.setdefault(chave, []).append(a)

    fundidos: list[dict] = []
    for grupo in grupos.values():
        dominante = max(grupo, key=_dominancia)         # motivo/correção vêm deste
        merged = dict(dominante)
        merged["camadas"] = list(dict.fromkeys(x.get("camada", "geral") for x in grupo))
        # severidade/natureza/confiança = pior caso do grupo (coerente com o dominante)
        merged["severidade"] = max((x.get("severidade") for x in grupo),
                                   key=lambda s: PESO_SEVERIDADE.get(s, 0))
        merged["natureza"] = "objetivo" if any(x.get("natureza") == "objetivo" for x in grupo) else dominante.get("natureza")
        merged["confianca"] = max(x.get("confianca", 0) for x in grupo)
        fundidos.append(merged)
    return fundidos + soltos


def _ordenar(achados: list[dict]) -> list[dict]:
    """Bloqueantes primeiro; depois por severidade, natureza objetiva e confiança."""
    return sorted(
        achados,
        key=lambda a: (
            _e_bloqueante(a),
            PESO_SEVERIDADE.get(a.get("severidade"), 0),
            a.get("natureza") == "objetivo",
            a.get("confianca", 0),
        ),
        reverse=True,
    )


def _veredicto(erros_bloqueantes: int, nota_geral: float) -> str:
    if erros_bloqueantes >= 3 or nota_geral < 5:
        return "REPROVADO"
    if erros_bloqueantes == 0 and nota_geral >= 8:
        return "APROVADO"
    return "APROVADO COM AJUSTES"


SYSTEM_SINTESE = """Você é o editor-chefe da Viral Media Labs. Escreva uma síntese executiva
curta e direta de uma revisão de roteiro, em português do Brasil, com base nos dados
fornecidos. Sem floreio. Você NÃO decide o veredicto (já está calculado) nem inventa
achados novos — apenas sintetiza o que foi encontrado."""


class AgenteConsolidador(AgenteBase):

    CAMADA = "consolidador"
    MAX_TOKENS = 1200
    MODELO = "claude-haiku-4-5"  # só a síntese em prosa usa LLM; o veredicto é determinístico

    def __init__(self):
        super().__init__()

    async def consolidar(self, roteiro: str, titulo: str, numero: int, analises: dict) -> dict:
        data_atual = datetime.now().strftime("%d/%m/%Y")

        # ── Coleta achados e notas de cada camada ────────────────────────────
        todos: list[dict] = []
        notas: dict[str, int] = {}
        resumos: dict[str, str] = {}
        falhas: list[str] = []

        for camada, res in analises.items():
            if not isinstance(res, dict):
                falhas.append(camada)
                continue
            for a in res.get("achados", []):
                a.setdefault("camada", camada)
                todos.append(a)
            if isinstance(res.get("nota"), (int, float)):
                notas[camada] = res["nota"]
            resumos[camada] = res.get("resumo", "")

        achados = _ordenar(_deduplicar(todos))

        bloqueantes = [a for a in achados if _e_bloqueante(a)]
        otimizacoes = [a for a in achados if not _e_bloqueante(a)]

        nota_viral = notas.get("viral", 0)
        notas_para_media = [v for k, v in notas.items() if k != "viral"]
        nota_geral = round(sum(notas_para_media) / len(notas_para_media), 1) if notas_para_media else 0.0

        veredicto = _veredicto(len(bloqueantes), nota_geral)

        # ── Síntese executiva (única chamada à LLM, ancorada nos dados) ──────
        diagnostico = await self._sintetizar(titulo, veredicto, nota_geral, nota_viral,
                                              bloqueantes, otimizacoes, resumos)

        painel = []
        for camada in ORDEM_PAINEL:
            if camada in notas or camada in resumos:
                painel.append({
                    "camada": camada,
                    "nome": NOMES_CAMADA.get(camada, camada),
                    "nota": notas.get(camada),
                })

        resultado = {
            "numero": numero,
            "titulo": titulo,
            "data": data_atual,
            "veredicto": veredicto,
            "nota_geral": nota_geral,
            "nota_viral": nota_viral,
            "painel": painel,
            "bloqueantes": bloqueantes,
            "otimizacoes": otimizacoes,
            "achados": achados,
            "diagnostico": diagnostico,
            "falhas_agentes": falhas,
        }
        resultado["relatorio"] = self._formatar_relatorio(resultado)
        return resultado

    async def _sintetizar(self, titulo, veredicto, nota_geral, nota_viral,
                          bloqueantes, otimizacoes, resumos) -> str:
        def linhas(achados, limite):
            out = []
            for a in achados[:limite]:
                trecho = (a.get("trecho_original") or "[global]")[:80]
                out.append(f"- [{a.get('camada')}/{a.get('severidade')}] {trecho} → {a.get('porque','')[:120]}")
            return "\n".join(out) or "(nenhum)"

        resumos_txt = "\n".join(f"- {NOMES_CAMADA.get(k,k)}: {v}" for k, v in resumos.items() if v)

        user_prompt = f"""ROTEIRO: {titulo}
VEREDICTO (já calculado): {veredicto}
NOTA GERAL: {nota_geral}/10 | POTENCIAL VIRAL: {nota_viral}/10

RESUMOS POR CAMADA:
{resumos_txt}

ERROS BLOQUEANTES (objetivos):
{linhas(bloqueantes, 8)}

PRINCIPAIS OTIMIZAÇÕES:
{linhas(otimizacoes, 8)}

Escreva, em no máximo 5 frases:
1) O que está funcionando bem no roteiro (1-2 frases honestas).
2) O diagnóstico central: o que define o sucesso ou fracasso deste roteiro.
Não repita listas de itens — isso já está no relatório. Seja o editor-chefe falando direto."""

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._chamar_api(SYSTEM_SINTESE, user_prompt)
        )

    # ── Relatório de texto (determinístico) ──────────────────────────────────
    def _formatar_relatorio(self, r: dict) -> str:
        L = []
        L.append("╔══════════════════════════════════════════════════════════════╗")
        L.append("║          RELATÓRIO DE REVISÃO — VIRAL MEDIA LABS             ║")
        L.append("╚══════════════════════════════════════════════════════════════╝")
        L.append(f"\nROTEIRO {r['numero']}: {r['titulo']}")
        L.append(f"DATA: {r['data']}")
        L.append("━" * 64)
        L.append(f"\n▶ VEREDICTO: {r['veredicto']}")
        L.append(f"   Nota geral: {r['nota_geral']}/10   |   Potencial viral: {r['nota_viral']}/10")
        L.append(f"   Erros bloqueantes: {len(r['bloqueantes'])}   |   Otimizações: {len(r['otimizacoes'])}")

        L.append("\n" + "━" * 64)
        L.append("PAINEL DOS AGENTES")
        L.append("━" * 64)
        for p in r["painel"]:
            nota = f"{p['nota']}/10" if p["nota"] is not None else "  —"
            L.append(f"  {p['nome']:<22} {nota:>6}")

        L.append("\n" + "━" * 64)
        L.append("SÍNTESE DO EDITOR-CHEFE")
        L.append("━" * 64)
        L.append(r["diagnostico"].strip())

        L.append("\n" + "━" * 64)
        L.append("CORREÇÕES OBRIGATÓRIAS (erros objetivos — impedem a publicação)")
        L.append("━" * 64)
        if r["bloqueantes"]:
            for i, a in enumerate(r["bloqueantes"], 1):
                L.append(self._fmt_achado(i, a))
        else:
            L.append("  Nenhuma. Nenhum erro objetivo bloqueante encontrado.")

        L.append("\n" + "━" * 64)
        L.append("OTIMIZAÇÕES RECOMENDADAS (opcionais — ordenadas por prioridade)")
        L.append("━" * 64)
        if r["otimizacoes"]:
            for i, a in enumerate(r["otimizacoes"], 1):
                L.append(self._fmt_achado(i, a))
        else:
            L.append("  Nenhuma otimização sugerida.")

        if r["falhas_agentes"]:
            L.append(f"\n⚠️  Agentes que falharam: {', '.join(r['falhas_agentes'])}")

        L.append("\n" + "═" * 64)
        return "\n".join(L)

    def _fmt_achado(self, i: int, a: dict) -> str:
        camadas = "+".join(dict.fromkeys(a.get("camadas", [a.get("camada", "geral")])))
        tag = f"[{camadas} · {a.get('severidade')} · {a.get('natureza')} · {a.get('confianca')}%]"
        linhas = [f"\n{i}. {tag}"]
        trecho = a.get("trecho_original", "").strip()
        if trecho:
            linhas.append(f'   Trecho:   "{trecho}"')
            linhas.append(f'   Trocar por: "{a.get("correcao","").strip()}"')
        else:
            linhas.append(f'   Sugestão: {a.get("correcao","").strip()}')
        linhas.append(f"   Porquê:   {a.get('porque','').strip()}")
        return "\n".join(linhas)
