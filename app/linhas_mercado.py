#!/usr/bin/env python3
"""Apitou — coletor de LINHAS DE MERCADO pra aba Desajustes.

Fontes:
  · OddsPapi (plano pago 08/08): betano.bet.br + bet365 — player props
    (finalizações e chutes a gol do jogador, com mainLine da casa) + mercados
    de time. 1 request por casa pega a liga inteira.
  · Altenar (feed público, grátis): linhas de time (escanteios/cartões/gols) e
    props do grupo EstrelaBet/LotoGreen — via robo/linhas_altenar.py, cujo
    app/linhas.js é mesclado se existir.

Saída app/linhas.js → window.SC_LINHAS = { geradoEm, jogos: { "<fixtureId>": {
  kickoff,
  jogador: { "Nome Como Veio": { fin|chutesGol: { p: linhaPrincipal, c: "betano"|"bet365",
             l: {"1.5": oddOver, ...} } } },
  time: { cantos|cartoes|gols: { total|t1|t2: {"9.5": oddOver, ...} } } } } }

Só a LINHA numérica vai pro app; odd fica como régua interna (não exibida).
Uso: python3 robo/linhas_mercado.py   (chave: ODDSPAPI_KEY no .env local ou do AcheiSure)
Custo: 2 requests OddsPapi por execução (3 execuções/dia = ~180/mês de 5.000).
"""
import json, os, subprocess, sys, time, unicodedata, re
from datetime import datetime, timezone, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRT = timezone(timedelta(hours=-3))
SCRATCH = os.path.dirname(os.path.abspath(__file__))

def acha_chave():
    for env in (os.path.join(RAIZ, ".env"), os.path.expanduser("~/Claude/Surebet/.env")):
        if os.path.exists(env):
            for l in open(env):
                if l.startswith("ODDSPAPI_KEY="):
                    return l.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("ODDSPAPI_KEY não encontrada")

KEY = acha_chave()
CASAS = [("betano.bet.br", "betano"), ("bet365", "bet365"), ("estrelabet", "estrela")]
TORNEIOS = "325,390"          # Série A e B (ids OddsPapi)
# Player props OddsPapi: market → chave Apitou; outcomes "N+" = linha N-0.5
M_PROPS = {"10743": "fin", "10753": "chutesGol"}

def curl(url):
    """urllib toma 403 do Cloudflare — curl passa"""
    r = subprocess.run(["curl", "-s", "-H", "Accept: application/json", url],
                       capture_output=True, text=True, timeout=90)
    return json.loads(r.stdout)

def norm(s):
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)

# nomes Apitou → fragmento presente no nome oficial longo do OddsPapi
ALIAS = {"athleticopr": "paranaense", "atleticomg": "atleticomineiro",
         "vasco": "vascodagama", "americamineiro": "americamg"}
def casa_time(nome_apitou, nome_feed):
    a, f = norm(nome_apitou), norm(nome_feed)
    a = ALIAS.get(a, a)
    return a in f or f in a

def main():
    # fixtures Apitou (dados.js) → mapa pra casar com o feed
    src = open(os.path.join(RAIZ, "app", "dados.js"), encoding="utf-8").read()
    i = src.index("window.SC_SEMANA=")
    sem, _ = json.JSONDecoder().raw_decode(src[i + len("window.SC_SEMANA="):].lstrip())
    fixtures = sem.get("fixtures", [])

    # participants OddsPapi (id→nome) — cacheado em disco, muda pouco (1 req quando falta)
    part_cache = os.path.join(SCRATCH, "oddspapi_participants.json")
    if os.path.exists(part_cache):
        participantes = json.load(open(part_cache))
    else:
        participantes = curl(f"https://api.oddspapi.io/v4/participants?sportId=10&apiKey={KEY}")
        json.dump(participantes, open(part_cache, "w"))
    if isinstance(participantes, list):
        participantes = {str(p.get("participantId") or p.get("id")): (p.get("name") or "") for p in participantes}

    por_data = {}
    for fx in fixtures:
        por_data.setdefault(fx["kickoff"][:10], []).append(fx)

    def acha_fixture(n1, n2, data_ev):
        for fx in por_data.get(data_ev, []):
            if casa_time(fx["home"], n1) and casa_time(fx["away"], n2):
                return fx
        return None

    jogos = {}
    for idx, (slug, apelido) in enumerate(CASAS):
        if idx: time.sleep(8)   # cooldown do endpoint (rate limit do OddsPapi)
        feed = None
        for tent in range(2):
            feed = curl(f"https://api.oddspapi.io/v4/odds-by-tournaments?bookmaker={slug}"
                        f"&tournamentIds={TORNEIOS}&oddsFormat=decimal&apiKey={KEY}")
            if isinstance(feed, list): break
            print(f"{slug}: rate limit/erro — aguardando 30s ({str(feed)[:80]})", flush=True)
            time.sleep(30)
        if not isinstance(feed, list):
            print(f"{slug}: desistindo nesta rodada", flush=True)
            continue
        casados = 0
        for ev in feed:
            n1 = participantes.get(str(ev.get("participant1Id")), "")
            n2 = participantes.get(str(ev.get("participant2Id")), "")
            data_ev = str(ev.get("startTime", ""))[:10]
            fx = acha_fixture(n1, n2, data_ev)
            if not fx: continue
            corpo = (ev.get("bookmakerOdds") or {}).get(slug) or {}
            jog = jogos.setdefault(str(fx["id"]), {"kickoff": fx["kickoff"], "jogador": {}, "time": {}})
            achou = False
            for mid, stat in M_PROPS.items():
                m = (corpo.get("markets") or {}).get(mid)
                if not m: continue
                for oid, oc in (m.get("outcomes") or {}).items():
                    # outcome "N+" → linha N-0.5 (10744="1+" → 0.5; base = market id + 1)
                    try: mais = int(oid) - int(mid) - 1 + 1   # 10744-10743 = 1 → "1+"
                    except ValueError: continue
                    if mais < 1: continue
                    linha = mais - 0.5
                    for p in (oc.get("players") or {}).values():
                        nome, preco = p.get("playerName"), p.get("price")
                        if not nome or preco is None or not p.get("active", True): continue
                        reg = jog["jogador"].setdefault(nome, {}).setdefault(stat, {"p": None, "c": apelido, "l": {}})
                        # betano é a referência; bet365 só preenche quem faltou
                        if reg["c"] != apelido and reg["l"]: continue
                        reg["c"] = apelido
                        reg["l"][str(linha)] = preco
                        if p.get("mainLine"): reg["p"] = linha
                        achou = True
            casados += 1 if achou else 0
        print(f"{slug}: {casados} jogos com props casados", flush=True)

    # linha principal ausente → deduz: a linha cuja odd do over está mais perto de 1.90
    for j in jogos.values():
        for stats in j["jogador"].values():
            for reg in stats.values():
                if reg["p"] is None and reg["l"]:
                    reg["p"] = float(min(reg["l"], key=lambda L: abs(reg["l"][L] - 1.9)))

    # mescla linhas de TIME do coletor Altenar (JSON intermediário, formato próprio)
    alt_path = os.path.join(RAIZ, "robo", "linhas_altenar.json")
    if os.path.exists(alt_path):
        try:
            alt = json.load(open(alt_path, encoding="utf-8"))
            for fid, aj in (alt.get("jogos") or {}).items():
                alvo = jogos.setdefault(fid, {"kickoff": aj.get("kickoff"), "jogador": {}, "time": {}})
                if aj.get("time"): alvo["time"] = aj["time"]
                # props Altenar só preenchem jogador que as casas pagas não trouxeram
                for nome, stats in (aj.get("jogador") or {}).items():
                    for stat, reg in stats.items():
                        alvo["jogador"].setdefault(nome, {}).setdefault(stat,
                            {"p": reg.get("principal"), "c": "altenar",
                             "l": {k: v for k, v in (reg.get("linhas") or {}).items()}})
        except Exception as e:
            print("merge altenar falhou:", e, flush=True)

    payload = {"geradoEm": datetime.now(BRT).isoformat(), "jogos": jogos}
    destino = os.path.join(RAIZ, "app", "linhas.js")
    with open(destino, "w", encoding="utf-8") as f:
        f.write("window.SC_LINHAS=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")
    tot_j = sum(len(j["jogador"]) for j in jogos.values())
    print(f"OK linhas.js: {len(jogos)} jogos · {tot_j} jogadores com linha · "
          f"{round(os.path.getsize(destino)/1024)} KB", flush=True)

if __name__ == "__main__":
    main()
