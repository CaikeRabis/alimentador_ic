import os
import glob
import warnings

import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import py_dss_interface

# ============================================================
# CONFIGURAÇÕES
# ============================================================

GDB_PATH = r"C:\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
PASTA_SAIDA = r"C:\Users\caike\PycharmProjects\bdgdbrasilia"

ALIMENTADORES = ["NW11"]

TENSAO_MT_KV = 13.8
TENSAO_BT_KV = 0.38
HORARIO_ANALISE = 19

# Caso você conheça o PAC da saída da subestação, informe aqui.
# Com None, o programa tenta identificar automaticamente pela coluna DIST.
PAC_INICIAL_MANUAL = None

# Caso você queira testar um transformador específico, informe o COD_ID.
# Com None, o programa escolhe automaticamente o maior transformador conectado.
TRANSFORMADOR_ALVO_MANUAL = None

FP_BASE = 0.92
FP_BAIXO = 0.85

# Cenários gerais de carregamento aparente dos transformadores.
# 0.60 = 60% da potência nominal em kVA.
CENARIOS_REDE = [
    {"nome": "Base 60%", "carregamento_rede": 0.60, "fp": FP_BASE},
    {"nome": "Rede 80%", "carregamento_rede": 0.80, "fp": FP_BASE},
    {"nome": "Rede 100%", "carregamento_rede": 1.00, "fp": FP_BASE},
    {"nome": "Rede 120%", "carregamento_rede": 1.20, "fp": FP_BASE},
    {"nome": "Rede 160%", "carregamento_rede": 1.60, "fp": FP_BASE},
    {"nome": "Rede 160% - FP baixo", "carregamento_rede": 1.60, "fp": FP_BAIXO},
]

# Ensaio localizado exigido pela Task:
# cargas abaixo e acima da potência nominal de um transformador escolhido.
CARREGAMENTOS_TRAFO_ALVO = [0.50, 0.80, 1.00, 1.20, 1.50]

# Impedâncias aproximadas quando a BDGD não trouxer R1/X1.
USAR_IMPEDANCIA_CONSERVADORA = True
TRAFO_PERCENT_R = 1.2
TRAFO_XHL = 4.5

# Limites de tensão usados apenas para classificação visual.
LIMITES_TENSAO = {
    "critico": 0.90,
    "atencao": 0.93,
    "alerta": 0.97,
}

# ============================================================
# FUNÇÕES BÁSICAS
# ============================================================


def bus(valor):
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
    try:
        texto = str(valor).lower().replace("kv", "").replace(",", ".").strip()
        return float(texto)
    except (TypeError, ValueError):
        return np.nan


def obter_coluna_existente(df, candidatos):
    mapa = {str(c).lower(): c for c in df.columns}
    for candidato in candidatos:
        if candidato.lower() in mapa:
            return mapa[candidato.lower()]
    return None


def obter_numero_linha(row, candidatos):
    mapa = {str(c).lower(): c for c in row.index}
    for candidato in candidatos:
        real = mapa.get(candidato.lower())
        if real is None:
            continue
        valor = limpar_numero(row[real])
        if pd.notna(valor) and valor > 0:
            return valor
    return None


def comprimento_km_linha(row):
    valor = limpar_numero(row.get("Shape_Length", np.nan))
    if pd.isna(valor) or valor <= 0:
        valor = limpar_numero(row.get("COMP", np.nan))
    if pd.isna(valor) or valor <= 0:
        return 0.001
    return max(valor / 1000.0, 0.001)


def obter_impedancia_linha(row, length_km):
    candidatos_r1 = [
        "R1", "R1_OHM_KM", "R1_OHMKM", "R1_OHM_POR_KM",
        "RESISTENCIA", "RESIST", "R_OHM_KM", "R_OHMKM"
    ]
    candidatos_x1 = [
        "X1", "X1_OHM_KM", "X1_OHMKM", "X1_OHM_POR_KM",
        "REATANCIA", "REAT", "X_OHM_KM", "X_OHMKM"
    ]

    r1 = obter_numero_linha(row, candidatos_r1)
    x1 = obter_numero_linha(row, candidatos_x1)

    if r1 is not None and x1 is not None:
        return r1, x1, "real_bdgd"

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


# ============================================================
# TOPOLOGIA ELÉTRICA
# ============================================================


def chave_esta_fechada(row):
    """
    Tenta interpretar o estado da chave usando apenas campos claramente
    relacionados a estado/posição. Quando não consegue, assume fechada,
    mas o diagnóstico final informa quantas ficaram indefinidas.
    """
    candidatos = [
        "ESTADO", "STATUS", "SITCONT", "POS", "EST_OPER",
        "SITUACAO", "SITUAÇÃO"
    ]
    abertas = {"AB", "ABERTA", "ABERTO", "OPEN", "OFF", "DESLIGADA", "DESLIGADO"}
    fechadas = {"FE", "FECHADA", "FECHADO", "CLOSED", "ON", "LIGADA", "LIGADO"}

    for coluna in candidatos:
        if coluna not in row.index:
            continue
        valor = str(row[coluna]).strip().upper()
        if valor in abertas:
            return False, coluna, valor
        if valor in fechadas:
            return True, coluna, valor

    return True, None, None


def construir_grafo(ssdmt, unsemt):
    grafo = nx.Graph()
    elementos = {}
    chaves_abertas = 0
    chaves_estado_indefinido = 0

    for _, row in ssdmt.iterrows():
        b1 = bus(row.get("PAC_1"))
        b2 = bus(row.get("PAC_2"))
        if not b1 or not b2 or b1 == b2:
            continue

        codigo = clean_id(row.get("COD_ID"))
        comprimento = comprimento_km_linha(row)

        grafo.add_edge(
            b1,
            b2,
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

    for _, row in unsemt.iterrows():
        b1 = bus(row.get("PAC_1"))
        b2 = bus(row.get("PAC_2"))
        if not b1 or not b2 or b1 == b2:
            continue

        fechada, coluna_estado, valor_estado = chave_esta_fechada(row)

        if coluna_estado is None:
            chaves_estado_indefinido += 1

        if not fechada:
            chaves_abertas += 1
            continue

        codigo = clean_id(row.get("COD_ID"))
        comprimento = 0.001

        grafo.add_edge(
            b1,
            b2,
            weight=comprimento,
            tipo="chave",
            codigo=codigo,
        )

        elementos[f"LINE.SW_{codigo}".upper()] = {
            "b1": b1,
            "b2": b2,
            "comprimento_km": comprimento,
            "tipo": "chave",
        }

    diagnostico = {
        "chaves_abertas": chaves_abertas,
        "chaves_estado_indefinido": chaves_estado_indefinido,
        "nos": grafo.number_of_nodes(),
        "arestas": grafo.number_of_edges(),
        "componentes": nx.number_connected_components(grafo) if grafo.number_of_nodes() else 0,
    }

    return grafo, elementos, diagnostico


def escolher_pac_inicial(ssdmt, grafo, pac_manual=None):
    if grafo.number_of_nodes() == 0:
        raise ValueError("O grafo do alimentador está vazio.")

    if pac_manual:
        candidato = bus(pac_manual)
        if candidato not in grafo:
            raise ValueError(
                f"O PAC manual '{candidato}' não existe no grafo do alimentador."
            )
        return candidato, "manual"

    # Usa DIST quando houver valores numéricos úteis.
    if "DIST" in ssdmt.columns:
        distancias = pd.to_numeric(
            ssdmt["DIST"].astype(str).str.replace(",", ".", regex=False),
            errors="coerce",
        )

        validas = distancias.notna()
        if validas.any():
            menor = distancias[validas].min()
            linhas_inicio = ssdmt.loc[validas & (distancias == menor)]

            candidatos = []
            for _, row in linhas_inicio.iterrows():
                candidatos.extend([bus(row.get("PAC_1")), bus(row.get("PAC_2"))])

            candidatos = [c for c in candidatos if c in grafo]
            if candidatos:
                # Em empate, prioriza o nó com menor grau, típico de saída radial.
                candidato = sorted(
                    set(candidatos),
                    key=lambda no: (grafo.degree(no), no)
                )[0]
                return candidato, f"automático pela menor DIST ({menor})"

    # Fallback: usa uma extremidade do diâmetro ponderado do maior componente.
    maior_componente = max(nx.connected_components(grafo), key=len)
    subgrafo = grafo.subgraph(maior_componente)

    inicio = next(iter(subgrafo.nodes))
    dist1 = nx.single_source_dijkstra_path_length(subgrafo, inicio, weight="weight")
    ponta1 = max(dist1, key=dist1.get)
    dist2 = nx.single_source_dijkstra_path_length(subgrafo, ponta1, weight="weight")
    ponta2 = max(dist2, key=dist2.get)

    # Escolhe como origem a extremidade de menor grau.
    if subgrafo.degree(ponta1) <= subgrafo.degree(ponta2):
        return ponta1, "fallback: extremidade do diâmetro do maior componente"
    return ponta2, "fallback: extremidade do diâmetro do maior componente"


def analisar_topologia(grafo, pac_inicial):
    if pac_inicial not in grafo:
        raise ValueError(f"PAC inicial {pac_inicial} ausente no grafo.")

    componente = nx.node_connected_component(grafo, pac_inicial)
    subgrafo = grafo.subgraph(componente).copy()

    distancias = nx.single_source_dijkstra_path_length(
        subgrafo,
        pac_inicial,
        weight="weight",
    )

    ponta = max(distancias, key=distancias.get)

    return {
        "subgrafo": subgrafo,
        "distancias": distancias,
        "ponta": ponta,
        "distancia_ponta_km": distancias[ponta],
        "barras_alcancadas": len(componente),
        "barras_totais": grafo.number_of_nodes(),
        "arestas_alcancadas": subgrafo.number_of_edges(),
    }


# ============================================================
# TRANSFORMADOR-ALVO
# ============================================================


def selecionar_transformador_alvo(untrmt, barras_energizadas, codigo_manual=None):
    dados = untrmt.copy()
    dados["BUS_MT"] = dados["PAC_1"].apply(bus)
    dados["POT_NOM_NUM"] = dados["POT_NOM"].apply(limpar_numero)

    dados = dados[
        dados["BUS_MT"].isin(barras_energizadas)
        & dados["POT_NOM_NUM"].notna()
        & (dados["POT_NOM_NUM"] > 0)
    ].copy()

    if dados.empty:
        return None

    if codigo_manual:
        codigo_manual_limpo = str(codigo_manual).strip()
        alvo = dados[
            dados["COD_ID"].astype(str).str.strip() == codigo_manual_limpo
        ]
        if alvo.empty:
            raise ValueError(
                f"O transformador manual '{codigo_manual_limpo}' não foi encontrado "
                "ou está fora do componente energizado."
            )
        return alvo.iloc[0]

    return dados.sort_values("POT_NOM_NUM", ascending=False).iloc[0]


# ============================================================
# LEITURA DOS CSVs DO OPENDSS
# ============================================================


def encontrar_exportacao(pasta, alimentador, sufixo):
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


def analisar_tensoes(df_v, distancias):
    df = df_v.copy()
    df.columns = df.columns.str.strip()

    col_bus = coluna_bus(df)
    if col_bus is None:
        raise ValueError("A exportação de tensões não possui coluna de barra.")

    col_base = obter_coluna_existente(df, ["BasekV", "Base kV", "BASEKV"])
    if col_base is not None:
        base_num = pd.to_numeric(df[col_base], errors="coerce")
        df = df[base_num.between(7.0, 14.5)].copy()

    colunas_pu = [
        c for c in df.columns
        if str(c).strip().lower() in {"pu1", "pu2", "pu3"}
    ]

    if len(colunas_pu) < 1:
        raise ValueError("A exportação de tensões não possui colunas pu1/pu2/pu3.")

    for c in colunas_pu:
        df[c] = pd.to_numeric(df[c], errors="coerce").replace(0, np.nan)

    df["Barra"] = df[col_bus].apply(bus)
    df["Tensao_pu"] = df[colunas_pu].mean(axis=1)
    df["Distancia_km"] = df["Barra"].map(distancias)
    df = df[df["Distancia_km"].notna()].copy()
    df = df.sort_values("Distancia_km").reset_index(drop=True)

    return df[["Barra", "Distancia_km", "Tensao_pu"]]


def colunas_fases_por_prefixo(df, prefixo):
    saida = []
    for c in df.columns:
        nome = str(c).strip().upper()
        if nome.startswith(prefixo.upper()):
            numero = pd.to_numeric(df[c], errors="coerce")
            if numero.notna().any():
                saida.append(c)
    return saida


def analisar_correntes(df_i, elementos, distancias):
    df = df_i.copy()
    df.columns = df.columns.str.strip()

    col_elem = coluna_elemento(df)
    if col_elem is None:
        raise ValueError("A exportação de correntes não possui coluna Element.")

    df["Elemento"] = df[col_elem].apply(normalizar_elemento)
    df = df[df["Elemento"].str.startswith("LINE.", na=False)].copy()

    cols_i = colunas_fases_por_prefixo(df, "I")
    if not cols_i:
        raise ValueError("Nenhuma coluna de corrente foi identificada.")

    for c in cols_i:
        df[c] = pd.to_numeric(df[c], errors="coerce").abs()

    df["Corrente_A"] = df[cols_i].max(axis=1)
    df["Distancia_km"] = df["Elemento"].map(
        lambda e: max(
            distancias.get(elementos.get(e, {}).get("b1"), np.nan),
            distancias.get(elementos.get(e, {}).get("b2"), np.nan),
        ) if e in elementos else np.nan
    )
    df = df[df["Distancia_km"].notna()].copy()
    return df[["Elemento", "Distancia_km", "Corrente_A"]].sort_values("Distancia_km")


def analisar_potencias(df_p, elementos, distancias):
    df = df_p.copy()
    df.columns = df.columns.str.strip()

    col_elem = coluna_elemento(df)
    if col_elem is None:
        raise ValueError("A exportação de potências não possui coluna Element.")

    df["Elemento"] = df[col_elem].apply(normalizar_elemento)
    df = df[df["Elemento"].str.startswith("LINE.", na=False)].copy()

    cols_p = [c for c in df.columns if str(c).strip().upper().startswith("P")]
    cols_q = [c for c in df.columns if str(c).strip().upper().startswith("Q")]

    cols_p = [c for c in cols_p if pd.to_numeric(df[c], errors="coerce").notna().any()]
    cols_q = [c for c in cols_q if pd.to_numeric(df[c], errors="coerce").notna().any()]

    if not cols_p or not cols_q:
        raise ValueError("Não foi possível identificar colunas P e Q.")

    for c in cols_p + cols_q:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Export Powers normalmente traz fases/terminais. Usa o maior módulo por elemento.
    df["P_kW"] = df[cols_p].sum(axis=1).abs()
    df["Q_kVAr"] = df[cols_q].sum(axis=1).abs()
    df["S_kVA"] = np.sqrt(df["P_kW"] ** 2 + df["Q_kVAr"] ** 2)

    df["Distancia_km"] = df["Elemento"].map(
        lambda e: max(
            distancias.get(elementos.get(e, {}).get("b1"), np.nan),
            distancias.get(elementos.get(e, {}).get("b2"), np.nan),
        ) if e in elementos else np.nan
    )

    df = df[df["Distancia_km"].notna()].copy()
    return df[
        ["Elemento", "Distancia_km", "P_kW", "Q_kVAr", "S_kVA"]
    ].sort_values("Distancia_km")


# ============================================================
# SIMULAÇÃO
# ============================================================


def montar_cenarios(transformador_alvo):
    cenarios = list(CENARIOS_REDE)

    if transformador_alvo is not None:
        for carregamento in CARREGAMENTOS_TRAFO_ALVO:
            cenarios.append({
                "nome": f"Trafo alvo {carregamento * 100:.0f}%",
                "carregamento_rede": 0.60,
                "carregamento_trafo_alvo": carregamento,
                "fp": FP_BASE,
            })

    return cenarios


def simular_alimentador(alim_id, ssdmt, untrmt, unsemt):
    grafo, elementos, diag_grafo = construir_grafo(ssdmt, unsemt)

    pac_inicial, metodo_origem = escolher_pac_inicial(
        ssdmt,
        grafo,
        PAC_INICIAL_MANUAL,
    )

    topo = analisar_topologia(grafo, pac_inicial)
    subgrafo = topo["subgrafo"]
    distancias = topo["distancias"]
    barras_energizadas = set(subgrafo.nodes)

    trafo_alvo = selecionar_transformador_alvo(
        untrmt,
        barras_energizadas,
        TRANSFORMADOR_ALVO_MANUAL,
    )

    print("\n============================================================")
    print(f"DIAGNÓSTICO TOPOLOGIA - {alim_id}")
    print("============================================================")
    print(f"PAC inicial: {pac_inicial}")
    print(f"Método de escolha: {metodo_origem}")
    print(f"Barras totais no grafo: {topo['barras_totais']}")
    print(f"Barras energizadas/alcançadas: {topo['barras_alcancadas']}")
    print(f"Arestas energizadas: {topo['arestas_alcancadas']}")
    print(f"Componentes conectados: {diag_grafo['componentes']}")
    print(f"Chaves abertas identificadas: {diag_grafo['chaves_abertas']}")
    print(
        "Chaves com estado indefinido, assumidas fechadas: "
        f"{diag_grafo['chaves_estado_indefinido']}"
    )
    print(f"Ponta elétrica: {topo['ponta']}")
    print(f"Distância elétrica até a ponta: {topo['distancia_ponta_km']:.3f} km")

    if trafo_alvo is not None:
        print("\nTransformador-alvo:")
        print(f"COD_ID: {trafo_alvo['COD_ID']}")
        print(f"PAC MT: {trafo_alvo['BUS_MT']}")
        print(f"Potência nominal: {trafo_alvo['POT_NOM_NUM']:.2f} kVA")
    else:
        print("\nAviso: nenhum transformador-alvo válido foi encontrado.")

    cenarios = montar_cenarios(trafo_alvo)

    resumo = []
    detalhes = {}

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

    for cenario in cenarios:
        nome = cenario["nome"]
        carregamento_rede = cenario["carregamento_rede"]
        carregamento_trafo_alvo = cenario.get("carregamento_trafo_alvo")
        fp = cenario["fp"]

        print(
            f"\nCenário: {nome} | Rede: {carregamento_rede * 100:.0f}% "
            f"| FP: {fp:.2f}"
        )

        dss = py_dss_interface.DSS()
        dss.text("Clear")
        dss.text(
            f"New Circuit.{alim_id} "
            f"bus1={pac_inicial} basekv={TENSAO_MT_KV} phases=3 pu=1.0"
        )

        imp_real = 0
        imp_estimada = 0

        for _, row in linhas_energizadas.iterrows():
            b1 = bus(row["PAC_1"])
            b2 = bus(row["PAC_2"])
            cod = clean_id(row["COD_ID"])
            length = comprimento_km_linha(row)
            r1, x1, origem_imp = obter_impedancia_linha(row, length)

            if origem_imp == "real_bdgd":
                imp_real += 1
            else:
                imp_estimada += 1

            dss.text(
                f"New Line.L_{cod} "
                f"bus1={b1} bus2={b2} phases=3 "
                f"length={length:.6f} units=km "
                f"r1={r1:.6f} x1={x1:.6f} c1=0"
            )

        for _, row in chaves_energizadas.iterrows():
            fechada, _, _ = chave_esta_fechada(row)
            if not fechada:
                continue

            b1 = bus(row["PAC_1"])
            b2 = bus(row["PAC_2"])
            cod = clean_id(row["COD_ID"])

            dss.text(
                f"New Line.SW_{cod} "
                f"bus1={b1} bus2={b2} phases=3 "
                f"length=0.001 units=km r1=0.001 x1=0.001 c1=0"
            )

        potencia_total_kw = 0.0
        potencia_total_kva = 0.0
        trafos_modelados = 0

        for _, row in trafos_energizados.iterrows():
            bus_mt = bus(row["PAC_1"])
            cod_original = str(row["COD_ID"]).strip()
            cod = clean_id(cod_original)
            pot_kva = limpar_numero(row["POT_NOM"])

            if not bus_mt or pd.isna(pot_kva) or pot_kva <= 0:
                continue

            carregamento = carregamento_rede

            if (
                trafo_alvo is not None
                and carregamento_trafo_alvo is not None
                and cod_original == str(trafo_alvo["COD_ID"]).strip()
            ):
                carregamento = carregamento_trafo_alvo

            carga_kva = pot_kva * carregamento
            carga_kw = carga_kva * fp
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

            potencia_total_kw += carga_kw
            potencia_total_kva += carga_kva
            trafos_modelados += 1

        dss.text(f"Set VoltageBases=[{TENSAO_MT_KV}, {TENSAO_BT_KV}]")
        dss.text("CalcVoltageBases")
        dss.text("Set mode=snapshot")
        dss.text("Solve")

        convergiu = bool(dss.solution.converged)

        if not convergiu:
            warnings.warn(f"O cenário '{nome}' do alimentador {alim_id} não convergiu.")

        losses = dss.circuit.losses
        perda_kw = losses[0] / 1000.0
        perda_kvar = losses[1] / 1000.0

        eficiencia = (
            100.0 * (1.0 - perda_kw / potencia_total_kw)
            if potencia_total_kw > 0 else np.nan
        )

        os.makedirs(PASTA_SAIDA, exist_ok=True)
        dss.text(f'cd "{PASTA_SAIDA}"')

        dss.text("Export Voltages")
        arq_v = encontrar_exportacao(PASTA_SAIDA, alim_id, "VOLTAGES")
        if arq_v is None:
            raise FileNotFoundError("CSV de tensões não encontrado.")
        tensoes = analisar_tensoes(pd.read_csv(arq_v), distancias)

        dss.text("Export Currents")
        arq_i = encontrar_exportacao(PASTA_SAIDA, alim_id, "CURRENTS")
        if arq_i is None:
            raise FileNotFoundError("CSV de correntes não encontrado.")
        correntes = analisar_correntes(pd.read_csv(arq_i), elementos, distancias)

        dss.text("Export Powers")
        arq_p = encontrar_exportacao(PASTA_SAIDA, alim_id, "POWERS")
        potencias = pd.DataFrame()
        if arq_p is not None:
            try:
                potencias = analisar_potencias(
                    pd.read_csv(arq_p),
                    elementos,
                    distancias,
                )
            except Exception as erro:
                print(f"Aviso ao analisar potências: {erro}")

        detalhes[nome] = {
            "tensoes": tensoes,
            "correntes": correntes,
            "potencias": potencias,
        }

        tensao_min = tensoes["Tensao_pu"].min()
        tensao_media = tensoes["Tensao_pu"].mean()
        corrente_max = correntes["Corrente_A"].max() if not correntes.empty else np.nan

        resumo.append({
            "Alimentador": alim_id,
            "Cenario": nome,
            "Convergiu": convergiu,
            "Horario_referencia": HORARIO_ANALISE,
            "PAC_Inicial": pac_inicial,
            "Metodo_Origem": metodo_origem,
            "Ponta_Eletrica": topo["ponta"],
            "Distancia_Ponta_km": topo["distancia_ponta_km"],
            "Barras_Totais_Grafo": topo["barras_totais"],
            "Barras_Energizadas": topo["barras_alcancadas"],
            "Carregamento_Rede_%": carregamento_rede * 100,
            "Fator_Potencia": fp,
            "Trafo_Alvo_COD_ID": (
                str(trafo_alvo["COD_ID"]) if trafo_alvo is not None else None
            ),
            "Trafo_Alvo_kVA": (
                float(trafo_alvo["POT_NOM_NUM"]) if trafo_alvo is not None else np.nan
            ),
            "Carregamento_Trafo_Alvo_%": (
                carregamento_trafo_alvo * 100
                if carregamento_trafo_alvo is not None else np.nan
            ),
            "Transformadores_Modelados": trafos_modelados,
            "Potencia_Carga_Total_kW": potencia_total_kw,
            "Potencia_Carga_Total_kVA": potencia_total_kva,
            "Tensao_Minima_pu": tensao_min,
            "Tensao_Media_pu": tensao_media,
            "Corrente_Maxima_A": corrente_max,
            "Perda_Ativa_kW": perda_kw,
            "Perda_Reativa_kVAr": perda_kvar,
            "Eficiencia_%": eficiencia,
            "Barras_Abaixo_0_97": int((tensoes["Tensao_pu"] < 0.97).sum()),
            "Barras_Abaixo_0_93": int((tensoes["Tensao_pu"] < 0.93).sum()),
            "Barras_Abaixo_0_90": int((tensoes["Tensao_pu"] < 0.90).sum()),
            "Linhas_Impedancia_Real_BDGD": imp_real,
            "Linhas_Impedancia_Estimada": imp_estimada,
        })

    return pd.DataFrame(resumo), detalhes, topo, trafo_alvo


# ============================================================
# GRÁFICOS E EXPORTAÇÃO
# ============================================================


def gerar_graficos(alim_id, resumo, detalhes):
    if resumo.empty:
        return

    plt.figure(figsize=(14, 7))
    plt.plot(resumo["Cenario"], resumo["Tensao_Minima_pu"], marker="o")
    plt.axhline(0.97, linestyle="--", label="0,97 p.u.")
    plt.axhline(0.93, linestyle="--", label="0,93 p.u.")
    plt.axhline(0.90, linestyle="--", label="0,90 p.u.")
    plt.title(f"Tensão mínima por cenário - {alim_id}")
    plt.ylabel("Tensão mínima (p.u.)")
    plt.xticks(rotation=35, ha="right")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(14, 7))
    plt.plot(resumo["Cenario"], resumo["Corrente_Maxima_A"], marker="o")
    plt.title(f"Corrente máxima por cenário - {alim_id}")
    plt.ylabel("Corrente máxima (A)")
    plt.xticks(rotation=35, ha="right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(14, 7))
    plt.plot(resumo["Cenario"], resumo["Perda_Ativa_kW"], marker="o")
    plt.title(f"Perdas ativas por cenário - {alim_id}")
    plt.ylabel("Perdas ativas (kW)")
    plt.xticks(rotation=35, ha="right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

    cenarios_perfil = [
        c for c in [
            "Base 60%",
            "Rede 100%",
            "Rede 160%",
            "Rede 160% - FP baixo",
            "Trafo alvo 100%",
            "Trafo alvo 150%",
        ] if c in detalhes
    ]

    plt.figure(figsize=(14, 7))
    for nome in cenarios_perfil:
        dados = detalhes[nome]["tensoes"]
        plt.plot(dados["Distancia_km"], dados["Tensao_pu"], label=nome)
    plt.axhline(0.97, linestyle="--")
    plt.axhline(0.93, linestyle="--")
    plt.axhline(0.90, linestyle="--")
    plt.title(f"Perfil de tensão ao longo do alimentador - {alim_id}")
    plt.xlabel("Distância elétrica acumulada (km)")
    plt.ylabel("Tensão (p.u.)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(14, 7))
    for nome in cenarios_perfil:
        dados = detalhes[nome]["correntes"]
        if not dados.empty:
            plt.plot(dados["Distancia_km"], dados["Corrente_A"], label=nome)
    plt.title(f"Corrente ao longo do alimentador - {alim_id}")
    plt.xlabel("Distância elétrica acumulada (km)")
    plt.ylabel("Corrente máxima por elemento (A)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()

    plt.figure(figsize=(14, 7))
    for nome in cenarios_perfil:
        dados = detalhes[nome]["potencias"]
        if not dados.empty:
            plt.plot(dados["Distancia_km"], dados["S_kVA"], label=nome)
    plt.title(f"Potência aparente ao longo do alimentador - {alim_id}")
    plt.xlabel("Distância elétrica acumulada (km)")
    plt.ylabel("Potência aparente (kVA)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.show()


def exportar_resultados(alim_id, resumo, detalhes):
    arquivo = os.path.join(
        PASTA_SAIDA,
        f"analise_eletrica_{alim_id}_corrigida.xlsx",
    )

    with pd.ExcelWriter(arquivo) as writer:
        resumo.to_excel(writer, sheet_name="Resumo", index=False)

        for nome, grupos in detalhes.items():
            nome_base = clean_id(nome)[:18]

            grupos["tensoes"].to_excel(
                writer,
                sheet_name=f"V_{nome_base}"[:31],
                index=False,
            )

            grupos["correntes"].to_excel(
                writer,
                sheet_name=f"I_{nome_base}"[:31],
                index=False,
            )

            if not grupos["potencias"].empty:
                grupos["potencias"].to_excel(
                    writer,
                    sheet_name=f"S_{nome_base}"[:31],
                    index=False,
                )

    print(f"\nResultados exportados para:\n{arquivo}")


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================


def main():
    os.makedirs(PASTA_SAIDA, exist_ok=True)

    filtro = " OR ".join([f"CTMT = '{a}'" for a in ALIMENTADORES])

    ssdmt_total = gpd.read_file(GDB_PATH, layer="SSDMT", where=filtro)
    untrmt_total = gpd.read_file(GDB_PATH, layer="UNTRMT", where=filtro)
    unsemt_total = gpd.read_file(GDB_PATH, layer="UNSEMT", where=filtro)

    print("\n=== DADOS CARREGADOS ===")
    print("Trechos MT:", len(ssdmt_total))
    print("Transformadores:", len(untrmt_total))
    print("Chaves:", len(unsemt_total))
    print(ssdmt_total["CTMT"].value_counts())
    print("========================")

    resumos = []

    for alim_id in ALIMENTADORES:
        ssdmt = ssdmt_total[ssdmt_total["CTMT"] == alim_id].copy()
        untrmt = untrmt_total[untrmt_total["CTMT"] == alim_id].copy()
        unsemt = unsemt_total[unsemt_total["CTMT"] == alim_id].copy()

        if ssdmt.empty:
            print(f"\n{alim_id} ignorado: sem trechos SSDMT.")
            continue

        resumo, detalhes, topo, trafo_alvo = simular_alimentador(
            alim_id,
            ssdmt,
            untrmt,
            unsemt,
        )

        exportar_resultados(alim_id, resumo, detalhes)
        gerar_graficos(alim_id, resumo, detalhes)
        resumos.append(resumo)

    if resumos:
        consolidado = pd.concat(resumos, ignore_index=True)
        caminho = os.path.join(
            PASTA_SAIDA,
            "resumo_consolidado_alimentadores_corrigido.xlsx",
        )
        consolidado.to_excel(caminho, index=False)
        print(f"\nResumo consolidado exportado para:\n{caminho}")

    print("\nAnálise elétrica corrigida concluída.")


if __name__ == "__main__":
    main()