"""
Reproduction du prototype du mémoire « Système d'autoguidage pour les malvoyants » (A. DJIMA, IFRI 2022-2023)
sur un ordinateur, en utilisant la caméra du téléphone à la place de la caméra du Raspberry Pi.

Même chaîne que l'annexe 3 du mémoire :
  flux vidéo -> modèle TFLite SSD -> distance par la focale -> synthèse vocale gTTS des objets à <= 100 cm.

Exemples :
  python detection_telephone.py --modeldir coco --source http://192.168.1.20:8080/video   (appli « IP Webcam » sur Android)
  python detection_telephone.py --modeldir coco --source 0                                (webcam ou DroidCam)
  python detection_telephone.py --modeldir coco --image photo.jpg                         (test sur une photo)
"""
import argparse
import io
import os
import queue
import threading
import time

import cv2
import numpy as np

# ---------- Arguments (mêmes noms que le script du mémoire, plus --source / --image / --seuil) ----------
parser = argparse.ArgumentParser()
parser.add_argument('--modeldir', help='Dossier contenant le fichier .tflite', required=True)
parser.add_argument('--graph', help='Nom du fichier .tflite', default='detect.tflite')
parser.add_argument('--labels', help='Nom du fichier labelmap', default='labelmap.txt')
parser.add_argument('--labels_fr', help='Labelmap en français (optionnel)', default='labelmap_fr.txt')
parser.add_argument('--threshold', help='Confiance minimale', default=0.5, type=float)
parser.add_argument('--resolution', help='Résolution LxH demandée à la caméra', default='1280x720')
parser.add_argument('--source', help="0 pour la webcam, ou l'URL du flux du téléphone", default='0')
parser.add_argument('--image', help='Analyser une seule photo au lieu du flux vidéo', default=None)
parser.add_argument('--seuil', help="Distance d'alerte vocale en cm", default=100, type=float)
parser.add_argument('--rotate', help='Tourner l\'image de 180° (comme sur le Raspberry Pi)', action='store_true')
parser.add_argument('--no-display', help="Ne pas ouvrir de fenêtre (serveur sans écran)", action='store_true')
args = parser.parse_args()

resW, resH = (int(v) for v in args.resolution.split('x'))

# ---------- Interpréteur TFLite (tflite_runtime si présent, sinon TensorFlow complet) ----------
try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:
    from tensorflow.lite.python.interpreter import Interpreter

PATH_TO_CKPT = os.path.join(args.modeldir, args.graph)
PATH_TO_LABELS = os.path.join(args.modeldir, args.labels)
PATH_TO_LABELS_FR = os.path.join(args.modeldir, args.labels_fr)

with open(PATH_TO_LABELS, 'r', encoding='utf-8') as f:
    labels = [line.strip() for line in f.readlines()]
labels_fr = labels
if os.path.exists(PATH_TO_LABELS_FR):
    with open(PATH_TO_LABELS_FR, 'r', encoding='utf-8') as f:
        labels_fr = [line.strip() for line in f.readlines()]
# Correction du modèle COCO « starter » : la première étiquette est '???'
if labels[0] == '???':
    del labels[0]
if labels_fr[0] == '???':
    del labels_fr[0]

interpreter = Interpreter(model_path=PATH_TO_CKPT)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
height = input_details[0]['shape'][1]
width = input_details[0]['shape'][2]
floating_model = (input_details[0]['dtype'] == np.float32)
input_mean = 127.5
input_std = 127.5

outname = output_details[0]['name']
if 'StatefulPartitionedCall' in outname:   # modèle TF2 (cas du modèle entraîné dans le mémoire)
    boxes_idx, classes_idx, scores_idx = 1, 3, 0
else:                                       # modèle TF1 (modèle COCO starter)
    boxes_idx, classes_idx, scores_idx = 0, 1, 2

# ---------- Distance (annexe 3, figure 3.33) ----------
measured_distance = 180
reference_real_width = 50
reference_width_image = 852
focal_length = (reference_width_image * measured_distance) / reference_real_width   # 3067.2 px pour une image de 1280 px


def estimate_distance(object_width_image, reference_real_width, focal_length):
    return (reference_real_width * focal_length) / (2 * object_width_image)


# ---------- Synthèse vocale (annexe 4) : gTTS comme dans le mémoire, pyttsx3 hors ligne en secours ----------
speech_queue = queue.Queue(maxsize=1)


def synthesize_and_play(text):
    try:
        from gtts import gTTS
        from pydub import AudioSegment
        from pydub.playback import play
        tts = gTTS(text=text, lang='fr')
        bytes_io = io.BytesIO()
        tts.write_to_fp(bytes_io)
        bytes_io.seek(0)
        audio = AudioSegment.from_file(bytes_io, format='mp3').set_frame_rate(24000).set_channels(1)
        play(audio)
    except Exception as e:  # pas d'internet, ffmpeg absent… on bascule sur la voix du système
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception:
            print('[voix indisponible]', text, '-', e)


def speech_worker():
    while True:
        text = speech_queue.get()
        synthesize_and_play(text)


threading.Thread(target=speech_worker, daemon=True).start()


def announce(text):
    print('ALERTE :', text)
    try:
        speech_queue.put_nowait(text)   # on n'empile pas : si la voix parle encore, l'alerte est ignorée
    except queue.Full:
        pass


# ---------- Détection sur une image ----------
def detect(frame1):
    imH, imW = frame1.shape[:2]
    frame_rgb = cv2.cvtColor(frame1, cv2.COLOR_BGR2RGB)
    frame_resized = cv2.resize(frame_rgb, (width, height))
    input_data = np.expand_dims(frame_resized, axis=0)
    if floating_model:
        input_data = (np.float32(input_data) - input_mean) / input_std
    interpreter.set_tensor(input_details[0]['index'], input_data)
    interpreter.invoke()
    boxes = interpreter.get_tensor(output_details[boxes_idx]['index'])[0]
    classes = interpreter.get_tensor(output_details[classes_idx]['index'])[0]
    scores = interpreter.get_tensor(output_details[scores_idx]['index'])[0]

    results = []
    for i in range(len(scores)):
        if args.threshold < scores[i] <= 1.0:
            ymin = int(max(1, boxes[i][0] * imH))
            xmin = int(max(1, boxes[i][1] * imW))
            ymax = int(min(imH, boxes[i][2] * imH))
            xmax = int(min(imW, boxes[i][3] * imW))
            # La focale de référence a été mesurée sur une image de 1280 px : on ramène la largeur à cette échelle
            object_width_image = (xmax - xmin) * 1280 / imW
            distance = estimate_distance(object_width_image, reference_real_width, focal_length)
            name = labels_fr[int(classes[i])]
            results.append((name, float(scores[i]), distance, (xmin, ymin, xmax, ymax)))
    return results


def draw(frame, results):
    for name, score, distance, (xmin, ymin, xmax, ymax) in results:
        color = (78, 90, 255) if distance <= args.seuil else (63, 210, 255)
        cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), color, 2)
        label = '%s %d%% %dcm' % (name, int(score * 100), int(distance))
        cv2.putText(frame, label, (xmin, max(20, ymin - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


def handle(results):
    proches = sorted([r for r in results if r[2] <= args.seuil], key=lambda r: r[2])
    if proches:
        name, _, distance, _ = proches[0]
        article = '' if name.startswith(('un ', 'une ')) else 'un '
        announce(article + name + ' à ' + str(round(distance)) + ' centimètres')


# ---------- Programme principal ----------
if args.image:
    frame = cv2.imread(args.image)
    res = detect(frame)
    for r in res:
        print('%-15s confiance=%.2f distance=%.0f cm' % (r[0], r[1], r[2]))
    handle(res)
    if not args.no_display:
        draw(frame, res)
        cv2.imshow('Detection', frame)
        cv2.waitKey(0)
    else:
        time.sleep(8)  # laisse le temps à la voix de finir
    raise SystemExit

source = int(args.source) if args.source.isdigit() else args.source
cap = cv2.VideoCapture(source)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, resW)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resH)
if not cap.isOpened():
    raise SystemExit("Impossible d'ouvrir la caméra : " + str(args.source))

freq = cv2.getTickFrequency()
frame_rate_calc = 1
while True:
    t1 = cv2.getTickCount()
    ok, frame1 = cap.read()
    if not ok:
        print('Flux vidéo interrompu')
        break
    if args.rotate:
        frame1 = cv2.rotate(frame1, cv2.ROTATE_180)
    res = detect(frame1)
    handle(res)
    if not args.no_display:
        draw(frame1, res)
        cv2.putText(frame1, 'FPS: {0:.2f}'.format(frame_rate_calc), (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 0), 2)
        cv2.imshow('Detection', frame1)
        if cv2.waitKey(1) == ord('q'):
            break
    frame_rate_calc = 1 / ((cv2.getTickCount() - t1) / freq)

cap.release()
cv2.destroyAllWindows()
