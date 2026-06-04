import py_dss_interface
import geopandas

dss = py_dss_interface.DSS()

gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"

ctmt = geopandas.read_file(gdb_path, layer="CTMT")

alim = ctmt.iloc[0]
# print(alim)

# cod_alim = alim["COD_ID"]
# nome_alim = alim["NOME"]
#
#
# ssdmt = geopandas.read_file(gdb_path, layer="SSDMT")
# linhas_alim = ssdmt[ssdmt["CTMT"] == cod_alim]
# print(linhas_alim)
# # # ================= OPENDSS =================
#
# dss.text("Clear")
# dss.text(f"New Circuit.{nome_alim} basekv=13.8 pu=1.0 phases=3")
#
# # fonte no barramento REAL
# bus_sub = str(linhas_alim.iloc[0]["PAC_1"])
#
# dss.text(f"""
# New Vsource.Substation
# bus1={bus_sub}
# basekv=13.8
# pu=1.0
# phases=3
# """)
#
# # Criar linhas
# for i, row in linhas_alim.iterrows():
#
#     bus1 = str(row["PAC_1"])
#     bus2 = str(row["PAC_2"])
#     comp_km = row["COMP"] / 1000
#
#     dss.text(f"""
#     New Line.L{i}
#     bus1={bus1}
#     bus2={bus2}
#     length={comp_km}
#     units=km
#     phases=3
#     r1=0.1
#     x1=0.2
#     """)
#
# print("Número de cargas:", dss.loads.count)
#
# # Criar carga fictícia
# potencia_total = ctmt.loc[ctmt["COD_ID"] == cod_alim, "ENE_01"].values[0]
# kw_carga = potencia_total / 2
#
# bus_carga = bus_sub
#
# dss.text(f"""
# New Load.CargaFicticia
# bus1={bus_carga}
# phases=3
# kv=13.8
# kw={kw_carga}
# pf=0.92
# """)
#
# # Rodar fluxo de potência
# dss.text("Solve")
#
# # ================= RESULTADOS =================
#
# dss.circuit.set_active_bus(bus_carga)
# print("Tensão (pu):", dss.bus.vmag_angle_pu)
#
# dss.circuit.set_active_element("Line.L0")
# print("Correntes:", dss.cktelement.currents_mag_ang)
# print("Potências:", dss.cktelement.powers)