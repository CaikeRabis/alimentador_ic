import geopandas as gpd
import networkx as nx

gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "TG_BZC1"
pac_ini = "TG_ELBZ"

ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")

print('rodando')

# Montar grafo da rede
G = nx.Graph()
for _, row in ssdmt.iterrows():
    G.add_edge(str(row['PAC_1']), str(row['PAC_2']), cod_id=row['COD_ID'])

# Calcular distância topológica de cada nó até o PAC_INI
distancias = nx.single_source_shortest_path_length(G, pac_ini)

# Pegar o nó mais distante
no_mais_distante = max(distancias, key=distancias.get)
print(f"Nó mais distante: {no_mais_distante} ({distancias[no_mais_distante]} saltos)")

# Achar transformador conectado a esse nó
trafos_ponta = untrmt[untrmt['PAC_1'].astype(str) == no_mais_distante]
if trafos_ponta.empty:
    # Tenta os 5 nós mais distantes
    top5 = sorted(distancias, key=distancias.get, reverse=True)[:5]
    print(f"Top 5 nós mais distantes: {top5}")
    trafos_ponta = untrmt[untrmt['PAC_1'].astype(str).isin([str(n) for n in top5])]

print(f"\nTransformadores na ponta da rede:")
print(trafos_ponta[['COD_ID', 'PAC_1', 'POT_NOM']].to_string())

print([c for c in untrmt.columns if c.upper().startswith("PAC_1")])
untrmt_pacs = untrmt[[c for c in untrmt.columns if c.upper().startswith("PAC_1")]].astype(str)
print(untrmt_pacs.head(10))

top5 = ['BZ_ELTG-1', 'STG_TG_BZC1_PNT_2608', 'STG_TG_BZC1_PNT_2610', 'STG_TG_BZC1_PNT_2612', 'STG_TG_BZC1_PNT_2614']

pac_cols = [c for c in untrmt.columns if c.upper().startswith("PAC_1")]
mask = False
for c in pac_cols:
    mask = mask | untrmt[c].astype(str).isin(top5)

trafos_ponta = untrmt[mask].copy()

print("Qtd trafos encontrados na ponta (top5 nós):", len(trafos_ponta))
if len(trafos_ponta) > 0:
    cols_show = ['COD_ID', 'POT_NOM'] + pac_cols
    print(trafos_ponta[cols_show].head(30).to_string(index=False))

no_mais_distante = "BZ_ELTG-1"

# Procura na camada SSDMT qual trecho toca esse nó
trechos_ponta = ssdmt[
    (ssdmt["PAC_1"].astype(str) == no_mais_distante) |
    (ssdmt["PAC_2"].astype(str) == no_mais_distante)
]

print("Trechos na ponta da rede:")
print(trechos_ponta[["COD_ID", "PAC_1", "PAC_2"]].to_string(index=False))