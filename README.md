# GoPro Webcam — Stream vers OBS

Petit utilitaire Python pour streamer une GoPro (Hero 9) via UDP vers une webcam virtuelle (OBS) en utilisant `pyvirtualcam` et OpenCV.

Usage rapide:

```bash
python main.py --res 1080 [-c] [--view]
```

Notes:

Le projet ne tente plus de modifier le FOV ou d'autres réglages qui ne passent pas proprement par l'API webcam GoPro. Il démarre le flux webcam avec la résolution demandée, puis transmet les images vers la sortie virtuelle.

Dépendances:

```bash
pip install -r requirements.txt
```