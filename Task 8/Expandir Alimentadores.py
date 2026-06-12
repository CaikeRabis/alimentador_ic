import geopandas as gpd
import py_dss_interface
import pandas as pd
import matplotlib.pyplot as plt
import os
import contextily as ctx

# --- CONFIG ---
gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"

alimentadores = [
    "02_BGC1", "02_BGC2", "02_BGC3",
    "0607", "0613", "0614", "0615",
    "BC39", "BC_06C2",
    "BG_01C1", "BG_01C2", "BG_01C3",
    "EN09", "EN10", "EN11", "EN13",
    "ES07", "ES08", "ES09",
    "ES13", "ES14", "ES15", "ES16", "ES17", "ES18",
    "ES21", "ES22", "ES23", "ES24",
    "HP02", "HP03"
]

csv_folder = r"C:\Users\usuario\PycharmProjects\bdgdbrasilia"
horario_pico = 19

cenarios = [
    ("Base (Task 6)", 1.2, False),
    ("Estresse Geral (20x)", 20.0, True),
    ("Carga Crítica no Fim", 1.2, False)
]


def bus(x):
    return str(x).strip().upper().replace("KV", "").replace(" ", "")


def clean_id(x):
    return str(x).strip().replace(" ", "_").replace(".", "").replace("-", "")


def limpar_numero(x):
    try:
        return float(str(x).lower().replace("kv", "").replace(",", ".").strip())
    except:
        return 0


# --- CARREGAMENTO DOS DADOS ---
filtro = " OR ".join([f"CTMT = '{a}'" for a in alimentadores])

ssdmt_total = gpd.read_file(gdb_path, layer="SSDMT", where=filtro)
untrmt_total = gpd.read_file(gdb_path, layer="UNTRMT", where=filtro)
unsemt_total = gpd.read_file(gdb_path, layer="UNSEMT", where=filtro)

print("\n=== DADOS CARREGADOS ===")
print("Trechos MT:", len(ssdmt_total))
print("Transformadores:", len(untrmt_total))
print("Chaves:", len(unsemt_total))
print(ssdmt_total["CTMT"].value_counts())
print("========================\n")

resultados_por_alimentador = {}

# --- SIMULAÇÃO POR ALIMENTADOR ---
for alim_id in alimentadores:

    print(f"\nSimulando {alim_id}...")

    ssdmt = ssdmt_total[ssdmt_total["CTMT"] == alim_id].copy()
    untrmt = untrmt_total[untrmt_total["CTMT"] == alim_id].copy()
    unsemt = unsemt_total[unsemt_total["CTMT"] == alim_id].copy()

    print(f"{alim_id}: {len(ssdmt)} trechos, {len(untrmt)} trafos, {len(unsemt)} chaves")

    if len(ssdmt) == 0:
        print(f"{alim_id} ignorado: sem trechos.")
        continue

    pac_ini = bus(ssdmt.iloc[0]["PAC_1"])
    print(f"{alim_id} - PAC inicial usado: {pac_ini}")

    resultados_v = {}
    resultados_i = {}

    for nome_cenario, fator_mult, add_carga_fim in cenarios:

        dss = py_dss_interface.DSS()
        dss.text("Clear")

        dss.text(f"New Circuit.{alim_id} bus1={pac_ini} basekv=13.8 phases=3 pu=1.0")

        mult = ".3 .2 .2 .2 .3 .4 .4 .5 .6 .7 .8 .9 1 .9 .8 .7 .8 .9 1 1.2 1.1 .9 .7 .5"
        dss.text(f"New Loadshape.dia_tipo npts=24 interval=1 mult=({mult})")

        for _, row in ssdmt.iterrows():
            b1 = bus(row["PAC_1"])
            b2 = bus(row["PAC_2"])
            cod = clean_id(row["COD_ID"])
            length = max(float(row["Shape_Length"]) / 1000, 0.001)

            if length < 0.1:
                r1, x1 = 0.7, 0.4
            elif length < 0.5:
                r1, x1 = 0.5, 0.35
            else:
                r1, x1 = 0.3, 0.3

            dss.text(
                f"New Line.L_{cod} "
                f"bus1={b1} bus2={b2} phases=3 "
                f"length={length} units=km "
                f"r1={r1 * 1.5} x1={x1 * 1.3}"
            )

        for _, row in unsemt.iterrows():
            b1 = bus(row["PAC_1"])
            b2 = bus(row["PAC_2"])
            cod = clean_id(row["COD_ID"])

            dss.text(
                f"New Line.SW_{cod} "
                f"bus1={b1} bus2={b2} phases=3 "
                f"length=0.001 r1=0.001 x1=0.001"
            )

        for _, row in untrmt.iterrows():
            bus_mt = bus(row["PAC_1"])
            cod = clean_id(row["COD_ID"])
            pot_kva = limpar_numero(row["POT_NOM"])

            if bus_mt == "" or pot_kva <= 0:
                continue

            bus_bt = f"{bus_mt}_BT"

            dss.text(
                f"New Transformer.T_{cod} "
                f"phases=3 windings=2 "
                f"buses=[{bus_mt} {bus_bt}] "
                f"kvs=[13.8 0.38] "
                f"kvas=[{pot_kva} {pot_kva}]"
            )

            dss.text(
                f"New Load.L_{cod} "
                f"bus1={bus_bt}.1.2.3 "
                f"phases=3 kv=0.38 "
                f"kw={pot_kva * fator_mult} "
                f"pf=0.92 daily=dia_tipo"
            )

        if add_carga_fim:
            ponta_alimentador = bus(ssdmt.iloc[-1]["PAC_2"])
            dss.text(
                f"New Load.GRANDE_CARGA "
                f"bus1={ponta_alimentador} "
                f"phases=3 kv=13.8 kw=5000 pf=0.95"
            )

        dss.text("Set VoltageBases=[13.8, 0.38]")
        dss.text("CalcVoltageBases")
        dss.text("Reset")
        dss.text("Set mode=daily stepsize=1h number=1")

        for h in range(1, horario_pico + 1):
            dss.text("Solve")

        dss.text(f"cd {csv_folder}")

        dss.text("Export Voltages")
        arquivo_v = os.path.join(csv_folder, f"{alim_id}_EXP_VOLTAGES.CSV")

        if not os.path.exists(arquivo_v):
            print(f"Aviso: arquivo de tensão não encontrado para {alim_id}: {arquivo_v}")
            continue

        df_v = pd.read_csv(arquivo_v)
        df_v.columns = df_v.columns.str.strip()

        col_base_kv = [
            col for col in df_v.columns
            if "base" in col.lower() and "kv" in col.lower()
        ]

        if col_base_kv:
            nome_col_kv = col_base_kv[0]
            df_v_mt = df_v[df_v[nome_col_kv].between(7.0, 14.0)].copy()
        else:
            df_v_mt = df_v.copy()

        col_distancia = [col for col in df_v.columns if "dist" in col.lower()]

        if col_distancia and not df_v_mt.empty:
            df_v_mt = df_v_mt.sort_values(by=col_distancia[0])

        if all(col in df_v_mt.columns for col in ["pu1", "pu2", "pu3"]):
            resultados_v[nome_cenario] = (
                df_v_mt[["pu1", "pu2", "pu3"]]
                .replace(0, pd.NA)
                .mean(axis=1)
                .reset_index(drop=True)
            )

        if nome_cenario == "Base (Task 6)" and not df_v_mt.empty:
            v_subestacao = df_v_mt[["pu1", "pu2", "pu3"]].iloc[0].mean()
            v_ponta = df_v_mt[["pu1", "pu2", "pu3"]].iloc[-1].mean()

            print(f"\n=== {alim_id} - VALORES DE TENSÃO BASE ===")
            print(f"Tensão na Subestação/Início: {v_subestacao:.4f} p.u. (~ {v_subestacao * 13.8:.2f} kV)")
            print(f"Tensão na Ponta: {v_ponta:.4f} p.u. (~ {v_ponta * 13.8:.2f} kV)")
            print("=========================================\n")

        dss.text("Export Currents")
        arquivo_i = os.path.join(csv_folder, f"{alim_id}_EXP_CURRENTS.CSV")

        if not os.path.exists(arquivo_i):
            print(f"Aviso: arquivo de corrente não encontrado para {alim_id}: {arquivo_i}")
            continue

        df_i = pd.read_csv(arquivo_i)
        df_i.columns = df_i.columns.str.strip()

        df_i_linhas = df_i[df_i["Element"].str.startswith("Line.", na=False)].copy()

        colunas_corrente = [
            col for col in df_i_linhas.columns
            if col.startswith("I") and col[1:2].isdigit()
        ]

        if not colunas_corrente:
            colunas_corrente = [
                col for col in df_i_linhas.columns
                if df_i_linhas[col].dtype in ["float64", "int64"]
            ][:3]

        if colunas_corrente:
            resultados_i[nome_cenario] = (
                df_i_linhas[colunas_corrente]
                .max(axis=1)
                .reset_index(drop=True)
            )

    resultados_por_alimentador[alim_id] = {
        "tensao": resultados_v,
        "corrente": resultados_i
    }


# --- PLOTAR GRÁFICOS DE CADA ALIMENTADOR ---
cores = ["green", "orange", "red"]

for alim_id, resultados in resultados_por_alimentador.items():

    resultados_v = resultados["tensao"]
    resultados_i = resultados["corrente"]

    if not resultados_v and not resultados_i:
        continue

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 7))

    for (nome, serie), cor in zip(resultados_v.items(), cores):
        ax1.plot(serie, label=nome, color=cor, linewidth=2)

    ax1.axhspan(0.93, 1.05, facecolor="green", alpha=0.1)
    ax1.axhspan(0.90, 0.93, facecolor="yellow", alpha=0.2)
    ax1.axhspan(0.00, 0.90, facecolor="red", alpha=0.1)
    ax1.axhline(y=0.93, color="orange", linestyle="--", alpha=0.5)
    ax1.axhline(y=0.90, color="red", linestyle="--", alpha=0.5)

    ax1.set_title(f"Perfil de Tensão - {alim_id} às {horario_pico}:00h")
    ax1.set_ylabel("Tensão (p.u.)")
    ax1.set_xlabel("Barras da Rede")
    ax1.set_ylim(0.80, 1.12)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    for (nome, serie), cor in zip(resultados_i.items(), cores):
        ax2.plot(serie, label=nome, color=cor, linewidth=2)

    ax2.set_title(f"Fluxo de Corrente nas Linhas - {alim_id} às {horario_pico}:00h")
    ax2.set_ylabel("Corrente Máxima por Fase (A)")
    ax2.set_xlabel("Trechos de Linhas")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


# --- MAPA COM TODOS OS ALIMENTADORES ---
print("\nGerando mapa georreferenciado com todos os alimentadores...")

plt.figure(figsize=(18, 14))
ax = plt.gca()

ssdmt_web = ssdmt_total.to_crs(epsg=3857)

cmap = plt.get_cmap("tab20", len(alimentadores))

cores_alimentadores = {
    alim: cmap(i)
    for i, alim in enumerate(alimentadores)
}

for alim in alimentadores:
    rede = ssdmt_web[ssdmt_web["CTMT"] == alim]

    if rede.empty:
        continue

    rede.plot(
        ax=ax,
        color=cores_alimentadores[alim],
        linewidth=3,
        alpha=0.95,
        label=alim
    )

ctx.add_basemap(
    ax,
    source=ctx.providers.CartoDB.Positron
)

plt.title("Mapa Real do Sistema de Distribuição - Alimentadores Selecionados")
plt.legend(
    title="Alimentadores",
    fontsize=7,
    ncol=3,
    loc="upper left"
)

plt.show()

print("\nTask 7 ampliada com sucesso!")