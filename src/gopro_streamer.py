from __future__ import annotations

from datetime import timedelta
import os
import threading
import time

import pyvirtualcam
import pystray
from PIL import Image, ImageDraw

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["AV_LOG_FORCE_NOCOLOR"] = "1"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "fflags;nobuffer|flags;low_delay|max_delay;0|probesize;32|analyzeduration;0"

import cv2

from .app_settings import AppSettings
from .config import DEFAULT_FPS, DEFAULT_RESOLUTION, FFMPEG_CAPTURE_OPTIONS, STREAM_URL
from .gopro_api import GoProAPI
from .settings_dialog import open_settings_dialog


class GoProStreamer:
    def __init__(self, res: int = DEFAULT_RESOLUTION, show_preview: bool = False, show_chrono: bool = False, settings: AppSettings | None = None):
        self.running = True
        self.stop_event = threading.Event()
        self.res = res
        self.preview_enabled = show_preview
        self.show_chrono = show_chrono
        self.settings = settings or AppSettings()
        self.api = GoProAPI()
        self.latest_frame = None
        self.frame_lock = threading.Lock()
        self.frame_event = threading.Event()
        self.start_time = None
        self.window_title = "GoPro Live - Aperçu local"
        self.tray_icon = None
        self.tray_ready = threading.Event()
        self.preview_lock = threading.Lock()
        self.preview_window_open = False
        self.close_prompt_active = False
        self.preview_close_requested = False

    def _update_settings(self, updated_settings: AppSettings) -> None:
        self.settings = updated_settings

    def _create_tray_image(self) -> Image.Image:
        image = Image.new("RGB", (64, 64), "black")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill=(25, 120, 255))
        draw.text((20, 19), "G", fill="white")
        return image

    def _show_preview(self, enabled: bool) -> None:
        with self.preview_lock:
            self.preview_enabled = enabled
            if not enabled:
                self.preview_close_requested = True

    def _tray_show_preview(self, icon, item) -> None:
        self._show_preview(True)

    def _tray_hide_preview(self, icon, item) -> None:
        self._show_preview(False)

    def _tray_open_settings(self, icon, item) -> None:
        open_settings_dialog(self.settings, on_save=self._update_settings)

    def _tray_quit(self, icon, item) -> None:
        self.stop_event.set()
        self.running = False
        icon.stop()

    def _start_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Paramètres", self._tray_open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Afficher l'aperçu", self._tray_show_preview),
            pystray.MenuItem("Masquer l'aperçu", self._tray_hide_preview),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter", self._tray_quit),
        )
        self.tray_icon = pystray.Icon("GoPro-Webcam", self._create_tray_image(), "GoPro-Webcam", menu)
        self.tray_ready.set()
        self.tray_icon.run()

    def _ask_close_or_minimize(self) -> str:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            minimize = messagebox.askyesno("GoPro-Webcam", "Fermer l'application ?\n\nOui = quitter\nNon = réduire dans la zone de notification")
            root.destroy()
            return "close" if minimize else "minimize"
        except Exception:
            return "minimize"

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
            self.preview_window_open = True

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                decision = self._ask_close_or_minimize()
                if decision == "close":
                    self.stop_event.set()
                    break
                self._show_preview(False)
                continue

            try:
                visible = cv2.getWindowProperty(window_title, cv2.WND_PROP_VISIBLE)
            except cv2.error:
                visible = 0

            if visible < 1 and not self.close_prompt_active:
                self.close_prompt_active = True
                decision = self._ask_close_or_minimize()
                if decision == "close":
                    self.stop_event.set()
                    break
                self._show_preview(False)
                self.preview_window_open = False
                self.close_prompt_active = False
                continue

            if visible >= 1:
                self.close_prompt_active = False

    def _run_preview_if_enabled(self) -> None:
        if self.preview_enabled:
            self._run_local_preview(self.window_title)

    def _run_headless_without_virtualcam(self) -> None:
        print("[+] Mode sans webcam virtuelle actif. Utilise l'icône de notification pour afficher l'aperçu ou quitter.")

        while self.running and not self.stop_event.is_set():
            if self.preview_enabled:
                self._run_local_preview(self.window_title)
                continue

            time.sleep(0.1)

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

        tray_thread = threading.Thread(target=self._start_tray, daemon=True)
        tray_thread.start()
        self.tray_ready.wait(timeout=2.0)

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

                    if self.preview_enabled:
                        cv2.imshow(self.window_title, frame)
                        self.preview_window_open = True

                        key = cv2.waitKey(1) & 0xFF
                        if key == ord("q"):
                            decision = self._ask_close_or_minimize()
                            if decision == "close":
                                self.stop_event.set()
                                break
                            self._show_preview(False)
                            continue

                        try:
                            visible = cv2.getWindowProperty(self.window_title, cv2.WND_PROP_VISIBLE)
                        except cv2.error:
                            visible = 0

                        if visible < 1 and not self.close_prompt_active:
                            self.close_prompt_active = True
                            decision = self._ask_close_or_minimize()
                            if decision == "close":
                                self.stop_event.set()
                                break
                            self._show_preview(False)
                            self.preview_window_open = False
                            self.close_prompt_active = False
                            continue

                        if visible >= 1:
                            self.close_prompt_active = False

                    elif self.preview_close_requested and self.preview_window_open:
                        try:
                            cv2.destroyWindow(self.window_title)
                        except cv2.error:
                            pass
                        self.preview_window_open = False
                        self.preview_close_requested = False

        except KeyboardInterrupt:
            print("\n[+] Arrêt demandé par l'utilisateur (Ctrl+C).")
        except Exception as exc:
            print(f"[-] Webcam virtuelle indisponible : {exc}")
            if self.preview_enabled:
                print("[+] Aperçu local activé.")
                self._run_local_preview(self.window_title)
            else:
                self._run_headless_without_virtualcam()
        finally:
            print("[+] Arrêt proprement...")
            self.running = False
            self.stop_event.set()
            if reader_thread.is_alive():
                reader_thread.join(timeout=1.0)
            cap.release()
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
            if self.tray_icon is not None:
                try:
                    self.tray_icon.stop()
                except Exception:
                    pass
            self.api.stop_webcam()
            print("[+] Terminé.")