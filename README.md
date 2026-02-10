# 🏔️ Prospecteur Foncier - Monts de Lacaune

Application Streamlit pour identifier des parcelles forestières dans les Monts de Lacaune (Tarn, 81) selon des critères géographiques spécifiques.

## 🎯 Critères de recherche

- **Surface** > 5 hectares (configurable)
- **Altitude** > 800 mètres (configurable)
- **Terrain boisé** (croisement avec données forestières OSM)
- **Présence d'eau** sur la parcelle (sources et cours d'eau)

## 📍 Zone couverte

~20 communes des Monts de Lacaune :
- Lacaune, Murat-sur-Vèbre, Nages, Viane, Moulin-Mage
- Lamontélarié, Gijounet, Fontrieu, Escroux, Lacaze
- Et autres communes limitrophes

## 🚀 Déploiement sur Streamlit Cloud

### 1. Créer un repository GitHub

```bash
# Depuis le dossier du projet
git init
git add .
git commit -m "Initial commit - Prospecteur Foncier Lacaune"
git branch -M main
git remote add origin https://github.com/VOTRE_USERNAME/prospecteur-foncier-lacaune.git
git push -u origin main
```

### 2. Déployer sur Streamlit Cloud

1. Aller sur [share.streamlit.io](https://share.streamlit.io)
2. Se connecter avec GitHub
3. Cliquer sur "New app"
4. Sélectionner le repository `prospecteur-foncier-lacaune`
5. Branche : `main`
6. Fichier principal : `app.py`
7. Cliquer sur "Deploy"

L'application sera accessible à : `https://votre-username-prospecteur-foncier-lacaune.streamlit.app`

## 💻 Exécution locale

```bash
# Installer les dépendances
pip install -r requirements.txt

# Lancer l'application
streamlit run app.py
```

L'application sera accessible à : `http://localhost:8501`

## 📦 Sources de données

| Donnée | Source | Accès |
|--------|--------|-------|
| Parcelles cadastrales | [cadastre.data.gouv.fr](https://cadastre.data.gouv.fr) | API gratuite |
| Hydrographie (cours d'eau, sources) | OpenStreetMap via Overpass | API gratuite |
| Zones forestières | OpenStreetMap via Overpass | API gratuite |
| Altitudes | Open-Elevation API | API gratuite |

## ⚠️ Limitations

1. **Propriétaires non disponibles** : Les noms des propriétaires ne sont pas en open data. L'application génère des courriers types pour faire une demande au cadastre.

2. **Altitude approximative** : L'API Open-Elevation a une précision limitée (~30m). Pour une vérification précise, utiliser les données IGN RGE ALTI.

3. **Données OSM** : Les zones forestières et cours d'eau proviennent d'OpenStreetMap, qui peut être incomplet dans certaines zones rurales.

4. **Cache** : Les données sont mises en cache pendant 24h pour améliorer les performances.

## 📄 Exports disponibles

- **Excel** : Liste des parcelles avec surface, commune, références cadastrales
- **GeoJSON** : Fichier géographique importable dans QGIS, Géoportail, etc.
- **Courriers** : Textes pré-remplis pour demande d'information au cadastre

## 🔧 Améliorations possibles

- [ ] Intégration des données IGN BD ALTI pour altitude précise
- [ ] Intégration BD Forêt IGN pour couverture forestière officielle
- [ ] Filtre par type de forêt (feuillus, résineux, mixte)
- [ ] Détection des parcelles contiguës (même propriétaire potentiel)
- [ ] Export DOCX pour les courriers
- [ ] Sauvegarde des recherches

## 📜 Licence

MIT - Libre d'utilisation

## 👤 Contact

Pour toute question ou suggestion, ouvrir une issue sur GitHub.
