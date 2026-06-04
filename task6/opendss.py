import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import networkx as nx
from shapely.geometry import LineString, MultiLineString

# =========================
# CONFIG
# =========================
gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "TG_BZC1"
pac_ini = "TG_ELBZ"

# Se você tiver pontos específicos medidos (exemplo), liste aqui:
# (você pode incluir os PACs que usou como ponto de monitoramento)
pontos_medidos_pac = [
    "TG_ELBZ",                  # subestação
    "STG_TG_BZC1_PNT_3100",      # nó vizinho já investigado
]

# =========================
# 1) CARREGAR CAMADAS
# =========================
ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")

# Normalizar PACs (evita problemas de espaços)
ssdmt["PAC_1_N"] = ssdmt["PAC_1"].astype(str).str.upper().str.strip()
ssdmt["PAC_2_N"] = ssdmt["PAC_2"].astype(str).str.upper().str.strip()

# =========================
# 2) MAPA GEOGRÁFICO DO ALIMENTADOR (TODOS OS TRECHOS)
# =========================
fig, ax = plt.subplots(1, 1, figsize=(10, 10))
ssdmt.plot(ax=ax, linewidth=0.6, color="gray")
ax.set_title(f"Alimentador {alim_id} (SSDMT) - Rede MT recortada")
ax.set_axis_off()
plt.tight_layout()
plt.show()

# =========================
# 3) ANÁLISE DE ILHAS (CONECTIVIDADE)
# =========================
G = nx.Graph()
G.add_edges_from(zip(ssdmt["PAC_1_N"], ssdmt["PAC_2_N"]))

ilhas = list(nx.connected_components(G))
ilhas_ordenadas = sorted(ilhas, key=len, reverse=True)

print("Total de nós:", G.number_of_nodes())
print("Total de ilhas:", len(ilhas))
print("Maior ilha (nós):", len(ilhas_ordenadas[0]))
print("PAC_INI na maior ilha?", pac_ini.upper() in ilhas_ordenadas[0])

# Criar um dicionário nó -> id_ilha
node_to_island = {}
for idx, comp in enumerate(ilhas_ordenadas):
    for n in comp:
        node_to_island[n] = idx

# Marcar em qual ilha cada linha está (pela PAC_1)
ssdmt["island_id"] = ssdmt["PAC_1_N"].map(node_to_island).fillna(-1).astype(int)

# =========================
# 4) MAPA: MAIOR ILHA vs RESTO
# =========================
fig, ax = plt.subplots(1, 1, figsize=(10, 10))
ssdmt[ssdmt["island_id"] != 0].plot(ax=ax, linewidth=0.4, color="lightgray", label="Outras ilhas")
ssdmt[ssdmt["island_id"] == 0].plot(ax=ax, linewidth=1.0, color="tab:blue", label="Maior ilha (energizável)")
ax.set_title(f"{alim_id} - Conectividade: maior ilha vs outras (total ilhas={len(ilhas)})")
ax.set_axis_off()
plt.tight_layout()
plt.show()

# =========================
# 5) PONTOS MEDIDOS (aproximação por PAC)
# =========================
# Para plotar pontos geográficos, precisamos associar PAC -> coordenada.
# Como não temos uma layer de nós, vamos aproximar:
# - Se PAC aparece em PAC_1, usamos o primeiro ponto da geometria da linha
# - Se PAC aparece em PAC_2, usamos o último ponto
pac_points = {}

for _, row in ssdmt.iterrows():
    geom = row.geometry
    if geom is None:
        continue

    # 👇 CORREÇÃO AQUI
    if geom.geom_type == "MultiLineString":
        coords = []
        for part in geom.geoms:
            coords.extend(list(part.coords))
    else:
        coords = list(geom.coords)

    p1 = row["PAC_1_N"]
    p2 = row["PAC_2_N"]

    if p1 not in pac_points:
        pac_points[p1] = coords[0]

    if p2 not in pac_points:
        pac_points[p2] = coords[-1]

# Criar GeoDataFrame com pontos medidos existentes no dicionário
rows = []
for pac in [p.upper().strip() for p in pontos_medidos_pac]:
    if pac in pac_points:
        x, y = pac_points[pac]
        rows.append({"PAC": pac, "geometry": gpd.points_from_xy([x], [y])[0]})
    else:
        print(f"AVISO: não encontrei coordenada para o PAC medido {pac}")

gdf_med = gpd.GeoDataFrame(rows, crs=ssdmt.crs)

fig, ax = plt.subplots(1, 1, figsize=(10, 10))
ssdmt.plot(ax=ax, linewidth=0.5, color="gray")
if len(gdf_med) > 0:
    gdf_med.plot(ax=ax, color="red", markersize=60)
    for _, r in gdf_med.iterrows():
        ax.annotate(r["PAC"], (r.geometry.x, r.geometry.y), xytext=(5, 5), textcoords="offset points")
ax.set_title(f"{alim_id} - Pontos medidos (PACs destacados)")
ax.set_axis_off()
plt.tight_layout()
plt.show()