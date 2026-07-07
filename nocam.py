# -*- coding: utf-8 -*-
"""
NoCam — NOLAM
Appareil photo Windows ultra-simple : un GROS bouton rond qui pulse (facon app
Camera d'origine), la photo part dans la Pellicule (Camera Roll) -> OneDrive la
synchronise vers le PC du bureau.

Pourquoi ca marche la ou l'app Camera Microsoft plante :
- capture via DirectShow (CAP_DSHOW) en priorite -> ne passe PAS par le
  Frame Server UWP (celui qui crashe MFCORE.dll sur la Surface Go).
- dossier resolu via l'API Windows FOLDERID_CameraRoll -> suit automatiquement
  la Pellicule meme si OneDrive l'a deplacee (Known Folder Move).

v1.1 — apercu PLEIN ECRAN (mode cover, zero bande noire), controles qui FLOTTENT
en overlay sur le bord DROIT (ergonomie droitier : declencheur + zoom sous le
pouce), zoom numerique +/- (crop centre), splash logo NOLAM au lancement.
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

# paliers de zoom numerique (crop centre). 8 MP source -> net jusqu'a ~2.5x.
ZOOM_STEPS = [1.0, 1.5, 2.0, 2.5]

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


def find_asset(*names):
    """Retrouve un asset (logo/ico) que l'on soit en dev ou dans le bundle
    PyInstaller (qui peut aplatir assets/ a la racine du _MEIPASS)."""
    bases = (RES_DIR, APP_DIR,
             os.path.join(RES_DIR, "assets"), os.path.join(APP_DIR, "assets"))
    for n in names:
        for base in bases:
            p = os.path.join(base, n)
            if os.path.exists(p):
                return p
    return None


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


# ---------------------------------------------------------------- cadrage

def compute_crop(fw, fh, target_w, target_h, zoom=1.0):
    """Rectangle source (x, y, w, h) a decouper dans la frame pour REMPLIR
    la cible (mode cover : zero bande noire) au ratio target_w/target_h, avec
    un zoom numerique (>1 = resserre au centre).

    Fonction PURE (aucun cv2/GUI/camera) -> testable au banc. Seul le RATIO de
    la cible compte : passer la resolution ecran donne un crop en pixels capteur
    a pleine definition, qu'on redimensionne ensuite (apercu) ou qu'on garde tel
    quel (photo enregistree)."""
    if fw <= 0 or fh <= 0 or target_w <= 0 or target_h <= 0:
        return 0, 0, max(1, int(fw)), max(1, int(fh))
    zoom = max(1.0, float(zoom))
    target_ar = target_w / target_h
    frame_ar = fw / fh
    if frame_ar > target_ar:
        # frame plus large que la cible -> on rogne les cotes
        crop_h = float(fh)
        crop_w = fh * target_ar
    else:
        # frame plus etroite -> on rogne haut/bas
        crop_w = float(fw)
        crop_h = fw / target_ar
    crop_w /= zoom
    crop_h /= zoom
    crop_w = max(1, min(fw, int(round(crop_w))))
    crop_h = max(1, min(fh, int(round(crop_h))))
    x = max(0, (fw - crop_w) // 2)
    y = max(0, (fh - crop_h) // 2)
    return int(x), int(y), int(crop_w), int(crop_h)


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

    # -- maths de cadrage (pas de camera necessaire) -------------------
    ok = True
    # capteur 4:3 (3264x2448) sur ecran 3:2 -> cover rogne le HAUT/BAS
    x, y, w, h = compute_crop(3264, 2448, 1500, 1000, 1.0)
    ok &= (w == 3264)                 # pleine largeur gardee
    ok &= abs(w / h - 1500 / 1000) < 0.01
    ok &= (x == 0 and y > 0)          # rogne verticalement, centre
    # zoom 2x -> zone deux fois plus petite, toujours centree
    x2, y2, w2, h2 = compute_crop(3264, 2448, 1500, 1000, 2.0)
    ok &= abs(w2 - w / 2) <= 1 and abs(h2 - h / 2) <= 1
    ok &= (x2 > x and y2 > y)
    # garde-fous
    gx, gy, gw, gh = compute_crop(0, 0, 100, 100, 1.0)
    ok &= (gw >= 1 and gh >= 1)
    print(f"  compute_crop: {'OK' if ok else 'ECHEC'}  "
          f"(z1={w}x{h}@{x},{y}  z2={w2}x{h2}@{x2},{y2})")

    found = []
    for i in range(3):
        cap, name = open_camera(i)
        if cap:
            found.append((i, name))
            cap.release()
    print(f"  cameras: {found if found else 'AUCUNE (normal sans webcam)'}")
    print("  OK" if ok else "  ATTENTION: maths de cadrage KO")
    return ok


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
        ico = find_asset("nocam.ico")
        if ico:
            root.iconbitmap(ico)
    except Exception:
        pass

    scr_w = root.winfo_screenwidth()
    scr_h = root.winfo_screenheight()

    state = {
        "cap": None, "grab": None, "index": cam_index,
        "flash_until": 0.0, "msg": "", "msg_err": False, "msg_until": 0.0,
        "saving": False, "t0": time.time(), "shot_anim": 0.0,
        "zoom_i": 0,                                   # index dans ZOOM_STEPS
        "splash_until": time.time() + 1.4,             # logo NOLAM au demarrage
    }

    # ---- une seule scene plein ecran : image DESSOUS, controles DESSUS --
    stage = tk.Canvas(root, bg=BG, highlightthickness=0, bd=0)
    stage.pack(fill="both", expand=True)

    tkimg = {"cam": None, "splash": None}              # refs anti-GC

    # image camera (tag "cam"), placee en haut-gauche, remplit l'ecran
    stage.create_image(0, 0, anchor="nw", image="", tags=("cam",))

    # message "camera introuvable" (tag propre, gere a part de "ctrl")
    stage.create_text(0, 0, text="", fill=RED, font=("Segoe UI", 26),
                      justify="center", tags=("noframe",))

    # -- branding discret (le gros logo est sur le splash) ---------------
    stage.create_text(0, 0, anchor="nw", text=f"{BRAND} · {APP_NAME}",
                      fill=GREY, font=("Segoe UI", 12, "bold"),
                      tags=("ctrl", "brand"))
    # -- message de confirmation (bas-gauche) ----------------------------
    stage.create_text(0, 0, anchor="sw", text="", fill=GREY,
                      font=("Segoe UI", 12), tags=("ctrl", "info"))

    # -- bouton fermer ✕ (haut-droite) -----------------------------------
    stage.create_oval(0, 0, 0, 0, fill=BG2, outline="", tags=("ctrl", "close"))
    stage.create_text(0, 0, text="✕", fill=GREY, font=("Segoe UI", 18, "bold"),
                      tags=("ctrl", "close"))
    # -- bouton changer de camera ⟳ --------------------------------------
    stage.create_oval(0, 0, 0, 0, fill=BG2, outline="", tags=("ctrl", "switch"))
    stage.create_text(0, 0, text="⟳", fill="white", font=("Segoe UI", 18, "bold"),
                      tags=("ctrl", "switch"))

    # -- zoom + / - (colonne droite, au-dessus du declencheur) -----------
    stage.create_oval(0, 0, 0, 0, fill=BG2, outline="", tags=("ctrl", "zin"))
    stage.create_text(0, 0, text="+", fill="white", font=("Segoe UI", 28, "bold"),
                      tags=("ctrl", "zin"))
    stage.create_oval(0, 0, 0, 0, fill=BG2, outline="", tags=("ctrl", "zout"))
    stage.create_text(0, 0, text="–", fill="white", font=("Segoe UI", 28, "bold"),
                      tags=("ctrl", "zout"))
    stage.create_text(0, 0, text="1×", fill=GREEN_HI, font=("Segoe UI", 13, "bold"),
                      tags=("ctrl", "zlabel"))

    # -- declencheur rond qui PULSE (bord droit, sous le pouce) -----------
    glow = stage.create_oval(0, 0, 0, 0, outline=GREEN, width=3, tags=("ctrl", "shutter"))
    ring = stage.create_oval(0, 0, 0, 0, outline="white", width=5, tags=("ctrl", "shutter"))
    disc = stage.create_oval(0, 0, 0, 0, fill=GREEN, outline="", tags=("ctrl", "shutter"))
    stage.create_text(0, 0, text="PHOTO", fill="white",
                      font=("Segoe UI", 20, "bold"), tags=("ctrl", "shutter"))

    # -- splash (dessine EN DERNIER -> au-dessus de tout) ----------------
    stage.create_rectangle(0, 0, 0, 0, fill=BG, outline="", tags=("splash", "sp_bg"))
    try:
        lp = find_asset("nolam-logo.png", "nolam_logo.png")
        if lp:
            im = Image.open(lp).convert("RGBA")
            tw = int(scr_w * 0.42)
            th = max(1, int(im.height * tw / im.width))
            im = im.resize((tw, th), Image.LANCZOS)
            tkimg["splash"] = ImageTk.PhotoImage(im)
    except Exception as e:
        log(f"splash logo KO: {e}")
    stage.create_image(0, 0, image=tkimg["splash"] or "", tags=("splash", "sp_logo"))
    if not tkimg["splash"]:
        stage.create_text(0, 0, text=f"{BRAND}\n{APP_NAME}", fill="white",
                          justify="center", font=("Segoe UI", 40, "bold"),
                          tags=("splash", "sp_logo"))

    # ---- feedback -------------------------------------------------------
    def flash_msg(text, err=False):
        state["msg"] = text
        state["msg_err"] = err
        state["msg_until"] = time.time() + 1.8

    # ---- camera ---------------------------------------------------------
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

    def switch_camera(event=None):
        nxt = (state["index"] + 1) % 3
        for _ in range(3):
            if start_camera(nxt):
                flash_msg(f"Caméra {nxt}")
                return
            nxt = (nxt + 1) % 3
        flash_msg("Pas d'autre caméra", err=True)

    # ---- zoom -----------------------------------------------------------
    def set_zoom(delta, event=None):
        state["zoom_i"] = max(0, min(len(ZOOM_STEPS) - 1, state["zoom_i"] + delta))
        z = ZOOM_STEPS[state["zoom_i"]]
        flash_msg(f"Zoom {z:g}×")

    # ---- prise de photo (WYSIWYG : on enregistre ce qui est cadre) ------
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
            # meme cadrage que l'apercu (cover + zoom), mais a pleine
            # definition capteur -> la photo = exactement ce qu'on voit.
            fh, fw = frame.shape[:2]
            tw = stage.winfo_width() or scr_w
            th = stage.winfo_height() or scr_h
            x, y, cw, ch = compute_crop(fw, fh, tw, th, ZOOM_STEPS[state["zoom_i"]])
            shot = frame[y:y + ch, x:x + cw]
            name = f"Foto_{datetime.datetime.now():%Y-%m-%d_%H-%M-%S}.jpg"
            path = os.path.join(save_dir, name)
            ok, buf = cv2.imencode(".jpg", shot, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                raise RuntimeError("encode JPEG KO")
            with open(path, "wb") as f:
                f.write(buf.tobytes())
            log(f"photo -> {path} ({cw}x{ch}, zoom {ZOOM_STEPS[state['zoom_i']]:g}x)")
            flash_msg("✓  Photo enregistrée")
        except Exception as e:
            log(f"ERREUR sauvegarde: {e}\n{traceback.format_exc()}")
            flash_msg("ERREUR — photo PAS enregistrée", err=True)
        finally:
            state["saving"] = False

    def do_quit(event=None):
        try:
            if state["grab"]:
                state["grab"].stop()
            if state["cap"]:
                state["cap"].release()
        except Exception:
            pass
        root.destroy()

    # ---- liaisons tactiles / clavier ------------------------------------
    stage.tag_bind("shutter", "<Button-1>", take_photo)
    stage.tag_bind("zin", "<Button-1>", lambda e: set_zoom(+1))
    stage.tag_bind("zout", "<Button-1>", lambda e: set_zoom(-1))
    stage.tag_bind("switch", "<Button-1>", switch_camera)
    stage.tag_bind("close", "<Button-1>", do_quit)
    root.bind("<space>", take_photo)
    root.bind("<Escape>", do_quit)
    root.bind("<plus>", lambda e: set_zoom(+1))
    root.bind("<minus>", lambda e: set_zoom(-1))

    # ---- interpolation couleur pour la pulsation ------------------------
    def lerp_color(c1, c2, t):
        a = tuple(int(c1[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(c2[i:i + 2], 16) for i in (1, 3, 5))
        m = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        return f"#{m[0]:02x}{m[1]:02x}{m[2]:02x}"

    def place_circle(tag, cx, cy, r):
        # 1er item du tag = le disque de fond (cercle), on le repositionne ;
        # le texte du meme tag est centre sur (cx, cy).
        items = stage.find_withtag(tag)
        if items:
            stage.coords(items[0], cx - r, cy - r, cx + r, cy + r)
            for it in items[1:]:
                stage.coords(it, cx, cy)

    # ---- boucle de rendu ------------------------------------------------
    def render():
        now = time.time()
        W = stage.winfo_width() or scr_w
        H = stage.winfo_height() or scr_h

        # -- SPLASH : logo NOLAM, on masque le reste ---------------------
        if now < state["splash_until"]:
            stage.itemconfigure("splash", state="normal")
            stage.itemconfigure("ctrl", state="hidden")
            stage.itemconfigure("cam", state="hidden")
            stage.itemconfigure("noframe", state="hidden")
            stage.coords("sp_bg", 0, 0, W, H)
            stage.coords("sp_logo", W // 2, H // 2)
            root.after(40, render)
            return
        stage.itemconfigure("splash", state="hidden")
        stage.itemconfigure("ctrl", state="normal")
        stage.itemconfigure("cam", state="normal")

        # -- apercu plein ecran (cover + zoom) ---------------------------
        g = state["grab"]
        frame = g.latest() if g else None
        if frame is not None and W > 50 and H > 50:
            stage.itemconfigure("noframe", state="hidden")
            fh, fw = frame.shape[:2]
            x, y, cw, ch = compute_crop(fw, fh, W, H, ZOOM_STEPS[state["zoom_i"]])
            crop = frame[y:y + ch, x:x + cw]
            disp = cv2.resize(crop, (W, H), interpolation=cv2.INTER_LINEAR)
            disp = cv2.cvtColor(disp, cv2.COLOR_BGR2RGB)
            if now < state["flash_until"]:
                white = 255 + 0 * disp
                disp = cv2.addWeighted(disp, 0.3, white, 0.7, 0)
            img = ImageTk.PhotoImage(Image.fromarray(disp))
            tkimg["cam"] = img
            stage.itemconfigure("cam", image=img)
        elif frame is None:
            stage.itemconfigure("cam", image="")
            stage.itemconfigure("noframe", state="normal")
            stage.coords("noframe", W // 2, H // 2)
            stage.itemconfigure(
                "noframe",
                text="Caméra introuvable\n\nTouchez  ⟳  pour réessayer")

        # -- positions des controles (bord droit, ergonomie droitier) ----
        stage.coords("brand", 22, 18)
        stage.coords("info", 22, H - 22)

        place_circle("close", W - 52, 52, 26)
        place_circle("switch", W - 52, 116, 26)

        # declencheur (pulsation : respiration ~2s + kick au declenchement)
        cx = W - 120
        cy = H - 150
        breathe = (math.sin((now - state["t0"]) * math.pi) + 1) / 2
        kick = max(0.0, 1.0 - (now - state["shot_anim"]) * 3.5) if state["shot_anim"] else 0.0
        r_disc = 58 + 3 * breathe + 8 * kick
        r_ring = r_disc + 8
        r_glow = r_ring + 6 + 10 * breathe + 14 * kick
        col = lerp_color(GREEN, GREEN_HI, 0.35 * breathe + 0.65 * kick)
        sh = stage.find_withtag("shutter")
        # ordre de creation : glow, ring, disc, label
        stage.coords(sh[0], cx - r_glow, cy - r_glow, cx + r_glow, cy + r_glow)
        stage.coords(sh[1], cx - r_ring, cy - r_ring, cx + r_ring, cy + r_ring)
        stage.coords(sh[2], cx - r_disc, cy - r_disc, cx + r_disc, cy + r_disc)
        stage.coords(sh[3], cx, cy)
        stage.itemconfigure(sh[2], fill=col)
        stage.itemconfigure(sh[0], outline=lerp_color(BG, GREEN_HI, 0.25 + 0.45 * breathe + 0.3 * kick))

        # zoom : + au-dessus, - en dessous, palier courant a gauche
        place_circle("zin", cx, cy - 235, 40)
        place_circle("zout", cx, cy - 145, 40)
        z = ZOOM_STEPS[state["zoom_i"]]
        stage.coords("zlabel", cx - 78, cy - 190)
        stage.itemconfigure("zlabel", text=f"{z:g}×")

        # -- messages / chemin de sauvegarde -----------------------------
        if now < state["msg_until"]:
            stage.itemconfigure("info", text=state["msg"],
                                fill=RED if state["msg_err"] else GREEN_HI,
                                font=("Segoe UI", 14, "bold"))
        else:
            stage.itemconfigure("info", text=f"→ {save_dir}", fill=GREY,
                                font=("Segoe UI", 11))

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
