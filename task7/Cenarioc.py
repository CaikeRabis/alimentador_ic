import geopandas as gpd
import py_dss_interface
import pandas as pd
import matplotlib.pyplot as plt
import os
import contextily as ctx  # Certifique-se de ter instalado: pip install contextily

# --- CONFIGURAÇÃO GLOBAL ---
gdb_path = r"C:\Users\caike\PycharmProjects\bdgdbrasilia\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
csv_folder = r"C:\Users\caike\PycharmProjects\bdgdbrasilia\task6"
horario_pico = 19  # Horário de maior estresse (conforme mult do loadshape)

# 🚀 LISTA DE ALIMENTADORES: Você pode adicionar outros códigos aqui para rodar em sequência
alimentadores_para_analisar = ["ES01"]


# --- FUNÇÕES AUXILIARES ---
def bus(x): return str(x).strip().upper().replace("KV", "").replace(" ", "")


def clean_id(x): return str(x).strip().replace(" ", "_").replace(".", "").replace("-", "")


def limpar_numero(x):
    try:
        return float(str(x).lower().replace("kv", "").replace(",", ".").strip())
    except:
        return 0


# --- LOOP PRINCIPAL DE ALIMENTADORES ---
for alim_id in alimentadores_para_analisar:
    print(f"\n\n{'#' * 60}\nINICIANDO SIMULAÇÃO DA TASK 7 PARA O ALIMENTADOR: {alim_id}\n{'#' * 60}")

    # --- CARREGAMENTO DE DADOS GEOGRÁFICOS ---
    try:
        ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
        untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")
        unsemt = gpd.read_file(gdb_path, layer="UNSEMT", where=f"CTMT = '{alim_id}'")
    except Exception as e:
        print(f"❌ Erro ao ler camadas para o alimentador {alim_id}: {e}")
        continue

    if ssdmt.empty:
        print(f"⚠️ Alimentador {alim_id} não encontrado na base de dados. Pulando...")
        continue

    pac_ini = bus(ssdmt.iloc[0]['PAC_1'])

    # Dicionário específico para armazenar resultados de tensão deste alimentador
    resultados_v = {}

    # --- LISTA DE CENÁRIOS PARA SIMULAR (AGORA COM 4 CENÁRIOS) ---
    # Estrutura: (Nome, Fator de Estresse Geral, Carga Crítica no Fim, Carga Crítica no Meio)
    cenarios = [
        ("Base (Task 6)", 1.2, False, False),
        ("Estresse Geral (20x)", 20.0, False, False),
        ("Carga Crítica no Fim (Ponta)", 1.2, True, False),
        ("Carga Crítica no Meio (Nó Intermediário)", 1.2, False, True)
    ]

    # Loop de Cenários de Estresse
    for nome_cenario, faktor_mult, add_carga_fim, add_carga_meio in cenarios:
        # Inicializa e limpa o OpenDSS completamente para cada cenário
        dss = py_dss_interface.DSS()
        dss.text("Clear")

        # Criar Circuito e Loadshape
        dss.text(f"New Circuit.{alim_id} bus1={pac_ini} basekv=13.8 phases=3 pu=1.0")
        mult = ".3 .2 .2 .2 .3 .4 .4 .5 .6 .7 .8 .9 1 .9 .8 .7 .8 .9 1 1.2 1.1 .9 .7 .5"
        dss.text(f"New Loadshape.dia_tipo npts=24 interval=1 mult=({mult})")

        # Criar Linhas
        for _, row in ssdmt.iterrows():
            b1, b2, cod = bus(row['PAC_1']), bus(row['PAC_2']), clean_id(row['COD_ID'])
            if b1 == "" or b2 == "": continue
            length = max(float(row['Shape_Length']) / 1000, 0.001)
            r1, x1 = (0.7, 0.4) if length < 0.1 else (0.5, 0.35) if length < 0.5 else (0.3, 0.3)
            dss.text(
                f"New Line.L_{cod} bus1={b1} bus2={b2} phases=3 length={length} units=km r1={r1 * 1.5} x1={x1 * 1.3}")

        # Criar Chaves
        for _, row in unsemt.iterrows():
            b1, b2, cod = bus(row['PAC_1']), bus(row['PAC_2']), clean_id(row['COD_ID'])
            if b1 == "" or b2 == "": continue
            dss.text(f"New Line.SW_{cod} bus1={b1} bus2={b2} phases=3 length=0.001 r1=0.001 x1=0.001")

        # Criar Transformadores e Cargas
        loads_criadas = 0
        for _, row in untrmt.iterrows():
            bus_mt, cod, pot_kva = bus(row['PAC_1']), clean_id(row['COD_ID']), limpar_numero(row['POT_NOM'])
            if bus_mt == "" or pot_kva <= 0: continue
            bus_bt = f"{bus_mt}_BT"
            dss.text(
                f"New Transformer.T_{cod} phases=3 windings=2 buses=[{bus_mt} {bus_bt}] kvs=[13.8 0.38] kvas=[{pot_kva} {pot_kva}]")
            dss.text(
                f"New Load.L_{cod} bus1={bus_bt}.1.2.3 phases=3 kv=0.38 kw={pot_kva * faktor_mult} pf=0.92 daily=dia_tipo")
            loads_criadas += 1

        # --- ADICIONAR CARGA CRÍTICA NA PONTA ---
        if add_carga_fim:
            ponta_alimentador = bus(ssdmt.iloc[-1]['PAC_2'])
            dss.text(f"New Load.GRANDE_CARGA_FIM bus1={ponta_alimentador} phases=3 kv=13.8 kw=5000 pf=0.95")

        # --- ADICIONAR CARGA CRÍTICA NO MEIO (NOVO NÓ) ---
        if add_carga_meio:
            meio_index = len(ssdmt) // 2
            meio_alimentador = bus(ssdmt.iloc[meio_index]['PAC_2'])
            dss.text(f"New Load.GRANDE_CARGA_MEIO bus1={meio_alimentador} phases=3 kv=13.8 kw=5000 pf=0.95")

        # --- SOLUÇÃO NO HORÁRIO DE PICO ---
        dss.text("CalcVoltageBases")
        dss.text("Reset")
        dss.text("Set mode=daily stepsize=1h number=1")
        for h in range(1, horario_pico + 1):
            dss.text("Solve")

        # Exportar e ler tensões para este cenário específico
        dss.text(f"cd {csv_folder}")
        dss.text("Export Voltages")
        df_v = pd.read_csv(os.path.join(csv_folder, f"{alim_id}_EXP_VOLTAGES.CSV"))
        df_v.columns = df_v.columns.str.strip()
        resultados_v[nome_cenario] = df_v[['pu1', 'pu2', 'pu3']].replace(0, pd.NA).mean(axis=1)

    # --- GRÁFICO COMPARATIVO DE CENÁRIOS POR ALIMENTADOR ---
    plt.figure(figsize=(12, 7))
    cores = ['green', 'orange', 'red', 'purple']  # Roxo adicionado para o cenário do meio
    for (nome, serie), cor in zip(resultados_v.items(), cores):
        plt.plot(serie, label=nome, color=cor, linewidth=2)

    # Faixas e Limites PRODIST
    plt.axhspan(0.93, 1.05, facecolor='green', alpha=0.1)
    plt.axhspan(0.90, 0.93, facecolor='yellow', alpha=0.2)
    plt.axhspan(0.00, 0.90, facecolor='red', alpha=0.1)
    plt.axhline(y=0.93, color='orange', linestyle='--', alpha=0.5)
    plt.axhline(y=0.90, color='red', linestyle='--', alpha=0.5)

    plt.title(f"Comparativo de Cenários de Estresse - Alimentador {alim_id} às {horario_pico}:00h")
    plt.ylabel("Tensão (p.u.)")
    plt.xlabel("Barras da Rede")
    plt.ylim(0.80, 1.05)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

    # --- GRÁFICO: MAPA REAL COM CONTEXTILY POR ALIMENTADOR ---
    print(f"[{alim_id}] Gerando mapa georreferenciado...")
    plt.figure(figsize=(12, 10))

    # Converter para formato de mapa web (Mercator)
    ssdmt_web = ssdmt.to_crs(epsg=3857)
    ax = ssdmt_web.plot(ax=plt.gca(), color='blue', linewidth=2, alpha=0.7, label=f'Alimentador {alim_id}')
    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik)

    # 1. Destacar a ponta crítica (Carga Final)
    ponta_geo = ssdmt.iloc[[-1]].to_crs(epsg=3857)
    ponta_geo.centroid.plot(ax=ax, color='red', markersize=150, marker='X', label='Ponto Crítico: Ponta (5MW)')

    # 2. Destacar o nó intermediário (Carga no Meio)
    meio_geo = ssdmt.iloc[[len(ssdmt) // 2]].to_crs(epsg=3857)
    meio_geo.centroid.plot(ax=ax, color='purple', markersize=150, marker='o', label='Ponto Crítico: Meio (5MW)')

    plt.title(f"Mapa Real do Sistema de Distribuição - Neoenergia Brasília ({alim_id})")
    plt.legend()
    plt.tight_layout()
    plt.show()

print("\n🚀 Simulação da Task 7 com múltiplos nós críticos concluída!")