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

from .config import DEFAULT_FOV, DEFAULT_FPS, DEFAULT_RESOLUTION, FFMPEG_CAPTURE_OPTIONS, STREAM_URL
from .gopro_api import GoProAPI


class GoProStreamer:
    def __init__(self, res: int = DEFAULT_RESOLUTION, fov: str = DEFAULT_FOV, fps: int = DEFAULT_FPS, show_preview: bool = False, show_chrono: bool = False):
        self.running = True
        self.stop_event = threading.Event()
        self.res = res
        self.fov_name = fov
        self.fps = fps
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

    def _format_chrono(self) -> str:
        elapsed = timedelta(seconds=int(time.time() - self.start_time))
        total_seconds = int(elapsed.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _draw_chrono(self, frame):
        if not self.show_chrono:
            return frame

        label = self._format_chrono()
        overlay = frame.copy()
        cv2.rectangle(overlay, (18, 18), (170, 64), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
        cv2.putText(frame, label, (32, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        return frame

    def _is_virtual_camera_missing(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "obs virtual camera device not found" in message
            or "'obs' backend" in message
            or "no camera registered" in message
            or ("backend" in message and "camera" in message)
        )

    def _run_preview_only(self, width: int, height: int) -> None:
        self.show_preview = True
        print(f"[+] Mode Preview activé automatiquement ({width}x{height} @ {self.fps}fps). Appuie sur 'q' pour quitter.")

        try:
            while self.running and not self.stop_event.is_set():
                if not self.frame_event.wait(timeout=0.05):
                    continue

                with self.frame_lock:
                    frame = None if self.latest_frame is None else self.latest_frame.copy()
                    self.frame_event.clear()

                if frame is None:
                    continue

                frame = self._draw_chrono(frame)
                cv2.imshow("GoPro Live - Aperçu local", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            cv2.destroyAllWindows()

    def start(self) -> None:
        print(f"[+] Initialisation de la GoPro ({self.res}p)...")

        try:
            if not self.api.start_webcam(self.res):
                print("[-] La GoPro a refusé de démarrer.")
                return

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
        print(f"[+] Initialisation de la Webcam Virtuelle OBS ({width}x{height} @ {self.fps}fps)...")

        try:
            with pyvirtualcam.Camera(width=width, height=height, fps=self.fps, fmt=pyvirtualcam.PixelFormat.BGR) as cam:
                print(f"[+] Webcam virtuelle active : {cam.device}")
                if self.show_preview:
                    print("[+] Mode Preview activé. Appuie sur 'q' pour quitter.")
                else:
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
                        cv2.imshow("GoPro Live - Envoi vers OBS", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break

        except KeyboardInterrupt:
            print("\n[+] Arrêt demandé par l'utilisateur (Ctrl+C).")
        except Exception as exc:
            if self._is_virtual_camera_missing(exc):
                print("[!] Caméra virtuelle OBS introuvable, bascule automatique vers l'aperçu local.")
                self._run_preview_only(width, height)
                return
            print(f"[-] Erreur critique : {exc}")
        finally:
            print("[+] Arrêt proprement...")
            self.running = False
            self.stop_event.set()
            if reader_thread.is_alive():
                reader_thread.join(timeout=1.0)
            cap.release()
            if self.show_preview:
                cv2.destroyAllWindows()
            self.api.stop_webcam()
            print("[+] Terminé.")