#!/usr/bin/env python3
"""Apitou — ROBÔ v2: coleta consolidada na SPORTMONKS (migração da API-Football).

Gera app/dados.js no MESMO formato do robô v1 (o app não muda), com upgrades:
  · finalizações por jogador COMPLETAS (incluem bloqueadas — prova do Lodi)
  · laterais (60) e tiros de meta (53) no raio-x dos times
  · árbitro do jogo + médias por temporada (cartões/faltas, split casa/fora)
  · fotos de TODOS os jogadores (CDN Sportmonks via proxy /smimg/)
  · elenco atual nativo (squads) — transferidos fora das listas
  · nomes canônicos por player_id — sem casamento frágil de strings

Regras de produto preservadas: amistosos fora (nem entram: só ligas assinadas),
jogos sem stats contam pra placar, continentais mescladas no app,
ligas regulares (71/72) puxam temporada anterior (cap 30).

Fase v2a: 5 competições BR/CONMEBOL (paridade). v2b: ligas europeias no app.

Env: SPORTMONKS_TOKEN (ou .env na raiz). Uso: python3 robo/coleta_sm.py
"""
import json, os, statistics, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))

TOK = os.environ.get("SPORTMONKS_TOKEN")
if not TOK:
    env = os.path.join(RAIZ, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("SPORTMONKS_TOKEN="):
                TOK = line.strip().split("=", 1)[1]
if not TOK:
    sys.exit("SPORTMONKS_TOKEN ausente")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) Safari/537.36", "Accept": "application/json"}
PAUSA = 1.5   # ~2.400 chamadas/hora (limite do plano: 2.500/h)

def sm(path, **params):
    params["api_token"] = TOK
    qs = urllib.parse.urlencode(params, safe=";:,.")
    url = f"https://api.sportmonks.com/v3/football{urllib.parse.quote(path, safe='/')}?{qs}"
    req = urllib.request.Request(url, headers=UA)
    for tent in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.load(r)
            time.sleep(PAUSA)
            return data
        except urllib.error.HTTPError as e:
            corpo = e.read().decode()[:200]
            if e.code == 429:
                print("rate limit — pausa 60s", flush=True); time.sleep(60); continue
            print(f"HTTP {e.code} {path}: {corpo}", flush=True); time.sleep(4)
        except Exception as e:
            print("retry", path, e, flush=True); time.sleep(4)
    return {}

def sm_paginado(path, **params):
    page, out = 1, []
    while True:
        d = sm(path, page=page, per_page=50, **params)
        out.extend(d.get("data", []))
        if not (d.get("pagination") or {}).get("has_more"): break
        page += 1
    return out

# ---------------- constantes / mapas ----------------
# liga Sportmonks → id canônico do app (o app depende de 71/72/73/11/13)
LIGA_CANON = {648: 71, 651: 72, 654: 73, 1116: 11, 1122: 13}
LIGA_NOME = {71: "Brasileirão", 72: "Série B", 73: "Copa do Brasil",
             11: "Sul-Americana", 13: "Libertadores"}
LIGAS_SM = list(LIGA_CANON.keys())
LIGAS_REGULARES = (71, 72)
FINALIZADO = ("FT", "AET", "FT_PEN")
POS = {24: "Goleiro", 25: "Defensor", 26: "Meia", 27: "Atacante"}
SEASON_INI = "2026-01-05"
SEASON_ANT = ("2025-01-05", "2025-12-22")

# tipos de estatística (validados empiricamente em 31/07/2026)
T_TIME = {42: "fin", 86: "chutesGol", 34: "cantos", 56: "faltas",
          84: "amarelos", 83: "vermelhos", 45: "posse", 57: "defesas",
          60: "laterais", 53: "tiroMeta"}
T_JOG = {42: "f", 86: "o", 52: "g", 56: "fc", 96: "fs", 84: "am", 83: "vm", 119: "m"}
TIPO_TITULAR = 11
REF_PRINCIPAL = 6

hoje = datetime.now(BRT).date()
d0, d1 = hoje.isoformat(), (hoje + timedelta(days=7)).isoformat()
print(f"janela: {d0} → {d1}", flush=True)

# ---------------- 1. fixtures da semana (NS) ----------------
brutos = sm_paginado(f"/fixtures/between/{d0}/{d1}",
                     filters=f"fixtureLeagues:{','.join(map(str, LIGAS_SM))}",
                     include="participants;state")
semana = []
for fx in brutos:
    if (fx.get("state") or {}).get("short_name") != "NS": continue
    parts = fx.get("participants", [])
    casa = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), None)
    fora = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), None)
    if not casa or not fora: continue
    lid = LIGA_CANON.get(fx.get("league_id"))
    ko = fx["starting_at"].replace(" ", "T") + "+00:00"
    semana.append({"id": fx["id"], "competicao": LIGA_NOME[lid], "ligaId": lid,
                   "home": casa["name"], "away": fora["name"],
                   "homeId": casa["id"], "awayId": fora["id"], "kickoff": ko,
                   "players": [], "_escudos": {casa["name"]: casa.get("image_path"),
                                               fora["name"]: fora.get("image_path")}})
semana.sort(key=lambda f: f["kickoff"])
print(f"{len(semana)} jogos NS", flush=True)
teams = {}
for fx in semana:
    teams[fx["homeId"]] = fx["home"]; teams[fx["awayId"]] = fx["away"]
print(f"{len(teams)} times", flush=True)

# ---------------- 2. elenco atual (squads) + nomes canônicos ----------------
squads, nome_por_pid, fotos = {}, {}, {}
for tid, tname in teams.items():
    d = sm(f"/squads/teams/{tid}", include="player")
    plantel = {}
    for s in d.get("data", []):
        p = s.get("player") or {}
        if not p: continue
        nome = p.get("display_name") or p.get("name")
        plantel[p["id"]] = {"nome": nome, "num": s.get("jersey_number"),
                            "pos": POS.get(p.get("position_id"), "")}
        nome_por_pid[p["id"]] = nome
        if p.get("image_path"):
            fotos[nome] = p["image_path"].replace("https://cdn.sportmonks.com", "/smimg")
    squads[tid] = plantel
    print(f"  plantel {tname}: {len(plantel)}", flush=True)

# ---------------- 3. varredura de temporada por time (1 detalhe por jogo, cacheado) ----------------
detalhe_cache = {}
INC_DET = "statistics;lineups.details;participants;scores;state;formations;coaches;referees.referee"
def detalhe(fid):
    if fid not in detalhe_cache:
        detalhe_cache[fid] = (sm(f"/fixtures/{fid}", include=INC_DET).get("data") or {})
    return detalhe_cache[fid]

def lista_time(tid, ini, fim):
    out = []
    for fx in sm_paginado(f"/fixtures/between/{ini}/{fim}/{tid}", include="state"):
        if (fx.get("state") or {}).get("short_name") in FINALIZADO:
            out.append({"fid": fx["id"], "ts": fx["starting_at"][:10],
                        "liga_sm": fx.get("league_id")})
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out

temporada, anterior = {}, {}
for tid, tname in teams.items():
    temporada[tid] = lista_time(tid, SEASON_INI, d0)
    print(f"  jogos 2026 {tname}: {len(temporada[tid])}", flush=True)
liga_teams = {tid for fx in semana if fx["ligaId"] in LIGAS_REGULARES
              for tid in (fx["homeId"], fx["awayId"])}
for tid in liga_teams:
    ant = lista_time(tid, *SEASON_ANT)
    anterior[tid] = [x for x in ant if LIGA_CANON.get(x["liga_sm"]) in LIGAS_REGULARES]
    print(f"  jogos 2025(liga) {teams[tid]}: {len(anterior[tid])}", flush=True)

def stats_do_time(det, tid):
    own, adv = {}, {}
    for st in det.get("statistics", []):
        campo = T_TIME.get(st.get("type_id"))
        if not campo: continue
        val = (st.get("data") or {}).get("value")
        if val is None: continue
        (own if st.get("participant_id") == tid else adv)[campo] = val
    return own, adv

def placar(det, tid):
    gols = golsSof = 0
    for sc in det.get("scores", []):
        if sc.get("description") != "CURRENT": continue
        g = (sc.get("score") or {}).get("goals") or 0
        if sc.get("participant_id") == tid: gols = g
        else: golsSof = g
    return gols, golsSof

def adversario(det, tid):
    for p in det.get("participants", []):
        if p["id"] != tid: return p["name"]
    return "?"

def registro_jogo(det, tid, ts, liga_canon):
    own, adv = stats_do_time(det, tid)
    g, gs = placar(det, tid)
    return {"liga": liga_canon or 0, "ts": ts, "advNome": adversario(det, tid),
            "own": own, "adv": adv, "gols": g, "golsSof": gs}

# ---------------- 4. raioxRaw + jogHist + elenco (numa passada) ----------------
raiox_raw, jog_hist, acum_elenco = {}, {}, {}
for tid, tname in teams.items():
    jogos_t = temporada[tid]
    regs, equipe = [], {}
    acum = acum_elenco.setdefault(tid, {})
    for jt in jogos_t:
        det = detalhe(jt["fid"])
        if not det: continue
        lc = LIGA_CANON.get(jt["liga_sm"])
        if len(regs) < 20:
            regs.append(registro_jogo(det, tid, jt["ts"], lc))
        for lu in det.get("lineups", []):
            if lu.get("team_id") != tid: continue
            pid = lu.get("player_id")
            vals = {campo: 0 for campo in T_JOG.values()}
            for dd in (lu.get("details") or []):
                campo = T_JOG.get(dd.get("type_id"))
                if campo:
                    vals[campo] = (dd.get("data") or {}).get("value") or 0
            if vals["m"] <= 0: continue
            nome = nome_por_pid.get(pid) or lu.get("player_name")
            # jogo a jogo (últimos 10) — só elenco atual
            if pid in squads.get(tid, {}) and len(equipe.get(nome, [])) < 10:
                equipe.setdefault(nome, []).append({
                    "t": jt["ts"], "l": lc or 0, "a": adversario(det, tid),
                    "m": vals["m"], "f": vals["f"], "o": vals["o"], "g": vals["g"],
                    "fc": vals["fc"], "fs": vals["fs"], "am": vals["am"], "vm": vals["vm"]})
            # acumulado da temporada (elenco)
            a = acum.setdefault(pid, {"apps": 0, "f": 0, "o": 0, "fc": 0, "fs": 0, "df": 0, "min": 0, "g": 0})
            a["apps"] += 1; a["min"] += vals["m"]; a["g"] += vals["g"]
            a["f"] += vals["f"]; a["o"] += vals["o"]; a["fc"] += vals["fc"]; a["fs"] += vals["fs"]
            for dd in (lu.get("details") or []):
                if dd.get("type_id") == 57:
                    a["df"] += (dd.get("data") or {}).get("value") or 0
    geral = regs[:15]
    liga = {}
    for fx in semana:
        if tid not in (fx["homeId"], fx["awayId"]): continue
        lid = fx["ligaId"]
        do_liga = [r for r in regs if r["liga"] == lid][:20]
        if lid in LIGAS_REGULARES:
            ant_regs = []
            for jt in anterior.get(tid, [])[:20]:
                det = detalhe(jt["fid"])
                if det: ant_regs.append(registro_jogo(det, tid, jt["ts"], LIGA_CANON.get(jt["liga_sm"])))
            do_liga = sorted(do_liga + ant_regs, key=lambda r: r["ts"], reverse=True)[:30]
        liga[str(lid)] = do_liga
    raiox_raw[str(tid)] = {"geral": geral, "liga": liga}
    jog_hist[str(tid)] = equipe
    print(f"  raiox+hist {tname}: {len(geral)} jogos · {len(equipe)} jogadores", flush=True)

# continentais: garante as duas copas pros times de Sula/Liberta
for fx in semana:
    if fx["ligaId"] not in (11, 13): continue
    for tid in (fx["homeId"], fx["awayId"]):
        reg = raiox_raw[str(tid)]
        for lid in (11, 13):
            if str(lid) not in reg["liga"]:
                todos = [r for r in reg["geral"] if r["liga"] == lid]
                reg["liga"][str(lid)] = todos

# ---------------- 5. elencos (médias da temporada, só plantel atual) ----------------
elencos, top_por_time = {}, {}
for tid, tname in teams.items():
    lista = []
    for pid, a in acum_elenco.get(tid, {}).items():
        if pid not in squads.get(tid, {}): continue
        if a["apps"] < 1 or a["min"] < 30: continue
        info = squads[tid][pid]
        lista.append({"name": info["nome"], "pos": info["pos"], "apps": a["apps"],
                      "media": round(a["f"] / a["apps"], 2),
                      "mediaOn": round(a["o"] / a["apps"], 2),
                      "faltasCom": round(a["fc"] / a["apps"], 2),
                      "faltasSof": round(a["fs"] / a["apps"], 2),
                      "defesas": round(a["df"] / a["apps"], 2),
                      "_pid": pid, "_min": a["min"], "_g": a["g"]})
    lista.sort(key=lambda x: x["media"], reverse=True)
    elencos[str(tid)] = lista
    top_por_time[tid] = [x for x in lista if x["apps"] >= 3][:3]

# ---------------- 6. cedidas / multAdversario + players do fixture ----------------
cedidas = {}
for tid in teams:
    vals = [r["adv"].get("fin") for r in raiox_raw[str(tid)]["geral"][:6] if r["adv"].get("fin") is not None]
    cedidas[tid] = round(statistics.mean(vals), 2) if vals else None
pool = [v for v in cedidas.values() if v]
ref_ced = statistics.mean(pool) if pool else 12.0
for fx in semana:
    for tid, adv_id, is_home in ((fx["homeId"], fx["awayId"], True), (fx["awayId"], fx["homeId"], False)):
        ced = cedidas.get(adv_id)
        mult = round(ced / ref_ced, 2) if ced else 1.0
        for j in top_por_time.get(tid, []):
            fx["players"].append({"playerId": j["_pid"], "name": j["name"], "team": teams[tid],
                                  "pos": j["pos"], "isHome": is_home, "media": j["media"],
                                  "apps": j["apps"], "minutosMedios": round(j["_min"] / j["apps"]),
                                  "multAdversario": mult, "mediaOn": j["mediaOn"], "gols": j["_g"]})

# ---------------- 7. confronto direto (h2h) ----------------
h2h, vistos = {}, {}
for fx in semana:
    a, b = fx["homeId"], fx["awayId"]
    par = (min(a, b), max(a, b))
    if par not in vistos:
        lst = sm_paginado(f"/fixtures/head-to-head/{a}/{b}", include="state")
        fin = [x for x in lst if (x.get("state") or {}).get("short_name") in FINALIZADO]
        fin.sort(key=lambda x: x["starting_at"], reverse=True)
        confs = []
        for x in fin[:12]:
            det = detalhe(x["id"])
            if not det: continue
            parts = det.get("participants", [])
            casa = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), None)
            fora = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), None)
            if not casa or not fora: continue
            sH, _ = stats_do_time(det, casa["id"]); sA, _ = stats_do_time(det, fora["id"])
            gH, _ = placar(det, casa["id"]); gA, _ = placar(det, fora["id"])
            def soma(*chaves):
                v = [s.get(c) for s in (sH, sA) for c in chaves if s.get(c) is not None]
                return int(sum(v)) if v else None
            lc = LIGA_CANON.get(det.get("league_id"))
            confs.append({"ts": x["starting_at"][:10], "comp": LIGA_NOME.get(lc, "Outros"),
                          "idH": casa["id"], "idA": fora["id"], "nH": casa["name"], "nA": fora["name"],
                          "gH": gH, "gA": gA, "sH": sH, "sA": sA,
                          "ca": soma("cantos"), "ct": soma("amarelos", "vermelhos"), "df": soma("defesas")})
        vistos[par] = confs
    h2h[str(fx["id"])] = vistos[par]
print("h2h ok", flush=True)

# ---------------- 8. escalações do último jogo + árbitros ----------------
escalacoes = {"ultimas": {}, "confirmadas": {}, "desfalques": {}}
for tid, tname in teams.items():
    jogos_t = temporada[tid]
    if not jogos_t: continue
    det = detalhe(jogos_t[0]["fid"])
    if not det: continue
    formacao = next((f.get("formation") for f in det.get("formations", [])
                     if f.get("participant_id") == tid), None)
    tecnico = next((c.get("display_name") for c in det.get("coaches", [])
                    if (c.get("meta") or {}).get("participant_id") == tid), None)
    xi = [{"nome": nome_por_pid.get(lu.get("player_id")) or lu.get("player_name"),
           "num": lu.get("jersey_number"), "pos": {24: "G", 25: "D", 26: "M", 27: "F"}.get(lu.get("position_id"), "M"),
           "grid": lu.get("formation_field")}
          for lu in det.get("lineups", [])
          if lu.get("team_id") == tid and lu.get("type_id") == TIPO_TITULAR]
    if xi:
        escalacoes["ultimas"][str(tid)] = {"ts": jogos_t[0]["ts"], "adv": adversario(det, tid),
                                            "formacao": formacao, "tecnico": tecnico, "xi": xi}
print(f"escalações: {len(escalacoes['ultimas'])}", flush=True)

# árbitro designado + perfil rico (agregado de TODAS as temporadas da base,
# com split casa/fora dos amarelos — leitura de mercado de cartões)
arbitros = {}
ref_stats_cache = {}
for fx in semana:
    det = sm(f"/fixtures/{fx['id']}", include="referees.referee").get("data") or {}
    ref = next(((r.get("referee") or {}) for r in det.get("referees", [])
                if r.get("type_id") == REF_PRINCIPAL), None)
    if not ref or not ref.get("id"): continue
    rid = ref["id"]
    if rid not in ref_stats_cache:
        rd = sm(f"/referees/{rid}", include="statistics.details.type").get("data") or {}
        jogos = am = am_c = am_f = vm = faltas = pen = varm = amrl = 0
        for st in rd.get("statistics", []):
            for dd in (st.get("details") or []):
                nome_t = ((dd.get("type") or {}).get("name") or "").lower()
                val = dd.get("value") or {}
                if not isinstance(val, dict): continue
                if "season matches" in nome_t: jogos += val.get("count") or 0
                elif nome_t == "yellowcards":
                    am += (val.get("all") or {}).get("count") or 0
                    am_c += (val.get("home") or {}).get("count") or 0
                    am_f += (val.get("away") or {}).get("count") or 0
                elif nome_t == "redcards": vm += (val.get("all") or {}).get("count") or 0
                elif "yellowred" in nome_t: amrl += (val.get("all") or {}).get("count") or 0
                elif nome_t == "fouls": faltas += val.get("count") or 0
                elif nome_t == "penalties": pen += (val.get("all") or {}).get("count") or 0
                elif "var" in nome_t: varm += val.get("count") or 0
        perfil = {"id": rid, "nome": ref.get("display_name") or ref.get("name"), "jogos": jogos}
        if jogos:
            r2 = lambda x: round(x, 2)
            perfil.update({"amarelos": r2(am/jogos), "amarelosCasa": r2(am_c/jogos),
                           "amarelosFora": r2(am_f/jogos), "vermelhos": r2((vm+amrl)/jogos),
                           "faltas": r2(faltas/jogos), "penaltis": r2(pen/jogos), "var": r2(varm/jogos)})
        ref_stats_cache[rid] = perfil
    arbitros[str(fx["id"])] = ref_stats_cache[rid]
print(f"árbitros designados: {len(arbitros)}", flush=True)

# ---------------- 9. monta dados.js ----------------
escudos = {}
for fx in semana:
    for nome, url in fx.pop("_escudos", {}).items():
        if url: escudos[nome] = url.replace("https://cdn.sportmonks.com", "/smimg")
for lista in elencos.values():
    for x in lista:
        x.pop("_pid", None); x.pop("_min", None); x.pop("_g", None)

sc_semana = {"geradoEm": datetime.now(BRT).isoformat(), "fonte": "sportmonks",
             "ref_cedidas": round(ref_ced, 2), "fixtures": semana, "elencos": elencos,
             "raioxRaw": raiox_raw, "h2h": h2h, "jogHist": jog_hist,
             "escalacoes": escalacoes, "arbitros": arbitros}
sc_assets = {"fotos": fotos, "escudos": escudos}

destino = os.path.join(RAIZ, "app", "dados.js")
with open(destino, "w", encoding="utf-8") as f:
    f.write("window.SC_SEMANA=" + json.dumps(sc_semana, ensure_ascii=False, separators=(",", ":")))
    f.write(";\nwindow.SC_ASSETS=" + json.dumps(sc_assets, ensure_ascii=False, separators=(",", ":")) + ";\n")
print(f"OK dados.js: {round(os.path.getsize(destino)/1024/1024, 2)} MB · {len(semana)} jogos · "
      f"{sum(len(v) for v in elencos.values())} jogadores · {len(detalhe_cache)} fixtures detalhadas", flush=True)
