"""
Sede da Exploração + SA — versão GDB (parcelas + sub-parcelas)
==============================================================

FONTES DE DADOS (ambas na mesma GDB):
  Parcelas     → parcelario_zv_2026210_Clip1_Freg_Sig_NIF  (camada com geometria)
  Sub-parcelas → sub_parcelas_ISIP                          (tabela sem geometria)

CHAVE DE LIGAÇÃO (Relate ArcGIS):
  Parcelas     : itemId      (texto)
  Sub-parcelas : itemId_txt  (texto)
  → ambos já são string; strip() aplicado para remover espaços

COLUNAS DE ÁREA:
  AreaHa          (sub-parcelas) → área individual de cada sub-parcela ← base para SA
  area_parcela_ha (parcelas)     → área total da parcela ← base para área total

CLASSIFICAÇÃO SA:
  Coluna 'OcSolo' da tabela sub_parcelas_ISIP

LÓGICA DA SEDE:
  1. SA por freguesia (dentro de cada decnif)
  2. Freguesia dominante = maior SA total
  3. Nessa freguesia → parcela com maior SA_parcela_ha
  4. Centróide dessa parcela = lat/lon da sede

SAÍDAS:
  sede_exploracao.csv
  sede_exploracao.geojson  (EPSG:4326)
"""

import pandas as pd
import geopandas as gpd
import json

# ══════════════════════════════════════════════════════════════
# CONFIGURAÇÃO — ajustar aqui se necessário
# ══════════════════════════════════════════════════════════════

GDB_PATH       = r"path/to/land_parcel_registry.gdb"
LAYER_PARCELAS = "parcels_layer"        # parcel geometry with holding ID and admin units
LAYER_SUBPARC  = "subparcels_layer"     # sub-parcel land-cover classification (iSIP)

# Campos na camada de PARCELAS
CAMPO_ITEMID       = "itemId"       # chave de ligação (texto) ↔ itemId_txt
CAMPO_DECNIF       = "DecNIF_num"   # NIF da exploração
CAMPO_DECNOME      = "DecNome"      # Nome da exploração
CAMPO_NOME_PARCELA = "Numero_txt"   # Número da parcela (texto)
CAMPO_AREA_PARCELA = "Area_ha"      # Área total da parcela (ha)
CAMPO_FREGUESIA    = "Freguesia_1"  # Freguesia (campo SIG)
CAMPO_CONCELHO     = "Concelho_1"   # Concelho (campo SIG)

# Campos na tabela de SUB-PARCELAS
CAMPO_ITEMID_TXT = "itemId_txt"   # chave de ligação (texto) ↔ itemId
CAMPO_OCSOLO     = "OcSolo"       # classificação da sub-parcela
CAMPO_AREA_SUB   = "AreaHa"       # área da sub-parcela (ha)
CAMPO_SUBPARC_ID = "SubParcela"   # identificador da sub-parcela

# ══════════════════════════════════════════════════════════════
# CLASSIFICAÇÕES SA (valores de OcSolo elegíveis como SA)
# ══════════════════════════════════════════════════════════════
# Valores marcados com (?) são novos face ao script anterior — confirmar se devem ser SA
SA_OCSOLOS = {
    'Cabeceiras e áreas envolventes',
    'Culturas frutícolas',
    'Culturas permanentes a evidenciar',               # (?) equivalente a 'Culturas permanentes'
    'Culturas protegidas',
    'Culturas Temporárias',
    'Misto de culturas permanentes',
    'Olival',
    'Outras culturas permanentes',
    'Pequenos Frutos',
    'PPE-AR: Prado e Pastagem Arbustiva',
    'PPE-PP: Prado e Pastagem Permanente',
    'PPE-PL: Prado e Pastagem Permanente Prática Local',  # (?) variante local de PPE-PP
    'Sobcoberto Misto',
    'Vinha',
    # 'Viveiros',                                      # (?) descomentar se for SA elegível
}

# ══════════════════════════════════════════════════════════════
# 1. CARREGAR CAMADA DE PARCELAS (com geometria)
# ══════════════════════════════════════════════════════════════
print("A carregar camada de parcelas...")
gdf = gpd.read_file(GDB_PATH, layer=LAYER_PARCELAS)

# ── Diagnóstico ───────────────────────────────────────────────
print(f"\nColunas na camada '{LAYER_PARCELAS}':")
print([c for c in gdf.columns if c != 'geometry'])
print(f"Registos: {len(gdf):,}\n")

# Verificar campos configurados
campos_parc = [CAMPO_ITEMID, CAMPO_DECNIF, CAMPO_DECNOME,
               CAMPO_NOME_PARCELA, CAMPO_AREA_PARCELA,
               CAMPO_FREGUESIA, CAMPO_CONCELHO]
faltam = [c for c in campos_parc if c not in gdf.columns]
if faltam:
    print(f"⚠ CAMPOS NÃO ENCONTRADOS na camada de parcelas: {faltam}")
    print("  → Ajustar a secção CONFIGURAÇÃO no topo do script.")
    raise SystemExit("Corrigir campos e executar novamente.")

# Reprojetar para WGS84 e calcular centróides
gdf_wgs84 = gdf.to_crs(epsg=4326)
gdf_wgs84['lon'] = gdf_wgs84.geometry.centroid.x.round(6)
gdf_wgs84['lat'] = gdf_wgs84.geometry.centroid.y.round(6)

# Selecionar e renomear campos
parcelas = gdf_wgs84[[
    CAMPO_ITEMID, CAMPO_DECNIF, CAMPO_DECNOME, CAMPO_NOME_PARCELA,
    CAMPO_AREA_PARCELA, CAMPO_FREGUESIA, CAMPO_CONCELHO,
    'lat', 'lon',
]].copy()

parcelas.rename(columns={
    CAMPO_ITEMID:       'n_parcelario',
    CAMPO_DECNIF:       'decnif',
    CAMPO_DECNOME:      'decnome',
    CAMPO_NOME_PARCELA: 'nome_parcela',
    CAMPO_AREA_PARCELA: 'area_parcela_ha',
    CAMPO_FREGUESIA:    'freguesia',
    CAMPO_CONCELHO:     'concelho',
}, inplace=True)

# Normalizar chave (strip por segurança — ambos já são texto)
parcelas['n_parcelario'] = parcelas['n_parcelario'].astype(str).str.strip()

print(f"Parcelas carregadas  : {len(parcelas):,}")
print(f"Explorações (decnif) : {parcelas['decnif'].nunique():,}")

# ══════════════════════════════════════════════════════════════
# 2. CARREGAR TABELA DE SUB-PARCELAS (sem geometria)
# ══════════════════════════════════════════════════════════════
print("\nA carregar tabela de sub-parcelas...")

try:
    sub_gdf = gpd.read_file(GDB_PATH, layer=LAYER_SUBPARC)
    sub = pd.DataFrame(sub_gdf.drop(columns='geometry', errors='ignore'))
except Exception as e:
    print(f"  gpd.read_file falhou ({e}), a tentar com fiona...")
    import fiona
    with fiona.open(GDB_PATH, layer=LAYER_SUBPARC) as src:
        sub = pd.DataFrame([f['properties'] for f in src])

# ── Diagnóstico ───────────────────────────────────────────────
print(f"Colunas em '{LAYER_SUBPARC}':")
print(list(sub.columns))
print(f"Registos: {len(sub):,}\n")

# Verificar campos configurados
campos_sub = [CAMPO_ITEMID_TXT, CAMPO_OCSOLO, CAMPO_AREA_SUB]
faltam_sub = [c for c in campos_sub if c not in sub.columns]
if faltam_sub:
    print(f"⚠ CAMPOS NÃO ENCONTRADOS na tabela de sub-parcelas: {faltam_sub}")
    print("  → Ajustar a secção CONFIGURAÇÃO no topo do script.")
    raise SystemExit("Corrigir campos e executar novamente.")

# Normalizar chave de ligação (texto → str limpo)
sub['n_parcelario'] = sub[CAMPO_ITEMID_TXT].astype(str).str.strip()

print(f"Sub-parcelas totais  : {len(sub):,}")
print(f"Parcelas únicas (sub): {sub['n_parcelario'].nunique():,}")

# ══════════════════════════════════════════════════════════════
# 3. JOIN: PARCELAS ← SUB-PARCELAS
#    Left join em n_parcelario (itemId ↔ itemId_txt, ambos str)
#    Mantém todas as parcelas da camada GDB
# ══════════════════════════════════════════════════════════════
cols_sub = ['n_parcelario', CAMPO_SUBPARC_ID, CAMPO_OCSOLO, CAMPO_AREA_SUB]
df = parcelas.merge(sub[cols_sub], on='n_parcelario', how='left')

df.rename(columns={
    CAMPO_AREA_SUB:   'area_subparcela_ha',
    CAMPO_SUBPARC_ID: 'sub_parcela_id',
}, inplace=True)

n_sem_sub = df['OcSolo'].isna().sum()
if n_sem_sub:
    print(f"\n⚠ {n_sem_sub:,} registos de parcelas sem sub-parcelas na tabela iSIP")

print(f"Registos após join   : {len(df):,}")

# ══════════════════════════════════════════════════════════════
# 4. FLAG SA + SA_ha POR SUB-PARCELA
# ══════════════════════════════════════════════════════════════
df['is_SA'] = df['OcSolo'].isin(SA_OCSOLOS)
df['SA_subparcela_ha'] = df['area_subparcela_ha'].where(df['is_SA'], other=0.0)

print(f"\nSub-parcelas totais  : {df['sub_parcela_id'].notna().sum():,}")
print(f"Sub-parcelas SA      : {df['is_SA'].sum():,}")

# ══════════════════════════════════════════════════════════════
# 5. AGREGAR POR PARCELA
#    SA_parcela_ha   = ∑ area_subparcela_ha das sub-parcelas SA
#    area_parcela_ha = valor único da parcela (não somar sub-parcelas)
# ══════════════════════════════════════════════════════════════
parcela = (
    df.groupby('n_parcelario')
    .agg(
        decnif           = ('decnif',            'first'),
        decnome          = ('decnome',           'first'),
        nome_parcela     = ('nome_parcela',      'first'),
        concelho         = ('concelho',          'first'),
        freguesia        = ('freguesia',         'first'),
        lat              = ('lat',               'first'),
        lon              = ('lon',               'first'),
        area_parcela_ha  = ('area_parcela_ha',   'first'),   # 1× por parcela
        SA_parcela_ha    = ('SA_subparcela_ha',  'sum'),     # ∑ SA das sub-parcelas
        n_subparcelas    = ('sub_parcela_id',    'count'),
        n_subparcelas_SA = ('is_SA',             'sum'),
    )
    .reset_index()
)

parcela['nSA_parcela_ha'] = (parcela['area_parcela_ha'] - parcela['SA_parcela_ha']).round(4)

n_mistas = ((parcela['n_subparcelas_SA'] > 0) &
            (parcela['n_subparcelas_SA'] < parcela['n_subparcelas'])).sum()

print(f"\nParcelas únicas      : {len(parcela):,}")
print(f"  → 100% SA          : {(parcela['n_subparcelas_SA'] == parcela['n_subparcelas']).sum():,}")
print(f"  → mistas (SA+nSA)  : {n_mistas:,}  (SA calculada exactamente por sub-parcela)")
print(f"  → 0% SA            : {(parcela['n_subparcelas_SA'] == 0).sum():,}")

# ══════════════════════════════════════════════════════════════
# 6. SA POR FREGUESIA (dentro de cada decnif)
# ══════════════════════════════════════════════════════════════
freg = (
    parcela.groupby(['decnif', 'freguesia'])
    .agg(
        SA_freg_ha   = ('SA_parcela_ha',   'sum'),
        area_freg_ha = ('area_parcela_ha', 'sum'),
        n_parc_freg  = ('n_parcelario',    'count'),
    )
    .reset_index()
    .sort_values(['decnif', 'SA_freg_ha', 'area_freg_ha'], ascending=[True, False, False])
)

freg_dom = (
    freg.groupby('decnif', sort=False)
    .first()
    .reset_index()
    .rename(columns={
        'freguesia':    'freg_sede',
        'SA_freg_ha':   'SA_freg_sede_ha',
        'area_freg_ha': 'area_freg_sede_ha',
        'n_parc_freg':  'n_parc_freg_sede',
    })
)

print(f"\nFreguesias dominantes: {len(freg_dom):,}")

# ══════════════════════════════════════════════════════════════
# 7. PARCELA SEDE
#    Na freguesia dominante → parcela com maior SA_parcela_ha
#    Desempate: maior area_parcela_ha
# ══════════════════════════════════════════════════════════════
p_dom     = parcela.merge(freg_dom[['decnif', 'freg_sede']], on='decnif', how='left')
p_na_sede = p_dom[p_dom['freguesia'] == p_dom['freg_sede']].copy()

parcela_sede = (
    p_na_sede
    .sort_values(['decnif', 'SA_parcela_ha', 'area_parcela_ha'], ascending=[True, False, False])
    .groupby('decnif', sort=False)
    .first()
    .reset_index()
    [['decnif', 'n_parcelario', 'nome_parcela',
      'SA_parcela_ha', 'area_parcela_ha', 'lat', 'lon']]
    .rename(columns={
        'n_parcelario':    'parcela_sede',
        'nome_parcela':    'nome_parcela_sede',
        'SA_parcela_ha':   'SA_parcela_sede_ha',
        'area_parcela_ha': 'area_parcela_sede_ha',
    })
)

print(f"Parcelas sede id.    : {len(parcela_sede):,}")

# ══════════════════════════════════════════════════════════════
# 8. TOTAIS DA EXPLORAÇÃO
# ══════════════════════════════════════════════════════════════
expl = (
    parcela.groupby('decnif')
    .agg(
        decnome          = ('decnome',          'first'),
        SA_total_ha      = ('SA_parcela_ha',    'sum'),
        area_total_ha    = ('area_parcela_ha',  'sum'),
        n_parcelas       = ('n_parcelario',     'count'),
        n_parcelas_SA    = ('n_subparcelas_SA', lambda x: (x > 0).sum()),
        n_subparcelas    = ('n_subparcelas',    'sum'),
        n_subparcelas_SA = ('n_subparcelas_SA', 'sum'),
    )
    .reset_index()
)

expl['area_nao_SA_ha'] = (expl['area_total_ha'] - expl['SA_total_ha']).round(4)
expl['pct_SA'] = (
    expl['SA_total_ha'] / expl['area_total_ha'].replace(0, pd.NA) * 100
).round(2)

# ══════════════════════════════════════════════════════════════
# 9. RESULTADO FINAL
# ══════════════════════════════════════════════════════════════
resultado = (
    expl
    .merge(freg_dom,     on='decnif', how='left')
    .merge(parcela_sede, on='decnif', how='left')
)

print(f"\nExplorações resultado: {len(resultado):,}")
print(f"Com SA > 0           : {(resultado['SA_total_ha'] > 0).sum():,}")

# ══════════════════════════════════════════════════════════════
# 10. EXPORTAR CSV
# ══════════════════════════════════════════════════════════════
cols_csv = [
    'decnif', 'decnome',
    'SA_total_ha', 'area_total_ha', 'area_nao_SA_ha', 'pct_SA',
    'n_parcelas', 'n_parcelas_SA', 'n_subparcelas', 'n_subparcelas_SA',
    'freg_sede', 'SA_freg_sede_ha', 'area_freg_sede_ha', 'n_parc_freg_sede',
    'parcela_sede', 'nome_parcela_sede', 'SA_parcela_sede_ha', 'area_parcela_sede_ha',
    'lat', 'lon',
]

resultado[cols_csv].to_csv("sede_exploracao.csv", index=False, encoding='utf-8-sig')
print("\n✓ sede_exploracao.csv exportado")

# ══════════════════════════════════════════════════════════════
# 11. EXPORTAR GeoJSON (EPSG:4326)
# ══════════════════════════════════════════════════════════════
geo_df   = resultado.dropna(subset=['lat', 'lon']).copy()
features = []

for _, row in geo_df.iterrows():
    props = {}
    for col in cols_csv:
        if col in ('lat', 'lon'):
            continue
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            props[col] = None
        elif hasattr(val, 'item'):
            props[col] = val.item()
        else:
            props[col] = val

    features.append({
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [round(float(row['lon']), 6), round(float(row['lat']), 6)]
        },
        "properties": props
    })

geojson = {
    "type": "FeatureCollection",
    "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
    "features": features
}

with open("sede_exploracao.geojson", "w", encoding="utf-8") as f:
    json.dump(geojson, f, ensure_ascii=False, indent=2)

print(f"✓ sede_exploracao.geojson exportado ({len(features):,} pontos, EPSG:4326)")

# ══════════════════════════════════════════════════════════════
# 12. SUMÁRIO
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SUMÁRIO")
print("=" * 60)
print(f"  Total explorações               : {len(resultado):,}")
print(f"  Com SA > 0                      : {(resultado['SA_total_ha'] > 0).sum():,}")
print(f"  SA média por exploração (ha)    : {resultado['SA_total_ha'].mean():.2f}")
print(f"  SA máxima (ha)                  : {resultado['SA_total_ha'].max():.2f}")
print(f"  SA total ZV (ha)                : {resultado['SA_total_ha'].sum():,.2f}")
print(f"  Área total declarada (ha)       : {resultado['area_total_ha'].sum():,.2f}")
print(f"  % SA média por exploração       : {resultado['pct_SA'].mean():.1f}%")
print("=" * 60)
print("""
METODOLOGIA:
  SA_total_ha   = ∑ AreaHa (sub_parcelas_ISIP) onde OcSolo ∈ SA_OCSOLOS
  area_total_ha = ∑ area_parcela_ha (parcelas GDB) — 1× por parcela
  area_nao_SA_ha= area_total_ha − SA_total_ha

  Sede = parcela com maior SA_parcela_ha,
         na freguesia (Freguesia_SIG) com maior SA da exploração

  Join: itemId (parcelas, txt) ↔ itemId_txt (sub_parcelas_ISIP, txt)
        strip() aplicado nos dois lados para remover espaços
""")