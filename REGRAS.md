# REGRAS DO PRODUTO — Desajustes (fonte da verdade)

> Estas regras foram definidas pelo Pedro. NENHUMA pode ser alterada, "refinada"
> ou flexibilizada em código sem aprovação explícita dele. O validador
> (`robo/valida_linhas.py`) falha o pipeline se o dado violar qualquer uma.

1. **Regra de ouro**: toda linha exibida tem odd REAL, COLETADA, ≥ 1,50, na
   direção exata (over pela escada do "Mais de", under pela do "Menos de").
   Zero inferência, zero espelhamento de odds.
2. **Linha-base**: a linha jogável que maximiza o edge —
   over = MENOR linha com odd ≥ 1,50 · under = MAIOR linha com odd ≥ 1,50.
   Props de jogador: a linha principal da casa (mainLine) vale se for jogável.
3. **Props de jogador são mercados de marco** ("Mais de" apenas). Não existe
   under de jogador em casa nenhuma → nunca exibir.
4. **Under só em mercados de duas vias**: escanteios, cartões e gols de time e
   de partida — sempre ancorado na escada do "Menos de" coletada.
5. **Referência = 10 amostras válidas** (completa com jogo mais antigo com dado).
   Jogo não disputado (0 minutos) ou sem a estatística: fora da média, nunca
   vira zero.
6. **Caps de sanidade**: desvio acima do plausível da estatística = homônimo ou
   viés de contagem, não oportunidade (caps em DJ_CAP/DJ_CAP_UNDER no app).
7. **Vocabulário do app**: linha, média, "passou/ficou abaixo em X de N".
   Nunca: odd, cotação, aposta, nome de casa (App Store).
8. **Cores**: ciano = marca · verde #2AE86B = positivo/bateu · rosa #FE2C55 =
   negativo/não bateu · dourado = estrela/favorito · cinza = neutro/sem dado.
9. **Nenhum número sobrepõe outro número** (design).
10. **Relato**: toda explicação sobre um jogo/linha específica exige conferência
    do fixture ID no dado bruto antes de afirmar qualquer coisa.
11. **Melhor odd multi-casas é o critério**: as escadas fundem TODAS as casas
    coletadas ficando com a melhor odd por linha; a jogabilidade (≥ 1,50) é
    julgada pela melhor odd. Nome de casa NUNCA aparece no app (política Apple).
12. **Quarentena**: escada com monotonia quebrada na zona de decisão (odds ≤ 3,0)
    é podada pelo coletor; o validador é o portão final — violou, não publica.
