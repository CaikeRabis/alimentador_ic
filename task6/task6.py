import geopandas as gpd
import py_dss_interface

# --- 1. CONFIGURAÇÕES ---
gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "ES01"

dss = py_dss_interface.DSS()
dss.text("Clear")

# --- 2. CARREGAMENTO ---
ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
unsemt = gpd.read_file(gdb_path, layer="UNSEMT", where=f"CTMT = '{alim_id}'")
untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")

pac_ini = str(ssdmt.iloc[0]['PAC_1']).strip().upper()

# --- 3. CIRCUITO E BASES (SINTAXE LIMPA) ---
dss.text(f"New Circuit.{alim_id}")
dss.text(f"~ basekv=13.8 bus1={pac_ini} phases=3 units=km")
dss.text("Set VoltageBases=[13.8, 0.38, 0.22]")
dss.text("Set controlmode=Static")  # [cite: 16]

# --- 4. CURVA DE CARGA (DAILY) ---
# Seguindo seu estudo anterior: pico às 20h [cite: 74, 79]
mult = ".3 .2 .2 .2 .3 .4 .4 .5 .6 .7 .8 .9 1 .9 .8 .7 .8 .9 1 1.2 1.1 .9 .7 .5"
dss.text(f"New Loadshape.dia_tipo npts=24 interval=1 mult=({mult})")

# --- 5. MODELAGEM COM IMPEDÂNCIAS TÉCNICAS ---
# No Plano Piloto (Asa Sul), usa-se muito o cabo 1/0 AWG ou 4/0 AWG.
# R1 aproximado: 0.54 Ohm/km | X1 aproximado: 0.38 Ohm/km
for _, row in ssdmt.iterrows():
    length = max(float(row['Shape_Length']) / 1000, 0.0001)
    # Aplicando valores mais realistas para o Plano Piloto
    dss.text(f"New Line.L_{row['COD_ID']} bus1={row['PAC_1'].upper()} bus2={row['PAC_2'].upper()} "
             f"length={length} units=km r1=0.543 x1=0.382")

for _, row in unsemt.iterrows():
    dss.text(f"New Line.SW_{row['COD_ID']} bus1={row['PAC_1'].upper()} bus2={row['PAC_2'].upper()} "
             f"length=0.001 r1=0.001 x1=0.001")

for _, row in untrmt.iterrows():
    bus_mt = str(row['PAC_1']).strip().upper()
    pot_kva = float(row['POT_NOM'])
    dss.text(
        f"New Load.L_{row['COD_ID']} bus1={bus_mt}.1.2.3 phases=3 kv=13.8 kw={pot_kva * 0.5} pf=0.92 daily=dia_tipo")

# --- 6. INSTRUMENTAÇÃO ---
primeira_linha = f"Line.L_{ssdmt.iloc[0]['COD_ID']}"
dss.text(f"New Energymeter.m1 element={primeira_linha} terminal=1")  # [cite: 12, 56]

# --- 7. SOLUÇÃO ---
dss.text("Set mode=Daily stepsize=1h number=24")  # [cite: 61, 63]
dss.text("CalcVoltageBases")
dss.text("Solve")  # [cite: 17, 64]
dss.text("Sample")  # Vital para o EnergyMeter consolidar dados

# --- 8. TERMINAL ---
print(f"\n{'=' * 50}\nRELATÓRIO CIENTÍFICO: {alim_id}\n{'=' * 50}")

if dss.solution.converged:
    # Tensão em p.u.
    v_base_ln = 13800 / (3 ** 0.5)
    dss.circuit.set_active_bus(str(untrmt.iloc[-1]['PAC_1']).upper())  # Pega uma barra de carga
    v_min_pu = dss.bus.vmag_angle[0] / v_base_ln

    # Balanço Energético [cite: 81, 82]

    e_cons = dss.meters.register_values[0]
    e_loss = dss.meters.register_values[12]
    perc = (e_loss / e_cons) * 100 if e_cons > 0 else 0

    print(f"1. TENSÃO MÍNIMA: {v_min_pu:.4f} p.u.")
    print(f"2. ENERGIA CONSUMIDA: {e_cons:.2f} kWh")
    print(f"3. PERDAS TOTAIS: {e_loss:.4f} kWh")
    print(f"4. EFICIÊNCIA (PERDAS %): {perc:.4f}%")
else:
    print("Erro na convergência.")