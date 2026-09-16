# Ressources graphiques

- `logo-ad-automation.pdf` : logo AD AUTOMATION fourni par Antony DE JESUS (source vectorielle).
- `logo-ad.svg` : conversion vectorielle de la page 1 du PDF.
- `logo-ad-<taille>.png` : logo noir sur fond transparent, pour le thème clair.
- `logo-ad-<taille>-blanc.png` : même logo en blanc, pour le thème sombre.

Les PNG sont générés depuis le PDF (PyMuPDF) ; la variante blanche est une
inversion RVB à alpha conservé. Ne pas modifier les PNG à la main : régénérer
depuis le PDF si le logo change.

Chargement dans l'application : `modbusai.ui.resources.asset_path(nom)`, qui
gère aussi le cas PyInstaller (`sys._MEIPASS`). Les fichiers sont embarqués par
`packaging/modbusai.spec` via `datas`.
