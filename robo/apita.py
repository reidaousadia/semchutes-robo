#!/usr/bin/env python3
"""Sem Chutes — APITOU: vigia de escalações confirmadas.

Roda a cada ~10 min (GitHub Actions). Pra cada jogo do dia a até ~90 min do
apito inicial, consulta /fixtures/lineups; quando a escalação sai, posta o XI
no canal do Telegram (@apitoualertas) e marca em robo/estado.json pra não
repetir. Sai em segundos quando não há jogo por perto.

Env: API_FOOTBALL_KEY, TELEGRAM_TOKEN (ou .env na raiz, local).
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))
CANAL = "@apitoualertas"
LIGAS = {71: "Brasileirão", 72: "Série B", 73: "Copa do Brasil",
         11: "Sul-Americana", 13: "Libertadores"}
JANELA_MIN = 90          # começa a vigiar a 90 min do jogo
SEASON = 2026

def carrega_env(nome):
    v = os.environ.get(nome)
    if v: return v
    env = os.path.join(RAIZ, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith(nome + "="):
                return line.strip().split("=", 1)[1]
    return None

KEY = carrega_env("API_FOOTBALL_KEY") or sys.exit("API_FOOTBALL_KEY ausente")
TG = carrega_env("TELEGRAM_TOKEN") or sys.exit("TELEGRAM_TOKEN ausente")

def api(path, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"https://v3.football.api-sports.io{path}?{qs}",
                                 headers={"x-apisports-key": KEY})
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            time.sleep(0.3)
            return data.get("response", [])
        except Exception as e:
            print("retry", path, e, flush=True); time.sleep(4)
    return []

def telegram(texto):
    data = urllib.parse.urlencode({"chat_id": CANAL, "text": texto,
                                   "parse_mode": "Markdown"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{TG}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r).get("ok")

ESTADO_PATH = os.path.join(RAIZ, "robo", "estado.json")
estado = {"alertados": []}
if os.path.exists(ESTADO_PATH):
    estado = json.load(open(ESTADO_PATH))

agora = datetime.now(timezone.utc)
hoje_brt = datetime.now(BRT).date().isoformat()

# jogos do dia (5 chamadas) — só ligas cobertas
candidatos = []
for lid in LIGAS:
    for f in api("/fixtures", league=lid, season=SEASON, date=hoje_brt, timezone="America/Sao_Paulo"):
        if f["fixture"]["status"]["short"] != "NS": continue
        kickoff = datetime.fromisoformat(f["fixture"]["date"])
        falta = (kickoff - agora).total_seconds() / 60
        if -15 <= falta <= JANELA_MIN:
            candidatos.append((f, kickoff, falta))
print(f"{len(candidatos)} jogo(s) na janela de {JANELA_MIN} min", flush=True)

novos = 0
for f, kickoff, falta in candidatos:
    fid = f["fixture"]["id"]
    if fid in estado["alertados"]: continue
    lineups = api("/fixtures/lineups", fixture=fid)
    if not lineups: continue  # ainda não saiu — tenta na próxima rodada
    h, a = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
    hora = kickoff.astimezone(BRT).strftime("%H:%M")
    liga = LIGAS.get(f["league"]["id"], f["league"]["name"])
    partes = [f"🚨 *Apitou! Escalação confirmada*",
              f"⚽ *{h} x {a}* · {liga} · {hora}", ""]
    for b in lineups:
        xi = ", ".join(p["player"]["name"] for p in (b.get("startXI") or []))
        if not xi: continue
        form = f" ({b['formation']})" if b.get("formation") else ""
        partes.append(f"*{b['team']['name']}*{form}:")
        partes.append(xi)
        partes.append("")
    partes.append("📊 raio-x completo: semchutes.com.br")
    if telegram("\n".join(partes)):
        estado["alertados"].append(fid)
        novos += 1
        print(f"apitou: {h} x {a}", flush=True)

# poda ids antigos (mantém últimos 200)
estado["alertados"] = estado["alertados"][-200:]
json.dump(estado, open(ESTADO_PATH, "w"))
print(f"OK · {novos} alerta(s) novo(s)", flush=True)
