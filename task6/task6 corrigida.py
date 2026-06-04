import geopandas as gpd
import py_dss_interface
import pandas as pd
import matplotlib.pyplot as plt
import os

# --- CONFIG ---
gdb_path = r"C:\Users\caike\PycharmProjects\bdgdbrasilia\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "ES01"

dss = py_dss_interface.DSS()
dss.text("Clear")

# --- FUNÇÕES ---
def bus(x):
    return (
        str(x)
        .strip()
        .upper()
        .replace("KV", "")
        .replace(" ", "")
    )

def clean_id(x):
    return (
        str(x)
        .strip()
        .replace(" ", "_")
        .replace(".", "")
        .replace("-", "")
    )

def limpar_numero(x):
    try:
        return float(str(x).lower().replace("kv", "").replace(",", ".").strip())
    except:
        return 0

# --- DADOS ---
ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
unsemt = gpd.read_file(gdb_path, layer="UNSEMT", where=f"CTMT = '{alim_id}'")
untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")

pac_ini = bus(ssdmt.iloc[0]['PAC_1'])

# --- CIRCUITO ---
dss.text(f"New Circuit.{alim_id} bus1={pac_ini} basekv=13.8 phases=3 pu=1.0")
dss.text("Set VoltageBases=[13.8, 0.38, 0.22]")
dss.text("Set controlmode=Static")

# --- LOADSHAPE ---
mult = ".3 .2 .2 .2 .3 .4 .4 .5 .6 .7 .8 .9 1 .9 .8 .7 .8 .9 1 1.2 1.1 .9 .7 .5"
dss.text(f"New Loadshape.dia_tipo npts=24 interval=1 mult=({mult})")

# --- LINHAS (com perdas maiores) ---
for _, row in ssdmt.iterrows():
    b1 = bus(row['PAC_1'])
    b2 = bus(row['PAC_2'])
    cod = clean_id(row['COD_ID'])

    if b1 == "" or b2 == "":
        continue

    length = max(float(row['Shape_Length']) / 1000, 0.001)

    if length < 0.1:
        r1, x1 = 0.7, 0.4
    elif length < 0.5:
        r1, x1 = 0.5, 0.35
    else:
        r1, x1 = 0.3, 0.3

    # 🔥 AUMENTO DE PERDAS
    r1 *= 1.5
    x1 *= 1.3

    dss.text(
        f"New Line.L_{cod} bus1={b1} bus2={b2} "
        f"phases=3 length={length} units=km r1={r1} x1={x1}"
    )

# --- CHAVES ---
for _, row in unsemt.iterrows():
    b1 = bus(row['PAC_1'])
    b2 = bus(row['PAC_2'])
    cod = clean_id(row['COD_ID'])

    if b1 == "" or b2 == "":
        continue

    dss.text(
        f"New Line.SW_{cod} bus1={b1} bus2={b2} "
        f"phases=3 length=0.001 r1=0.001 x1=0.001"
    )

# --- SOLVE PARCIAL ---
dss.text("CalcVoltageBases")
dss.text("Solve")

# --- TRANSFORMADORES + CARGAS ---
loads_criadas = 0

for _, row in untrmt.iterrows():
    bus_mt = bus(row['PAC_1'])
    cod = clean_id(row['COD_ID'])
    pot_kva = limpar_numero(row['POT_NOM'])

    if bus_mt == "" or pot_kva <= 0:
        continue

    bus_bt = f"{bus_mt}_BT"

    # 🔥 TRANSFORMADOR (AGORA EXISTE!)
    dss.text(
        f"New Transformer.T_{cod} phases=3 windings=2 "
        f"buses=[{bus_mt} {bus_bt}] "
        f"kvs=[13.8 0.38] "
        f"kvas=[{pot_kva} {pot_kva}] "
        f"%loadloss=2 %imag=1"
    )

    # 🔥 CARGA NA BAIXA TENSÃO
    # Aumentar até chegar na parte crítica
    kw = pot_kva * 1.2  # mais pesado

    dss.text(
        f"New Load.L_{cod} bus1={bus_bt}.1.2.3 "
        f"phases=3 kv=0.38 kw={kw} pf=0.92 daily=dia_tipo"
    )

    loads_criadas += 1

print("Loads criadas:", loads_criadas)

# --- CÁLCULO DE KVA CENÁRIO ---
kva_total_cenario = 0
for i in range(untrmt.shape[0]):
    pot_kva = limpar_numero(untrmt.iloc[i]['POT_NOM'])
    if pot_kva > 0:
        # Multiplicamos pelo fator 1.2 que você usou na criação das cargas
        kva_total_cenario += pot_kva * 1.2

# --- ENERGYMETERS (Comparações de Pontos) ---
# Ponto 1: Saída da Subestação (Já existe no seu código)
primeira_linha = f"Line.L_{clean_id(ssdmt.iloc[0]['COD_ID'])}"
dss.text(f"New Energymeter.m1 element={primeira_linha} terminal=1")

# Ponto 2: No último transformador que recebeu carga
# Isso garante que haverá fluxo passando pelo medidor
ultimo_cod_trafo = clean_id(untrmt.iloc[loads_criadas - 1]['COD_ID'])
dss.text(f"New Energymeter.m2 element=Transformer.T_{ultimo_cod_trafo} terminal=1")

# --- SOLUÇÃO FINAL ---
dss.text('Reset')
dss.text("Set mode=Daily stepsize=1h number=24")
dss.text("Solve")
dss.text("Sample")

# --- DEBUG ---
print("\nDEBUG:")
print("Barras:", dss.circuit.num_buses)
print("Elementos:", dss.circuit.num_ckt_elements)
print("Loads:", dss.loads.count)
print("Convergiu?", dss.solution.converged)
print("Potência total:", dss.circuit.total_power)

# --- RESULTADOS ---
print(f"\n{'=' * 50}\nRELATÓRIO CIENTÍFICO: {alim_id}\n{'=' * 50}")

if dss.solution.converged:
    # --- DADOS DO PONTO 1 (SUBESTAÇÃO) ---
    dss.meters.name = "m1"
    e_cons_m1 = dss.meters.register_values[0]
    e_loss_m1 = dss.meters.register_values[12]

    perc = (e_loss_m1 / e_cons_m1) * 100 if e_cons_m1 > 0 else 0

    # --- DADOS DO PONTO 2 (DISTANTE) ---
    dss.meters.name = "m2"
    e_cons_m2 = abs(dss.meters.register_values[0])

    # Exibição Comparativa
    print(f"1. ENERGIA NA SAÍDA DA SE (m1): {e_cons_m1:.2f} kWh")
    print(f"2. ENERGIA NO PONTO DISTANTE (m2): {e_cons_m2:.2f} kWh")
    print(f"3. ENERGIA CONSUMIDA/PERDIDA NO TRECHO: {e_cons_m1 - e_cons_m2:.2f} kWh")
    print(f"4. PERDAS TOTAIS DO SISTEMA: {e_loss_m1:.4f} kWh")

    # Cálculo de Tensão (Mantendo sua lógica anterior)
    v_base_ln = 13800 / (3 ** 0.5)
    dss.circuit.set_active_bus(pac_ini)
    tensao_bus = dss.bus.vmag_angle
    v_min_pu = tensao_bus[0] / v_base_ln if len(tensao_bus) > 0 else 0
    print(f"5. TENSÃO NA BARRA INICIAL: {v_min_pu:.4f} p.u.")
    print(f"6. CARREGAMENTO TOTAL DO CENÁRIO: {kva_total_cenario:.2f} kVA")

else:
    print("❌ Problema na solução.")

# --- DIRETÓRIO DOS CSVs ---
csv_folder = r"C:\Users\caike\PycharmProjects\bdgdbrasilia\task6"

# --- COMANDOS PARA GERAR OS CSVS (Faltava isso!) ---
# Define para onde o OpenDSS vai exportar os arquivos
dss.text(f"cd {csv_folder}")

dss.text("Export Voltages") # Vai gerar ES01_EXP_VOLTAGES.CSV
dss.text("Export Powers")   # Vai gerar ES01_EXP_POWERS.CSV
dss.text("Export Losses")   # Vai gerar ES01_EXP_LOSSES.CSV

# --- LER CSVs ---
df_v = pd.read_csv(os.path.join(csv_folder, f"{alim_id}_EXP_VOLTAGES.CSV"))
df_p = pd.read_csv(os.path.join(csv_folder, f"{alim_id}_EXP_POWERS.CSV"))
df_l = pd.read_csv(os.path.join(csv_folder, f"{alim_id}_EXP_LOSSES.CSV"))

# --- REMOVER ESPAÇOS DAS COLUNAS ---
df_v.columns = df_v.columns.str.strip()
df_p.columns = df_p.columns.str.strip()
df_l.columns = df_l.columns.str.strip()

# --- TENSÃO (média das fases, ignorando zeros) ---
tensao = df_v[['pu1','pu2','pu3']].replace(0, pd.NA).mean(axis=1)

# --- POTÊNCIA ---
# verifica se existe coluna 'kW', senão pega a segunda coluna
if 'kW' in df_p.columns:
    potencia = df_p['kW']
else:
    potencia = df_p.iloc[:, 1]

# --- PERDAS (W → kW) ---
if 'Losses' in df_l.columns:
    perdas = df_l['Losses'] / 1000
else:
    perdas = df_l.iloc[:, 1] / 1000

# --- GRÁFICO 1: TENSÃO COM LIMITES PRODIST ---
plt.figure(figsize=(10,6))
plt.plot(tensao, marker='o', color='black', label='Tensão Medida', linewidth=1, markersize=4)

# Adicionando faixas de qualidade (PRODIST)
plt.axhspan(0.93, 1.05, facecolor='green', alpha=0.2, label='Adequada')
plt.axhspan(0.90, 0.93, facecolor='yellow', alpha=0.3, label='Precaria')
plt.axhspan(0.00, 0.90, facecolor='red', alpha=0.2, label='Crítica')

# Linhas de referência
plt.axhline(y=0.93, color='orange', linestyle='--', linewidth=1)
plt.axhline(y=1.05, color='red', linestyle='--', linewidth=1)

plt.title(f"Perfil de Tensão - Alimentador {alim_id} (Conformidade PRODIST)")
plt.xlabel("Barras (Da Subestação até o Final)")
plt.ylabel("Tensão (p.u.)")

### ALTERAR AS VISUALIZAÇÕES ###
### VISUALIZAR CONFORMIDADE PRODIST ###
# plt.ylim(0.85, 1.1) # Ajuste para ver bem as faixas

### VISUALIZAR BEM A DIFERENÇA DOS PONTOS ###
plt.ylim(0.998, 1.0)

plt.legend(loc='lower left')
plt.grid(True, which='both', linestyle=':', alpha=0.5)

# --- GRÁFICO 2: POTÊNCIA ---
plt.figure(figsize=(10,5))
plt.plot(potencia, marker='o', color='tab:green')
plt.title("Fluxo de Potência por Elemento")
plt.xlabel("Elementos")
plt.ylabel("Potência (kW)")
plt.grid(True)

# --- GRÁFICO 3: PERDAS ---
plt.figure(figsize=(12,5))
plt.bar(df_l['Name'] if 'Name' in df_l.columns else range(len(perdas)), perdas, color='tab:red')
plt.title("Perdas por Elemento")
plt.xlabel("Elementos")
plt.ylabel("Perdas (kW)")
plt.xticks(rotation=90)
plt.grid(True, axis='y')

plt.tight_layout()
plt.show()

# --- GRÁFICO 4: MAPA DE TOPOLOGIA E PONTOS DE MEDIÇÃO ---
plt.figure(figsize=(10, 8))

# 1. Plotar todas as linhas do alimentador (fundo)
ssdmt.plot(ax=plt.gca(), color='lightgrey', linewidth=1, label='Rede MT (ES01)')

# 2. Destacar o PONTO 1 (Subestação / m1)
# Pegamos a geometria do primeiro trecho
ponto_se = ssdmt.iloc[0].geometry.centroid
plt.plot(ponto_se.x, ponto_se.y, 'ro', markersize=10, label='Ponto 1: Subestação (m1)')

# 3. Destacar o PONTO 2 (Transformador / m2)
# Buscamos o transformador que usamos para o m2
trafo_m2_geo = untrmt[untrmt['COD_ID'].str.contains(ultimo_cod_trafo, na=False)]
if not trafo_m2_geo.empty:
    ponto_m2 = trafo_m2_geo.iloc[0].geometry.centroid
    plt.plot(ponto_m2.x, ponto_m2.y, 'bs', markersize=8, label='Ponto 2: Entrega (m2)')

# 4. Plotar os outros transformadores (Cargas do Cenário)
untrmt.plot(ax=plt.gca(), color='green', markersize=20, alpha=0.5, label='Outras Cargas')

plt.title(f"Distribuição Espacial dos Pontos de Medição - {alim_id}")
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.legend()
plt.grid(True, linestyle='--', alpha=0.6)

plt.tight_layout()
plt.show()

# --- INSIGHTS AUTOMÁTICOS ---
# print("\n=== INSIGHTS ===")
# print("Tensão mínima:", round(tensao.min(), 4))
# print("Tensão máxima:", round(tensao.max(), 4))
# print("Maior perda:", round(perdas.max(), 4))
# print("Perda média:", round(perdas.mean(), 4))

# --- INSIGHTS TÉCNICOS E CIENTÍFICOS ---
print("\n" + "="*50)
print("             ANÁLISE DE IMPACTO E RESILIÊNCIA")
print("="*50)

# 1. Análise de Qualidade (PRODIST)
v_min = tensao.min()
status_prodist = "ADEQUADA" if v_min >= 0.93 else ("PRECARIA" if v_min >= 0.90 else "CRÍTICA")

print(f"I.   QUALIDADE DE ENERGIA (PRODIST):")
print(f"     - Status da Tensão: {status_prodist}")
print(f"     - Tensão Mínima Registrada: {v_min:.4f} p.u.")
print(f"     - Tensão Máxima Registrada: {tensao.max():.4f} p.u.")

# 2. Análise de Fluxo e Distância
queda_trecho = e_cons_m1 - e_cons_m2
print(f"\nII.  FLUXO DE POTÊNCIA E DISTÂNCIA:")
print(f"     - Energia Injetada (Subestação): {e_cons_m1:.2f} kWh")
print(f"     - Energia no Ponto de Entrega (m2): {e_cons_m2:.2f} kWh")
print(f"     - Queda de Energia no Trecho Analisado: {queda_trecho:.2f} kWh")

# 3. Análise de Eficiência e Cenário
print(f"\nIII. CENÁRIO E EFICIÊNCIA:")
print(f"     - Capacidade Instalada no Cenário: {kva_total_cenario:.2f} kVA")
print(f"     - Perdas Totais do Sistema: {e_loss_m1:.2f} kWh")
print(f"     - Eficiência Energética Global: {100 - perc:.2f}%")

# 4. Conclusão Acadêmica
print("\n" + "-"*50)
print("CONCLUSÃO:")
if v_min >= 0.93 and perc < 5:
    print("O alimentador apresenta alta resiliência para o cenário proposto,")
    print("operando com níveis de tensão estáveis e perdas dentro do esperado.")
else:
    print("Alerta: O sistema apresenta pontos de atenção em perdas ou tensão.")
print("-"*50)