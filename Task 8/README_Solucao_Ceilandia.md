# Solução do Problema de Subtensão Severa - Alimentador CN15 (Ceilândia)

Este documento detalha a investigação e a resolução de uma anomalia estrutural identificada nas simulações elétricas do alimentador Residencial Ceilândia (CN15) utilizando o OpenDSS.

## 1. O Problema
Ao rodar as simulações de fluxo de potência para a Ceilândia, os relatórios apontavam um colapso quase total de tensão no alimentador:
* Mais de **95% das barras de Média Tensão (MT)** (cerca de 2.188 de 2.286) operavam com tensões abaixo de **0.80 p.u.** (o que na vida real representaria desligamentos em massa por subtensão severa e sobreaquecimento).
* As perdas técnicas calculadas pelo OpenDSS eram colossais (mais de 30% da potência injetada dissipava-se nos cabos).
* Inicialmente, suspeitou-se de erros no cálculo da geometria (distâncias dos cabos) ou na modelagem de cargas muito pesadas na ponta.

## 2. A Causa Raiz
A investigação revelou que o problema **não** estava na carga nem na extensão (distância) dos cabos, mas sim na forma como as **impedâncias das linhas** estavam sendo atribuídas durante a geração do modelo pelo arquivo `Expandir Alimentadores.py`.

A função `obter_impedancia_linha` tentava extrair a resistência (`R1`) e reatância (`X1`) lendo diretamente as colunas da camada SSDMT. Se os dados não estivessem explícitos ou o código do cabo (ex: `94_A4_3_1`) não fosse validado, o script acionava uma cláusula de salvaguarda (um *fallback* conservador):
```python
if length_km < 0.1:
    r1, x1 = 1.20, 0.70
```

Na prática, como quase 1.920 trechos curtos caíam nessa condição de fallback, o script atribuía compulsoriamente **R1 = 1.20 ohms/km** a toda a rede principal do alimentador. 
Para referência, 1.20 ohms/km é uma resistência altíssima, típica de cabos rurais monofásicos extremamente finos (como o cabo de aço cobreado 4 AWG). Ao aplicar essa resistência por toda uma rede urbana de grande porte de 17 km, a impedância em série se somou em dezenas de Ohms, criando um gargalo que derrubava a tensão.

## 3. A Solução
O problema foi resolvido através das seguintes atualizações no `Expandir Alimentadores.py`:

1. **Inclusão de Tabela de Condutores Típica:**
   Foi implementado o dicionário `IMPEDANCIAS_TIPICAS`, mapeando dezenas de códigos da coluna `TIP_CND` (Alumínio Nu, Cobre Nu, Cabos Isolados) para seus respectivos `R1` e `X1` de fábrica.
2. **Correção do Fallback (Valores Realistas):**
   Para ramais onde o cabo ainda seja desconhecido, as impedâncias de salvaguarda foram ajustadas para médias realistas do ambiente urbano:
   * Em vez de `1.20` ohms/km, o sistema agora adota valores mais realistas entre **0.30 e 0.70 ohms/km** (similar aos cabos CAA 336.4 ou CA 1/0 usados massivamente em Brasília).
3. **Limpeza e Estabilidade do Processamento:**
   Removemos os comandos `plt.show()` espalhados pelo código que pausavam indevidamente a geração das planilhas em execução *background*.

## 4. Resultados Finais
Após a regeneração dos arquivos `.dss` com a nova modelagem de impedâncias, a rede voltou imediatamente à normalidade elétrica esperada:

* **0 (zero) barras abaixo de 0.93 p.u.**
* **100% das barras do CN15 operando acima de 0.97 p.u.** 

O perfil de tensão provou-se excelente e compatível com as características reais de um grande circuito tronco bem projetado da Neoenergia Brasília.
