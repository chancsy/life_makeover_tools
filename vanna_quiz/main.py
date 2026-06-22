# Quiz Game Assistant — Life Makeover Vvanna Quiz (ADB automation)
#
# Dependencies:
#   pip install opencv-python pytesseract requests beautifulsoup4 numpy Pillow
#   Tesseract-OCR binary: https://github.com/tesseract-ocr/tesseract
#
# First-time setup:
#   python setup.py           ← register device + define screen regions → config.json
#
# Usage:
#   python main.py
#
# Debug mode (no device needed):
#   Set DEBUG_MODE = True and DEBUG_SCREENSHOT = 'path/to/screenshot.png'
#   Annotated output saved alongside the screenshot as *_debug_q1.png

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.lm_adb import get_adb, get_scrcpy, read_common_config  # also wires lib-utils into sys.path

import argparse
import difflib
import json
import random
import time
import requests
import cv2
import numpy as np
import pytesseract
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANSWER_URL = 'https://life-makeover.fandom.com/wiki/Shining_Journey/Vvanna_Quiz'

ADB_PATH = None  # None = use system PATH; or r'C:\Android\platform-tools\adb.exe'

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

SCRCPY_WINDOW_TITLE = 'vanna_quiz'

QUESTIONS_PER_QUIZ = 8
TRANSITION_MIN_WAIT = 0.5   # seconds to wait after tap before polling (animation settling)
TRANSITION_POLL     = 0.3   # polling interval while waiting for new question
TRANSITION_TIMEOUT  = 10.0  # give up and proceed after this long

FUZZY_CUTOFF = 0.4

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _read_config(path):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _write_config(path, cfg):
    with open(path, 'w') as f:
        json.dump(cfg, f, indent=2)


def load_regions_for_device(config_path, device_serial):
    entry = _read_config(config_path).get('devices', {}).get(device_serial)
    if entry is None:
        return None
    regions = {k: tuple(v) for k, v in entry['regions'].items()}
    size = entry.get('screen_size', ['?', '?'])
    name = entry.get('name', device_serial)
    print(f'Recognized device "{name}" ({device_serial}) — {size[0]}×{size[1]}')
    return regions


# ---------------------------------------------------------------------------
# Answer loader — local cache first, web fetch on miss
# ---------------------------------------------------------------------------

class QuizAnswerLoader:
    def __init__(self, url, config_path):
        self.url = url
        self._config_path = config_path
        self._answers = None   # {question_lower: answer_lower}
        self._web_fetched = False

    def _load_local(self):
        answers = _read_config(self._config_path).get('answers', {})
        if answers:
            print(f'Loaded {len(answers)} answers from local cache')
        return answers

    def _fetch_web(self):
        if self._answers is None:
            self._answers = {}
        print('Fetching answers from wiki (MediaWiki API)...')
        # Use the MediaWiki API to avoid Cloudflare blocking on the HTML page
        base_url, page_title = self.url.split('/wiki/', 1)
        api_url = f'{base_url}/api.php'

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        params = {
            'action': 'parse',
            'page': page_title,
            'prop': 'text',
            'format': 'json',
            'disableeditsection': '1',
        }
        resp = session.get(api_url, params=params, timeout=15)
        resp.raise_for_status()

        data = resp.json()
        if 'error' in data:
            raise ValueError(f'MediaWiki API error: {data["error"].get("info", data["error"])}')

        html = data['parse']['text']['*']
        soup = BeautifulSoup(html, 'html.parser')

        # Pick the table with the most rows (skip nav/infobox tables)
        all_tables = soup.find_all('table')
        if not all_tables:
            raise ValueError('No table found in parsed wiki content — page structure may have changed')
        table = max(all_tables, key=lambda t: len(t.find_all('tr')))

        rows = table.find_all('tr')
        print(f'  Tables found: {len(all_tables)}, using table with {len(rows)} rows')
        if rows:
            sample_cols = rows[0].find_all(['td', 'th'])
            print(f'  First row ({len(sample_cols)} cols): {[c.get_text(strip=True)[:30] for c in sample_cols]}')

        fetched = {}
        for row in rows[1:]:
            cols = row.find_all(['td', 'th'])
            if len(cols) < 2:
                continue
            q = cols[0].get_text(separator=' ', strip=True).lower()
            a = cols[1].get_text(separator=' ', strip=True).lower()
            if q and a:
                fetched[q] = a

        new_count = sum(1 for k in fetched if k not in self._answers)
        self._answers.update(fetched)
        self._web_fetched = True
        self._save_answers()
        print(f'Fetched {len(fetched)} entries from wiki ({new_count} new)')

    def _save_answers(self):
        cfg = _read_config(self._config_path)
        cfg['answers'] = self._answers
        _write_config(self._config_path, cfg)

    def _fuzzy_find(self, query):
        q = query.lower().strip()
        keys = list(self._answers.keys())
        matches = difflib.get_close_matches(q, keys, n=1, cutoff=FUZZY_CUTOFF)
        if matches:
            matched_q = matches[0]
            return matched_q, self._answers[matched_q]
        return None, None

    def lookup(self, ocr_question):
        """Return (matched_question, answer) or (None, None). Fetches web on first miss."""
        if self._answers is None:
            self._answers = self._load_local()

        matched_q, answer = self._fuzzy_find(ocr_question)
        if matched_q:
            return matched_q, answer

        if not self._web_fetched:
            self._fetch_web()
            matched_q, answer = self._fuzzy_find(ocr_question)

        return matched_q, answer


# ---------------------------------------------------------------------------

class QuizScreenReader:
    def __init__(self, regions):
        self.regions = regions

    def _crop_region(self, img, key):
        h, w = img.shape[:2]
        x1p, y1p, x2p, y2p = self.regions[key]
        x1, y1 = int(x1p * w), int(y1p * h)
        x2, y2 = int(x2p * w), int(y2p * h)
        return img[y1:y2, x1:x2], (x1, y1, x2, y2)

    def _ocr(self, crop, single_line=False):
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        psm = '7' if single_line else '6'
        return pytesseract.image_to_string(thresh, config=f'--psm {psm}').strip()

    def read_screen(self, screenshot):
        result = {}
        t0 = time.perf_counter()
        result['question'] = self._ocr(self._crop_region(screenshot, 'question')[0], single_line=False)
        print(f'  [time] OCR question:  {(time.perf_counter()-t0)*1000:5.0f} ms')
        for label in ('A', 'B', 'C', 'D'):
            t0 = time.perf_counter()
            result[label] = self._ocr(self._crop_region(screenshot, label)[0], single_line=True)
            print(f'  [time] OCR {label}:         {(time.perf_counter()-t0)*1000:5.0f} ms')
        return result

    def read_question(self, screenshot):
        """OCR the question region only — cheap poll for transition detection."""
        return self._ocr(self._crop_region(screenshot, 'question')[0], single_line=False)

    def get_region_px(self, screenshot, key):
        _, bbox = self._crop_region(screenshot, key)
        return bbox



# ---------------------------------------------------------------------------

class QuizAssistant:
    def __init__(self, adb, loader, reader, capture=None):
        self.adb = adb
        self.loader = loader
        self.reader = reader
        self._capture = capture

    def _take_screenshot(self):
        if self._capture is not None:
            return self._capture.take_screenshot()
        return self.adb.take_screenshot()

    def _fuzzy_match_choice(self, answer, choice_texts):
        a = answer.lower().strip()
        c_lower = [c.lower().strip() for c in choice_texts]
        matches = difflib.get_close_matches(a, c_lower, n=1, cutoff=FUZZY_CUTOFF)
        if matches:
            return choice_texts[c_lower.index(matches[0])]
        return None

    def _wait_for_new_question(self, prev_question):
        """After tapping, poll until the question text changes. Returns the new screenshot."""
        time.sleep(TRANSITION_MIN_WAIT)
        t0 = time.perf_counter()
        while True:
            shot = self._take_screenshot()
            if shot is not None:
                q = self.reader.read_question(shot)
                elapsed = time.perf_counter() - t0 + TRANSITION_MIN_WAIT
                if q and q != prev_question:
                    print(f'  [transition] new question in {elapsed:.1f}s')
                    return shot
                if time.perf_counter() - t0 >= TRANSITION_TIMEOUT:
                    print(f'  [transition] timeout after {elapsed:.1f}s — proceeding anyway')
                    return shot
            time.sleep(TRANSITION_POLL)

    def _find_correct_choice(self, ocr_texts):
        """Returns (label, matched_q, correct_answer) — any can be None on failure."""
        matched_q, correct_answer = self.loader.lookup(ocr_texts['question'])
        if matched_q is None:
            print(f'  [WARN] No answer found for: "{ocr_texts["question"][:60]}"')
            return None, None, None

        print(f'  Q match:  "{matched_q[:55]}"')
        print(f'  Answer:   "{correct_answer}"')

        choice_labels = ['A', 'B', 'C', 'D']
        choice_texts = [ocr_texts[l] for l in choice_labels]
        matched_choice = self._fuzzy_match_choice(correct_answer, choice_texts)
        if matched_choice is None:
            print(f'  [WARN] Answer not matched in choices: {choice_texts}')
            return None, matched_q, correct_answer

        label = choice_labels[choice_texts.index(matched_choice)]
        print(f'  -> Choice {label}: "{matched_choice}"')
        return label, matched_q, correct_answer

    def _save_debug_image(self, screenshot, ocr_texts, label, matched_q, correct_answer,
                          q_num, screenshot_path=None):
        img = screenshot.copy()
        h, w = img.shape[:2]
        regions = self.reader.regions

        for key, (x1p, y1p, x2p, y2p) in regions.items():
            x1, y1 = int(x1p * w), int(y1p * h)
            x2, y2 = int(x2p * w), int(y2p * h)
            is_chosen = key == label
            color = (50, 50, 230) if is_chosen else (160, 160, 160)  # BGR
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 3 if is_chosen else 1)
            cv2.putText(img, key, (x1 + 6, y1 + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # Circle + crosshair at the randomised tap point (mirrors tap_in_region margin=0.25)
        if label and label in regions:
            x1p, y1p, x2p, y2p = regions[label]
            x1r, y1r = int(x1p * w), int(y1p * h)
            x2r, y2r = int(x2p * w), int(y2p * h)
            dx, dy = (x2r - x1r) * 0.25, (y2r - y1r) * 0.25
            cx = random.randint(int(x1r + dx), int(x2r - dx))
            cy = random.randint(int(y1r + dy), int(y2r - dy))
            r = max(40, int((y2p - y1p) * h * 0.35))
            red = (50, 50, 230)
            cv2.circle(img, (cx, cy), r, red, 3)
            cv2.line(img, (cx - r + 10, cy), (cx + r - 10, cy), red, 2)
            cv2.line(img, (cx, cy - r + 10), (cx, cy + r - 10), red, 2)

        # Info overlay
        lines = [
            f'Q{q_num} [DEBUG]',
            f'Match: {(matched_q or "?")[:52]}',
            f'Answer: {correct_answer or "?"}',
            f'Chosen: {label or "none"}',
        ]
        y = 36
        for line in lines:
            cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4)
            cv2.putText(img, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
            y += 28

        src = screenshot_path or 'screenshot'
        out_path = f'{os.path.splitext(src)[0]}_debug_q{q_num}.png'
        cv2.imwrite(out_path, img)
        print(f'  Debug image → {out_path}')

    def run(self, loop_count=QUESTIONS_PER_QUIZ, debug=False, screenshot_path=None):
        prev_question = None
        screenshot = None

        for i in range(1, loop_count + 1):
            print(f'\n--- Question {i}/{loop_count} ---')

            if debug and screenshot_path:
                screenshot = cv2.imread(screenshot_path)
                if screenshot is None:
                    print(f'Cannot read {screenshot_path}')
                    break
            elif screenshot is None:
                # First question — take a fresh screenshot
                t0 = time.perf_counter()
                screenshot = self._take_screenshot()
                print(f'  [time] screenshot:    {(time.perf_counter()-t0)*1000:5.0f} ms')
                if screenshot is None:
                    print('Failed to capture screenshot, skipping')
                    time.sleep(TRANSITION_POLL)
                    continue
            # else: screenshot already set by _wait_for_new_question from previous iteration

            t0 = time.perf_counter()
            ocr_texts = self.reader.read_screen(screenshot)
            print(f'  [time] OCR total:     {(time.perf_counter()-t0)*1000:5.0f} ms')
            print(f'  OCR Q:  "{ocr_texts["question"][:60]}"')
            for lbl in ('A', 'B', 'C', 'D'):
                print(f'  OCR {lbl}: "{ocr_texts[lbl]}"')
            prev_question = ocr_texts['question']

            t0 = time.perf_counter()
            label, matched_q, correct_answer = self._find_correct_choice(ocr_texts)
            print(f'  [time] lookup:        {(time.perf_counter()-t0)*1000:5.0f} ms')

            if debug:
                self._save_debug_image(screenshot, ocr_texts, label, matched_q, correct_answer,
                                       i, screenshot_path)
                break  # debug always stops after 1 question
            else:
                if label is None:
                    try:
                        input('  [MANUAL] Answer not found — answer on your phone, then press Enter to continue (Ctrl+C to exit)...')
                    except KeyboardInterrupt:
                        print('\nExiting.')
                        break
                    screenshot = None  # force fresh capture after manual answer
                else:
                    bbox = self.reader.get_region_px(screenshot, label)
                    t0 = time.perf_counter()
                    self.adb.tap_in_region(bbox[0], bbox[1], bbox[2], bbox[3])
                    print(f'  [time] tap:           {(time.perf_counter()-t0)*1000:5.0f} ms')
                    screenshot = self._wait_for_new_question(prev_question)

        print('\nDebug run complete.' if debug else '\nQuiz complete.')


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Life Makeover — Vvanna Quiz assistant')
    parser.add_argument('--debug', '-d', action='store_true',
                        help='Debug mode: annotate screenshot instead of tapping')
    parser.add_argument('--screenshot', '-s', metavar='PATH',
                        help='Screenshot file to use in debug mode (implies --debug)')
    parser.add_argument('--adb-path', metavar='PATH', default=ADB_PATH,
                        help='Path to adb executable (default: use system PATH)')
    parser.add_argument('--adb', action='store_true',
                        help='Force adb screencap instead of scrcpy window capture')
    parser.add_argument('--fetch-answers', action='store_true',
                        help='Fetch latest answers from wiki and update config.json, then exit')
    args = parser.parse_args()

    if args.fetch_answers:
        loader = QuizAnswerLoader(ANSWER_URL, CONFIG_PATH)
        loader._answers = loader._load_local()
        loader._fetch_web()
        print('Done.')
        return

    debug = args.debug or bool(args.screenshot)
    screenshot_path = args.screenshot
    cfg = _read_config(CONFIG_PATH)

    if debug and screenshot_path:
        # File-based debug: no device needed, use first available region config
        devices_cfg = cfg.get('devices', {})
        if not devices_cfg:
            print('No device config found. Run setup.py first.')
            sys.exit(1)
        first_serial = next(iter(devices_cfg))
        regions = {k: tuple(v) for k, v in devices_cfg[first_serial]['regions'].items()}
        print(f'Debug mode — regions from device "{first_serial}"')

        loader = QuizAnswerLoader(ANSWER_URL, CONFIG_PATH)
        reader = QuizScreenReader(regions)
        assistant = QuizAssistant(adb=None, loader=loader, reader=reader)
        assistant.run(debug=True, screenshot_path=screenshot_path)
        return

    adb = get_adb(adb_path=args.adb_path)
    regions = load_regions_for_device(CONFIG_PATH, adb.device)
    if regions is None:
        print(f'Device "{adb.device}" not in config. Run setup.py to register this device.')
        sys.exit(1)

    capture = None
    _scrcpy_cfg = {**read_common_config().get('scrcpy', {}), **cfg.get('scrcpy', {})}
    if not args.adb and _scrcpy_cfg:
        capture = get_scrcpy(cfg, serial=adb.device, adb=adb, window_title=SCRCPY_WINDOW_TITLE)

    loader = QuizAnswerLoader(ANSWER_URL, CONFIG_PATH)
    reader = QuizScreenReader(regions)
    assistant = QuizAssistant(adb=adb, loader=loader, reader=reader, capture=capture)
    assistant.run(debug=debug, screenshot_path=screenshot_path)


if __name__ == '__main__':
    main()
