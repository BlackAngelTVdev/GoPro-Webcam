from __future__ import annotations

import time

import requests

from .config import FOV_MAP, GOPRO_IP


class GoProAPI:
    def __init__(self, ip: str = GOPRO_IP):
        self.ip = ip
        self.session = requests.Session()

    def start_webcam(self, res: int) -> bool:
        response = requests.get(f"http://{self.ip}/gp/gpWebcam/START?res={res}", timeout=5)
        return response.status_code == 200

    def set_fov(self, fov_name: str) -> bool:
        fov_id = FOV_MAP.get(fov_name, 0)
        response = requests.get(f"http://{self.ip}/gp/gpWebcam/FOV?fov={fov_id}", timeout=5)
        return response.status_code == 200

    def keep_alive(self, stop_event) -> None:
        while not stop_event.is_set():
            try:
                self.session.get(f"http://{self.ip}/gp/gpWebcam/VERSION", timeout=2)
            except requests.RequestException:
                pass
            time.sleep(2)

    def stop_webcam(self) -> None:
        try:
            requests.get(f"http://{self.ip}/gp/gpWebcam/STOP", timeout=2)
        except requests.RequestException:
            pass