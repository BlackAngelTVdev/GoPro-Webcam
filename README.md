# 🚀 GoPro-Webcam vB1.03
![Stars](https://img.shields.io/github/stars/BlackAngelTVdev/GoPro-Webcam?style=for-the-badge&color=yellow)
![Commits](https://img.shields.io/github/commit-activity/m/BlackAngelTVdev/GoPro-Webcam?style=for-the-badge&color=blue)
![Issues](https://img.shields.io/github/issues/BlackAngelTVdev/GoPro-Webcam?style=for-the-badge&color=orange)
![Forks](https://img.shields.io/github/forks/BlackAngelTVdev/GoPro-Webcam?style=for-the-badge&color=808080)
![Last Commit](https://img.shields.io/github/last-commit/BlackAngelTVdev/GoPro-Webcam?style=for-the-badge&color=blue)

> Outil pour streamer une GoPro (Hero en mode Webcam) vers OBS ou un aperçu local.

---

## 🧐 Aperçu
Capture le flux webcam de la GoPro et l'expose comme une webcam virtuelle pour OBS, avec option d'aperçu local, chronomètre et réglages orientés faible latence.

## ✨ Fonctionnalités
- ✅ Démarrage/arrêt automatique de la GoPro en mode Webcam
- ✅ Sortie webcam virtuelle compatible OBS (pyvirtualcam)
- ✅ Bascule automatique vers un aperçu local si OBS/virtualcam absent
- ✅ Icône dans la zone de notification avec `Afficher`, `Masquer` et `Quitter`
- ✅ Option `-c/--chrono` pour superposer un chronomètre
- ✅ Réglages optimisés faible-latence et lecture UDP via OpenCV

## 🛠 Tech Stack
| Technologie | Usage |
| :--- | :--- |
| Python 3.10+ | Langage principal |
| OpenCV (cv2) | Lecture du flux vidéo (FFmpeg backend) |
| pyvirtualcam | Sortie webcam virtuelle |
| requests | Contrôle HTTP de la GoPro |

## 🚀 Installation & Lancement

1. **Cloner le projet**
	```bash
	git clone https://github.com/BlackAngelTVdev/GoPro-Webcam.git
	cd GoPro-Webcam
	```
2. **Installer les dépendances**
	```bash
	python -m pip install -r requirements.txt
	```
3. **Lancer le script (exemples)**
	- Aperçu local avec chronomètre :
	  ```bash
	  python main.py --view -c
	  ```
	- Lancer pour OBS (mode par défaut) :
	  ```bash
	  python main.py
	  ```

## 🔧 Packaging en .exe (Windows)
Utilise PyInstaller pour créer un exécutable. Exemple:
```powershell
python -m pip install pyinstaller
python -m PyInstaller --onefile --name GoPro-Webcam main.py    # debug (console)
python -m PyInstaller --onefile --noconsole --name GoPro-Webcam main.py  # sans console
```
Après build, exécutable : `dist\\GoPro-Webcam.exe`.

## 📖 Utilisation rapide
```bash
# Aperçu local
dist\\GoPro-Webcam.exe --view -c

# Ou double‑clic sur dist\\GoPro-Webcam.exe pour lancer en mode par défaut
```

## 🤝 Contribution
1. Forkez le projet
2. Créez votre branche (git checkout -b feature/AmazingFeature)
3. Commit (git commit -m 'Add some AmazingFeature')
4. Push (git push origin feature/AmazingFeature)
5. Ouvrez une Pull Request

## 👤 Auteur

**BlackAngelTVdev**
![Follow](https://img.shields.io/github/followers/BlackAngelTVdev?label=Follow%20Me&style=social)

---
## 📄 Licence

Ce projet est sous licence :
![GitHub License](https://img.shields.io/github/license/BlackAngelTVdev/GoPro-Webcam?style=flat-square&color=blue)

### 🧑‍💻 Contributors

Merci à toutes les personnes qui contribuent au projet.

[![Contributors](https://contrib.rocks/image?repo=BlackAngelTVdev/GoPro-Webcam)](https://github.com/BlackAngelTVdev/GoPro-Webcam/graphs/contributors)