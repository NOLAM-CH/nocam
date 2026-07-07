<p align="center"><img src="assets/nocam-icon.png" width="170" alt="NoCam — NOLAM"></p>

# 📷 NoCam

> **NOLAM, NoCam.** *(chantez-le, vous l'avez déjà en tête)* 🎵
>
> La petite app photo Windows qui dit **non** : non à la télémétrie, non au Store,
> non aux comptes, non aux mises à jour qui cassent tout un matin de semaine.

*A [NOLAM](https://nolam.ch) project — No GAFAM.* · [English below](#-english)

---

## L'histoire vraie

Un matin de juillet 2026, une mise à jour automatique de l'app **Caméra Microsoft**
(`2026.2605.7.0`) s'est mise à crasher (`MFCORE.dll`) sur la tablette Surface d'une
carrosserie — l'outil de travail qui photographie les véhicules accidentés. Matériel
sain, pilotes sains : **seule l'app fournie par l'OS était cassée**, et impossible de
revenir en arrière proprement.

Alors on a écrit NoCam en une demi-heure. Elle a remis le client au travail le jour
même, et elle ne se mettra **jamais** à jour dans son dos.

## Ce qu'elle fait

- **Un gros bouton rond qui pulse.** Vous appuyez, la photo est prise. C'est tout.
- Les photos tombent dans la **Pellicule** (Camera Roll) → si OneDrive/autre la
  synchronise déjà, votre flux existant continue tel quel.
- **Caméra arrière choisie automatiquement** au premier lancement (tablettes) ;
  bouton ⟳ pour changer, choix mémorisé.
- Fichiers horodatés `Foto_2026-07-02_15-04-33.jpg` → tri chronologique naturel.
- Plein écran, pensé tactile, lisible par n'importe qui.

## Ce qu'elle ne fait PAS (le manifeste)

- ❌ **Zéro télémétrie, zéro phone-home** — elle n'ouvre aucune connexion réseau.
- ❌ Zéro Store, zéro compte, zéro abonnement, zéro pub.
- ❌ Zéro mise à jour silencieuse — c'est **vous** qui décidez ce qui tourne chez vous.

## Pourquoi elle marche là où l'app Microsoft plantait

- Capture **DirectShow** en priorité (fallback Media Foundation) → contourne le
  *Windows Camera Frame Server*, le composant UWP qui crashait.
- Dossier résolu via l'API Windows **`FOLDERID_CameraRoll`** → le vrai dossier
  Pellicule, même déplacé par OneDrive (Known Folder Move).

## Build (Windows 10/11)

```bat
python -m pip install opencv-python pillow pyinstaller pygrabber comtypes
python nocam.py --selftest
python -m PyInstaller --noconfirm --windowed --name NoCam --icon nocam.ico --add-data "nocam.ico;." --add-data "assets/nolam-logo.png;." nocam.py
:: -> dist\NoCam\  (garder le dossier entier ; onedir = démarrage rapide sur petites machines)
:: le --add-data du logo est requis depuis la v1.1 (splash NOLAM au lancement)
```

Binaire non signé → SmartScreen demandera confirmation au premier lancement.
Vérifier `Confidentialité > Caméra >` accès autorisé aux applications de bureau.

## Licence

**GPL-3.0-or-later** — voir [LICENSE](LICENSE) et [NOTICE](NOTICE).
© 2026 NOLAM / dpan-Bug (Suisse).

---

## 🇬🇧 English

**NoCam** — the tiny Windows camera app that says **no**: no telemetry, no Store,
no accounts, no silent updates that break your morning.

**True story:** in July 2026, an automatic update of the Microsoft Camera app
started crashing (`MFCORE.dll`) on a body shop's Surface tablet — the tool they use
to photograph damaged vehicles. Hardware fine, drivers fine, only the OS-bundled
app was broken, with no clean rollback. NoCam was written in half an hour and put
the shop back to work the same day.

**What it does:** one big pulsing round button; photos land in the **Camera Roll**
(so an existing OneDrive sync keeps working untouched); rear camera auto-selected
on tablets (⟳ to switch, remembered); timestamped filenames; fullscreen,
touch-first.

**What it never does:** no telemetry, no phone-home (it opens zero network
connections), no Store, no account, no silent updates.

**Why it works where the stock app crashed:** DirectShow capture first (bypasses
the Windows Camera Frame Server), and the Camera Roll is resolved through the
`FOLDERID_CameraRoll` API — correct even when OneDrive has moved the folder.

Build: see above. License: **GPL-3.0-or-later** — see [LICENSE](LICENSE) & [NOTICE](NOTICE).
