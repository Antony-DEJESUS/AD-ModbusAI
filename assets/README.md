# Ressources graphiques

- `logo-a-<taille>.png` : la marque de l'application, le A seul, noir sur fond
  transparent (thème clair) ; `-blanc` pour le thème sombre. Tailles 64 à 512.
- `modbusai.ico` / `modbusai-icon-256.png` : icône de l'application, le A clair
  sur carré arrondi terracotta (#D97757), la couleur d'accent de la charte.
- `source/` : artwork d'origine (PDF, SVG, PNG du logo complet). Conservé pour
  régénérer la marque, **non embarqué** dans l'exécutable.

Les fichiers de `source/` ne sont pas chargés par l'application : le spec
PyInstaller n'embarque que `assets/*.png` et `assets/modbusai.ico`.

Régénération : le A est extrait du logo complet par analyse des composantes
connexes (on garde les deux plus grandes, qui forment le monogramme, et on
laisse le cadre et les textes). Chargement dans l'application :
`modbusai.ui.resources.logo_pixmap()` / `app_icon()`, qui gèrent le cas
PyInstaller (`sys._MEIPASS`).
