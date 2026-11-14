"""Le bouton du casque, imité au clavier pour les tests (téléphone ou PC).

    Entrée            → appui court
    l puis Entrée     → appui long
    q puis Entrée     → quitter le programme

Sur le casque, la même interface sera branchée sur la broche du vrai bouton
(appui court / appui long mesurés sur la durée d'appui).
"""
import os
import queue
import threading


class BoutonClavier:
    def __init__(self):
        self._file = queue.Queue()
        self._fini = threading.Event()  # fin du clavier (EOF) : on quitte
        threading.Thread(target=self._lit, daemon=True).start()

    def _lit(self):
        # Lecture directe du clavier (os.read) plutôt qu'input() : à la fin du
        # programme, ce fil ne bloque pas la fermeture de Python.
        tampon = b""
        while True:
            try:
                morceau = os.read(0, 1024)
            except OSError:
                morceau = b""
            if not morceau:
                self._fini.set()
                return
            tampon += morceau
            while b"\n" in tampon:
                ligne, tampon = tampon.split(b"\n", 1)
                self._recoit(ligne.decode("utf-8", "replace"))

    def _recoit(self, ligne):
        touche = ligne.strip().lower()
        if touche in ("q", "quitter"):
            self._file.put("quitter")
        elif touche.startswith("l"):
            self._file.put("long")
        else:
            self._file.put("court")

    def vide(self):
        """Oublie les appuis faits pendant le guidage."""
        while True:
            try:
                self._file.get_nowait()
            except queue.Empty:
                return

    def attend(self, delai=None):
        """Renvoie « court », « long » ou « quitter » ; None si rien pendant `delai` secondes."""
        restant = delai
        while restant is None or restant > 0:
            pas = 0.5 if restant is None else min(0.5, restant)
            try:
                return self._file.get(timeout=pas)
            except queue.Empty:
                if self._fini.is_set():
                    return "quitter"
                if restant is not None:
                    restant -= pas
        return None
