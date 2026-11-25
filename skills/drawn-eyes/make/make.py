#!/usr/bin/env python3
"""Draws a drawn-eyes Short on your own computer, from your own pictures and your own voice.

    python3 make.py tidy  raw.wav voice.wav    close the pauses in a voice take
    python3 make.py words voice.wav words.txt  when each word is said        -> words.json
    python3 make.py faces                      where the eyes and mouth are  -> faces.json, faces-1.jpg ...
    python3 make.py look                       stills of every shot          -> look-1.jpg ..., and what is wrong
    python3 make.py film                       the finished film             -> film.mp4

Run it in the folder that holds film.json, people/ and places/. ../make.md says what goes in film.json.
It needs ffmpeg, and: pip install pillow numpy opencv-python-headless faster-whisper
"""
import difflib
import json
import math
import os
import re
import subprocess
import sys
from functools import lru_cache
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
if sys.argv[1:2] != ["words"]:  # the listening and the drawing carry the same video library, so never load both at once
    import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
WIDE, HIGH, FPS = 1080, 1920, 24
FINE = 4  # eyes and mouths are drawn this many times bigger, then made small, so their edges are smooth
INK, WHITE, TONGUE, DEEP = (18, 20, 32), (255, 255, 252), (216, 106, 98), (74, 20, 34)

# How open each eye is (its left, its right), how far the lids lean, the pupil, and the mouth.
FEELS = {
    "steady": (82, 82, 0, "middling", "line"),
    "doubt": (40, 96, 0, "middling", "crooked"),
    "shock": (100, 100, 0, "small", "round"),
    "smug": (54, 54, 0, "middling", "smirk"),
    "cross": (72, 72, 42, "middling", "down"),
    "sad": (74, 74, -42, "big", "down"),
    "joy": (100, 100, 0, "big", "laugh"),
    "asleep": (0, 0, 0, "middling", "line"),
}
PUPILS = {"small": 0.31, "middling": 0.52, "big": 0.6}
GROWN = {"shock": 1.2}  # the whole eye gets bigger
CHEEKS = {"joy": 0.24}  # the cheek pushes up into the eye
LOOKS = {"ahead": (0, 0), "left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}


def stop(message):
    sys.exit("make.py: " + message)


def read(path, or_else=None):
    if not os.path.exists(path):
        if or_else is not None:
            return or_else
        stop(path + " is not here. Run this in the folder that holds it.")
    with open(path, encoding="utf8") as file:
        return json.load(file)


def write(path, value):
    with open(path, "w", encoding="utf8") as file:
        json.dump(value, file, indent=1, ensure_ascii=False)


# ---------------------------------------------------------------- the pictures


@lru_cache(maxsize=12)
def cut_out(path):
    """A person with the flat colour behind them taken away, trimmed: the picture, where it was, and the edges it runs off."""
    image = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if image is None:
        stop("cannot open the picture " + path)
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[0] > 2400:
        image = cv2.resize(image, None, fx=2400 / image.shape[0], fy=2400 / image.shape[0], interpolation=cv2.INTER_AREA)
    high, wide = image.shape[:2]
    if image.shape[2] == 4 and (image[..., 3] < 10).mean() > 0.02:
        colour, alpha = image[..., :3].copy(), image[..., 3].astype(np.float32) / 255
    else:
        colour = image[..., :3].copy()
        edge = max(4, high // 60)
        rim = np.concatenate([colour[:edge].reshape(-1, 3), colour[: high // 2, :edge].reshape(-1, 3),
                              colour[: high // 2, -edge:].reshape(-1, 3)]).astype(np.float32)
        flat = np.median(rim, axis=0)
        if (np.abs(rim - flat).max(axis=1) < 45).mean() < 0.6:
            stop(path + ": the colour behind this person is not flat. Draw it again on one flat bright colour, "
                 "or cut the person out with any tool and save a transparent PNG.")
        lab = cv2.cvtColor(colour, cv2.COLOR_BGR2LAB).astype(np.float32)
        key = cv2.cvtColor(np.uint8([[flat]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
        away = np.hypot(lab[..., 1] - key[1], lab[..., 2] - key[2])
        far = max(30.0, np.hypot(key[1] - 128, key[2] - 128))
        alpha = np.clip((away - far * 0.3) / (far * 0.35), 0, 1)
        alpha = cv2.GaussianBlur(cv2.erode(alpha, np.ones((3, 3))), (3, 3), 0)
        # Take the colour's glow off the person: no pixel keeps more of it than its other channels have.
        strong = flat > flat.max() * 0.7
        if strong.sum() == 1 and flat.max() - np.median(flat) > 40:
            channel = int(np.argmax(strong))
            others = np.delete(colour, channel, axis=2).max(axis=2)
            colour[..., channel] = np.minimum(colour[..., channel], others)
        elif strong.sum() == 2:
            other = colour[..., int(np.argmin(strong))]
            for channel in np.where(strong)[0]:
                colour[..., channel] = np.where(away < far * 0.8, np.minimum(colour[..., channel], other), colour[..., channel])
    seen = np.argwhere(alpha > 0.5)
    if not len(seen):
        stop(path + ": nobody is left once the flat colour is taken away.")
    (top, left), (bottom, right) = seen.min(axis=0), seen.max(axis=0) + 1
    out = np.dstack([colour, (alpha * 255).astype(np.uint8)])[top:bottom, left:right]
    runs_off = {"bottom": bool(bottom >= high * 0.99), "left": bool(left <= wide * 0.01 and (out[:, 2, 3] > 128).mean() > 0.03),
                "right": bool(right >= wide * 0.99 and (out[:, -3, 3] > 128).mean() > 0.03)}
    return out, (left, top, wide, high), runs_off


def ink_line(draw, points, width, colour=INK):
    draw.line(points, fill=colour + (255,), width=max(1, round(width)), joint="curve")
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=colour + (255,))


def draw_eye(radius, feels, left, look, shut, skin):
    """One eye, on its own little picture."""
    open_left, open_right, leaning, pupil_kind, _ = FEELS[feels]
    r = radius * GROWN.get(feels, 1) * FINE
    size = int(r * 2.6) + 8
    c = size / 2
    line = max(1.5 * FINE, r * 0.075)
    eye = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(eye)

    def disc(x, y, q, fill):
        pen.ellipse((x - q, y - q, x + q, y + q), fill=fill + (255,))

    disc(c, c, r, INK)
    disc(c, c, r - line, WHITE)
    inner = r - line
    lid = 1.0 if shut else 1 - (open_left if left else open_right) / 100
    if lid < 0.95:
        pupil = inner * PUPILS[pupil_kind]
        reach = (inner - pupil) * 0.72
        drop = inner * 0.5 * lid  # an eye half shut looks out from under its lid
        under = c - inner + 2 * inner * lid + pupil * 0.15  # never hidden behind its own lid
        x, y = c + look[0] * reach, min(c + inner - pupil * 0.9, max(under, c + look[1] * reach + drop * (look[1] >= 0)))
        disc(x, y, pupil, INK)
        disc(x + pupil * 0.08, y - pupil * 0.55, pupil * 0.22, (255, 255, 255))
    lean = leaning / 100 * (1 if left else -1)
    across = np.linspace(-1.2, 1.2, 33)
    cover = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    over = ImageDraw.Draw(cover)
    if lid >= 0.95:
        over.ellipse((c - inner, c - inner, c + inner, c + inner), fill=skin + (255,))
        ink_line(over, [(c + t * inner * 0.76, c + inner * 0.08 + inner * 0.38 * (1 - t * t)) for t in np.linspace(-1, 1, 25)], line)
    elif lid > 0.02:
        curve = [(c + t * inner, c - inner + 2 * inner * lid + lean * t * inner * 0.7
                  + inner * 0.16 * lid * math.cos(max(-1, min(1, t)) * math.pi / 2)) for t in across]
        over.polygon([(c - 1.3 * inner, c - 1.6 * inner), (c + 1.3 * inner, c - 1.6 * inner)] + curve[::-1], fill=skin + (255,))
        over.line(curve, fill=INK + (255,), width=round(line))
    if feels in CHEEKS and lid < 0.95:
        curve = [(c + t * inner, c + inner - 2 * inner * CHEEKS[feels] + inner * 0.2 * t * t) for t in across]
        over.polygon([(c - 1.3 * inner, c + 1.6 * inner), (c + 1.3 * inner, c + 1.6 * inner)] + curve[::-1], fill=skin + (255,))
        over.line(curve, fill=INK + (255,), width=round(line))
    inside = Image.new("L", (size, size), 0)
    ImageDraw.Draw(inside).ellipse((c - inner, c - inner, c + inner, c + inner), fill=255)
    cover.putalpha(Image.fromarray(np.minimum(np.array(cover.split()[3]), np.array(inside))))
    eye.alpha_composite(cover)
    return eye


def draw_mouth(gap, kind, pale):
    """One mouth, on its own little picture. gap is the space between the eyes' middles; pale is a colour to lay under the line when the face is dark there."""
    g = gap * FINE
    size = int(g * 1.5) + 8
    c = size / 2
    line = max(1.5 * FINE, g * 0.07)
    mouth = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(mouth)
    steps = np.linspace(-1, 1, 25)
    thin = {
        "line": lambda t: (t * 0.34, 0.015 * t * t),
        "crooked": lambda t: (t * 0.34, -t * 0.07 + 0.04 * math.sin(t * 3)),
        "smirk": lambda t: (t * 0.38, -0.14 * max(0, t) ** 2 + 0.03 * (1 - t * t)),
        "down": lambda t: (t * 0.34, 0.14 * t * t - 0.05),
    }
    if kind in thin:
        points = [(c + x * g, c + y * g) for x, y in map(thin[kind], steps)]
        if pale:
            ink_line(pen, points, line * 3.6)
            ink_line(pen, points, line * 2.4, pale)
        ink_line(pen, points, line)
    elif kind == "round":
        pen.ellipse((c - g * 0.2, c - g * 0.24, c + g * 0.2, c + g * 0.3), fill=INK + (255,))
        pen.ellipse((c - g * 0.2 + line, c - g * 0.24 + line, c + g * 0.2 - line, c + g * 0.3 - line), fill=DEEP + (255,))
    elif kind == "laugh":
        box = (c - g * 0.42, c - g * 0.5, c + g * 0.42, c + g * 0.4)
        pen.chord(box, 0, 180, fill=INK + (255,))
        pen.chord((box[0] + line, box[1] + line, box[2] - line, box[3] - line), 6, 174, fill=DEEP + (255,))
        pen.ellipse((c - g * 0.2, c + g * 0.16, c + g * 0.2, c + g * 0.4 - line), fill=TONGUE + (255,))
        pen.rounded_rectangle((c - g * 0.33, c - g * 0.03, c + g * 0.33, c + g * 0.07), g * 0.03, fill=WHITE + (255,))
    return mouth


def stick(card, patch, x, y, turn):
    """Put a little picture on the person's picture, turned as the head is turned."""
    if turn:
        patch = patch.rotate(-turn, Image.BICUBIC, expand=True)
    small = patch.resize((max(1, round(patch.width / FINE)), max(1, round(patch.height / FINE))), Image.LANCZOS)
    card.alpha_composite(small, (max(0, round(x - small.width / 2)), max(0, round(y - small.height / 2))))


@lru_cache(maxsize=16)
def person_card(path, tall, flip, feels, look, shut, face):
    """The person at the size they are on screen, with the face drawn on. Returns the picture and the face's middle."""
    picture, (left, top, wide, high), _ = cut_out(path)
    size = tall / picture.shape[0]
    scaled = cv2.resize(picture, (max(1, round(picture.shape[1] * size)), max(1, round(tall))),
                        interpolation=cv2.INTER_AREA if size < 1 else cv2.INTER_CUBIC)
    points = None
    if face:
        points = [((x * wide / 100 - left) * size, (y * high / 100 - top) * size) for x, y in face]
    if flip:
        scaled = scaled[:, ::-1]
        if points:
            mirror = [(scaled.shape[1] - x, y) for x, y in points]
            points = [mirror[1], mirror[0], mirror[2]]
    if points and feels != "none":
        (ax, ay), (bx, by), (mx, my) = points
        gap = math.hypot(bx - ax, by - ay)
        turn = math.degrees(math.atan2(by - ay, bx - ax))
        rgb = scaled[..., [2, 1, 0]]
        cheek_y, cheek_x = int(min(max((ay + by) / 2 + gap * 0.55, 0), rgb.shape[0] - 1)), int(min(max(ax, 0), rgb.shape[1] - 1))
        q = max(2, int(gap * 0.08))
        skin = np.median(rgb[max(0, cheek_y - q):cheek_y + q, max(0, cheek_x - q):cheek_x + q].reshape(-1, 3), axis=0)
        skin = tuple(int(v) for v in skin)
        card = Image.fromarray(np.dstack([rgb, scaled[..., 3]]))
        for side, (x, y) in enumerate(((ax, ay), (bx, by))):
            # Less than half the gap, so the two whites never touch over the nose.
            stick(card, draw_eye(gap * 0.38, feels, side == 0, LOOKS[look], shut, skin), x, y, turn)
        mouth_y, mouth_x = int(min(max(my, 0), rgb.shape[0] - 1)), int(min(max(mx, 0), rgb.shape[1] - 1))
        near = rgb[max(0, mouth_y - 2 * q):mouth_y + 2 * q, max(0, mouth_x - 3 * q):mouth_x + 3 * q]
        pale = tuple(int(v * 0.86) for v in skin) if near.mean() < 95 < np.mean(skin) else None  # a dark beard hides a thin mouth
        stick(card, draw_mouth(gap, FEELS[feels][4], pale), mx, my, turn)
        done = np.array(card)
        scaled = np.dstack([done[..., 2], done[..., 1], done[..., 0], done[..., 3]])
    ready = scaled.astype(np.float32)
    ready[..., :3] *= ready[..., 3:] / 255
    return ready.astype(np.uint8), points


@lru_cache(maxsize=6)
def place_picture(path):
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        stop("cannot open the picture " + path)
    size = max(WIDE / image.shape[1], HIGH / image.shape[0]) * 1.06
    return cv2.resize(image, None, fx=size, fy=size, interpolation=cv2.INTER_CUBIC if size > 1 else cv2.INTER_AREA)


# ---------------------------------------------------------------- the film


class Film:
    def __init__(self, path="film.json"):
        film = read(path)
        self.film, self.words, self.faces = film, read("words.json"), read("faces.json", {})
        self.voice = film.get("voice", "voice.wav")
        shots = film["shots"]
        starts = [0.0] + [self.said(s.get("start"), f"shot {i + 2}: start") for i, s in enumerate(shots[1:])]
        end = self.words[-1]["to"] + 0.7
        self.frames = round(end * FPS)
        marks = [round(t * FPS) for t in starts] + [self.frames]
        for i in range(len(shots)):
            if marks[i + 1] <= marks[i]:
                stop(f"shot {i + 1} has no time: its start word must come before the next shot's.")
        self.shots = [dict(shot, first=marks[i], last=marks[i + 1], number=i + 1) for i, shot in enumerate(shots)]
        for shot in self.shots:
            if not os.path.exists(os.path.join("places", shot.get("place", "?"))):
                stop(f"shot {shot['number']}: places/{shot.get('place', '?')} is not here.")
            for person in shot.get("people", []):
                for part in [person] + person.get("changes", []):
                    picture = part.get("picture", person.get("picture", "?"))
                    if not os.path.exists(os.path.join("people", picture)):
                        stop(f"shot {shot['number']}: people/{picture} is not here.")
                    if part.get("feels", "steady") not in list(FEELS) + ["none"]:
                        stop(f"shot {shot['number']}: feels is one of {', '.join(FEELS)}, or none.")
                    if part.get("look", "ahead") not in LOOKS:
                        stop(f"shot {shot['number']}: look is one of {', '.join(LOOKS)}.")

    def said(self, number, where):
        if not isinstance(number, int) or not 1 <= number <= len(self.words):
            stop(f"{where}: {number} is not the number of a word in words.json (1 to {len(self.words)}).")
        return self.words[number - 1]["from"]

    def face(self, picture):
        points = self.faces.get(picture)
        return tuple(tuple(p) for p in (points["eyes"] + [points["mouth"]])) if points else None

    def pose(self, shot, person, frame):
        """What this person is on this frame: the first pose, or the last change whose word has been said."""
        now, since = dict(person), frame - shot["first"]
        fresh = False
        for change in person.get("changes", []):
            at = round(self.said(change["word"], f"shot {shot['number']}") * FPS)
            if frame >= at:
                fresh = "picture" in change and change["picture"] != now["picture"]
                now.update(change)
                since = frame - at
        return now, since, fresh

    def zoom(self, shot, frame):
        along = (frame - shot["first"]) / max(1, shot["last"] - shot["first"])
        return {"in": 1 + 0.06 * along, "out": 1.06 - 0.06 * along}.get(shot.get("camera", "in"), 1.0)

    def placed(self, shot, index, person, frame):
        """The person's picture, its face, and the sum that puts it on the screen; None before they come in."""
        now, since, fresh = self.pose(shot, person, frame)
        slide = 0.0
        enters = person.get("enters")
        if enters:
            begin = round(self.said(enters["word"], f"shot {shot['number']}") * FPS)
            if frame < begin:
                return None
            left_to_go = max(0.0, 1 - (frame - begin + 1) / 8) ** 3
            slide = left_to_go * WIDE * (-1.3 if enters.get("from", "left") == "left" else 1.3)
        path = os.path.join("people", now["picture"])
        shut = (frame + 37 * index + 11 * shot["number"]) % 83 < 4 and now.get("feels", "steady") in ("steady", "doubt", "sad")
        card, points = person_card(path, round(now.get("tall", 70) * HIGH / 100), bool(now.get("flip")), now.get("feels", "steady"),
                                   now.get("look", "ahead"), shut, self.face(now["picture"]))
        high, wide = card.shape[:2]
        size = 1 + (0.05 * max(0.0, 1 - since / 4) if fresh else 0)
        turn = math.radians(0.5) * math.sin(2 * math.pi * frame / (FPS * 3.1) + index * 1.9 + shot["number"])
        cos, sin = math.cos(turn) * size, math.sin(turn) * size
        foot_x, foot_y = now.get("x", 50) * WIDE / 100 + slide, (now.get("head", 25) + now.get("tall", 70)) * HIGH / 100
        here = np.array([[cos, -sin, foot_x - cos * wide / 2 + sin * high], [sin, cos, foot_y - sin * wide / 2 - cos * high], [0, 0, 1]])
        z = self.zoom(shot, frame)
        camera = np.array([[z, 0, WIDE / 2 * (1 - z)], [0, z, HIGH * 0.42 * (1 - z)], [0, 0, 1]])
        return card, points, (camera @ here)[:2], now

    def word_now(self, frame):
        now = frame / FPS + 1e-6
        for i, word in enumerate(self.words):
            after = self.words[i + 1]["from"] if i + 1 < len(self.words) else word["to"] + 0.4
            if word["from"] <= now < min(after, word["to"] + 0.45):
                return word["word"]
        return None

    def draw(self, frame):
        shot = next(s for s in self.shots if s["first"] <= frame < s["last"])
        place = place_picture(os.path.join("places", shot["place"]))
        z = 1 + (self.zoom(shot, frame) - 1) * 0.6
        high, wide = place.shape[:2]
        canvas = cv2.warpAffine(place, np.float32([[z, 0, WIDE / 2 - z * wide / 2], [0, z, HIGH / 2 - z * high / 2]]), (WIDE, HIGH),
                                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        for index, person in enumerate(shot.get("people", [])):
            done = self.placed(shot, index, person, frame)
            if not done:
                continue
            card, _, move, _ = done
            corners = np.array([[0, 0, 1], [card.shape[1], 0, 1], [0, card.shape[0], 1], [card.shape[1], card.shape[0], 1]]) @ move.T
            x0, y0 = np.maximum(np.floor(corners.min(axis=0)).astype(int) - 1, 0)
            x1, y1 = np.minimum(np.ceil(corners.max(axis=0)).astype(int) + 1, (WIDE, HIGH))
            if x1 <= x0 or y1 <= y0:
                continue
            shift = move.copy()
            shift[:, 2] -= (x0, y0)
            layer = cv2.warpAffine(card, shift, (int(x1 - x0), int(y1 - y0)), flags=cv2.INTER_LINEAR)
            part = canvas[y0:y1, x0:x1]
            part *= 1 - layer[..., 3:].astype(np.float32) / 255
            part += layer[..., :3]
        word = self.word_now(frame)
        if word:
            stamp, (x, y) = word_stamp(word, shot.get("words_at", self.film.get("words_at", 62)))
            part = canvas[y:y + stamp.shape[0], x:x + stamp.shape[1]]
            stamp = stamp[: part.shape[0], : part.shape[1]]
            part *= 1 - stamp[..., 3:] / 255
            part += stamp[..., :3]
        return np.clip(canvas, 0, 255).astype(np.uint8)

    def moments(self):
        """One frame for each thing the film shows: every shot, and every change in it."""
        for shot in self.shots:
            marks = {shot["first"]}
            for person in shot.get("people", []):
                marks |= {round(self.said(c["word"], f"shot {shot['number']}") * FPS) for c in person.get("changes", [])}
                if person.get("enters"):
                    marks.add(round(self.said(person["enters"]["word"], f"shot {shot['number']}") * FPS) + 7)
            marks = sorted(m for m in marks if shot["first"] <= m < shot["last"]) + [shot["last"]]
            for i in range(len(marks) - 1):
                yield shot, (marks[i] + marks[i + 1]) // 2, f"{shot['number']}{'abcdefghij'[i] if len(marks) > 2 and i < 10 else ''}"

    def faults(self):
        """What can be found without looking. It does not replace looking."""
        found, soft = [], {}
        for shot in self.shots:
            n = shot["number"]
            long = (shot["last"] - shot["first"]) / FPS
            if long > 3.5:
                found.append(f"shot {n}: holds for {long:.1f} seconds. Cut it on a word, or give it a change.")
            for index, person in enumerate(shot.get("people", [])):
                for part in [person] + person.get("changes", []):
                    now = dict(person, **part)
                    name = now["picture"]
                    picture, _, runs_off = cut_out(os.path.join("people", name))
                    if runs_off["bottom"] and now.get("head", 25) + now.get("tall", 70) < 101:
                        found.append(f"shot {n}: {name} is cut off above the bottom of the screen. Head plus tall must be 101 or more.")
                    shape, middle = picture.shape[1] / picture.shape[0] * HIGH / 100 / 2, now.get("x", 50) * WIDE / 100
                    need = 0
                    for side, room in (("left", middle), ("right", WIDE - middle)):
                        real = {"left": "right", "right": "left"}[side] if now.get("flip") else side
                        if runs_off[real] and shape * now.get("tall", 70) < room - 4:
                            need = max(need, math.ceil(room / shape))
                    if need:
                        found.append(f"shot {n}: {name} runs off the side of its picture, and that edge shows. Make tall {need}, "
                                     "or move that side off the screen, or use a picture with room round it.")
                    bigger = now.get("tall", 70) * HIGH / 100 / picture.shape[0]
                    if bigger > max(2.5, soft.get(name, (0,))[0]):
                        soft[name] = (bigger, n)
                    if now.get("feels", "steady") != "none" and not self.faces.get(name):
                        found.append(f"shot {n}: {name} has no face in faces.json, so none is drawn. Add it, or say \"feels\": \"none\".")
                for change in person.get("changes", []):
                    at = round(self.said(change["word"], f"shot {n}") * FPS)
                    if not shot["first"] <= at < shot["last"]:
                        found.append(f"shot {n}: word {change['word']} is not said in this shot, so that change never shows.")
            hit = set()
            for frame in range(shot["first"], shot["last"], 3):
                word = self.word_now(frame)
                if not word:
                    continue
                stamp, (x, y) = word_stamp(word, shot.get("words_at", self.film.get("words_at", 62)))
                for index, person in enumerate(shot.get("people", [])):
                    done = self.placed(shot, index, person, frame)
                    if not done or not done[1]:
                        continue
                    spots = np.array([[px, py, 1] for px, py in done[1]]) @ done[2].T
                    reach = np.hypot(*(spots[1] - spots[0])) * 0.45
                    box = (*(spots.min(axis=0) - reach), *(spots.max(axis=0) + reach))
                    if box[0] < x + stamp.shape[1] and box[2] > x and box[1] < y + stamp.shape[0] and box[3] > y:
                        hit.add(word)
            if hit:
                found.append(f"shot {n}: on a face: {', '.join(sorted(hit))}. Set words_at for the shot, or move the person.")
        for name, (bigger, n) in soft.items():
            found.append(f"shot {n}: {name} is shown {bigger:.1f} times bigger than it was drawn, so it looks soft. Draw it bigger, or show it smaller.")
        return list(dict.fromkeys(found))


@lru_cache(maxsize=512)
def word_stamp(word, at):
    size = 98
    while True:
        font = ImageFont.truetype(os.path.join(HERE, "words.ttf"), size)
        box = font.getbbox(word, stroke_width=size // 9)
        if box[2] - box[0] < WIDE * 0.9 or size < 40:
            break
        size -= 6
    edge, soft = size // 9, 14
    wide, high = box[2] - box[0] + 2 * soft, box[3] - box[1] + 2 * soft
    dark = Image.new("L", (wide, high), 0)
    ImageDraw.Draw(dark).text((soft - box[0], soft - box[1]), word, font=font, fill=255, stroke_width=edge, stroke_fill=255)
    glow = cv2.GaussianBlur(np.array(dark), (0, 0), 5).astype(np.float32) * 0.55
    alpha = np.maximum(np.array(dark).astype(np.float32), glow)
    front = Image.new("L", (wide, high), 0)
    ImageDraw.Draw(front).text((soft - box[0], soft - box[1]), word, font=font, fill=255)
    shade = np.array(front).astype(np.float32)[..., None] / 255
    colour = shade * np.array([255, 255, 255], np.float32) + (1 - shade) * np.array(INK[::-1], np.float32)
    stamp = np.dstack([colour * alpha[..., None] / 255, alpha])
    return stamp, (max(0, (WIDE - wide) // 2), max(0, min(HIGH - high, round(HIGH * at / 100 - high / 2))))


# ---------------------------------------------------------------- the commands


def tidy(raw, out):
    quiet = ("silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.05:"
             "stop_periods=-1:stop_threshold=-38dB:stop_duration=0.3:stop_silence=0.2")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-ac", "1", "-ar", "48000", "-af", quiet, out], check=True)
    print("wrote", out)


def plain(word):
    return re.sub(r"[^\w]", "", word.lower())


def words(voice, script, model="small"):
    from faster_whisper import WhisperModel

    # ffmpeg opens the file, not the listener's own opener: that one breaks with each new version of its library.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", voice, "-f", "f32le", "-ac", "1", "-ar", "16000", "-"], check=True, capture_output=True)
    sound, heard = np.frombuffer(raw.stdout, np.float32), []
    for part in WhisperModel(model, device="cpu", compute_type="int8").transcribe(sound, word_timestamps=True)[0]:
        heard += [(w.word.strip(), w.start, w.end) for w in part.words]
    with open(script, encoding="utf8") as file:
        wanted = file.read().split()
    if not heard:
        stop("no words were heard in " + voice)
    out, unsure = [None] * len(wanted), []
    match = difflib.SequenceMatcher(None, [plain(w) for w in wanted], [plain(h[0]) for h in heard], autojunk=False)
    for kind, a0, a1, b0, b1 in match.get_opcodes():
        if kind == "equal":
            for i in range(a1 - a0):
                out[a0 + i] = (heard[b0 + i][1], heard[b0 + i][2])
        elif a1 > a0:
            # Heard differently, or not at all: share the time that is there between the words that were written.
            begin = heard[b0][1] if b1 > b0 else (heard[b0 - 1][2] if b0 else 0.0)
            end = heard[b1 - 1][2] if b1 > b0 else (heard[b0][1] if b0 < len(heard) else heard[-1][2] + 0.3)
            step = max(0.06, (end - begin) / (a1 - a0))
            for i in range(a1 - a0):
                out[a0 + i] = (begin + i * step, begin + (i + 1) * step)
                unsure.append(a0 + i + 1)
    rows = []
    for i, (word, (begin, end)) in enumerate(zip(wanted, out)):
        if rows and begin < rows[-1]["from"] + 0.04:
            begin = rows[-1]["from"] + 0.04
        rows.append({"n": i + 1, "word": word, "from": round(float(begin), 3), "to": round(float(max(end, begin + 0.06)), 3)})
    write("words.json", rows)
    for row in rows:
        print(f"{row['n']:4} {row['from']:7.2f}  {row['word']}{'   <- not heard clearly' if row['n'] in unsure else ''}")


def find_face(path):
    picture, (left, top, wide, high), _ = cut_out(path)
    alpha = picture[..., 3:].astype(np.float32) / 255
    grey = (picture[..., :3] * alpha + 128 * (1 - alpha)).astype(np.uint8)
    finder = cv2.FaceDetectorYN.create(os.path.join(HERE, "faces.onnx"), "", (320, 320), 0.5, 0.3, 50)
    best = None
    for part in (1.0, 0.6, 0.35):
        crop = grey[: max(8, int(grey.shape[0] * part))]
        size = 640 / max(crop.shape[:2])
        small = cv2.copyMakeBorder(cv2.resize(crop, None, fx=size, fy=size), 64, 64, 64, 64, cv2.BORDER_CONSTANT, value=(128, 128, 128))
        finder.setInputSize((small.shape[1], small.shape[0]))
        _, found = finder.detect(small)
        for row in found if found is not None else []:
            if best is None or row[14] > best[0]:
                best = (float(row[14]), (row[4:14].reshape(5, 2) - 64) / size, row[2] / size)
    if not best:
        return None, None
    _, spots, across = best
    eyes = sorted(spots[:2].tolist())
    mouth = ((spots[3] + spots[4]) / 2).tolist()
    room = (eyes[1][0] - eyes[0][0]) * 0.12
    side_on = room < across * 0.034 or not eyes[0][0] + room < spots[2][0] < eyes[1][0] - room

    def percent(point):
        return [round(float((point[0] + left) / wide * 100), 2), round(float((point[1] + top) / high * 100), 2)]

    return {"eyes": [percent(eyes[0]), percent(eyes[1])], "mouth": percent(mouth)}, side_on


def faces():
    done = read("faces.json", {})
    names = sorted(n for n in os.listdir("people") if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
    for name in names:
        if name in done:
            continue
        done[name], side_on = find_face(os.path.join("people", name))
        if done[name] is None:
            print(f"{name}: no face found. A back or a hand is right. If it has a face, write it in faces.json by hand.")
        elif side_on:
            print(f"{name}: seen from the side. Drawn eyes look wrong on it: use another picture, or \"feels\": \"none\".")
    write("faces.json", done)
    tiles = []
    for name in names:
        picture, (left, top, wide, high), _ = cut_out(os.path.join("people", name))
        face, alpha = done[name], picture[..., 3:].astype(np.float32) / 255
        view = (picture[..., :3] * alpha + 200 * (1 - alpha)).astype(np.uint8)
        if face:
            spots = [((x * wide / 100) - left, (y * high / 100) - top) for x, y in face["eyes"] + [face["mouth"]]]
            gap = max(8, math.hypot(spots[1][0] - spots[0][0], spots[1][1] - spots[0][1]))
            mx, my = np.mean(spots, axis=0)
            x0, y0 = int(max(0, mx - gap * 1.7)), int(max(0, my - gap * 1.7))
            crop = view[y0:int(my + gap * 1.7), x0:int(mx + gap * 1.7)].copy()
            size = 400 / max(crop.shape[:2])
            crop = cv2.resize(crop, None, fx=size, fy=size, interpolation=cv2.INTER_CUBIC)
            for i, (x, y) in enumerate(spots):
                spot = (round((x - x0) * size), round((y - y0) * size))
                cv2.drawMarker(crop, spot, (0, 0, 255) if i < 2 else (255, 0, 0), cv2.MARKER_CROSS, 26, 3)
        else:
            size = 400 / max(view.shape[:2])
            crop = cv2.resize(view, None, fx=size, fy=size)
        tile = np.full((440, 400, 3), 245, np.uint8)
        tile[: crop.shape[0], : crop.shape[1]] = crop[:400, :400]
        cv2.putText(tile, name[:34], (6, 428), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        tiles.append(tile)
    sheets("faces", tiles, 4, 3)


def sheets(name, tiles, across, down):
    blank = np.full_like(tiles[0], 255) if tiles else None
    for page in range(0, len(tiles), across * down):
        some = tiles[page:page + across * down]
        some += [blank] * (-len(some) % across)
        rows = [np.hstack(some[i:i + across]) for i in range(0, len(some), across)]
        path = f"{name}-{page // (across * down) + 1}.jpg"
        cv2.imwrite(path, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
        print("wrote", path)


def look():
    film = Film()
    tiles = []
    for _, frame, name in film.moments():
        tile = cv2.resize(film.draw(frame), (360, 640), interpolation=cv2.INTER_AREA)
        cv2.putText(tile, name, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 7)
        cv2.putText(tile, name, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
        tiles.append(tile)
    sheets("look", tiles, 5, 2)
    found = film.faults()
    print(f"{len(film.shots)} shots, {film.frames / FPS:.1f} seconds. " + ("Nothing found. Now look at every still." if not found else "To put right:"))
    for line in found:
        print(" -", line)


_film = None


def _begin():
    global _film
    cv2.setNumThreads(1)
    _film = Film()


def _frame(number):
    return _film.draw(number).tobytes()


def make_film(out="film.mp4"):
    film = Film()
    music = film.film.get("music")
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{WIDE}x{HIGH}", "-r", str(FPS), "-i", "-", "-i", film.voice]
    if music:
        command += ["-stream_loop", "-1", "-i", music]
        sound = "[1:a]aresample=48000,apad[v];[2:a]aresample=48000,volume=0.13[m];[v][m]amix=inputs=2:duration=first:normalize=0,"
    else:
        sound = "[1:a]aresample=48000,apad,"
    sound += "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    command += ["-filter_complex", sound, "-map", "0:v", "-map", "[a]", "-t", f"{film.frames / FPS:.3f}", "-c:v", "libx264", "-preset", "medium",
                "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    ffmpeg = subprocess.Popen(command, stdin=subprocess.PIPE)
    with Pool(max(1, min(8, (os.cpu_count() or 2) - 1)), initializer=_begin) as pool:
        for i, data in enumerate(pool.imap(_frame, range(film.frames), chunksize=6)):
            ffmpeg.stdin.write(data)
            if i % 120 == 0:
                print(f"{i} of {film.frames} frames", flush=True)
    ffmpeg.stdin.close()
    if ffmpeg.wait():
        stop("ffmpeg could not write " + out)
    print("wrote", out)


COMMANDS = {"tidy": (tidy, 2), "words": (words, 2), "faces": (faces, 0), "look": (look, 0), "film": (make_film, 0)}

if __name__ == "__main__":
    asked = sys.argv[1:]
    if not asked or asked[0] not in COMMANDS or len(asked) - 1 < COMMANDS[asked[0]][1]:
        sys.exit(__doc__)
    COMMANDS[asked[0]][0](*asked[1:])
