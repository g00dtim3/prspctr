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
import geopandas as gpd
import folium
from folium import plugins
from streamlit_folium import st_folium
import requests
import json
import os
from pathlib import Path
from io import BytesIO
from datetime import datetime
import zipfile
import tempfile

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
    "81256": "Saint-Sever-du-Moustier",  # Aveyron limitrophe mais souvent inclus
    "81150": "Lacapelle-Pinet",
}

# URL de base pour le cadastre
CADASTRE_API_BASE = "https://cadastre.data.gouv.fr/bundler/cadastre-etalab/communes"

# ============================================================================
# FONCTIONS DE CHARGEMENT DES DONNÉES
# ============================================================================

@st.cache_data(ttl=3600*24, show_spinner=False)
def get_communes_list():
    """Retourne la liste des communes disponibles."""
    return COMMUNES_MONTS_LACAUNE

@st.cache_data(ttl=3600*24, show_spinner="Téléchargement des parcelles...")
def load_parcelles_commune(code_insee: str) -> gpd.GeoDataFrame:
    """
    Charge les parcelles d'une commune depuis l'API cadastre.
    
    Args:
        code_insee: Code INSEE de la commune
        
    Returns:
        GeoDataFrame avec les parcelles
    """
    url = f"{CADASTRE_API_BASE}/{code_insee}/geojson/parcelles"
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        
        gdf = gpd.read_file(BytesIO(response.content))
        
        # Calcul de la surface en hectares
        gdf_projected = gdf.to_crs(epsg=2154)  # Lambert 93 pour calculs métriques
        gdf['surface_ha'] = gdf_projected.geometry.area / 10000
        
        # Ajout du nom de commune
        gdf['commune'] = COMMUNES_MONTS_LACAUNE.get(code_insee, code_insee)
        gdf['code_insee'] = code_insee
        
        return gdf
        
    except Exception as e:
        st.warning(f"Erreur pour {COMMUNES_MONTS_LACAUNE.get(code_insee, code_insee)}: {e}")
        return gpd.GeoDataFrame()

@st.cache_data(ttl=3600*24, show_spinner="Chargement de l'hydrographie...")
def load_hydrographie_departement() -> gpd.GeoDataFrame:
    """
    Charge les cours d'eau du Tarn depuis les données BD TOPO simplifiées.
    Utilise les données OpenStreetMap via Overpass comme alternative.
    """
    # Bounding box approximative des Monts de Lacaune
    bbox = (2.5, 43.55, 2.9, 43.85)  # (min_lon, min_lat, max_lon, max_lat)
    
    # Requête Overpass pour les cours d'eau
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
                    from shapely.geometry import LineString
                    features.append({
                        'geometry': LineString(coords),
                        'type': element.get('tags', {}).get('waterway', 'water'),
                        'name': element.get('tags', {}).get('name', 'Sans nom')
                    })
            elif element['type'] == 'node':
                from shapely.geometry import Point
                features.append({
                    'geometry': Point(element['lon'], element['lat']),
                    'type': 'source',
                    'name': element.get('tags', {}).get('name', 'Source')
                })
        
        if features:
            gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
            return gdf
        else:
            return gpd.GeoDataFrame()
            
    except Exception as e:
        st.warning(f"Erreur chargement hydrographie: {e}")
        return gpd.GeoDataFrame()

@st.cache_data(ttl=3600*24, show_spinner="Chargement des zones forestières...")
def load_foret_zone() -> gpd.GeoDataFrame:
    """
    Charge les zones forestières depuis Corine Land Cover ou OSM.
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
        
        from shapely.geometry import Polygon, MultiPolygon
        
        features = []
        for element in data.get('elements', []):
            if element['type'] == 'way' and 'geometry' in element:
                coords = [(node['lon'], node['lat']) for node in element['geometry']]
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    features.append({
                        'geometry': Polygon(coords),
                        'type': 'forest'
                    })
        
        if features:
            return gpd.GeoDataFrame(features, crs="EPSG:4326")
        else:
            return gpd.GeoDataFrame()
            
    except Exception as e:
        st.warning(f"Erreur chargement forêts: {e}")
        return gpd.GeoDataFrame()

def get_elevation_for_point(lat: float, lon: float) -> float:
    """
    Récupère l'altitude d'un point via l'API Open-Elevation.
    """
    try:
        url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data['results'][0]['elevation']
    except:
        return None

@st.cache_data(ttl=3600*24, show_spinner="Récupération des altitudes...")
def get_elevations_batch(points: list) -> dict:
    """
    Récupère les altitudes pour une liste de points (batch).
    
    Args:
        points: Liste de tuples (lat, lon, id)
        
    Returns:
        Dict {id: elevation}
    """
    if not points:
        return {}
    
    # L'API accepte max 100 points par requête
    elevations = {}
    batch_size = 100
    
    for i in range(0, len(points), batch_size):
        batch = points[i:i+batch_size]
        locations = "|".join([f"{p[0]},{p[1]}" for p in batch])
        
        try:
            url = f"https://api.open-elevation.com/api/v1/lookup?locations={locations}"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            for j, result in enumerate(data.get('results', [])):
                point_id = batch[j][2]
                elevations[point_id] = result.get('elevation', 0)
                
        except Exception as e:
            # En cas d'erreur, on met des valeurs par défaut
            for p in batch:
                elevations[p[2]] = None
    
    return elevations

# ============================================================================
# FONCTIONS DE FILTRAGE
# ============================================================================

def filter_parcelles(
    gdf: gpd.GeoDataFrame,
    min_surface_ha: float = 5.0,
    min_altitude: float = 800.0,
    require_forest: bool = True,
    require_water: bool = True,
    foret_gdf: gpd.GeoDataFrame = None,
    hydro_gdf: gpd.GeoDataFrame = None
) -> gpd.GeoDataFrame:
    """
    Filtre les parcelles selon les critères.
    """
    if gdf.empty:
        return gdf
    
    # Filtre surface
    filtered = gdf[gdf['surface_ha'] >= min_surface_ha].copy()
    
    if filtered.empty:
        return filtered
    
    # Filtre forêt (intersection avec zones boisées)
    if require_forest and foret_gdf is not None and not foret_gdf.empty:
        # Vérifier l'intersection
        filtered_2154 = filtered.to_crs(epsg=2154)
        foret_2154 = foret_gdf.to_crs(epsg=2154)
        
        # Union de toutes les forêts
        foret_union = foret_2154.unary_union
        
        # Garder les parcelles qui intersectent significativement (>50% de la surface)
        def is_mostly_forest(geom):
            if geom is None or foret_union is None:
                return False
            try:
                intersection = geom.intersection(foret_union)
                return intersection.area / geom.area > 0.5
            except:
                return False
        
        mask = filtered_2154.geometry.apply(is_mostly_forest)
        filtered = filtered[mask]
    
    if filtered.empty:
        return filtered
    
    # Filtre eau (intersection avec hydrographie)
    if require_water and hydro_gdf is not None and not hydro_gdf.empty:
        filtered_2154 = filtered.to_crs(epsg=2154)
        hydro_2154 = hydro_gdf.to_crs(epsg=2154)
        
        # Buffer autour des cours d'eau (1m pour "sur la parcelle")
        hydro_buffer = hydro_2154.geometry.buffer(1).unary_union
        
        mask = filtered_2154.geometry.intersects(hydro_buffer)
        filtered = filtered[mask]
    
    return filtered

# ============================================================================
# FONCTIONS D'EXPORT
# ============================================================================

def create_excel_export(gdf: gpd.GeoDataFrame) -> BytesIO:
    """Crée un fichier Excel avec les parcelles filtrées."""
    df = gdf.drop(columns=['geometry']).copy()
    
    # Réorganisation des colonnes
    cols_order = ['commune', 'code_insee', 'id', 'section', 'numero', 'surface_ha']
    cols_order = [c for c in cols_order if c in df.columns]
    other_cols = [c for c in df.columns if c not in cols_order]
    df = df[cols_order + other_cols]
    
    # Arrondir la surface
    df['surface_ha'] = df['surface_ha'].round(2)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Parcelles', index=False)
        
        # Ajout d'un onglet récapitulatif par commune
        recap = df.groupby('commune').agg({
            'id': 'count',
            'surface_ha': ['sum', 'mean']
        }).round(2)
        recap.columns = ['Nb parcelles', 'Surface totale (ha)', 'Surface moyenne (ha)']
        recap.to_excel(writer, sheet_name='Récapitulatif')
    
    output.seek(0)
    return output

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
# INTERFACE STREAMLIT
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
    
    # Sélection des communes
    communes = get_communes_list()
    selected_communes = st.sidebar.multiselect(
        "📍 Communes",
        options=list(communes.keys()),
        default=list(communes.keys())[:5],  # 5 premières par défaut
        format_func=lambda x: communes[x]
    )
    
    # Filtres numériques
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
    
    # Options booléennes
    require_forest = st.sidebar.checkbox("🌲 Terrain boisé", value=True)
    require_water = st.sidebar.checkbox("💧 Eau sur parcelle", value=True)
    
    # Bouton de recherche
    search_button = st.sidebar.button("🔍 Rechercher", type="primary", use_container_width=True)
    
    # Zone principale
    if search_button and selected_communes:
        
        # Chargement des données
        with st.spinner("Chargement des données..."):
            
            # Parcelles
            all_parcelles = []
            progress_bar = st.progress(0)
            
            for i, code_insee in enumerate(selected_communes):
                gdf = load_parcelles_commune(code_insee)
                if not gdf.empty:
                    all_parcelles.append(gdf)
                progress_bar.progress((i + 1) / len(selected_communes))
            
            progress_bar.empty()
            
            if not all_parcelles:
                st.error("Aucune parcelle chargée. Vérifiez votre connexion.")
                return
            
            parcelles_gdf = pd.concat(all_parcelles, ignore_index=True)
            parcelles_gdf = gpd.GeoDataFrame(parcelles_gdf, crs="EPSG:4326")
            
            st.info(f"📊 {len(parcelles_gdf)} parcelles chargées pour {len(selected_communes)} communes")
            
            # Données complémentaires
            foret_gdf = None
            hydro_gdf = None
            
            if require_forest:
                foret_gdf = load_foret_zone()
                if not foret_gdf.empty:
                    st.success(f"🌲 {len(foret_gdf)} zones forestières chargées")
                else:
                    st.warning("⚠️ Données forestières non disponibles - filtre désactivé")
                    require_forest = False
            
            if require_water:
                hydro_gdf = load_hydrographie_departement()
                if not hydro_gdf.empty:
                    st.success(f"💧 {len(hydro_gdf)} éléments hydrographiques chargés")
                else:
                    st.warning("⚠️ Données hydrographiques non disponibles - filtre désactivé")
                    require_water = False
        
        # Filtrage
        with st.spinner("Application des filtres..."):
            
            # Premier filtre : surface
            filtered = parcelles_gdf[parcelles_gdf['surface_ha'] >= min_surface].copy()
            st.write(f"Après filtre surface ≥ {min_surface} ha : **{len(filtered)}** parcelles")
            
            # Filtre forêt
            if require_forest and foret_gdf is not None and not foret_gdf.empty:
                filtered = filter_parcelles(
                    filtered,
                    min_surface_ha=min_surface,
                    require_forest=True,
                    require_water=False,
                    foret_gdf=foret_gdf
                )
                st.write(f"Après filtre forêt : **{len(filtered)}** parcelles")
            
            # Filtre eau
            if require_water and hydro_gdf is not None and not hydro_gdf.empty:
                filtered = filter_parcelles(
                    filtered,
                    min_surface_ha=0,  # Déjà filtré
                    require_forest=False,
                    require_water=True,
                    hydro_gdf=hydro_gdf
                )
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
            
            # Tabs pour les résultats
            tab_carte, tab_tableau, tab_export = st.tabs(["🗺️ Carte", "📋 Tableau", "📥 Export"])
            
            with tab_carte:
                # Carte Folium
                center = [filtered.geometry.centroid.y.mean(), filtered.geometry.centroid.x.mean()]
                m = folium.Map(location=center, zoom_start=11, tiles='OpenStreetMap')
                
                # Ajout des parcelles
                for _, row in filtered.iterrows():
                    folium.GeoJson(
                        row.geometry.__geo_interface__,
                        style_function=lambda x: {
                            'fillColor': '#228B22',
                            'color': '#006400',
                            'weight': 2,
                            'fillOpacity': 0.5
                        },
                        tooltip=f"{row['commune']} - {row.get('id', 'N/A')} ({row['surface_ha']:.2f} ha)"
                    ).add_to(m)
                
                # Ajout des cours d'eau si disponibles
                if hydro_gdf is not None and not hydro_gdf.empty:
                    for _, row in hydro_gdf.iterrows():
                        if row.geometry.geom_type in ['LineString', 'MultiLineString']:
                            folium.GeoJson(
                                row.geometry.__geo_interface__,
                                style_function=lambda x: {'color': '#1E90FF', 'weight': 2}
                            ).add_to(m)
                
                # Légende
                plugins.Fullscreen().add_to(m)
                
                st_folium(m, width=None, height=500, use_container_width=True)
            
            with tab_tableau:
                # Tableau des résultats
                display_df = filtered.drop(columns=['geometry']).copy()
                display_df['surface_ha'] = display_df['surface_ha'].round(2)
                
                # Sélection des colonnes à afficher
                cols_display = ['commune', 'id', 'section', 'numero', 'surface_ha']
                cols_display = [c for c in cols_display if c in display_df.columns]
                
                st.dataframe(
                    display_df[cols_display],
                    use_container_width=True,
                    hide_index=True
                )
                
                # Statistiques
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
                    # Export Excel
                    excel_data = create_excel_export(filtered)
                    st.download_button(
                        label="📊 Télécharger Excel",
                        data=excel_data,
                        file_name=f"parcelles_lacaune_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                
                with col2:
                    # Export GeoJSON
                    geojson_str = filtered.to_json()
                    st.download_button(
                        label="🗺️ Télécharger GeoJSON",
                        data=geojson_str,
                        file_name=f"parcelles_lacaune_{datetime.now().strftime('%Y%m%d')}.geojson",
                        mime="application/json"
                    )
                
                st.markdown("---")
                st.subheader("📄 Courriers Mairies")
                
                # Génération des courriers par commune
                communes_with_parcelles = filtered['commune'].unique()
                
                selected_commune_courrier = st.selectbox(
                    "Sélectionnez une commune",
                    options=communes_with_parcelles
                )
                
                if selected_commune_courrier:
                    parcelles_commune = filtered[filtered['commune'] == selected_commune_courrier]
                    courrier = generate_courrier_mairie(
                        selected_commune_courrier,
                        parcelles_commune.drop(columns=['geometry'])
                    )
                    
                    st.text_area(
                        "Courrier type",
                        value=courrier,
                        height=400
                    )
                    
                    st.download_button(
                        label=f"📄 Télécharger courrier {selected_commune_courrier}",
                        data=courrier,
                        file_name=f"courrier_{selected_commune_courrier.replace(' ', '_')}.txt",
                        mime="text/plain"
                    )
    
    elif not selected_communes:
        st.info("👆 Sélectionnez au moins une commune dans la barre latérale pour commencer.")
    
    else:
        # État initial
        st.info("👆 Configurez vos critères dans la barre latérale et cliquez sur **Rechercher**.")
        
        # Affichage de la carte de la zone
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
