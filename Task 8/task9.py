# =============================================================================
# ANÁLISE ELÉTRICA DE ALIMENTADORES – NEOENERGIA BRASÍLIA
# Alimentador Industrial: NW08 (SIA / Setor Industrial de Armazenagem)
#
# FASE 1 — CORREÇÕES APLICADAS NESTE ARQUIVO:
#   [A1] Comprimento real pela geometria (EPSG:31983)
#   [A2] Origem do alimentador sem uso de DIST
#   [A3] Diagnóstico topológico completo (ciclos, folhas, distâncias reais)
#   [A4] Análise de chaves (estado, planilha diagnóstica)
#
# Simulações OpenDSS desativadas até validação (SIMULAR = False).
# =============================================================================

import math
import os
import glob
import warnings

import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import py_dss_interface

# =============================================================================
# SEÇÃO DE CONFIGURAÇÕES
# =============================================================================

GDB_PATH = r"C:\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
PASTA_SAIDA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CODIGO_ALIMENTADOR_RESIDENCIAL = "CN15"

ALIMENTADORES_ESTUDO = {
    "NW08": {
        "codigo": "NW08",
        "perfil": "Industrial/comercial",
        "regiao": "SIA",
        "transformador_alvo": "FP8401",
        "descricao": (
            "Alimentador representativo de área predominantemente "
            "industrial e comercial do Setor de Indústria e Abastecimento."
        ),
    },
    "RESIDENCIAL_CEILANDIA": {
        "codigo": CODIGO_ALIMENTADOR_RESIDENCIAL,
        "perfil": "Residencial",
        "regiao": "Ceilândia",
        "transformador_alvo": None,  # Será selecionado automaticamente (~300kVA ou maior)
        "descricao": (
            "Alimentador representativo de área predominantemente "
            "residencial de Ceilândia."
        ),
    },
}

ALIMENTADORES_ATIVOS = [
    "NW08",
    "RESIDENCIAL_CEILANDIA",
]

# Variáveis globais base
TENSAO_MT_KV = 13.8
TENSAO_BT_KV = 0.38

# [A1] CRS métrico para o Distrito Federal (fuso 23S, SIRGAS 2000)
CRS_METRICO = 31983

# [A2] PAC da saída da subestação – informe aqui se conhecido.
# Com None o programa usa fallback topológico (PROVISÓRIO).
PAC_INICIAL_MANUAL = None

# [A7] Tipo de simulação – snapshot estático, sem referência de horário.
TIPO_SIMULACAO = "Snapshot estático"

FP_BASE = 0.92
FP_BAIXO = 0.85

# Cenários gerais de carregamento aparente dos transformadores.
# 0.60 = 60 % da potência nominal em kVA.
#CENARIOS_REDE = [
#    {"nome": "Base 60%",          "carregamento_rede": 0.60, "fp": FP_BASE},
#    {"nome": "Rede 80%",          "carregamento_rede": 0.80, "fp": FP_BASE},
#    {"nome": "Rede 100%",         "carregamento_rede": 1.00, "fp": FP_BASE},
#    {"nome": "Rede 120%",         "carregamento_rede": 1.20, "fp": FP_BASE},
#    {"nome": "Rede 160%",         "carregamento_rede": 1.60, "fp": FP_BASE},
#    {"nome": "Rede 160% FP baixo","carregamento_rede": 1.60, "fp": FP_BAIXO},
#]
#CENARIOS_REDE = [
#    {"nome": "Base 60%", "carregamento_rede": 0.60, "fp": 0.92},
#    {"nome": "Rede 80%", "carregamento_rede": 0.80, "fp": 0.92},
#    {"nome": "Rede 100%", "carregamento_rede": 1.00, "fp": 0.92},
#    {"nome": "Rede 120%", "carregamento_rede": 1.20, "fp": 0.92},
#    {"nome": "Rede 160%", "carregamento_rede": 1.60, "fp": 0.92},
#]
CENARIOS_REDE = [
    {"nome": "Rede 20%", "carregamento_rede": 0.20, "fp": 0.92},
    {"nome": "Rede 40%", "carregamento_rede": 0.40, "fp": 0.92},
    {"nome": "Base 60%", "carregamento_rede": 0.60, "fp": 0.92},
    {"nome": "Rede 80%", "carregamento_rede": 0.80, "fp": 0.92},
    {"nome": "Rede 100%", "carregamento_rede": 1.00, "fp": 0.92},
    {"nome": "Rede 120%", "carregamento_rede": 1.20, "fp": 0.92},
]

# Ensaio localizado no transformador-alvo (FP8401 – 300 kVA).
CARREGAMENTOS_TRAFO_ALVO = [
    0.50,
    0.80,
    1.00,
    1.20,
    1.50,
]

# Impedâncias aproximadas quando a BDGD não tiver R1/X1.
USAR_IMPEDANCIA_CONSERVADORA = True
TRAFO_PERCENT_R = 1.2
TRAFO_XHL     = 4.5

# Limites de tensão para classificação visual.
LIMITES_TENSAO = {
    "critico":  0.90,
    "atencao":  0.93,
    "alerta":   0.97,
}

# [A4] Hipótese de modelagem: chaves com estado indefinido são assumidas FECHADAS.
# Altere para False para removê-las do grafo.
ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS = True

# Controla se as simulações OpenDSS serão executadas.
# Mantenha False até validar topologia e comprimentos.
#SIMULAR = False
SIMULAR = True

# -----------------------------------------------------------------------
# Cenário de calibração por demanda-alvo
# -----------------------------------------------------------------------
# Informe a demanda total em kVA que deseja impor ao alimentador.
# O fator de carregamento será calculado automaticamente:
#   fator = DEMANDA_TOTAL_ALVO_KVA / soma_POT_NOM_energizada
# Com None, o cenário de calibração é omitido.
DEMANDA_TOTAL_ALVO_KVA = None   # ex.: 6000 para aproximar a demanda real

# =============================================================================
# FUNÇÕES AUXILIARES BÁSICAS
# =============================================================================


def bus(valor):
    """Normaliza o nome de uma barra para uso no grafo e no OpenDSS."""
    if pd.isna(valor):
        return ""
    return (
        str(valor)
        .strip()
        .upper()
        .replace("KV", "")
        .replace(" ", "")
    )


def clean_id(valor):
    """Remove caracteres inválidos para nomes de elementos OpenDSS."""
    return (
        str(valor)
        .strip()
        .replace(" ", "_")
        .replace(".", "")
        .replace("-", "")
        .replace("/", "_")
        .replace("\\", "_")
    )


def limpar_numero(valor):
    """Converte valor para float, aceitando vírgula decimal e sufixo 'kv'."""
    try:
        texto = str(valor).lower().replace("kv", "").replace(",", ".").strip()
        return float(texto)
    except (TypeError, ValueError):
        return np.nan


def obter_coluna_existente(df, candidatos):
    """Retorna o nome real da primeira coluna que bater (case-insensitive)."""
    mapa = {str(c).lower(): c for c in df.columns}
    for candidato in candidatos:
        if candidato.lower() in mapa:
            return mapa[candidato.lower()]
    return None


def obter_numero_linha(row, candidatos):
    """Lê o primeiro valor numérico positivo entre as colunas candidatas da row."""
    mapa = {str(c).lower(): c for c in row.index}
    for candidato in candidatos:
        real = mapa.get(candidato.lower())
        if real is None:
            continue
        valor = limpar_numero(row[real])
        if pd.notna(valor) and valor > 0:
            return valor
    return None


# =============================================================================
# [A1] COMPRIMENTO REAL PELA GEOMETRIA
# =============================================================================


def comprimento_km_linha(row):
    """
    [A1] Retorna o comprimento em km do trecho.

    Prioridade:
    1. COMPRIMENTO_REAL_KM  — calculado da geometria em EPSG:31983
    2. Shape_Length          — fallback (já em metros se CRS métrico)
    3. 0.00001 km            — mínimo absoluto (nunca zero)
    """
    # 1. Geometria métrica (coluna calculada após to_crs)
    valor = limpar_numero(row.get("COMPRIMENTO_REAL_KM", np.nan))
    if pd.notna(valor) and valor > 0:
        return max(valor, 0.00001)

    # 2. Shape_Length (metros)
    valor_shape = limpar_numero(row.get("Shape_Length", np.nan))
    if pd.notna(valor_shape) and valor_shape > 0:
        return max(valor_shape / 1000.0, 0.00001)

    # 3. Mínimo absoluto
    return 0.00001


def calcular_comprimentos_geometria(ssdmt_original):
    """
    [A1] Reprojecta a camada SSDMT para CRS_METRICO e calcula comprimentos reais.

    Retorna (ssdmt_metrico, ssdmt_geo):
      - ssdmt_metrico: GeoDataFrame em EPSG:31983 com coluna COMPRIMENTO_REAL_KM
      - ssdmt_geo:     GeoDataFrame em EPSG:4326 para mapas (preserva geometria original)
    """
    print("\n--- [A1] Comprimento real pela geometria ---")
    print(f"CRS original: {ssdmt_original.crs}")

    ssdmt = ssdmt_original.copy()

    # Converter para CRS métrico
    ssdmt = ssdmt.to_crs(epsg=CRS_METRICO)
    print(f"CRS métrico:  {ssdmt.crs}")

    # Detectar geometrias nulas/vazias
    geom_vazia = ssdmt.geometry.is_empty | ssdmt.geometry.isna()
    n_vazia = geom_vazia.sum()
    if n_vazia > 0:
        print(f"AVISO: {n_vazia} trecho(s) com geometria vazia – receberão comprimento mínimo.")

    # Calcular comprimento
    ssdmt["COMPRIMENTO_REAL_KM"] = np.where(
        geom_vazia,
        0.00001,
        ssdmt.geometry.length / 1000.0,
    )

    # Estatísticas
    desc = ssdmt["COMPRIMENTO_REAL_KM"].describe()
    print("\nEstatísticas de COMPRIMENTO_REAL_KM (km):")
    print(desc.to_string())
    print(f"\nComprimento total do alimentador: {ssdmt['COMPRIMENTO_REAL_KM'].sum():.3f} km")

    n_minimo = (ssdmt["COMPRIMENTO_REAL_KM"] <= 0.00001).sum()
    print(f"Trechos com comprimento no mínimo absoluto (<= 0.00001 km): {n_minimo}")
    print(f"Trechos com geometria vazia: {n_vazia}")

    # Versão geográfica para mapas (EPSG:4326)
    try:
        ssdmt_geo = ssdmt.to_crs(epsg=4326)
    except Exception:
        ssdmt_geo = ssdmt_original.copy()

    return ssdmt, ssdmt_geo


def diagnostico_comprimentos_df(ssdmt):
    """Retorna DataFrame resumo para exportar na aba Diag_Comprimentos."""
    linhas = []
    for _, row in ssdmt.iterrows():
        comp_real = limpar_numero(row.get("COMPRIMENTO_REAL_KM", np.nan))
        shape_len = limpar_numero(row.get("Shape_Length", np.nan))
        geom_vazia = row.geometry is None or row.geometry.is_empty
        fonte = "geometria" if (pd.notna(comp_real) and comp_real > 0) \
                else ("Shape_Length" if (pd.notna(shape_len) and shape_len > 0)
                      else "mínimo_absoluto")
        linhas.append({
            "COD_ID":               row.get("COD_ID", ""),
            "PAC_1":                row.get("PAC_1", ""),
            "PAC_2":                row.get("PAC_2", ""),
            "COMPRIMENTO_REAL_KM":  comp_real,
            "Shape_Length_m":       shape_len,
            "Geometria_Vazia":      geom_vazia,
            "Fonte_Comprimento":    fonte,
        })
    return pd.DataFrame(linhas)


# =============================================================================
# IMPEDÂNCIAS
# =============================================================================


IMPEDANCIAS_SEGCON = {}


def carregar_impedancias_segcon(gdb_path):
    """Carrega R1/X1 oficiais por TIP_CND a partir da camada SEGCON."""
    global IMPEDANCIAS_SEGCON

    segcon = gpd.read_file(gdb_path, layer="SEGCON")
    colunas = {str(col).upper(): col for col in segcon.columns}
    obrigatorias = ["COD_ID", "R1", "X1"]
    ausentes = [col for col in obrigatorias if col not in colunas]
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


def diagnosticar_cobertura_segcon(ssdmt):
    """Confere a cobertura da SEGCON e resume os parametros aplicados."""
    tipos = ssdmt["TIP_CND"].astype(str).str.strip()
    cobertos = tipos.isin(IMPEDANCIAS_SEGCON)
    faltantes = sorted(tipos[~cobertos].unique())

    print("\n--- Diagnostico de impedancias SEGCON ---")
    print(f"Trechos cobertos pela SEGCON: {int(cobertos.sum())}/{len(ssdmt)}")
    if faltantes:
        print(f"TIP_CND sem correspondencia: {faltantes}")

    if cobertos.any():
        comprimentos = ssdmt.loc[cobertos, "COMPRIMENTO_REAL_KM"].astype(float)
        r1 = tipos.loc[cobertos].map(lambda codigo: IMPEDANCIAS_SEGCON[codigo][0])
        x1 = tipos.loc[cobertos].map(lambda codigo: IMPEDANCIAS_SEGCON[codigo][1])
        peso_total = comprimentos.sum()
        print(
            "R1 medio ponderado pelo comprimento: "
            f"{(r1 * comprimentos).sum() / peso_total:.4f} ohm/km"
        )
        print(
            "X1 medio ponderado pelo comprimento: "
            f"{(x1 * comprimentos).sum() / peso_total:.4f} ohm/km"
        )

    if faltantes:
        warnings.warn(
            "Ha trechos sem R1/X1 na SEGCON; somente eles usarao fallback."
        )


IMPEDANCIAS_TIPICAS = {
    '94_A4_3_1': (0.2920, 0.3510, 'ACSR 4/0 AWG'),
    '68_A4_3_1': (0.5260, 0.3600, 'ACSR 2/0 AWG'),
    '7_A4_3_1':  (0.8220, 0.3980, 'ACSR #4 AWG'),
    '70_A4_3_1': (0.4920, 0.3590, 'ACSR 1/0 AWG'),
    '47_A4_1_1': (0.7690, 0.4020, 'Fase-Neutro Menor'),
    '89_A4_1_1': (0.3560, 0.3600, 'Fase-Neutro Maior'),
    '84_A4_3_1': (0.3980, 0.3620, 'ACSR 3/0 AWG'),
}

def obter_impedancia_linha(row, length_km):
    """
    [A12] Tenta usar impedâncias reais da BDGD.
    Registra se usou valor real ou estimado.
    """
    candidatos_r1 = [
        "R1", "R1_OHM_KM", "R1_OHMKM", "R1_OHM_POR_KM",
        "RESISTENCIA", "RESIST", "R_OHM_KM", "R_OHMKM",
    ]
    candidatos_x1 = [
        "X1", "X1_OHM_KM", "X1_OHMKM", "X1_OHM_POR_KM",
        "REATANCIA", "REAT", "X_OHM_KM", "X_OHMKM",
    ]

    r1 = obter_numero_linha(row, candidatos_r1)
    x1 = obter_numero_linha(row, candidatos_x1)

    if r1 is not None and x1 is not None:
        return r1, x1, "real_bdgd"
        
    # Tenta usar lookup por tipo de cabo se disponível na BDGD
    tip_cnd = str(row.get("TIP_CND", "")).strip()
    if tip_cnd in IMPEDANCIAS_SEGCON:
        r1_segcon, x1_segcon = IMPEDANCIAS_SEGCON[tip_cnd]
        return r1_segcon, x1_segcon, "segcon_bdgd"

    if tip_cnd in IMPEDANCIAS_TIPICAS:
        r1_tipico, x1_tipico, _ = IMPEDANCIAS_TIPICAS[tip_cnd]
        return r1_tipico, x1_tipico, f"estimada_cabo_{tip_cnd}"

    if USAR_IMPEDANCIA_CONSERVADORA:
        if length_km < 0.1:
            return 1.20, 0.70, "estimada_conservadora"
        if length_km < 0.5:
            return 0.95, 0.55, "estimada_conservadora"
        return 0.75, 0.45, "estimada_conservadora"

    if length_km < 0.1:
        return 0.70, 0.40, "estimada_simples"
    if length_km < 0.5:
        return 0.50, 0.35, "estimada_simples"
    return 0.30, 0.30, "estimada_simples"


# =============================================================================
# [A4] ESTADO DAS CHAVES
# =============================================================================

# Conjuntos de valores que identificam claramente abertura ou fechamento.
_VALORES_ABERTA  = {"AB", "ABERTA", "ABERTO", "OPEN", "OFF", "DESLIGADA",
                    "DESLIGADO", "A", "0"}
_VALORES_FECHADA = {"FE", "FECHADA", "FECHADO", "CLOSED", "ON", "LIGADA",
                    "LIGADO", "F", "1"}

# Campos candidatos para estado operacional da chave (em ordem de preferência).
_CAMPOS_ESTADO_CHAVE = [
    "P_N_OPE", "ESTADO", "STATUS", "SITCONT", "POS",
    "EST_OPER", "SITUACAO", "SITUAÇÃO",
]


def interpretar_estado_chave(valor_bruto):
    """
    Interpreta o valor de um campo de estado de chave.

    Retorna: "aberta" | "fechada" | "indefinido"
    """
    if pd.isna(valor_bruto):
        return "indefinido"
    texto = str(valor_bruto).strip().upper()
    if texto in _VALORES_ABERTA:
        return "aberta"
    if texto in _VALORES_FECHADA:
        return "fechada"
    # Tenta interpretar como numérico (0 = aberta, 1 = fechada)
    try:
        num = float(texto)
        if num == 0.0:
            return "aberta"
        if num == 1.0:
            return "fechada"
    except ValueError:
        pass
    return "indefinido"


def chave_esta_fechada(row):
    """
    [A4] Determina se a chave está fechada.

    Retorna: (bool_fechada, campo_utilizado, valor_original, interpretacao)
    """
    for campo in _CAMPOS_ESTADO_CHAVE:
        if campo not in row.index:
            continue
        valor_bruto = row[campo]
        interp = interpretar_estado_chave(valor_bruto)
        if interp == "aberta":
            return False, campo, valor_bruto, interp
        if interp == "fechada":
            return True, campo, valor_bruto, interp
        # indefinido: continua tentando próximo campo

    # Nenhum campo reconheceu o estado
    # Aplica hipótese de modelagem
    fechada = ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS
    return fechada, None, None, "indefinido"


def diagnostico_chaves(unsemt):
    """
    [A4] Gera diagnóstico completo das chaves.

    Imprime:
      - colunas disponíveis na UNSEMT
      - value_counts dos possíveis campos de estado
      - resumo de aberta/fechada/indefinido

    Retorna DataFrame com planilha diagnóstica.
    """
    print("\n--- [A4] Diagnóstico das chaves ---")
    print("Colunas disponíveis na UNSEMT:")
    print(list(unsemt.columns))

    # Campos de estado realmente presentes
    campos_presentes = [c for c in _CAMPOS_ESTADO_CHAVE if c in unsemt.columns]
    print(f"\nCampos de estado encontrados: {campos_presentes}")

    for campo in campos_presentes:
        print(f"\n  {campo} — value_counts:")
        print(unsemt[campo].value_counts(dropna=False).to_string())

    # Montar planilha diagnóstica
    linhas = []
    for _, row in unsemt.iterrows():
        fechada, campo_usado, valor_orig, interp = chave_esta_fechada(row)
        linhas.append({
            "COD_ID":         row.get("COD_ID", ""),
            "PAC_1":          row.get("PAC_1", ""),
            "PAC_2":          row.get("PAC_2", ""),
            "Campo_Utilizado": campo_usado,
            "Valor_Original":  valor_orig,
            "Interpretacao":   interp,
            "Estado_Final":    "fechada" if fechada else "aberta",
            "Hipotese_Modelo": (
                f"ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS={ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS}"
                if interp == "indefinido" else ""
            ),
        })

    df_diag = pd.DataFrame(linhas)

    contagem = df_diag["Interpretacao"].value_counts()
    print("\nResumo das chaves:")
    print(f"  Claramente fechadas:  {contagem.get('fechada', 0)}")
    print(f"  Claramente abertas:   {contagem.get('aberta', 0)}")
    print(f"  Estado indefinido:    {contagem.get('indefinido', 0)}")
    if df_diag["Interpretacao"].eq("indefinido").any():
        print(
            f"  → Hipótese: chaves indefinidas assumidas "
            f"{'FECHADAS' if ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS else 'ABERTAS'} "
            "(configurável em ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS)"
        )

    return df_diag


# =============================================================================
# [A3] GRAFO ELÉTRICO
# =============================================================================


def construir_grafo(ssdmt, unsemt):
    """
    [A3] Constrói o grafo elétrico a partir de SSDMT e UNSEMT.

    Usa comprimento real (COMPRIMENTO_REAL_KM) como peso das arestas SSDMT.
    Chaves fechadas recebem peso muito pequeno (0.00001 km).

    Retorna: (grafo, elementos, diagnostico)
    """
    grafo = nx.Graph()
    elementos = {}
    chaves_abertas    = 0
    chaves_fechadas   = 0
    chaves_indefinido = 0

    # --- Linhas SSDMT ---
    for _, row in ssdmt.iterrows():
        b1 = bus(row.get("PAC_1"))
        b2 = bus(row.get("PAC_2"))
        if not b1 or not b2 or b1 == b2:
            continue

        codigo     = clean_id(row.get("COD_ID"))
        comprimento = comprimento_km_linha(row)

        grafo.add_edge(
            b1, b2,
            weight=comprimento,
            tipo="linha",
            codigo=codigo,
        )
        elementos[f"LINE.L_{codigo}".upper()] = {
            "b1": b1,
            "b2": b2,
            "comprimento_km": comprimento,
            "tipo": "linha",
        }

    # --- Chaves UNSEMT ---
    for _, row in unsemt.iterrows():
        b1 = bus(row.get("PAC_1"))
        b2 = bus(row.get("PAC_2"))
        if not b1 or not b2 or b1 == b2:
            continue

        fechada, campo_usado, valor_orig, interp = chave_esta_fechada(row)

        if interp == "aberta":
            chaves_abertas += 1
        elif interp == "fechada":
            chaves_fechadas += 1
        else:
            chaves_indefinido += 1

        if not fechada:
            # Se interp == "aberta", já foi contado acima.
            # Se interp == "indefinido" e ASSUMIR=False, a chave fica aberta
            # (já foi contada em chaves_indefinido; não duplicar em chaves_abertas).
            continue

        codigo = clean_id(row.get("COD_ID"))
        # Peso muito pequeno para chaves (praticamente sem comprimento elétrico)
        grafo.add_edge(
            b1, b2,
            weight=0.00001,
            tipo="chave",
            codigo=codigo,
        )
        elementos[f"LINE.SW_{codigo}".upper()] = {
            "b1": b1,
            "b2": b2,
            "comprimento_km": 0.00001,
            "tipo": "chave",
        }

    n_nos     = grafo.number_of_nodes()
    n_arestas = grafo.number_of_edges()
    n_comp    = nx.number_connected_components(grafo) if n_nos > 0 else 0

    # Ciclos: fórmula de Euler (>=0 indica malhas)
    ciclos_euler = max(0, n_arestas - n_nos + n_comp)

    # Ciclos explícitos (pode ser lento em grafos grandes)
    try:
        ciclos_nx = len(nx.cycle_basis(grafo))
    except Exception:
        ciclos_nx = -1  # não foi possível calcular

    folhas = sum(1 for n in grafo.nodes if grafo.degree(n) == 1)

    diagnostico = {
        "chaves_abertas":     chaves_abertas,
        "chaves_fechadas":    chaves_fechadas,
        "chaves_indefinido":  chaves_indefinido,
        "nos":                n_nos,
        "arestas":            n_arestas,
        "componentes":        n_comp,
        "ciclos_euler":       ciclos_euler,
        "ciclos_nx":          ciclos_nx,
        "nos_folha_grau1":    folhas,
    }

    return grafo, elementos, diagnostico


# =============================================================================
# [A2] ORIGEM DO ALIMENTADOR
# =============================================================================


def _tentar_origem_ctmt(grafo, gdb_path, alim_id):
    """
    [A2] Tenta obter o PAC de origem lendo a camada CTMT da GDB.

    Nunca inventa nome de coluna. Apenas inspeciona as existentes.
    Retorna (pac, metodo) ou (None, None).
    """
    try:
        ctmt = gpd.read_file(
            gdb_path,
            layer="CTMT",
            where=f"COD_ID = '{alim_id}'",
        )
        if ctmt.empty:
            print(f"  [CTMT] Nenhum registro encontrado para COD_ID = '{alim_id}'")
            return None, None

        print(f"  [CTMT] Colunas disponíveis: {list(ctmt.columns)}")
        print(f"  [CTMT] Registro(s) encontrado(s):")
        print(ctmt.to_string())

        # Busca colunas cujos nomes se parecem com PAC de conexão
        candidatos_pac = [
            "PAC", "PAC_INI", "PAC_1", "PN_CON", "BARRA",
            "BUS", "PNT_CON", "COD_ID",
        ]
        col_pac = obter_coluna_existente(ctmt, candidatos_pac)

        if col_pac is None:
            print(
                "  [CTMT] Nenhuma coluna de PAC/conexão encontrada. "
                "Usando fallback topológico."
            )
            return None, None

        valor = ctmt.iloc[0][col_pac]
        pac_candidato = bus(valor)

        if not pac_candidato:
            print(f"  [CTMT] Coluna '{col_pac}' está vazia.")
            return None, None

        if pac_candidato not in grafo:
            print(
                f"  [CTMT] PAC '{pac_candidato}' (coluna '{col_pac}') "
                "não existe no grafo. Usando fallback topológico."
            )
            return None, None

        print(f"  [CTMT] PAC de origem obtido da CTMT: {pac_candidato} (coluna '{col_pac}')")
        return pac_candidato, f"CTMT coluna '{col_pac}'"

    except Exception as erro:
        print(f"  [CTMT] Não foi possível ler a camada CTMT: {erro}")
        return None, None


def _fallback_topologico(grafo):
    """
    [A2] Método provisório: extremidade topológica do maior componente conectado.

    Escolhe a extremidade de grau 1 que fica mais distante da outra extremidade
    (diâmetro do grafo), priorizando o nó de menor grau.
    """
    print(
        "\n  [ORIGEM] Método provisório: extremidade topológica do maior "
        "componente conectado"
    )

    maior_componente = max(nx.connected_components(grafo), key=len)
    subgrafo = grafo.subgraph(maior_componente).copy()

    # Folhas (grau 1) são candidatas preferenciais
    folhas = [n for n in subgrafo.nodes if subgrafo.degree(n) == 1]
    print(f"  [ORIGEM] Folhas (grau 1) no maior componente: {len(folhas)}")

    inicio_arb = next(iter(subgrafo.nodes))

    dist_1 = nx.single_source_dijkstra_path_length(
        subgrafo, inicio_arb, weight="weight"
    )
    ponta_1 = max(dist_1, key=dist_1.get)

    dist_2 = nx.single_source_dijkstra_path_length(
        subgrafo, ponta_1, weight="weight"
    )
    ponta_2 = max(dist_2, key=dist_2.get)

    # Prefere a que tem menor grau (mais típico de entrada de subestação)
    if subgrafo.degree(ponta_1) <= subgrafo.degree(ponta_2):
        origem = ponta_1
    else:
        origem = ponta_2

    return origem, "provisório – extremidade topológica do maior componente"


def escolher_pac_inicial(ssdmt, grafo, gdb_path, pac_manual=None):
    """
    [A2] Escolhe o PAC inicial do alimentador.

    Prioridade:
    1. PAC_INICIAL_MANUAL (quando informado pelo usuário)
    2. Leitura da camada CTMT da GDB
    3. Fallback topológico (marcado como PROVISÓRIO)

    DIST e UNI_TR_AT NÃO são usados como critério de origem.
    """
    if grafo.number_of_nodes() == 0:
        raise ValueError("O grafo do alimentador está vazio.")

    # -----------------------------------------------------------------------
    # 1. PAC manual
    # -----------------------------------------------------------------------
    if pac_manual:
        candidato = bus(pac_manual)
        if candidato not in grafo:
            raise ValueError(
                f"O PAC manual '{candidato}' não existe no grafo. "
                "Verifique o valor de PAC_INICIAL_MANUAL."
            )
        print(f"\n  [ORIGEM] PAC manual informado: {candidato}")
        return candidato, "manual (PAC_INICIAL_MANUAL)"

    print("\n--- [A2] Escolha da origem do alimentador ---")

    # -----------------------------------------------------------------------
    # 2. Leitura da CTMT
    # -----------------------------------------------------------------------
    pac_ctmt, metodo_ctmt = _tentar_origem_ctmt(grafo, gdb_path, ssdmt.iloc[0].get("CTMT", ""))
    if pac_ctmt is not None:
        return pac_ctmt, metodo_ctmt

    # -----------------------------------------------------------------------
    # 3. Fallback topológico
    # -----------------------------------------------------------------------
    origem, metodo = _fallback_topologico(grafo)
    print(
        f"\n  AVISO: A origem '{origem}' é PROVISÓRIA. "
        "Informe PAC_INICIAL_MANUAL quando o PAC correto for validado."
    )
    return origem, metodo


# =============================================================================
# [A3] ANÁLISE TOPOLÓGICA
# =============================================================================


def analisar_topologia(grafo, pac_inicial, diag_grafo):
    """
    [A3] Realiza análise topológica completa a partir do PAC inicial.

    Retorna dicionário com métricas e caminho até a ponta elétrica.
    """
    if pac_inicial not in grafo:
        raise ValueError(f"PAC inicial '{pac_inicial}' ausente no grafo.")

    componente = nx.node_connected_component(grafo, pac_inicial)
    subgrafo   = grafo.subgraph(componente).copy()

    distancias = nx.single_source_dijkstra_path_length(
        subgrafo, pac_inicial, weight="weight"
    )

    ponta = max(distancias, key=distancias.get)
    dist_ponta = distancias[ponta]

    # Caminho entre origem e ponta
    try:
        caminho = nx.shortest_path(
            subgrafo, pac_inicial, ponta, weight="weight"
        )
    except nx.NetworkXNoPath:
        caminho = [pac_inicial, ponta]

    # Comprimento total das arestas do subgrafo
    comprimento_total = sum(
        d.get("weight", 0)
        for _, _, d in subgrafo.edges(data=True)
    )

    barras_alcancadas = len(componente)
    barras_totais     = grafo.number_of_nodes()
    pct_alcancadas    = 100.0 * barras_alcancadas / barras_totais if barras_totais > 0 else 0.0

    print("\n============================================================")
    print(f"DIAGNÓSTICO TOPOLÓGICO DO GRAFO")
    print("============================================================")
    print(f"  Nós totais no grafo:           {diag_grafo['nos']}")
    print(f"  Arestas totais no grafo:       {diag_grafo['arestas']}")
    print(f"  Componentes conectados:        {diag_grafo['componentes']}")
    print(f"  Ciclos (fórmula Euler):        {diag_grafo['ciclos_euler']}")
    print(f"  Ciclos (nx.cycle_basis):       {diag_grafo['ciclos_nx']}")
    print(f"  Folhas (grau 1):               {diag_grafo['nos_folha_grau1']}")
    if diag_grafo["ciclos_euler"] > 0:
        print(
            f"\n  AVISO: {diag_grafo['ciclos_euler']} ciclo(s) detectado(s). "
            "Uma rede radial pura teria 0 ciclos.\n"
            "  Possíveis causas: chaves indefinidas assumidas fechadas, "
            "trechos paralelos na BDGD ou malhas reais."
        )
    print(f"\n  Barras energizadas (alcançadas): {barras_alcancadas}")
    print(f"  Barras totais no grafo:          {barras_totais}")
    print(f"  % de barras alcançadas:          {pct_alcancadas:.1f}%")
    print(f"\n  Comprimento total dos trechos:   {comprimento_total:.3f} km")
    print(f"  Distância elétrica até a ponta:  {dist_ponta:.3f} km")
    print(f"  Ponta elétrica:                  {ponta}")
    print(f"\n  Chaves abertas identificadas:    {diag_grafo['chaves_abertas']}")
    print(f"  Chaves fechadas identificadas:   {diag_grafo['chaves_fechadas']}")
    print(f"  Chaves com estado indefinido:    {diag_grafo['chaves_indefinido']}")
    print(
        f"  -> Hipótese modelagem indefinidas: "
        f"{'FECHADAS' if ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS else 'ABERTAS'}"
    )
    print(f"\n  Comprimento do caminho (origem -> ponta): {len(caminho)} nós")

    return {
        "subgrafo":          subgrafo,
        "distancias":        distancias,
        "ponta":             ponta,
        "distancia_ponta_km": dist_ponta,
        "barras_alcancadas": barras_alcancadas,
        "barras_totais":     barras_totais,
        "pct_alcancadas":    pct_alcancadas,
        "arestas_alcancadas": subgrafo.number_of_edges(),
        "comprimento_total_km": comprimento_total,
        "caminho_origem_ponta": caminho,
    }


def diagnostico_topologia_df(diag_grafo, topo, pac_inicial, metodo_origem):
    """Retorna DataFrame de diagnóstico topológico para exportação."""
    dados = {
        "Metrica": [
            "PAC_inicial",
            "Metodo_origem",
            "Nos_totais",
            "Arestas_totais",
            "Componentes_conectados",
            "Ciclos_Euler",
            "Ciclos_nx_cycle_basis",
            "Nos_folha_grau1",
            "Barras_alcancadas",
            "Pct_alcancadas",
            "Comprimento_total_km",
            "Distancia_ponta_km",
            "Ponta_eletrica",
            "Chaves_abertas",
            "Chaves_fechadas",
            "Chaves_indefinido",
            "Hipotese_chaves_indefinidas",
        ],
        "Valor": [
            pac_inicial,
            metodo_origem,
            diag_grafo["nos"],
            diag_grafo["arestas"],
            diag_grafo["componentes"],
            diag_grafo["ciclos_euler"],
            diag_grafo["ciclos_nx"],
            diag_grafo["nos_folha_grau1"],
            topo["barras_alcancadas"],
            f"{topo['pct_alcancadas']:.1f}%",
            f"{topo['comprimento_total_km']:.3f}",
            f"{topo['distancia_ponta_km']:.3f}",
            topo["ponta"],
            diag_grafo["chaves_abertas"],
            diag_grafo["chaves_fechadas"],
            diag_grafo["chaves_indefinido"],
            "FECHADAS" if ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS else "ABERTAS",
        ],
    }
    return pd.DataFrame(dados)


# =============================================================================
# TRANSFORMADOR-ALVO
# =============================================================================


def selecionar_transformador_alvo(untrmt, barras_energizadas, codigo_manual=None):
    """Seleciona o transformador para análise específica."""
    dados = untrmt.copy()
    dados["BUS_MT"]      = dados["PAC_1"].apply(bus)
    dados["POT_NOM_NUM"] = dados["POT_NOM"].apply(limpar_numero)

    dados = dados[
        dados["BUS_MT"].isin(barras_energizadas)
        & dados["POT_NOM_NUM"].notna()
        & (dados["POT_NOM_NUM"] > 0)
    ].copy()

    if dados.empty:
        return None

    if codigo_manual:
        codigo_limpo = str(codigo_manual).strip()
        alvo = dados[dados["COD_ID"].astype(str).str.strip() == codigo_limpo]
        if alvo.empty:
            raise ValueError(
                f"Transformador manual '{codigo_limpo}' não encontrado "
                "ou fora do componente energizado."
            )
        return alvo.iloc[0]

    return dados.sort_values("POT_NOM_NUM", ascending=False).iloc[0]


# =============================================================================
# LEITURA DOS CSVs DO OPENDSS
# =============================================================================


def encontrar_exportacao(pasta, alimentador, sufixo):
    """Localiza o CSV mais recente exportado pelo OpenDSS para este alimentador."""
    esperado = os.path.join(pasta, f"{alimentador}_EXP_{sufixo}.CSV")
    if os.path.exists(esperado):
        return esperado

    padroes = [
        os.path.join(pasta, f"*{alimentador}*EXP_{sufixo}*.CSV"),
        os.path.join(pasta, f"*EXP_{sufixo}*.CSV"),
    ]
    candidatos = []
    for padrao in padroes:
        candidatos.extend(glob.glob(padrao))

    if not candidatos:
        return None
    return max(candidatos, key=os.path.getmtime)


def coluna_bus(df):
    return obter_coluna_existente(df, ["Bus", "BusName", "Bus Name", "BUS"])


def coluna_elemento(df):
    return obter_coluna_existente(df, ["Element", "ELEMENT", "ElementName"])


def normalizar_elemento(valor):
    return str(valor).strip().upper()


def colunas_fases_por_prefixo(df, prefixo):
    saida = []
    for c in df.columns:
        nome = str(c).strip().upper()
        if nome.startswith(prefixo.upper()):
            numero = pd.to_numeric(df[c], errors="coerce")
            if numero.notna().any():
                saida.append(c)
    return saida


def analisar_tensoes(df_v, distancias):
    """
    [A8] Processa CSV de tensões do OpenDSS.

    Retorna DataFrame com: Barra, Distancia_km, V_fase1_pu, V_fase2_pu,
    V_fase3_pu, Tensao_Media_pu, Tensao_Min_Fases_pu.
    """
    df = df_v.copy()
    df.columns = df.columns.str.strip()

    col_bus = coluna_bus(df)
    if col_bus is None:
        raise ValueError("Exportação de tensões sem coluna de barra.")

    col_base = obter_coluna_existente(df, ["BasekV", "Base kV", "BASEKV"])
    if col_base is not None:
        base_num = pd.to_numeric(df[col_base], errors="coerce")
        df = df[base_num.between(7.0, 14.5)].copy()

    mapa_pu = {}
    for nome_alvo in ["pu1", "pu2", "pu3"]:
        col = obter_coluna_existente(df, [nome_alvo])
        if col is not None:
            mapa_pu[nome_alvo] = col

    if not mapa_pu:
        raise ValueError("Exportação de tensões sem colunas pu1/pu2/pu3.")

    for nome_alvo, col in mapa_pu.items():
        df[col] = pd.to_numeric(df[col], errors="coerce").replace(0, np.nan)

    df["Barra"] = df[col_bus].apply(bus)

    # Colunas padronizadas
    df["V_fase1_pu"] = df[mapa_pu["pu1"]] if "pu1" in mapa_pu else np.nan
    df["V_fase2_pu"] = df[mapa_pu["pu2"]] if "pu2" in mapa_pu else np.nan
    df["V_fase3_pu"] = df[mapa_pu["pu3"]] if "pu3" in mapa_pu else np.nan

    fases_cols = [c for c in ["V_fase1_pu", "V_fase2_pu", "V_fase3_pu"]
                  if c in df.columns]

    df["Tensao_Media_pu"]    = df[fases_cols].mean(axis=1)
    df["Tensao_Min_Fases_pu"] = df[fases_cols].min(axis=1)

    df["Distancia_km"] = df["Barra"].map(distancias)
    df = df[df["Distancia_km"].notna()].copy()
    df = df.sort_values("Distancia_km").reset_index(drop=True)

    # Alias para compatibilidade interna
    df["Tensao_pu"] = df["Tensao_Media_pu"]

    return df[[
        "Barra", "Distancia_km",
        "V_fase1_pu", "V_fase2_pu", "V_fase3_pu",
        "Tensao_Media_pu", "Tensao_Min_Fases_pu", "Tensao_pu",
    ]]


def analisar_correntes(df_i, elementos, distancias):
    """
    [A9] Processa CSV de correntes do OpenDSS.

    Retorna DataFrame com: Elemento, Barra_orig, Barra_dest,
    Distancia_km, I1, I2, I3, Corrente_Max_A.
    """
    df = df_i.copy()
    df.columns = df.columns.str.strip()

    col_elem = coluna_elemento(df)
    if col_elem is None:
        raise ValueError("Exportação de correntes sem coluna Element.")

    df["Elemento"] = df[col_elem].apply(normalizar_elemento)
    # Somente linhas de MT (exclui transformadores para não misturar)
    df = df[df["Elemento"].str.startswith("LINE.", na=False)].copy()

    cols_i = colunas_fases_por_prefixo(df, "I")
    if not cols_i:
        raise ValueError("Nenhuma coluna de corrente identificada.")

    for c in cols_i:
        df[c] = pd.to_numeric(df[c], errors="coerce").abs()

    # I1, I2, I3 padronizados
    df["I1"] = df[cols_i[0]] if len(cols_i) > 0 else np.nan
    df["I2"] = df[cols_i[1]] if len(cols_i) > 1 else np.nan
    df["I3"] = df[cols_i[2]] if len(cols_i) > 2 else np.nan
    df["Corrente_Max_A"] = df[cols_i].max(axis=1)

    # Alias para compatibilidade interna
    df["Corrente_A"] = df["Corrente_Max_A"]

    df["Barra_orig"] = df["Elemento"].map(
        lambda e: elementos.get(e, {}).get("b1", "")
    )
    df["Barra_dest"] = df["Elemento"].map(
        lambda e: elementos.get(e, {}).get("b2", "")
    )
    df["Distancia_km"] = df["Elemento"].map(
        lambda e: (
            max(
                distancias.get(elementos[e]["b1"], np.nan),
                distancias.get(elementos[e]["b2"], np.nan),
            )
            if e in elementos else np.nan
        )
    )
    df = df[df["Distancia_km"].notna()].copy()

    return df[[
        "Elemento", "Barra_orig", "Barra_dest",
        "Distancia_km", "I1", "I2", "I3", "Corrente_Max_A", "Corrente_A",
    ]].sort_values("Distancia_km")


def analisar_potencias(df_p, elementos, distancias):
    """
    [A10] Processa CSV de potências do OpenDSS.

    Identificação explícita de P1, P2, P3, Q1, Q2, Q3 (não genérica).
    Usa apenas Terminal 1 para evitar duplicação.
    Imprime as colunas originais do CSV para auditoria.

    Retorna DataFrame com: Elemento, Terminal, Barra_orig, Barra_dest,
    Distancia_km, P_kW, Q_kVAr, S_kVA, FP_calculado.
    """
    df = df_p.copy()
    df.columns = df.columns.str.strip()

    # --- Auditoria: imprime colunas originais do CSV ---
    print(f"  [Powers CSV] Colunas originais: {list(df.columns)}")

    col_elem = coluna_elemento(df)
    if col_elem is None:
        raise ValueError("Exportação de potências sem coluna Element.")

    df["Elemento"] = df[col_elem].apply(normalizar_elemento)
    df = df[df["Elemento"].str.startswith("LINE.", na=False)].copy()

    # --- [A10] Filtrar apenas Terminal 1 ---
    col_terminal = obter_coluna_existente(df, ["Terminal", "TERMINAL", "term"])
    if col_terminal is not None:
        df_t1 = df[pd.to_numeric(df[col_terminal], errors="coerce") == 1].copy()
        if not df_t1.empty:
            df = df_t1
            df["Terminal"] = 1
        else:
            df = df.drop_duplicates(subset=["Elemento"]).copy()
            df["Terminal"] = None
    else:
        df = df.drop_duplicates(subset=["Elemento"]).copy()
        df["Terminal"] = None

    # --- Identificação das colunas de potência ---
    # Suporta dois formatos do Export Powers:
    #   Formato A: P1, P2, P3, Q1, Q2, Q3  (modelo por fase)
    #   Formato B: P(kW), Q(kvar)           (modelo total por elemento, OpenDSS moderno)
    # Fallback genérico por prefixo foi REMOVIDO para evitar capturar colunas erradas
    # (ex.: P_Normal, P_Emergency).
    cols_mapa_upper = {str(c).strip().upper(): c for c in df.columns}

    def _fases(prefixo):
        """Busca P1/P2/P3 ou Q1/Q2/Q3 exatamente (após strip+upper)."""
        return [
            cols_mapa_upper[f"{prefixo}{n}"]
            for n in ("1", "2", "3")
            if f"{prefixo}{n}" in cols_mapa_upper
        ]

    # Formato A: fases individuais
    cols_p_fases = _fases("P")
    cols_q_fases = _fases("Q")

    # Formato B: colunas totais P(kW) e Q(kvar)
    #   OpenDSS pode gerar "P(kW)" ou " P(kW)" (com espaço) — o strip() já limpou.
    col_p_total = cols_mapa_upper.get("P(KW)") or cols_mapa_upper.get("P(KW) ")
    col_q_total = cols_mapa_upper.get("Q(KVAR)") or cols_mapa_upper.get("Q(KVAR) ")

    modo = None
    if cols_p_fases and cols_q_fases:
        modo = "fases"
        col_p_usado = cols_p_fases
        col_q_usado = cols_q_fases
    elif col_p_total and col_q_total:
        modo = "total"
        col_p_usado = [col_p_total]
        col_q_usado = [col_q_total]
    else:
        raise ValueError(
            "Export Powers: nenhum formato reconhecido de colunas P/Q. "
            f"Colunas disponíveis: {list(df.columns)}"
        )

    print(f"  [Powers CSV] Modo detectado: {modo}")
    print(f"  [Powers CSV] Colunas P usadas: {col_p_usado}")
    print(f"  [Powers CSV] Colunas Q usadas: {col_q_usado}")

    for c in col_p_usado + col_q_usado:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Soma das fases (Terminal 1 = fluxo de entrada; sinal indica direção)
    df["P_kW"]   = df[col_p_usado].sum(axis=1)
    df["Q_kVAr"] = df[col_q_usado].sum(axis=1)
    df["S_kVA"]  = np.sqrt(df["P_kW"] ** 2 + df["Q_kVAr"] ** 2)
    df["FP_calculado"] = np.where(
        df["S_kVA"] > 0,
        df["P_kW"].abs() / df["S_kVA"],
        np.nan,
    )

    df["Barra_orig"] = df["Elemento"].map(
        lambda e: elementos.get(e, {}).get("b1", "")
    )
    df["Barra_dest"] = df["Elemento"].map(
        lambda e: elementos.get(e, {}).get("b2", "")
    )
    df["Distancia_km"] = df["Elemento"].map(
        lambda e: (
            max(
                distancias.get(elementos[e]["b1"], np.nan),
                distancias.get(elementos[e]["b2"], np.nan),
            )
            if e in elementos else np.nan
        )
    )
    df = df[df["Distancia_km"].notna()].copy()

    return df[[
        "Elemento", "Terminal", "Barra_orig", "Barra_dest",
        "Distancia_km", "P_kW", "Q_kVAr", "S_kVA", "FP_calculado",
    ]].sort_values("Distancia_km")


# =============================================================================
# CENÁRIOS DE SIMULAÇÃO
# =============================================================================


def montar_cenarios(transformador_alvo, soma_pot_nom_kva):
    """
    Monta lista de cenários:
      - Cenário de calibração (se DEMANDA_TOTAL_ALVO_KVA for informado)
      - Cenários percentuais gerais (estresse)
      - Cenários localizados no transformador-alvo

    Args:
        transformador_alvo: row do trafo alvo ou None
        soma_pot_nom_kva:   soma das potências nominais dos trafos energizados
    """
    cenarios = []

    # --- Cenário de calibração por demanda-alvo ---
    if DEMANDA_TOTAL_ALVO_KVA is not None and soma_pot_nom_kva > 0:
        fator_calib = DEMANDA_TOTAL_ALVO_KVA / soma_pot_nom_kva
        cenarios.append({
            "nome":             f"Calibração {DEMANDA_TOTAL_ALVO_KVA:.0f} kVA",
            "carregamento_rede": fator_calib,
            "fp":               FP_BASE,
        })
        print(
            f"  [Calibração] DEMANDA_TOTAL_ALVO_KVA={DEMANDA_TOTAL_ALVO_KVA:.0f} kVA | "
            f"Soma POT_NOM={soma_pot_nom_kva:.0f} kVA | "
            f"Fator={fator_calib:.4f} ({fator_calib*100:.1f}%)"
        )

    # --- Cenários percentuais (estresse) ---
    cenarios += list(CENARIOS_REDE)

    # --- Cenários localizados no transformador-alvo ---
    if transformador_alvo is not None:
        for carregamento in CARREGAMENTOS_TRAFO_ALVO:
            cenarios.append({
                "nome":                    f"Trafo alvo {carregamento * 100:.0f}%",
                "carregamento_rede":       0.60,
                "carregamento_trafo_alvo": carregamento,
                "fp":                      FP_BASE,
            })

    return cenarios


# =============================================================================
# [A6] FATOR DE POTÊNCIA — DOIS TIPOS DE CENÁRIO
# =============================================================================


def calcular_carga_mesmo_kva(pot_kva, carregamento, fp):
    """
    [A6-A] Mesmo kVA com fator de potência variável.
    kVA fixo; kW varia com FP.
    """
    carga_kva = pot_kva * carregamento
    carga_kw  = carga_kva * fp
    return carga_kva, carga_kw


def calcular_carga_mesmo_kw(kw_referencia, fp_novo):
    """
    [A6-B] Mesmo kW com fator de potência variável.
    kW fixo; kVA aumenta quando FP diminui.
    """
    if fp_novo <= 0:
        raise ValueError("FP deve ser > 0.")
    carga_kva  = kw_referencia / fp_novo
    carga_kvar = kw_referencia * math.tan(math.acos(fp_novo))
    return carga_kva, kw_referencia, carga_kvar


# =============================================================================
# SIMULAÇÃO OPENDSS
# =============================================================================


def simular_cenario(
    dss,
    alim_id,
    pac_inicial,
    cenario,
    linhas_energizadas,
    chaves_energizadas,
    trafos_energizados,
    trafo_alvo,
    elementos,
    distancias,
    pasta_saida_alim,
    distancia_max_km,
    comprimento_total_km,
):
    """
    Executa um cenário no OpenDSS e retorna os resultados.
    [A7] Não afirma que representa um horário específico.
    """
    nome                  = cenario["nome"]
    carregamento_rede     = cenario["carregamento_rede"]
    carregamento_trafo_alvo = cenario.get("carregamento_trafo_alvo")
    fp                    = cenario["fp"]

    print(
        f"\nCenário: {nome} | Rede: {carregamento_rede * 100:.0f}% "
        f"| FP: {fp:.2f} | Tipo: {TIPO_SIMULACAO}"
    )

    dss.text("Clear")
    dss.text(
        f"New Circuit.{alim_id} "
        f"bus1={pac_inicial} basekv={TENSAO_MT_KV} phases=3 pu=1.0"
    )

    imp_real      = 0
    imp_estimada  = 0

    # --- Linhas ---
    for _, row in linhas_energizadas.iterrows():
        b1     = bus(row["PAC_1"])
        b2     = bus(row["PAC_2"])
        cod    = clean_id(row["COD_ID"])
        length = comprimento_km_linha(row)
        r1, x1, origem_imp = obter_impedancia_linha(row, length)

        if origem_imp in {"real_bdgd", "segcon_bdgd"}:
            imp_real += 1
        else:
            imp_estimada += 1

        dss.text(
            f"New Line.L_{cod} "
            f"bus1={b1} bus2={b2} phases=3 "
            f"length={length:.6f} units=km "
            f"r1={r1:.6f} x1={x1:.6f} c1=0"
        )

    # --- Chaves fechadas ---
    for _, row in chaves_energizadas.iterrows():
        fechada, _, _, _ = chave_esta_fechada(row)
        if not fechada:
            continue
        b1  = bus(row["PAC_1"])
        b2  = bus(row["PAC_2"])
        cod = clean_id(row["COD_ID"])
        dss.text(
            f"New Line.SW_{cod} "
            f"bus1={b1} bus2={b2} phases=3 "
            f"length=0.00001 units=km r1=0.001 x1=0.001 c1=0"
        )

    # --- Transformadores e cargas ---
    potencia_total_kw  = 0.0
    potencia_total_kva = 0.0
    trafos_modelados   = 0

    for _, row in trafos_energizados.iterrows():
        bus_mt       = bus(row["PAC_1"])
        cod_original = str(row["COD_ID"]).strip()
        cod          = clean_id(cod_original)
        pot_kva      = limpar_numero(row["POT_NOM"])

        if not bus_mt or pd.isna(pot_kva) or pot_kva <= 0:
            continue

        carregamento = carregamento_rede
        if (
            trafo_alvo is not None
            and carregamento_trafo_alvo is not None
            and cod_original == str(trafo_alvo["COD_ID"]).strip()
        ):
            carregamento = carregamento_trafo_alvo

        # [A5] kVA = pot_nom * carregamento; kW = kVA * fp
        carga_kva, carga_kw = calcular_carga_mesmo_kva(pot_kva, carregamento, fp)
        bus_bt = f"{bus_mt}_BT_{cod}"

        dss.text(
            f"New Transformer.T_{cod} "
            f"phases=3 windings=2 "
            f"buses=[{bus_mt} {bus_bt}] "
            f"kvs=[{TENSAO_MT_KV} {TENSAO_BT_KV}] "
            f"kvas=[{pot_kva:.3f} {pot_kva:.3f}] "
            f"%r={TRAFO_PERCENT_R:.3f} xhl={TRAFO_XHL:.3f}"
        )
        dss.text(
            f"New Load.L_{cod} "
            f"bus1={bus_bt}.1.2.3 phases=3 kv={TENSAO_BT_KV} "
            f"kw={carga_kw:.3f} pf={fp:.4f}"
        )

        potencia_total_kw  += carga_kw
        potencia_total_kva += carga_kva
        trafos_modelados   += 1

    dss.text(f"Set VoltageBases=[{TENSAO_MT_KV}, {TENSAO_BT_KV}]")
    dss.text("CalcVoltageBases")
    dss.text("Set mode=snapshot")
    dss.text("Solve")

    convergiu = bool(dss.solution.converged)
    if not convergiu:
        warnings.warn(f"Cenário '{nome}' não convergiu.")

    # --- Perdas totais via dss.circuit.losses ---
    losses     = dss.circuit.losses
    perda_kw   = losses[0] / 1000.0
    perda_kvar = losses[1] / 1000.0

    # Parâmetros de modelo de carga (registrados no cenário)
    # OpenDSS Load padrão: model=1 (ZIP), Vminpu=0.95, Vmaxpu=1.05
    CARGA_MODEL  = 1        # modelo ZIP constante potência
    CARGA_VMIN   = 0.95     # Vminpu padrão
    CARGA_VMAX   = 1.05     # Vmaxpu padrão
    CARGA_STATUS = "fixed"
    CARGA_CONN   = "wye"
    # kV, kW, pf são definidos por trafo — registrados no resultado abaixo

    # --- Exportações (com limpeza prévia para evitar CSVs antigos) ---
    import glob
    for csv_file in glob.glob(os.path.join(pasta_saida_alim, "*EXP_*.CSV")):
        try:
            os.remove(csv_file)
        except OSError:
            pass

    os.makedirs(pasta_saida_alim, exist_ok=True)
    dss.text(f'cd "{pasta_saida_alim}"')

    dss.text("Export Voltages")
    arq_v = encontrar_exportacao(pasta_saida_alim, alim_id, "VOLTAGES")
    if arq_v is None:
        raise FileNotFoundError("CSV de tensões não encontrado.")
    tensoes = analisar_tensoes(pd.read_csv(arq_v), distancias)

    dss.text("Export Currents")
    arq_i = encontrar_exportacao(pasta_saida_alim, alim_id, "CURRENTS")
    if arq_i is None:
        raise FileNotFoundError("CSV de correntes não encontrado.")
    correntes = analisar_correntes(pd.read_csv(arq_i), elementos, distancias)

    dss.text("Export Powers")
    arq_p = encontrar_exportacao(pasta_saida_alim, alim_id, "POWERS")
    potencias = pd.DataFrame()
    if arq_p is not None:
        try:
            potencias = analisar_potencias(
                pd.read_csv(arq_p), elementos, distancias
            )
        except Exception as err_p:
            print(f"  Aviso ao analisar potências: {err_p}")

    tensao_min   = tensoes["Tensao_pu"].min()
    tensao_media = tensoes["Tensao_pu"].mean()
    corrente_max = correntes["Corrente_A"].max() if not correntes.empty else np.nan

    # -------------------------------------------------------------------
    # Potência da fonte: P, Q, S
    # -------------------------------------------------------------------
    # total_power já retorna valores em kW e kVAr (não em W/VAr).
    # Sinal: negativo = geração pela fonte; abs() converte para positivo.
    tp = dss.circuit.total_power
    p_fonte_kw   = abs(float(tp[0]))
    q_fonte_kvar = abs(float(tp[1]))
    s_fonte_kva  = np.hypot(p_fonte_kw, q_fonte_kvar)

    # Tensão real no barramento da fonte (p.u. e kV fase-fase)
    try:
        v_fonte_pu = None
        v_pu_bus = tensoes[tensoes["Barra"] == pac_inicial.upper()]
        if not v_pu_bus.empty:
            v_fonte_pu = float(v_pu_bus["Tensao_pu"].iloc[0])
        v_fonte_kv = (v_fonte_pu * TENSAO_MT_KV) if v_fonte_pu is not None else TENSAO_MT_KV
    except Exception:
        v_fonte_kv = TENSAO_MT_KV
        v_fonte_pu = None

    # Corrente calculada pela potência da fonte: I = S / (√3 × V_linha)
    i_fonte_calc = (
        s_fonte_kva / (math.sqrt(3) * v_fonte_kv)
        if v_fonte_kv > 0 else np.nan
    )

    # Leitura direta das correntes no Vsource
    i_vsource_fases = []          # magnitudes por fase (A)
    i_vsource_media = np.nan      # média das três fases
    try:
        # Tentar ativar o elemento Vsource.Source
        vsource_nome = "Vsource.Source"
        dss.circuit.set_active_element(vsource_nome)
        elem_nome = dss.cktelement.name

        if elem_nome.upper() != vsource_nome.upper():
            # Nome padrão não encontrado; listar Vsources disponíveis
            vsources_disponiveis = [
                e for e in dss.circuit.elements_names
                if e.upper().startswith("VSOURCE.")
            ]
            print(f"  [Vsource] '{vsource_nome}' não encontrado. ")
            print(f"  [Vsource] Vsources disponíveis: {vsources_disponiveis}")
            if vsources_disponiveis:
                dss.circuit.set_active_element(vsources_disponiveis[0])
                vsource_nome = vsources_disponiveis[0]
                print(f"  [Vsource] Usando: {vsource_nome}")

        # currents_mag_ang: lista alternada [mag_f1, ang_f1, mag_f2, ang_f2, ...]
        # Terminal 1 = índices 0,2,4 (magnitudes)
        mag_ang = dss.cktelement.currents_mag_ang
        if mag_ang and len(mag_ang) >= 6:
            i_vsource_fases = [mag_ang[0], mag_ang[2], mag_ang[4]]
            i_vsource_media  = float(np.mean(i_vsource_fases))
        else:
            print(f"  [Vsource] currents_mag_ang retornou: {mag_ang}")
    except Exception as err_vs:
        print(f"  [Vsource] Erro ao ler correntes: {err_vs}")

    # Corrente do primeiro trecho real (> 0,01 A, excluindo elementos SW)
    corrente_primeiro_trecho = np.nan
    elem_primeiro_trecho     = None
    if not correntes.empty:
        df_ord = correntes[
            ~correntes["Elemento"].str.contains(r"\.SW_", case=False, na=False)
        ].sort_values("Distancia_km")
        for _, row_c in df_ord.iterrows():
            val = float(row_c["Corrente_A"])
            if val > 0.01:            # ignora correntes praticamente nulas
                corrente_primeiro_trecho = val
                elem_primeiro_trecho     = row_c["Elemento"]
                break
        if np.isnan(corrente_primeiro_trecho):
            print("  [Validação] AVISO: nenhum trecho (não-SW) com corrente > 0,01 A.")

    # -------------------------------------------------------------------
    # Indicadores Normalizados e Cálculos Efetivos
    # -------------------------------------------------------------------
    p_carga_efetiva_kw   = p_fonte_kw   - perda_kw
    q_carga_efetiva_kvar = q_fonte_kvar - perda_kvar
    s_carga_efetiva_kva  = np.hypot(p_carga_efetiva_kw, q_carga_efetiva_kvar)

    razao_efetiva_nominal = (
        100.0 * p_carga_efetiva_kw / potencia_total_kw
        if potencia_total_kw > 0 else np.nan
    )

    eficiencia_nominal = (
        100.0 * potencia_total_kw / (potencia_total_kw + perda_kw)
        if (potencia_total_kw + perda_kw) > 0 else np.nan
    )

    eficiencia_fluxo = (
        100.0 * p_carga_efetiva_kw / p_fonte_kw
        if p_fonte_kw > 0 else np.nan
    )
    
    # 1. Perdas relativas à fonte
    perdas_fonte_pct = (100.0 * perda_kw / p_fonte_kw) if p_fonte_kw > 0 else np.nan
    # 2. Perdas relativas à carga efetiva
    perdas_carga_pct = (100.0 * perda_kw / p_carga_efetiva_kw) if p_carga_efetiva_kw > 0 else np.nan
    # 3. Corrente por MVA instalado
    corrente_por_mva = i_fonte_calc / (potencia_total_kva / 1000.0) if potencia_total_kva > 0 else np.nan
    # 4. Potência instalada por quilômetro
    potencia_kva_por_km = potencia_total_kva / comprimento_total_km if comprimento_total_km > 0 else np.nan
    # 5. Transformadores por quilômetro
    trafos_por_km = trafos_modelados / comprimento_total_km if comprimento_total_km > 0 else np.nan
    # 6. Queda de tensão global (pu)
    queda_tensao_pu = v_fonte_pu - tensao_min if v_fonte_pu is not None else np.nan
    # 7. Queda de tensão por quilômetro
    queda_tensao_por_km = queda_tensao_pu / distancia_max_km if pd.notna(queda_tensao_pu) and distancia_max_km > 0 else np.nan

    # --- Impressão do bloco de validação ---
    verif_pq = potencia_total_kw + perda_kw
    dif_efetiva_nominal = p_carga_efetiva_kw - potencia_total_kw
    print(
        f"\n  [Balanço de potência]"
        f"\n    P carga nominal (cmd):  {potencia_total_kw:.2f} kW"
        f"\n    P perdas (losses):      {perda_kw:.2f} kW"
        f"\n    P carga + P perdas:     {verif_pq:.2f} kW"
        f"\n    P fonte (total_pwr):    {p_fonte_kw:.2f} kW"
        f"\n    Dif P_fonte vs soma:    {abs(p_fonte_kw - verif_pq):.2f} kW"
        f"\n    P carga efetiva:        {p_carga_efetiva_kw:.2f} kW  [= P_fonte - P_perdas]"
        f"\n    Q carga efetiva:        {q_carga_efetiva_kvar:.2f} kVAr"
        f"\n    S carga efetiva:        {s_carga_efetiva_kva:.2f} kVA"
        f"\n    Dif efetiva vs nominal: {dif_efetiva_nominal:+.2f} kW"
        f"  ({razao_efetiva_nominal:.1f}% da nominal)" if pd.notna(razao_efetiva_nominal) else ""
    )
    if pd.notna(razao_efetiva_nominal) and razao_efetiva_nominal < 95.0:
        print(
            "    DIAGNÓSTICO: Carga efetiva < 95% da nominal. "
            "Possível efeito de subtensão (Vminpu=0.95) ou perdas elevadas no transformador. "
            "Verifique tensões nas barras BT e ajuste Vminpu/Vmaxpu se necessário."
        )
    print(
        f"    Q fonte:                {q_fonte_kvar:.2f} kVAr"
        f"\n    S fonte:                {s_fonte_kva:.2f} kVA"
        f"\n    V linha real (kV):      {v_fonte_kv:.4f} kV  "
        f"(pu={v_fonte_pu if v_fonte_pu is not None else 'N/D'})"
    )
    if i_vsource_fases:
        print(
            f"    I Vsource fases (A):    {[f'{x:.2f}' for x in i_vsource_fases]}"
            f"  media={i_vsource_media:.2f} A"
        )
    else:
        print("    I Vsource fases (A):    não disponível")
    print(
        f"    I fonte calculada:      {i_fonte_calc:.2f} A" if pd.notna(i_fonte_calc) else
        "    I fonte calculada:      N/D"
    )
    if pd.notna(i_vsource_media) and pd.notna(i_fonte_calc) and i_fonte_calc > 0:
        diff_pct_vs = abs(i_vsource_media - i_fonte_calc) / i_fonte_calc * 100
        alerta_vs = "  *** ALERTA > 20%" if diff_pct_vs > 20 else ""
        print(f"    Dif I_vsource vs I_calc: {diff_pct_vs:.1f}%{alerta_vs}")
    if pd.notna(corrente_primeiro_trecho):
        print(
            f"    I 1º trecho não-nulo:   {corrente_primeiro_trecho:.3f} A"
            f"  [{elem_primeiro_trecho}]"
        )

    # --- Parâmetros de modelo de carga impressos ---
    print(
        f"\n  [Modelo de carga OpenDSS]"
        f"\n    model={CARGA_MODEL} | Vminpu={CARGA_VMIN} | Vmaxpu={CARGA_VMAX}"
        f"\n    status={CARGA_STATUS} | conexão={CARGA_CONN}"
        f"\n    kV={TENSAO_BT_KV} | FP={fp:.4f}"
    )

    # --- Resumo do cenário no terminal ---
    print(
        f"\n  [Resumo cenário '{nome}']"
        f"\n    Convergiu:              {convergiu}"
        f"\n    Tensão mínima:          {tensao_min:.4f} p.u."
        f"\n    Tensão média:           {tensao_media:.4f} p.u."
        f"\n    P fonte:                {p_fonte_kw:.2f} kW"
        f"\n    Q fonte:                {q_fonte_kvar:.2f} kVAr"
        f"\n    S fonte:                {s_fonte_kva:.2f} kVA"
        f"\n    I fonte (calc.):        {i_fonte_calc:.2f} A" if pd.notna(i_fonte_calc) else
        f"\n  [Resumo cenário '{nome}']\n    Convergiu: {convergiu}"
    )
    print(
        f"    P carga efetiva:        {p_carga_efetiva_kw:.2f} kW"
        f"\n    Perdas:                 {perda_kw:.2f} kW  |  {perda_kvar:.2f} kVAr"
        f"\n    Efic. nominal:          {eficiencia_nominal:.2f} %  [P_nom/(P_nom+perdas)]"
        f"\n    Efic. fluxo efetivo:    {eficiencia_fluxo:.2f} %  [P_efetiva/P_fonte]  <- PRINCIPAL"
    )

    resultado = {
        "Alimentador":                    alim_id,
        "Cenario":                        nome,
        "Tipo_Simulacao":                 TIPO_SIMULACAO,
        "Convergiu":                      convergiu,
        "Carregamento_Rede_%":            carregamento_rede * 100,
        "Carregamento_Trafo_Alvo_%": (
            carregamento_trafo_alvo * 100 if carregamento_trafo_alvo is not None else np.nan
        ),
        "Fator_Potencia":                 fp,
        "Transformadores_Modelados":      trafos_modelados,
        # --- Carga nominal comandada ao OpenDSS ---
        "P_Carga_Nominal_Comandada_kW":   potencia_total_kw,
        "S_Carga_Nominal_Comandada_kVA":  potencia_total_kva,
        # --- Potência da fonte (fluxo real) ---
        "P_Fonte_kW":                     p_fonte_kw,
        "Q_Fonte_kVAr":                   q_fonte_kvar,
        "S_Fonte_kVA":                    s_fonte_kva,
        "I_Fonte_Calculada_A":            i_fonte_calc,
        "I_Vsource_Media_A":              i_vsource_media,
        "I_Primeiro_Trecho_A":            corrente_primeiro_trecho,
        "Elem_Primeiro_Trecho":           elem_primeiro_trecho,
        "V_Fonte_pu":                     v_fonte_pu,
        # --- Carga efetiva absorvida (P_fonte - perdas) ---
        "P_Carga_Efetiva_kW":             p_carga_efetiva_kw,
        "Q_Carga_Efetiva_kVAr":           q_carga_efetiva_kvar,
        "S_Carga_Efetiva_kVA":            s_carga_efetiva_kva,
        "Razao_Carga_Efetiva_Nominal_%":  razao_efetiva_nominal,
        # --- Perdas ---
        "Perda_Ativa_estimada_kW":        perda_kw,
        "Perda_Reativa_estimada_kVAr":    perda_kvar,
        # --- Tensões ---
        "Tensao_Minima_pu":               tensao_min,
        "Tensao_Media_pu":                tensao_media,
        "Corrente_Maxima_A":              corrente_max,
        # --- Eficiências ---
        "Eficiencia_Nominal_%":           eficiencia_nominal,
        "Eficiencia_Fluxo_Efetivo_%":     eficiencia_fluxo,
        # --- Indicadores Normalizados ---
        "Comprimento_Total_km":           comprimento_total_km,
        "Distancia_Maxima_km":            distancia_max_km,
        "Perdas_Fonte_%":                 perdas_fonte_pct,
        "Perdas_Carga_%":                 perdas_carga_pct,
        "Corrente_por_MVA":               corrente_por_mva,
        "Potencia_kVA_por_km":            potencia_kva_por_km,
        "Trafos_por_km":                  trafos_por_km,
        "Queda_Tensao_pu":                queda_tensao_pu,
        "Queda_Tensao_por_km":            queda_tensao_por_km,
        # --- Parâmetros de modelo de carga ---
        "Carga_Model":                    CARGA_MODEL,
        "Carga_Vminpu":                   CARGA_VMIN,
        "Carga_Vmaxpu":                   CARGA_VMAX,
        "Carga_Status":                   CARGA_STATUS,
        "Carga_Conn":                     CARGA_CONN,
        "Carga_kV":                       TENSAO_BT_KV,
        "Carga_FP":                       fp,
        # --- Qualidade ---
        "Total_Barras":                   len(tensoes) if not tensoes.empty else np.nan,
        "Barras_Abaixo_0_97":             int((tensoes["Tensao_pu"] < 0.97).sum()),
        "Barras_Abaixo_0_93":             int((tensoes["Tensao_pu"] < 0.93).sum()),
        "Barras_Abaixo_0_90":             int((tensoes["Tensao_pu"] < 0.90).sum()),
        "Percentual_Abaixo_0_97":         100.0 * (tensoes["Tensao_pu"] < 0.97).sum() / len(tensoes) if not tensoes.empty else np.nan,
        "Percentual_Abaixo_0_93":         100.0 * (tensoes["Tensao_pu"] < 0.93).sum() / len(tensoes) if not tensoes.empty else np.nan,
        "Percentual_Abaixo_0_90":         100.0 * (tensoes["Tensao_pu"] < 0.90).sum() / len(tensoes) if not tensoes.empty else np.nan,
        "Linhas_Impedancia_Real_BDGD":    imp_real,
        "Linhas_Impedancia_Estimada":     imp_estimada,
    }

    return resultado, tensoes, correntes, potencias


# =============================================================================
# FUNÇÃO PRINCIPAL POR ALIMENTADOR
# =============================================================================


def processar_alimentador(alim_id, alim_config, ssdmt_orig, untrmt, unsemt):
    """
    Executa todas as etapas para um alimentador:
      1. Comprimento pela geometria
      2. Construção do grafo
      3. Escolha da origem
      4. Análise topológica
      5. Diagnóstico de chaves
      6. Simulações (se SIMULAR=True)
      7. Exportação de planilhas e gráficos
    """
    pasta_saida_alim = os.path.join(PASTA_SAIDA, "resultados", clean_id(alim_id))
    os.makedirs(pasta_saida_alim, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"ALIMENTADOR: {alim_id} ({alim_config['perfil']})")
    print(f"{'=' * 60}")

    # ------------------------------------------------------------------
    # [A1] Comprimento pela geometria
    # ------------------------------------------------------------------
    ssdmt, ssdmt_geo = calcular_comprimentos_geometria(ssdmt_orig)
    diagnosticar_cobertura_segcon(ssdmt)

    # ------------------------------------------------------------------
    # [A4] Diagnóstico das chaves
    # ------------------------------------------------------------------
    df_diag_chaves = diagnostico_chaves(unsemt)

    # ------------------------------------------------------------------
    # [A3] Construção do grafo
    # ------------------------------------------------------------------
    grafo, elementos, diag_grafo = construir_grafo(ssdmt, unsemt)

    # ------------------------------------------------------------------
    # [A2] Escolha da origem
    # ------------------------------------------------------------------
    pac_inicial, metodo_origem = escolher_pac_inicial(
        ssdmt, grafo, GDB_PATH, PAC_INICIAL_MANUAL
    )
    print(f"\n  PAC inicial : {pac_inicial}")
    print(f"  Método      : {metodo_origem}")

    # ------------------------------------------------------------------
    # [A3] Análise topológica
    # ------------------------------------------------------------------
    topo = analisar_topologia(grafo, pac_inicial, diag_grafo)

    barras_energizadas = set(topo["subgrafo"].nodes)

    # ------------------------------------------------------------------
    # Transformador-alvo
    # ------------------------------------------------------------------
    trafo_alvo = selecionar_transformador_alvo(
        untrmt, barras_energizadas, alim_config.get("transformador_alvo")
    )

    if trafo_alvo is not None:
        print(f"\n  Transformador-alvo: {trafo_alvo['COD_ID']}")
        print(f"  PAC MT:             {trafo_alvo['BUS_MT']}")
        print(f"  Potência nominal:   {trafo_alvo['POT_NOM_NUM']:.2f} kVA")

        i_trafo_100pct = trafo_alvo["POT_NOM_NUM"] / (math.sqrt(3) * TENSAO_MT_KV)
        print(f"  Corrente aprox. 100%: {i_trafo_100pct:.1f} A")
    else:
        print("\n  AVISO: transformador-alvo não encontrado.")

    # ------------------------------------------------------------------
    # Elementos energizados
    # ------------------------------------------------------------------
    linhas_energizadas = ssdmt[
        ssdmt["PAC_1"].apply(bus).isin(barras_energizadas)
        & ssdmt["PAC_2"].apply(bus).isin(barras_energizadas)
    ].copy()

    chaves_energizadas = unsemt[
        unsemt["PAC_1"].apply(bus).isin(barras_energizadas)
        & unsemt["PAC_2"].apply(bus).isin(barras_energizadas)
    ].copy()

    trafos_energizados = untrmt[
        untrmt["PAC_1"].apply(bus).isin(barras_energizadas)
    ].copy()

    # ------------------------------------------------------------------
    # [A3] DataFrames de diagnóstico para exportação
    # ------------------------------------------------------------------
    df_diag_topo = diagnostico_topologia_df(
        diag_grafo, topo, pac_inicial, metodo_origem
    )
    df_diag_comp = diagnostico_comprimentos_df(ssdmt)
    df_caminho   = pd.DataFrame(
        {"Sequencia": range(len(topo["caminho_origem_ponta"])),
         "Barra":     topo["caminho_origem_ponta"]}
    )
    df_trafos = trafos_energizados[[
        c for c in ["COD_ID", "PAC_1", "PAC_2", "POT_NOM"]
        if c in trafos_energizados.columns
    ]].copy()

    # ------------------------------------------------------------------
    # Simulações OpenDSS
    # ------------------------------------------------------------------
    resumo  = []
    detalhes = {}

    if SIMULAR:
        # Soma das potências nominais dos trafos energizados (para calibração)
        soma_pot_nom_kva = trafos_energizados["POT_NOM"].apply(limpar_numero).sum()
        soma_pot_nom_kva = soma_pot_nom_kva if pd.notna(soma_pot_nom_kva) else 0.0
        print(f"\n  Soma POT_NOM dos trafos energizados: {soma_pot_nom_kva:.0f} kVA")

        cenarios = montar_cenarios(trafo_alvo, soma_pot_nom_kva)
        dss = py_dss_interface.DSS()

        for cenario in cenarios:
            nome_cen = cenario["nome"]
            try:
                resultado, tensoes, correntes, potencias = simular_cenario(
                    dss=dss,
                    alim_id=alim_id,
                    pac_inicial=pac_inicial,
                    cenario=cenario,
                    linhas_energizadas=linhas_energizadas,
                    chaves_energizadas=chaves_energizadas,
                    trafos_energizados=trafos_energizados,
                    trafo_alvo=trafo_alvo,
                    elementos=elementos,
                    distancias=topo["distancias"],
                    pasta_saida_alim=pasta_saida_alim,
                    distancia_max_km=topo["distancia_ponta_km"],
                    comprimento_total_km=topo["comprimento_total_km"],
                )
                resultado.update({
                    "PAC_Inicial":       pac_inicial,
                    "Metodo_Origem":     metodo_origem,
                    "Ponta_Eletrica":    topo["ponta"],
                    "Distancia_Ponta_km": topo["distancia_ponta_km"],
                    "Barras_Totais_Grafo": topo["barras_totais"],
                    "Barras_Energizadas": topo["barras_alcancadas"],
                    "Trafo_Alvo_COD_ID": (
                        str(trafo_alvo["COD_ID"]) if trafo_alvo is not None else None
                    ),
                    "Trafo_Alvo_kVA": (
                        float(trafo_alvo["POT_NOM_NUM"]) if trafo_alvo is not None else np.nan
                    ),
                })
                resumo.append(resultado)
                detalhes[nome_cen] = {
                    "tensoes":   tensoes,
                    "correntes": correntes,
                    "potencias": potencias,
                }
            except Exception as err_cen:
                msg_erro = str(err_cen).encode('ascii', 'ignore').decode()
                warnings.warn(f"Erro no cenário '{nome_cen}': {msg_erro}")
    else:
        print(
            "\n  [INFO] Simulações OpenDSS desativadas (SIMULAR = False).\n"
            "         Valide a topologia e os comprimentos antes de habilitar."
        )

    df_resumo = pd.DataFrame(resumo) if resumo else pd.DataFrame()

    # ------------------------------------------------------------------
    # Exportação da planilha
    # ------------------------------------------------------------------
    exportar_planilha(
        alim_id=alim_id,
        pasta_saida_alim=pasta_saida_alim,
        df_resumo=df_resumo,
        df_diag_topo=df_diag_topo,
        df_diag_comp=df_diag_comp,
        df_diag_chaves=df_diag_chaves,
        df_trafos=df_trafos,
        df_caminho=df_caminho,
        detalhes=detalhes,
    )

    # ------------------------------------------------------------------
    # Gráficos
    # ------------------------------------------------------------------
    if SIMULAR and not df_resumo.empty:
        gerar_graficos(alim_id, pasta_saida_alim, df_resumo, detalhes)

    # Mapa (sempre, se geometria disponível)
    gerar_mapa(alim_id, pasta_saida_alim, ssdmt_geo, topo, trafo_alvo, pac_inicial, metodo_origem)

    return df_resumo


# =============================================================================
# EXPORTAÇÃO DE PLANILHA
# =============================================================================


def exportar_planilha(
    alim_id,
    pasta_saida_alim,
    df_resumo,
    df_diag_topo,
    df_diag_comp,
    df_diag_chaves,
    df_trafos,
    df_caminho,
    detalhes,
):
    """
    [A13] Exporta planilha Excel com abas padronizadas.
    Nome: analise_eletrica_{alim_id}.xlsx
    """
    arquivo = os.path.join(
        pasta_saida_alim, f"analise_eletrica_{alim_id}.xlsx"
    )

    # Avisa se o arquivo já existe
    if os.path.exists(arquivo):
        print(f"\n  AVISO: O arquivo '{arquivo}' já existe e será sobrescrito.")

    params_modelagem = pd.DataFrame({
        "Parametro": [
            "GDB_PATH",
            "ALIMENTADORES_ATIVOS",
            "TENSAO_MT_KV",
            "TENSAO_BT_KV",
            "CRS_METRICO",
            "PAC_INICIAL_MANUAL",
            "TRANSFORMADOR_ALVO_MANUAL",
            "TIPO_SIMULACAO",
            "FP_BASE",
            "FP_BAIXO",
            "USAR_IMPEDANCIA_CONSERVADORA",
            "TRAFO_PERCENT_R",
            "TRAFO_XHL",
            "ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS",
            "SIMULAR",
            "Nota_Impedancias",
            "Nota_Perdas",
        ],
        "Valor": [
            GDB_PATH,
            str(ALIMENTADORES_ATIVOS),
            TENSAO_MT_KV,
            TENSAO_BT_KV,
            CRS_METRICO,
            str(PAC_INICIAL_MANUAL),
            str(ALIMENTADORES_ESTUDO.get(alim_id, {}).get("transformador_alvo", "N/A")),
            TIPO_SIMULACAO,
            FP_BASE,
            FP_BAIXO,
            USAR_IMPEDANCIA_CONSERVADORA,
            TRAFO_PERCENT_R,
            TRAFO_XHL,
            ASSUMIR_CHAVES_INDEFINIDAS_FECHADAS,
            SIMULAR,
            "Impedâncias estimadas quando R1/X1 não disponíveis na BDGD",
            "Perdas estimadas no modelo (não são perdas reais da concessionária)",
        ],
    })

    with pd.ExcelWriter(arquivo, engine="openpyxl") as writer:
        # 1. Resumo
        if not df_resumo.empty:
            df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
        else:
            pd.DataFrame({"Info": ["Simulações desativadas (SIMULAR=False)"]}).to_excel(
                writer, sheet_name="Resumo", index=False
            )

        # 2. Diagnóstico de topologia
        df_diag_topo.to_excel(
            writer, sheet_name="Diag_Topologia", index=False
        )

        # 3. Diagnóstico de comprimentos
        df_diag_comp.to_excel(
            writer, sheet_name="Diag_Comprimentos", index=False
        )

        # 4. Diagnóstico de chaves
        df_diag_chaves.to_excel(
            writer, sheet_name="Diag_Chaves", index=False
        )

        # 5. Transformadores energizados
        df_trafos.to_excel(
            writer, sheet_name="Transformadores", index=False
        )

        # 6–8. Tensão, Corrente, Potência por cenário (somente se simulado)
        for nome_cen, grupo in detalhes.items():
            nome_base = clean_id(nome_cen)[:15]

            if not grupo["tensoes"].empty:
                grupo["tensoes"].to_excel(
                    writer,
                    sheet_name=f"V_{nome_base}"[:31],
                    index=False,
                )
            if not grupo["correntes"].empty:
                grupo["correntes"].to_excel(
                    writer,
                    sheet_name=f"I_{nome_base}"[:31],
                    index=False,
                )
            if not grupo["potencias"].empty:
                grupo["potencias"].to_excel(
                    writer,
                    sheet_name=f"P_{nome_base}"[:31],
                    index=False,
                )

        # 9. Caminho origem → ponta
        df_caminho.to_excel(
            writer, sheet_name="Caminho_Orig_Ponta", index=False
        )

        # 10. Balanço de potência por cenário
        if not df_resumo.empty:
            cols_balanco = [
                c for c in [
                    "Cenario",
                    "Convergiu",
                    "P_Fonte_kW",
                    "Q_Fonte_kVAr",
                    "S_Fonte_kVA",
                    "Perda_Ativa_estimada_kW",
                    "Perda_Reativa_estimada_kVAr",
                    "P_Carga_Efetiva_kW",
                    "Q_Carga_Efetiva_kVAr",
                    "S_Carga_Efetiva_kVA",
                    "P_Carga_Nominal_Comandada_kW",
                    "Razao_Carga_Efetiva_Nominal_%",
                    "Eficiencia_Fluxo_Efetivo_%",
                    "Eficiencia_Nominal_%",
                    "Tensao_Minima_pu",
                    "Tensao_Media_pu",
                ]
                if c in df_resumo.columns
            ]
            df_resumo[cols_balanco].to_excel(
                writer, sheet_name="Balanco_Potencia", index=False
            )

        # 11. Parâmetros de modelagem
        params_modelagem.to_excel(
            writer, sheet_name="Params_Modelagem", index=False
        )

    print(f"\n  Planilha exportada para:\n  {arquivo}")


# =============================================================================
# GRÁFICOS
# =============================================================================


def salvar_figura(fig, pasta, nome_arquivo):
    """Salva figura em PNG na pasta de saída."""
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, nome_arquivo)
    fig.savefig(caminho, dpi=150, bbox_inches="tight")
    print(f"  Gráfico salvo: {caminho}")


def gerar_graficos(alim_id, pasta_saida_alim, resumo, detalhes):
    """
    [A14] Gera e salva todos os gráficos por cenário e por distância.
    """
    if resumo.empty:
        return

    pasta_graf = os.path.join(pasta_saida_alim, "graficos")
    os.makedirs(pasta_graf, exist_ok=True)

    # 1. Tensão mínima por cenário
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(resumo["Cenario"], resumo["Tensao_Minima_pu"], marker="o")
    for lim, cor, label in [
        (0.97, "orange", "0,97 p.u."),
        (0.93, "red",    "0,93 p.u."),
        (0.90, "darkred","0,90 p.u."),
    ]:
        ax.axhline(lim, linestyle="--", color=cor, label=label)
    ax.set_title(f"Tensão mínima por cenário — {alim_id}")
    ax.set_ylabel("Tensão mínima (p.u.)")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"{alim_id}_tensao_min_cenario.png")
    # plt.show()

    # 2. Corrente máxima por cenário
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(resumo["Cenario"], resumo["Corrente_Maxima_A"], marker="o")
    ax.set_title(f"Corrente máxima por cenário — {alim_id}")
    ax.set_ylabel("Corrente máxima (A)")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"{alim_id}_corrente_max_cenario.png")
    # plt.show()

    # 3. Perdas ativas por cenário
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(resumo["Cenario"], resumo["Perda_Ativa_estimada_kW"], marker="o")
    ax.set_title(f"Perdas ativas estimadas por cenário — {alim_id}")
    ax.set_ylabel("Perdas ativas estimadas (kW)")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"{alim_id}_perdas_cenario.png")
    # plt.show()

    # Cenários para perfis ao longo da distância
    cenarios_perfil = [
        c for c in [
            "Rede 20%", "Rede 40%", "Base 60%", "Rede 80%",
            "Rede 100%", "Rede 120%", "Trafo alvo 100%", "Trafo alvo 150%",
        ]
        if c in detalhes
    ]

    # 4. Tensão ao longo da distância
    fig, ax = plt.subplots(figsize=(14, 7))
    for nome in cenarios_perfil:
        dados = detalhes[nome]["tensoes"]
        ax.plot(dados["Distancia_km"], dados["Tensao_pu"], label=nome)
    for lim, cor, label in [
        (0.97, "orange", "0,97 p.u."),
        (0.93, "red",    "0,93 p.u."),
        (0.90, "darkred","0,90 p.u."),
    ]:
        ax.axhline(lim, linestyle="--", color=cor, label=label)
    ax.set_title(f"Perfil de tensão — {alim_id}")
    ax.set_xlabel("Distância elétrica acumulada (km)")
    ax.set_ylabel("Tensão (p.u.)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"{alim_id}_tensao_distancia.png")
    # plt.show()

    # 5. Corrente ao longo da distância
    fig, ax = plt.subplots(figsize=(14, 7))
    for nome in cenarios_perfil:
        dados = detalhes[nome]["correntes"]
        if not dados.empty:
            ax.plot(dados["Distancia_km"], dados["Corrente_A"], label=nome)
    ax.set_title(f"Corrente ao longo do alimentador — {alim_id}")
    ax.set_xlabel("Distância elétrica acumulada (km)")
    ax.set_ylabel("Corrente máxima por elemento (A)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"{alim_id}_corrente_distancia.png")
    # plt.show()

    # 6. Potência ativa ao longo da distância
    fig, ax = plt.subplots(figsize=(14, 7))
    for nome in cenarios_perfil:
        dados = detalhes[nome]["potencias"]
        if not dados.empty:
            ax.plot(dados["Distancia_km"], dados["P_kW"], label=nome)
    ax.set_title(f"Potência ativa ao longo do alimentador — {alim_id}")
    ax.set_xlabel("Distância elétrica acumulada (km)")
    ax.set_ylabel("P (kW)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"{alim_id}_P_distancia.png")
    # plt.show()

    # 7. Potência reativa ao longo da distância
    fig, ax = plt.subplots(figsize=(14, 7))
    for nome in cenarios_perfil:
        dados = detalhes[nome]["potencias"]
        if not dados.empty:
            ax.plot(dados["Distancia_km"], dados["Q_kVAr"], label=nome)
    ax.set_title(f"Potência reativa ao longo do alimentador — {alim_id}")
    ax.set_xlabel("Distância elétrica acumulada (km)")
    ax.set_ylabel("Q (kVAr)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"{alim_id}_Q_distancia.png")
    # plt.show()

    # 8. Potência aparente ao longo da distância
    fig, ax = plt.subplots(figsize=(14, 7))
    for nome in cenarios_perfil:
        dados = detalhes[nome]["potencias"]
        if not dados.empty:
            ax.plot(dados["Distancia_km"], dados["S_kVA"], label=nome)
    ax.set_title(f"Potência aparente ao longo do alimentador — {alim_id}")
    ax.set_xlabel("Distância elétrica acumulada (km)")
    ax.set_ylabel("S (kVA)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    salvar_figura(fig, pasta_graf, f"{alim_id}_S_distancia.png")
    # plt.show()

    # 9. Carregamento do transformador-alvo (cenários localizados)
    cenarios_trafo = [c for c in resumo["Cenario"] if "Trafo alvo" in c]
    if cenarios_trafo:
        df_trafo = resumo[resumo["Cenario"].isin(cenarios_trafo)].copy()
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.bar(df_trafo["Cenario"], df_trafo["Tensao_Minima_pu"])
        ax.set_title(f"Tensão mínima — cenários trafo-alvo — {alim_id}")
        ax.set_ylabel("Tensão mínima (p.u.)")
        ax.tick_params(axis="x", rotation=35)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        salvar_figura(fig, pasta_graf, f"{alim_id}_trafo_alvo_tensao.png")
        # plt.show()


# =============================================================================
# [A15] MAPA DO ALIMENTADOR
# =============================================================================


def gerar_mapa(alim_id, pasta_saida_alim, ssdmt_geo, topo, trafo_alvo, pac_inicial, metodo_origem):
    """
    [A15] Gera mapa do alimentador.

    Usa geometria em EPSG:4326.
    Tenta adicionar basemap via Contextily (EPSG:3857).
    Marca: rede, origem (provisória ou não), ponta elétrica, trafo-alvo.
    """
    try:
        if ssdmt_geo is None or ssdmt_geo.empty:
            print("  Mapa ignorado: sem geometria disponível.")
            return

        pasta_graf = os.path.join(pasta_saida_alim, "graficos")
        os.makedirs(pasta_graf, exist_ok=True)

        fig, ax = plt.subplots(figsize=(14, 12))

        # Rede do alimentador
        ssdmt_geo.plot(ax=ax, linewidth=0.8, color="steelblue", label="Rede MT")

        # Tenta adicionar basemap
        try:
            import contextily as ctx
            # Contextily precisa de EPSG:3857
            ssdmt_3857 = ssdmt_geo.to_crs(epsg=3857)
            ax_ctx, _ = plt.subplots(figsize=(14, 12))
            ssdmt_3857.plot(ax=ax_ctx, linewidth=0.8, color="steelblue", label="Rede MT")
            ctx.add_basemap(ax_ctx, source=ctx.providers.OpenStreetMap.Mapnik)
            ax_ctx.set_title(
                f"Mapa do alimentador {alim_id}"
                + (" [ORIGEM PROVISÓRIA]" if "provisório" in metodo_origem else ""),
                fontsize=12,
            )
            fig_ctx = ax_ctx.get_figure()
            fig_ctx.tight_layout()
            salvar_figura(fig_ctx, pasta_graf, f"{alim_id}_mapa_basemap.png")
            plt.close(fig_ctx)
        except ImportError:
            print("  Contextily não instalado. Mapa sem basemap.")
        except Exception as err_ctx:
            print(f"  Basemap não disponível: {err_ctx}")

        ax.set_title(
            f"Rede do alimentador {alim_id}"
            + (" [ORIGEM PROVISÓRIA]" if "provisório" in metodo_origem else ""),
            fontsize=12,
        )
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)

        # Anotações de barras notáveis (se geometria de pontos disponível)
        # Origem e ponta são apenas nomes de barra, não há geometria direta
        ax.annotate(
            f"Origem:\n{pac_inicial}\n({metodo_origem})",
            xy=(0.02, 0.02), xycoords="axes fraction",
            fontsize=7, color="green",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.7),
        )
        ax.annotate(
            f"Ponta:\n{topo['ponta']}\n({topo['distancia_ponta_km']:.2f} km)",
            xy=(0.02, 0.12), xycoords="axes fraction",
            fontsize=7, color="red",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.7),
        )
        if trafo_alvo is not None:
            ax.annotate(
                f"Trafo-alvo:\n{trafo_alvo['COD_ID']}\n{trafo_alvo['POT_NOM_NUM']:.0f} kVA",
                xy=(0.02, 0.22), xycoords="axes fraction",
                fontsize=7, color="purple",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.7),
            )

        fig.tight_layout()
        salvar_figura(fig, pasta_graf, f"{alim_id}_mapa.png")
        # plt.show()

    except Exception as err:
        print(f"  Aviso ao gerar mapa: {err}")


# =============================================================================
# MÓDULO COMPARATIVO (Industrial x Residencial)
# =============================================================================


def gerar_relatorio_texto(pasta_comp, nw08_100, res_100, nw08_120, res_120):
    texto = [
        "============================================================================",
        "ANÁLISE COMPARATIVA AUTOMÁTICA: PERFIL INDUSTRIAL vs. RESIDENCIAL",
        "============================================================================",
        f"\nOs resultados do modelo indicam as seguintes respostas do alimentador NW08 (Industrial) e do "
        f"Alimentador Residencial sob as mesmas condições metodológicas de análise de fluxo de carga.",
        "\n1. QUEDA DE TENSÃO E BARRAS CRÍTICAS",
    ]
    if nw08_100 is not None and res_100 is not None:
        texto.append(
            f"No cenário nominal (100%), o NW08 apresentou queda total de {nw08_100['Queda_Tensao_pu']:.4f} p.u. "
            f"({nw08_100['Queda_Tensao_por_km']:.4f} p.u./km), com {nw08_100['Percentual_Abaixo_0_93']:.1f}% das barras em atenção."
        )
        texto.append(
            f"O alimentador residencial apresentou queda de {res_100['Queda_Tensao_pu']:.4f} p.u. "
            f"({res_100['Queda_Tensao_por_km']:.4f} p.u./km), com {res_100['Percentual_Abaixo_0_93']:.1f}% das barras em atenção."
        )
    
    texto.append("\n2. SENSIBILIDADE AO CRESCIMENTO DE CARGA (100% -> 120%)")
    if nw08_100 is not None and nw08_120 is not None and res_100 is not None and res_120 is not None:
        sens_nw08 = nw08_100['Tensao_Minima_pu'] - nw08_120['Tensao_Minima_pu']
        sens_res  = res_100['Tensao_Minima_pu'] - res_120['Tensao_Minima_pu']
        texto.append(
            f"A tensão mínima do NW08 caiu {sens_nw08:.4f} p.u. no estresse térmico, enquanto o residencial "
            f"caiu {sens_res:.4f} p.u."
        )
        maior_sens = "Residencial" if sens_res > sens_nw08 else "Industrial"
        texto.append(f"O alimentador {maior_sens} demonstrou maior sensibilidade de tensão ao aumento global da carga.")
        
        cresc_perda_nw08 = (nw08_120['Perda_Ativa_estimada_kW'] - nw08_100['Perda_Ativa_estimada_kW']) / nw08_100['Perda_Ativa_estimada_kW'] * 100
        cresc_perda_res  = (res_120['Perda_Ativa_estimada_kW'] - res_100['Perda_Ativa_estimada_kW']) / res_100['Perda_Ativa_estimada_kW'] * 100
        texto.append(
            f"\nEm termos de perdas, o NW08 teve crescimento relativo de {cresc_perda_nw08:.1f}%, e o residencial {cresc_perda_res:.1f}%."
        )

    texto.append("\nCONCLUSÃO")
    texto.append("Nas condições e hipóteses adotadas (impedâncias estimadas, ausência de demanda calibrada exata), ")
    texto.append("os indicadores normalizados permitem avaliar as discrepâncias de comportamento elétrico entre os dois perfis territoriais.")
    texto.append("Os valores absolutos devem ser interpretados considerando as limitações do modelo expostas na planilha.")

    arq_txt = os.path.join(pasta_comp, "analise_comparativa_industrial_residencial.txt")
    with open(arq_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(texto))
    print(f"  Laudo analítico gerado: {arq_txt}")


def comparar_alimentadores(resumos_dict):
    """
    Gera as análises integradas dos alimentadores ativos.
    """
    if len(resumos_dict) < 2:
        print("\n[Comparação] Necessário pelo menos 2 alimentadores simulados para gerar comparação.")
        return

    pasta_comp = os.path.join(PASTA_SAIDA, "resultados", "comparacao")
    os.makedirs(pasta_comp, exist_ok=True)
    
    pasta_graf_comp = os.path.join(pasta_comp, "graficos_comparativos")
    os.makedirs(pasta_graf_comp, exist_ok=True)

    dfs_validos = []
    for alim_id, df_res in resumos_dict.items():
        if not df_res.empty:
            df = df_res.copy()
            config = next(
                cfg
                for cfg in ALIMENTADORES_ESTUDO.values()
                if cfg.get("codigo") == alim_id
            )
            df.insert(0, "Perfil", config["perfil"])
            df.insert(1, "Regiao", config["regiao"])
            dfs_validos.append(df)
            
    if not dfs_validos:
        return
        
    consolidado = pd.concat(dfs_validos, ignore_index=True)
    
    # Exportação da Planilha Comparativa
    arq_comp = os.path.join(pasta_comp, "comparacao_industrial_residencial.xlsx")
    with pd.ExcelWriter(arq_comp) as writer:
        consolidado.to_excel(writer, sheet_name="Resultados_Cenarios", index=False)
        
        # Abas solicitadas vazias estruturais por enquanto
        pd.DataFrame([{"Aviso": "Construído a partir dos resultados"}]).to_excel(writer, sheet_name="Caracterizacao", index=False)
        pd.DataFrame([{"Aviso": "Ver colunas de Indicadores no final da Resultados_Cenarios"}]).to_excel(writer, sheet_name="Indicadores_Normalizados", index=False)
        pd.DataFrame([
            {"Metodologia": "Mesma versão de código"},
            {"Metodologia": "Mesmos cenários (20% a 120% + alvo)"},
            {"Metodologia": "Mesmo modelo de carga (ZIP 1)"},
        ]).to_excel(writer, sheet_name="Metodologia", index=False)
        pd.DataFrame([
            {"Limitacoes": "Impedâncias estimadas para falta de R1/X1"},
            {"Limitacoes": "Ausência de demanda real calibrada"},
            {"Limitacoes": "Classificação industrial/residencial baseada em topologia territorial indireta"},
        ]).to_excel(writer, sheet_name="Limitacoes", index=False)

    # Gráfico 1: Tensão Mínima
    fig, ax = plt.subplots(figsize=(12, 6))
    for alim_id in resumos_dict.keys():
        df_plot = consolidado[(consolidado["Alimentador"] == alim_id) & (~consolidado["Cenario"].str.contains("Trafo"))]
        if not df_plot.empty:
            config = next(
                cfg
                for cfg in ALIMENTADORES_ESTUDO.values()
                if cfg.get("codigo") == alim_id
            )
            ax.plot(df_plot["Cenario"], df_plot["Tensao_Minima_pu"], marker="o", label=f"{alim_id} ({config['perfil']})")
    for lim, cor, label in [(0.97, "orange", "0,97 p.u."), (0.93, "red", "0,93 p.u."), (0.90, "darkred", "0,90 p.u.")]:
        ax.axhline(lim, linestyle="--", color=cor, label=label)
    ax.set_title("Tensão Mínima por Cenário Comparada")
    ax.legend()
    ax.grid(True, alpha=0.3)
    salvar_figura(fig, pasta_graf_comp, "comp_tensao_minima.png")
    plt.close(fig)

    # Gráfico 2: Perdas Relativas à Fonte
    fig, ax = plt.subplots(figsize=(12, 6))
    for alim_id in resumos_dict.keys():
        df_plot = consolidado[(consolidado["Alimentador"] == alim_id) & (~consolidado["Cenario"].str.contains("Trafo"))]
        if not df_plot.empty:
            ax.plot(df_plot["Cenario"], df_plot["Perdas_Fonte_%"], marker="o", label=f"{alim_id}")
    ax.set_title("Perdas Relativas (%) à Fonte Comparada")
    ax.legend()
    ax.grid(True, alpha=0.3)
    salvar_figura(fig, pasta_graf_comp, "comp_perdas_relativas.png")
    plt.close(fig)

    # Texto analítico
    nw08_100 = consolidado[(consolidado["Alimentador"] == "NW08") & (consolidado["Cenario"] == "Rede 100%")].to_dict('records')
    res_100  = consolidado[(consolidado["Alimentador"] != "NW08") & (consolidado["Cenario"] == "Rede 100%")].to_dict('records')
    nw08_120 = consolidado[(consolidado["Alimentador"] == "NW08") & (consolidado["Cenario"] == "Rede 120%")].to_dict('records')
    res_120  = consolidado[(consolidado["Alimentador"] != "NW08") & (consolidado["Cenario"] == "Rede 120%")].to_dict('records')
    
    gerar_relatorio_texto(
        pasta_comp,
        nw08_100[0] if nw08_100 else None,
        res_100[0] if res_100 else None,
        nw08_120[0] if nw08_120 else None,
        res_120[0] if res_120 else None,
    )
    print(f"\n[Sucesso] Resultados comparativos consolidados em: {pasta_comp}")


# =============================================================================
# PROGRAMA PRINCIPAL
# =============================================================================


def main():
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    carregar_impedancias_segcon(GDB_PATH)

    print("\n=== CONFIGURAÇÕES ATIVAS ===")
    for chave in ALIMENTADORES_ATIVOS:
        cfg = ALIMENTADORES_ESTUDO.get(chave)
        print(
            f"Chave={chave} | "
            f"código={cfg.get('codigo') if cfg else None} | "
            f"perfil={cfg.get('perfil') if cfg else None} | "
            f"região={cfg.get('regiao') if cfg else None} | "
            f"trafo={cfg.get('transformador_alvo') if cfg else None}"
        )

    codigos_ativos = []
    for chave in ALIMENTADORES_ATIVOS:
        cfg = ALIMENTADORES_ESTUDO.get(chave)
        if cfg and cfg.get("codigo"):
            codigos_ativos.append(cfg["codigo"])

    print("\nCódigos efetivamente carregados:", codigos_ativos)

    if not codigos_ativos:
        print("Nenhum alimentador com código válido para simulação.")
        return

    filtro = " OR ".join([f"CTMT = '{a}'" for a in set(codigos_ativos)])

    print("\nCarregando dados da GDB...")
    ssdmt_total  = gpd.read_file(GDB_PATH, layer="SSDMT",  where=filtro)
    untrmt_total = gpd.read_file(GDB_PATH, layer="UNTRMT", where=filtro)
    unsemt_total = gpd.read_file(GDB_PATH, layer="UNSEMT", where=filtro)

    print("\n=== DADOS CARREGADOS ===")
    print(f"Trechos MT  (SSDMT):  {len(ssdmt_total)}")
    print(f"Transformadores:      {len(untrmt_total)}")
    print(f"Chaves (UNSEMT):      {len(unsemt_total)}")
    
    print("\nCTMT disponíveis em SSDMT:")
    ctmt_unicos = set(ssdmt_total["CTMT"].dropna().astype(str).unique())
    for alim in codigos_ativos:
        print(f"{alim} em SSDMT: {str(alim) in ctmt_unicos}")

    resumos = {}

    for indice, chave_config in enumerate(ALIMENTADORES_ATIVOS, start=1):
        print(f"\n>>> INICIANDO ALIMENTADOR {indice}/{len(ALIMENTADORES_ATIVOS)}: {chave_config}")
        
        config = ALIMENTADORES_ESTUDO.get(chave_config)
        if config is None:
            print(f"ERRO: configuração '{chave_config}' não encontrada.")
            continue
            
        alim_id = config.get("codigo")
        if not alim_id:
            print(f"ERRO: código não definido para '{chave_config}'.")
            continue

        print(f">>> Código real do alimentador: {alim_id}")

        ssdmt_alim = ssdmt_total[ssdmt_total["CTMT"].astype(str) == str(alim_id)].copy()
        untrmt_alim = untrmt_total[untrmt_total["CTMT"].astype(str) == str(alim_id)].copy()
        unsemt_alim = unsemt_total[unsemt_total["CTMT"].astype(str) == str(alim_id)].copy()

        print(f">>> Dados filtrados de {alim_id}: {len(ssdmt_alim)} trechos, {len(untrmt_alim)} transformadores, {len(unsemt_alim)} chaves.")

        if ssdmt_alim.empty:
            print(f"ERRO: nenhum trecho encontrado para o alimentador {alim_id}.")
            continue

        try:
            df_resumo = processar_alimentador(alim_id, config, ssdmt_alim, untrmt_alim, unsemt_alim)
            resumos[alim_id] = df_resumo
            print(f"\n>>> ALIMENTADOR {alim_id} CONCLUÍDO COM SUCESSO.")
        except Exception as erro:
            print(f"\nERRO AO PROCESSAR {alim_id}: {type(erro).__name__}: {erro}")
            import traceback
            traceback.print_exc()
            continue

    if SIMULAR:
        resultados_validos = {k: v for k, v in resumos.items() if v is not None}
        if len(resultados_validos) >= 2:
            comparar_alimentadores(resultados_validos)
        else:
            print("\nComparação não gerada: menos de dois alimentadores foram processados com sucesso.")

    print("\nProcessamento concluído.")
    if not SIMULAR:
        print(
            "\n  Próximo passo: valide a topologia e os comprimentos na planilha,\n"
            "  depois ajuste PAC_INICIAL_MANUAL (se necessário) e defina SIMULAR = True."
        )


if __name__ == "__main__":
    main()
