import geopandas as gpd
import py_dss_interface
import pandas as pd
import matplotlib.pyplot as plt
import os
import contextily as ctx

# --- CONFIG ---
gdb_path = r"C:\Users\caike\PycharmProjects\bdgdbrasilia\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "ES01"
csv_folder = r"C:\Users\caike\PycharmProjects\bdgdbrasilia\task6"
horario_pico = 19


# --- FUNÇÕES AUXILIARES ---
def bus(x): return str(x).strip().upper().replace("KV", "").replace(" ", "")


def clean_id(x): return str(x).strip().replace(" ", "_").replace(".", "").replace("-", "")


def limpar_numero(x):
    try:
        return float(str(x).lower().replace("kv", "").replace(",", ".").strip())
    except:
        return 0


# --- CARREGAMENTO DE DADOS GEOGRÁFICOS ---
ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")
unsemt = gpd.read_file(gdb_path, layer="UNSEMT", where=f"CTMT = '{alim_id}'")
pac_ini = bus(ssdmt.iloc[0]['PAC_1'])

# Dicionários para armazenar os resultados de cada cenário
resultados_v = {}
resultados_i = {}

# --- LISTA DE CENÁRIOS PARA SIMULAR ---
cenarios = [
    ("Base (Task 6)", 1.2, False),
    ("Estresse Geral (20x)", 20.0, True),
    ("Carga Crítica no Fim", 1.2, False)
]

for nome_cenario, fator_mult, add_carga_fim in cenarios:
    dss = py_dss_interface.DSS()
    dss.text("Clear")

    # Criar Circuito e Loadshape
    dss.text(f"New Circuit.{alim_id} bus1={pac_ini} basekv=13.8 phases=3 pu=1.0")
    mult = ".3 .2 .2 .2 .3 .4 .4 .5 .6 .7 .8 .9 1 .9 .8 .7 .8 .9 1 1.2 1.1 .9 .7 .5"
    dss.text(f"New Loadshape.dia_tipo npts=24 interval=1 mult=({mult})")

    # Criar Linhas e Chaves
    for _, row in ssdmt.iterrows():
        b1, b2, cod = bus(row['PAC_1']), bus(row['PAC_2']), clean_id(row['COD_ID'])
        length = max(float(row['Shape_Length']) / 1000, 0.001)
        r1, x1 = (0.7, 0.4) if length < 0.1 else (0.5, 0.35) if length < 0.5 else (0.3, 0.3)
        dss.text(f"New Line.L_{cod} bus1={b1} bus2={b2} phases=3 length={length} units=km r1={r1 * 1.5} x1={x1 * 1.3}")

    for _, row in unsemt.iterrows():
        b1, b2, cod = bus(row['PAC_1']), bus(row['PAC_2']), clean_id(row['COD_ID'])
        dss.text(f"New Line.SW_{cod} bus1={b1} bus2={b2} phases=3 length=0.001 r1=0.001 x1=0.001")

    # Criar Transformadores e Cargas
    for _, row in untrmt.iterrows():
        bus_mt, cod, pot_kva = bus(row['PAC_1']), clean_id(row['COD_ID']), limpar_numero(row['POT_NOM'])
        if bus_mt == "" or pot_kva <= 0: continue
        bus_bt = f"{bus_mt}_BT"
        dss.text(
            f"New Transformer.T_{cod} phases=3 windings=2 buses=[{bus_mt} {bus_bt}] kvs=[13.8 0.38] kvas=[{pot_kva} {pot_kva}]")
        dss.text(
            f"New Load.L_{cod} bus1={bus_bt}.1.2.3 phases=3 kv=0.38 kw={pot_kva * fator_mult} pf=0.92 daily=dia_tipo")

    # Adicionar Carga Crítica
    if add_carga_fim:
        ponta_alimentador = bus(ssdmt.iloc[-1]['PAC_2'])
        dss.text(f"New Load.GRANDE_CARGA bus1={ponta_alimentador} phases=3 kv=13.8 kw=5000 pf=0.95")

    # Solução no Horário de Pico
    dss.text("Set VoltageBases=[13.8, 0.38]")
    dss.text("CalcVoltageBases")
    dss.text("Reset")
    dss.text("Set mode=daily stepsize=1h number=1")
    for h in range(1, horario_pico + 1):
        dss.text("Solve")

    # Direcionar pasta para exportação
    dss.text(f"cd {csv_folder}")

    # --- 1. PROCESSAR TENSÕES ---
    # --- 1. PROCESSAR TENSÕES (Filtrando apenas Média Tensão: 13.8 kV) ---
    dss.text("Export Voltages")
    df_v = pd.read_csv(os.path.join(csv_folder, f"{alim_id}_EXP_VOLTAGES.CSV"))
    df_v.columns = df_v.columns.str.strip()

    # Identifica dinamicamente a coluna de Tensão Base nominal (pode ser 'Base kV', 'BasekV' ou 'kVBase')
    col_base_kv = [col for col in df_v.columns if 'base' in col.lower() and 'kv' in col.lower()]

    if col_base_kv:
        nome_col_kv = col_base_kv[0]
        # Filtra as barras com base entre 7.0 kV e 14.0 kV (Média Tensão)
        df_v_mt = df_v[df_v[nome_col_kv].between(7.0, 14.0)].copy()
    else:
        # Se não achar a coluna por algum motivo, não trava: usa o DataFrame completo
        df_v_mt = df_v.copy()

    # Identifica dinamicamente a coluna de distância para ordenar do início ao fim do alimentador
    col_distancia = [col for col in df_v.columns if 'dist' in col.lower()]
    if col_distancia and not df_v_mt.empty:
        df_v_mt = df_v_mt.sort_values(by=col_distancia[0])

    # Calcula a média das fases para as barras de Média Tensão
    resultados_v[nome_cenario] = df_v_mt[['pu1', 'pu2', 'pu3']].replace(0, pd.NA).mean(axis=1).reset_index(drop=True)

    # --- PRINT PARA O ORIENTADOR (Cenário Base) ---
    if nome_cenario == "Base (Task 6)" and not df_v_mt.empty:
        v_subestacao = df_v_mt[['pu1', 'pu2', 'pu3']].iloc[0].mean()
        v_ponta = df_v_mt[['pu1', 'pu2', 'pu3']].iloc[-1].mean()
        print("\n=== VALORES DE TENSÃO PARA O ORIENTADOR (Cenário Base) ===")
        print(f"Tensão na Subestação (Início): {v_subestacao:.4f} p.u. (~ {v_subestacao * 13.8:.2f} kV)")
        print(f"Tensão na Ponta do Alimentador: {v_ponta:.4f} p.u. (~ {v_ponta * 13.8:.2f} kV)")
        print("===========================================================\n")

    # --- 2. PROCESSAR CORRENTES ---
    dss.text("Export Currents")
    df_i = pd.read_csv(os.path.join(csv_folder, f"{alim_id}_EXP_CURRENTS.CSV"))
    df_i.columns = df_i.columns.str.strip()

    # Filtrando apenas as linhas (Lines) para o gráfico
    df_i_linhas = df_i[df_i['Element'].str.startswith('Line.', na=False)].copy()

    # PROCURA DINÂMICA: Descobre quais colunas representam as correntes das fases
    # Geralmente começam com 'I' maiúsculo seguido de números (ex: I1, I2, I3 ou I1_1, I2_1...)
    colunas_corrente = [col for col in df_i_linhas.columns if col.startswith('I') and col[1:2].isdigit()]

    # Caso o OpenDSS tenha exportado com outro padrão, pegamos as 3 primeiras colunas numéricas após 'Element'
    if not colunas_corrente:
        colunas_corrente = [col for col in df_i_linhas.columns if df_i_linhas[col].dtype in ['float64', 'int64']][:3]

    # Extrai o valor máximo entre as fases identificadas
    resultados_i[nome_cenario] = df_i_linhas[colunas_corrente].max(axis=1).reset_index(drop=True)

# --- PLOTAGEM DOS GRÁFICOS (LADO A LADO) ---
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 7))
cores = ['green', 'orange', 'red']

# Gráfico 1: Tensões (O que você já tinha)
for (nome, serie), cor in zip(resultados_v.items(), cores):
    ax1.plot(serie, label=nome, color=cor, linewidth=2)
ax1.axhspan(0.93, 1.05, facecolor='green', alpha=0.1)
ax1.axhspan(0.90, 0.93, facecolor='yellow', alpha=0.2)
ax1.axhspan(0.00, 0.90, facecolor='red', alpha=0.1)
ax1.axhline(y=0.93, color='orange', linestyle='--', alpha=0.5)
ax1.axhline(y=0.90, color='red', linestyle='--', alpha=0.5)
ax1.set_title(f"Perfil de Tensão - {alim_id} às {horario_pico}:00h")
ax1.set_ylabel("Tensão (p.u.)")
ax1.set_xlabel("Barras da Rede")
ax1.set_ylim(0.80, 1.12)
ax1.legend()
ax1.grid(True, alpha=0.3)

# Gráfico 2: Correntes Elétricas (O Novo!)
for (nome, serie), cor in zip(resultados_i.items(), cores):
    ax2.plot(serie, label=nome, color=cor, linewidth=2)
ax2.set_title(f"Fluxo de Corrente nas Linhas - {alim_id} às {horario_pico}:00h")
ax2.set_ylabel("Corrente Máxima por Fase (A)")
ax2.set_xlabel("Trechos de Linhas (Do início ao fim)")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.show()

# --- GRÁFICO: MAPA REAL (Inalterado) ---
print("\nGerando mapa georreferenciado...")
plt.figure(figsize=(12, 10))
ssdmt_web = ssdmt.to_crs(epsg=3857)
ax = ssdmt_web.plot(ax=plt.gca(), color='blue', linewidth=2, alpha=0.7, label='Alimentador ES01')
ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik)
ponta_geo = ssdmt.iloc[[-1]].to_crs(epsg=3857)
ponta_geo.centroid.plot(ax=ax, color='red', markersize=150, marker='X', label='Ponto de Carga Crítica')
plt.title("Mapa Real do Sistema de Distribuição - Neoenergia Brasília")
plt.legend()
plt.show()

print("\nTask 7 ampliada com sucesso!")