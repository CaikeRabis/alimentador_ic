import geopandas as gpd
import py_dss_interface
from shapely.ops import nearest_points

# 1. Configurações
gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "TN01"
pac_ini = "TN_ALTN01"

# 2. Carregar Dados
ctmt = gpd.read_file(gdb_path, layer="CTMT", where=f"COD_ID = '{alim_id}'")
ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")

dss = py_dss_interface.DSS()
dss.text("Clear")
dss.text(f"New Circuit.{alim_id} basekv=13.8 bus1={pac_ini} phases=3")

# 3. O PULO DO GATO: Conectar a Subestação à Rede
# Vamos achar o ponto da rede SSDMT mais próximo da coordenada da Subestação (CTMT)
ponto_sub = ctmt.iloc[0].geometry
# Criamos uma união de todas as linhas para achar o ponto mais próximo
uniao_rede = ssdmt.geometry.unary_union
ponto_proximo_rede = nearest_points(ponto_sub, uniao_rede)[1]

# Descobrir qual PAC da rede está nesse ponto próximo
# (Vamos usar o PAC_1 da primeira linha que encosta nesse ponto)
distancias = ssdmt.geometry.distance(ponto_proximo_rede)
linha_mae = ssdmt.iloc[distancias.idxmin()]
no_conexao = str(linha_mae['PAC_1']).upper().strip()

print(f"Conectando Subestação ({pac_ini}) ao nó da rede ({no_conexao})...")
dss.text(f"New Line.JUMPER_SUB bus1={pac_ini} bus2={no_conexao} length=0.001 units=km r1=0.01 x1=0.01")

# 4. Criar o restante da rede (SSDMT)
for _, row in ssdmt.iterrows():
    b1 = str(row['PAC_1']).upper().strip()
    b2 = str(row['PAC_2']).upper().strip()
    dss.text(f"New Line.{row['COD_ID']} bus1={b1} bus2={b2} length={row['Shape_Length']/1000} units=km r1=0.3 x1=0.35")

# 5. Criar Cargas (UNTRMT)
for _, row in untrmt.iterrows():
    bus_mt = str(row['PAC_1']).upper().strip()
    pot = float(row['POT_NOM'])
    dss.text(f"New Load.L_{row['COD_ID']} bus1={bus_mt}.1.2.3 phases=3 kv=13.8 kw={pot*0.5} pf=0.92")

# 6. Resolver e Validar
dss.text("Solve")
pot_total = dss.circuit.total_power[0] * -1
print(f"\n--- RESULTADO FINAL TN01 ---")
print(f"Potência Total: {pot_total:.2f} kW")

if pot_total > 10:
    print("SUCESSO! A rede está energizada.")
    dss.text("Plot Profile")
else:
    print("ERRO: A rede continua isolada. Verifique se o 'no_conexao' faz parte da maior ilha.")