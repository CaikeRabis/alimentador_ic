import geopandas as gpd
import py_dss_interface

gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "ES01"

dss = py_dss_interface.DSS()
dss.text("Clear")

# 1. Carregar dados
ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
unsemt = gpd.read_file(gdb_path, layer="UNSEMT", where=f"CTMT = '{alim_id}'")
untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")

pac_ini = str(ssdmt.iloc[0]['PAC_1']).strip().upper()

# 2. Criar o Circuito - REMOVIDO "units" para evitar erro 320
dss.text(f"New Circuit.{alim_id} basekv=13.8 bus1={pac_ini} phases=3")
# Definimos as unidades e curto-circuito em comandos separados para segurança
dss.text(f"~ MVAsc3=2000 MVAsc1=2100")

# 3. Criar Trechos de Linha (SSDMT) com trava de segurança para comprimento zero
for _, row in ssdmt.iterrows():
    b1 = str(row['PAC_1']).strip().upper()
    b2 = str(row['PAC_2']).strip().upper()
    nome = str(row['COD_ID']).strip()

    # Prevenção do erro de inversão de matriz: comprimento não pode ser zero
    length = max(float(row['Shape_Length']) / 1000, 0.0001)

    # Se r1 ou x1 forem 0, o OpenDSS trava na inversão. Usamos valores padrão robustos:
    dss.text(f"New Line.L_{nome} bus1={b1} bus2={b2} length={length:.6f} units=km r1=0.3 x1=0.35")

# 4. Criar Chaves (UNSEMT) - Usando valores levemente maiores que 0 para estabilidade
for _, row in unsemt.iterrows():
    b1 = str(row['PAC_1']).strip().upper()
    b2 = str(row['PAC_2']).strip().upper()
    nome = str(row['COD_ID']).strip()
    # Chaves não podem ter resistência ABSOLUTAMENTE zero em alguns motores
    dss.text(f"New Line.SW_{nome} bus1={b1} bus2={b2} length=0.001 units=km r1=0.001 x1=0.001")

# 5. Criar Cargas (UNTRMT)
for _, row in untrmt.iterrows():
    bus_mt = str(row['PAC_1']).strip().upper()
    trafo = str(row['COD_ID']).strip()
    pot_kva = float(row['POT_NOM'])
    dss.text(f"New Load.L_{trafo} bus1={bus_mt}.1.2.3 phases=3 kv=13.8 kw={pot_kva * 0.5:.2f} pf=0.92 model=1")

# 6. Solução com verificação de bases
dss.text("Set VoltageBases=[13.8]")
dss.text("CalcVoltageBases")
dss.text("Solve")


# 1. Exportar tensões para análise científica
dss.text("Export Voltages")
print(f"Arquivo de tensões gerado na pasta do projeto.")

# 2. Verificar Perdas Totais (Essencial para pesquisa de planejamento)
perdas_ativas = dss.circuit.losses[0] / 1000 # Convertendo para kW
print(f"Perdas Ativas Totais: {perdas_ativas:.2f} kW")

# --- ANÁLISE CIENTÍFICA REFINADA ---
# --- DIAGNÓSTICO CORRETO ---
print("\n--- Top 5 Barras com Menor Tensão (p.u.) ---")

tensões_reais_pu = []
all_bus_names = dss.circuit.buses_names

for nome_barra in all_bus_names:
    dss.circuit.set_active_bus(nome_barra)
    # pu_vmag_angle retorna [V1, Ang1, V2, Ang2, V3, Ang3] em p.u.
    v_pu_list = dss.bus.vmag_angle_pu

    if v_pu_list and len(v_pu_list) > 0:
        # Pegamos a média das fases presentes para simplificar a busca pela menor
        v_media = sum(v_pu_list[0::2]) / (len(v_pu_list) / 2)
        tensões_reais_pu.append((nome_barra, v_media))

# Ordenar
tensões_reais_pu.sort(key=lambda x: x[1])

for barra, v in tensões_reais_pu[:5]:
    # Agora o resultado DEVE ser algo como 0.9985 p.u.
    print(f"Barra: {barra.lower()} | Tensão: {v:.4f} p.u.")