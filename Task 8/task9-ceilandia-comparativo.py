# =============================================================================
# ANÁLISE ELÉTRICA COMPARATIVA — DOIS ALIMENTADORES RESIDENCIAIS DE CEILÂNDIA
# task9-ceilandia-comparativo.py
#
# OBJETIVO:
#   Comparar o alimentador CN15 (já analisado) com um segundo alimentador
#   residencial de Ceilândia, utilizando exatamente a mesma metodologia.
#
# ETAPAS:
#   1.  Identificar alimentadores candidatos em Ceilândia
#   2.  Selecionar automaticamente o melhor para comparação
#   3.  Confirmar parâmetros metodológicos idênticos ao CN15
#   4.  Auditar impedâncias (TIP_CND / R1 / X1 / origem)
#   5.  Diagnóstico topológico completo
#   6.  Cenários de carregamento: 20/40/60/80/100/120%
#   7.  Validar Vmin (20 menores tensões + auditoria barra crítica)
#   8.  Faixas de tensão por cenário
#   9.  Tabelas comparativas com CN15
#   10. Gráficos comparativos (G1-G4)
#   11. Tabela estrutural comparativa
#   12. Insights técnicos baseados em evidência numérica
#   13. Questão central da pesquisa (evidência: forte/moderada/inconclusiva)
#   14. Varredura 10-100% + refinamento para encontrar limiar 0,93 p.u.
#   15. Relatório final em arquivo .txt
#
# PRESERVAÇÃO:
#   task9.py NÃO é alterado. Funções são importadas dinamicamente.
#
# =============================================================================

import importlib.util
import math
import os
import sys
import warnings
import glob

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import py_dss_interface

matplotlib.rcParams.update({
    "font.family": "DejaVu Sans",
    "figure.dpi": 120,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

# =============================================================================
# CONFIGURACOES PRINCIPAIS
# =============================================================================

GDB_PATH    = r"C:\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
PASTA_SAIDA = r"C:\Users\adm\Documents\Analise-Alimentador\alimentador_ic"

# Alimentador de referencia ja analisado (nao sera reprocessado)
CODIGO_CN15 = "CN15"

# Resultados conhecidos do CN15 por cenario (hardcoded - auditados)
CN15_RESULTADOS = {
    "Rede 20%":  {"vmin": 0.947540, "vmean": 0.972447},
    "Rede 40%":  {"vmin": 0.899403, "vmean": 0.946117},
    "Base 60%":  {"vmin": 0.856327, "vmean": 0.922294},
    "Rede 80%":  {"vmin": 0.817410, "vmean": 0.900433},
    "Rede 100%": {"vmin": 0.782030, "vmean": 0.880212},
    "Rede 120%": {"vmin": 0.749770, "vmean": 0.861452},
}
CN15_ESTRUTURA = {
    "trechos_mt":            1920,
    "transformadores":        398,
    "potencia_instalada_kva": 13300,
    "comprimento_total_km":   128.5,
    "distancia_eletrica_km":  16.42,
    "r1_medio":               1.252664,
    "r1_mediano":             1.5289,
}

# Parametros metodologicos - IDENTICOS ao CN15 (nao alterar)
TENSAO_MT_KV = 13.8
TENSAO_BT_KV = 0.38
CRS_METRICO  = 31983
FP_BASE      = 0.92
TRAFO_PERCENT_R = 1.2
TRAFO_XHL       = 4.5
ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS = True
USAR_IMPEDANCIA_CONSERVADORA        = True
TIPO_SIMULACAO = "Snapshot estatico"

# Cenarios principais - exatamente os mesmos do CN15
CENARIOS_REDE = [
    {"nome": "Rede 20%",  "carregamento_rede": 0.20, "fp": FP_BASE},
    {"nome": "Rede 40%",  "carregamento_rede": 0.40, "fp": FP_BASE},
    {"nome": "Base 60%",  "carregamento_rede": 0.60, "fp": FP_BASE},
    {"nome": "Rede 80%",  "carregamento_rede": 0.80, "fp": FP_BASE},
    {"nome": "Rede 100%", "carregamento_rede": 1.00, "fp": FP_BASE},
    {"nome": "Rede 120%", "carregamento_rede": 1.20, "fp": FP_BASE},
]

# Criterios para selecao do segundo alimentador
MIN_TRECHOS_MT      = 200
MIN_TRANSFORMADORES = 100
MIN_POTENCIA_KVA    = 3000
MAX_POTENCIA_KVA    = 30000

# Parametros de controle
SIMULAR = True

# Referencia ao 0,93 p.u. (limiar de carregamento do modelo)
LIMIAR_VMIN_PU = 0.93

PONTE_CN12_BUS1 = "SCN_CN12_9158_CEIRJ001_ATV"
PONTE_CN12_BUS2 = "SCN_CN12_9121_CEI054"
PONTE_CN12_COMPRIMENTO_KM = 0.014799

IMPEDANCIAS_SEGCON = {}


def carregar_impedancias_segcon(gdb_path):
    """Carrega R1/X1 oficiais por TIP_CND a partir da camada SEGCON."""
    global IMPEDANCIAS_SEGCON

    segcon = gpd.read_file(gdb_path, layer="SEGCON")
    colunas = {str(col).upper(): col for col in segcon.columns}
    ausentes = [col for col in ["COD_ID", "R1", "X1"] if col not in colunas]
    if ausentes:
        raise KeyError(f"SEGCON sem as colunas obrigatorias: {ausentes}")

    mapa = {}
    for _, row in segcon.iterrows():
        codigo = str(row[colunas["COD_ID"]]).strip()
        r1 = limpar_numero(row[colunas["R1"]])
        x1 = limpar_numero(row[colunas["X1"]])
        if codigo and pd.notna(r1) and pd.notna(x1) and r1 > 0 and x1 > 0:
            mapa[codigo] = (r1, x1)

    if not mapa:
        raise ValueError("Nenhuma impedancia valida foi carregada da SEGCON.")
    IMPEDANCIAS_SEGCON = mapa
    print(f"Impedancias carregadas da SEGCON: {len(mapa)} tipos de condutor")


TABELA_IMPEDANCIA_TIP_CND = {
    "63_A4_3_1": (0.50, 0.35),
    "84_A4_3_1": (0.33, 0.34),
    "70_A4_3_1": (0.45, 0.35),
    "94_A4_3_1": (0.30, 0.33),
    "47_A4_1_1": (0.70, 0.40),
    "68_A4_3_1": (0.40, 0.35),
}

# =============================================================================
# IMPORTACAO DINAMICA DE FUNCOES DO task9.py
# =============================================================================

def _importar_task9():
    """
    Importa o modulo task9.py sem alterar o arquivo original.
    Retorna o modulo carregado ou None em caso de falha.
    """
    task9_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "task9.py"
    )
    if not os.path.exists(task9_path):
        print(f"  AVISO: task9.py nao encontrado em '{task9_path}'.")
        return None

    spec   = importlib.util.spec_from_file_location("task9_module", task9_path)
    modulo = importlib.util.module_from_spec(spec)
    modulo.USAR_IMPEDANCIA_CONSERVADORA = USAR_IMPEDANCIA_CONSERVADORA
    modulo.ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS = ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS
    modulo.TENSAO_MT_KV = TENSAO_MT_KV
    modulo.TENSAO_BT_KV = TENSAO_BT_KV
    modulo.CRS_METRICO  = CRS_METRICO
    modulo.FP_BASE      = FP_BASE
    modulo.FP_BAIXO     = 0.85
    modulo.TRAFO_PERCENT_R = TRAFO_PERCENT_R
    modulo.TRAFO_XHL    = TRAFO_XHL
    modulo.TIPO_SIMULACAO = TIPO_SIMULACAO
    modulo.GDB_PATH     = GDB_PATH
    modulo.PASTA_SAIDA  = PASTA_SAIDA
    modulo.PAC_INICIAL_MANUAL = None
    modulo.DEMANDA_TOTAL_ALVO_KVA = None
    modulo.CENARIOS_REDE = CENARIOS_REDE
    modulo.CARREGAMENTOS_TRAFO_ALVO = []
    modulo.ALIMENTADORES_ESTUDO = {}
    modulo.ALIMENTADORES_ATIVOS = []
    modulo.SIMULAR = False
    try:
        spec.loader.exec_module(modulo)
        print(f"  [OK] task9.py importado de: {task9_path}")
        return modulo
    except Exception as err:
        print(f"  ERRO ao importar task9.py: {err}")
        return None


_t9 = _importar_task9()


# --- Bind de funcoes: usa task9 quando disponivel, copia local como fallback ---

def bus(valor):
    if pd.isna(valor): return ""
    return str(valor).strip().upper().replace("KV", "").replace(" ", "")

def clean_id(valor):
    return str(valor).strip().replace(" ","_").replace(".","").replace("-","").replace("/","_").replace("\\","_")

def limpar_numero(valor):
    try:
        return float(str(valor).lower().replace("kv","").replace(",",".").strip())
    except: return np.nan

def obter_coluna_existente(df, candidatos):
    mapa = {str(c).lower(): c for c in df.columns}
    for c in candidatos:
        if c.lower() in mapa: return mapa[c.lower()]
    return None

def obter_numero_linha(row, candidatos):
    mapa = {str(c).lower(): c for c in row.index}
    for c in candidatos:
        real = mapa.get(c.lower())
        if real is None: continue
        v = limpar_numero(row[real])
        if pd.notna(v) and v > 0: return v
    return None

def comprimento_km_linha(row):
    v = limpar_numero(row.get("COMPRIMENTO_REAL_KM", np.nan))
    if pd.notna(v) and v > 0: return max(v, 0.00001)
    vs = limpar_numero(row.get("Shape_Length", np.nan))
    if pd.notna(vs) and vs > 0: return max(vs/1000.0, 0.00001)
    return 0.00001

def calcular_comprimentos_geometria(ssdmt_original):
    ssdmt = ssdmt_original.copy().to_crs(epsg=CRS_METRICO)
    geom_vazia = ssdmt.geometry.is_empty | ssdmt.geometry.isna()
    ssdmt["COMPRIMENTO_REAL_KM"] = np.where(geom_vazia, 0.00001, ssdmt.geometry.length/1000.0)
    ssdmt_geo = ssdmt.to_crs(epsg=4326)
    return ssdmt, ssdmt_geo

def interpretar_estado_chave(valor_bruto):
    if pd.isna(valor_bruto): return "indefinido"
    t = str(valor_bruto).strip().upper()
    if t in {"AB","ABERTA","ABERTO","OPEN","OFF","A","0"}: return "aberta"
    if t in {"FE","FECHADA","FECHADO","CLOSED","ON","F","1"}: return "fechada"
    return "indefinido"

def chave_esta_fechada(row):
    for campo in ["P_N_OPE","ESTADO","STATUS","SITCONT","POS","EST_OPER","SITUACAO"]:
        if campo not in row.index: continue
        interp = interpretar_estado_chave(row[campo])
        if interp == "aberta":  return False, campo, row[campo], interp
        if interp == "fechada": return True,  campo, row[campo], interp
    return ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS, None, None, "indefinido"

def construir_grafo(ssdmt, unsemt):
    grafo = nx.Graph()
    elementos = {}
    ch_ab = ch_fe = ch_ind = 0
    for _, row in ssdmt.iterrows():
        b1, b2 = bus(row.get("PAC_1")), bus(row.get("PAC_2"))
        if not b1 or not b2 or b1==b2: continue
        cod = clean_id(row.get("COD_ID"))
        comp = comprimento_km_linha(row)
        grafo.add_edge(b1, b2, weight=comp, tipo="linha", codigo=cod)
        elementos[f"LINE.L_{cod}".upper()] = {"b1":b1,"b2":b2,"comprimento_km":comp,"tipo":"linha"}
    for _, row in unsemt.iterrows():
        b1, b2 = bus(row.get("PAC_1")), bus(row.get("PAC_2"))
        if not b1 or not b2 or b1==b2: continue
        fechada, _, _, interp = chave_esta_fechada(row)
        if interp=="aberta": ch_ab+=1
        elif interp=="fechada": ch_fe+=1
        else: ch_ind+=1
        if not fechada: continue
        cod = clean_id(row.get("COD_ID"))
        grafo.add_edge(b1, b2, weight=0.00001, tipo="chave", codigo=cod)
        elementos[f"LINE.SW_{cod}".upper()] = {"b1":b1,"b2":b2,"comprimento_km":0.00001,"tipo":"chave"}
    n_nos = grafo.number_of_nodes()
    n_are = grafo.number_of_edges()
    n_comp = nx.number_connected_components(grafo) if n_nos>0 else 0
    ciclos_euler = max(0, n_are - n_nos + n_comp)
    try: ciclos_nx = len(nx.cycle_basis(grafo))
    except: ciclos_nx = -1
    folhas = sum(1 for n in grafo.nodes if grafo.degree(n)==1)

    diag = {"chaves_abertas":ch_ab,"chaves_fechadas":ch_fe,"chaves_indefinido":ch_ind,
            "nos":n_nos,"arestas":n_are,"componentes":n_comp,
            "ciclos_euler":ciclos_euler,"ciclos_nx":ciclos_nx,"nos_folha_grau1":folhas}
    
    # PONTE TOPOLOGICA PARA CN12
    b1_ponte = PONTE_CN12_BUS1
    b2_ponte = PONTE_CN12_BUS2
    if b1_ponte in grafo.nodes and b2_ponte in grafo.nodes:
        grafo.add_edge(b1_ponte, b2_ponte, weight=PONTE_CN12_COMPRIMENTO_KM, tipo="chave_virtual", codigo="PONTE_VIRTUAL_CN12")
        elementos["LINE.SW_PONTE_VIRTUAL_CN12"] = {"b1":b1_ponte, "b2":b2_ponte, "comprimento_km":PONTE_CN12_COMPRIMENTO_KM, "tipo":"chave"}
        diag["arestas"] += 1
        diag["chaves_fechadas"] += 1
        diag["componentes"] = nx.number_connected_components(grafo)
    
    return grafo, elementos, diag

def analisar_topologia(grafo, pac_inicial, diag_grafo):
    componente = nx.node_connected_component(grafo, pac_inicial)
    sub = grafo.subgraph(componente).copy()
    dist = nx.single_source_dijkstra_path_length(sub, pac_inicial, weight="weight")
    ponta = max(dist, key=dist.get)
    dist_ponta = dist[ponta]
    try: caminho = nx.shortest_path(sub, pac_inicial, ponta, weight="weight")
    except: caminho = [pac_inicial, ponta]
    comp_total = sum(d.get("weight",0) for _,_,d in sub.edges(data=True))
    return {"subgrafo":sub,"distancias":dist,"ponta":ponta,"distancia_ponta_km":dist_ponta,
            "barras_alcancadas":len(componente),"barras_totais":grafo.number_of_nodes(),
            "pct_alcancadas":100.0*len(componente)/grafo.number_of_nodes() if grafo.number_of_nodes()>0 else 0.0,
            "arestas_alcancadas":sub.number_of_edges(),"comprimento_total_km":comp_total,
            "caminho_origem_ponta":caminho}

def escolher_pac_inicial(ssdmt, grafo, gdb_path, pac_manual=None):
    if pac_manual:
        origem = bus(pac_manual)
        if origem not in grafo:
            raise ValueError(f"PAC manual ausente do grafo: {origem}")
        return origem, "manual (PAC_INICIAL_MANUAL)"

    alim_id = str(ssdmt.iloc[0].get("CTMT", "")).strip()
    ctmt = gpd.read_file(gdb_path, layer="CTMT", where=f"COD_ID = '{alim_id}'")
    if not ctmt.empty and "PAC_INI" in ctmt.columns:
        origem = bus(ctmt.iloc[0]["PAC_INI"])
        if origem in grafo:
            return origem, "CTMT coluna 'PAC_INI'"
        raise ValueError(f"PAC_INI oficial '{origem}' ausente do grafo de {alim_id}.")

    raise ValueError(f"Nao foi possivel obter PAC_INI oficial para {alim_id}.")

def obter_impedancia_linha(row, length_km):
    col_tip = obter_coluna_existente(row.to_frame().T, ["TIP_CND","TIPO_CND","TIP_COND"])
    if col_tip:
        tip = str(row[col_tip]).strip()
        if tip in IMPEDANCIAS_SEGCON:
            r1, x1 = IMPEDANCIAS_SEGCON[tip]
            return r1, x1, "segcon_bdgd"
        if tip in TABELA_IMPEDANCIA_TIP_CND:
            r1, x1 = TABELA_IMPEDANCIA_TIP_CND[tip]
            return r1, x1, "tabela_tip_cnd"
            
    candidatos_r = ["R1","R1_OHM_KM","R1_OHMKM","RESISTENCIA"]
    candidatos_x = ["X1","X1_OHM_KM","X1_OHMKM","REATANCIA"]
    r1 = obter_numero_linha(row, candidatos_r)
    x1 = obter_numero_linha(row, candidatos_x)
    if r1 is not None and x1 is not None: return r1, x1, "real_bdgd"
    if USAR_IMPEDANCIA_CONSERVADORA:
        if length_km < 0.1: return 1.20, 0.70, "estimada_conservadora"
        if length_km < 0.5: return 0.95, 0.55, "estimada_conservadora"
        return 0.75, 0.45, "estimada_conservadora"
    if length_km < 0.1: return 0.70, 0.40, "estimada_simples"
    if length_km < 0.5: return 0.50, 0.35, "estimada_simples"
    return 0.30, 0.30, "estimada_simples"

def analisar_tensoes(df_v, distancias):
    df = df_v.copy()
    df.columns = df.columns.str.strip()
    col_bus  = obter_coluna_existente(df, ["Bus","BusName","BUS"])
    col_base = obter_coluna_existente(df, ["BasekV","Base kV","BASEKV"])
    if col_base is not None:
        base_num = pd.to_numeric(df[col_base], errors="coerce")
        df = df[base_num.between(7.0, 14.5)].copy()
    for nm in ["pu1","pu2","pu3"]:
        col = obter_coluna_existente(df, [nm])
        if col: df[col] = pd.to_numeric(df[col], errors="coerce").replace(0, np.nan)
    df["Barra"] = df[col_bus].apply(bus)
    col_pu1 = obter_coluna_existente(df, ["pu1"])
    col_pu2 = obter_coluna_existente(df, ["pu2"])
    col_pu3 = obter_coluna_existente(df, ["pu3"])
    df["V_fase1_pu"] = df[col_pu1] if col_pu1 else np.nan
    df["V_fase2_pu"] = df[col_pu2] if col_pu2 else np.nan
    df["V_fase3_pu"] = df[col_pu3] if col_pu3 else np.nan
    fases = [c for c in ["V_fase1_pu","V_fase2_pu","V_fase3_pu"] if c in df.columns]
    df["Tensao_Media_pu"]     = df[fases].mean(axis=1)
    df["Tensao_Min_Fases_pu"] = df[fases].min(axis=1)
    df["Tensao_pu"]            = df["Tensao_Media_pu"]
    df["Distancia_km"]         = df["Barra"].map(distancias)
    df = df[df["Distancia_km"].notna()].copy()
    return df[["Barra","Distancia_km","Tensao_Media_pu","Tensao_Min_Fases_pu","Tensao_pu"]].sort_values("Distancia_km").reset_index(drop=True)

# =============================================================================
# FUNCAO AUXILIAR: SALVAR FIGURA
# =============================================================================

def salvar_figura(fig, pasta, nome_arquivo):
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, nome_arquivo)
    fig.savefig(caminho, dpi=150, bbox_inches="tight")
    print(f"  Grafico salvo: {caminho}")
    plt.close(fig)

# =============================================================================
# ETAPA 1 - IDENTIFICAR ALIMENTADORES CANDIDATOS
# =============================================================================

def listar_candidatos_ceilandia(gdb_path, codigo_excluir=CODIGO_CN15):
    """
    Etapa 1: Le SSDMT e UNTRMT da BDGD e lista todos os alimentadores
    com trechos em Ceilandia (prefixo CN).
    """
    print("\n" + "=" * 60)
    print("ETAPA 1 - IDENTIFICAR ALIMENTADORES CANDIDATOS EM CEILANDIA")
    print("=" * 60)

    print("\nLendo SSDMT (filtro CN%)...")
    try:
        ssdmt_all = gpd.read_file(gdb_path, layer="SSDMT", where="CTMT LIKE 'CN%'")
    except Exception as err:
        print(f"  AVISO: filtro LIKE falhou ({err}). Lendo camada completa...")
        ssdmt_all = gpd.read_file(gdb_path, layer="SSDMT")
        ssdmt_all = ssdmt_all[ssdmt_all["CTMT"].astype(str).str.startswith("CN")].copy()

    if ssdmt_all.empty:
        print("  Nenhum trecho CN encontrado. Lendo camada completa...")
        ssdmt_all = gpd.read_file(gdb_path, layer="SSDMT")

    ssdmt_all["CTMT"] = ssdmt_all["CTMT"].astype(str).str.strip()
    ssdmt_all = ssdmt_all.to_crs(epsg=CRS_METRICO)
    geom_vazia = ssdmt_all.geometry.is_empty | ssdmt_all.geometry.isna()
    ssdmt_all["COMPRIMENTO_REAL_KM"] = np.where(
        geom_vazia, 0.00001, ssdmt_all.geometry.length / 1000.0
    )

    trechos_por_ctmt = (
        ssdmt_all.groupby("CTMT", as_index=False)
        .agg(
            trechos_mt=("CTMT", "size"),
            comprimento_total_km=("COMPRIMENTO_REAL_KM", "sum"),
        )
    )

    print(f"  CTMTs CN encontrados na BDGD: {len(trechos_por_ctmt)}")

    ctmts = trechos_por_ctmt["CTMT"].tolist()
    filtro = " OR ".join([f"CTMT = '{c}'" for c in ctmts[:50]])

    print("  Lendo UNTRMT...")
    try:
        untrmt_all = gpd.read_file(gdb_path, layer="UNTRMT", where=filtro)
    except Exception:
        untrmt_all = gpd.read_file(gdb_path, layer="UNTRMT")
        untrmt_all = untrmt_all[untrmt_all["CTMT"].astype(str).isin(ctmts)].copy()

    untrmt_all["CTMT"]        = untrmt_all["CTMT"].astype(str).str.strip()
    untrmt_all["POT_NOM_NUM"] = untrmt_all["POT_NOM"].apply(limpar_numero)

    trafos_por_ctmt = (
        untrmt_all[untrmt_all["POT_NOM_NUM"] > 0]
        .groupby("CTMT", as_index=False)
        .agg(
            transformadores=("CTMT", "size"),
            potencia_instalada_kva=("POT_NOM_NUM", "sum"),
        )
    )

    print("  Lendo UNSEMT...")
    try:
        unsemt_all = gpd.read_file(gdb_path, layer="UNSEMT", where=filtro)
    except Exception:
        unsemt_all = gpd.read_file(gdb_path, layer="UNSEMT")
        unsemt_all = unsemt_all[unsemt_all["CTMT"].astype(str).isin(ctmts)].copy()

    unsemt_all["CTMT"] = unsemt_all["CTMT"].astype(str).str.strip()
    chaves_por_ctmt = (
        unsemt_all.groupby("CTMT", as_index=False)
        .agg(chaves=("CTMT", "size"))
    )

    candidatos = trechos_por_ctmt.merge(trafos_por_ctmt, on="CTMT", how="left")
    candidatos = candidatos.merge(chaves_por_ctmt,   on="CTMT", how="left")
    candidatos["transformadores"]        = candidatos["transformadores"].fillna(0).astype(int)
    candidatos["potencia_instalada_kva"] = candidatos["potencia_instalada_kva"].fillna(0)
    candidatos["chaves"]                 = candidatos["chaves"].fillna(0).astype(int)

    candidatos = candidatos[candidatos["CTMT"] != codigo_excluir].copy()
    candidatos = candidatos.sort_values(
        ["transformadores", "comprimento_total_km"], ascending=[False, False]
    ).reset_index(drop=True)

    print("\n" + "-" * 90)
    print(f"{'CTMT':<8} {'Trechos':>8} {'Comp.total(km)':>15} {'Trafos':>8} {'Pot.inst.(kVA)':>15} {'Chaves':>7}")
    print("-" * 90)
    for _, row in candidatos.head(20).iterrows():
        print(
            f"{row['CTMT']:<8} {row['trechos_mt']:>8} "
            f"{row['comprimento_total_km']:>15.2f} {row['transformadores']:>8} "
            f"{row['potencia_instalada_kva']:>15.0f} {row['chaves']:>7}"
        )
    print("-" * 90)
    if len(candidatos) > 20:
        print(f"  ... e mais {len(candidatos)-20} alimentadores.")

    return candidatos, ssdmt_all, untrmt_all, unsemt_all


# =============================================================================
# ETAPA 2 - SELECIONAR ALIMENTADOR PARA COMPARACAO
# =============================================================================

def selecionar_alimentador_comparativo(candidatos):
    """
    Etapa 2: Seleciona automaticamente o melhor alimentador para comparacao.
    """
    print("\n" + "=" * 60)
    print("ETAPA 2 - SELECIONAR ALIMENTADOR PARA COMPARACAO")
    print("=" * 60)

    df = candidatos.copy()
    df_filtrado = df[
        (df["trechos_mt"] >= MIN_TRECHOS_MT) &
        (df["transformadores"] >= MIN_TRANSFORMADORES) &
        (df["potencia_instalada_kva"] >= MIN_POTENCIA_KVA) &
        (df["potencia_instalada_kva"] <= MAX_POTENCIA_KVA)
    ].copy()

    if df_filtrado.empty:
        print("  Nenhum candidato passou pelos filtros. Relaxando criterios...")
        df_filtrado = df[df["transformadores"] >= 50].copy()

    if df_filtrado.empty:
        df_filtrado = df.copy()

    cn15_pot = CN15_ESTRUTURA["potencia_instalada_kva"]
    df_filtrado = df_filtrado.copy()
    df_filtrado["score_pot"] = 1.0 - abs(
        df_filtrado["potencia_instalada_kva"] - cn15_pot * 0.65
    ) / (cn15_pot + 1e-9)

    max_trec = df_filtrado["trechos_mt"].max()
    df_filtrado["score_tamanho"] = df_filtrado["trechos_mt"] / (max_trec + 1e-9)

    df_filtrado["score_total"] = (
        0.6 * df_filtrado["score_pot"] +
        0.4 * df_filtrado["score_tamanho"]
    )
    df_filtrado = df_filtrado.sort_values("score_total", ascending=False)

    selecionado = df_filtrado.iloc[0]
    alim_id = selecionado["CTMT"]

    print(f"""
ALIMENTADOR SELECIONADO PARA COMPARACAO
-----------------------------------------
Codigo:              {alim_id}
Trechos MT:          {int(selecionado['trechos_mt'])}
Comprimento total:   {selecionado['comprimento_total_km']:.2f} km
Transformadores:     {int(selecionado['transformadores'])}
Potencia instalada:  {selecionado['potencia_instalada_kva']:.0f} kVA
Chaves:              {int(selecionado['chaves'])}

JUSTIFICATIVA DA ESCOLHA:
  - Alimentador CN da Ceilandia com dados completos na BDGD
  - {int(selecionado['transformadores'])} transformadores (representativo)
  - Potencia instalada de {selecionado['potencia_instalada_kva']:.0f} kVA
    (referencia: CN15 = {cn15_pot:.0f} kVA)
  - Selecionado por score composto de adequacao estrutural
  - Nao e o maior da lista para garantir comparacao util
""")

    return alim_id, selecionado


# =============================================================================
# ETAPA 4 - AUDITORIA DE IMPEDANCIAS
# =============================================================================

def auditar_impedancias(ssdmt):
    """
    Etapa 4: Audita R1/X1 por trecho.
    Verifica fallback R1=1.20 ohm/km (antigo).
    """
    print("\n" + "=" * 60)
    print("ETAPA 4 - AUDITORIA DE IMPEDANCIAS")
    print("=" * 60)

    linhas_audit = []
    r1_vals, x1_vals = [], []
    qtd_real = qtd_estimada = qtd_fallback_120 = qtd_tabela = 0

    col_tip = obter_coluna_existente(ssdmt, ["TIP_CND","TIPO_CND","TIP_COND","TIPO_COND","TIPOCND"])

    for _, row in ssdmt.iterrows():
        length = comprimento_km_linha(row)
        r1, x1, origem = obter_impedancia_linha(row, length)
        tip = str(row[col_tip]).strip() if col_tip else "N/D"
        r1_vals.append(r1)
        x1_vals.append(x1)
        if origem in {"real_bdgd", "segcon_bdgd"}: qtd_real += 1
        elif origem == "tabela_tip_cnd": qtd_tabela += 1
        else: qtd_estimada += 1
        
        if abs(r1 - 1.20) < 1e-6: qtd_fallback_120 += 1
        linhas_audit.append({
            "TIP_CND": tip, "R1": r1, "X1": x1,
            "Comprimento_km": length, "Origem": origem,
            "Fallback_1_20": abs(r1 - 1.20) < 1e-6,
        })

    df_audit = pd.DataFrame(linhas_audit)

    if col_tip:
        df_tip = (
            df_audit.groupby("TIP_CND")
            .agg(quantidade=("R1","count"), R1_medio=("R1","mean"), X1_medio=("X1","mean"))
            .reset_index().sort_values("quantidade", ascending=False)
        )
        if qtd_real == len(df_audit):
            df_tip["Origem"] = "SEGCON_BDGD"
        elif qtd_real == 0:
            df_tip["Origem"] = "estimada_conservadora"
        else:
            df_tip["Origem"] = "misto_BDGD_estimada"
    else:
        df_tip = pd.DataFrame({
            "TIP_CND": ["N/D"],
            "quantidade": [len(df_audit)],
            "R1_medio": [np.mean(r1_vals)],
            "X1_medio": [np.mean(x1_vals)],
            "Origem": ["estimada_conservadora"],
        })

    r1_arr = np.array(r1_vals)
    x1_arr = np.array(x1_vals)

    print(f"\n  Estatisticas R1 (ohm/km):")
    print(f"    Minimo:   {r1_arr.min():.4f}")
    print(f"    Medio:    {r1_arr.mean():.4f}")
    print(f"    Mediano:  {np.median(r1_arr):.4f}")
    print(f"    Maximo:   {r1_arr.max():.4f}")
    print(f"\n  Estatisticas X1 (ohm/km):")
    print(f"    Minimo:   {x1_arr.min():.4f}")
    print(f"    Medio:    {x1_arr.mean():.4f}")
    print(f"    Mediano:  {np.median(x1_arr):.4f}")
    print(f"    Maximo:   {x1_arr.max():.4f}")
    print(f"\n  Trechos com R1/X1 real (BDGD):       {qtd_real}")
    print(f"  Trechos com tabela TIP_CND:           {qtd_tabela}")
    print(f"  Trechos com impedancia estimada:      {qtd_estimada}")
    print(f"  Trechos com R1=1,20 ohm/km (fallback): {qtd_fallback_120}")

    return {
        "r1_min": float(r1_arr.min()), "r1_medio": float(r1_arr.mean()),
        "r1_mediano": float(np.median(r1_arr)), "r1_max": float(r1_arr.max()),
        "x1_min": float(x1_arr.min()), "x1_medio": float(x1_arr.mean()),
        "x1_mediano": float(np.median(x1_arr)), "x1_max": float(x1_arr.max()),
        "qtd_real": qtd_real, "qtd_estimada": qtd_estimada,
        "qtd_tabela": qtd_tabela, "qtd_fallback_120": qtd_fallback_120,
    }, df_tip


# =============================================================================
# ETAPA 5 - DIAGNOSTICO TOPOLOGICO
# =============================================================================

def imprimir_diagnostico_topologico(alim_id, grafo, diag_grafo, topo, pac_inicial, metodo_origem):
    """Etapa 5: Imprime diagnostico topologico completo."""
    print("\n" + "=" * 60)
    print(f"ETAPA 5 - DIAGNOSTICO TOPOLOGICO: {alim_id}")
    print("=" * 60)
    print(f"""
  Nos totais no grafo:              {diag_grafo['nos']}
  Arestas totais no grafo:          {diag_grafo['arestas']}
  Componentes conectados:           {diag_grafo['componentes']}
  Ciclos (formula Euler):           {diag_grafo['ciclos_euler']}
  Ciclos (nx.cycle_basis):          {diag_grafo['ciclos_nx']}
  Folhas (grau 1):                  {diag_grafo['nos_folha_grau1']}

  Barras energizadas:               {topo['barras_alcancadas']}
  Barras totais:                    {topo['barras_totais']}
  % de barras alcancadas:           {topo['pct_alcancadas']:.1f}%

  COMPRIMENTO TOTAL DA REDE:        {topo['comprimento_total_km']:.3f} km
  DISTANCIA ELETRICA MAXIMA:        {topo['distancia_ponta_km']:.3f} km

  PAC inicial (origem):             {pac_inicial}
  Metodo de determinacao:           {metodo_origem}
  Ponta eletrica:                   {topo['ponta']}
  Nos no caminho origem->ponta:     {len(topo['caminho_origem_ponta'])}

  Chaves abertas identificadas:     {diag_grafo['chaves_abertas']}
  Chaves fechadas identificadas:    {diag_grafo['chaves_fechadas']}
  Chaves indefinidas:               {diag_grafo['chaves_indefinido']}
  -> Hipotese indefinidas:          {'FECHADAS' if ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS else 'ABERTAS'}
""")
    if diag_grafo["ciclos_euler"] > 0:
        print(f"  AVISO: {diag_grafo['ciclos_euler']} ciclo(s) detectado(s) no grafo.")


# =============================================================================
# SIMULACAO OPENDSS (cenario unico)
# =============================================================================

def simular_cenario_local(
    dss, alim_id, pac_inicial, cenario,
    linhas_energizadas, chaves_energizadas, trafos_energizados,
    elementos, distancias, pasta_saida_alim,
    distancia_max_km, comprimento_total_km,
):
    """
    Executa um cenario no OpenDSS com parametros identicos ao CN15.
    model=1, Vminpu=0.95, Vmaxpu=1.05, status=fixed, conn=wye.
    """
    nome         = cenario["nome"]
    carregamento = cenario["carregamento_rede"]
    fp           = cenario["fp"]

    print(f"\n  Cenario: {nome} | Carregamento: {carregamento*100:.0f}% | FP: {fp:.2f}")

    dss.text("Clear")
    dss.text(
        f"New Circuit.{alim_id} "
        f"bus1={pac_inicial} basekv={TENSAO_MT_KV} phases=3 pu=1.0"
    )

    imp_real = imp_estimada = 0

    for _, row in linhas_energizadas.iterrows():
        b1     = bus(row["PAC_1"])
        b2     = bus(row["PAC_2"])
        cod    = clean_id(row["COD_ID"])
        length = comprimento_km_linha(row)
        r1, x1, orig = obter_impedancia_linha(row, length)
        if orig in {"real_bdgd", "segcon_bdgd"}: imp_real += 1
        else:                    imp_estimada += 1
        dss.text(
            f"New Line.L_{cod} bus1={b1} bus2={b2} phases=3 "
            f"length={length:.6f} units=km r1={r1:.6f} x1={x1:.6f} c1=0"
        )

    for _, row in chaves_energizadas.iterrows():
        fechada, _, _, _ = chave_esta_fechada(row)
        if not fechada: continue
        b1  = bus(row["PAC_1"])
        b2  = bus(row["PAC_2"])
        cod = clean_id(row["COD_ID"])
        dss.text(
            f"New Line.SW_{cod} bus1={b1} bus2={b2} phases=3 "
            f"length=0.00001 units=km r1=0.001 x1=0.001 c1=0"
        )

    # Reparo topologico validado por uma lacuna geografica de 14,8 m na BDGD.
    # A mesma conexao precisa existir no OpenDSS, nao apenas no grafo NetworkX.
    if alim_id == "CN12":
        dss.text(
            f"New Line.SW_PONTE_VIRTUAL_CN12 "
            f"bus1={PONTE_CN12_BUS1} bus2={PONTE_CN12_BUS2} phases=3 "
            f"length={PONTE_CN12_COMPRIMENTO_KM:.6f} units=km "
            f"r1=0.001 x1=0.001 c1=0"
        )

    pot_total_kw = pot_total_kva = 0.0
    trafos_modelados = 0

    for _, row in trafos_energizados.iterrows():
        bus_mt  = bus(row["PAC_1"])
        cod     = clean_id(str(row["COD_ID"]).strip())
        pot_kva = limpar_numero(row["POT_NOM"])
        if not bus_mt or pd.isna(pot_kva) or pot_kva <= 0: continue
        carga_kva = pot_kva * carregamento
        carga_kw  = carga_kva * fp
        bus_bt    = f"{bus_mt}_BT_{cod}"
        dss.text(
            f"New Transformer.T_{cod} phases=3 windings=2 "
            f"buses=[{bus_mt} {bus_bt}] kvs=[{TENSAO_MT_KV} {TENSAO_BT_KV}] "
            f"kvas=[{pot_kva:.3f} {pot_kva:.3f}] "
            f"%r={TRAFO_PERCENT_R:.3f} xhl={TRAFO_XHL:.3f}"
        )
        dss.text(
            f"New Load.L_{cod} bus1={bus_bt}.1.2.3 phases=3 kv={TENSAO_BT_KV} "
            f"kw={carga_kw:.3f} pf={fp:.4f} "
            f"model=1 Vminpu=0.95 Vmaxpu=1.05 status=fixed conn=wye"
        )
        pot_total_kw  += carga_kw
        pot_total_kva += carga_kva
        trafos_modelados += 1

    dss.text(f"Set VoltageBases=[{TENSAO_MT_KV}, {TENSAO_BT_KV}]")
    dss.text("CalcVoltageBases")
    dss.text("Set mode=snapshot")
    dss.text("Solve")

    convergiu = bool(dss.solution.converged)
    if not convergiu:
        warnings.warn(f"  Cenario '{nome}' nao convergiu!")

    losses     = dss.circuit.losses
    perda_kw   = losses[0] / 1000.0
    perda_kvar = losses[1] / 1000.0

    tp           = dss.circuit.total_power
    p_fonte_kw   = abs(float(tp[0]))
    q_fonte_kvar = abs(float(tp[1]))
    s_fonte_kva  = np.hypot(p_fonte_kw, q_fonte_kvar)

    # Limpar CSVs antigos e exportar tensoes
    for csv_file in glob.glob(os.path.join(pasta_saida_alim, "*EXP_*.CSV")):
        try: os.remove(csv_file)
        except OSError: pass

    os.makedirs(pasta_saida_alim, exist_ok=True)
    dss.text(f'cd "{pasta_saida_alim}"')
    dss.text("Export Voltages")

    esperado = os.path.join(pasta_saida_alim, f"{alim_id}_EXP_VOLTAGES.CSV")
    if not os.path.exists(esperado):
        candidatos_csv = glob.glob(os.path.join(pasta_saida_alim, "*EXP_VOLTAGES*.CSV"))
        esperado = max(candidatos_csv, key=os.path.getmtime) if candidatos_csv else None

    if esperado is None or not os.path.exists(esperado):
        raise FileNotFoundError(f"CSV de tensoes nao encontrado em {pasta_saida_alim}")

    tensoes = analisar_tensoes(pd.read_csv(esperado), distancias)

    tensao_min   = tensoes["Tensao_pu"].min()
    tensao_media = tensoes["Tensao_pu"].mean()
    p_efetiva_kw = p_fonte_kw - perda_kw
    efic_fluxo   = 100.0 * p_efetiva_kw / p_fonte_kw if p_fonte_kw > 0 else np.nan
    efic_nom     = (100.0 * pot_total_kw / (pot_total_kw + perda_kw)
                    if (pot_total_kw + perda_kw) > 0 else np.nan)

    print(
        f"    Convergiu: {convergiu} | Vmin: {tensao_min:.4f} p.u. | "
        f"Vmean: {tensao_media:.4f} p.u. | Efic.: {efic_fluxo:.1f}%"
    )

    total_barras = len(tensoes)
    return {
        "Alimentador":               alim_id,
        "Cenario":                   nome,
        "Convergiu":                 convergiu,
        "Carregamento_Rede_%":       carregamento * 100,
        "Fator_Potencia":            fp,
        "Transformadores_Modelados": trafos_modelados,
        "P_Carga_Nominal_kW":        pot_total_kw,
        "S_Carga_Nominal_kVA":       pot_total_kva,
        "P_Fonte_kW":                p_fonte_kw,
        "Q_Fonte_kVAr":              q_fonte_kvar,
        "S_Fonte_kVA":               s_fonte_kva,
        "P_Efetiva_kW":              p_efetiva_kw,
        "Perda_Ativa_kW":            perda_kw,
        "Perda_Reativa_kVAr":        perda_kvar,
        "Tensao_Minima_pu":          tensao_min,
        "Tensao_Media_pu":           tensao_media,
        "Eficiencia_Nominal_%":      efic_nom,
        "Eficiencia_Fluxo_%":        efic_fluxo,
        "Comprimento_Total_km":      comprimento_total_km,
        "Distancia_Maxima_km":       distancia_max_km,
        "Imp_Real_BDGD":             imp_real,
        "Imp_Estimada":              imp_estimada,
        "Total_Barras":              total_barras,
        "Barras_Abaixo_0_90":        int((tensoes["Tensao_pu"] < 0.90).sum()),
        "Barras_Entre_090_093":      int(((tensoes["Tensao_pu"] >= 0.90) & (tensoes["Tensao_pu"] < 0.93)).sum()),
        "Barras_Entre_093_105":      int(((tensoes["Tensao_pu"] >= 0.93) & (tensoes["Tensao_pu"] <= 1.05)).sum()),
        "Barras_Acima_1_05":         int((tensoes["Tensao_pu"] > 1.05).sum()),
        "Tipo_Simulacao":            TIPO_SIMULACAO,
    }, tensoes


# =============================================================================
# ETAPA 6 - EXECUTAR CENARIOS
# =============================================================================

def executar_cenarios(
    alim_id, pac_inicial, topo,
    linhas_energizadas, chaves_energizadas, trafos_energizados,
    elementos, pasta_saida_alim, cenarios_lista,
):
    """Etapa 6: Executa todos os cenarios e coleta resultados."""
    print("\n" + "=" * 60)
    print(f"ETAPA 6 - CENARIOS DE CARREGAMENTO: {alim_id}")
    print("=" * 60)

    dss = py_dss_interface.DSS()
    resumo = []
    tensoes_por_cenario = {}

    for cenario in cenarios_lista:
        try:
            res, tensoes = simular_cenario_local(
                dss=dss, alim_id=alim_id, pac_inicial=pac_inicial, cenario=cenario,
                linhas_energizadas=linhas_energizadas, chaves_energizadas=chaves_energizadas,
                trafos_energizados=trafos_energizados, elementos=elementos,
                distancias=topo["distancias"], pasta_saida_alim=pasta_saida_alim,
                distancia_max_km=topo["distancia_ponta_km"],
                comprimento_total_km=topo["comprimento_total_km"],
            )
            resumo.append(res)
            tensoes_por_cenario[cenario["nome"]] = tensoes
        except Exception as err:
            warnings.warn(f"  Erro no cenario '{cenario['nome']}': {err}")

    return resumo, tensoes_por_cenario


# =============================================================================
# ETAPA 7 - VALIDAR VMIN
# =============================================================================

def validar_vmin(alim_id, tensoes_60pct, topo, ssdmt, untrmt):
    """Etapa 7: Auditoria da barra de Vmin no cenario de 60%."""
    print("\n" + "=" * 60)
    print(f"ETAPA 7 - VALIDACAO DO VMIN (60%): {alim_id}")
    print("=" * 60)

    if tensoes_60pct is None or tensoes_60pct.empty:
        print("  Sem dados de tensao para o cenario de 60%.")
        return

    df_v = tensoes_60pct.sort_values("Tensao_pu").reset_index(drop=True)
    vmin       = df_v["Tensao_pu"].min()
    barra_vmin = df_v.iloc[0]["Barra"]
    dist_vmin  = df_v.iloc[0]["Distancia_km"]

    print(f"\n  Vmin MT (60%):          {vmin:.4f} p.u.")
    print(f"  Barra:                  {barra_vmin}")
    print(f"  Distancia da origem:    {dist_vmin:.3f} km")
    print(f"  Tensao fase-neutro:     {vmin * TENSAO_MT_KV / math.sqrt(3):.3f} kV")
    print(f"  Tensao fase-fase:       {vmin * TENSAO_MT_KV:.3f} kV")

    barra_up   = str(barra_vmin).upper()
    col_tip    = obter_coluna_existente(ssdmt, ["TIP_CND","TIPO_CND","TIP_COND"])
    trecho_info = "N/D"
    for _, row in ssdmt.iterrows():
        if bus(row.get("PAC_2","")) == barra_up:
            cod  = str(row.get("COD_ID",""))
            comp = comprimento_km_linha(row)
            r1, x1, orig = obter_impedancia_linha(row, comp)
            tip  = str(row[col_tip]).strip() if col_tip else "N/D"
            trecho_info = (f"COD_ID={cod} | comp={comp:.4f} km | "
                           f"TIP_CND={tip} | R1={r1:.4f} | X1={x1:.4f} | {orig}")
            break
    print(f"\n  Trecho MT que alimenta: {trecho_info}")

    trafo_info = "N/D"
    for _, row in untrmt.iterrows():
        if bus(row.get("PAC_1","")) == barra_up:
            trafo_info = str(row.get("COD_ID","")) + f" | {limpar_numero(row.get('POT_NOM',0)):.0f} kVA"
            break
    print(f"  Transformador assoc.:   {trafo_info}")

    print(f"\n  20 MENORES TENSOES MT - cenario 60%:")
    print(f"  {'#':>3} {'Barra':<30} {'Vpu':>8} {'Dist_km':>10}")
    print("  " + "-" * 55)
    for i, row in df_v.head(20).iterrows():
        print(f"  {i+1:>3} {str(row['Barra']):<30} {row['Tensao_pu']:>8.4f} {row['Distancia_km']:>10.3f}")

    limiar_1pct    = vmin * 1.01
    n_proximo_vmin = (df_v["Tensao_pu"] <= limiar_1pct).sum()
    pct_proximo    = 100.0 * n_proximo_vmin / len(df_v)
    print(f"\n  Barras dentro de +1% do Vmin (<= {limiar_1pct:.4f}): {n_proximo_vmin} ({pct_proximo:.1f}%)")
    if pct_proximo > 5:
        print("  -> Vmin DISTRIBUIDO: regiao com muitas barras em tensao semelhante.")
    else:
        print("  -> Vmin ISOLADO: ocorre em barra especifica.")


# =============================================================================
# ETAPA 8 - FAIXAS DE TENSAO
# =============================================================================

def imprimir_faixas_tensao(alim_id, resumo_lista):
    """Etapa 8: Faixas de tensao por cenario (condicao simulada)."""
    print("\n" + "=" * 60)
    print(f"ETAPA 8 - FAIXAS DE TENSAO MT: {alim_id}")
    print("=" * 60)
    print("  [Condicao simulada sob as hipoteses adotadas]\n")
    print(f"  {'Cenario':<15} {'Total':>6} {'<0,90 n(%)':>12} {'0,90-0,93 n(%)':>16} {'0,93-1,05 n(%)':>16} {'>1,05 n(%)':>12}")
    print("  " + "-" * 80)
    for res in resumo_lista:
        if res.get("Cenario","").startswith("Var"): continue
        total = max(res.get("Total_Barras", 1), 1)
        ab090 = res.get("Barras_Abaixo_0_90", 0)
        en093 = res.get("Barras_Entre_090_093", 0)
        en105 = res.get("Barras_Entre_093_105", 0)
        ac105 = res.get("Barras_Acima_1_05", 0)
        print(
            f"  {res['Cenario']:<15} {total:>6} "
            f"{ab090:>4}({100*ab090/total:.0f}%) "
            f"{en093:>6}({100*en093/total:.0f}%)      "
            f"{en105:>6}({100*en105/total:.0f}%)      "
            f"{ac105:>4}({100*ac105/total:.0f}%)"
        )


# =============================================================================
# ETAPA 9 - TABELAS COMPARATIVAS
# =============================================================================

def imprimir_tabelas_comparativas(alim_id, resumo_lista):
    """Etapa 9: Tabelas Vmin e Vmean comparando CN15 vs. novo alimentador."""
    print("\n" + "=" * 60)
    print("ETAPA 9 - COMPARACAO DIRETA COM CN15")
    print("=" * 60)

    cenarios_p = list(CN15_RESULTADOS)
    res_novo   = {r["Cenario"]: r for r in resumo_lista}

    print(f"\n  Tabela Vmin (p.u.):")
    print(f"  {'Cenario':<12} {'CN15':>10} {alim_id:>14} {'Delta':>10}")
    print("  " + "-" * 50)
    for cen in cenarios_p:
        cn15_v  = CN15_RESULTADOS.get(cen, {}).get("vmin", np.nan)
        novo_v  = res_novo.get(cen, {}).get("Tensao_Minima_pu", np.nan)
        delta   = (novo_v - cn15_v) if pd.notna(novo_v) and pd.notna(cn15_v) else np.nan
        d_str   = f"{delta:+.4f}" if pd.notna(delta) else "N/D"
        n_str   = f"{novo_v:.4f}" if pd.notna(novo_v) else "N/D"
        print(f"  {cen:<12} {cn15_v:>10.4f} {n_str:>14} {d_str:>10}")

    print(f"\n  Tabela Vmean (p.u.):")
    print(f"  {'Cenario':<12} {'CN15':>10} {alim_id:>14}")
    print("  " + "-" * 40)
    for cen in cenarios_p:
        cn15_vm = CN15_RESULTADOS.get(cen, {}).get("vmean", np.nan)
        novo_vm = res_novo.get(cen, {}).get("Tensao_Media_pu", np.nan)
        n_str   = f"{novo_vm:.4f}" if pd.notna(novo_vm) else "N/D"
        print(f"  {cen:<12} {cn15_vm:>10.4f} {n_str:>14}")


# =============================================================================
# ETAPA 10 - GRAFICOS COMPARATIVOS
# =============================================================================

def gerar_graficos_comparativos(alim_id, pasta_comp, resumo_lista, tensoes_por_cenario):
    """
    Etapa 10: Gera G1-G4 comparativos.
    G1: Vmin x carregamento   G2: Vmean x carregamento
    G3: Delta Vmin             G4: Perfil tensao x distancia (60%)
    """
    pasta_graf = os.path.join(pasta_comp, "graficos_comparativos")
    os.makedirs(pasta_graf, exist_ok=True)

    cenarios_p  = list(CN15_RESULTADOS)
    labels_x    = ["20%", "40%", "60%", "80%", "100%", "120%"]
    res_novo    = {r["Cenario"]: r for r in resumo_lista}

    cn15_vmins  = [CN15_RESULTADOS.get(c, {}).get("vmin",  np.nan) for c in cenarios_p]
    cn15_vmeans = [CN15_RESULTADOS.get(c, {}).get("vmean", np.nan) for c in cenarios_p]
    novo_vmins  = [res_novo.get(c, {}).get("Tensao_Minima_pu", np.nan) for c in cenarios_p]
    novo_vmeans = [res_novo.get(c, {}).get("Tensao_Media_pu",  np.nan) for c in cenarios_p]

    cor_cn15 = "#1f77b4"
    cor_novo = "#ff7f0e"

    # G1 - Vmin x carregamento
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(labels_x, cn15_vmins,  "o-",  color=cor_cn15, lw=2.2, ms=8, label="CN15 (referencia)")
    ax.plot(labels_x, novo_vmins,  "s--", color=cor_novo,  lw=2.2, ms=8, label=alim_id)
    ax.axhline(0.93, color="red",     lw=1.4, ls="--", label="0,93 p.u.")
    ax.axhline(0.90, color="darkred", lw=1.0, ls=":",  label="0,90 p.u.")
    ax.axhline(0.97, color="orange",  lw=1.0, ls=":",  label="0,97 p.u.")
    ax.set_xlabel("Carregamento (%)", fontsize=11)
    ax.set_ylabel("Vmin MT (p.u.)", fontsize=11)
    ax.set_title(f"G1 - Tensao Minima MT x Carregamento\nCN15 vs. {alim_id}", fontsize=12)
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3); ax.set_ylim(0.60, 1.05)
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, "G1_vmin_carregamento.png")

    # G2 - Vmean x carregamento
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(labels_x, cn15_vmeans, "o-",  color=cor_cn15, lw=2.2, ms=8, label="CN15 (referencia)")
    ax.plot(labels_x, novo_vmeans, "s--", color=cor_novo,  lw=2.2, ms=8, label=alim_id)
    ax.axhline(0.93, color="red", lw=1.4, ls="--", label="0,93 p.u.")
    ax.set_xlabel("Carregamento (%)", fontsize=11)
    ax.set_ylabel("Vmean MT (p.u.)", fontsize=11)
    ax.set_title(f"G2 - Tensao Media MT x Carregamento\nCN15 vs. {alim_id}", fontsize=12)
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3); ax.set_ylim(0.65, 1.05)
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, "G2_vmean_carregamento.png")

    # G3 - Delta Vmin
    delta_vmins = []
    for n, c in zip(novo_vmins, cn15_vmins):
        if pd.notna(n) and pd.notna(c): delta_vmins.append(n - c)
        else: delta_vmins.append(np.nan)

    cores_delta = []
    for d in delta_vmins:
        if d is None or (isinstance(d, float) and np.isnan(d)): cores_delta.append("gray")
        elif d >= 0: cores_delta.append("#2ca02c")
        else:        cores_delta.append("#d62728")

    fig, ax = plt.subplots(figsize=(10, 5))
    x_pos = range(len(labels_x))
    bars  = ax.bar(labels_x, delta_vmins, color=cores_delta, edgecolor="white", lw=1.2)
    ax.axhline(0, color="black", lw=1.0)
    ax.set_xlabel("Carregamento (%)", fontsize=11)
    ax.set_ylabel("Delta Vmin (p.u.)", fontsize=11)
    ax.set_title(f"G3 - Diferenca de Vmin: {alim_id} - CN15\n(verde = melhor; vermelho = pior)", fontsize=12)
    for bar, val in zip(bars, delta_vmins):
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            ax.text(bar.get_x() + bar.get_width()/2,
                    val + (0.001 if val >= 0 else -0.003),
                    f"{val:+.4f}", ha="center",
                    va="bottom" if val >= 0 else "top", fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, "G3_delta_vmin.png")

    # G4 - Perfil tensao x distancia (60%) para o novo alimentador
    fig, ax = plt.subplots(figsize=(12, 6))
    if "Base 60%" in tensoes_por_cenario:
        df_t = tensoes_por_cenario["Base 60%"]
        ax.scatter(df_t["Distancia_km"], df_t["Tensao_pu"],
                   c=cor_novo, s=8, alpha=0.5, label=f"{alim_id} (barras MT)")
        df_ord = df_t.sort_values("Distancia_km")
        if len(df_ord) > 50:
            size  = max(10, len(df_ord)//30)
            y_sm = (
                df_ord["Tensao_pu"]
                .rolling(window=size, center=True, min_periods=1)
                .mean()
                .to_numpy()
            )
            ax.plot(df_ord["Distancia_km"], y_sm, color=cor_novo, lw=2, label="Tendencia suavizada")
    ax.axhline(0.93, color="red",    lw=1.4, ls="--", label="0,93 p.u.")
    ax.axhline(0.90, color="darkred", lw=1.0, ls=":",  label="0,90 p.u.")
    ax.axhline(0.97, color="orange", lw=1.0, ls=":",   label="0,97 p.u.")
    ax.set_xlabel("Distancia eletrica da fonte (km)", fontsize=11)
    ax.set_ylabel("Tensao MT (p.u.)", fontsize=11)
    ax.set_title(f"G4 - Perfil Tensao x Distancia Eletrica - {alim_id} (60%)", fontsize=12)
    ax.legend(fontsize=9); ax.grid(True, alpha=0.3); ax.set_ylim(0.60, 1.10)
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"G4_perfil_tensao_distancia_{alim_id}_60pct.png")

    print(f"\n  Graficos salvos em: {pasta_graf}")


# =============================================================================
# ETAPA 11 - TABELA ESTRUTURAL
# =============================================================================

def imprimir_tabela_estrutural(alim_id, imp_stats, topo, soma_pot_kva, resumo_lista):
    """Etapa 11: Tabela comparativa estrutural CN15 vs. novo alimentador."""
    print("\n" + "=" * 60)
    print("ETAPA 11 - COMPARACAO ESTRUTURAL")
    print("=" * 60)

    res_novo    = {r["Cenario"]: r for r in resumo_lista}
    trafos_mod  = res_novo.get("Base 60%", {}).get("Transformadores_Modelados", "N/D")
    imp_real    = res_novo.get("Base 60%", {}).get("Imp_Real_BDGD", 0)
    imp_est     = res_novo.get("Base 60%", {}).get("Imp_Estimada",  0)
    trechos_tot = imp_real + imp_est

    def _gv(campo, cen):
        v = res_novo.get(cen, {}).get(campo, np.nan)
        return f"{v:.4f}" if pd.notna(v) else "N/D"

    rows = [
        ("Trechos MT",           str(CN15_ESTRUTURA["trechos_mt"]),                       str(trechos_tot)),
        ("Transformadores",      str(CN15_ESTRUTURA["transformadores"]),                   str(trafos_mod)),
        ("Potencia inst. (kVA)", f"{CN15_ESTRUTURA['potencia_instalada_kva']:.0f}",        f"{soma_pot_kva:.0f}"),
        ("Comp. total (km)",     f"{CN15_ESTRUTURA['comprimento_total_km']:.1f}",          f"{topo['comprimento_total_km']:.1f}"),
        ("Dist. elet. max (km)", f"{CN15_ESTRUTURA['distancia_eletrica_km']:.2f}",         f"{topo['distancia_ponta_km']:.2f}"),
        ("R1 medio (ohm/km)",    f"{CN15_ESTRUTURA['r1_medio']:.4f}",                      f"{imp_stats['r1_medio']:.4f}"),
        ("R1 mediano (ohm/km)",  f"{CN15_ESTRUTURA['r1_mediano']:.4f}",                    f"{imp_stats['r1_mediano']:.4f}"),
        ("Vmin 60%",             f"{CN15_RESULTADOS['Base 60%']['vmin']:.4f}",              _gv("Tensao_Minima_pu","Base 60%")),
        ("Vmean 60%",            f"{CN15_RESULTADOS['Base 60%']['vmean']:.4f}",             _gv("Tensao_Media_pu","Base 60%")),
        ("Vmin 100%",            f"{CN15_RESULTADOS['Rede 100%']['vmin']:.4f}",             _gv("Tensao_Minima_pu","Rede 100%")),
        ("Vmin 120%",            f"{CN15_RESULTADOS['Rede 120%']['vmin']:.4f}",             _gv("Tensao_Minima_pu","Rede 120%")),
    ]

    print(f"\n  {'Indicador':<25} {'CN15':>18} {alim_id:>18}")
    print("  " + "-" * 65)
    for label, cn15_val, novo_val in rows:
        print(f"  {label:<25} {cn15_val:>18} {novo_val:>18}")


# =============================================================================
# ETAPA 12 - INSIGHTS TECNICOS
# =============================================================================

def gerar_insights_tecnicos(alim_id, resumo_lista, topo, imp_stats, soma_pot_kva):
    """Etapa 12: Analise tecnica comparativa com base em evidencia numerica."""
    print("\n" + "=" * 60)
    print("ETAPA 12 - INSIGHTS TECNICOS")
    print("=" * 60)

    res_novo      = {r["Cenario"]: r for r in resumo_lista}
    vmin_novo_60  = res_novo.get("Base 60%",  {}).get("Tensao_Minima_pu", np.nan)
    vmin_cn15_60  = CN15_RESULTADOS["Base 60%"]["vmin"]
    vmin_novo_100 = res_novo.get("Rede 100%", {}).get("Tensao_Minima_pu", np.nan)
    vmin_cn15_100 = CN15_RESULTADOS["Rede 100%"]["vmin"]

    if pd.isna(vmin_novo_60):
        print("\n  Sem resultados para analise.")
        return

    delta_60  = vmin_novo_60  - vmin_cn15_60
    delta_100 = vmin_novo_100 - vmin_cn15_100 if pd.notna(vmin_novo_100) else np.nan
    limiar    = 0.02

    print(f"\n  Delta Vmin (60%):  {delta_60:+.4f} p.u.  ({alim_id} - CN15)")
    if pd.notna(delta_100):
        print(f"  Delta Vmin (100%): {delta_100:+.4f} p.u.")

    if delta_60 > limiar:
        print(f"\n  CASO A: {alim_id} apresenta tensao MELHOR que o CN15.")
        print(f"  Possiveis explicacoes (com evidencia numerica):")
        if topo["distancia_ponta_km"] < CN15_ESTRUTURA["distancia_eletrica_km"]:
            print(f"    [OK] Menor distancia eletrica: {topo['distancia_ponta_km']:.2f} km vs. {CN15_ESTRUTURA['distancia_eletrica_km']:.2f} km (CN15)")
        if soma_pot_kva < CN15_ESTRUTURA["potencia_instalada_kva"]:
            print(f"    [OK] Menor potencia instalada: {soma_pot_kva:.0f} kVA vs. {CN15_ESTRUTURA['potencia_instalada_kva']:.0f} kVA (CN15)")
        if imp_stats["r1_medio"] < CN15_ESTRUTURA["r1_medio"]:
            print(f"    [OK] R1 medio menor: {imp_stats['r1_medio']:.4f} vs. {CN15_ESTRUTURA['r1_medio']:.4f} ohm/km (CN15)")
        if topo["comprimento_total_km"] < CN15_ESTRUTURA["comprimento_total_km"]:
            print(f"    [OK] Rede menos extensa: {topo['comprimento_total_km']:.1f} km vs. {CN15_ESTRUTURA['comprimento_total_km']:.1f} km (CN15)")

    elif delta_60 < -limiar:
        print(f"\n  CASO C: {alim_id} apresenta tensao PIOR que o CN15.")
        print(f"  Possiveis explicacoes (com evidencia numerica):")
        if topo["distancia_ponta_km"] > CN15_ESTRUTURA["distancia_eletrica_km"]:
            print(f"    [!] Maior distancia eletrica: {topo['distancia_ponta_km']:.2f} km vs. {CN15_ESTRUTURA['distancia_eletrica_km']:.2f} km (CN15)")
        if soma_pot_kva > CN15_ESTRUTURA["potencia_instalada_kva"]:
            print(f"    [!] Maior potencia instalada: {soma_pot_kva:.0f} kVA vs. {CN15_ESTRUTURA['potencia_instalada_kva']:.0f} kVA (CN15)")
        if imp_stats["r1_medio"] > CN15_ESTRUTURA["r1_medio"]:
            print(f"    [!] R1 medio maior: {imp_stats['r1_medio']:.4f} vs. {CN15_ESTRUTURA['r1_medio']:.4f} ohm/km (CN15)")
    else:
        print(f"\n  CASO B: {alim_id} apresenta tensao SEMELHANTE ao CN15 (Delta < +/-{limiar:.2f} p.u.).")
        print(f"  Possivel padrao comum de alimentadores residenciais extensos de Ceilandia.")

    kva_km_novo = soma_pot_kva / topo["comprimento_total_km"] if topo["comprimento_total_km"] > 0 else np.nan
    kva_km_cn15 = CN15_ESTRUTURA["potencia_instalada_kva"] / CN15_ESTRUTURA["comprimento_total_km"]
    print(f"\n  Densidade de potencia (kVA/km):")
    print(f"    CN15:    {kva_km_cn15:.1f} kVA/km")
    print(f"    {alim_id}: {kva_km_novo:.1f} kVA/km" if pd.notna(kva_km_novo) else f"    {alim_id}: N/D")


# =============================================================================
# ETAPA 13 - QUESTAO CENTRAL DA PESQUISA
# =============================================================================

def questao_central_pesquisa(alim_id, resumo_lista):
    """Etapa 13: Responde a questao central e classifica a evidencia."""
    print("\n" + "=" * 60)
    print("ETAPA 13 - QUESTAO CENTRAL DA PESQUISA")
    print("=" * 60)

    res_novo    = {r["Cenario"]: r for r in resumo_lista}
    cenarios_p  = list(CN15_RESULTADOS.keys())
    vmins_novo  = [res_novo.get(c, {}).get("Tensao_Minima_pu", np.nan) for c in cenarios_p]
    vmins_cn15  = [CN15_RESULTADOS[c]["vmin"] for c in cenarios_p]
    vmins_novo_v = [(n, c) for n, c in zip(vmins_novo, vmins_cn15) if pd.notna(n)]

    print("""
  QUESTAO: O baixo Vmin encontrado no CN15 e caracteristica particular
  desse alimentador ou comportamento que tambem aparece em outro
  alimentador residencial de Ceilandia sob a mesma hipotese?
""")

    if not vmins_novo_v:
        print("  Sem resultados suficientes para responder.")
        return "INCONCLUSIVA", "Sem resultados."

    deltas      = [abs(n - c) for n, c in vmins_novo_v]
    delta_medio = np.mean(deltas)
    vmin_novo60 = res_novo.get("Base 60%", {}).get("Tensao_Minima_pu", np.nan)
    vmin_cn1560 = CN15_RESULTADOS["Base 60%"]["vmin"]
    ambos_093   = pd.notna(vmin_novo60) and vmin_novo60 < LIMIAR_VMIN_PU and vmin_cn1560 < LIMIAR_VMIN_PU
    ambos_090   = pd.notna(vmin_novo60) and vmin_novo60 < 0.90 and vmin_cn1560 < 0.90

    if ambos_093 and delta_medio < 0.05:
        classificacao = "FORTE"
        conclusao = (
            f"Ambos apresentam Vmin_MT < {LIMIAR_VMIN_PU:.2f} p.u. a 60%, "
            f"com desvio medio de {delta_medio:.4f} p.u. entre si. "
            "Evidencia FORTE de padrao regional."
        )
    elif ambos_093 and delta_medio < 0.10:
        classificacao = "MODERADA"
        conclusao = (
            f"Ambos apresentam Vmin_MT < {LIMIAR_VMIN_PU:.2f} p.u. a 60%, "
            f"mas com desvio medio de {delta_medio:.4f} p.u. "
            "Evidencia MODERADA de padrao regional."
        )
    elif delta_medio > 0.10:
        classificacao = "INCONCLUSIVA"
        conclusao = (
            f"Desvio medio entre alimentadores = {delta_medio:.4f} p.u. "
            "Necessario analisar mais alimentadores para conclusao definitiva."
        )
    else:
        classificacao = "MODERADA"
        conclusao = (
            f"Comportamento de tensao similar (desvio medio = {delta_medio:.4f} p.u.). "
            "Evidencia MODERADA de padrao regional."
        )

    print(f"  CLASSIFICACAO DA EVIDENCIA: {classificacao}")
    print(f"\n  CONCLUSAO:\n  {conclusao}")
    print(f"\n  Valores de referencia (60%):")
    print(f"    CN15:    Vmin = {vmin_cn1560:.4f} p.u.")
    if pd.notna(vmin_novo60):
        print(f"    {alim_id}: Vmin = {vmin_novo60:.4f} p.u.")
        print(f"    Ambos abaixo de 0,93 p.u.: {ambos_093}")
        print(f"    Ambos abaixo de 0,90 p.u.: {ambos_090}")

    return classificacao, conclusao


# =============================================================================
# ETAPA 14 - CARREGAMENTO LIMITE
# =============================================================================

def calcular_limite_carregamento(
    alim_id, pac_inicial, topo,
    linhas_energizadas, chaves_energizadas, trafos_energizados,
    elementos, pasta_saida_alim,
):
    """
    Etapa 14: Varredura 10%-100% + refinamento para Vmin = 0,93 p.u.
    Resultado como 'limite de carregamento do modelo sob as hipoteses adotadas'.
    """
    print("\n" + "=" * 60)
    print(f"ETAPA 14 - CARREGAMENTO LIMITE ({alim_id})")
    print("=" * 60)
    print(f"  Objetivo: Vmin_MT = {LIMIAR_VMIN_PU:.2f} p.u.")
    print(f"  Varredura: 10% -> 100% (passo 10%), depois refinamento 1%.\n")

    dss = py_dss_interface.DSS()
    varredura = []

    for p in range(10, 110, 10):
        cenario = {"nome": f"Var {p}%", "carregamento_rede": p/100.0, "fp": FP_BASE}
        try:
            res, _ = simular_cenario_local(
                dss=dss, alim_id=alim_id, pac_inicial=pac_inicial, cenario=cenario,
                linhas_energizadas=linhas_energizadas, chaves_energizadas=chaves_energizadas,
                trafos_energizados=trafos_energizados, elementos=elementos,
                distancias=topo["distancias"], pasta_saida_alim=pasta_saida_alim,
                distancia_max_km=topo["distancia_ponta_km"],
                comprimento_total_km=topo["comprimento_total_km"],
            )
            varredura.append((p, res["Tensao_Minima_pu"]))
            print(f"    {p:>4}%  ->  Vmin = {res['Tensao_Minima_pu']:.4f} p.u.")
        except Exception as err:
            print(f"    {p:>4}%  ->  ERRO: {err}")

    # Faixa de cruzamento
    limite_grosso = None
    for i in range(len(varredura) - 1):
        p_low, v_low = varredura[i]
        p_high, v_high = varredura[i+1]
        if v_low >= LIMIAR_VMIN_PU > v_high:
            limite_grosso = (p_low, p_high)
            break
        if v_low < LIMIAR_VMIN_PU and i == 0:
            limite_grosso = (0, p_low)
            break

    limite_refinado = None

    if limite_grosso:
        p_low, p_high = limite_grosso
        print(f"\n  Faixa de cruzamento: {p_low}% - {p_high}%")
        print("  Refinando em passo de 1%...")
        for p in range(p_low, p_high + 1):
            cenario = {"nome": f"Ref {p}%", "carregamento_rede": p/100.0, "fp": FP_BASE}
            try:
                res, _ = simular_cenario_local(
                    dss=dss, alim_id=alim_id, pac_inicial=pac_inicial, cenario=cenario,
                    linhas_energizadas=linhas_energizadas, chaves_energizadas=chaves_energizadas,
                    trafos_energizados=trafos_energizados, elementos=elementos,
                    distancias=topo["distancias"], pasta_saida_alim=pasta_saida_alim,
                    distancia_max_km=topo["distancia_ponta_km"],
                    comprimento_total_km=topo["comprimento_total_km"],
                )
                vmin = res["Tensao_Minima_pu"]
                print(f"    {p:>4}%  ->  Vmin = {vmin:.4f} p.u.")
                if vmin < LIMIAR_VMIN_PU and limite_refinado is None:
                    limite_refinado = p
                    break
            except Exception as err:
                print(f"    {p:>4}%  ->  ERRO: {err}")
    else:
        if varredura:
            min_vmin = min(v for _, v in varredura)
            if min_vmin >= LIMIAR_VMIN_PU:
                print(f"\n  Vmin nao cruzou {LIMIAR_VMIN_PU:.2f} p.u. na faixa 10-100%.")
            else:
                print(f"\n  Vmin cruza {LIMIAR_VMIN_PU:.2f} p.u. antes de 10%. Limite < 10%.")
                limite_refinado = 10

    if limite_refinado is not None:
        print(f"""
  LIMITE DE CARREGAMENTO DO MODELO (hipoteses adotadas)
  {alim_id}: aprox. {limite_refinado}% -> Vmin_MT cruza {LIMIAR_VMIN_PU:.2f} p.u.
""")
    else:
        print(f"\n  Limite a {LIMIAR_VMIN_PU:.2f} p.u. nao identificado na faixa simulada.")

    return limite_refinado, varredura


# =============================================================================
# ETAPA 15 - RELATORIO FINAL
# =============================================================================

def gerar_relatorio_final(
    alim_id, pasta_comp, selecionado_info,
    imp_stats, df_tip_cnd, topo, diag_grafo, soma_pot_kva,
    resumo_lista, classificacao_evidencia, conclusao_pesquisa,
    limite_novo_pct, varredura_novo,
):
    """Etapa 15: Gera relatorio completo em arquivo .txt."""
    sep = "=" * 72
    linhas = []
    def add(t=""): linhas.append(t)

    add(sep)
    add("RELATORIO COMPARATIVO - ALIMENTADORES RESIDENCIAIS DE CEILANDIA")
    add(f"CN15 vs. {alim_id}")
    add("Gerado por task9-ceilandia-comparativo.py")
    add(sep)

    add("\n1. ALIMENTADOR SELECIONADO")
    add("-" * 40)
    add(f"  Codigo:              {alim_id}")
    add(f"  Trechos MT:          {int(selecionado_info.get('trechos_mt', 0))}")
    add(f"  Transformadores:     {int(selecionado_info.get('transformadores', 0))}")
    add(f"  Potencia instalada:  {selecionado_info.get('potencia_instalada_kva', 0):.0f} kVA")
    add(f"  Comprimento total:   {topo['comprimento_total_km']:.2f} km")
    add(f"  Distancia eletrica:  {topo['distancia_ponta_km']:.2f} km")

    add("\n2. IMPEDANCIAS")
    add("-" * 40)
    add(f"  R1: min={imp_stats['r1_min']:.4f} | medio={imp_stats['r1_medio']:.4f} | mediano={imp_stats['r1_mediano']:.4f} | max={imp_stats['r1_max']:.4f}")
    add(f"  X1: min={imp_stats['x1_min']:.4f} | medio={imp_stats['x1_medio']:.4f} | mediano={imp_stats['x1_mediano']:.4f} | max={imp_stats['x1_max']:.4f}")
    add(f"  Trechos real BDGD:   {imp_stats['qtd_real']}")
    add(f"  Trechos estimados:   {imp_stats['qtd_estimada']}")
    add(f"  Fallback R1=1,20:    {imp_stats['qtd_fallback_120']}")

    add("\n3. RESULTADOS DOS CENARIOS")
    add("-" * 40)
    res_novo = {r["Cenario"]: r for r in resumo_lista}
    add(f"  {'Cenario':<12} {'CN15 Vmin':>10} {'Novo Vmin':>10} {'Delta':>8} {'CN15 Vmean':>11} {'Novo Vmean':>11}")
    add("  " + "-" * 65)
    for cen in CN15_RESULTADOS:
        cv  = CN15_RESULTADOS.get(cen, {}).get("vmin",  np.nan)
        cvm = CN15_RESULTADOS.get(cen, {}).get("vmean", np.nan)
        nv  = res_novo.get(cen, {}).get("Tensao_Minima_pu",  np.nan)
        nvm = res_novo.get(cen, {}).get("Tensao_Media_pu",   np.nan)
        d   = (nv - cv) if pd.notna(nv) and pd.notna(cv) else np.nan
        add(
            f"  {cen:<12} {cv:>10.4f} "
            f"{(f'{nv:.4f}' if pd.notna(nv) else 'N/D'):>10} "
            f"{(f'{d:+.4f}' if pd.notna(d) else 'N/D'):>8} "
            f"{cvm:>11.4f} "
            f"{(f'{nvm:.4f}' if pd.notna(nvm) else 'N/D'):>11}"
        )

    add("\n4. LIMITES DE CARREGAMENTO DO MODELO")
    add("-" * 40)
    add(f"  CN15:    Vmin < {LIMIAR_VMIN_PU:.2f} p.u. ja no cenario de 60% (limite < 60%)")
    add(f"  {alim_id}: " + (f"aprox. {limite_novo_pct}%" if limite_novo_pct else "Nao cruzou na faixa 10-100%"))

    add("\n5. QUESTAO CENTRAL DA PESQUISA")
    add("-" * 40)
    add(f"  Classificacao da evidencia: {classificacao_evidencia}")
    add(f"\n  {conclusao_pesquisa}")

    add("\n6. LIMITACOES DA ANALISE")
    add("-" * 40)
    add("  - Modelo de carga simplificado (model=1, potencia constante)")
    add("  - Impedancias de transformadores estimadas (%R=1.2, XHL=4.5)")
    add("  - Cenarios de carregamento globais (sem demanda real calibrada)")
    add("  - Origem oficial obtida da coluna PAC_INI da camada CTMT")
    add("  - Carga uniformemente distribuida entre todos os transformadores")
    add("  - Resultados sao condicoes simuladas sob as hipoteses adotadas")
    add("  - Nao afirmar automaticamente violacao PRODIST")

    add("\n" + sep)
    add("FIM DO RELATORIO")
    add(sep)

    relatorio = "\n".join(linhas)
    print("\n\n" + relatorio)

    arq = os.path.join(pasta_comp, f"relatorio_comparativo_CN15_vs_{alim_id}.txt")
    with open(arq, "w", encoding="utf-8") as f:
        f.write(relatorio)
    print(f"\n  Relatorio salvo em: {arq}")
    return arq


# =============================================================================
# EXPORTAR PLANILHA COMPARATIVA
# =============================================================================

def exportar_planilha_comparativa(alim_id, pasta_comp, resumo_lista, df_tip_cnd, imp_stats, topo, soma_pot_kva):
    """Exporta planilha Excel consolidada."""
    arq = os.path.join(pasta_comp, f"comparativo_CN15_vs_{alim_id}.xlsx")
    df_resumo = pd.DataFrame(resumo_lista)

    cn15_rows = [
        {"Alimentador":"CN15","Cenario":c,"Tensao_Minima_pu":d["vmin"],"Tensao_Media_pu":d["vmean"]}
        for c, d in CN15_RESULTADOS.items()
    ]
    df_cn15 = pd.DataFrame(cn15_rows)

    with pd.ExcelWriter(arq, engine="openpyxl") as writer:
        df_resumo.to_excel(writer, sheet_name=f"Resultados_{alim_id}", index=False)
        df_cn15.to_excel(writer,   sheet_name="Resultados_CN15_ref",   index=False)
        df_tip_cnd.to_excel(writer, sheet_name="Impedancias_TIP_CND",  index=False)

        struct = pd.DataFrame([
            {"Indicador":"Alimentador",         "CN15":"CN15",                                        alim_id:alim_id},
            {"Indicador":"Potencia_kVA",        "CN15":CN15_ESTRUTURA["potencia_instalada_kva"],      alim_id:soma_pot_kva},
            {"Indicador":"Comp_total_km",       "CN15":CN15_ESTRUTURA["comprimento_total_km"],        alim_id:topo["comprimento_total_km"]},
            {"Indicador":"Dist_eletrica_km",    "CN15":CN15_ESTRUTURA["distancia_eletrica_km"],       alim_id:topo["distancia_ponta_km"]},
            {"Indicador":"R1_medio_ohm_km",     "CN15":CN15_ESTRUTURA["r1_medio"],                    alim_id:imp_stats["r1_medio"]},
            {"Indicador":"R1_mediano_ohm_km",   "CN15":CN15_ESTRUTURA["r1_mediano"],                  alim_id:imp_stats["r1_mediano"]},
        ])
        struct.to_excel(writer, sheet_name="Estrutura_Comparativa", index=False)

        pd.DataFrame([
            {"Parametro":"Tensao_MT_kV",          "Valor":TENSAO_MT_KV},
            {"Parametro":"Tensao_BT_kV",          "Valor":TENSAO_BT_KV},
            {"Parametro":"FP_base",               "Valor":FP_BASE},
            {"Parametro":"Carga_model",           "Valor":1},
            {"Parametro":"Carga_Vminpu",          "Valor":0.95},
            {"Parametro":"Carga_Vmaxpu",          "Valor":1.05},
            {"Parametro":"Carga_status",          "Valor":"fixed"},
            {"Parametro":"Carga_conn",            "Valor":"wye"},
            {"Parametro":"Tipo_simulacao",        "Valor":TIPO_SIMULACAO},
            {"Parametro":"Nota","Valor":"Parametros identicos ao CN15"},
        ]).to_excel(writer, sheet_name="Metodologia", index=False)

    print(f"\n  Planilha comparativa salva em: {arq}")


# =============================================================================
# PROGRAMA PRINCIPAL
# =============================================================================

def main():
    print("\n" + "=" * 72)
    print("ANALISE COMPARATIVA - ALIMENTADORES RESIDENCIAIS DE CEILANDIA")
    print("task9-ceilandia-comparativo.py")
    print("=" * 72)
    print(f"\nReferencia: {CODIGO_CN15} (resultados hardcoded)")
    print(f"SIMULAR = {SIMULAR}")
    carregar_impedancias_segcon(GDB_PATH)

    # ETAPAS 1-2: Selecao
    candidatos, ssdmt_all_cn, untrmt_all_cn, unsemt_all_cn = listar_candidatos_ceilandia(
        GDB_PATH, codigo_excluir=CODIGO_CN15
    )
    if candidatos.empty:
        print("\nERRO: Nenhum candidato encontrado.")
        return

    alim_id, selecionado_info = selecionar_alimentador_comparativo(candidatos)

    # Diretorios
    pasta_saida_alim = os.path.join(PASTA_SAIDA, "resultados", alim_id)
    pasta_comp       = os.path.join(PASTA_SAIDA, "resultados", "comparacao_ceilandia")
    os.makedirs(pasta_saida_alim, exist_ok=True)
    os.makedirs(pasta_comp,       exist_ok=True)

    # Carregar dados do alimentador selecionado
    print(f"\nCarregando dados do {alim_id} da BDGD...")
    ssdmt_orig  = ssdmt_all_cn[ssdmt_all_cn["CTMT"].astype(str) == alim_id].copy()
    untrmt_orig = untrmt_all_cn[untrmt_all_cn["CTMT"].astype(str) == alim_id].copy()
    unsemt_orig = unsemt_all_cn[unsemt_all_cn["CTMT"].astype(str) == alim_id].copy()

    if ssdmt_orig.empty:
        print(f"  Recarregando {alim_id} com filtro direto...")
        ssdmt_orig  = gpd.read_file(GDB_PATH, layer="SSDMT",  where=f"CTMT = '{alim_id}'")
        untrmt_orig = gpd.read_file(GDB_PATH, layer="UNTRMT", where=f"CTMT = '{alim_id}'")
        unsemt_orig = gpd.read_file(GDB_PATH, layer="UNSEMT", where=f"CTMT = '{alim_id}'")

    if ssdmt_orig.empty:
        print(f"\nERRO: sem trechos para {alim_id}.")
        return

    print(f"  SSDMT: {len(ssdmt_orig)} | UNTRMT: {len(untrmt_orig)} | UNSEMT: {len(unsemt_orig)}")

    # ETAPA 3: Confirmar parametros
    print("\n" + "=" * 60)
    print("ETAPA 3 - PARAMETROS METODOLOGICOS (identicos ao CN15)")
    print("=" * 60)
    print(f"  Tensao MT: {TENSAO_MT_KV} kV | FP: {FP_BASE} | model=1 | Vminpu=0.95 | Vmaxpu=1.05")
    print(f"  status=fixed | conn=wye | Snapshot estatico | ChavesIndef=FECHADAS")

    # Comprimentos reais
    ssdmt, ssdmt_geo = calcular_comprimentos_geometria(ssdmt_orig)

    # ETAPA 4: Impedancias
    imp_stats, df_tip_cnd = auditar_impedancias(ssdmt)

    # Grafo e topologia
    grafo, elementos, diag_grafo = construir_grafo(ssdmt, unsemt_orig)
    pac_inicial, metodo_origem   = escolher_pac_inicial(ssdmt, grafo, GDB_PATH, pac_manual=None)
    print(f"\n  PAC inicial: {pac_inicial}  ({metodo_origem})")
    topo = analisar_topologia(grafo, pac_inicial, diag_grafo)

    # ETAPA 5: Diagnostico topologico
    imprimir_diagnostico_topologico(alim_id, grafo, diag_grafo, topo, pac_inicial, metodo_origem)

    barras_energizadas = set(topo["subgrafo"].nodes)
    linhas_energizadas = ssdmt[
        ssdmt["PAC_1"].apply(bus).isin(barras_energizadas) &
        ssdmt["PAC_2"].apply(bus).isin(barras_energizadas)
    ].copy()
    chaves_energizadas = unsemt_orig[
        unsemt_orig["PAC_1"].apply(bus).isin(barras_energizadas) &
        unsemt_orig["PAC_2"].apply(bus).isin(barras_energizadas)
    ].copy()
    trafos_energizados = untrmt_orig[
        untrmt_orig["PAC_1"].apply(bus).isin(barras_energizadas)
    ].copy()

    soma_pot_kva = trafos_energizados["POT_NOM"].apply(limpar_numero).sum()
    soma_pot_kva = soma_pot_kva if pd.notna(soma_pot_kva) else 0.0
    print(f"\n  Soma POT_NOM energizados: {soma_pot_kva:.0f} kVA")


    comp_total = topo["comprimento_total_km"]

    print("\n" + "=" * 60)
    print("=== VALIDAÇÃO PRÉ-SIMULAÇÃO CN12 ===")
    print("=" * 60)
    print(f"Barras energizadas: {topo['barras_alcancadas']} / {topo['barras_totais']}")
    print(f"Transformadores energizados: {len(trafos_energizados)} / {len(untrmt_orig)}")
    print(f"Potência energizada: aproximadamente {soma_pot_kva:.0f} kVA")
    print(f"Distância elétrica máxima: aproximadamente {topo['distancia_ponta_km']:.3f} km")
    print(f"Trechos usando fallback: {imp_stats.get('qtd_estimada', 0)}")
    print(f"R1 médio: aproximadamente {imp_stats['r1_medio']:.4f} ohm/km\n")
    
    # Abort conditions exactly as user requested
    if topo['barras_alcancadas'] < 1000 or len(trafos_energizados) < 100 or soma_pot_kva < 9000 or imp_stats.get('qtd_estimada', 0) > 10:
        print("FALHA NA VALIDAÇÃO! Retornando aos valores antigos. Execução interrompida.")
        import sys
        sys.exit(1)

    resumo_lista          = []
    tensoes_por_cenario   = {}
    classificacao_evidencia = "INCONCLUSIVA"
    conclusao_pesquisa      = "Sem resultados."
    limite_novo_pct         = None
    varredura_novo          = []

    if SIMULAR:
        # ETAPAS 6
        resumo_lista, tensoes_por_cenario = executar_cenarios(
            alim_id=alim_id, pac_inicial=pac_inicial, topo=topo,
            linhas_energizadas=linhas_energizadas, chaves_energizadas=chaves_energizadas,
            trafos_energizados=trafos_energizados, elementos=elementos,
            pasta_saida_alim=pasta_saida_alim, cenarios_lista=CENARIOS_REDE,
        )
        # ETAPA 7
        validar_vmin(alim_id, tensoes_por_cenario.get("Base 60%"), topo, ssdmt, untrmt_orig)
        # ETAPA 8
        imprimir_faixas_tensao(alim_id, resumo_lista)
        # ETAPA 9
        imprimir_tabelas_comparativas(alim_id, resumo_lista)
        # ETAPA 10
        gerar_graficos_comparativos(alim_id, pasta_comp, resumo_lista, tensoes_por_cenario)
        # ETAPA 11
        imprimir_tabela_estrutural(alim_id, imp_stats, topo, soma_pot_kva, resumo_lista)
        # ETAPA 12
        gerar_insights_tecnicos(alim_id, resumo_lista, topo, imp_stats, soma_pot_kva)
        # ETAPA 13
        result = questao_central_pesquisa(alim_id, resumo_lista)
        if result:
            classificacao_evidencia, conclusao_pesquisa = result

        # ETAPA 14
        print("\n" + "=" * 60)
        print("ETAPA 14 - REFERENCIA HISTORICA CN15")
        print("=" * 60)
        print(f"  CN15: Vmin = {CN15_RESULTADOS['Base 60%']['vmin']:.4f} p.u. a 60%")
        print(f"  -> Limite CN15 < 60% (ja esta abaixo de {LIMIAR_VMIN_PU:.2f} p.u.)")

        limite_novo_pct, varredura_novo = calcular_limite_carregamento(
            alim_id=alim_id, pac_inicial=pac_inicial, topo=topo,
            linhas_energizadas=linhas_energizadas, chaves_energizadas=chaves_energizadas,
            trafos_energizados=trafos_energizados, elementos=elementos,
            pasta_saida_alim=pasta_saida_alim,
        )

        # ETAPA 15
        gerar_relatorio_final(
            alim_id=alim_id, pasta_comp=pasta_comp,
            selecionado_info=selecionado_info,
            imp_stats=imp_stats, df_tip_cnd=df_tip_cnd,
            topo=topo, diag_grafo=diag_grafo, soma_pot_kva=soma_pot_kva,
            resumo_lista=resumo_lista,
            classificacao_evidencia=classificacao_evidencia,
            conclusao_pesquisa=conclusao_pesquisa,
            limite_novo_pct=limite_novo_pct,
            varredura_novo=varredura_novo,
        )
        exportar_planilha_comparativa(
            alim_id, pasta_comp, resumo_lista, df_tip_cnd, imp_stats, topo, soma_pot_kva
        )
    else:
        print("\n  [INFO] SIMULAR = False. Habilite para executar OpenDSS.")

    print("\n" + "=" * 72)
    print("PROCESSAMENTO CONCLUIDO")
    print(f"  Alimentador comparado: {alim_id}")
    print(f"  Resultados em: {pasta_comp}")
    print("=" * 72)


if __name__ == "__main__":
    main()
