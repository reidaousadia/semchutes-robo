#!/usr/bin/env python3
"""Valida app/linhas.js contra as REGRAS do produto (ver REGRAS.md).

Roda no workflow DEPOIS da coleta e ANTES do deploy: se qualquer regra for
violada no dado, o pipeline FALHA e a versão anterior continua no ar — o erro
nunca chega no usuário. Uso: python3 robo/valida_linhas.py [caminho]
"""
import json, os, sys

caminho = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "linhas.js")
src = open(caminho, encoding="utf-8").read()
d, _ = json.JSONDecoder().raw_decode(src[src.index("window.SC_LINHAS=") + len("window.SC_LINHAS="):].lstrip())

erros, avisos = [], []
TIME_TIPOS = {"cantos", "cartoes", "gols"}

def escada_ok(l, onde, lado="over"):
    if not isinstance(l, dict) or not l:
        erros.append(f"{onde}: escada vazia/ inválida"); return
    pares = []
    for linha, odd in l.items():
        try: lf = float(linha)
        except ValueError: erros.append(f"{onde}: linha não-numérica '{linha}'"); continue
        if not isinstance(odd, (int, float)) or odd <= 1.0:
            erros.append(f"{onde}: odd inválida {odd} na linha {linha}"); continue
        pares.append((lf, odd))
    # MONOTONIA na ZONA DE DECISÃO (odds <= 3.0, onde a linha-base opera):
    # over encarece conforme a linha sobe; under o contrário. Nas caudas (odds
    # altas) a fusão melhor-odd entre casas quebra monotonia legitimamente.
    pares = sorted(p for p in pares if p[1] <= 3.0)
    for (l1, o1), (l2, o2) in zip(pares, pares[1:]):
        if lado == "over" and o2 < o1 * 0.85:
            erros.append(f"{onde}: monotonia quebrada (over {l1}@{o1} vs {l2}@{o2})")
        if lado == "under" and o2 > o1 * 1.18:
            erros.append(f"{onde}: monotonia quebrada (under {l1}@{o1} vs {l2}@{o2})")

jogos = d.get("jogos") or {}
if not jogos:
    erros.append("linhas.js sem jogos")

tot_jog, tot_time, jogaveis_jog = 0, 0, 0
for fid, jg in jogos.items():
    # REGRA 3: props de jogador são over-only por construção (uma escada "l" do Mais de)
    for nome, stats in (jg.get("jogador") or {}).items():
        for stat, reg in stats.items():
            tot_jog += 1
            if "l" not in reg:
                erros.append(f"jogador {nome}/{stat} ({fid}): sem escada"); continue
            escada_ok(reg["l"], f"jogador {nome}/{stat} ({fid})")
            if any(isinstance(o, (int, float)) and o >= 1.5 for o in reg["l"].values()):
                jogaveis_jog += 1
            p = reg.get("p")
            if p is not None and str(float(p)) not in reg["l"] and str(p) not in reg["l"]:
                avisos.append(f"jogador {nome}/{stat} ({fid}): principal {p} fora da escada")
    # REGRAS 1/4: time tem over em "time" e under APENAS em "timeU"
    for chave, obrigatorio in (("time", False), ("timeU", False)):
        for tipo, subs in (jg.get(chave) or {}).items():
            if tipo not in TIME_TIPOS:
                erros.append(f"{chave}.{tipo} ({fid}): tipo desconhecido")
            for sub, ladder in (subs or {}).items():
                if sub not in ("total", "t1", "t2"):
                    erros.append(f"{chave}.{tipo}.{sub} ({fid}): sub desconhecido")
                tot_time += 1
                escada_ok(ladder, f"{chave}.{tipo}.{sub} ({fid})", "under" if chave == "timeU" else "over")

if tot_jog == 0: avisos.append("nenhum prop de jogador coletado nesta rodada")
if jogaveis_jog == 0 and tot_jog > 0: erros.append("NENHUMA escada de jogador com odd >= 1,50")

print(f"validação: {len(jogos)} jogos · {tot_jog} props de jogador ({jogaveis_jog} jogáveis) · {tot_time} escadas de time")
for a in avisos[:10]: print("aviso:", a)
if erros:
    for e in erros[:20]: print("ERRO:", e)
    sys.exit(f"linhas.js VIOLA as regras ({len(erros)} erros) — deploy abortado")
print("OK — regras respeitadas")
