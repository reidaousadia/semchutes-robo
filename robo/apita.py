#!/usr/bin/env python3
"""Apitou — APITOU: vigia PLANTONISTA de escalações confirmadas (fonte: Sportmonks).

Migrado da API-Football em 05/08/2026 após teste A/B lado a lado:
a Sportmonks publica a escalação ~T-72min antes do apito; a API-Football, ~T-29min.
45 minutos de vantagem = alerta útil pro apostador agir antes da linha mexer.

O agendador do GitHub Actions atrasa (cron */10 vira ~1x/hora na prática).
Solução: cada acionamento vira um PLANTÃO — o script fica até ~55 min acordado,
checando escalações a cada 5 min, e sai antes se não houver jogo por perto.
Com acionamentos ~de hora em hora, a cobertura fica contínua.

Quando a escalação sai (XI completo dos DOIS times): posta no canal
(@apitoualertas) e marca em robo/estado.json (commitado pelo workflow)
pra nunca repetir alerta. Concorrência: 1 plantão por vez.

Env: SPORTMONKS_TOKEN, TELEGRAM_TOKEN (ou .env na raiz, local).
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))
CANAL = "@apitoualertas"
LIGAS = {648: "Brasileirão", 651: "Série B", 654: "Copa do Brasil",
         1116: "Sul-Americana", 1122: "Libertadores"}
JANELA_MIN = 100         # começa a vigiar a 100 min do apito (Sportmonks publica ~T-75)
TOLERANCIA_MIN = 15      # segue tentando até 15 min depois do apito
PLANTAO_SEG = 55 * 60    # duração máxima de um plantão
CICLO_SEG = 5 * 60       # intervalo entre checagens dentro do plantão
TIPO_TITULAR = 11
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36",
      "Accept": "application/json"}

def carrega_env(nome):
    v = os.environ.get(nome)
    if v: return v
    env = os.path.join(RAIZ, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith(nome + "="):
                return line.strip().split("=", 1)[1]
    return None

TOKEN = carrega_env("SPORTMONKS_TOKEN") or sys.exit("SPORTMONKS_TOKEN ausente")
TG = carrega_env("TELEGRAM_TOKEN") or sys.exit("TELEGRAM_TOKEN ausente")

def sm(path, **params):
    params["api_token"] = TOKEN
    qs = urllib.parse.urlencode(params, safe=";:,.")
    req = urllib.request.Request(f"https://api.sportmonks.com/v3/football{path}?{qs}", headers=UA)
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            time.sleep(0.4)
            return data
        except Exception as e:
            print("retry", path, e, flush=True); time.sleep(4)
    return {}

def push_fcm(titulo, corpo):
    """Dispara push nativo pro tópico 'escalacoes' via FCM (Android/iOS).
    Silencioso se o secret não existir — o Telegram continua sendo o canal principal."""
    sa = os.environ.get("FCM_SERVICE_ACCOUNT")
    if not sa: return False
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests as garq
        info = json.loads(sa)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
        creds.refresh(garq.Request())
        req = urllib.request.Request(
            f"https://fcm.googleapis.com/v1/projects/{info['project_id']}/messages:send",
            data=json.dumps({"message": {
                "topic": "escalacoes",
                "notification": {"title": titulo, "body": corpo},
                "apns": {"payload": {"aps": {"sound": "default", "badge": 1}}},
                "android": {"priority": "HIGH"},
            }}).encode(),
            headers={"Authorization": f"Bearer {creds.token}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = r.status == 200
        if ok: print("push FCM enviado", flush=True)
        return ok
    except Exception as e:
        print("push fcm falhou:", e, flush=True)
        return False

def telegram(texto):
    data = urllib.parse.urlencode({"chat_id": CANAL, "text": texto,
                                   "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TG}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r).get("ok")
    except Exception as e:
        print("telegram falhou:", e, flush=True)
        return False

ESTADO_PATH = os.path.join(RAIZ, "robo", "estado.json")
estado = {"alertados": []}
if os.path.exists(ESTADO_PATH):
    estado = json.load(open(ESTADO_PATH))

def salva_estado():
    estado["alertados"] = estado["alertados"][-200:]
    json.dump(estado, open(ESTADO_PATH, "w"))

# ---------------- jogos do dia em BRT (1 varredura por plantão) ----------------
hoje_brt = datetime.now(BRT).date()
d1, d2 = hoje_brt.isoformat(), (hoje_brt + timedelta(days=1)).isoformat()
ids_ligas = ",".join(str(l) for l in LIGAS)
candidatos, page = [], 1
while True:
    r = sm(f"/fixtures/between/{d1}/{d2}", include="participants;state",
           filters=f"fixtureLeagues:{ids_ligas}", per_page=50, page=page)
    for f in r.get("data", []):
        if (f.get("state") or {}).get("short_name") != "NS": continue
        ko = datetime.fromisoformat(f["starting_at"]).replace(tzinfo=timezone.utc)
        if ko.astimezone(BRT).date() != hoje_brt: continue   # datas da API são UTC
        parts = f.get("participants", [])
        casa = next((p["name"] for p in parts if (p.get("meta") or {}).get("location") == "home"), "?")
        fora = next((p["name"] for p in parts if (p.get("meta") or {}).get("location") == "away"), "?")
        candidatos.append({"fid": f["id"], "kickoff": ko, "casa": casa, "fora": fora,
                           "liga": LIGAS.get(f.get("league_id"), "")})
    if not (r.get("pagination") or {}).get("has_more"): break
    page += 1
print(f"{len(candidatos)} jogo(s) hoje ({hoje_brt})", flush=True)
if not candidatos:
    salva_estado(); print("sem jogos — plantão encerrado"); sys.exit(0)

def apita(c):
    """Consulta a escalação na Sportmonks; se os DOIS XIs saíram, posta. True se alertou."""
    det = sm(f"/fixtures/{c['fid']}", include="lineups;formations").get("data") or {}
    lus = [l for l in det.get("lineups", []) if l.get("type_id") == TIPO_TITULAR]
    if len(lus) < 22: return False   # espera a escalação COMPLETA dos dois times
    por_time = {}
    for l in lus:
        por_time.setdefault(l.get("team_id"), []).append(l)
    formacoes = {f.get("participant_id"): f.get("formation")
                 for f in det.get("formations", [])}
    nomes_time = {p["id"]: p["name"] for p in det.get("participants", [])} or None

    hora = c["kickoff"].astimezone(BRT).strftime("%H:%M")
    partes = [f"🚨 *Apitou! Escalação confirmada*",
              f"⚽ *{c['casa']} x {c['fora']}* · {c['liga']} · {hora}", ""]
    # mandante primeiro; ordena o XI pela posição no campo (formation_field "linha:coluna")
    ordem_grid = lambda l: tuple(int(x) for x in (l.get("formation_field") or "9:9").split(":"))
    times_ordenados = sorted(por_time.items(),
                             key=lambda kv: 0 if (nomes_time or {}).get(kv[0]) == c["casa"] else 1)
    for tid, xi in times_ordenados:
        nome = (nomes_time or {}).get(tid) or ""
        form = formacoes.get(tid)
        xi = sorted(xi, key=ordem_grid)
        partes.append(f"*{nome}*{f' ({form})' if form else ''}:")
        partes.append(", ".join(l.get("player_name") or "?" for l in xi))
        partes.append("")
    partes.append("📊 raio-x completo: apitou.com.br")
    if telegram("\n".join(partes)):
        estado["alertados"].append(c["fid"])
        salva_estado()
        push_fcm("🚨 Apitou! Escalação confirmada",
                 f"{c['casa']} x {c['fora']} · {c['liga']} · {hora} — toca pra ver o raio-x completo")
        print(f"APITOU: {c['casa']} x {c['fora']}", flush=True)
        return True
    return False

# ---------------- o plantão ----------------
t0 = time.time()
rodada = 0
while True:
    rodada += 1
    agora = datetime.now(timezone.utc)
    def falta(c): return (c["kickoff"] - agora).total_seconds()
    na_janela = [c for c in candidatos if c["fid"] not in estado["alertados"]
                 and -TOLERANCIA_MIN*60 <= falta(c) <= JANELA_MIN*60]
    a_caminho = [c for c in candidatos if c["fid"] not in estado["alertados"]
                 and falta(c) > JANELA_MIN*60]
    novos = sum(1 for c in na_janela if apita(c))
    restante = PLANTAO_SEG - (time.time() - t0)
    print(f"rodada {rodada}: {len(na_janela)} na janela · {novos} alerta(s) · "
          f"{len(a_caminho)} a caminho · restam {int(restante/60)} min de plantão", flush=True)
    if restante <= CICLO_SEG:
        print("fim do plantão (tempo)"); break
    entra_em_breve = any(falta(c) - JANELA_MIN*60 < restante for c in a_caminho)
    if not na_janela and not entra_em_breve:
        print("nada pra vigiar no restante do plantão — encerrando cedo"); break
    time.sleep(CICLO_SEG)

salva_estado()
print("OK — plantão concluído", flush=True)
