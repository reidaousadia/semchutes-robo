#!/usr/bin/env python3
"""Apitou — APITOU: vigia PLANTONISTA de escalações confirmadas.

O agendador do GitHub Actions atrasa (cron */10 vira ~1x/hora na prática).
Solução: cada acionamento vira um PLANTÃO — o script fica até ~55 min acordado,
checando escalações a cada 5 min, e sai antes se não houver jogo por perto.
Com acionamentos ~de hora em hora, a cobertura fica contínua.

Quando a escalação sai: posta o XI no canal (@apitoualertas) e marca em
robo/estado.json (commitado pelo workflow) pra nunca repetir alerta.
O grupo de concorrência do workflow garante 1 plantão por vez (estado serializado).

Env: API_FOOTBALL_KEY, TELEGRAM_TOKEN (ou .env na raiz, local).
"""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))
CANAL = "@apitoualertas"
LIGAS = {71: "Brasileirão", 72: "Série B", 73: "Copa do Brasil",
         11: "Sul-Americana", 13: "Libertadores"}
JANELA_MIN = 90          # começa a vigiar a 90 min do apito inicial
TOLERANCIA_MIN = 15      # segue tentando até 15 min depois do apito
PLANTAO_SEG = 55 * 60    # duração máxima de um plantão
CICLO_SEG = 5 * 60       # intervalo entre checagens dentro do plantão
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

# ---------------- jogos do dia (1 vez por plantão; 5 chamadas) ----------------
hoje_brt = datetime.now(BRT).date().isoformat()
candidatos = []
for lid in LIGAS:
    for f in api("/fixtures", league=lid, season=SEASON, date=hoje_brt, timezone="America/Sao_Paulo"):
        if f["fixture"]["status"]["short"] != "NS": continue
        candidatos.append({"f": f, "fid": f["fixture"]["id"],
                           "kickoff": datetime.fromisoformat(f["fixture"]["date"])})
print(f"{len(candidatos)} jogo(s) hoje ({hoje_brt})", flush=True)
if not candidatos:
    salva_estado(); print("sem jogos — plantão encerrado"); sys.exit(0)

def apita(c):
    """Consulta a escalação; se saiu, posta no canal. True se alertou."""
    lineups = api("/fixtures/lineups", fixture=c["fid"])
    if not lineups: return False
    f = c["f"]
    h, a = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
    hora = c["kickoff"].astimezone(BRT).strftime("%H:%M")
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
        estado["alertados"].append(c["fid"])
        salva_estado()
        print(f"APITOU: {h} x {a}", flush=True)
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
    # ninguém na janela e ninguém ENTRA na janela até o fim do plantão → dorme cedo
    entra_em_breve = any(falta(c) - JANELA_MIN*60 < restante for c in a_caminho)
    if not na_janela and not entra_em_breve:
        print("nada pra vigiar no restante do plantão — encerrando cedo"); break
    time.sleep(CICLO_SEG)

salva_estado()
print("OK — plantão concluído", flush=True)
