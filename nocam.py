# -*- coding: utf-8 -*-
"""
PhotoCam — dpan-BUG
Appareil photo Windows ultra-simple : un GROS bouton rond qui pulse (facon app
Camera d'origine), la photo part dans la Pellicule (Camera Roll) -> OneDrive la
synchronise vers le PC du bureau.

Pourquoi ca marche la ou l'app Camera Microsoft plante :
- capture via DirectShow (CAP_DSHOW) en priorite -> ne passe PAS par le
  Frame Server UWP (celui qui crashe MFCORE.dll sur la Surface Go).
- dossier resolu via l'API Windows FOLDERID_CameraRoll -> suit automatiquement
  la Pellicule meme si OneDrive l'a deplacee (Known Folder Move).
"""

import os
import sys
import json
import math
import time
import ctypes
import datetime
import threading
import traceback
from ctypes import wintypes

import cv2

APP_NAME = "NoCam"
BRAND = "NOLAM"
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)
LOG_PATH = os.path.join(APP_DIR, "nocam.log")
CFG_PATH = os.path.join(APP_DIR, "nocam.cfg")

# palette
BG = "#0b0f14"
BG2 = "#121922"
GREEN = "#1f9d44"
GREEN_HI = "#3dff7c"
BLUE = "#2196f3"
GREY = "#8aa0b4"
RED = "#ff7070"

# ---------------------------------------------------------------- utilitaires

def log(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass


def camera_roll_path():
    """Resout le VRAI dossier Pellicule via l'API Windows (suit OneDrive KFM)."""
    try:
        import uuid

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        u = uuid.UUID("{AB5FB87B-7CE2-4F83-915D-550846C9537B}")  # FOLDERID_CameraRoll
        g = GUID()
        g.Data1, g.Data2, g.Data3 = u.time_low, u.time_mid, u.time_hi_version
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b

        pth = ctypes.c_wchar_p()
        res = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(g), 0, None, ctypes.byref(pth)
        )
        if res == 0 and pth.value:
            p = pth.value
            ctypes.windll.ole32.CoTaskMemFree(pth)
            if os.path.isdir(p):
                return p
    except Exception as e:
        log(f"KnownFolder API KO: {e}")

    home = os.path.expanduser("~")
    for cand in (
        os.path.join(home, "OneDrive", "Pictures", "Camera Roll"),
        os.path.join(home, "OneDrive", "Images", "Pellicule"),
        os.path.join(home, "Pictures", "Camera Roll"),
    ):
        if os.path.isdir(cand):
            return cand
    p = os.path.join(home, "Pictures", "Camera Roll")
    os.makedirs(p, exist_ok=True)
    return p


# ---------------------------------------------------------------- camera

BACKENDS = [
    (cv2.CAP_DSHOW, "DirectShow"),
    (cv2.CAP_MSMF, "MediaFoundation"),
]

REAR_HINTS = ("rear", "back", "arriere", "arrière", "world")


def pick_default_camera():
    """1er lancement : vise la camera ARRIERE (Surface: 'Microsoft Camera Rear').
    pygrabber liste les noms DirectShow dans le MEME ordre que les index CAP_DSHOW."""
    try:
        from pygrabber.dshow_graph import FilterGraph
        names = FilterGraph().get_input_devices()
        log(f"cameras DirectShow: {names}")
        for i, n in enumerate(names):
            if any(h in n.lower() for h in REAR_HINTS):
                log(f"camera ARRIERE detectee -> index {i} ({n})")
                return i
    except Exception as e:
        log(f"enum pygrabber KO: {e}")
    return 0


def open_camera(index):
    for be, name in BACKENDS:
        cap = cv2.VideoCapture(index, be)
        if cap.isOpened():
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3264)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2448)
            except Exception:
                pass
            ok, frame = cap.read()
            if ok and frame is not None:
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                log(f"camera {index} via {name} ({w}x{h})")
                return cap, name
            cap.release()
    return None, None


class Grabber(threading.Thread):
    def __init__(self, cap):
        super().__init__(daemon=True)
        self.cap = cap
        self.lock = threading.Lock()
        self.frame = None
        self.running = True

    def run(self):
        while self.running:
            try:
                ok, f = self.cap.read()
                if ok and f is not None:
                    with self.lock:
                        self.frame = f
                else:
                    time.sleep(0.05)
            except Exception:
                time.sleep(0.1)

    def latest(self):
        with self.lock:
            return None if self.frame is None else self.frame.copy()

    def stop(self):
        self.running = False


# ---------------------------------------------------------------- self-test

def selftest():
    print(f"{APP_NAME} self-test")
    print(f"  pellicule -> {camera_roll_path()}")
    found = []
    for i in range(3):
        cap, name = open_camera(i)
        if cap:
            found.append((i, name))
            cap.release()
    print(f"  cameras: {found if found else 'AUCUNE (normal sans webcam)'}")
    print("  OK")


# ---------------------------------------------------------------- application

def main():
    import tkinter as tk
    from PIL import Image, ImageTk

    save_dir = camera_roll_path()
    cfg = load_cfg()
    if "camera_index" in cfg:
        cam_index = int(cfg["camera_index"])          # choix memorise (⟳)
    else:
        cam_index = pick_default_camera()             # 1er lancement: ARRIERE
    log(f"start — pellicule={save_dir} cam={cam_index}")

    root = tk.Tk()
    root.title(f"{APP_NAME} — {BRAND}")
    root.configure(bg=BG)
    root.attributes("-fullscreen", True)
    try:
        ico = os.path.join(RES_DIR, "nocam.ico")
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass

    state = {"cap": None, "grab": None, "index": cam_index, "flash_until": 0.0,
             "msg": "", "msg_err": False, "msg_until": 0.0, "saving": False,
             "t0": time.time(), "shot_anim": 0.0}

    # ---- barre du haut -------------------------------------------
    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", side="top")

    brand = tk.Label(top, text=f"⚙ {APP_NAME}", font=("Segoe UI", 15, "bold"),
                     bg=BG, fg=BLUE)
    brand.pack(side="left", padx=(12, 0), pady=8)
    tk.Label(top, text=BRAND, font=("Segoe UI", 15, "bold"),
             bg=BG, fg="white").pack(side="left", padx=(6, 0))

    def do_quit(event=None):
        try:
            if state["grab"]:
                state["grab"].stop()
            if state["cap"]:
                state["cap"].release()
        except Exception:
            pass
        root.destroy()

    btn_close = tk.Button(top, text="✕", font=("Segoe UI", 15, "bold"),
                          bg=BG2, fg=GREY, activebackground="#5c2b2b",
                          activeforeground="white", bd=0, padx=18, pady=6,
                          command=do_quit)
    btn_close.pack(side="right", padx=8, pady=6)

    btn_switch = tk.Button(top, text="⟳  caméra", font=("Segoe UI", 13),
                           bg=BG2, fg="white", activebackground="#2a3947",
                           activeforeground="white", bd=0, padx=16, pady=6)
    btn_switch.pack(side="right", padx=4, pady=6)

    info = tk.Label(top, text="", font=("Segoe UI", 11), bg=BG, fg=GREY)
    info.pack(side="left", padx=14)

    # ---- barre du bas : declencheur rond qui PULSE ----------------
    # PACKEE AVANT l'apercu -> sa place est RESERVEE, l'image ne peut
    # jamais la pousser hors ecran (bug v1 : boucle de layout Tkinter).
    SH_H = 190
    shutter = tk.Canvas(root, height=SH_H, bg=BG, highlightthickness=0)
    shutter.pack(fill="x", side="bottom")
    shutter.pack_propagate(False)

    # ---- apercu (packe EN DERNIER : prend uniquement le reste) ----
    preview = tk.Label(root, bg=BG, bd=0, highlightthickness=0)
    preview.pack(fill="both", expand=True)

    def shutter_geometry():
        w = shutter.winfo_width() or root.winfo_screenwidth()
        return w // 2, SH_H // 2

    # dessine une premiere fois (sera anime dans render())
    cx, cy = 400, SH_H // 2
    glow = shutter.create_oval(0, 0, 0, 0, outline=GREEN, width=3)
    ring = shutter.create_oval(0, 0, 0, 0, outline="white", width=5)
    disc = shutter.create_oval(0, 0, 0, 0, fill=GREEN, outline="")
    label = shutter.create_text(0, 0, text="PHOTO", fill="white",
                                font=("Segoe UI", 22, "bold"))

    # ---- feedback -------------------------------------------------
    def flash_msg(text, err=False):
        state["msg"] = text
        state["msg_err"] = err
        state["msg_until"] = time.time() + 1.8

    # ---- camera ---------------------------------------------------
    def start_camera(index):
        if state["grab"]:
            state["grab"].stop()
        if state["cap"]:
            try:
                state["cap"].release()
            except Exception:
                pass
        state["cap"], _ = open_camera(index)
        if state["cap"]:
            state["index"] = index
            state["grab"] = Grabber(state["cap"])
            state["grab"].start()
            cfg["camera_index"] = index
            save_cfg(cfg)
            return True
        return False

    def switch_camera():
        nxt = (state["index"] + 1) % 3
        for _ in range(3):
            if start_camera(nxt):
                flash_msg(f"Caméra {nxt}")
                return
            nxt = (nxt + 1) % 3
        flash_msg("Pas d'autre caméra", err=True)

    btn_switch.configure(command=switch_camera)

    # ---- prise de photo -------------------------------------------
    def take_photo(event=None):
        if state["saving"]:
            return
        g = state["grab"]
        frame = g.latest() if g else None
        if frame is None:
            flash_msg("Caméra pas prête…", err=True)
            return
        state["saving"] = True
        state["flash_until"] = time.time() + 0.22
        state["shot_anim"] = time.time()
        try:
            name = f"Foto_{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}.jpg"
            path = os.path.join(save_dir, name)
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise RuntimeError("encode JPEG KO")
            with open(path, "wb") as f:
                f.write(buf.tobytes())
            log(f"photo -> {path}")
            flash_msg("✓  Photo enregistrée")
        except Exception as e:
            log(f"ERREUR sauvegarde: {e}\n{traceback.format_exc()}")
            flash_msg("ERREUR — photo PAS enregistrée", err=True)
        finally:
            state["saving"] = False

    for item in (glow, ring, disc, label):
        shutter.tag_bind(item, "<Button-1>", take_photo)
    shutter.bind("<Button-1>", lambda e: take_photo() if
                 (abs(e.x - shutter_geometry()[0]) < 110 and True) else None)
    root.bind("<space>", take_photo)
    root.bind("<Escape>", do_quit)

    # ---- interpolation couleur pour la pulsation ------------------
    def lerp_color(c1, c2, t):
        a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
        m = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        return f"#{m[0]:02x}{m[1]:02x}{m[2]:02x}"

    tkimg_holder = {"img": None}

    def render():
        now = time.time()
        g = state["grab"]
        frame = g.latest() if g else None

        # -- apercu (marge -6px : l'image ne peut JAMAIS depasser sa case)
        w = (preview.winfo_width() or 800) - 6
        h = (preview.winfo_height() or 420) - 6
        if frame is not None and w > 50 and h > 50:
            fh, fw = frame.shape[:2]
            scale = min(w / fw, h / fh)
            disp = cv2.resize(frame, (max(1, int(fw * scale)), max(1, int(fh * scale))),
                              interpolation=cv2.INTER_LINEAR)
            disp = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
            if now < state["flash_until"]:
                white = 255 + 0 * disp
                disp = cv2.addWeighted(disp, 0.3, white, 0.7, 0)
            img = ImageTk.PhotoImage(Image.fromarray(disp))
            tkimg_holder["img"] = img
            preview.configure(image=img, text="")
        elif frame is None:
            preview.configure(
                image="", text="Caméra introuvable\n\nTouchez  ⟳ caméra  pour réessayer",
                font=("Segoe UI", 22), fg=RED, bg=BG,
            )

        # -- pulsation du declencheur (respiration ~2s + kick au declenchement)
        cx, cy = shutter_geometry()
        breathe = (math.sin((now - state["t0"]) * math.pi) + 1) / 2   # 0..1
        kick = max(0.0, 1.0 - (now - state["shot_anim"]) * 3.5) if state["shot_anim"] else 0.0
        r_disc = 58 + 3 * breathe + 8 * kick
        r_ring = r_disc + 8
        r_glow = r_ring + 6 + 10 * breathe + 14 * kick
        col = lerp_color(GREEN, GREEN_HI, 0.35 * breathe + 0.65 * kick)
        shutter.coords(glow, cx - r_glow, cy - r_glow, cx + r_glow, cy + r_glow)
        shutter.coords(ring, cx - r_ring, cy - r_ring, cx + r_ring, cy + r_ring)
        shutter.coords(disc, cx - r_disc, cy - r_disc, cx + r_disc, cy + r_disc)
        shutter.coords(label, cx, cy)
        shutter.itemconfigure(disc, fill=col)
        shutter.itemconfigure(glow, outline=lerp_color(BG, GREEN_HI, 0.25 + 0.45 * breathe + 0.3 * kick))

        # -- messages
        if now < state["msg_until"]:
            info.configure(text=state["msg"],
                           fg=RED if state["msg_err"] else GREEN_HI,
                           font=("Segoe UI", 15, "bold"))
        else:
            info.configure(text=f"→ {save_dir}", fg=GREY, font=("Segoe UI", 10))

        root.after(50, render)   # ~20 fps, doux pour le Pentium

    if not start_camera(cam_index):
        for i in range(3):
            if i != cam_index and start_camera(i):
                break

    render()
    root.mainloop()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        try:
            main()
        except Exception as e:
            log(f"CRASH: {e}\n{traceback.format_exc()}")
            raise
