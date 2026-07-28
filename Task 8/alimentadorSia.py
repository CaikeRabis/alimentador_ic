import os
import geopandas as gpd
import pandas as pd

# ============================================================
# CONFIGURAÇÕES
# ============================================================

GDB_PATH = r"C:\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"

PASTA_SAIDA = r"C:\Users\caike\PycharmProjects\bdgdbrasilia"

# SIA = Setor de Indústria e Abastecimento
REGIAO_ADMINISTRATIVA = "SIA"

# Limites oficiais atuais das Regiões Administrativas do DF
URL_REGIOES_DF = (
    "https://www.geoservicos.ide.df.gov.br/arcgis/rest/services/"
    "Publico/LIMITES/FeatureServer/1/query"
    "?where=1%3D1"
    "&outFields=*"
    "&returnGeometry=true"
    "&f=geojson"
)


# ============================================================
# EXECUÇÃO
# ============================================================

def main():
    os.makedirs(PASTA_SAIDA, exist_ok=True)

    print("Lendo a camada SSDMT da BDGD...")
    rede = gpd.read_file(GDB_PATH, layer="SSDMT")

    if rede.empty:
        raise ValueError("A camada SSDMT está vazia.")

    if "CTMT" not in rede.columns:
        raise ValueError("A camada SSDMT não possui a coluna CTMT.")

    if rede.crs is None:
        raise ValueError(
            "A camada SSDMT não possui sistema de coordenadas definido."
        )

    print("Carregando os limites das Regiões Administrativas...")
    regioes = gpd.read_file(URL_REGIOES_DF)

    if "ra_nome" not in regioes.columns:
        raise ValueError(
            "O serviço de limites não possui a coluna ra_nome."
        )

    regioes["_nome_normalizado"] = (
        regioes["ra_nome"]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    regiao = regioes[
        regioes["_nome_normalizado"]
        == REGIAO_ADMINISTRATIVA.upper().strip()
    ].copy()

    if regiao.empty:
        nomes = sorted(
            regioes["ra_nome"]
            .dropna()
            .astype(str)
            .unique()
        )

        raise ValueError(
            f"Região '{REGIAO_ADMINISTRATIVA}' não encontrada.\n"
            f"Regiões disponíveis: {nomes}"
        )

    # CRS métrico adequado ao Distrito Federal
    rede = rede.to_crs(epsg=31983)
    regiao = regiao.to_crs(epsg=31983)

    # Compatível com versões novas e antigas do GeoPandas
    try:
        limite = regiao.geometry.union_all()
    except AttributeError:
        limite = regiao.geometry.unary_union

    # --------------------------------------------------------
    # TODOS OS ALIMENTADORES DO ARQUIVO
    # --------------------------------------------------------

    rede["CTMT"] = rede["CTMT"].astype(str).str.strip()
    rede["Comprimento_Total_km"] = rede.geometry.length / 1000

    todos = (
        rede.groupby("CTMT", as_index=False)
        .agg(
            Trechos_Totais=("CTMT", "size"),
            Comprimento_Total_km=("Comprimento_Total_km", "sum")
        )
        .sort_values("CTMT")
        .reset_index(drop=True)
    )

    # --------------------------------------------------------
    # ALIMENTADORES QUE PASSAM PELO SIA
    # --------------------------------------------------------

    dentro = rede[rede.geometry.intersects(limite)].copy()

    if dentro.empty:
        raise ValueError(
            f"Nenhum alimentador foi encontrado em "
            f"{REGIAO_ADMINISTRATIVA}."
        )

    dentro["Comprimento_Dentro_km"] = (
        dentro.geometry.intersection(limite).length / 1000
    )

    # Remove contatos pontuais ou geometrias sem comprimento útil
    dentro = dentro[
        dentro["Comprimento_Dentro_km"] > 0
    ].copy()

    alimentadores_regiao = (
        dentro.groupby("CTMT", as_index=False)
        .agg(
            Trechos_na_Regiao=("CTMT", "size"),
            Comprimento_Dentro_km=(
                "Comprimento_Dentro_km",
                "sum"
            )
        )
        .merge(todos, on="CTMT", how="left")
    )

    alimentadores_regiao["Percentual_Dentro_%"] = (
        100
        * alimentadores_regiao["Comprimento_Dentro_km"]
        / alimentadores_regiao["Comprimento_Total_km"]
    )

    alimentadores_regiao = alimentadores_regiao.sort_values(
        [
            "Comprimento_Dentro_km",
            "Percentual_Dentro_%"
        ],
        ascending=[False, False]
    ).reset_index(drop=True)

    # --------------------------------------------------------
    # EXPORTAÇÃO
    # --------------------------------------------------------

    nome_regiao = REGIAO_ADMINISTRATIVA.lower().replace(" ", "_")

    arquivo_excel = os.path.join(
        PASTA_SAIDA,
        f"alimentadores_{nome_regiao}.xlsx"
    )

    with pd.ExcelWriter(arquivo_excel) as writer:
        alimentadores_regiao.to_excel(
            writer,
            sheet_name="Alimentadores_Regiao",
            index=False
        )

        todos.to_excel(
            writer,
            sheet_name="Todos_Alimentadores_DF",
            index=False
        )

    codigos = (
        alimentadores_regiao["CTMT"]
        .astype(str)
        .tolist()
    )

    print("\n============================================================")
    print(
        f"ALIMENTADORES ENCONTRADOS EM "
        f"{REGIAO_ADMINISTRATIVA}"
    )
    print("============================================================")

    print(
        alimentadores_regiao[
            [
                "CTMT",
                "Comprimento_Dentro_km",
                "Percentual_Dentro_%",
                "Trechos_na_Regiao"
            ]
        ].to_string(
            index=False,
            formatters={
                "Comprimento_Dentro_km": "{:.3f}".format,
                "Percentual_Dentro_%": "{:.2f}".format
            }
        )
    )

    print("\nCopie esta linha para o código principal:\n")
    print(f"alimentadores = {codigos}")

    print("\nPlanilha criada em:")
    print(arquivo_excel)


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print("\nERRO AO EXECUTAR:")
        print(type(erro).__name__, "-", erro)