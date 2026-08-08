#!/usr/bin/env python3
"""Apitou — coletor de LINHAS de mercado (plataforma Altenar, feed público dos widgets).

Pra que serve: alimenta a aba Desajustes — compara a linha que a casa abre com a
mediana Apitou. As casas Altenar (LotoGreen, EstrelaBet, Gol de Bet, VaiDeBet...)
compartilham o motor de linhas, então UMA integração representa o grupo todo.

Saída: app/linhas.js → window.SC_LINHAS = {
  geradoEm, fonte: "altenar",
  jogos: { "<fixtureIdApitou>": {
    ev: <idAltenar>, kickoff,
    time:    { cantos: {t1: linhas, t2: linhas, total: linhas},
               cartoes: {...}, gols: {...} },
    jogador: { "<nome normalizado>": { fin: {principal, linhas}, chutesGol: {...}, cartoes: {...} } } } }
}
onde `linhas` = { "8.5": 1.85, "9.5": 2.30, ... } (odd do MAIS DE) e `principal`
é a linha que a casa destaca (campo sv do mercado).

SEM linguagem de aposta no app: só a LINHA numérica sobe; odds ficam pra régua
interna de desajuste (quanto menor a odd do over, mais "esticada" a linha).

Uso: python3 robo/linhas_altenar.py  (lê app/dados.js pra casar os jogos)
"""
import json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))
BASE = "https://sb2frontend-altenar2.biahosted.com/api/widget"
INTEGRACAO = os.environ.get("ALTENAR_INTEGRACAO", "lotogreen")
SPORT_FOOTBALL = 66
# champs Altenar (ids da plataforma, não da Sportmonks)
CHAMPS = {11318: "Brasileirão Série A"}
CHAMPS_EXTRA = os.environ.get("ALTENAR_CHAMPS", "")  # "id:nome,id:nome" pra ampliar sem editar código
for par in CHAMPS_EXTRA.split(","):
    if ":" in par:
        cid, nome = par.split(":", 1)
        CHAMPS[int(cid)] = nome

UA = {"Accept": "application/json",
      "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def req(path, **params):
    params.update({"culture": "pt-BR", "timezoneOffset": "180", "integration": INTEGRACAO,
                   "deviceType": "1", "numFormat": "en-GB", "countryCode": "BR"})
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    for tent in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                return json.load(r)
        except Exception as e:
            if tent == 2: raise
            print(f"  retry {path}: {e}", flush=True)
            time.sleep(3)

def norm(s):
    """normaliza nome pra casar Altenar × Sportmonks (acentos, sufixos de estado)"""
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(mg|rs|sp|rj|pr|sc|ba|ce|pe|go|fc|ec|sc)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)

# ---------- mercados-alvo (nome do market Altenar → chave Apitou) ----------
# time (usa sv da odd como linha; odd = preço do "Mais de")
M_TIME = {
    "Total de escanteios": ("cantos", "total"),
    "Total cartões": ("cartoes", "total"),
    "Total de gols": ("gols", "total"),
}
RE_TIME_LADO = [  # "{Time} total de escanteios" → por mando
    (re.compile(r"^(.+?) total de escanteios$", re.I), "cantos"),
    (re.compile(r"^(.+?) total cartões$", re.I), "cartoes"),
    (re.compile(r"^(.+?) Total de Gols$", re.I), "gols"),
]
# jogador: mercado "guarda-chuva" com childMarkets por jogador
M_JOG = {
    "Total de Chutes do Jogador + Substituto": "fin",
    "Total de Chutes a gol do Jogador + Substituto": "chutesGol",
    "Cartões - Incl. Substituto": "cartoes",
}
RE_JOG_NOME = re.compile(r"\(([^()]+?)(?:\s*\([A-Z]{2,4}\))?\)")  # "(Nome (GRE))" → Nome

def extrai_linhas(oddIds, odds_por_id, lado="mais"):
    """dict linha → odd do lado pedido ("mais" = over · "menos" = under)"""
    out = {}
    flat = []
    for x in oddIds or []:
        flat.extend(x if isinstance(x, list) else [x])
    for oid in flat:
        o = odds_por_id.get(oid)
        if not o: continue
        nome = str(o.get("name", ""))
        if not nome.lower().startswith(lado): continue
        sv = o.get("sv")
        try: linha = float(sv)
        except (TypeError, ValueError): continue
        out[str(linha)] = o.get("price")
    return out

def coleta_evento(ev_id):
    d = req("GetEventDetails", eventId=ev_id)
    mks = d.get("markets") or []
    cms = {c["id"]: c for c in (d.get("childMarkets") or [])}
    odds_por_id = {o["id"]: o for o in (d.get("odds") or [])}
    comp = [c.get("name", "") for c in (d.get("competitors") or [])]
    time_out, time_u_out, jog_out = {}, {}, {}

    for m in mks:
        nome = str(m.get("name", ""))
        # variantes por tempo NÃO entram (sobrescreviam a escada do jogo inteiro)
        if nome.startswith(("1º", "2º")): continue
        # --- mercados de TIME (linhas no próprio market ou nos filhos) ---
        alvo = M_TIME.get(nome)
        lado = None
        if not alvo:
            for rx, chave in RE_TIME_LADO:
                mm = rx.match(nome)
                if mm:
                    qual = norm(mm.group(1))
                    lado = "t1" if comp and norm(comp[0]).startswith(qual[:6]) else "t2"
                    alvo = (chave, lado)
                    break
        if alvo:
            chave, sub = alvo
            linhas = extrai_linhas(m.get("desktopOddIds"), odds_por_id)
            linhas_u = extrai_linhas(m.get("desktopOddIds"), odds_por_id, "menos")
            for cid in m.get("childMarketIds") or []:
                c = cms.get(cid)
                if c:
                    ids = c.get("desktopOddIds") or c.get("oddIds")
                    linhas.update(extrai_linhas(ids, odds_por_id))
                    linhas_u.update(extrai_linhas(ids, odds_por_id, "menos"))
            if linhas:
                time_out.setdefault(chave, {})[sub] = linhas
            if linhas_u:
                time_u_out.setdefault(chave, {})[sub] = linhas_u
            continue
        # --- mercados de JOGADOR (childMarkets por atleta) ---
        stat = M_JOG.get(nome)
        if not stat: continue
        for cid in m.get("childMarketIds") or []:
            c = cms.get(cid)
            if not c: continue
            mnome = RE_JOG_NOME.search(str(c.get("name", "")))
            if not mnome: continue
            jogador = mnome.group(1).strip()
            sv = str(c.get("sv", ""))
            principal = None
            if "|" in sv:
                try: principal = float(sv.split("|")[0])
                except ValueError: pass
            linhas = extrai_linhas(c.get("desktopOddIds") or c.get("oddIds"), odds_por_id)
            if linhas:
                jog_out.setdefault(jogador, {})[stat] = {"principal": principal, "linhas": linhas}
    return time_out, time_u_out, jog_out

def main():
    # jogos Apitou pra casar (dados.js)
    src = open(os.path.join(RAIZ, "app", "dados.js"), encoding="utf-8").read()
    i = src.index("window.SC_SEMANA=")
    sem, _ = json.JSONDecoder().raw_decode(src[i + len("window.SC_SEMANA="):].lstrip())
    por_chave = {}
    for fx in sem.get("fixtures", []):
        k = (norm(fx["home"])[:9], norm(fx["away"])[:9], fx["kickoff"][:10])
        por_chave[k] = fx

    jogos_out, casados, ev_total = {}, 0, 0
    for champ_id, champ_nome in CHAMPS.items():
        lista = req("GetEvents", sportId=SPORT_FOOTBALL, champIds=champ_id,
                    count=500, eventTypes=0)
        comp = {c["id"]: c.get("name", "") for c in lista.get("competitors", [])}
        for ev in lista.get("events", []):
            ev_total += 1
            nomes = [comp.get(c, "") for c in ev.get("competitorIds", [])]
            if len(nomes) != 2: continue
            data_ev = str(ev.get("startDate", ""))[:10]
            fx = por_chave.get((norm(nomes[0])[:9], norm(nomes[1])[:9], data_ev))
            if not fx: continue
            time.sleep(1.2)  # educação com o servidor
            try:
                time_out, time_u_out, jog_out = coleta_evento(ev["id"])
            except Exception as e:
                print(f"  erro {nomes[0]} x {nomes[1]}: {e}", flush=True)
                continue
            if time_out or jog_out:
                casados += 1
                jogos_out[str(fx["id"])] = {"ev": ev["id"], "kickoff": fx["kickoff"],
                                            "time": time_out, "timeU": time_u_out, "jogador": jog_out}
                print(f"  {fx['home']} x {fx['away']}: {len(jog_out)} jogadores, "
                      f"{sum(len(v) for v in time_out.values())} linhas de time", flush=True)

    payload = {"geradoEm": datetime.now(BRT).isoformat(), "fonte": "altenar",
               "integracao": INTEGRACAO, "jogos": jogos_out}
    destino = os.path.join(RAIZ, "robo", "linhas_altenar.json")
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"OK linhas.js: {casados} jogos casados de {ev_total} eventos · "
          f"{round(os.path.getsize(destino)/1024)} KB", flush=True)

if __name__ == "__main__":
    main()
