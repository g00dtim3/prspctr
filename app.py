"""
🏔️ Prospecteur Foncier - Monts de Lacaune
Application Streamlit pour identifier des parcelles selon des critères géographiques.

Critères de recherche :
- Surface > 5 ha
- Altitude > 800 m
- Terrain boisé
- Présence d'eau (source ou cours d'eau sur la parcelle)
"""

import streamlit as st
import pandas as pd
import folium
from folium import plugins
from streamlit_folium import st_folium
import requests
import json
import math
from io import BytesIO
from datetime import datetime

# Configuration de la page
st.set_page_config(
    page_title="Prospecteur Foncier - Monts de Lacaune",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# CONFIGURATION - Communes des Monts de Lacaune (Tarn 81)
# ============================================================================

COMMUNES_MONTS_LACAUNE = {
    "81124": "Lacaune",
    "81192": "Murat-sur-Vèbre",
    "81193": "Nages",
    "81314": "Viane",
    "81178": "Moulin-Mage",
    "81154": "Lamontélarié",
    "81108": "Gijounet",
    "81096": "Fontrieu",
    "81076": "Escroux",
    "81149": "Lacaze",
    "81262": "Senaux",
    "81033": "Boissezon",
    "81047": "Burlats",
    "81253": "Saint-Salvy-de-la-Balme",
    "81028": "Berlats",
    "81174": "Montredon-Labessonnié",
    "81234": "Roquecourbe",
    "81019": "Barre",
    "81256": "Saint-Sever-du-Moustier",
    "81150": "Lacapelle-Pinet",
}

CADASTRE_API_BASE = "https://cadastre.data.gouv.fr/bundler/cadastre-etalab/communes"

# ============================================================================
# PURE PYTHON GEOMETRY HELPERS
# ============================================================================

def geodesic_polygon_area(coords):
    """
    Calculate polygon area in m² from (lon, lat) coordinates.
    Uses the spherical excess formula (Shoelace on sphere).
    """
    R = 6371000.0
    if len(coords) < 3:
        return 0.0
    # Ensure closed
    if coords[0] != coords[-1]:
        coords = list(coords) + [coords[0]]
    area = 0.0
    for i in range(len(coords) - 1):
        lon1 = math.radians(coords[i][0])
        lat1 = math.radians(coords[i][1])
        lon2 = math.radians(coords[i + 1][0])
        lat2 = math.radians(coords[i + 1][1])
        area += (lon2 - lon1) * (2 + math.sin(lat1) + math.sin(lat2))
    return abs(area * R * R / 2.0)


def point_in_polygon(px, py, polygon):
    """Ray casting algorithm to test if (px, py) is inside polygon."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def segments_intersect(a1, a2, b1, b2):
    """Check if segment a1-a2 intersects segment b1-b2."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    d1 = cross(b1, b2, a1)
    d2 = cross(b1, b2, a2)
    d3 = cross(a1, a2, b1)
    d4 = cross(a1, a2, b2)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def line_intersects_polygon(line_coords, polygon_coords):
    """Check if a linestring intersects or is inside a polygon."""
    for pt in line_coords:
        if point_in_polygon(pt[0], pt[1], polygon_coords):
            return True
    n = len(polygon_coords)
    for i in range(len(line_coords) - 1):
        for j in range(n - 1):
            if segments_intersect(
                line_coords[i], line_coords[i + 1],
                polygon_coords[j], polygon_coords[j + 1]
            ):
                return True
    return False


def polygon_centroid(coords):
    """Simple average centroid for (lon, lat) polygon."""
    pts = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
    if not pts:
        return (0, 0)
    return (
        sum(c[0] for c in pts) / len(pts),
        sum(c[1] for c in pts) / len(pts)
    )


def polygon_bbox(coords):
    """Return (min_lon, min_lat, max_lon, max_lat)."""
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def bboxes_overlap(bb1, bb2):
    """Check if two bounding boxes overlap."""
    return not (bb1[2] < bb2[0] or bb2[2] < bb1[0] or
                bb1[3] < bb2[1] or bb2[3] < bb1[1])


def get_exterior_rings(geometry):
    """Extract list of exterior ring coordinate lists from a GeoJSON geometry."""
    t = geometry.get('type', '')
    if t == 'Polygon':
        return [geometry['coordinates'][0]]
    elif t == 'MultiPolygon':
        return [poly[0] for poly in geometry['coordinates']]
    return []


def estimate_forest_coverage(parcel_ring, forest_rings, forest_bboxes, grid_n=8):
    """
    Estimate fraction of parcel covered by forest using grid sampling.
    Returns a value between 0.0 and 1.0.
    """
    bbox = polygon_bbox(parcel_ring)
    min_lon, min_lat, max_lon, max_lat = bbox

    if max_lon <= min_lon or max_lat <= min_lat:
        return 0.0

    nearby = [fr for fr, fb in zip(forest_rings, forest_bboxes)
              if bboxes_overlap(bbox, fb)]
    if not nearby:
        return 0.0

    inside_parcel = 0
    inside_forest = 0
    step_x = (max_lon - min_lon) / grid_n
    step_y = (max_lat - min_lat) / grid_n

    for i in range(grid_n):
        px = min_lon + step_x * (i + 0.5)
        for j in range(grid_n):
            py = min_lat + step_y * (j + 0.5)
            if point_in_polygon(px, py, parcel_ring):
                inside_parcel += 1
                for fr in nearby:
                    if point_in_polygon(px, py, fr):
                        inside_forest += 1
                        break

    return inside_forest / inside_parcel if inside_parcel > 0 else 0.0


def parcel_intersects_water(parcel_ring, water_features):
    """Check if a parcel polygon intersects any water feature."""
    bbox = polygon_bbox(parcel_ring)
    for feat in water_features:
        if feat['geom_type'] == 'line':
            coords = feat['coords']
            f_lons = [c[0] for c in coords]
            f_lats = [c[1] for c in coords]
            f_bbox = (min(f_lons), min(f_lats), max(f_lons), max(f_lats))
            if not bboxes_overlap(bbox, f_bbox):
                continue
            if line_intersects_polygon(coords, parcel_ring):
                return True
        elif feat['geom_type'] == 'point':
            px, py = feat['coords']
            if point_in_polygon(px, py, parcel_ring):
                return True
    return False


# ============================================================================
# DATA LOADING FUNCTIONS
# ============================================================================

@st.cache_data(ttl=3600 * 24, show_spinner=False)
def get_communes_list():
    """Retourne la liste des communes disponibles."""
    return COMMUNES_MONTS_LACAUNE


@st.cache_data(ttl=3600 * 24, show_spinner="Téléchargement des parcelles...")
def load_parcelles_commune(code_insee: str) -> list:
    """
    Charge les parcelles d'une commune depuis l'API cadastre.
    Returns list of dicts with properties and GeoJSON geometry.
    """
    url = f"{CADASTRE_API_BASE}/{code_insee}/geojson/parcelles"

    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()

        parcelles = []
        for feature in data.get('features', []):
            geom = feature.get('geometry')
            props = feature.get('properties', {})

            if not geom:
                continue

            rings = get_exterior_rings(geom)
            total_area = sum(geodesic_polygon_area(ring) for ring in rings)
            surface_ha = total_area / 10000.0

            centroid = polygon_centroid(rings[0]) if rings else (0, 0)

            parcelles.append({
                'id': props.get('id', ''),
                'section': props.get('section', ''),
                'numero': props.get('numero', ''),
                'surface_ha': surface_ha,
                'commune': COMMUNES_MONTS_LACAUNE.get(code_insee, code_insee),
                'code_insee': code_insee,
                'geometry': geom,
                'centroid_lon': centroid[0],
                'centroid_lat': centroid[1],
            })

        return parcelles

    except Exception as e:
        st.warning(f"Erreur pour {COMMUNES_MONTS_LACAUNE.get(code_insee, code_insee)}: {e}")
        return []


@st.cache_data(ttl=3600 * 24, show_spinner="Chargement de l'hydrographie...")
def load_hydrographie_departement() -> list:
    """
    Charge les cours d'eau depuis OpenStreetMap via Overpass API.
    Returns list of water feature dicts.
    """
    bbox = (2.5, 43.55, 2.9, 43.85)

    overpass_url = "https://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json][timeout:60];
    (
      way["waterway"="stream"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      way["waterway"="river"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      node["natural"="spring"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
    );
    out geom;
    """

    try:
        response = requests.post(overpass_url, data={"data": overpass_query}, timeout=120)
        response.raise_for_status()
        data = response.json()

        features = []
        for element in data.get('elements', []):
            if element['type'] == 'way' and 'geometry' in element:
                coords = [(node['lon'], node['lat']) for node in element['geometry']]
                if len(coords) >= 2:
                    features.append({
                        'geom_type': 'line',
                        'coords': coords,
                        'water_type': element.get('tags', {}).get('waterway', 'water'),
                        'name': element.get('tags', {}).get('name', 'Sans nom'),
                        'geometry': {
                            'type': 'LineString',
                            'coordinates': coords
                        }
                    })
            elif element['type'] == 'node':
                features.append({
                    'geom_type': 'point',
                    'coords': (element['lon'], element['lat']),
                    'water_type': 'source',
                    'name': element.get('tags', {}).get('name', 'Source'),
                    'geometry': {
                        'type': 'Point',
                        'coordinates': [element['lon'], element['lat']]
                    }
                })

        return features

    except Exception as e:
        st.warning(f"Erreur chargement hydrographie: {e}")
        return []


@st.cache_data(ttl=3600 * 24, show_spinner="Chargement des zones forestières...")
def load_foret_zone() -> dict:
    """
    Charge les zones forestières depuis OpenStreetMap via Overpass API.
    Returns dict with 'rings' and 'bboxes' lists.
    """
    bbox = (2.5, 43.55, 2.9, 43.85)

    overpass_url = "https://overpass-api.de/api/interpreter"
    overpass_query = f"""
    [out:json][timeout:120];
    (
      way["landuse"="forest"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      way["natural"="wood"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      relation["landuse"="forest"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
      relation["natural"="wood"]({bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]});
    );
    out geom;
    """

    try:
        response = requests.post(overpass_url, data={"data": overpass_query}, timeout=180)
        response.raise_for_status()
        data = response.json()

        rings = []
        bboxes = []

        for element in data.get('elements', []):
            if element['type'] == 'way' and 'geometry' in element:
                coords = [(node['lon'], node['lat']) for node in element['geometry']]
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    rings.append(coords)
                    bboxes.append(polygon_bbox(coords))

        return {'rings': rings, 'bboxes': bboxes, 'count': len(rings)}

    except Exception as e:
        st.warning(f"Erreur chargement forêts: {e}")
        return {'rings': [], 'bboxes': [], 'count': 0}


# ============================================================================
# EXPORT FUNCTIONS
# ============================================================================

def create_excel_export(df: pd.DataFrame) -> BytesIO:
    """Crée un fichier Excel avec les parcelles filtrées."""
    export_df = df.drop(columns=['geometry', 'centroid_lon', 'centroid_lat'], errors='ignore').copy()

    cols_order = ['commune', 'code_insee', 'id', 'section', 'numero', 'surface_ha']
    cols_order = [c for c in cols_order if c in export_df.columns]
    other_cols = [c for c in export_df.columns if c not in cols_order]
    export_df = export_df[cols_order + other_cols]
    export_df['surface_ha'] = export_df['surface_ha'].round(2)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        export_df.to_excel(writer, sheet_name='Parcelles', index=False)

        recap = export_df.groupby('commune').agg(
            Nb_parcelles=('id', 'count'),
            Surface_totale_ha=('surface_ha', 'sum'),
            Surface_moyenne_ha=('surface_ha', 'mean')
        ).round(2)
        recap.to_excel(writer, sheet_name='Récapitulatif')

    output.seek(0)
    return output


def create_geojson_export(df: pd.DataFrame) -> str:
    """Crée un GeoJSON FeatureCollection."""
    features = []
    for _, row in df.iterrows():
        props = {}
        for k, v in row.items():
            if k in ('geometry', 'centroid_lon', 'centroid_lat'):
                continue
            # Convert numpy/pandas types to Python natives
            if hasattr(v, 'item'):
                v = v.item()
            props[k] = v
        features.append({
            'type': 'Feature',
            'geometry': row['geometry'],
            'properties': props
        })
    return json.dumps({
        'type': 'FeatureCollection',
        'features': features
    }, ensure_ascii=False, indent=2)


def generate_courrier_mairie(commune: str, parcelles_df: pd.DataFrame) -> str:
    """Génère le texte d'un courrier type pour une mairie."""
    date_str = datetime.now().strftime("%d/%m/%Y")

    parcelles_list = parcelles_df.apply(
        lambda row: f"  - Section {row.get('section', 'N/A')} n°{row.get('numero', row.get('id', 'N/A'))} ({row['surface_ha']:.2f} ha)",
        axis=1
    ).tolist()

    courrier = f"""
DEMANDE DE RENSEIGNEMENTS CADASTRAUX

{commune}, le {date_str}

Madame, Monsieur le Maire,

Je me permets de vous contacter afin d'obtenir des renseignements cadastraux
concernant les parcelles suivantes situées sur le territoire de votre commune :

{chr(10).join(parcelles_list)}

Conformément aux dispositions de l'article L107 A du Livre des procédures fiscales,
je souhaiterais obtenir les informations suivantes :
- Le nom et l'adresse du ou des propriétaires
- La nature cadastrale des parcelles
- Toute information utile concernant le statut de ces terrains

Je vous remercie par avance de l'attention que vous porterez à ma demande et
vous prie d'agréer, Madame, Monsieur le Maire, l'expression de mes salutations
distinguées.

[Votre nom]
[Votre adresse]
[Votre téléphone / email]

---
Pièce jointe : Liste des parcelles (optionnel)
"""
    return courrier


# ============================================================================
# MAIN APP
# ============================================================================

def main():
    # En-tête
    st.title("🏔️ Prospecteur Foncier")
    st.subheader("Monts de Lacaune - Tarn (81)")

    st.markdown("""
    Cette application permet d'identifier des parcelles répondant à des critères spécifiques :
    - **Surface** > 5 hectares
    - **Altitude** > 800 mètres
    - **Terrain boisé**
    - **Présence d'eau** (source ou cours d'eau sur la parcelle)
    """)

    # Sidebar - Filtres
    st.sidebar.header("🎯 Critères de recherche")

    communes = get_communes_list()
    selected_communes = st.sidebar.multiselect(
        "📍 Communes",
        options=list(communes.keys()),
        default=list(communes.keys())[:5],
        format_func=lambda x: communes[x]
    )

    min_surface = st.sidebar.slider(
        "📐 Surface minimum (ha)",
        min_value=1.0,
        max_value=50.0,
        value=5.0,
        step=0.5
    )

    min_altitude = st.sidebar.slider(
        "⛰️ Altitude minimum (m)",
        min_value=500,
        max_value=1200,
        value=800,
        step=50
    )

    require_forest = st.sidebar.checkbox("🌲 Terrain boisé", value=True)
    require_water = st.sidebar.checkbox("💧 Eau sur parcelle", value=True)

    search_button = st.sidebar.button("🔍 Rechercher", type="primary", use_container_width=True)

    # Zone principale
    if search_button and selected_communes:

        # Chargement des données
        with st.spinner("Chargement des données..."):

            all_parcelles = []
            progress_bar = st.progress(0)

            for i, code_insee in enumerate(selected_communes):
                parcelles = load_parcelles_commune(code_insee)
                all_parcelles.extend(parcelles)
                progress_bar.progress((i + 1) / len(selected_communes))

            progress_bar.empty()

            if not all_parcelles:
                st.error("Aucune parcelle chargée. Vérifiez votre connexion.")
                return

            df = pd.DataFrame(all_parcelles)
            st.info(f"📊 {len(df)} parcelles chargées pour {len(selected_communes)} communes")

            # Données complémentaires
            foret_data = None
            water_features = None

            if require_forest:
                foret_data = load_foret_zone()
                if foret_data['count'] > 0:
                    st.success(f"🌲 {foret_data['count']} zones forestières chargées")
                else:
                    st.warning("⚠️ Données forestières non disponibles - filtre désactivé")
                    require_forest = False

            if require_water:
                water_features = load_hydrographie_departement()
                if water_features:
                    st.success(f"💧 {len(water_features)} éléments hydrographiques chargés")
                else:
                    st.warning("⚠️ Données hydrographiques non disponibles - filtre désactivé")
                    require_water = False

        # Filtrage
        with st.spinner("Application des filtres..."):

            # Filtre surface
            filtered = df[df['surface_ha'] >= min_surface].copy()
            st.write(f"Après filtre surface ≥ {min_surface} ha : **{len(filtered)}** parcelles")

            # Filtre forêt
            if require_forest and foret_data and foret_data['count'] > 0 and not filtered.empty:
                forest_mask = []
                for _, row in filtered.iterrows():
                    rings = get_exterior_rings(row['geometry'])
                    is_forest = False
                    for ring in rings:
                        coverage = estimate_forest_coverage(
                            ring, foret_data['rings'], foret_data['bboxes']
                        )
                        if coverage > 0.5:
                            is_forest = True
                            break
                    forest_mask.append(is_forest)
                filtered = filtered[forest_mask]
                st.write(f"Après filtre forêt : **{len(filtered)}** parcelles")

            # Filtre eau
            if require_water and water_features and not filtered.empty:
                water_mask = []
                for _, row in filtered.iterrows():
                    rings = get_exterior_rings(row['geometry'])
                    has_water = any(
                        parcel_intersects_water(ring, water_features)
                        for ring in rings
                    )
                    water_mask.append(has_water)
                filtered = filtered[water_mask]
                st.write(f"Après filtre eau : **{len(filtered)}** parcelles")

        # Résultats
        st.markdown("---")

        if filtered.empty:
            st.warning("😕 Aucune parcelle ne correspond à tous les critères.")
            st.info("""
            **Suggestions :**
            - Réduisez la surface minimum
            - Désactivez le filtre forêt ou eau
            - Sélectionnez plus de communes
            """)
        else:
            st.success(f"✅ **{len(filtered)}** parcelles correspondent à vos critères !")

            tab_carte, tab_tableau, tab_export = st.tabs(["🗺️ Carte", "📋 Tableau", "📥 Export"])

            with tab_carte:
                center_lat = filtered['centroid_lat'].mean()
                center_lon = filtered['centroid_lon'].mean()
                m = folium.Map(location=[center_lat, center_lon], zoom_start=11, tiles='OpenStreetMap')

                for _, row in filtered.iterrows():
                    folium.GeoJson(
                        row['geometry'],
                        style_function=lambda x: {
                            'fillColor': '#228B22',
                            'color': '#006400',
                            'weight': 2,
                            'fillOpacity': 0.5
                        },
                        tooltip=f"{row['commune']} - {row.get('id', 'N/A')} ({row['surface_ha']:.2f} ha)"
                    ).add_to(m)

                if water_features:
                    for feat in water_features:
                        if feat['geom_type'] == 'line':
                            folium.GeoJson(
                                feat['geometry'],
                                style_function=lambda x: {'color': '#1E90FF', 'weight': 2}
                            ).add_to(m)

                plugins.Fullscreen().add_to(m)
                st_folium(m, width=None, height=500, use_container_width=True)

            with tab_tableau:
                display_cols = ['commune', 'id', 'section', 'numero', 'surface_ha']
                display_cols = [c for c in display_cols if c in filtered.columns]
                display_df = filtered[display_cols].copy()
                display_df['surface_ha'] = display_df['surface_ha'].round(2)

                st.dataframe(display_df, use_container_width=True, hide_index=True)

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Parcelles", len(filtered))
                with col2:
                    st.metric("Surface totale", f"{filtered['surface_ha'].sum():.1f} ha")
                with col3:
                    st.metric("Surface moyenne", f"{filtered['surface_ha'].mean():.1f} ha")

            with tab_export:
                st.subheader("📥 Téléchargements")

                col1, col2 = st.columns(2)

                with col1:
                    excel_data = create_excel_export(filtered)
                    st.download_button(
                        label="📊 Télécharger Excel",
                        data=excel_data,
                        file_name=f"parcelles_lacaune_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

                with col2:
                    geojson_str = create_geojson_export(filtered)
                    st.download_button(
                        label="🗺️ Télécharger GeoJSON",
                        data=geojson_str,
                        file_name=f"parcelles_lacaune_{datetime.now().strftime('%Y%m%d')}.geojson",
                        mime="application/json"
                    )

                st.markdown("---")
                st.subheader("📄 Courriers Mairies")

                communes_with_parcelles = filtered['commune'].unique()

                selected_commune_courrier = st.selectbox(
                    "Sélectionnez une commune",
                    options=communes_with_parcelles
                )

                if selected_commune_courrier:
                    parcelles_commune = filtered[filtered['commune'] == selected_commune_courrier]
                    courrier = generate_courrier_mairie(
                        selected_commune_courrier,
                        parcelles_commune
                    )

                    st.text_area("Courrier type", value=courrier, height=400)

                    st.download_button(
                        label=f"📄 Télécharger courrier {selected_commune_courrier}",
                        data=courrier,
                        file_name=f"courrier_{selected_commune_courrier.replace(' ', '_')}.txt",
                        mime="text/plain"
                    )

    elif not selected_communes:
        st.info("👆 Sélectionnez au moins une commune dans la barre latérale pour commencer.")

    else:
        st.info("👆 Configurez vos critères dans la barre latérale et cliquez sur **Rechercher**.")

        st.subheader("📍 Zone de recherche : Monts de Lacaune")

        m = folium.Map(location=[43.7, 2.7], zoom_start=10, tiles='OpenStreetMap')
        folium.Marker(
            [43.707, 2.69],
            popup="Lacaune",
            icon=folium.Icon(color='green', icon='info-sign')
        ).add_to(m)

        st_folium(m, width=None, height=400, use_container_width=True)

    # Footer
    st.markdown("---")
    st.caption("""
    🏔️ Prospecteur Foncier - Monts de Lacaune |
    Données : cadastre.data.gouv.fr, OpenStreetMap |
    ⚠️ Les données propriétaires ne sont pas publiques (demande au cadastre nécessaire)
    """)


if __name__ == "__main__":
    main()
