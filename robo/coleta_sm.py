#!/usr/bin/env python3
"""Apitou — ROBÔ v2b: coleta GLOBAL na Sportmonks (todas as ligas assinadas).

Catálogo de ~30 competições com flags (liga/copa/continental + grupo) que o app
lê em vez de IDs fixos. Coleta em DOIS NÍVEIS:
  · TIER 1 (BR + top-5 europeu + UCL/UEL): profundidade total — elencos,
    jogo a jogo por jogador, raio-x 15/30 c/ temporada anterior, h2h com
    estatística por time, escalações, árbitro rico com histórico.
  · TIER 2 (demais): agenda + raio-x dos últimos 6 + h2h só placar +
    escalação do último jogo + árbitro designado com médias.

Histórico por JANELA DE 12 MESES (não por "temporada") — unifica o calendário
brasileiro (ano civil) com o europeu (ago-mai) sem casos especiais.

Regras de produto preservadas: amistosos nem entram (só ligas assinadas),
jogos sem stats contam pra placar, continentais mescladas POR GRUPO no app,
ligas regulares puxam até 30 jogos de janela.

Env: SPORTMONKS_TOKEN. Uso: python3 robo/coleta_sm.py
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
PAUSA = 1.5

def sm(path, **params):
    params["api_token"] = TOK
    qs = urllib.parse.urlencode(params, safe=";:,.")
    url = f"https://api.sportmonks.com/v3/football{urllib.parse.quote(path, safe='/')}?{qs}"
    req = urllib.request.Request(url, headers=UA)
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.load(r)
            time.sleep(PAUSA)
            return data
        except urllib.error.HTTPError as e:
            corpo = e.read().decode()[:150]
            if e.code == 429:
                print("rate limit — 60s", flush=True); time.sleep(60); continue
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

# ================= CATÁLOGO DE LIGAS (id Sportmonks) =================
# tipo: "liga" (pontos corridos) | "copa" | "continental"
# grupo: br | eu | am | uefa | conmebol | concacaf  (continental mescla por grupo)
# tier: 1 = profundidade total · 2 = leve
LIGAS = {
    648:  ("Brasileirão",        "liga",        "br",       1),
    651:  ("Série B",            "liga",        "br",       1),
    657:  ("Série C",            "liga",        "br",       2),
    654:  ("Copa do Brasil",     "copa",        "br",       1),
    1296: ("Carioca",            "liga",        "br",       2),   # estaduais: agenda jan-abr;
    1313: ("Paulista",           "liga",        "br",       2),   # já engordam o confronto direto o ano todo
    1122: ("Libertadores",       "continental", "conmebol", 1),
    1116: ("Sul-Americana",      "continental", "conmebol", 1),
    8:    ("Premier League",     "liga",        "eu",       1),
    564:  ("La Liga",            "liga",        "eu",       1),
    384:  ("Serie A italiana",   "liga",        "eu",       1),
    82:   ("Bundesliga",         "liga",        "eu",       1),
    301:  ("Ligue 1",            "liga",        "eu",       1),
    2:    ("Champions League",   "continental", "uefa",     1),
    5:    ("Europa League",      "continental", "uefa",     1),
    2286: ("Conference League",  "continental", "uefa",     2),
    1328: ("Supercopa UEFA",     "continental", "uefa",     2),
    9:    ("Championship",       "liga",        "eu",       2),
    # 24: FA Cup — REMOVIDA até janeiro: as fases preliminares (ago-dez) são
    # centenas de jogos amadores que poluem a agenda. Reativar na fase principal.
    72:   ("Eredivisie",         "liga",        "eu",       2),
    85:   ("2. Bundesliga",      "liga",        "eu",       2),
    109:  ("Copa da Alemanha",   "copa",        "eu",       2),
    307:  ("Copa da França",     "copa",        "eu",       2),
    462:  ("Liga Portugal",      "liga",        "eu",       2),
    468:  ("Taça de Portugal",   "copa",        "eu",       2),
    570:  ("Copa do Rei",        "copa",        "eu",       2),
    1251: ("Supercopa",          "copa",        "eu",       2),
    636:  ("Argentina",          "liga",        "am",       2),
    642:  ("Copa Argentina",     "copa",        "am",       2),
    672:  ("Colômbia",           "liga",        "am",       2),
    743:  ("Liga MX",            "liga",        "am",       2),
    779:  ("MLS",                "liga",        "am",       2),
    1479: ("Concacaf League",    "continental", "concacaf", 2),
}
FINALIZADO = ("FT", "AET", "FTP", "FT_PEN", "PEN")  # FTP = decidido nos pênaltis (caso Boca×O'Higgins)
POS = {24: "Goleiro", 25: "Defensor", 26: "Meia", 27: "Atacante"}
T_TIME = {42: "fin", 86: "chutesGol", 34: "cantos", 56: "faltas",
          84: "amarelos", 83: "vermelhos", 45: "posse", 57: "defesas",
          60: "laterais", 53: "tiroMeta"}
T_JOG = {42: "f", 86: "o", 52: "g", 56: "fc", 96: "fs", 84: "am", 83: "vm", 119: "m", 78: "ds", 80: "ps"}
TIPO_TITULAR = 11
REF_PRINCIPAL = 6
LIGAS_BR_REF = [648, 651, 654, 1116, 1122]   # histórico de árbitro (mercado BR)

def data_local(starting_at):
    """Data BRT do jogo (starting_at vem em UTC) — jogo de 21h30 não vira 'amanhã'."""
    dt = datetime.fromisoformat(starting_at.replace(" ", "T")).replace(tzinfo=timezone.utc)
    return dt.astimezone(BRT).date().isoformat()

def liga_nome(lid): return LIGAS.get(lid, (f"Liga {lid}",))[0]
def liga_tier(lid): return LIGAS.get(lid, (None, None, None, 2))[3]

hoje = datetime.now(BRT).date()
d0, d1 = hoje.isoformat(), (hoje + timedelta(days=7)).isoformat()
IDS_TODAS = ",".join(map(str, LIGAS))
print(f"janela: {d0} → {d1} · {len(LIGAS)} ligas", flush=True)

# ================= 1. fixtures da semana =================
brutos = sm_paginado(f"/fixtures/between/{d0}/{d1}",
                     filters=f"fixtureLeagues:{IDS_TODAS}",
                     include="participants;state")
semana = []
for fx in brutos:
    if (fx.get("state") or {}).get("short_name") != "NS": continue
    parts = fx.get("participants", [])
    casa = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), None)
    fora = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), None)
    if not casa or not fora or fx.get("league_id") not in LIGAS: continue
    lid = fx["league_id"]
    semana.append({"id": fx["id"], "competicao": liga_nome(lid), "ligaId": lid,
                   "home": casa["name"], "away": fora["name"],
                   "homeId": casa["id"], "awayId": fora["id"],
                   "kickoff": fx["starting_at"].replace(" ", "T") + "+00:00",
                   "players": [],
                   "_escudos": {casa["name"]: casa.get("image_path"),
                                fora["name"]: fora.get("image_path")}})
semana.sort(key=lambda f: f["kickoff"])
print(f"{len(semana)} jogos NS", flush=True)

teams, team_tier = {}, {}
for fx in semana:
    t = liga_tier(fx["ligaId"])
    for tid, nome in ((fx["homeId"], fx["home"]), (fx["awayId"], fx["away"])):
        teams[tid] = nome
        team_tier[tid] = min(team_tier.get(tid, 2), t)
t1 = [t for t in teams if team_tier[t] == 1]
print(f"{len(teams)} times · {len(t1)} em tier 1", flush=True)

# ================= 2. elenco atual (tier 1) =================
squads, nome_por_pid, fotos = {}, {}, {}
for tid in t1:
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
print(f"plantéis tier1: {len(squads)}", flush=True)

# ================= 3. históricos por time (janela de 12 meses) =================
detalhe_cache = {}
INC_DET = "statistics;lineups.details;participants;scores;state;formations;coaches;referees.referee"
def detalhe(fid):
    if fid not in detalhe_cache:
        detalhe_cache[fid] = (sm(f"/fixtures/{fid}", include=INC_DET).get("data") or {})
    return detalhe_cache[fid]

def lista_time(tid, meses):
    """Jogos finalizados do time nos últimos N meses (janelas de 90d)."""
    out, fim = [], hoje
    for _ in range(max(1, meses // 3)):
        ini = fim - timedelta(days=90)
        for fx in sm_paginado(f"/fixtures/between/{ini.isoformat()}/{fim.isoformat()}/{tid}",
                              include="state"):
            if (fx.get("state") or {}).get("short_name") in FINALIZADO and fx.get("league_id") in LIGAS:
                out.append({"fid": fx["id"], "ts": data_local(fx["starting_at"]), "liga": fx["league_id"]})
        fim = ini - timedelta(days=1)
    out.sort(key=lambda x: x["ts"], reverse=True)
    return out

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
    g = gs = 0
    for sc in det.get("scores", []):
        if sc.get("description") != "CURRENT": continue
        v = (sc.get("score") or {}).get("goals") or 0
        if sc.get("participant_id") == tid: g = v
        else: gs = v
    return g, gs

def adversario(det, tid):
    for p in det.get("participants", []):
        if p["id"] != tid: return p["name"]
    return "?"

def foi_casa(det, tid):
    for p in det.get("participants", []):
        if (p.get("meta") or {}).get("location") == "home":
            return p["id"] == tid
    return None

def registro_jogo(det, tid, ts, lid):
    own, adv = stats_do_time(det, tid)
    g, gs = placar(det, tid)
    return {"liga": lid, "ts": ts, "advNome": adversario(det, tid),
            "casa": foi_casa(det, tid),
            "own": own, "adv": adv, "gols": g, "golsSof": gs}

raiox_raw, jog_hist, acum_elenco, temporada = {}, {}, {}, {}
for tid, tname in teams.items():
    cheio = team_tier[tid] == 1
    jogos_t = lista_time(tid, 12 if cheio else 3)
    temporada[tid] = jogos_t
    limite_regs = 30 if cheio else 6
    regs, equipe, acum = [], {}, {}
    for jt in jogos_t[:limite_regs]:
        det = detalhe(jt["fid"])
        if not det: continue
        regs.append(registro_jogo(det, tid, jt["ts"], jt["liga"]))
        if not cheio: continue
        for lu in det.get("lineups", []):
            if lu.get("team_id") != tid: continue
            pid = lu.get("player_id")
            vals = {c: 0 for c in T_JOG.values()}
            for dd in (lu.get("details") or []):
                c = T_JOG.get(dd.get("type_id"))
                if c: vals[c] = (dd.get("data") or {}).get("value") or 0
            if vals["m"] <= 0: continue
            nome = nome_por_pid.get(pid) or lu.get("player_name")
            if pid in squads.get(tid, {}) and len(equipe.get(nome, [])) < 10:
                equipe.setdefault(nome, []).append({
                    "t": jt["ts"], "l": jt["liga"], "a": adversario(det, tid), "c": foi_casa(det, tid),
                    "m": vals["m"], "f": vals["f"], "o": vals["o"], "g": vals["g"],
                    "fc": vals["fc"], "fs": vals["fs"], "am": vals["am"], "vm": vals["vm"],
                    "ds": vals["ds"], "ps": vals["ps"]})
            a = acum.setdefault(pid, {"apps": 0, "f": 0, "o": 0, "fc": 0, "fs": 0, "df": 0, "min": 0, "g": 0, "ds": 0, "ps": 0})
            a["apps"] += 1; a["min"] += vals["m"]; a["g"] += vals["g"]
            a["f"] += vals["f"]; a["o"] += vals["o"]; a["fc"] += vals["fc"]; a["fs"] += vals["fs"]
            a["ds"] += vals["ds"]; a["ps"] += vals["ps"]
            for dd in (lu.get("details") or []):
                if dd.get("type_id") == 57:
                    a["df"] += (dd.get("data") or {}).get("value") or 0
    acum_elenco[tid] = acum
    geral = regs[:15]
    liga = {}
    for fx in semana:
        if tid not in (fx["homeId"], fx["awayId"]): continue
        lid = fx["ligaId"]
        tipo = LIGAS[lid][1]
        cap = 30 if tipo == "liga" else 20
        liga[str(lid)] = [r for r in regs if r["liga"] == lid][:cap]
    raiox_raw[str(tid)] = {"geral": geral, "liga": liga}
    jog_hist[str(tid)] = equipe
    print(f"  {tname} ({'T1' if cheio else 'T2'}): {len(geral)} jogos", flush=True)

# continentais: garante irmãs do mesmo grupo
for fx in semana:
    info = LIGAS[fx["ligaId"]]
    if info[1] != "continental": continue
    irmas = [l for l, i in LIGAS.items() if i[1] == "continental" and i[2] == info[2]]
    for tid in (fx["homeId"], fx["awayId"]):
        reg = raiox_raw[str(tid)]
        for l2 in irmas:
            if str(l2) not in reg["liga"]:
                reg["liga"][str(l2)] = [r for r in reg["geral"] if r["liga"] == l2]

# ================= 4. elencos (só tier 1) =================
elencos, top_por_time = {}, {}
for tid in teams:
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
                      "desarmes": round(a["ds"] / a["apps"], 2),
                      "passes": round(a["ps"] / a["apps"], 1),
                      "_pid": pid, "_min": a["min"], "_g": a["g"]})
    lista.sort(key=lambda x: x["media"], reverse=True)
    if lista: elencos[str(tid)] = lista
    top_por_time[tid] = [x for x in lista if x["apps"] >= 3][:3]

# ================= 5. cedidas + players destaque =================
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

# ================= 6. confronto direto =================
h2h, vistos = {}, {}
for fx in semana:
    a, b = fx["homeId"], fx["awayId"]
    cheio = liga_tier(fx["ligaId"]) == 1
    par = (min(a, b), max(a, b))
    if par not in vistos:
        lst = sm_paginado(f"/fixtures/head-to-head/{a}/{b}", include="state;participants;scores")
        fin, ids_h2h = [], set()
        for x in lst:
            if (x.get("state") or {}).get("short_name") not in FINALIZADO: continue
            if x["id"] in ids_h2h: continue  # a API às vezes repete fixtures entre páginas
            ids_h2h.add(x["id"])
            fin.append(x)
        fin.sort(key=lambda x: x["starting_at"], reverse=True)
        confs = []
        for x in fin[:12]:
            parts = x.get("participants", [])
            casa = next((p for p in parts if (p.get("meta") or {}).get("location") == "home"), None)
            fora = next((p for p in parts if (p.get("meta") or {}).get("location") == "away"), None)
            if not casa or not fora: continue
            if cheio:
                det = detalhe(x["id"])
                sH, _ = stats_do_time(det, casa["id"]); sA, _ = stats_do_time(det, fora["id"])
                gH, _ = placar(det, casa["id"]); gA, _ = placar(det, fora["id"])
            else:
                sH, sA = {}, {}
                gH = gA = 0
                for sc in x.get("scores", []):
                    if sc.get("description") != "CURRENT": continue
                    v = (sc.get("score") or {}).get("goals") or 0
                    if sc.get("participant_id") == casa["id"]: gH = v
                    else: gA = v
            def soma(*chaves):
                v = [s.get(c) for s in (sH, sA) for c in chaves if s.get(c) is not None]
                return int(sum(v)) if v else None
            confs.append({"ts": data_local(x["starting_at"]), "comp": liga_nome(x.get("league_id")),
                          "idH": casa["id"], "idA": fora["id"], "nH": casa["name"], "nA": fora["name"],
                          "gH": gH, "gA": gA, "sH": sH, "sA": sA,
                          "ca": soma("cantos"), "ct": soma("amarelos", "vermelhos"), "df": soma("defesas")})
        vistos[par] = confs
    h2h[str(fx["id"])] = vistos[par]
print("h2h ok", flush=True)

# ================= 7. escalações do último jogo =================
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
           "num": lu.get("jersey_number"),
           "pos": {24: "G", 25: "D", 26: "M", 27: "F"}.get(lu.get("position_id"), "M"),
           "grid": lu.get("formation_field")}
          for lu in det.get("lineups", [])
          if lu.get("team_id") == tid and lu.get("type_id") == TIPO_TITULAR]
    if xi:
        escalacoes["ultimas"][str(tid)] = {"ts": jogos_t[0]["ts"], "adv": adversario(det, tid),
                                            "formacao": formacao, "tecnico": tecnico, "xi": xi}
print(f"escalações: {len(escalacoes['ultimas'])}", flush=True)

# ================= 8. árbitros =================
arbitros, ref_stats_cache = {}, {}
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

# jogo a jogo dos árbitros (12 meses, ligas BR — mercado de cartões)
por_ref, fim_ref = {}, hoje
for _ in range(4):
    ini_ref = fim_ref - timedelta(days=90)
    for fx2 in sm_paginado(f"/fixtures/between/{ini_ref.isoformat()}/{fim_ref.isoformat()}",
                           filters=f"fixtureLeagues:{','.join(map(str, LIGAS_BR_REF))}",
                           include="referees.referee;statistics;participants;state"):
        if (fx2.get("state") or {}).get("short_name") not in FINALIZADO: continue
        ref2 = next(((r.get("referee") or {}) for r in fx2.get("referees", [])
                     if r.get("type_id") == REF_PRINCIPAL), None)
        if not ref2 or not ref2.get("id"): continue
        casa_id = next((p["id"] for p in fx2.get("participants", [])
                        if (p.get("meta") or {}).get("location") == "home"), None)
        am = vm = fl = amC = amF = 0
        for st in fx2.get("statistics", []):
            t = st.get("type_id"); v = (st.get("data") or {}).get("value") or 0
            if t == 84:
                am += v
                if st.get("participant_id") == casa_id: amC += v
                else: amF += v
            elif t == 83: vm += v
            elif t == 56: fl += v
        nomes = sorted(fx2.get("participants", []), key=lambda p: (p.get("meta") or {}).get("location") != "home")
        por_ref.setdefault(ref2["id"], []).append({
            "ts": data_local(fx2["starting_at"]), "jogo": " x ".join(p["name"] for p in nomes),
            "am": am, "amC": amC, "amF": amF, "vm": vm, "faltas": fl})
    fim_ref = ini_ref - timedelta(days=1)
for rid2 in por_ref:
    por_ref[rid2] = sorted(por_ref[rid2], key=lambda x: x["ts"], reverse=True)[:30]
for fid2, arb2 in arbitros.items():
    lst = por_ref.get(arb2.get("id"))
    if lst: arb2["ultimos"] = lst
print(f"árbitros com jogo a jogo: {sum(1 for a in arbitros.values() if a.get('ultimos'))}", flush=True)

# ================= 8b. catálogo COMPLETO de times (aba Times) =================
# todos os times das ligas assinadas; quem não está na agenda da semana ganha
# os últimos 10 jogos COM estatísticas completas (mesmas ~2 chamadas por time —
# a diferença é só o include; decisão do Pedro 07/08: perfil completo pra todos)
catalogo_times, escudos_cat, ids_cat = [], {}, set()
for lid in LIGAS:
    liga_d = sm(f"/leagues/{lid}", include="currentseason").get("data") or {}
    sid = (liga_d.get("currentseason") or {}).get("id")
    if not sid: continue
    for tm in sm_paginado(f"/teams/seasons/{sid}"):
        catalogo_times.append({"id": tm["id"], "nome": tm["name"], "liga": lid})
        if tm["id"] not in ids_cat:
            ids_cat.add(tm["id"])
            if tm.get("image_path"):
                escudos_cat[tm["name"]] = tm["image_path"].replace("https://cdn.sportmonks.com", "/smimg")
print(f"catálogo: {len(ids_cat)} times únicos nas {len(LIGAS)} ligas", flush=True)

lite_ids = [t for t in ids_cat if t not in teams]
for i, tid in enumerate(lite_ids):
    jogos_l, fim_l = [], hoje
    for _ in range(2):  # ~6 meses cobrem 10 jogos na maioria das ligas
        ini_l = fim_l - timedelta(days=90)
        for fx in sm_paginado(f"/fixtures/between/{ini_l.isoformat()}/{fim_l.isoformat()}/{tid}",
                              include="state;participants;scores;statistics"):
            if (fx.get("state") or {}).get("short_name") not in FINALIZADO: continue
            if fx.get("league_id") not in LIGAS: continue
            casa_p = next((p for p in fx.get("participants", []) if (p.get("meta") or {}).get("location") == "home"), None)
            fora_p = next((p for p in fx.get("participants", []) if (p.get("meta") or {}).get("location") == "away"), None)
            if not casa_p or not fora_p: continue
            eh_casa = casa_p["id"] == tid
            g = gs = 0
            for sc in fx.get("scores", []):
                if sc.get("description") != "CURRENT": continue
                v = (sc.get("score") or {}).get("goals") or 0
                if sc.get("participant_id") == tid: g = v
                else: gs = v
            own, adv = {}, {}
            for st in fx.get("statistics", []):
                campo = T_TIME.get(st.get("type_id"))
                if not campo: continue
                v = (st.get("data") or {}).get("value") or 0
                (own if st.get("participant_id") == tid else adv)[campo] = v
            jogos_l.append({"liga": fx["league_id"], "ts": data_local(fx["starting_at"]),
                            "advNome": (fora_p if eh_casa else casa_p)["name"],
                            "casa": eh_casa, "own": own, "adv": adv, "gols": g, "golsSof": gs})
        fim_l = ini_l - timedelta(days=1)
        if len(jogos_l) >= 10: break
    jogos_l.sort(key=lambda x: x["ts"], reverse=True)
    if jogos_l and str(tid) not in raiox_raw:
        raiox_raw[str(tid)] = {"geral": jogos_l[:10], "liga": {}}
    if (i + 1) % 50 == 0: print(f"  forma lite: {i+1}/{len(lite_ids)}", flush=True)
print(f"forma lite: {len(lite_ids)} times fora da semana", flush=True)

# ================= 9. monta dados.js =================
escudos = {}
for fx in semana:
    for nome, url in fx.pop("_escudos", {}).items():
        if url: escudos[nome] = url.replace("https://cdn.sportmonks.com", "/smimg")
for lista in elencos.values():
    for x in lista:
        x.pop("_pid", None); x.pop("_min", None); x.pop("_g", None)

catalogo = {str(lid): {"nome": v[0], "tipo": v[1], "grupo": v[2], "tier": v[3]}
            for lid, v in LIGAS.items()}
sc_semana = {"geradoEm": datetime.now(BRT).isoformat(), "fonte": "sportmonks",
             "ligas": catalogo, "ref_cedidas": round(ref_ced, 2),
             "fixtures": semana, "elencos": elencos, "raioxRaw": raiox_raw,
             "h2h": h2h, "jogHist": jog_hist, "escalacoes": escalacoes, "arbitros": arbitros,
             "catalogoTimes": catalogo_times}
for _nome, _url in escudos_cat.items():
    escudos.setdefault(_nome, _url)
sc_assets = {"fotos": fotos, "escudos": escudos}

destino = os.path.join(RAIZ, "app", "dados.js")
with open(destino, "w", encoding="utf-8") as f:
    f.write("window.SC_SEMANA=" + json.dumps(sc_semana, ensure_ascii=False, separators=(",", ":")))
    f.write(";\nwindow.SC_ASSETS=" + json.dumps(sc_assets, ensure_ascii=False, separators=(",", ":")) + ";\n")
print(f"OK dados.js: {round(os.path.getsize(destino)/1024/1024, 2)} MB · {len(semana)} jogos · "
      f"{len(teams)} times · {len(detalhe_cache)} fixtures detalhadas", flush=True)
