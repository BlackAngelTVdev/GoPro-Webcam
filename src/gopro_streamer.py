from __future__ import annotations

from datetime import timedelta
import os
import threading
import time

import pyvirtualcam

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["AV_LOG_FORCE_NOCOLOR"] = "1"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "fflags;nobuffer|flags;low_delay|max_delay;0|probesize;32|analyzeduration;0"

import cv2

from .config import DEFAULT_FPS, DEFAULT_RESOLUTION, FFMPEG_CAPTURE_OPTIONS, STREAM_URL
from .gopro_api import GoProAPI


class GoProStreamer:
    def __init__(self, res: int = DEFAULT_RESOLUTION, show_preview: bool = False, show_chrono: bool = False):
        self.running = True
        self.stop_event = threading.Event()
        self.res = res
        self.show_preview = show_preview
        self.show_chrono = show_chrono
        self.api = GoProAPI()
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.frame_event = threading.Event()
        self.start_time = None

    def enqueue_frames(self, cap) -> None:
        while self.running and not self.stop_event.is_set():
            try:
                ret, frame = cap.read()
            except cv2.error:
                break

            if not ret:
                if self.stop_event.is_set():
                    break
                time.sleep(0.005)
                continue

            with self.frame_lock:
                self.latest_frame = frame
            self.frame_event.set()

    def _draw_chrono(self, frame):
        if not self.show_chrono:
            return frame

        elapsed = timedelta(seconds=int(time.time() - self.start_time))
        total_seconds = int(elapsed.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        label = f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

        overlay = frame.copy()
        cv2.rectangle(overlay, (18, 18), (170, 64), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
        cv2.putText(frame, label, (32, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        return frame

    def _run_local_preview(self, window_title: str = "GoPro Live - Aperçu local") -> None:
        print("[+] Bascule automatique vers l'aperçu local.")

        while self.running and not self.stop_event.is_set():
            if not self.frame_event.wait(timeout=0.05):
                continue

            with self.frame_lock:
                frame = None if self.latest_frame is None else self.latest_frame.copy()
                self.frame_event.clear()

            if frame is None:
                continue

            frame = self._draw_chrono(frame)
            cv2.imshow(window_title, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    def start(self) -> None:
        print(f"[+] Initialisation de la GoPro ({self.res}p)...")

        try:
            if not self.api.start_webcam(self.res):
                print("[-] La GoPro a refusé de démarrer.")
                return

        except Exception as exc:
            print(f"[-] Impossible de configurer la GoPro : {exc}")
            return

        keep_alive_thread = threading.Thread(target=self.api.keep_alive, args=(self.stop_event,), daemon=True)
        keep_alive_thread.start()

        print("[+] Connexion au flux vidéo (Attente de l'image clé...)")
        cap = cv2.VideoCapture(STREAM_URL, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000)

        if FFMPEG_CAPTURE_OPTIONS:
            cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE)

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

        self.start_time = time.time()
        print(f"[+] Initialisation de la Webcam Virtuelle OBS ({width}x{height} @ {DEFAULT_FPS}fps)...")

        try:
            with pyvirtualcam.Camera(width=width, height=height, fps=DEFAULT_FPS, fmt=pyvirtualcam.PixelFormat.BGR) as cam:
                print(f"[+] Webcam virtuelle active : {cam.device}")
                print("[+] Mode Invisible actif. Fais Ctrl+C dans le terminal pour quitter.")

                while self.running and not self.stop_event.is_set():
                    if not self.frame_event.wait(timeout=0.05):
                        continue

                    with self.frame_lock:
                        frame = None if self.latest_frame is None else self.latest_frame.copy()
                        self.frame_event.clear()

                    if frame is None:
                        continue

                    frame = self._draw_chrono(frame)
                    cam.send(frame)
                    cam.sleep_until_next_frame()

                    if self.show_preview:
                        cv2.imshow("GoPro Live - Aperçu local", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break

        except KeyboardInterrupt:
            print("\n[+] Arrêt demandé par l'utilisateur (Ctrl+C).")
        except Exception as exc:
            print(f"[-] Webcam virtuelle indisponible, aperçu local activé : {exc}")
            self._run_local_preview()
        finally:
            print("[+] Arrêt proprement...")
            self.running = False
            self.stop_event.set()
            if reader_thread.is_alive():
                reader_thread.join(timeout=1.0)
            cap.release()
            cv2.destroyAllWindows()
            self.api.stop_webcam()
            print("[+] Terminé.")