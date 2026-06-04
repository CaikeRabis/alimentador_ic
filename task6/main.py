import py_dss_interface
import fiona
import geopandas


gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"

layers = fiona.listlayers(gdb_path)

for layer in layers:
    print(layer)


