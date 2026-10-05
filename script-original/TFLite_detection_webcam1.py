# Script d'origine du mémoire (dépôt honorinedjima/SmartGuide, TFLite_detection_webcam1.py).
# Modifications pour la reproduction, toutes marquées [reproduction] :
#   --source       : utiliser le téléphone comme caméra (IP Webcam / DroidCam) au lieu de la caméra du Raspberry Pi
#   --sans-rotation: ne pas retourner l'image de 180° (la caméra du Pi était montée à l'envers)
#   labelmap_Fr.txt: chemin relatif au dossier du modèle au lieu de /home/laboia/...
#   phrase vocale  : ajout des espaces manquants
######## Webcam Object Detection Using Tensorflow-trained Classifier #########
#
# Author: Evan Juras
# Date: 10/27/19
# Description: 
# This program uses a TensorFlow Lite model to perform object detection on a live webcam
# feed. It draws boxes and scores around the objects of interest in each frame from the
# webcam. To improve FPS, the webcam object runs in a separate thread from the main program.
# This script will work with either a Picamera or regular USB webcam.
#
# This code is based off the TensorFlow Lite image classification example at:
# https://github.com/tensorflow/tensorflow/blob/master/tensorflow/lite/examples/python/label_image.py
#
# I added my own method of drawing boxes and labels using OpenCV.

# Import packages
import os
import argparse
import cv2
import numpy as np
import sys
import time
from threading import Thread
#import pygame
import importlib.util

#gtts pour la traduction
from gtts import gTTS

# Audio
import io
from pydub import AudioSegment
from pydub.playback import play

# Initialisation de Pygame pour la lecture audio
#pygame.init()
#pygame.mixer.init()

# Define VideoStream class to handle streaming of video from webcam in separate processing thread
# Source - Adrian Rosebrock, PyImageSearch: https://www.pyimagesearch.com/2015/12/28/increasing-raspberry-pi-fps-with-python-and-opencv/

class VideoStream:
    """Camera object that controls video streaming from the Picamera"""
    def __init__(self,resolution=(640,480),framerate=30):
        # Initialize the PiCamera and the camera image stream
        self.stream = cv2.VideoCapture(SOURCE)  # [reproduction] 0 = webcam, ou URL du flux du téléphone
        ret = self.stream.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        ret = self.stream.set(3,resolution[0])
        ret = self.stream.set(4,resolution[1])
            
        # Read first frame from the stream
        (self.grabbed, self.frame) = self.stream.read()

	# Variable to control when the camera is stopped
        self.stopped = False

    def start(self):
	# Start the thread that reads frames from the video stream
        Thread(target=self.update,args=()).start()
        return self
      
    def update(self):
        # Keep looping indefinitely until the thread is stopped
        while True:
            # If the camera is stopped, stop the thread
            if self.stopped:
                # Close camera resources
                self.stream.release()
                return

            # Otherwise, grab the next frame from the stream
            (self.grabbed, self.frame) = self.stream.read()

    def read(self):
	# Return the most recent frame
        return self.frame

    def stop(self):
	# Indicate that the camera and thread should be stopped
        self.stopped = True

"""def synthesize_audio(text, filename):
      text_to_speak = ' '.join(text)
      tts = gTTS(text=text_to_speak, lang='fr')
      tts.save(filename, format="wav")"""
def synthesize_audio(text, filename, distance):
    #text_to_speak = ' '.join(text)
    distance = round(distance, 1)
    text = 'un ' + text + ' ' + 'à' + ' ' + str(distance) + ' centimètres'  # [reproduction] espaces manquants (« unpersonne »)
    tts = gTTS(text=text, lang='fr')
    
    # Enregistrer le texte parlé au format MP3
    bytes_io = io.BytesIO()
    tts.write_to_fp(bytes_io)
    
    # Revenir au début du fichier
    bytes_io.seek(0)
    
    # Charger le fichier MP3 et le convertir en format WAV
    audio_mp3 = AudioSegment.from_file(bytes_io, format="mp3")
    audio_wav = audio_mp3.set_frame_rate(24000).set_channels(1)
    
    # Sauvegarder le fichier WAV
    audio_wav.export(filename, format="wav")

def play_audio(response_audio_file):
    # Charger et jouer le fichier audio avec pydub
    audio = AudioSegment.from_wav(response_audio_file)
    play(audio)
    

# Par exemple, si une personne a une taille de 160 cm dans la vraie vie et 64 pixels dans l'image (à une certaine distance et avec une certaine résolution), 
# vous pouvez utiliser cette information comme référence pour estimer la distance des autres objets détectés.
#reference_real_width = 160  # cm
#reference_width_image = 64  # pixels
#focal_length = 0.4  # La longueur focale de votre caméra

measured_distance=180
reference_real_width=50
reference_width_image=852

# focal length finder function 
focal_length = (reference_width_image* measured_distance)/ reference_real_width 

#Calcule de la disatance entre l'objet et la camera    
def estimate_distance(object_width_image, reference_width_image, reference_real_width, focal_length):
    return (reference_real_width * focal_length) / (2 * object_width_image)



    
# Define and parse input arguments
parser = argparse.ArgumentParser()
parser.add_argument('--modeldir', help='Folder the .tflite file is located in',
                    required=True)
parser.add_argument('--graph', help='Name of the .tflite file, if different than detect.tflite',
                    default='detect.tflite')
parser.add_argument('--labels', help='Name of the labelmap file, if different than labelmap.txt',
                    default='labelmap.txt')
parser.add_argument('--threshold', help='Minimum confidence threshold for displaying detected objects',
                    default=0.5)
parser.add_argument('--source', help="[reproduction] 0 pour la webcam, ou l'URL du flux du téléphone (ex. http://192.168.1.20:8080/video)", default='0')
parser.add_argument('--sans-rotation', help="[reproduction] ne pas tourner l'image de 180° (utile avec un téléphone)", action='store_true')
parser.add_argument('--resolution', help='Desired webcam resolution in WxH. If the webcam does not support the resolution entered, errors may occur.',
                    default='1280x720')
parser.add_argument('--edgetpu', help='Use Coral Edge TPU Accelerator to speed up detection',
                    action='store_true')

args = parser.parse_args()

MODEL_NAME = args.modeldir
GRAPH_NAME = args.graph
LABELMAP_NAME = args.labels
min_conf_threshold = float(args.threshold)
resW, resH = args.resolution.split('x')
imW, imH = int(resW), int(resH)
SOURCE = int(args.source) if args.source.isdigit() else args.source  # [reproduction]
use_TPU = args.edgetpu

# Import TensorFlow libraries
# If tflite_runtime is installed, import interpreter from tflite_runtime, else import from regular tensorflow
# If using Coral Edge TPU, import the load_delegate library
pkg = importlib.util.find_spec('tflite_runtime')
if pkg:
    from tflite_runtime.interpreter import Interpreter
    if use_TPU:
        from tflite_runtime.interpreter import load_delegate
else:
    from tensorflow.lite.python.interpreter import Interpreter
    if use_TPU:
        from tensorflow.lite.python.interpreter import load_delegate

# If using Edge TPU, assign filename for Edge TPU model
if use_TPU:
    # If user has specified the name of the .tflite file, use that name, otherwise use default 'edgetpu.tflite'
    if (GRAPH_NAME == 'detect.tflite'):
        GRAPH_NAME = 'edgetpu.tflite'       

# Get path to current working directory
CWD_PATH = os.getcwd()

# Path to .tflite file, which contains the model that is used for object detection
PATH_TO_CKPT = os.path.join(CWD_PATH,MODEL_NAME,GRAPH_NAME)

# Path to label map file
PATH_TO_LABELS = os.path.join(CWD_PATH,MODEL_NAME,LABELMAP_NAME)


# Load the label map
with open(PATH_TO_LABELS, 'r') as f:
    labels = [line.strip() for line in f.readlines()]

with open(os.path.join(CWD_PATH,MODEL_NAME,'labelmap_Fr.txt'), 'r', encoding='utf-8') as f:  # [reproduction] chemin relatif au lieu de /home/laboia/...
    labels_fr = [line.strip() for line in f.readlines()]


# Have to do a weird fix for label map if using the COCO "starter model" from
# https://www.tensorflow.org/lite/models/object_detection/overview
# First label is '???', which has to be removed.
if labels[0] == '???':
    del(labels[0])
    
if labels_fr[0] == '???':
    del(labels_fr[0])    

# Load the Tensorflow Lite model.
# If using Edge TPU, use special load_delegate argument
if use_TPU:
    interpreter = Interpreter(model_path=PATH_TO_CKPT,
                              experimental_delegates=[load_delegate('libedgetpu.so.1.0')])
    print(PATH_TO_CKPT)
else:
    interpreter = Interpreter(model_path=PATH_TO_CKPT)

interpreter.allocate_tensors()

# Get model details
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
height = input_details[0]['shape'][1]
width = input_details[0]['shape'][2]

floating_model = (input_details[0]['dtype'] == np.float32)

input_mean = 127.5
input_std = 127.5

# Check output layer name to determine if this model was created with TF2 or TF1,
# because outputs are ordered differently for TF2 and TF1 models
outname = output_details[0]['name']

if ('StatefulPartitionedCall' in outname): # This is a TF2 model
    boxes_idx, classes_idx, scores_idx = 1, 3, 0
else: # This is a TF1 model
    boxes_idx, classes_idx, scores_idx = 0, 1, 2

# Initialize frame rate calculation
frame_rate_calc = 1
freq = cv2.getTickFrequency()

# Initialize video stream
videostream = VideoStream(resolution=(imW,imH),framerate=30).start()
time.sleep(1)

#for frame1 in camera.capture_continuous(rawCapture, format="bgr",use_video_port=True):
while True:

    # Start timer (for calculating frame rate)
    t1 = cv2.getTickCount()

    # Grab frame from video stream
    frame1 = videostream.read()
    if not args.sans_rotation:  # [reproduction]
        frame1 = cv2.rotate(frame1, cv2.ROTATE_180)

    # Acquire frame and resize to expected shape [1xHxWx3]
    frame = frame1.copy()
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    frame_resized = cv2.resize(frame_rgb, (width, height))
    input_data = np.expand_dims(frame_resized, axis=0)

    # Normalize pixel values if using a floating model (i.e. if model is non-quantized)
    if floating_model:
        input_data = (np.float32(input_data) - input_mean) / input_std

    # Perform the actual detection by running the model with the image as input
    interpreter.set_tensor(input_details[0]['index'],input_data)
    interpreter.invoke()

    # Retrieve detection results
    boxes = interpreter.get_tensor(output_details[boxes_idx]['index'])[0] # Bounding box coordinates of detected objects
    classes = interpreter.get_tensor(output_details[classes_idx]['index'])[0] # Class index of detected objects
    scores = interpreter.get_tensor(output_details[scores_idx]['index'])[0] # Confidence of detected objects

    # Loop over all detections and draw detection box if confidence is above minimum threshold
    for i in range(len(scores)):
        if ((scores[i] > min_conf_threshold) and (scores[i] <= 1.0)):

            # Get bounding box coordinates and draw box
            # Interpreter can return coordinates that are outside of image dimensions, need to force them to be within image using max() and min()
            ymin = int(max(1,(boxes[i][0] * imH)))
            xmin = int(max(1,(boxes[i][1] * imW)))
            ymax = int(min(imH,(boxes[i][2] * imH)))
            xmax = int(min(imW,(boxes[i][3] * imW)))
            
            
            
            cv2.rectangle(frame, (xmin,ymin), (xmax,ymax), (10, 255, 0), 2)

            # Draw label
            object_name = labels[int(classes[i])] # Look up object name from "labels" array using class index
            #3. Trouver l'index du label anglais dans le tableau labels_en :
            index = labels.index(object_name)
            
            #4. Utiliser le même index pour récupérer le label français correspondant dans labels_fr :
            object_name_fr = labels_fr[index]

            label = '%s: %d%%' % (object_name_fr, int(scores[i]*100)) # Example: 'person: 72%'
            labelSize, baseLine = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2) # Get font size
            label_ymin = max(ymin, labelSize[1] + 10) # Make sure not to draw label too close to top of window
            cv2.rectangle(frame, (xmin, label_ymin-labelSize[1]-10), (xmin+labelSize[0], label_ymin+baseLine-10), (255, 255, 255), cv2.FILLED) # Draw white box to put label text in
            
            # Estimation de la distance
            object_width_image = xmax - xmin  # Mesurez la largeur de l'objet détecté
            distance = estimate_distance(object_width_image, reference_width_image, reference_real_width, focal_length)
            print(object_width_image)
            cv2.putText(frame, f'{distance:.3f} cm', (xmin, label_ymin + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
            cv2.putText(frame, label, (xmin, label_ymin-7), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2) # Draw label text
        
            if distance <= 100:
                # Générer le fichier audio dans un thread séparé
                response_audio_file = 'reponse.wav'
                #audio_thread = Thread(target=synthesize_audio, args=(object_name_fr, response_audio_file))
                #audio_thread.start()
                synthesize_audio(object_name_fr, response_audio_file, distance)
                

                # Charger et jouer le fichier audio avec Pygame
                #pygame.mixer.music.load(response_audio_file)
                #pygame.mixer.music.play()
                
            
                # Lancer la lecture du fichier audio dans un thread séparé
                #audio_play_thread = Thread(target=play_audio, args=(response_audio_file,))
                #audio_play_thread.start()
                play_audio(response_audio_file)
                

            # Attendre la fin de la lecture audio
            #while pygame.mixer.music.get_busy():
                #continue

            # Supprimer le fichier audio après lecture
            #os.remove(response_audio_file)
            
            #print(label)
    # Draw framerate in corner of frame
    cv2.putText(frame,'FPS: {0:.2f}'.format(frame_rate_calc),(30,50),cv2.FONT_HERSHEY_SIMPLEX,1,(255,255,0),2,cv2.LINE_AA)

    # All the results have been drawn on the frame, so it's time to display it.
      
    cv2.imshow('Object detector', frame)

    # Calculate framerate
    t2 = cv2.getTickCount()
    time1 = (t2-t1)/freq
    frame_rate_calc= 1/time1

    # Press 'q' to quit
    if cv2.waitKey(1) == ord('q'):
        break

# Clean up
cv2.destroyAllWindows()
videostream.stop()
