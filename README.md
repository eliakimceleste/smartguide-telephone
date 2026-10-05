# SmartGuide sur téléphone

Reproduction du prototype du mémoire « Système d'autoguidage pour les malvoyants » (A. DJIMA, IFRI 2022-2023, dépôt d'origine : https://github.com/honorinedjima/SmartGuide), testable avec un simple téléphone.

**Tester :** ouvrez https://eliakimceleste.github.io/smartguide-telephone/ sur le téléphone, branchez des écouteurs et appuyez sur « Démarrer ».

- `index.html`, `lib/`, `model/` : application web (détection d'objets COCO dans le navigateur, distance par la focale, alerte vocale en français sous 100 cm).
- `script-original/` : script de l'autrice (`TFLite_detection_webcam1.py`) adapté pour utiliser le téléphone comme caméra.
- `script-python/` : réécriture propre du même script.
- `GUIDE.md` : guide pas à pas et constats de la reproduction.

Le modèle fine-tuné du mémoire n'étant pas publié, les deux versions utilisent un modèle SSD MobileNet pré-entraîné sur COCO.
