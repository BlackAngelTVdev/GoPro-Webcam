import sys
import os
import argparse
import requests
import time
import threading
 
import pyvirtualcam

# --- TWEAK ULTIME POUR LES LOGS ---
# Masque les messages d'erreur et d'avertissement de FFmpeg/OpenCV au démarrage
os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["AV_LOG_FORCE_NOCOLOR"] = "1"

import cv2 # Importé après le changement d'environnement log

GOPRO_IP = "172.24.105.51"
STREAM_URL = "udp://@0.0.0.0:8554?overrun_nonfatal=1&fifo_size=50000000"

# Mapping mis à jour pour la Hero 9
FOV_MAP = {
    "wide": 0,
    "narrow": 1,
    "superview": 2,
    "linear": 4
}

class GoProStreamer:
    def __init__(self, res=1080, fov="wide", fps=30, show_preview=False):
        self.running = True
        self.stop_event = threading.Event()
        self.res = res
        self.fov_name = fov
        self.fov_id = FOV_MAP.get(fov, 0)
        self.fps = fps
        self.show_preview = show_preview
        # optimisation: conserver uniquement la dernière frame pour réduire la latence
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.frame_event = threading.Event()

    def keep_alive(self):
        session = requests.Session()
        while not self.stop_event.is_set():
            try:
                session.get(f"http://{GOPRO_IP}/gp/gpWebcam/VERSION", timeout=2)
            except:
                pass
            time.sleep(2)

    def enqueue_frames(self, cap):
        # Lecture en continu: on met à jour `latest_frame` et signale l'arrivée
        while self.running and not self.stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.02)
                continue
            with self.frame_lock:
                # stocker la dernière frame (remplace l'ancienne)
                self.latest_frame = frame
            self.frame_event.set()

    def start(self):
        print(f"[+] Initialisation de la GoPro ({self.res}p)...")
        try:
            # 1. Start du flux
            res_init = requests.get(f"http://{GOPRO_IP}/gp/gpWebcam/START?res={self.res}", timeout=5)
            if res_init.status_code != 200:
                print("[-] La GoPro a refusé de démarrer.")
                return
            
            # On attend un poil plus que la caméra soit bien passée en mode stream avant le FOV
            time.sleep(1.0)
            
            # 2. Application du FOV (uniquement si ce n'est pas le mode par défaut)
            if self.fov_name != "wide":
                print(f"[+] Application du mode de vue : {self.fov_name}...")
                fov_init = requests.get(f"http://{GOPRO_IP}/gp/gpWebcam/FOV?fov={self.fov_id}", timeout=5)
                if fov_init.status_code != 200:
                    print(f"[!] Note: Le mode '{self.fov_name}' peut être indisponible dans cette résolution sur la Hero 9.")

        except Exception as e:
            print(f"[-] Impossible de configurer la GoPro : {e}")
            return

        ka_thread = threading.Thread(target=self.keep_alive, daemon=True)
        ka_thread.start()

        print("[+] Connexion au flux vidéo (Attente de l'image clé...)")
        cap = cv2.VideoCapture(STREAM_URL, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            print("[-] Échec de l'ouverture du flux UDP.")
            self.stop_event.set()
            return

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        if width == 0 or height == 0:
            width, height = (1920, 1080) if self.res == 1080 else (1280, 720)

        reader_thread = threading.Thread(target=self.enqueue_frames, args=(cap,), daemon=True)
        reader_thread.start()

        print(f"[+] Initialisation de la Webcam Virtuelle OBS ({width}x{height} @ {self.fps}fps)...")
        
        try:
            # Utiliser BGR directement pour éviter la conversion coûteuse
            with pyvirtualcam.Camera(width=width, height=height, fps=self.fps, fmt=pyvirtualcam.PixelFormat.BGR) as cam:
                print(f"[+] Webcam virtuelle active : {cam.device}")
                if self.show_preview:
                    print("[+] Mode Preview activé. Appuie sur 'q' pour quitter.")
                else:
                    print("[+] Mode Invisible actif. Fais Ctrl+C dans le terminal pour quitter.")
                
                idle_sleep = 0.001
                while self.running and not self.stop_event.is_set():
                    # attendre l'arrivée d'une frame et récupérer la dernière
                    if self.frame_event.wait(timeout=1.0):
                        with self.frame_lock:
                            frame = None if self.latest_frame is None else self.latest_frame.copy()
                            # on remet l'événement à zéro
                            self.frame_event.clear()

                        if frame is None:
                            continue

                        cam.send(frame)
                        cam.sleep_until_next_frame()

                        if self.show_preview:
                            cv2.imshow("GoPro Live - Envoi vers OBS", frame)
                            if cv2.waitKey(1) & 0xFF == ord('q'):
                                break
                    else:
                        time.sleep(idle_sleep)

        except KeyboardInterrupt:
            print("\n[+] Arrêt demandé par l'utilisateur (Ctrl+C).")
        except Exception as e:
            print(f"[-] Erreur critique : {e}")

        print("[+] Arrêt proprement...")
        self.running = False
        self.stop_event.set()
        cap.release()
        if self.show_preview:
            cv2.destroyAllWindows()
        
        try:
            requests.get(f"http://{GOPRO_IP}/gp/gpWebcam/STOP", timeout=2)
        except:
            pass
        print("[+] Terminé.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GoPro Hero 9 Streaming Tool pour OBS")
    parser.add_argument("--res", type=int, choices=[720, 1080], default=1080, help="720 ou 1080")
    parser.add_argument("--fps", type=int, default=30, help="Frames par seconde")
    parser.add_argument("--fov", type=str, choices=["wide", "narrow", "superview", "linear"], default="wide", help="Lentille")
    parser.add_argument("--view", action="store_true", help="Afficher la fenêtre")
    
    args = parser.parse_args()
    
    streamer = GoProStreamer(res=args.res, fov=args.fov, fps=args.fps, show_preview=args.view)
    streamer.start()