import os
import geopandas as gpd
import pandas as pd

# ============================================================
# CONFIGURAÇÕES
# ============================================================

GDB_PATH = r"C:\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"

PASTA_SAIDA = r"C:\Users\adm\Documents\Analise-Alimentador\alimentador_ic"

# Pode trocar futuramente por TAGUATINGA, SAMAMBAIA, GAMA etc.
REGIAO_ADMINISTRATIVA = "CEILÂNDIA"

# Limites atuais das Regiões Administrativas do Distrito Federal
URL_REGIOES_DF = (
    "https://www.geoservicos.ide.df.gov.br/arcgis/rest/services/"
    "Aplicacoes/HISTORICO_RA/MapServer/7/query"
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
        raise ValueError("A camada SSDMT não possui sistema de coordenadas definido.")

    print("Carregando os limites das Regiões Administrativas...")
    regioes = gpd.read_file(URL_REGIOES_DF)

    if "ra_nome" not in regioes.columns:
        raise ValueError("O serviço de limites não possui a coluna ra_nome.")

    regiao = regioes[
        regioes["ra_nome"].astype(str).str.upper().str.strip()
        == REGIAO_ADMINISTRATIVA.upper().strip()
    ].copy()

    if regiao.empty:
        nomes = sorted(regioes["ra_nome"].dropna().astype(str).unique())
        raise ValueError(
            f"Região '{REGIAO_ADMINISTRATIVA}' não encontrada.\n"
            f"Regiões disponíveis: {nomes}"
        )

    # EPSG 31983 permite calcular comprimentos em metros no DF.
    rede = rede.to_crs(epsg=31983)
    regiao = regiao.to_crs(epsg=31983)

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
    # ALIMENTADORES QUE PASSAM PELA REGIÃO ESCOLHIDA
    # --------------------------------------------------------

    dentro = rede[rede.geometry.intersects(limite)].copy()

    if dentro.empty:
        raise ValueError(
            f"Nenhum alimentador foi encontrado em {REGIAO_ADMINISTRATIVA}."
        )

    dentro["Comprimento_Dentro_km"] = (
        dentro.geometry.intersection(limite).length / 1000
    )

    alimentadores_regiao = (
        dentro.groupby("CTMT", as_index=False)
        .agg(
            Trechos_na_Regiao=("CTMT", "size"),
            Comprimento_Dentro_km=("Comprimento_Dentro_km", "sum")
        )
        .merge(todos, on="CTMT", how="left")
    )

    alimentadores_regiao["Percentual_Dentro_%"] = (
        100
        * alimentadores_regiao["Comprimento_Dentro_km"]
        / alimentadores_regiao["Comprimento_Total_km"]
    )

    alimentadores_regiao = alimentadores_regiao.sort_values(
        ["Comprimento_Dentro_km", "Percentual_Dentro_%"],
        ascending=[False, False]
    ).reset_index(drop=True)

    # --------------------------------------------------------
    # EXPORTAÇÃO
    # --------------------------------------------------------

    nome_regiao = (
        REGIAO_ADMINISTRATIVA.lower()
        .replace(" ", "_")
        .replace("â", "a")
        .replace("ã", "a")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )

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

    codigos = alimentadores_regiao["CTMT"].astype(str).tolist()

    print("\n============================================================")
    print(f"ALIMENTADORES ENCONTRADOS EM {REGIAO_ADMINISTRATIVA}")
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
        print(erro)
        print(erro)