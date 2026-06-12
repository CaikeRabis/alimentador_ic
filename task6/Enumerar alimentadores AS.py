import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as ctx

gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"

ssdmt = gpd.read_file(gdb_path, layer="SSDMT")
ctmt = gpd.read_file(gdb_path, layer="CTMT")

alimentadores_asa_sul = [
    '02_BGC1', '02_BGC2', '02_BGC3',
    '0607', '0613', '0614', '0615',
    'BC39', 'BC_06C2',
    'BG_01C1', 'BG_01C2', 'BG_01C3',
    'EN09', 'EN10', 'EN11', 'EN13',
    'ES07', 'ES08', 'ES09', 'ES13',
    'ES14', 'ES15', 'ES16', 'ES17',
    'ES18', 'ES21', 'ES22', 'ES23',
    'ES24', 'HP02', 'HP03'
]

# Filtra apenas os alimentadores desejados
rede = ssdmt[ssdmt["CTMT"].isin(alimentadores_asa_sul)]

# Plota a rede
ax = rede.to_crs(3857).plot(
    figsize=(14, 14),
    linewidth=1.5,
    column="CTMT",  # cada alimentador com uma cor
    legend=True
)

ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik)

plt.title("Alimentadores da Asa Sul")
plt.axis("off")
plt.show()
# print("Colunas:")
# print(ctmt.columns)
#
# print("\nPrimeiras linhas:")
# print(ctmt.head())
#
# print(ctmt["COD_ID"].unique())