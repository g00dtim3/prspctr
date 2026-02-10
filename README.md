

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
