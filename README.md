# Sem Chutes — robô

Atualiza https://semchutes.com.br automaticamente.

- `app/` — o site (index.html + config Netlify). `dados.js` é gerado na hora, não fica no repo.
- `robo/coleta.py` — coleta diária completa (API-Football) e gera `app/dados.js`.
- `robo/deploy.py` — publica `app/` no Netlify via API.
- Workflow `atualiza-site` roda todo dia 06:00 (Brasília) e pode ser disparado manualmente.

Chaves ficam em **Settings → Secrets and variables → Actions** (nunca no código):
`API_FOOTBALL_KEY`, `NETLIFY_TOKEN`.
