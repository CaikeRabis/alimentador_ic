import geopandas as gpd
import py_dss_interface
import pandas as pd
import matplotlib.pyplot as plt
import os
import contextily as ctx
import networkx as nx
import numpy as np

# ============================================================
# CONFIGURAÇÕES
# ============================================================

gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"

alimentadores = [
     '0607', '0613', '0614', '0615',
]

csv_folder = r"C:\Users\usuario\PycharmProjects\bdgdbrasilia"
horario_pico = 19

# 0.60 = condição inicial de 60% da potência nominal dos transformadores
fator_base = 0.60

# Curva diária de carga
mult = ".3 .2 .2 .2 .3 .4 .4 .5 .6 .7 .8 .9 1 .9 .8 .7 .8 .9 1 1.2 1.1 .9 .7 .5"

# Cenários de estresse
cenarios = [
    {"nome": "Base", "fator_mult": 1.0, "fp": 0.92, "carga_ponta_kw": 0},
    {"nome": "Carga Distribuída 120%", "fator_mult": 2.0, "fp": 0.92, "carga_ponta_kw": 0},
    {"nome": "Carga Distribuída 160%", "fator_mult": 2.67, "fp": 0.92, "carga_ponta_kw": 0},
    {"nome": "FP Baixo", "fator_mult": 2.67, "fp": 0.85, "carga_ponta_kw": 0},
    {"nome": "Carga na Ponta", "fator_mult": 1.0, "fp": 0.92, "carga_ponta_kw": 5000},
    {"nome": "Pior Caso", "fator_mult": 2.67, "fp": 0.85, "carga_ponta_kw": 5000},
    {"nome": "Pior Caso Extremo", "fator_mult": 3.5, "fp": 0.80, "carga_ponta_kw": 10000}
]

# Se True, força impedâncias mais severas quando não houver colunas reais de impedância
# Isso ajuda a observar sensibilidade, mas deve ser descrito como cenário conservador.
usar_impedancia_conservadora_quando_sem_dado = True

# Parâmetros típicos de transformador quando a BDGD não tiver impedância explícita
trafo_percent_r = 1.2
trafo_xhl = 4.5


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def bus(x):
    return str(x).strip().upper().replace("KV", "").replace(" ", "")


def clean_id(x):
    return str(x).strip().replace(" ", "_").replace(".", "").replace("-", "").replace("/", "_")


def limpar_numero(x):
    try:
        return float(str(x).lower().replace("kv", "").replace(",", ".").strip())
    except:
        return np.nan


def obter_coluna_existente(df, candidatos):
    """
    Procura uma coluna existente em df, ignorando diferença de maiúsculas/minúsculas.
    """
    colunas_lower = {c.lower(): c for c in df.columns}

    for candidato in candidatos:
        if candidato.lower() in colunas_lower:
            return colunas_lower[candidato.lower()]

    return None


def obter_numero_linha(row, candidatos):
    """
    Tenta obter valor numérico de uma linha usando uma lista de possíveis nomes de colunas.
    """
    for candidato in candidatos:
        if candidato in row.index:
            valor = limpar_numero(row[candidato])
            if pd.notna(valor) and valor > 0:
                return valor

    return None


def obter_impedancia_linha(row, length_km):
    """
    Tenta usar impedâncias reais, caso existam na camada SSDMT.
    Se não existirem, usa aproximação conservadora por comprimento.

    IMPORTANTE:
    A BDGD pode variar nomes de campos dependendo da distribuidora/versão.
    Por isso, esta função procura vários nomes possíveis.
    """

    candidatos_r1 = [
        "R1", "R1_OHM_KM", "R1_OHMKM", "R1_OHM_POR_KM",
        "RESISTENCIA", "RESIST", "R_OHM_KM", "R_OHMKM"
    ]

    candidatos_x1 = [
        "X1", "X1_OHM_KM", "X1_OHMKM", "X1_OHM_POR_KM",
        "REATANCIA", "REAT", "X_OHM_KM", "X_OHMKM"
    ]

    r1_real = obter_numero_linha(row, candidatos_r1)
    x1_real = obter_numero_linha(row, candidatos_x1)

    if r1_real is not None and x1_real is not None:
        return r1_real, x1_real, "real_bdgd"

    # Fallback: valores típicos/conservadores por comprimento
    if usar_impedancia_conservadora_quando_sem_dado:
        if length_km < 0.1:
            r1, x1 = 1.20, 0.70
        elif length_km < 0.5:
            r1, x1 = 0.95, 0.55
        else:
            r1, x1 = 0.75, 0.45
        return r1, x1, "estimada_conservadora"

    # Fallback mais leve, parecido com sua versão anterior
    if length_km < 0.1:
        r1, x1 = 0.70, 0.40
    elif length_km < 0.5:
        r1, x1 = 0.50, 0.35
    else:
        r1, x1 = 0.30, 0.30

    return r1, x1, "estimada_simples"


def encontrar_ponta_eletrica(ssdmt, pac_ini):
    """
    Encontra a ponta elétrica do alimentador usando grafo.

    Em vez de usar ssdmt.iloc[-1], monta um grafo com PAC_1 e PAC_2
    e busca o nó mais distante da origem pelo comprimento acumulado.
    """
    G = nx.Graph()

    for _, row in ssdmt.iterrows():
        b1 = bus(row["PAC_1"])
        b2 = bus(row["PAC_2"])

        if b1 == "" or b2 == "":
            continue

        try:
            length_km = max(float(row["Shape_Length"]) / 1000, 0.001)
        except:
            length_km = 0.001

        G.add_edge(b1, b2, weight=length_km)

    if pac_ini not in G.nodes:
        print(f"Aviso: PAC inicial {pac_ini} não encontrado no grafo. Usando última barra como fallback.")
        return bus(ssdmt.iloc[-1]["PAC_2"]), None

    distancias = nx.single_source_dijkstra_path_length(G, pac_ini, weight="weight")

    if not distancias:
        return bus(ssdmt.iloc[-1]["PAC_2"]), None

    ponta = max(distancias, key=distancias.get)
    distancia_total_km = distancias[ponta]

    return ponta, distancia_total_km


def classificar_criticidade(tensao):
    if pd.isna(tensao):
        return "Sem dado"
    elif tensao < 0.90:
        return "Crítico"
    elif tensao < 0.93:
        return "Atenção"
    elif tensao < 0.97:
        return "Alerta leve"
    else:
        return "Adequado"


def cor_criticidade(status):
    if status == "Crítico":
        return "red"
    elif status == "Atenção":
        return "orange"
    elif status == "Alerta leve":
        return "yellow"
    elif status == "Adequado":
        return "green"
    else:
        return "gray"


# ============================================================
# CARREGAMENTO DOS DADOS
# ============================================================

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

print("Colunas SSDMT disponíveis:")
print(list(ssdmt_total.columns))
print("\n")


# ============================================================
# SIMULAÇÃO
# ============================================================

resultados_resumo = []
resultados_detalhados = {}

for alim_id in alimentadores:

    print(f"\nSimulando alimentador {alim_id}...")

    ssdmt = ssdmt_total[ssdmt_total["CTMT"] == alim_id].copy()
    untrmt = untrmt_total[untrmt_total["CTMT"] == alim_id].copy()
    unsemt = unsemt_total[unsemt_total["CTMT"] == alim_id].copy()

    print(f"{alim_id}: {len(ssdmt)} trechos, {len(untrmt)} trafos, {len(unsemt)} chaves")

    if len(ssdmt) == 0:
        print(f"{alim_id} ignorado: sem trechos.")
        continue

    pac_ini = bus(ssdmt.iloc[0]["PAC_1"])
    ponta_alimentador, distancia_ponta_km = encontrar_ponta_eletrica(ssdmt, pac_ini)

    print(f"{alim_id} - PAC inicial: {pac_ini}")
    print(f"{alim_id} - Ponta elétrica encontrada: {ponta_alimentador} | distância aprox.: {distancia_ponta_km:.2f} km")

    resultados_detalhados[alim_id] = {
        "tensao": {},
        "corrente": {}
    }

    for cenario in cenarios:

        nome_cenario = cenario["nome"]
        fator_mult = cenario["fator_mult"]
        fp_carga = cenario["fp"]
        carga_ponta_kw = cenario["carga_ponta_kw"]

        carregamento_percentual = fator_base * fator_mult * 100

        print(
            f"  Cenário: {nome_cenario} | "
            f"Carregamento distribuído: {carregamento_percentual:.0f}% | "
            f"FP: {fp_carga} | "
            f"Carga na ponta: {carga_ponta_kw} kW"
        )

        dss = py_dss_interface.DSS()
        dss.text("Clear")

        dss.text(
            f"New Circuit.{alim_id} "
            f"bus1={pac_ini} basekv=13.8 phases=3 pu=1.0"
        )

        dss.text(f"New Loadshape.dia_tipo npts=24 interval=1 mult=({mult})")

        qtd_linhas_imp_real = 0
        qtd_linhas_imp_estimada = 0

        # --- Linhas MT ---
        for _, row in ssdmt.iterrows():
            b1 = bus(row["PAC_1"])
            b2 = bus(row["PAC_2"])
            cod = clean_id(row["COD_ID"])
            length = max(float(row["Shape_Length"]) / 1000, 0.001)

            r1, x1, origem_imp = obter_impedancia_linha(row, length)

            if origem_imp == "real_bdgd":
                qtd_linhas_imp_real += 1
            else:
                qtd_linhas_imp_estimada += 1

            dss.text(
                f"New Line.L_{cod} "
                f"bus1={b1} bus2={b2} phases=3 "
                f"length={length:.6f} units=km "
                f"r1={r1:.6f} x1={x1:.6f} "
                f"c1=0"
            )

        # --- Chaves ---
        for _, row in unsemt.iterrows():
            b1 = bus(row["PAC_1"])
            b2 = bus(row["PAC_2"])
            cod = clean_id(row["COD_ID"])

            dss.text(
                f"New Line.SW_{cod} "
                f"bus1={b1} bus2={b2} phases=3 "
                f"length=0.001 units=km "
                f"r1=0.001 x1=0.001 c1=0"
            )

        potencia_distribuida_total_kw = 0

        # --- Transformadores e cargas distribuídas ---
        for _, row in untrmt.iterrows():
            bus_mt = bus(row["PAC_1"])
            cod = clean_id(row["COD_ID"])
            pot_kva = limpar_numero(row["POT_NOM"])

            if bus_mt == "" or pd.isna(pot_kva) or pot_kva <= 0:
                continue

            bus_bt = f"{bus_mt}_BT"

            dss.text(
                f"New Transformer.T_{cod} "
                f"phases=3 windings=2 "
                f"buses=[{bus_mt} {bus_bt}] "
                f"kvs=[13.8 0.38] "
                f"kvas=[{pot_kva:.2f} {pot_kva:.2f}] "
                f"%r={trafo_percent_r:.2f} "
                f"xhl={trafo_xhl:.2f}"
            )

            kw_carga = pot_kva * fator_base * fator_mult
            potencia_distribuida_total_kw += kw_carga

            dss.text(
                f"New Load.L_{cod} "
                f"bus1={bus_bt}.1.2.3 "
                f"phases=3 kv=0.38 "
                f"kw={kw_carga:.2f} "
                f"pf={fp_carga} daily=dia_tipo"
            )

        # --- Carga concentrada na ponta elétrica ---
        if carga_ponta_kw > 0:
            dss.text(
                f"New Load.CARGA_PONTA_{alim_id}_{clean_id(nome_cenario)} "
                f"bus1={ponta_alimentador}.1.2.3 "
                f"phases=3 kv=13.8 "
                f"kw={carga_ponta_kw:.2f} "
                f"pf={fp_carga}"
            )

        potencia_total_kw = potencia_distribuida_total_kw + carga_ponta_kw

        # --- Configuração da simulação ---
        dss.text("Set VoltageBases=[13.8, 0.38]")
        dss.text("CalcVoltageBases")
        dss.text("Reset")
        dss.text("Set mode=daily stepsize=1h number=1")

        for h in range(1, horario_pico + 1):
            dss.text("Solve")

        # --- Perdas totais do circuito ---
        losses = dss.circuit.losses
        perda_kw = losses[0] / 1000
        perda_kvar = losses[1] / 1000

        eficiencia_percentual = (
            100 * (1 - perda_kw / potencia_total_kw)
            if potencia_total_kw > 0 else None
        )

        dss.text(f"cd {csv_folder}")

        # --- Exportar tensões ---
        dss.text("Export Voltages")
        arquivo_v = os.path.join(csv_folder, f"{alim_id}_EXP_VOLTAGES.CSV")

        if not os.path.exists(arquivo_v):
            print(f"Aviso: arquivo de tensão não encontrado para {alim_id}")
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
            serie_tensao = (
                df_v_mt[["pu1", "pu2", "pu3"]]
                .replace(0, pd.NA)
                .mean(axis=1)
                .reset_index(drop=True)
            )

            resultados_detalhados[alim_id]["tensao"][nome_cenario] = serie_tensao

            tensao_min = serie_tensao.min()
            tensao_media = serie_tensao.mean()
            barras_abaixo_097 = (serie_tensao < 0.97).sum()
            barras_abaixo_093 = (serie_tensao < 0.93).sum()
            barras_abaixo_090 = (serie_tensao < 0.90).sum()

        else:
            tensao_min = None
            tensao_media = None
            barras_abaixo_097 = None
            barras_abaixo_093 = None
            barras_abaixo_090 = None

        # --- Exportar correntes ---
        dss.text("Export Currents")
        arquivo_i = os.path.join(csv_folder, f"{alim_id}_EXP_CURRENTS.CSV")

        if not os.path.exists(arquivo_i):
            print(f"Aviso: arquivo de corrente não encontrado para {alim_id}")
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
            serie_corrente = (
                df_i_linhas[colunas_corrente]
                .max(axis=1)
                .reset_index(drop=True)
            )

            resultados_detalhados[alim_id]["corrente"][nome_cenario] = serie_corrente
            corrente_max = serie_corrente.max()
        else:
            corrente_max = None

        resultados_resumo.append({
            "Alimentador": alim_id,
            "Cenario": nome_cenario,
            "Fator_Base": fator_base,
            "Fator_Carga": fator_mult,
            "Carregamento_Distribuido_%": carregamento_percentual,
            "Fator_Potencia": fp_carga,
            "Carga_Ponta_kW": carga_ponta_kw,
            "Ponta_Eletrica": ponta_alimentador,
            "Distancia_Ponta_km": distancia_ponta_km,
            "Potencia_Total_kW": potencia_total_kw,
            "Tensao_Minima_pu": tensao_min,
            "Tensao_Media_pu": tensao_media,
            "Corrente_Maxima_A": corrente_max,
            "Perda_Ativa_kW": perda_kw,
            "Perda_Reativa_kVAr": perda_kvar,
            "Eficiencia_%": eficiencia_percentual,
            "Barras_Abaixo_0_97": barras_abaixo_097,
            "Barras_Abaixo_0_93": barras_abaixo_093,
            "Barras_Abaixo_0_90": barras_abaixo_090,
            "Linhas_Impedancia_Real_BDGD": qtd_linhas_imp_real,
            "Linhas_Impedancia_Estimada": qtd_linhas_imp_estimada,
            "Trafo_percent_R": trafo_percent_r,
            "Trafo_XHL": trafo_xhl
        })


# ============================================================
# RESULTADOS E EXPORTAÇÃO
# ============================================================

df_resultados = pd.DataFrame(resultados_resumo)

arquivo_saida = os.path.join(csv_folder, "resumo_qualidade_energia_cenarios_melhorado.xlsx")
df_resultados.to_excel(arquivo_saida, index=False)

print("\nResumo exportado para:")
print(arquivo_saida)

print("\n=== RESUMO DOS RESULTADOS ===")
print(df_resultados.head())


# ============================================================
# GRÁFICOS
# ============================================================

# --- GRÁFICO 1: TENSÃO MÍNIMA POR CENÁRIO ---
plt.figure(figsize=(14, 7))

for alim_id in df_resultados["Alimentador"].unique():
    df_alim = df_resultados[df_resultados["Alimentador"] == alim_id]

    plt.plot(
        df_alim["Cenario"],
        df_alim["Tensao_Minima_pu"],
        marker="o",
        linewidth=2,
        label=alim_id
    )

plt.axhline(0.97, color="yellow", linestyle="--", label="Alerta leve 0.97 p.u.")
plt.axhline(0.93, color="orange", linestyle="--", label="Limite 0.93 p.u.")
plt.axhline(0.90, color="red", linestyle="--", label="Limite crítico 0.90 p.u.")

plt.title("Tensão Mínima por Cenário de Estresse")
plt.xlabel("Cenário")
plt.ylabel("Tensão Mínima (p.u.)")
plt.xticks(rotation=30, ha="right")
plt.grid(True, alpha=0.3)
plt.legend(ncol=3)
plt.tight_layout()
plt.show()


# --- GRÁFICO 2: CORRENTE MÁXIMA POR CENÁRIO ---
plt.figure(figsize=(14, 7))

for alim_id in df_resultados["Alimentador"].unique():
    df_alim = df_resultados[df_resultados["Alimentador"] == alim_id]

    plt.plot(
        df_alim["Cenario"],
        df_alim["Corrente_Maxima_A"],
        marker="o",
        linewidth=2,
        label=alim_id
    )

plt.title("Corrente Máxima por Cenário de Estresse")
plt.xlabel("Cenário")
plt.ylabel("Corrente Máxima nas Linhas (A)")
plt.xticks(rotation=30, ha="right")
plt.grid(True, alpha=0.3)
plt.legend(ncol=3)
plt.tight_layout()
plt.show()


# --- GRÁFICO 3: PERDAS TÉCNICAS POR CENÁRIO ---
plt.figure(figsize=(14, 7))

for alim_id in df_resultados["Alimentador"].unique():
    df_alim = df_resultados[df_resultados["Alimentador"] == alim_id]

    plt.plot(
        df_alim["Cenario"],
        df_alim["Perda_Ativa_kW"],
        marker="o",
        linewidth=2,
        label=alim_id
    )

plt.title("Perdas Técnicas por Cenário de Estresse")
plt.xlabel("Cenário")
plt.ylabel("Perdas Ativas (kW)")
plt.xticks(rotation=30, ha="right")
plt.grid(True, alpha=0.3)
plt.legend(ncol=3)
plt.tight_layout()
plt.show()


# --- GRÁFICOS DETALHADOS POR ALIMENTADOR ---
cenarios_plotar = ["Base", "Carga Distribuída 160%", "FP Baixo", "Carga na Ponta", "Pior Caso", "Pior Caso Extremo"]

for alim_id, resultados in resultados_detalhados.items():

    resultados_v = resultados["tensao"]
    resultados_i = resultados["corrente"]

    if not resultados_v and not resultados_i:
        continue

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 7))

    for cenario in cenarios_plotar:
        if cenario in resultados_v:
            ax1.plot(
                resultados_v[cenario],
                label=cenario,
                linewidth=2
            )

    ax1.axhspan(0.97, 1.05, facecolor="green", alpha=0.08)
    ax1.axhspan(0.93, 0.97, facecolor="yellow", alpha=0.18)
    ax1.axhspan(0.90, 0.93, facecolor="orange", alpha=0.18)
    ax1.axhspan(0.00, 0.90, facecolor="red", alpha=0.10)
    ax1.axhline(y=0.97, color="gold", linestyle="--", alpha=0.7)
    ax1.axhline(y=0.93, color="orange", linestyle="--", alpha=0.7)
    ax1.axhline(y=0.90, color="red", linestyle="--", alpha=0.7)

    ax1.set_title(f"Perfil de Tensão - {alim_id} às {horario_pico}:00h")
    ax1.set_ylabel("Tensão (p.u.)")
    ax1.set_xlabel("Barras da Rede")
    ax1.set_ylim(0.80, 1.12)
    ax1.legend(title="Cenário")
    ax1.grid(True, alpha=0.3)

    for cenario in cenarios_plotar:
        if cenario in resultados_i:
            ax2.plot(
                resultados_i[cenario],
                label=cenario,
                linewidth=2
            )

    ax2.set_title(f"Fluxo de Corrente nas Linhas - {alim_id} às {horario_pico}:00h")
    ax2.set_ylabel("Corrente Máxima por Fase (A)")
    ax2.set_xlabel("Trechos de Linhas")
    ax2.legend(title="Cenário")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()


# --- RANKING DE FRAGILIDADE ---
ranking = (
    df_resultados
    .sort_values(["Tensao_Minima_pu", "Perda_Ativa_kW"], ascending=[True, False])
)

print("\n=== RANKING DE FRAGILIDADE POR MENOR TENSÃO ===")
print(ranking[[
    "Alimentador",
    "Cenario",
    "Carregamento_Distribuido_%",
    "Fator_Potencia",
    "Carga_Ponta_kW",
    "Ponta_Eletrica",
    "Distancia_Ponta_km",
    "Tensao_Minima_pu",
    "Corrente_Maxima_A",
    "Perda_Ativa_kW",
    "Barras_Abaixo_0_97",
    "Barras_Abaixo_0_93",
    "Barras_Abaixo_0_90"
]].head(20))


# ============================================================
# MAPAS
# ============================================================

# --- MAPA DE CRITICIDADE POR CENÁRIO ---
print("\nGerando mapa de criticidade dos alimentadores...")

cenario_mapa = "Pior Caso Extremo"  # troque para: "Base", "Pior Caso", "Carga na Ponta" etc.

df_mapa = df_resultados[df_resultados["Cenario"] == cenario_mapa].copy()

df_mapa["Status"] = df_mapa["Tensao_Minima_pu"].apply(classificar_criticidade)
df_mapa["Cor"] = df_mapa["Status"].apply(cor_criticidade)

ssdmt_web = ssdmt_total.to_crs(epsg=3857)

fig, ax = plt.subplots(figsize=(18, 14))

for _, row in df_mapa.iterrows():
    alim = row["Alimentador"]
    cor = row["Cor"]
    status = row["Status"]
    tensao_min = row["Tensao_Minima_pu"]

    rede = ssdmt_web[ssdmt_web["CTMT"] == alim]

    if rede.empty:
        continue

    rede.plot(
        ax=ax,
        color=cor,
        linewidth=4,
        alpha=0.95,
        label=f"{alim} - {status} ({tensao_min:.3f} p.u.)"
    )

ctx.add_basemap(
    ax,
    source=ctx.providers.OpenStreetMap.Mapnik
)

plt.title(f"Mapa de Criticidade dos Alimentadores - {cenario_mapa}")
plt.legend(
    title="Criticidade por Tensão",
    fontsize=8,
    ncol=2,
    loc="upper left"
)

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
    source=ctx.providers.OpenStreetMap.Mapnik
)

plt.title("Mapa Real do Sistema de Distribuição - Alimentadores Selecionados")
plt.legend(
    title="Alimentadores",
    fontsize=7,
    ncol=3,
    loc="upper left"
)

plt.show()

print("\nAnálise ampliada melhorada concluída com sucesso!")
