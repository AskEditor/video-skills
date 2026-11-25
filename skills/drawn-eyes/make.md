# Making the film on your own computer

`make/make.py` draws the film. The person brings the pictures and the voice. Nothing leaves the computer, except what they choose to send to
their own picture tool or voice tool.

## What it takes

| | Where it comes from |
|---|---|
| Python 3.10 or newer, and ffmpeg | Free. Check for both first. If one is missing, say how to get it on this computer and ask before installing |
| Four Python packages | Free, about 300 MB. In a folder for this film: `python3 -m venv env`, then `env/bin/pip install pillow numpy opencv-python-headless faster-whisper` |
| A listening model | Free, about 500 MB. It downloads itself the first time |
| The pictures | Any picture tool the person has |
| The voice | Theirs, or any voice tool they have |

Made and tested on a Mac. Linux and Windows are untested.

**What it does not do:** a route that draws itself on a map, things that fall, legs that walk, sound effects. Choose shots without them.

Make one folder for the film, with `people/`, `places/`, `SHOTS.md` and `words.txt` (the agreed words, and nothing else) in it. Run every command there.
`make.py` below means `env/bin/python <this skill>/make/make.py`.

## 1. The pictures

Write `BRIEFS.md`: one brief for each picture, with the file name to save it under, such as `people/baker.png` or `places/shop.jpg`. Follow
`shots.md`. Upright pictures, in the shape of a phone screen (9 by 16), about 1080 by 1920 or bigger. Leave room round each person: only the bottom of
the body may touch an edge. A thing drawn alone goes in `people/` too, with `feels: none` later on.

Ask the person how they draw pictures. Wait for the answer.

| They say | Do this |
|---|---|
| "I have a key for a picture tool" | Read that tool's own page, today, for how to call it and what a picture costs. Say the total and wait for a yes. They put the key in an environment variable themselves. Never ask them to paste it in the chat, and never write it in a file |
| "I use an app" | Give them the briefs one at a time to paste in, each with the name to save it under |
| "I have neither" | Find two or three that can be used free today, with their limits, and let them choose |

Draw one person and one place first, and look at them together. Go on only when both are right. When the same person comes back in another
picture, give the tool their first picture with the new brief, so that it is the same face.

Look at every picture when it arrives. Ask for it again if the mouth is open, the face is from the side, a hand is wrong, or the colour behind is not flat.

## 2. The voice

Ask which: they read it themselves (a phone is fine), a voice tool of theirs, with the key handled as above, or a free voice program on this
computer. Never anybody else's voice without their yes. One take. Then:

```
make.py tidy take.wav voice.wav
make.py words voice.wav words.txt
```

The second prints every word with its number. The film is built on those numbers. Words are counted from 1, one for each gap in
`words.txt`, so "second-hand" is one word and "137" is one word. Where a word is marked "not heard clearly", a number often is, play that moment and put its
times right in `words.json`.

## 3. The faces

```
make.py faces
```

Look at every `faces-*.jpg`. A red cross on each eye, a blue one on the mouth. Where one is wrong, or a face was missed (an animal always is), enlarge the
picture, look, and write the points in `faces.json` yourself: how far across and how far down the picture, from 0 to 100. A back or a hand stays `null`.

## 4. The shot list, as a file

Write `film.json` from the agreed shot list. A number from 1 to 100 is a part of the screen, across or down.

```
{
 "voice": "voice.wav",
 "words_at": 62,
 "shots": [
  {"place": "shop.jpg",
   "people": [{"picture": "baker.png", "x": 50, "head": 20, "tall": 85, "feels": "steady", "look": "down",
               "changes": [{"word": 6, "picture": "baker-shouting.png", "feels": "cross", "look": "ahead"}]}]},
  {"start": 11, "place": "road.jpg", "camera": "out",
   "people": [{"picture": "thief.png", "x": 70, "head": 22, "tall": 82, "feels": "smug", "enters": {"word": 13, "from": "right"}}]}
 ]
}
```

| | What it says |
|---|---|
| `voice`, `music` | The sound files. Music is optional, and sits under the voice |
| `words_at` | How far down the word sits. For the film, or for one shot |
| `start` | The number of the word this shot cuts in on. The first shot has none |
| `place` | A picture in `places/` |
| `camera` | `in` (the usual one), `out` or `still` |
| `people` | From the back to the front |
| `picture` | A picture in `people/`. `flip: true` turns it round |
| `x` | The middle of the person, across |
| `head` | The top of their head, down |
| `tall` | How tall they are once the flat colour is gone, from the top of the head to wherever their picture ends. See the sizes below |
| `feels` | steady, doubt, shock, smug, cross, sad, joy, asleep. `none` draws no face |
| `look` | ahead, left, right, up, down. Towards whoever they are dealing with; ahead is at us |
| `changes` | What is different from that word on: the feeling, the look, the picture, or where they are |
| `enters` | They slide in on that word, from the left or the right |

`start` and `word` are the numbers `make.py words` printed: find each shot's first word there. Fewer words means fewer shots, a new one about every second and a half.

| You want | `head` | `tall` |
|---|---|---|
| Head and chest, from a waist-up picture | 8 | 94 |
| Waist up | 20 | 82 |
| A whole person, with their feet on the ground | 40 | 52 |

Someone cut off at the waist must reach past the bottom of the screen, so head plus tall is 101 or more. A whole person stops above it, so that their
feet show. A hand or an arm comes in from the side of the screen its sleeve runs off, with `feels: none`.

## 5. Look, then make it

```
make.py look
```

It draws a still of every shot and every change, and says what it found wrong, with the number that puts it right where there is one. Put each one right. Then look at every still yourself, by `checks.md`: it
finds cut edges, soft pictures, words on faces and shots that hold too long, and nothing else. Ask of each still: does it show what the word says? **STOP.** Show the stills and wait for a yes.

```
make.py film
```

The sound is set to the usual loudness for a Short.

To change one shot, change its lines in `film.json` and run both again. It costs nothing.
