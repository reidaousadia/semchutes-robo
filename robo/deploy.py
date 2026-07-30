#!/usr/bin/env python3
"""Sem Chutes — ROBÔ: publica a pasta app/ no Netlify via API (sem drag-drop).

Token: env NETLIFY_TOKEN, ou linha NETLIFY_TOKEN=... no .env da raiz (local).
Site: adorable-crisp-5c2dc0 (semchutes.com.br).
Uso: python3 robo/deploy.py
"""
import io, json, os, sys, urllib.request, zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "adorable-crisp-5c2dc0.netlify.app"

TOKEN = os.environ.get("NETLIFY_TOKEN")
if not TOKEN:
    env = os.path.join(RAIZ, ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("NETLIFY_TOKEN="):
                TOKEN = line.strip().split("=", 1)[1]
if not TOKEN:
    sys.exit("NETLIFY_TOKEN ausente (env ou .env)")

app = os.path.join(RAIZ, "app")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for nome in sorted(os.listdir(app)):
        caminho = os.path.join(app, nome)
        if os.path.isfile(caminho) and not nome.startswith("."):
            z.write(caminho, nome)
dados = buf.getvalue()
print(f"zip: {round(len(dados)/1024/1024, 2)} MB", flush=True)

req = urllib.request.Request(
    f"https://api.netlify.com/api/v1/sites/{SITE}/deploys",
    data=dados, method="POST",
    headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/zip"})
with urllib.request.urlopen(req, timeout=300) as r:
    resp = json.load(r)
print(f"deploy: {resp.get('id')} · estado: {resp.get('state')}")
print("no ar em https://semchutes.com.br assim que processar (segundos).")
