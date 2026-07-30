#!/usr/bin/env python3
"""Sem Chutes — ROBÔ: coleta diária consolidada.

Gera app/dados.js completo do zero:
  fixtures da semana (71 Brasileirão, 72 Série B, 73 Copa do Brasil,
  11 Sul-Americana, 13 Libertadores) + top-3 finalizadores por time +
  elencos (com id/foto), raioxRaw (geral/por liga, 2025 pras ligas, amistosos
  fora, jogos sem stats contam), h2h (com stats por time), jogHist (jogo a
  jogo por jogador), escalação do último jogo por time.

Regras de produto (decididas com o Pedro — NÃO mudar sem ele):
  - amistosos NÃO contam pra forma;
  - jogos sem estatística detalhada CONTAM pra resultado/gols;
  - Sul-Americana + Libertadores contam juntas ("continentais");
  - ligas regulares (71/72) puxam também a temporada anterior (cap 30).

Chave da API: env API_FOOTBALL_KEY, ou .env na raiz do repo (local).
Uso: python3 robo/coleta.py   (escreve app/dados.js)
"""
import json, os, statistics, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))

KEY = os.environ.get("API_FOOTBALL_KEY")
if not KEY:
    env = os.path.join(RAIZ, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("API_FOOTBALL_KEY="):
                KEY = line.strip().split("=", 1)[1]
if not KEY:
    sys.exit("API_FOOTBALL_KEY ausente (env ou .env)")

BASE = "https://v3.football.api-sports.io"
def get(path, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}{path}?{qs}", headers={"x-apisports-key": KEY})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            if data.get("errors") and "rateLimit" in str(data["errors"]):
                time.sleep(10); continue
            time.sleep(0.30)
            return data.get("response", []), data.get("paging", {})
        except Exception as e:
            print("retry", path, e, flush=True); time.sleep(5)
    return [], {}

LIGAS = {71: "Brasileirão", 72: "Série B", 73: "Copa do Brasil",
         11: "Sul-Americana", 13: "Libertadores"}
LIGAS_REGULARES = (71, 72)      # histórico alcança a temporada anterior
CONTINENTAIS = (11, 13)
POS = {"Attacker": "Atacante", "Midfielder": "Meia", "Defender": "Defensor", "Goalkeeper": "Goleiro"}
TIPOS = {"Total Shots": "fin", "Shots on Goal": "chutesGol", "Corner Kicks": "cantos",
         "Fouls": "faltas", "Yellow Cards": "amarelos", "Red Cards": "vermelhos",
         "Ball Possession": "posse", "Goalkeeper Saves": "defesas"}
FINALIZADO = ("FT", "AET", "PEN")
SEASON = 2026

def eh_amistoso(f):
    return "Friendl" in (f["league"]["name"] or "")

# ---------------------------------------------------------------- 1. fixtures da semana
hoje = datetime.now(BRT).date()
d0, d1 = hoje.isoformat(), (hoje + timedelta(days=7)).isoformat()
print(f"janela: {d0} → {d1}", flush=True)

fixtures_raw = []
for lid, nome in LIGAS.items():
    resp, _ = get("/fixtures", league=lid, season=SEASON, **{"from": d0, "to": d1})
    for f in resp:
        if f["fixture"]["status"]["short"] != "NS":
            continue
        f["_liga"], f["_ligaId"] = nome, lid
        fixtures_raw.append(f)
    print(f"  {nome}: {len(resp)} no período", flush=True)
fixtures_raw.sort(key=lambda f: f["fixture"]["date"])
print(f"{len(fixtures_raw)} jogos NS", flush=True)

teams = {}
for f in fixtures_raw:
    for side in ("home", "away"):
        t = f["teams"][side]
        teams[t["id"]] = t["name"]
print(f"{len(teams)} times", flush=True)

# ---------------------------------------------------------------- 2. elencos (com id → foto por URL)
elencos, top_por_time, fotos = {}, {}, {}
for tid, tname in teams.items():
    acum, page = {}, 1
    while page <= 5:
        resp, paging = get("/players", team=tid, season=SEASON, page=page)
        if not resp: break
        for r in resp:
            pid = r["player"]["id"]
            # soma TODAS as competições do jogador nesse time (lição v10)
            for s in r["statistics"]:
                if s["team"]["id"] != tid: continue
                a = acum.setdefault(pid, {"id": pid, "name": r["player"]["name"],
                    "pos": POS.get(s["games"]["position"] or "", s["games"]["position"] or ""),
                    "apps": 0, "shots": 0, "on": 0, "mins": 0, "gols": 0,
                    "fc": 0, "fs": 0, "defesas": 0})
                a["apps"] += s["games"]["appearences"] or 0
                a["shots"] += s["shots"]["total"] or 0
                a["on"] += s["shots"]["on"] or 0
                a["mins"] += s["games"]["minutes"] or 0
                a["gols"] += s["goals"]["total"] or 0
                a["fc"] += (s["fouls"]["committed"] or 0)
                a["fs"] += (s["fouls"]["drawn"] or 0)
                a["defesas"] += (s["goals"]["saves"] or 0)
        if page >= (paging.get("total") or 1): break
        page += 1
    lista = []
    for a in acum.values():
        if a["apps"] < 1 or a["mins"] < 30: continue
        lista.append({"name": a["name"], "pos": a["pos"], "apps": a["apps"],
                      "media": round(a["shots"] / a["apps"], 2),
                      "mediaOn": round(a["on"] / a["apps"], 2),
                      "faltasCom": round(a["fc"] / a["apps"], 2),
                      "faltasSof": round(a["fs"] / a["apps"], 2),
                      "defesas": round(a["defesas"] / a["apps"], 2),
                      "_id": a["id"], "_mins": a["mins"], "_gols": a["gols"]})
        fotos[a["name"]] = f"/media/football/players/{a['id']}.png"
    lista.sort(key=lambda x: x["media"], reverse=True)
    elencos[str(tid)] = lista
    # top 3 finalizadores (≥3 jogos) pro bloco de destaques do jogo
    quali = [x for x in lista if x["apps"] >= 3]
    top_por_time[tid] = quali[:3]
    print(f"  elenco {tname}: {len(lista)}", flush=True)

# ---------------------------------------------------------------- 3. finalizações cedidas (mult adversário)
stats_cache = {}   # fixture id -> blocos de estatística
def stats_fixture(fid):
    if fid not in stats_cache:
        stats_cache[fid], _ = get("/fixtures/statistics", fixture=fid)
    return stats_cache[fid]

cedidas = {}
for tid, tname in teams.items():
    ult, _ = get("/fixtures", team=tid, season=SEASON, last=8)
    vals = []
    for f in ult:
        if f["fixture"]["status"]["short"] not in FINALIZADO or eh_amistoso(f): continue
        for s in stats_fixture(f["fixture"]["id"]):
            if s["team"]["id"] != tid:
                for item in s["statistics"]:
                    if item["type"] == "Total Shots" and item["value"] is not None:
                        vals.append(item["value"])
        if len(vals) >= 6: break
    cedidas[tid] = round(statistics.mean(vals), 2) if vals else None
ref = statistics.mean([v for v in cedidas.values() if v]) if any(cedidas.values()) else 12.0
print(f"ref cedidas: {ref:.2f}", flush=True)

# ---------------------------------------------------------------- 4. estrutura de fixtures + players (top 3)
fixtures = []
for f in fixtures_raw:
    h, a = f["teams"]["home"], f["teams"]["away"]
    entry = {"id": f["fixture"]["id"], "competicao": f["_liga"], "ligaId": f["_ligaId"],
             "home": h["name"], "away": a["name"], "homeId": h["id"], "awayId": a["id"],
             "kickoff": f["fixture"]["date"], "players": []}
    for tid, adv_id, is_home in ((h["id"], a["id"], True), (a["id"], h["id"], False)):
        ced = cedidas.get(adv_id)
        mult = round(ced / ref, 2) if ced else 1.0
        for j in top_por_time.get(tid, []):
            entry["players"].append({
                "playerId": j["_id"], "name": j["name"], "team": teams[tid],
                "pos": j["pos"], "isHome": is_home, "media": j["media"],
                "apps": j["apps"], "minutosMedios": round(j["_mins"] / j["apps"]),
                "multAdversario": mult, "mediaOn": j["mediaOn"], "gols": j["_gols"]})
    fixtures.append(entry)

# ---------------------------------------------------------------- 5. raioxRaw (times: geral + por liga)
def extrai(bloco):
    out = {}
    for item in bloco["statistics"]:
        k = TIPOS.get(item["type"])
        if k:
            v = item["value"]
            if v is None: v = 0
            if isinstance(v, str): v = float(v.replace("%", "") or 0)
            out[k] = v
    return out

def monta_jogos(fxs, tid, limite=15):
    jogos = []
    for f in fxs:  # API devolve mais recente primeiro; ordenamos por ts mesmo assim
        if f["fixture"]["status"]["short"] not in FINALIZADO or eh_amistoso(f): continue
        blocos = stats_fixture(f["fixture"]["id"])
        proprio = [b for b in blocos if b["team"]["id"] == tid]
        outro = [b for b in blocos if b["team"]["id"] != tid]
        eh_casa = f["teams"]["home"]["id"] == tid
        jogos.append({
            "liga": f["league"]["id"], "ts": f["fixture"]["date"][:10],
            "advNome": f["teams"]["away" if eh_casa else "home"]["name"],
            "own": extrai(proprio[0]) if proprio else {},
            "adv": extrai(outro[0]) if outro else {},
            "gols": f["goals"]["home" if eh_casa else "away"] or 0,
            "golsSof": f["goals"]["away" if eh_casa else "home"] or 0,
        })
        if len(jogos) >= limite: break
    jogos.sort(key=lambda j: j["ts"], reverse=True)
    return jogos

pares, times_cont = set(), set()
for fx in fixtures:
    for tid in (fx["homeId"], fx["awayId"]):
        pares.add((tid, fx["ligaId"]))
        if fx["ligaId"] in CONTINENTAIS: times_cont.add(tid)

raiox_raw = {}
ultima_fixture = {}   # tid -> fixture id mais recente (pra escalação)
for tid in teams:
    fxs, _ = get("/fixtures", team=tid, season=SEASON, last=20)
    fin = [f for f in fxs if f["fixture"]["status"]["short"] in FINALIZADO and not eh_amistoso(f)]
    if fin: ultima_fixture[tid] = {"fid": fin[0]["fixture"]["id"], "ts": fin[0]["fixture"]["date"][:10],
                                   "adv": fin[0]["teams"]["away"]["name"] if fin[0]["teams"]["home"]["id"] == tid else fin[0]["teams"]["home"]["name"]}
    raiox_raw[str(tid)] = {"geral": monta_jogos(fxs, tid), "liga": {}}
    print(f"  raiox geral {teams[tid]}", flush=True)

for tid, lid in sorted(pares):
    fxs, _ = get("/fixtures", team=tid, season=SEASON, league=lid, last=20)
    jogos = monta_jogos(fxs, tid)
    if lid in LIGAS_REGULARES:  # acrescenta temporada anterior (cap 30)
        fxs_ant, _ = get("/fixtures", team=tid, season=SEASON - 1, league=lid, last=20)
        jogos = sorted(jogos + monta_jogos(fxs_ant, tid), key=lambda j: j["ts"], reverse=True)[:30]
    raiox_raw[str(tid)]["liga"][str(lid)] = jogos

for tid in times_cont:  # crossover continental: garante as duas copas
    for lid in CONTINENTAIS:
        if str(lid) in raiox_raw[str(tid)]["liga"]: continue
        fxs, _ = get("/fixtures", team=tid, season=SEASON, league=lid, last=20)
        raiox_raw[str(tid)]["liga"][str(lid)] = monta_jogos(fxs, tid)
print("raioxRaw ok", flush=True)

# ---------------------------------------------------------------- 6. confronto direto (h2h, stats por time)
def stats_por_time(fid):
    por = {}
    for b in stats_fixture(fid):
        out = extrai(b)
        if out: por[b["team"]["id"]] = out
    return por

def soma(sH, sA, *chaves):
    vals = [s.get(c) for s in (sH, sA) for c in chaves if s.get(c) is not None]
    return int(sum(vals)) if vals else None

h2h, vistos = {}, {}
for fx in fixtures:
    hid, aid = fx["homeId"], fx["awayId"]
    par = (min(hid, aid), max(hid, aid))
    if par not in vistos:
        resp, _ = get("/fixtures/headtohead", h2h=f"{hid}-{aid}", last=12)
        confrontos = []
        for f in resp:
            if f["fixture"]["status"]["short"] not in FINALIZADO or eh_amistoso(f): continue
            por = stats_por_time(f["fixture"]["id"])
            idH, idA = f["teams"]["home"]["id"], f["teams"]["away"]["id"]
            sH, sA = por.get(idH, {}), por.get(idA, {})
            confrontos.append({
                "ts": f["fixture"]["date"][:10],
                "comp": LIGAS.get(f["league"]["id"], f["league"]["name"]),
                "idH": idH, "idA": idA,
                "nH": f["teams"]["home"]["name"], "nA": f["teams"]["away"]["name"],
                "gH": f["goals"]["home"] or 0, "gA": f["goals"]["away"] or 0,
                "sH": sH, "sA": sA,
                "ca": soma(sH, sA, "cantos"), "ct": soma(sH, sA, "amarelos", "vermelhos"),
                "df": soma(sH, sA, "defesas")})
        confrontos.sort(key=lambda j: j["ts"], reverse=True)
        vistos[par] = confrontos
    h2h[str(fx["id"])] = vistos[par]
print("h2h ok", flush=True)

# ---------------------------------------------------------------- 7. jogo a jogo por jogador
time_fixtures, fids = {}, set()
for tid in teams:
    fxs, _ = get("/fixtures", team=tid, season=SEASON, last=14)
    lst = []
    for f in fxs:
        if f["fixture"]["status"]["short"] not in FINALIZADO or eh_amistoso(f): continue
        eh_casa = f["teams"]["home"]["id"] == tid
        lst.append({"fid": f["fixture"]["id"], "ts": f["fixture"]["date"][:10],
                    "liga": f["league"]["id"],
                    "adv": f["teams"]["away" if eh_casa else "home"]["name"]})
        if len(lst) >= 10: break
    time_fixtures[tid] = lst
    fids.update(x["fid"] for x in lst)

players_cache = {}
for i, fid in enumerate(sorted(fids)):
    players_cache[fid], _ = get("/fixtures/players", fixture=fid)
    if i % 40 == 0: print(f"  players {i}/{len(fids)}", flush=True)

jog_hist = {}
for tid, lst in time_fixtures.items():
    equipe = {}
    for fxinfo in lst:
        bloco = next((b for b in players_cache.get(fxinfo["fid"], []) if b["team"]["id"] == tid), None)
        if not bloco: continue
        for p in bloco["players"]:
            st = (p.get("statistics") or [{}])[0]
            m = (st.get("games") or {}).get("minutes") or 0
            if m <= 0: continue
            sh, fl, cd, gl = st.get("shots") or {}, st.get("fouls") or {}, st.get("cards") or {}, st.get("goals") or {}
            equipe.setdefault(p["player"]["name"], []).append({
                "t": fxinfo["ts"], "l": fxinfo["liga"], "a": fxinfo["adv"], "m": m,
                "f": sh.get("total") or 0, "o": sh.get("on") or 0, "g": gl.get("total") or 0,
                "fc": fl.get("committed") or 0, "fs": fl.get("drawn") or 0,
                "am": cd.get("yellow") or 0, "vm": cd.get("red") or 0})
            fotos.setdefault(p["player"]["name"], f"/media/football/players/{p['player']['id']}.png")
    jog_hist[str(tid)] = equipe
print("jogHist ok", flush=True)

# ---------------------------------------------------------------- 8. escalação do último jogo por time
escalacoes = {"ultimas": {}, "confirmadas": {}}
for tid, info in ultima_fixture.items():
    resp, _ = get("/fixtures/lineups", fixture=info["fid"])
    bloco = next((b for b in resp if b["team"]["id"] == tid), None)
    if not bloco: continue
    escalacoes["ultimas"][str(tid)] = {
        "ts": info["ts"], "adv": info["adv"],
        "formacao": bloco.get("formation"),
        "tecnico": (bloco.get("coach") or {}).get("name"),
        "xi": [{"nome": p["player"]["name"], "num": p["player"]["number"],
                "pos": p["player"]["pos"], "grid": p["player"]["grid"]}
               for p in (bloco.get("startXI") or [])]}
print(f"escalações: {len(escalacoes['ultimas'])} times", flush=True)

# ---------------------------------------------------------------- 9. escreve app/dados.js
for lista in elencos.values():  # remove campos internos
    for x in lista:
        x.pop("_id", None); x.pop("_mins", None); x.pop("_gols", None)

sc_semana = {"geradoEm": datetime.now(BRT).isoformat(), "ref_cedidas": round(ref, 2),
             "fixtures": fixtures, "elencos": elencos, "raioxRaw": raiox_raw,
             "h2h": h2h, "jogHist": jog_hist, "escalacoes": escalacoes}
sc_assets = {"fotos": fotos,
             "escudos": {teams[tid]: f"/media/football/teams/{tid}.png" for tid in teams}}

destino = os.path.join(RAIZ, "app", "dados.js")
with open(destino, "w", encoding="utf-8") as f:
    f.write("window.SC_SEMANA=" + json.dumps(sc_semana, ensure_ascii=False, separators=(",", ":")))
    f.write(";\nwindow.SC_ASSETS=" + json.dumps(sc_assets, ensure_ascii=False, separators=(",", ":")) + ";\n")
print(f"OK dados.js: {round(os.path.getsize(destino)/1024/1024, 2)} MB · "
      f"{len(fixtures)} jogos · {sum(len(v) for v in elencos.values())} jogadores", flush=True)
