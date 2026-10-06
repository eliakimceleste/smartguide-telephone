#!/bin/bash
# Installation de SmartGuide sur Raspberry Pi OS Bookworm (64 bits recommandé).
# À lancer depuis ce dossier :  bash install.sh
set -e
cd "$(dirname "$0")"

echo "== Paquets système (caméra, OpenCV, voix) =="
sudo apt update
sudo apt install -y python3-venv python3-picamera2 python3-opencv python3-numpy espeak-ng mpg123

echo "== Environnement Python =="
# --system-site-packages : réutilise picamera2, OpenCV et numpy installés par apt
python3 -m venv --system-site-packages venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install gTTS
./venv/bin/pip install tflite-runtime || ./venv/bin/pip install ai-edge-litert

echo "== Test du modèle =="
./venv/bin/python - <<'PY'
import os, sys
sys.argv = ['x']
for m in ('ai_edge_litert.interpreter', 'tflite_runtime.interpreter'):
    try:
        I = __import__(m, fromlist=['Interpreter']).Interpreter
        I(model_path=os.path.join('model', 'detect.tflite')).allocate_tensors()
        print('Modèle chargé avec', m)
        break
    except ImportError:
        pass
else:
    sys.exit('Aucun moteur TFLite installé')
PY

echo "== Test de la voix =="
espeak-ng -v fr "Installation terminée" || echo "Pas de son : vérifiez les écouteurs (sudo raspi-config > System > Audio)"

echo
echo "Lancer à la main :   ./venv/bin/python smartguide_pi.py --affichage"
echo "Démarrage automatique : voir README.md, étape 5"
