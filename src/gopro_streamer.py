from __future__ import annotations

import os
import threading
import time

import pyvirtualcam

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["AV_LOG_FORCE_NOCOLOR"] = "1"

import cv2

from .config import DEFAULT_FOV, DEFAULT_FPS, DEFAULT_RESOLUTION, STREAM_URL
from .gopro_api import GoProAPI


class GoProStreamer:
    def __init__(self, res: int = DEFAULT_RESOLUTION, fov: str = DEFAULT_FOV, fps: int = DEFAULT_FPS, show_preview: bool = False):
        self.running = True
        self.stop_event = threading.Event()
        self.res = res
        self.fov_name = fov
        self.fps = fps
        self.show_preview = show_preview
        self.api = GoProAPI()
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.frame_event = threading.Event()

    def enqueue_frames(self, cap) -> None:
        while self.running and not self.stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.02)
                continue

            with self.frame_lock:
                self.latest_frame = frame
            self.frame_event.set()

    def start(self) -> None:
        print(f"[+] Initialisation de la GoPro ({self.res}p)...")

        try:
            if not self.api.start_webcam(self.res):
                print("[-] La GoPro a refusé de démarrer.")
                return

            time.sleep(1.0)

            if self.fov_name != "wide":
                print(f"[+] Application du mode de vue : {self.fov_name}...")
                if not self.api.set_fov(self.fov_name):
                    print(f"[!] Note: Le mode '{self.fov_name}' peut être indisponible dans cette résolution sur la Hero 9.")

        except Exception as exc:
            print(f"[-] Impossible de configurer la GoPro : {exc}")
            return

        keep_alive_thread = threading.Thread(target=self.api.keep_alive, args=(self.stop_event,), daemon=True)
        keep_alive_thread.start()

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
            with pyvirtualcam.Camera(width=width, height=height, fps=self.fps, fmt=pyvirtualcam.PixelFormat.BGR) as cam:
                print(f"[+] Webcam virtuelle active : {cam.device}")
                if self.show_preview:
                    print("[+] Mode Preview activé. Appuie sur 'q' pour quitter.")
                else:
                    print("[+] Mode Invisible actif. Fais Ctrl+C dans le terminal pour quitter.")

                while self.running and not self.stop_event.is_set():
                    if not self.frame_event.wait(timeout=1.0):
                        time.sleep(0.001)
                        continue

                    with self.frame_lock:
                        frame = None if self.latest_frame is None else self.latest_frame.copy()
                        self.frame_event.clear()

                    if frame is None:
                        continue

                    cam.send(frame)
                    cam.sleep_until_next_frame()

                    if self.show_preview:
                        cv2.imshow("GoPro Live - Envoi vers OBS", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break

        except KeyboardInterrupt:
            print("\n[+] Arrêt demandé par l'utilisateur (Ctrl+C).")
        except Exception as exc:
            print(f"[-] Erreur critique : {exc}")
        finally:
            print("[+] Arrêt proprement...")
            self.running = False
            self.stop_event.set()
            cap.release()
            if self.show_preview:
                cv2.destroyAllWindows()
            self.api.stop_webcam()
            print("[+] Terminé.")