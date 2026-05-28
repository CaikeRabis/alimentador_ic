import fiona
import pandas as pd
import os
from py_dss_interface import DSS
import matplotlib.pyplot as plt

# =========================================================
# 1. CONFIGURAÇÃO E LEITURA DA BDGD
# =========================================================

gdb_path = r"/Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb/Neoenergia_Brasilia_5160_2024-12-31_V11_20250929-1338.gdb"


def read_layer_as_df(gdb, layer_name):
    with fiona.open(gdb, layer=layer_name, mode="r") as src:
        records = [dict(feat["properties"]) for feat in src]
    return pd.DataFrame(records)


# Ler camadas
print("Lendo UCMT_tab...")
ucmt_df = read_layer_as_df(gdb_path, "UCMT_tab")
print("Lendo BAR...")
bar_df = read_layer_as_df(gdb_path, "BAR")

# =========================================================
# 2. ESCOLHER CIRCUITO E FILTRAR
# =========================================================

ctmt_unicos = ucmt_df["CTMT"].unique()
print("\nCTMT disponíveis (primeiros 10):", ctmt_unicos[:10])

CIRCUITO_ALVO = ctmt_unicos[0]  # escolha o circuito que quiser
print(f"\nCircuito selecionado: {CIRCUITO_ALVO}")

ucmt_circ = ucmt_df[ucmt_df["CTMT"] == CIRCUITO_ALVO].copy()
print(f"Número de UCs no circuito: {len(ucmt_circ)}")

# =========================================================
# 3. ESCOLHER BARRA MT DE REFERÊNCIA
# =========================================================

bars_mt = bar_df[
    (bar_df["DIST"] == 5160) &
    (bar_df["TIP_INST"] == "SE_MT")
    ].copy()

if len(bars_mt) == 0:
    raise RuntimeError("Nenhuma barra MT encontrada.")

barra_ref = bars_mt.iloc[0]
barra_ref_id = str(barra_ref["COD_ID"]).replace(" ", "_").replace("-", "_")
kv_base = float(barra_ref["TEN_NOM"])

print(f"Barra de referência: {barra_ref_id} - {kv_base} kV")


# =========================================================
# 4. FUNÇÃO PARA POTÊNCIA DA UC
# =========================================================

def get_pot_uc_kw(uc_row):
    if pd.notnull(uc_row.get("CAR_INST", None)):
        try:
            val = float(uc_row["CAR_INST"])
            if val > 0:
                return val
        except:
            pass
    if pd.notnull(uc_row.get("DEM_CONT", None)):
        try:
            val = float(uc_row["DEM_CONT"])
            if val > 0:
                return val
        except:
            pass
    return 5.0  # potência fictícia


# =========================================================
# 5. GERAR SCRIPT DSS
# =========================================================

dss_lines = []
dss_lines.append("clear")
dss_lines.append(
    f"new circuit.{CIRCUITO_ALVO} bus1={barra_ref_id} basekv={kv_base} pu=1.0 phases=3"
)

# Criar cargas
print("\nGerando cargas...")
for idx, uc in ucmt_circ.iterrows():
    uc_id = str(uc["PN_CON"]).replace(" ", "_").replace("-", "_").replace(".", "_")
    p_kw = get_pot_uc_kw(uc)

    dss_lines.append(
        f"new load.UC_{uc_id} bus1={barra_ref_id}.1.2.3 phases=3 "
        f"conn=wye kv={kv_base} kw={p_kw:.3f} pf=0.92"
    )

dss_lines.append("set maxiterations=50")
dss_lines.append("solve")

# Salvar arquivo
dss_file = f"rede_{CIRCUITO_ALVO}.dss"
with open(dss_file, "w", encoding="utf-8") as f:
    f.write("\n".join(dss_lines))

print(f"Arquivo DSS salvo: {dss_file}")

# =========================================================
# 6. INICIALIZAR OPENDSS VIA py-dss-interface
# =========================================================

print("\n" + "=" * 60)
print("INICIALIZANDO OPENDSS")
print("=" * 60)

try:
    dss = DSS()
    print("✓ OpenDSS inicializado com sucesso!")
except Exception as e:
    print(f"✗ Erro ao inicializar OpenDSS: {e}")
    print("\nVerifique se o OpenDSS está instalado no Windows.")
    print("Download: https://sourceforge.net/projects/electricdss/")
    exit(1)

# =========================================================
# 7. RODAR SIMULAÇÃO
# =========================================================

print("\n" + "=" * 60)
print("RODANDO SIMULAÇÃO")
print("=" * 60)

# Limpar e carregar o circuito
dss.text("clear")
dss.text(f"redirect {os.path.abspath(dss_file)}")

# Verificar convergência
converged = dss.solution.converged
if converged:
    print("✓ Solução convergiu!")
else:
    print("✗ Solução NÃO convergiu")

# =========================================================
# 8. EXTRAIR RESULTADOS GERAIS
# =========================================================

print(f"\nCircuito: {dss.circuit.name}")
print(f"Número de barras: {dss.circuit.num_buses}")
print(f"Número de nós: {dss.circuit.num_nodes}")

# Potência total
total_power = dss.circuit.total_power
print(f"\nPotência total: {total_power[0]:.2f} kW + j{total_power[1]:.2f} kvar")

# Perdas
losses = dss.circuit.losses
print(f"Perdas totais: {losses[0] / 1000:.2f} kW + j{losses[1] / 1000:.2f} kvar")
print(f"Perdas percentuais: {(losses[0] / 1000 / abs(total_power[0])) * 100:.2f}%")

# =========================================================
# 9. COLETAR DADOS DAS CARGAS
# =========================================================

print("\nColetando dados das cargas...")

cargas_data = []

# Iterar sobre todas as cargas
dss.loads.first()
num_loads = dss.loads.count()

for i in range(num_loads):
    try:
        nome = dss.loads.name()
        kw = dss.loads.kw()
        kvar = dss.loads.kvar()
        pf = dss.loads.pf()

        # Tensão na barra da carga
        bus_name = dss.cktelement.bus_names()[0].split('.')[0]
        dss.circuit.set_active_bus(bus_name)
        voltages = dss.bus.pu_vmag_angle()
        v_pu = voltages[0] if len(voltages) > 0 else 1.0

        cargas_data.append({
            'Nome': nome,
            'kW': kw,
            'kvar': kvar,
            'PF': pf,
            'V_pu': v_pu
        })
    except Exception as e:
        print(f"Erro ao processar carga {i}: {e}")

    dss.loads.next()

df_cargas = pd.DataFrame(cargas_data)

print("\n" + "=" * 60)
print("RESUMO DAS CARGAS")
print("=" * 60)
print(df_cargas.head(10))
print(f"\nTotal de cargas: {len(df_cargas)}")
print(f"Potência total das cargas: {df_cargas['kW'].sum():.2f} kW")
print(f"Tensão mínima: {df_cargas['V_pu'].min():.4f} pu")
print(f"Tensão média: {df_cargas['V_pu'].mean():.4f} pu")
print(f"Tensão máxima: {df_cargas['V_pu'].max():.4f} pu")

# Salvar resultados em CSV
csv_file = f"resultados_{CIRCUITO_ALVO}.csv"
df_cargas.to_csv(csv_file, index=False, encoding='utf-8-sig')
print(f"\nResultados salvos em: {csv_file}")

# =========================================================
# 10. VISUALIZAÇÃO
# =========================================================

print("\nGerando gráficos...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle(f'Análise do Circuito {CIRCUITO_ALVO}', fontsize=16, fontweight='bold')

# Gráfico 1: Distribuição de potências
axes[0, 0].hist(df_cargas['kW'], bins=30, color='steelblue', edgecolor='black', alpha=0.7)
axes[0, 0].set_xlabel('Potência (kW)', fontsize=10)
axes[0, 0].set_ylabel('Número de UCs', fontsize=10)
axes[0, 0].set_title('Distribuição de Potências das UCs', fontsize=11, fontweight='bold')
axes[0, 0].grid(True, alpha=0.3)
axes[0, 0].axvline(df_cargas['kW'].mean(), color='red', linestyle='--',
                   label=f'Média: {df_cargas["kW"].mean():.2f} kW')
axes[0, 0].legend()

# Gráfico 2: Distribuição de tensões
axes[0, 1].hist(df_cargas['V_pu'], bins=30, color='coral', edgecolor='black', alpha=0.7)
axes[0, 1].set_xlabel('Tensão (pu)', fontsize=10)
axes[0, 1].set_ylabel('Número de UCs', fontsize=10)
axes[0, 1].set_title('Distribuição de Tensões nas UCs', fontsize=11, fontweight='bold')
axes[0, 1].axvline(x=0.93, color='red', linestyle='--', linewidth=2, label='Limite inferior (0.93 pu)')
axes[0, 1].axvline(x=1.05, color='red', linestyle='--', linewidth=2, label='Limite superior (1.05 pu)')
axes[0, 1].legend(fontsize=8)
axes[0, 1].grid(True, alpha=0.3)

# Gráfico 3: Top 10 maiores cargas
if len(df_cargas) >= 10:
    top10 = df_cargas.nlargest(10, 'kW')
else:
    top10 = df_cargas.nlargest(len(df_cargas), 'kW')

axes[1, 0].barh(range(len(top10)), top10['kW'], color='green', alpha=0.7)
axes[1, 0].set_yticks(range(len(top10)))
axes[1, 0].set_yticklabels([n[:25] + '...' if len(n) > 25 else n for n in top10['Nome']], fontsize=8)
axes[1, 0].set_xlabel('Potência (kW)', fontsize=10)
axes[1, 0].set_title(f'Top {len(top10)} Maiores Cargas', fontsize=11, fontweight='bold')
axes[1, 0].grid(True, alpha=0.3, axis='x')
axes[1, 0].invert_yaxis()

# Gráfico 4: Fator de potência
axes[1, 1].hist(df_cargas['PF'], bins=20, color='purple', edgecolor='black', alpha=0.7)
axes[1, 1].set_xlabel('Fator de Potência', fontsize=10)
axes[1, 1].set_ylabel('Número de UCs', fontsize=10)
axes[1, 1].set_title('Distribuição de Fator de Potência', fontsize=11, fontweight='bold')
axes[1, 1].axvline(df_cargas['PF'].mean(), color='red', linestyle='--',
                   label=f'Média: {df_cargas["PF"].mean():.3f}')
axes[1, 1].legend()
axes[1, 1].grid(True, alpha=0.3)

plt.tight_layout()
plot_file = f'analise_{CIRCUITO_ALVO}.png'
plt.savefig(plot_file, dpi=300, bbox_inches='tight')
print(f"Gráfico salvo: {plot_file}")
plt.show()

# =========================================================
# 11. RESUMO FINAL
# =========================================================

print("\n" + "=" * 60)
print("RESUMO DA ANÁLISE")
print("=" * 60)
print(f"Circuito: {CIRCUITO_ALVO}")
print(f"Número de UCs: {len(df_cargas)}")
print(f"Potência total: {df_cargas['kW'].sum():.2f} kW")
print(f"Perdas: {losses[0] / 1000:.2f} kW ({(losses[0] / 1000 / abs(total_power[0])) * 100:.2f}%)")
print(f"Tensão mínima: {df_cargas['V_pu'].min():.4f} pu")
print(f"Tensão máxima: {df_cargas['V_pu'].max():.4f} pu")
print(f"Fator de potência médio: {df_cargas['PF'].mean():.3f}")

# Verificar violações de tensão
violacoes_min = df_cargas[df_cargas['V_pu'] < 0.93]
violacoes_max = df_cargas[df_cargas['V_pu'] > 1.05]

print(f"\nViolações de tensão:")
print(f"  - Abaixo de 0.93 pu: {len(violacoes_min)} UCs")
print(f"  - Acima de 1.05 pu: {len(violacoes_max)} UCs")

print("\n" + "=" * 60)
print("ANÁLISE CONCLUÍDA!")
print("=" * 60)