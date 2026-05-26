from __future__ import annotations

from datetime import timedelta
import ctypes
import os
import socket
import subprocess
import sys
import struct
import threading
import time
from pathlib import Path

import pyvirtualcam
import pystray
import numpy as np
from PIL import Image, ImageDraw

os.environ["OPENCV_LOG_LEVEL"] = "OFF"
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "0"
os.environ["OPENCV_FFMPEG_DEBUG"] = "0"
os.environ["AV_LOG_FORCE_NOCOLOR"] = "1"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "fflags;nobuffer|flags;low_delay|max_delay;0|probesize;32|analyzeduration;0"

import cv2

from .app_settings import AppSettings
from .config import DEFAULT_FPS, DEFAULT_RESOLUTION, FFMPEG_CAPTURE_OPTIONS, NETWORK_STREAM_PATH, NETWORK_STREAM_PORT, STREAM_URL
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
        self.frame_seq = 0
        self.start_time = None
        self.window_title = "GoPro Live - Aperçu local"
        self.tray_icon = None
        self.tray_ready = threading.Event()
        self.preview_lock = threading.Lock()
        self.preview_window_open = False
        self.close_prompt_active = False
        self.preview_close_requested = False
        self.local_webcam_active = False
        self.network_send_socket: socket.socket | None = None
        self.network_server_socket: socket.socket | None = None

    def _update_settings(self, updated_settings: AppSettings) -> None:
        self.settings = updated_settings

    def _get_asset_path(self, *parts: str) -> Path:
        base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        return base_path / "src" / "asset" / Path(*parts)

    def _apply_preview_window_icon(self, window_title: str) -> None:
        if os.name != "nt":
            return

        icon_path = self._get_asset_path("icon.ico")
        if not icon_path.exists():
            return

        user32 = ctypes.windll.user32
        image_handle = ctypes.windll.user32.LoadImageW(
            None,
            str(icon_path),
            1,
            0,
            0,
            0x0010 | 0x0040,
        )
        if not image_handle:
            return

        window_handle = None
        for _ in range(20):
            window_handle = user32.FindWindowW(None, window_title)
            if window_handle:
                break
            time.sleep(0.05)

        if not window_handle:
            return

        user32.SendMessageW(window_handle, 0x0080, 0, image_handle)
        user32.SendMessageW(window_handle, 0x0080, 1, image_handle)

    def _create_tray_image(self) -> Image.Image:
        icon_path = self._get_asset_path("icon.png")
        if icon_path.exists():
            with Image.open(icon_path) as icon_image:
                return icon_image.convert("RGBA")

        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
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

    def _build_restart_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, *sys.argv[1:]]

        script_path = Path(__file__).resolve().parents[1] / "main.py"
        return [sys.executable, str(script_path), *sys.argv[1:]]

    def _tray_restart(self, icon, item) -> None:
        try:
            subprocess.Popen(
                self._build_restart_command(),
                cwd=str(Path.cwd()),
            )
        except Exception as exc:
            print(f"[-] Impossible de redémarrer l'application : {exc}")
            return

        self.stop_event.set()
        self.running = False
        icon.stop()

    def _tray_quit(self, icon, item) -> None:
        self.stop_event.set()
        self.running = False
        icon.stop()

    def _open_stream_capture(self, stream_url: str) -> cv2.VideoCapture | None:
        cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)

        if cap.isOpened():
            if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap

        cap.release()
        return None

    def _wait_for_stream_capture(self, stream_url: str, timeout_seconds: float = 15.0) -> cv2.VideoCapture | None:
        deadline = time.time() + timeout_seconds

        while not self.stop_event.is_set() and time.time() < deadline:
            cap = self._open_stream_capture(stream_url)
            if cap is not None:
                return cap
            time.sleep(0.5)

        return None

    def _build_network_stream_url(self) -> str | None:
        host = self.settings.network_stream_host.strip()
        if not host:
            return None

        return f"http://{host}:{NETWORK_STREAM_PORT}/{NETWORK_STREAM_PATH}"

    def _build_network_peer_host(self) -> str | None:
        host = self.settings.network_stream_host.strip()
        return host or None

    def _close_network_sender(self) -> None:
        if self.network_send_socket is not None:
            try:
                self.network_send_socket.close()
            except OSError:
                pass
            self.network_send_socket = None

    def _close_network_server(self) -> None:
        if self.network_server_socket is not None:
            try:
                self.network_server_socket.close()
            except OSError:
                pass
            self.network_server_socket = None

    def _ensure_network_sender(self, peer_host: str) -> bool:
        if self.network_send_socket is not None:
            return True

        try:
            sender_socket = socket.create_connection((peer_host, NETWORK_STREAM_PORT), timeout=3.0)
            sender_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.network_send_socket = sender_socket
            return True
        except OSError:
            self._close_network_sender()
            return False

    def _send_frame_to_peer(self, frame, peer_host: str) -> None:
        if not self._ensure_network_sender(peer_host):
            return

        try:
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return

            payload = encoded.tobytes()
            header = struct.pack("!I", len(payload))
            self.network_send_socket.sendall(header + payload)
        except OSError:
            self._close_network_sender()

    def _recv_exact(self, conn: socket.socket, size: int) -> bytes | None:
        buffer = bytearray()

        while len(buffer) < size and self.running and not self.stop_event.is_set():
            try:
                chunk = conn.recv(size - len(buffer))
            except OSError:
                return None

            if not chunk:
                return None

            buffer.extend(chunk)

        if len(buffer) != size:
            return None

        return bytes(buffer)

    def _run_network_receiver(self, allowed_peer_ip: str | None) -> None:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            server_socket.bind(("0.0.0.0", NETWORK_STREAM_PORT))
            server_socket.listen(1)
            server_socket.settimeout(1.0)
            self.network_server_socket = server_socket

            while self.running and not self.stop_event.is_set():
                try:
                    conn, addr = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                peer_ip = addr[0]
                if allowed_peer_ip and peer_ip != allowed_peer_ip:
                    conn.close()
                    continue

                conn.settimeout(1.0)

                try:
                    while self.running and not self.stop_event.is_set():
                        header = self._recv_exact(conn, 4)
                        if header is None:
                            break

                        payload_size = struct.unpack("!I", header)[0]
                        if payload_size <= 0:
                            continue

                        payload = self._recv_exact(conn, payload_size)
                        if payload is None:
                            break

                        frame_array = np.frombuffer(payload, dtype=np.uint8)
                        frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                        if frame is None:
                            continue

                        with self.frame_lock:
                            self.latest_frame = frame
                            self.frame_seq += 1
                finally:
                    conn.close()
        finally:
            try:
                server_socket.close()
            except OSError:
                pass
            if self.network_server_socket is server_socket:
                self.network_server_socket = None

    def _configure_capture(self, cap) -> None:
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if FFMPEG_CAPTURE_OPTIONS and hasattr(cv2, "CAP_PROP_HW_ACCELERATION"):
            cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_NONE)

    def enqueue_frames(self, cap) -> None:
        while self.running and not self.stop_event.is_set():
            try:
                ret, frame = cap.read()
            except cv2.error:
                break

            if not ret:
                if self.stop_event.is_set():
                    break
                time.sleep(0.001)
                continue

            with self.frame_lock:
                self.latest_frame = frame
                self.frame_seq += 1

    def _start_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Paramètres", self._tray_open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Afficher l'aperçu", self._tray_show_preview),
            pystray.MenuItem("Masquer l'aperçu", self._tray_hide_preview),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Redémarrer", self._tray_restart),
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

    def _handle_preview_window(self, frame, window_title: str) -> bool:
        cv2.imshow(window_title, frame)
        self._apply_preview_window_icon(window_title)
        self.preview_window_open = True

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            decision = self._ask_close_or_minimize()
            if decision == "close":
                self.stop_event.set()
                return False
            self._show_preview(False)
            return True

        try:
            visible = cv2.getWindowProperty(window_title, cv2.WND_PROP_VISIBLE)
        except cv2.error:
            visible = 0

        if visible < 1 and not self.close_prompt_active:
            self.close_prompt_active = True
            decision = self._ask_close_or_minimize()
            if decision == "close":
                self.stop_event.set()
                return False
            self._show_preview(False)
            self.preview_window_open = False
            self.close_prompt_active = False
            return True

        if visible >= 1:
            self.close_prompt_active = False

        return True

    def _run_preview_loop(self) -> None:
        return

    def _get_latest_frame(self, last_seq: int) -> tuple[int, object | None]:
        with self.frame_lock:
            if self.frame_seq == last_seq or self.latest_frame is None:
                return last_seq, None

            return self.frame_seq, self.latest_frame.copy()

    def start(self) -> None:
        tray_thread = threading.Thread(target=self._start_tray, daemon=True)
        tray_thread.start()
        self.tray_ready.wait(timeout=2.0)

        print(f"[+] Démarrage en zone de notification ({self.res}p)...")

        peer_host = self._build_network_peer_host()
        cap = None
        width, height = (1920, 1080) if self.res == 1080 else (1280, 720)

        try:
            if self.api.start_webcam(self.res):
                self.local_webcam_active = True
                print("[+] GoPro détectée, mode émetteur activé.")
            else:
                print("[+] GoPro non détectée, mode récepteur activé.")
        except Exception:
            print("[+] GoPro non détectée, mode récepteur activé.")

        if self.local_webcam_active:
            stream_url = STREAM_URL
            keep_alive_thread = threading.Thread(target=self.api.keep_alive, args=(self.stop_event,), daemon=True)
            keep_alive_thread.start()

            cap = self._wait_for_stream_capture(stream_url, timeout_seconds=15.0)
            if cap is None:
                print("[-] Impossible d'ouvrir le flux local de la GoPro, passage en réception réseau.")
                self.local_webcam_active = False
                self._close_network_sender()

        if not self.local_webcam_active:
            receiver_thread = threading.Thread(target=self._run_network_receiver, args=(peer_host,), daemon=True)
            receiver_thread.start()
            if peer_host is None:
                print("[+] En attente d'un flux réseau entrant. Configure l'IP du PC distant dans les paramètres.")
            else:
                print(f"[+] En attente du flux réseau depuis {peer_host}.")

        if cap is not None:
            self._configure_capture(cap)

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

                last_seq = -1

                while self.running and not self.stop_event.is_set():
                    last_seq, frame = self._get_latest_frame(last_seq)
                    if frame is None:
                        time.sleep(0.001)
                        continue

                    frame = self._draw_chrono(frame)
                    cam.send(frame)

                    if self.local_webcam_active and peer_host is not None:
                        self._send_frame_to_peer(frame, peer_host)

                    if self.preview_enabled:
                        if not self._handle_preview_window(frame, self.window_title):
                            break

                    if self.preview_close_requested and self.preview_window_open:
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
                last_seq = -1
                while self.running and not self.stop_event.is_set():
                    last_seq, frame = self._get_latest_frame(last_seq)
                    if frame is None:
                        time.sleep(0.001)
                        continue
                    frame = self._draw_chrono(frame)
                    if not self._handle_preview_window(frame, self.window_title):
                        break
            else:
                self._run_headless_without_virtualcam()
        finally:
            print("[+] Arrêt proprement...")
            self.running = False
            self.stop_event.set()
            if cap is not None:
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
            if self.local_webcam_active:
                self.api.stop_webcam()
            self._close_network_sender()
            self._close_network_server()
            print("[+] Terminé.")