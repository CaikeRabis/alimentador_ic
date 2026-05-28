import geopandas as gpd
import py_dss_interface

# --- 1. CONFIGURAÇÕES DE CAMINHO ---
gdb_path = r"/Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb/Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "ES01"

dss = py_dss_interface.DSS()
dss.text("Clear")  # [cite: 10]

# --- 2. CARREGAMENTO DE DADOS (BDGD) ---
ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
unsemt = gpd.read_file(gdb_path, layer="UNSEMT", where=f"CTMT = '{alim_id}'")
untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")

pac_ini = str(ssdmt.iloc[0]['PAC_1']).strip().upper()

# --- 3. CRIAÇÃO DO CIRCUITO (SINTAXE ANTI-ERRO) ---
dss.text(f"New Circuit.{alim_id}")
dss.text(f"~ basekv=13.8")
dss.text(f"~ bus1={pac_ini}")
dss.text(f"~ phases=3")
dss.text(f"~ units=km")
dss.text("Set controlmode=Static")  # [cite: 16]

# Definição de bases para normalização interna
dss.text("Set VoltageBases=[13.8, 0.38, 0.22]")

# --- 4. CURVA DE CARGA (DAILY) ---
# Baseado no perfil residencial do seu relatório de Palmas [cite: 78]
multiplicadores = ".3 .2 .2 .2 .3 .4 .4 .5 .6 .7 .8 .9 1 .9 .8 .7 .8 .9 1 1.2 1.1 .9 .7 .5"
dss.text(f"New Loadshape.dia_tipo npts=24 interval=1 mult=({multiplicadores})")

# --- 5. MODELAGEM DA REDE ---
for _, row in ssdmt.iterrows():
    length = max(float(row['Shape_Length']) / 1000, 0.0001)
    dss.text(
        f"New Line.L_{row['COD_ID']} bus1={row['PAC_1'].upper()} bus2={row['PAC_2'].upper()} length={length} units=km r1=0.3 x1=0.35")

for _, row in unsemt.iterrows():
    dss.text(
        f"New Line.SW_{row['COD_ID']} bus1={row['PAC_1'].upper()} bus2={row['PAC_2'].upper()} length=0.001 r1=0.001 x1=0.001")

for _, row in untrmt.iterrows():
    bus_mt = str(row['PAC_1']).strip().upper()
    pot_kva = float(row['POT_NOM'])
    # kV definido explicitamente para evitar erros de base de tensão
    dss.text(
        f"New Load.L_{row['COD_ID']} bus1={bus_mt}.1.2.3 phases=3 kv=13.8 kw={pot_kva * 0.5} pf=0.92 daily=dia_tipo")

# --- 6. INSTRUMENTAÇÃO ---
primeira_linha = f"Line.L_{ssdmt.iloc[0]['COD_ID']}"
dss.text(f"New Energymeter.medidor_geral element={primeira_linha} terminal=1")  # [cite: 12, 57]

# --- 7. SOLUÇÃO ---
dss.text("Set mode=Daily stepsize=1h number=24")  # [cite: 61, 63]
dss.text("CalcVoltageBases")
dss.text("Solve")  # [cite: 17, 64]
dss.text("Sample")  # Força o medidor a ler os dados finais

# --- 8. RELATÓRIO NO TERMINAL ---
print(f"\n{'=' * 50}")
print(f"RELATÓRIO TÉCNICO: ALIMENTADOR {alim_id}")
print(f"{'=' * 50}")

if dss.solution.converged:
    # A. Cálculo Manual de p.u. para garantir precisão científica
    all_bus_pu = []
    v_base_ln = 13800 / (3 ** 0.5)

    for nome_barra in dss.circuit.buses_names:
        dss.circuit.set_active_bus(nome_barra)
        v_volts = dss.bus.vmag_angle[0]
        v_pu_real = v_volts / v_base_ln
        all_bus_pu.append((nome_barra, v_pu_real))

    all_bus_pu.sort(key=lambda x: x[1])
    min_v_barra, min_v_val = all_bus_pu[0]

    print(f"1. QUALIDADE DA TENSÃO:")
    print(f"   - Tensão Mínima: {min_v_val:.4f} p.u. (Barra: {min_v_barra})")  #

    # B. Balanço Energético (24h)
    energia_total = dss.meters.register_values[0]  # [cite: 83]
    perdas_totais = dss.meters.register_values[12]  # [cite: 84]
    perc_perdas = (perdas_totais / energia_total) * 100 if energia_total > 0 else 0

    print(f"\n2. BALANÇO ENERGÉTICO (DIÁRIO):")
    print(f"   - Energia Consumida: {energia_total:.2f} kWh")
    print(f"   - Perdas Totais: {perdas_totais:.4f} kWh")
    print(f"   - Eficiência (Perdas %): {perc_perdas:.4f}%")

    # C. Demanda Instantânea Final
    p_atual = dss.circuit.total_power[0] * -1
    print(f"\n3. CARREGAMENTO:")
    print(f"   - Demanda Final: {p_atual:.2f} kW")  # [cite: 79]
else:
    print("ERRO: O sistema não convergiu.")

print(f"{'=' * 50}\n")