import geopandas as gpd
import py_dss_interface
import matplotlib.pyplot as plt

# --- CONFIG ---
gdb_path = r"C:\Users\Usuario\PycharmProjects\CircuitosTestesEx5\Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"
alim_id = "ES01"

dss = py_dss_interface.DSS()

# --- FUNÇÕES ---
def bus(x):
    return str(x).strip().upper().replace("KV", "").replace(" ", "")

def clean_id(x):
    return str(x).strip().replace(" ", "_").replace(".", "").replace("-", "")

def limpar_numero(x):
    try:
        return float(str(x).lower().replace("kv", "").replace(",", ".").strip())
    except:
        return 0

# --- DADOS ---
ssdmt = gpd.read_file(gdb_path, layer="SSDMT", where=f"CTMT = '{alim_id}'")
unsemt = gpd.read_file(gdb_path, layer="UNSEMT", where=f"CTMT = '{alim_id}'")
untrmt = gpd.read_file(gdb_path, layer="UNTRMT", where=f"CTMT = '{alim_id}'")

pac_ini = bus(ssdmt.iloc[0]['PAC_1'])

# --- BASE DE TENSÃO BT ---
v_base_bt = 380 / (3 ** 0.5)  # ≈ 220V

# --- PERFIL DE CARGA 24h ---
mult = [0.3,0.2,0.2,0.2,0.3,0.4,0.4,0.5,0.6,0.7,0.8,0.9,
        1.0,0.9,0.8,0.7,0.8,0.9,1.0,1.2,1.1,0.9,0.7,0.5]

# --- CENÁRIOS ---
cenarios = {
    "leve": 0.6,
    "medio": 1.0,
    "pesado": 1.8
}

# =========================
# LOOP PRINCIPAL
# =========================
for nome, fator in cenarios.items():

    print(f"\n{'='*50}")
    print(f"CENÁRIO: {nome.upper()}")
    print(f"{'='*50}")

    tensao_horas = []

    for hora in range(24):

        fator_hora = mult[hora]

        dss.text("Clear")

        # --- CIRCUITO ---
        dss.text(f"New Circuit.{alim_id} bus1={pac_ini} basekv=13.8 phases=3 pu=1.0")
        dss.text("Set VoltageBases=[13.8, 0.38, 0.22]")
        dss.text("Set controlmode=Static")

        # --- LINHAS ---
        for _, row in ssdmt.iterrows():
            b1 = bus(row['PAC_1'])
            b2 = bus(row['PAC_2'])
            cod = clean_id(row['COD_ID'])

            if b1 == "" or b2 == "":
                continue

            length = max(float(row['Shape_Length']) / 1000, 0.001)

            if length < 0.1:
                r1, x1 = 0.7, 0.4
            elif length < 0.5:
                r1, x1 = 0.5, 0.35
            else:
                r1, x1 = 0.3, 0.3

            r1 *= 1.5
            x1 *= 1.3

            dss.text(
                f"New Line.L_{cod} bus1={b1} bus2={b2} "
                f"phases=3 length={length} units=km r1={r1} x1={x1}"
            )

        # --- CHAVES ---
        for _, row in unsemt.iterrows():
            b1 = bus(row['PAC_1'])
            b2 = bus(row['PAC_2'])
            cod = clean_id(row['COD_ID'])

            if b1 == "" or b2 == "":
                continue

            dss.text(
                f"New Line.SW_{cod} bus1={b1} bus2={b2} "
                f"phases=3 length=0.001 r1=0.001 x1=0.001"
            )

        # --- TRANSFORMADORES + CARGAS ---
        for _, row in untrmt.iterrows():
            bus_mt = bus(row['PAC_1'])
            cod = clean_id(row['COD_ID'])
            pot_kva = limpar_numero(row['POT_NOM'])

            if bus_mt == "" or pot_kva <= 0:
                continue

            bus_bt = f"{bus_mt}_BT"

            dss.text(
                f"New Transformer.T_{cod} phases=3 windings=2 "
                f"buses=[{bus_mt} {bus_bt}] "
                f"kvs=[13.8 0.38] "
                f"kvas=[{pot_kva} {pot_kva}]"
            )

            # 🔥 CARGA VARIANDO NO TEMPO
            kw = pot_kva * fator * fator_hora

            dss.text(
                f"New Load.L_{cod} bus1={bus_bt}.1.2.3 "
                f"phases=3 kv=0.38 kw={kw} pf=0.92"
            )

        # --- SOLVE ---
        dss.text("Solve")

        # --- TENSÃO MÍNIMA (PU) ---
        v_min = 999

        for i in range(dss.circuit.num_buses):
            dss.circuit.set_active_bus(dss.circuit.buses_names[i])
            tensoes = dss.bus.vmag_angle

            if len(tensoes) > 0:
                v = min(tensoes[::2]) / v_base_bt
                v_min = min(v_min, v)

        tensao_horas.append(v_min)

        print(f"Hora {hora:02d} | Fator {fator_hora:.2f} | Vmin {v_min:.4f} pu")

    # --- RESULTADOS ---
    print(f"Tensão mínima do dia: {min(tensao_horas):.4f} pu")

    # --- GRÁFICO ---
    plt.figure(figsize=(10,5))
    plt.plot(range(24), tensao_horas, marker='o')

    plt.title(f"Perfil de Tensão 24h - {nome.upper()}")
    plt.xlabel("Hora do dia")
    plt.ylabel("Tensão mínima (pu)")
    plt.grid(True)

    plt.axhline(0.95, linestyle='--')
    plt.axhline(0.93, linestyle='--')

    plt.show(block=True)