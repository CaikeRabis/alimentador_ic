# Estudo de Fluxo de Potência e Sensibilidade de Carga - BDGD Neoenergia Brasília

Este repositório contém os scripts de simulação e análise do sistema de distribuição de energia elétrica da região central de Brasília, utilizando dados reais da **BDGD (Base de Dados de Agências Distribuidoras)** da Neoenergia Brasília e o motor de cálculo **OpenDSS** via interface Python (`py_dss_interface`).

---

## 📌 Entendimento Geral do Sistema (Até o Momento)

As simulações iniciais focaram no **Alimentador ES01**, responsável pelo atendimento de cargas institucionais críticas na região do Setor de Administração Federal Sul (SAFS), englobando órgãos como o STJ, TST e TSE.

A análise combinada de **Perfil de Tensão ($p.u.$)** e **Fluxo de Corrente ($A$)** sob diferentes cenários de estresse revelou um comportamento característico de redes de distribuição centrais altamente robustas:

* **Perfil de Tensão Plano:** Inicialmente, a plotagem misturava barras de Média Tensão ($13.8 \text{ kV}$) e Baixa Tensão ($0.38 \text{ kV}$), gerando uma queda vertical abrupta artificial. Após a filtragem e ordenação por distância, constatou-se que a tensão na Média Tensão permanece praticamente estável (flutuando muito próxima a $1.0 \text{ p.u.}$) do início ao fim do circuito.
* **Justificativa Geográfica e Elétrica:** O alimentador ES01 é eletricamente curto (cerca de $1$ a $1.5 \text{ km}$ de extensão total) e utiliza condutores de grande bitola (baixa impedância). Fisicamente, o circuito não acumula queda de resistência suficiente para gerar afundamentos de tensão expressivos ($\Delta V$), mesmo quando a carga é multiplicada por 20x.
* **Gargalo Térmico vs. Regulatório:** O estudo provou que o limitador deste sistema **não é o critério de tensão do PRODIST (ANEEL)**, mas sim a **capacidade térmica dos condutores**. No cenário de estresse severo, a tensão permanece dentro dos limites regulatórios, mas a corrente ultrapassa os $2000 \text{ A}$, o que causaria a atuação das proteções ou a queima física dos cabos (cuja capacidade real gira em torno de $300\text{ A}$ a $400\text{ A}$) muito antes de a tensão colapsar.

---

## 🔍 O que Estamos Analisando?

* **Qualidade do Produto (Tensão em p.u.):** Avaliação de conformidade com os limites de regime permanente do PRODIST Módulo 8 (subtensão e sobretensão).
* **Segurança de Infraestrutura (Corrente em Ampères):** Verificação de carregamento térmico e riscos de sobrecarga em linhas e transformadores.
* **Hosting Capacity (Capacidade de Suporte):** Análise do comportamento do circuito sob injeção de cargas críticas concentradas no fim da linha ou aumentos sazonais escalados.

---

## 🚀 Próxima Etapa: Expansão para a Asa Sul

Como o alimentador atual (ES01) apresentou um comportamento muito rígido devido à sua curta extensão e robustez institucional, a próxima tarefa do projeto consistirá em ampliar o escopo geográfico e elétrico da simulação:

* **Objetivo:** Expandir o modelo de simulação para abranger circuitos de distribuição que cubram a extensão residencial e comercial da **Asa Sul**, desde a ponta inicial (próximo às quadras iniciais/centro) até a ponta final (proximidades da quadra 716/Sudoeste/Aeroporto).
* **Hipótese de Pesquisa:** Espera-se que, ao aumentar significativamente o comprimento físico dos alimentadores e inserir a dinâmica de cargas residenciais e comerciais típicas do plano piloto, o sistema comece a apresentar curvas clássicas de queda de tensão gradual (perfil em rampa), permitindo um estudo mais profundo sobre regulação de tensão, perdas na linha e alocação de bancos de capacitores ou geração distribuída.

---

### 🛠️ Como Executar os Scripts Atuais

1. Certifique-se de ter o arquivo `.gdb` da BDGD no caminho especificado no arquivo de configuração.
2. Instale as dependências necessárias:
   ```bash
   pip install geopandas py-dss-interface pandas matplotlib contextily