#!/usr/bin/env node
/* APITOU — melhor desajuste do dia (post diário do grupo VIP).
 *
 * Roda no GitHub Actions (Node) depois da coleta da manhã: carrega dados.js +
 * linhas.js de produção, calcula o ranking com AS MESMAS regras da aba
 * Desajustes (funções copiadas verbatim do app — ver REGRAS.md; qualquer
 * mudança na regra do app precisa ser espelhada aqui) e imprime em stdout a
 * mensagem pronta do post. O workflow manda essa mensagem pro Telegram do
 * Pedro, que encaminha pro grupo do WhatsApp (a API oficial do WhatsApp não
 * posta em grupos; automação não-oficial = risco de banimento do número).
 *
 * Uso: node robo/melhor_desajuste.js [dir-com-dados.js-e-linhas.js]
 */
"use strict";
const fs = require("fs");
const path = require("path");

const dir = process.argv[2] || path.join(__dirname, "..", "app");
const window = {};
// dados.js e linhas.js só atribuem em window.* — eval com window no escopo
new Function("window", fs.readFileSync(path.join(dir, "dados.js"), "utf8"))(window);
new Function("window", fs.readFileSync(path.join(dir, "linhas.js"), "utf8"))(window);

const SEM = window.SC_SEMANA || { fixtures: [] };
const JOG_HIST = SEM.jogHist || {};
const RAIOX_RAW = SEM.raioxRaw || {};
const LINHAS = window.SC_LINHAS || { jogos: {} };

/* ---- funções copiadas VERBATIM do app (prototipo.html) — não "melhorar" ---- */
function normNome(s){
  s = (s || "").toLowerCase();
  if (s.includes(",")) s = s.split(",").reverse().join(" ");
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z ]/g, " ").replace(/\s+/g, " ").trim();
}
function resolveJogador(nomeFeed, tids){
  const alvo = normNome(nomeFeed), alvoSem = alvo.replace(/ /g, "");
  const tokens = alvo.split(" ").filter(Boolean);
  const sobren = tokens[tokens.length - 1] || "";
  const candidatos = [];
  for (const tid of tids)
    for (const nome of Object.keys((SEM.jogHist || {})[String(tid)] || {})) candidatos.push([tid, nome]);
  for (const c of candidatos) if (normNome(c[1]).replace(/ /g, "") === alvoSem) return c;
  const porSobren = candidatos.filter(c => {
    const n = normNome(c[1]);
    return n.split(" ").includes(sobren) || (sobren.length > 4 && n.replace(/ /g, "").includes(sobren));
  });
  if (porSobren.length === 1) return porSobren[0];
  if (porSobren.length > 1 && tokens[0]){
    const porIni = porSobren.filter(c => normNome(c[1])[0] === tokens[0][0]);
    if (porIni.length === 1) return porIni[0];
  }
  return null;
}
function getHistJogador(tid, nome, janela){
  let jogos = [...(((JOG_HIST[String(tid)] || {})[nome]) || [])];
  jogos.sort((a, b) => b.t.localeCompare(a.t));
  return janela ? jogos.slice(0, janela) : jogos;
}
function getJogosRx(tid, janela){          // escopo "geral" (o ranking só usa esse)
  const reg = RAIOX_RAW[String(tid)];
  if (!reg) return [];
  const jogos = [...(reg.geral || [])];
  if (jogos.length && jogos[0].ts) jogos.sort((a, b) => b.ts.localeCompare(a.ts));
  return jogos.slice(0, janela);
}
const DJ_STAT_LBL = { fin: "finalizações", chutesGol: "chutes a gol", gols: "gols",
                      desarmes: "desarmes", faltas: "faltas cometidas", cartoes: "cartões" };
const DJ_SEL = { fin: g => g.f, chutesGol: g => g.o, gols: g => g.g, desarmes: g => g.ds,
                 faltas: g => g.fc, cartoes: g => (g.am != null ? (g.am || 0) + (g.vm || 0) : null) };
const DJ_CAP = { fin: 3, chutesGol: 3, gols: 2, desarmes: 3, faltas: 3, cartoes: 2,
                 tCantos: 4.5, tCartoes: 3, tGols: 2.5 };
const DJ_CAP_UNDER = { fin: 1.2, chutesGol: 1, desarmes: 1, faltas: 1 };
const DJ_TMETA = {
  cantos:  { chip: "tCantos",  lbl: "escanteios",
             own: j => j.own?.cantos ?? null,
             tot: j => (j.own?.cantos != null && j.adv?.cantos != null) ? j.own.cantos + j.adv.cantos : null },
  cartoes: { chip: "tCartoes", lbl: "cartões",
             own: j => j.own?.amarelos != null ? (j.own.amarelos || 0) + (j.own.vermelhos || 0) : null,
             tot: j => (j.own?.amarelos != null && j.adv?.amarelos != null)
                  ? (j.own.amarelos || 0) + (j.own.vermelhos || 0) + (j.adv.amarelos || 0) + (j.adv.vermelhos || 0) : null },
  gols:    { chip: "tGols",    lbl: "gols",
             own: j => j.gols ?? null,
             tot: j => (j.gols != null && j.golsSof != null) ? j.gols + j.golsSof : null },
};

/* ---- ranking (mesma lógica do renderDesajustes, filtro "hoje") ---- */
const janela = 10;
const dStr = d => d.toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" });
const hojeS = dStr(new Date());
const passaDia = k => k && dStr(new Date(k)) === hojeS;

const fxPorId = {};
for (const fx of SEM.fixtures || []) if (fx && fx.id != null) fxPorId[String(fx.id)] = fx;

const PRIO = { betano: 0, bet365: 1, estrela: 2, altenar: 3 };
const porChave = new Map();
for (const [fid, jg] of Object.entries(LINHAS.jogos || {})){
  const fx = fxPorId[fid]; if (!fx || !passaDia(fx.kickoff)) continue;
  for (const [nomeFeed, stats] of Object.entries(jg.jogador || {})){
    const res = resolveJogador(nomeFeed, [fx.homeId, fx.awayId]);
    if (!res) continue;
    const [tid, nome] = res;
    for (const [stat, reg] of Object.entries(stats)){
      if (!DJ_SEL[stat] || !reg.l) continue;
      const escada = Object.entries(reg.l).map(([L, o]) => [parseFloat(L), o])
        .filter(([L, o]) => !isNaN(L) && o != null).sort((a, b) => a[0] - b[0]);
      if (!escada.length) continue;
      let linha = null;
      if (reg.p != null && reg.l[String(reg.p)] >= 1.5) linha = reg.p;
      else {
        const jogaveis = escada.filter(([L, o]) => o >= 1.5);
        if (!jogaveis.length) continue;
        linha = jogaveis[0][0];
      }
      const hist = getHistJogador(tid, nome, 15).filter(g => (g.m || 0) > 0);
      const amostra = hist.map(g => ({ v: DJ_SEL[stat](g) })).filter(p => p.v != null).slice(0, janela);
      const vals = amostra.map(p => p.v);
      if (vals.length < 5) continue;
      const media = vals.reduce((a, b) => a + b, 0) / vals.length;
      const edgeOver = media - linha;
      if (Math.abs(edgeOver) > (DJ_CAP[stat] || 3)) continue;
      if (edgeOver < 0) continue;            // props de jogador: over apenas (REGRAS.md #3)
      const chave = `${tid}:${nome}:${stat}`;
      const atual = porChave.get(chave);
      if (atual && (PRIO[atual.casa] ?? 9) <= (PRIO[reg.c] ?? 9)) continue;
      porChave.set(chave, { fx, nome, stat, statLbl: DJ_STAT_LBL[stat], linha, media,
        edge: edgeOver, dir: "over", casa: reg.c, n: vals.length,
        hit: vals.filter(v => v > linha).length, ehTime: false });
    }
  }
  for (const [tipo, subs] of Object.entries(jg.time || {})){
    const meta = DJ_TMETA[tipo]; if (!meta) continue;
    for (const [sub, ladder] of Object.entries(subs)){
      let vals;
      const valsDe = (tid2, getter) => getJogosRx(tid2, 15)
        .map(j => getter(j)).filter(v => v != null).slice(0, janela);
      if (sub === "total") vals = [...valsDe(fx.homeId, meta.tot), ...valsDe(fx.awayId, meta.tot)];
      else vals = valsDe(sub === "t1" ? fx.homeId : fx.awayId, meta.own);
      if (vals.length < 5) continue;
      const media = vals.reduce((a, b) => a + b, 0) / vals.length;
      const escadaDe = obj => Object.entries(obj || {}).map(([L, o]) => [parseFloat(L), o])
        .filter(([L, o]) => !isNaN(L) && o != null).sort((a, b) => a[0] - b[0]);
      const direcoes = [["over", escadaDe(ladder)],
                        ["under", escadaDe(((jg.timeU || {})[tipo] || {})[sub])]];
      for (const [rdir, escada] of direcoes){
        const jogaveis = escada.filter(([L, o]) => o >= 1.5);
        if (!jogaveis.length) continue;
        const linha = rdir === "over" ? jogaveis[0][0] : jogaveis[jogaveis.length - 1][0];
        const edge = rdir === "over" ? media - linha : linha - media;
        if (edge <= 0) continue;
        const cap = rdir === "under" ? (DJ_CAP_UNDER[meta.chip] ?? (DJ_CAP[meta.chip] || 4)) : (DJ_CAP[meta.chip] || 4);
        if (edge > cap) continue;
        const nome = sub === "total" ? `${fx.home} x ${fx.away}` : sub === "t1" ? fx.home : fx.away;
        porChave.set(`time:${fid}:${tipo}:${sub}:${rdir}`, { fx, nome, linha, media, edge, dir: rdir,
          statLbl: `${meta.lbl}${sub === "total" ? " na partida" : ""}`, n: Math.min(vals.length, janela * (sub === "total" ? 2 : 1)),
          hit: vals.filter(v => rdir === "over" ? v > linha : v < linha).length, ehTime: true });
      }
    }
  }
}

const rows = [...porChave.values()].sort((a, b) => b.edge - a.edge);
if (!rows.length){
  console.log("SEM_DESAJUSTE_HOJE");
  process.exit(0);
}
const r = rows[0];
const fmt = n => String(Math.round(n * 10) / 10).replace(".", ",");
const hora = new Date(r.fx.kickoff).toLocaleTimeString("pt-BR",
  { hour: "2-digit", minute: "2-digit", timeZone: "America/Sao_Paulo" });
const lado = r.dir === "over" ? "Mais de" : "Menos de";
const msg = [
  `🎯 DESAJUSTE DO DIA — APITOU!`,
  ``,
  `${r.ehTime ? "🏟" : "👤"} ${r.nome}`,
  `⚽ ${r.fx.home} x ${r.fx.away} · hoje ${hora}`,
  ``,
  `📊 ${lado} ${String(r.linha).replace(".", ",")} ${r.statLbl}`,
  `📈 Média APITOU: ${fmt(r.media)} — ${r.dir === "over" ? "acima" : "abaixo"} da linha em ${fmt(r.edge)}`,
  `✅ Bateu em ${r.hit} dos últimos ${r.n} jogos com dado`,
  ``,
  `Os números falam. 🟢⚫`,
  `Veja o ranking completo: https://apitou.com.br/#/desajustes`,
].join("\n");
console.log(msg);
