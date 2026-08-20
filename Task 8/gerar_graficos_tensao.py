"""Consolida e plota as tensões dos cenários de 20% a 120%."""

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


RAIZ = Path(__file__).resolve().parent.parent
PASTA_GRAFICOS = RAIZ / "resultados" / "graficos_tensao"
CENARIOS = [20, 40, 60, 80, 100, 120]

FONTES = {
    "NW08": (RAIZ / "resultados" / "NW08" / "analise_eletrica_NW08.xlsx", "Resumo"),
    "ES11": (RAIZ / "analise_eletrica_ES11_validada.xlsx", "Resumo"),
    "CN12": (
        RAIZ / "resultados" / "comparacao_ceilandia" / "comparativo_CN15_vs_CN12.xlsx",
        "Resultados_CN12",
    ),
    "CN15": (RAIZ / "resultados" / "CN15" / "analise_eletrica_CN15.xlsx", "Resumo"),
}


def carregar_resultados(alimentador, arquivo, planilha):
    df = pd.read_excel(arquivo, sheet_name=planilha)
    df = df[df["Carregamento_Rede_%"].isin(CENARIOS)].copy()
    if "Carregamento_Trafo_Alvo_%" in df:
        df = df[df["Carregamento_Trafo_Alvo_%"].isna()]
    df = df.sort_values("Carregamento_Rede_%")

    encontrados = df["Carregamento_Rede_%"].round().astype(int).tolist()
    if encontrados != CENARIOS:
        raise ValueError(
            f"{alimentador}: cenarios encontrados {encontrados}; esperados {CENARIOS}."
        )

    return pd.DataFrame(
        {
            "Alimentador": alimentador,
            "Carregamento_%": df["Carregamento_Rede_%"].to_numpy(),
            "Tensao_Minima_pu": df["Tensao_Minima_pu"].to_numpy(),
            "Tensao_Media_pu": df["Tensao_Media_pu"].to_numpy(),
            "Queda_desde_1pu": 1.0 - df["Tensao_Minima_pu"].to_numpy(),
            "Convergiu": df["Convergiu"].to_numpy(),
        }
    )


def configurar_eixos(ax, alimentador):
    ax.axhline(
        0.93,
        color="#ff4d4d",
        linewidth=2,
        linestyle="--",
        label="Limite crítico (0,93 p.u.)",
    )
    ax.set_title(
        f"Perfil de Queda de Tensão MT - Alimentador {alimentador}",
        fontsize=17,
        weight="bold",
    )
    ax.set_xlabel("Cenário de carregamento (% da potência instalada)", fontsize=12)
    ax.set_ylabel("Tensão mínima MT (p.u.)", fontsize=12)
    ax.set_xticks(CENARIOS, [f"{valor}%" for valor in CENARIOS])
    ax.grid(True, alpha=0.35)


def gerar_grafico_individual(df, alimentador):
    fig, ax = plt.subplots(figsize=(12, 7.5))
    x = df["Carregamento_%"]
    y = df["Tensao_Minima_pu"]
    ax.plot(
        x,
        y,
        color="#3f7fa3",
        marker="o",
        linewidth=3,
        markersize=8,
        label=f"Vmin MT ({alimentador})",
    )
    ax.fill_between(x, y, y.min() - 0.04, color="#3f7fa3", alpha=0.10)
    configurar_eixos(ax, alimentador)
    limite_inferior = min(y.min(), 0.93)
    limite_superior = max(y.max(), 0.93)
    margem = max(0.012, (limite_superior - limite_inferior) * 0.12)
    ax.set_ylim(limite_inferior - margem, limite_superior + margem)
    for carga, tensao in zip(x, y):
        ax.annotate(
            f"{tensao:.4f}",
            (carga, tensao),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            weight="bold",
        )
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(PASTA_GRAFICOS / f"queda_tensao_{alimentador}.png", dpi=180)
    plt.close(fig)


def gerar_grafico_comparativo(consolidado):
    fig, ax = plt.subplots(figsize=(13, 8))
    for alimentador, df in consolidado.groupby("Alimentador", sort=False):
        ax.plot(
            df["Carregamento_%"],
            df["Tensao_Minima_pu"],
            marker="o",
            linewidth=2.4,
            markersize=7,
            label=alimentador,
        )
    ax.axhline(
        0.93,
        color="#ff4d4d",
        linewidth=2,
        linestyle="--",
        label="Limite crítico (0,93 p.u.)",
    )
    ax.set_title(
        "Tensão mínima MT por cenário - Todos os alimentadores",
        fontsize=17,
        weight="bold",
    )
    ax.set_xlabel("Cenário de carregamento (% da potência instalada)", fontsize=12)
    ax.set_ylabel("Tensão mínima MT (p.u.)", fontsize=12)
    ax.set_xticks(CENARIOS, [f"{valor}%" for valor in CENARIOS])
    ax.grid(True, alpha=0.35)
    ax.legend()
    fig.tight_layout()
    fig.savefig(PASTA_GRAFICOS / "queda_tensao_todos_comparativo.png", dpi=180)
    plt.close(fig)


def main():
    PASTA_GRAFICOS.mkdir(parents=True, exist_ok=True)
    quadros = []
    for alimentador, (arquivo, planilha) in FONTES.items():
        df = carregar_resultados(alimentador, arquivo, planilha)
        quadros.append(df)
        gerar_grafico_individual(df, alimentador)

    consolidado = pd.concat(quadros, ignore_index=True)
    consolidado.to_csv(
        RAIZ / "resultados" / "valores_tensao_cenarios_20_120.csv",
        index=False,
        decimal=",",
        sep=";",
        float_format="%.6f",
    )
    gerar_grafico_comparativo(consolidado)
    print(consolidado.to_string(index=False))


if __name__ == "__main__":
    main()
