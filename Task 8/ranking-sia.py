import os
import geopandas as gpd
import pandas as pd
import numpy as np

# ============================================================
# CONFIGURAÇÕES
# ============================================================

GDB_PATH = r"C:\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"

PASTA_SAIDA = r"C:\Users\adm\Documents\Analise-Alimentador\alimentador_ic"

ARQUIVO_ALIMENTADORES_SIA = os.path.join(
    PASTA_SAIDA,
    "alimentadores_sia.xlsx"
)

ARQUIVO_SAIDA_XLSX = os.path.join(
    PASTA_SAIDA,
    "ranking_alimentadores_industriais_sia.xlsx"
)

ARQUIVO_SAIDA_CSV = os.path.join(
    PASTA_SAIDA,
    "ranking_alimentadores_industriais_sia.csv"
)


# ============================================================
# FUNÇÕES
# ============================================================

def limpar_numero(valor):
    try:
        texto = (
            str(valor)
            .lower()
            .replace("kva", "")
            .replace("kv", "")
            .replace(",", ".")
            .strip()
        )
        return float(texto)
    except (TypeError, ValueError):
        return np.nan


# ============================================================
# PROGRAMA PRINCIPAL
# ============================================================

def main():
    os.makedirs(PASTA_SAIDA, exist_ok=True)

    if not os.path.exists(ARQUIVO_ALIMENTADORES_SIA):
        raise FileNotFoundError(
            "A planilha alimentadores_sia.xlsx não foi encontrada em:\n"
            f"{ARQUIVO_ALIMENTADORES_SIA}"
        )

    # --------------------------------------------------------
    # ALIMENTADORES LOCALIZADOS NO SIA
    # --------------------------------------------------------

    alimentadores_sia = pd.read_excel(
        ARQUIVO_ALIMENTADORES_SIA,
        sheet_name="Alimentadores_Regiao"
    )

    if "CTMT" not in alimentadores_sia.columns:
        raise ValueError(
            "A planilha alimentadores_sia.xlsx não possui a coluna CTMT."
        )

    alimentadores_sia["CTMT"] = (
        alimentadores_sia["CTMT"]
        .astype(str)
        .str.strip()
    )

    codigos_sia = (
        alimentadores_sia["CTMT"]
        .dropna()
        .unique()
        .tolist()
    )

    print(f"Quantidade de alimentadores do SIA: {len(codigos_sia)}")

    # --------------------------------------------------------
    # LEITURA DOS TRANSFORMADORES
    # --------------------------------------------------------

    filtro = " OR ".join(
        [f"CTMT = '{codigo}'" for codigo in codigos_sia]
    )

    print("Lendo transformadores da camada UNTRMT...")

    untrmt = gpd.read_file(
        GDB_PATH,
        layer="UNTRMT",
        where=filtro
    )

    if untrmt.empty:
        raise ValueError(
            "Nenhum transformador foi encontrado para os alimentadores do SIA."
        )

    colunas_obrigatorias = ["CTMT", "COD_ID", "POT_NOM", "PAC_1"]

    faltantes = [
        coluna
        for coluna in colunas_obrigatorias
        if coluna not in untrmt.columns
    ]

    if faltantes:
        raise ValueError(
            f"Colunas ausentes na UNTRMT: {faltantes}"
        )

    untrmt["CTMT"] = (
        untrmt["CTMT"]
        .astype(str)
        .str.strip()
    )

    untrmt["POT_NOM_NUM"] = (
        untrmt["POT_NOM"]
        .apply(limpar_numero)
    )

    untrmt_validos = untrmt[
        untrmt["POT_NOM_NUM"].notna()
        & (untrmt["POT_NOM_NUM"] > 0)
    ].copy()

    if untrmt_validos.empty:
        raise ValueError(
            "Nenhum transformador possui potência nominal válida."
        )

    # --------------------------------------------------------
    # INDICADORES POR ALIMENTADOR
    # --------------------------------------------------------

    resumo = (
        untrmt_validos
        .groupby("CTMT", as_index=False)
        .agg(
            Quantidade_Transformadores=("COD_ID", "count"),
            Potencia_Total_kVA=("POT_NOM_NUM", "sum"),
            Potencia_Media_kVA=("POT_NOM_NUM", "mean"),
            Potencia_Mediana_kVA=("POT_NOM_NUM", "median"),
            Menor_Transformador_kVA=("POT_NOM_NUM", "min"),
            Maior_Transformador_kVA=("POT_NOM_NUM", "max")
        )
    )

    contagens_faixas = (
        untrmt_validos
        .groupby("CTMT")
        .agg(
            Trafos_75_kVA_ou_mais=(
                "POT_NOM_NUM",
                lambda serie: int((serie >= 75).sum())
            ),
            Trafos_150_kVA_ou_mais=(
                "POT_NOM_NUM",
                lambda serie: int((serie >= 150).sum())
            ),
            Trafos_300_kVA_ou_mais=(
                "POT_NOM_NUM",
                lambda serie: int((serie >= 300).sum())
            ),
            Trafos_500_kVA_ou_mais=(
                "POT_NOM_NUM",
                lambda serie: int((serie >= 500).sum())
            ),
            Trafos_750_kVA_ou_mais=(
                "POT_NOM_NUM",
                lambda serie: int((serie >= 750).sum())
            ),
            Trafos_1000_kVA_ou_mais=(
                "POT_NOM_NUM",
                lambda serie: int((serie >= 1000).sum())
            )
        )
        .reset_index()
    )

    ranking = resumo.merge(
        contagens_faixas,
        on="CTMT",
        how="left"
    )

    ranking = ranking.merge(
        alimentadores_sia,
        on="CTMT",
        how="left"
    )

    # Índice somente comparativo, não oficial.
    ranking["Indice_Industrial_Comparativo"] = (
        ranking["Potencia_Total_kVA"]
        + 2 * ranking["Maior_Transformador_kVA"]
        + 250 * ranking["Trafos_300_kVA_ou_mais"]
        + 500 * ranking["Trafos_500_kVA_ou_mais"]
        + 750 * ranking["Trafos_750_kVA_ou_mais"]
        + 1000 * ranking["Trafos_1000_kVA_ou_mais"]
    )

    ranking = ranking.sort_values(
        by=[
            "Indice_Industrial_Comparativo",
            "Potencia_Total_kVA",
            "Maior_Transformador_kVA"
        ],
        ascending=False
    ).reset_index(drop=True)

    ranking.insert(
        0,
        "Posicao_Ranking",
        range(1, len(ranking) + 1)
    )

    # --------------------------------------------------------
    # LISTA DETALHADA DOS TRANSFORMADORES
    # --------------------------------------------------------

    colunas_detalhes = [
        coluna
        for coluna in [
            "CTMT",
            "COD_ID",
            "PAC_1",
            "PAC_2",
            "POT_NOM",
            "POT_NOM_NUM",
            "SUB",
            "CONJ",
            "ARE_LOC",
            "geometry"
        ]
        if coluna in untrmt_validos.columns
    ]

    detalhes = untrmt_validos[colunas_detalhes].copy()

    if "geometry" in detalhes.columns:
        detalhes["Longitude_Centroide"] = (
            detalhes.geometry.centroid.x
        )
        detalhes["Latitude_Centroide"] = (
            detalhes.geometry.centroid.y
        )
        detalhes = pd.DataFrame(
            detalhes.drop(columns="geometry")
        )

    detalhes = detalhes.sort_values(
        by=["CTMT", "POT_NOM_NUM"],
        ascending=[True, False]
    ).reset_index(drop=True)

    # --------------------------------------------------------
    # MAIORES TRANSFORMADORES
    # --------------------------------------------------------

    maiores_transformadores = (
        detalhes
        .sort_values("POT_NOM_NUM", ascending=False)
        .reset_index(drop=True)
    )

    maiores_transformadores.insert(
        0,
        "Posicao_Geral",
        range(1, len(maiores_transformadores) + 1)
    )

    # --------------------------------------------------------
    # EXPORTAÇÃO XLSX E CSV
    # --------------------------------------------------------

    ranking.to_csv(
        ARQUIVO_SAIDA_CSV,
        index=False,
        encoding="utf-8-sig",
        sep=";"
    )

    with pd.ExcelWriter(
        ARQUIVO_SAIDA_XLSX,
        engine="openpyxl"
    ) as writer:
        ranking.to_excel(
            writer,
            sheet_name="Ranking_Alimentadores",
            index=False
        )

        detalhes.to_excel(
            writer,
            sheet_name="Todos_Transformadores",
            index=False
        )

        maiores_transformadores.to_excel(
            writer,
            sheet_name="Maiores_Transformadores",
            index=False
        )

        alimentadores_sia.to_excel(
            writer,
            sheet_name="Dados_Geograficos_SIA",
            index=False
        )

        # Ajuste automático simples das larguras.
        for nome_aba, planilha in writer.sheets.items():
            planilha.freeze_panes = "A2"
            planilha.auto_filter.ref = planilha.dimensions

            for coluna in planilha.columns:
                largura = 0
                letra = coluna[0].column_letter

                for celula in coluna:
                    if celula.value is not None:
                        largura = max(
                            largura,
                            len(str(celula.value))
                        )

                planilha.column_dimensions[letra].width = min(
                    largura + 2,
                    35
                )

    print("\nArquivos criados com sucesso:")

    print("\nXLSX:")
    print(ARQUIVO_SAIDA_XLSX)

    print("\nCSV:")
    print(ARQUIVO_SAIDA_CSV)


if __name__ == "__main__":
    try:
        main()
    except Exception as erro:
        print("\nERRO:")
        print(type(erro).__name__, "-", erro)