# Quiz Game Assistant — Life Makeover Vvanna Quiz (ADB automation). See README.md.
#
#   python setup.py                     # first time per device: screen regions -> config.json
#   python main.py                      # answer a quiz (scrcpy capture if found, else adb screencap)
#   python main.py --debug              # read one question live, save an annotated image; no tap
#   python main.py --debug -s shot.png  # same on a saved screenshot (no device needed)

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common.lm_adb import open_capture
from common.lm_tool import add_common_args, read_config, write_config, select_device, profile_regions

import argparse
import difflib
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

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

SCRCPY_WINDOW_TITLE = 'vanna_quiz'

QUESTIONS_PER_QUIZ = 8
TRANSITION_MIN_WAIT = 1.0   # seconds to wait after tap before polling (the question changes some
                            # time after the answer is chosen)
TRANSITION_POLL     = 0.3   # polling interval while waiting for new question
TRANSITION_TIMEOUT  = 10.0  # give up and proceed after this long
NEW_QUESTION_MAX_SIM = 0.8  # below this similarity to the previous question text = a new question.
                            # OCR noise on one question scores ~0.97-0.98 ("ihere" vs "there"), but
                            # some different bank questions score up to 0.94, so a similar read is
                            # not trusted either way: wait TRANSITION_CONFIRM_WAIT and take that frame
TRANSITION_CONFIRM_WAIT = 1.0  # after a read still >= NEW_QUESTION_MAX_SIM: wait this long, then
                               # accept the next frame as the new question

FUZZY_CUTOFF = 0.4


def _text_sim(a, b):
    """Similarity 0..1 of two OCR'd texts (case-insensitive), as difflib's matcher scores them."""
    return difflib.SequenceMatcher(None, (a or '').lower().strip(), (b or '').lower().strip()).ratio()

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
        answers = read_config(self._config_path).get('answers', {})
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
        cfg = read_config(self._config_path)
        cfg['answers'] = self._answers
        write_config(self._config_path, cfg)

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

    def _ocr(self, crop):
        """OCR as a block of text (--psm 6) with line breaks joined into single spaces.

        Questions and answers both wrap onto two lines; single-line mode (--psm 7) garbled
        wrapped answers ("Redeem with Basic Color Chart" -> "ee chor") badly enough to pick
        the wrong box. Joined lines also compare cleanly against the one-line answer bank."""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return ' '.join(pytesseract.image_to_string(thresh, config='--psm 6').split())

    def read_screen(self, screenshot):
        result = {}
        t0 = time.perf_counter()
        result['question'] = self._ocr(self._crop_region(screenshot, 'question')[0])
        print(f'  [time] OCR question:  {(time.perf_counter()-t0)*1000:5.0f} ms')
        for label in ('A', 'B', 'C', 'D'):
            t0 = time.perf_counter()
            result[label] = self._ocr(self._crop_region(screenshot, label)[0])
            print(f'  [time] OCR {label}:         {(time.perf_counter()-t0)*1000:5.0f} ms')
        return result

    def read_question(self, screenshot):
        """OCR the question region only — cheap poll for transition detection."""
        return self._ocr(self._crop_region(screenshot, 'question')[0])


# ---------------------------------------------------------------------------

class QuizAssistant:
    def __init__(self, adb, loader, reader, capture=None, device_size=None):
        self.adb = adb
        self.loader = loader
        self.reader = reader
        self._capture = capture
        self._device_size = device_size  # (w, h) in device pixels — taps are always in device pixels

    def _tap_region(self, key, screenshot):
        """Tap inside a region. Regions are stored as fractions of the screen, so they are
        scaled to device pixels — never to screenshot pixels, which differ under scrcpy capture
        (the mirror window is usually smaller than the device resolution)."""
        size = self._device_size
        if not size:
            # Device size unknown: screenshot pixels are only correct for adb screencap.
            size = (screenshot.shape[1], screenshot.shape[0])
            if self._capture is not None:
                print('  [WARN] device screen size unknown — tapping in screenshot pixels, may miss under scrcpy')
        self.adb.tap_in_fraction_region(self.reader.regions[key], size)

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
        """After tapping, wait for the next question to be shown. Returns its screenshot.

        Waits TRANSITION_MIN_WAIT, then polls until a question is read. Text below
        NEW_QUESTION_MAX_SIM similarity to the previous question is new. Text at or above it may
        be the previous question still on screen (OCR varies by a letter between frames, so an
        exact comparison took it for new and Q4 was read off Q3's screen) or a similar new one:
        wait TRANSITION_CONFIRM_WAIT and take the next frame as the new question."""
        time.sleep(TRANSITION_MIN_WAIT)
        t0 = time.perf_counter()
        while True:
            shot = self._take_screenshot()
            if shot is not None:
                q = self.reader.read_question(shot)
                elapsed = time.perf_counter() - t0 + TRANSITION_MIN_WAIT
                if q:
                    sim = _text_sim(q, prev_question)
                    if sim < NEW_QUESTION_MAX_SIM:
                        print(f'  [transition] new question in {elapsed:.1f}s '
                              f'(similarity to previous {sim:.2f})')
                        return shot
                    print(f'  [transition] similar to previous ({sim:.2f}) at {elapsed:.1f}s — '
                          f'waiting {TRANSITION_CONFIRM_WAIT:.1f}s, then taking the next frame')
                    time.sleep(TRANSITION_CONFIRM_WAIT)
                    confirm = self._take_screenshot()
                    return confirm if confirm is not None else shot
                if time.perf_counter() - t0 >= TRANSITION_TIMEOUT:
                    print(f'  [transition] timeout after {elapsed:.1f}s — proceeding anyway')
                    return shot
            time.sleep(TRANSITION_POLL)

    def _read_and_answer(self, screenshot):
        """OCR the screen and look up the answer: (ocr_texts, label, matched_q, correct_answer)."""
        t0 = time.perf_counter()
        ocr_texts = self.reader.read_screen(screenshot)
        print(f'  [time] OCR total:     {(time.perf_counter()-t0)*1000:5.0f} ms')
        print(f'  OCR Q:  "{ocr_texts["question"][:60]}"')
        for lbl in ('A', 'B', 'C', 'D'):
            print(f'  OCR {lbl}: "{ocr_texts[lbl]}"')
        t0 = time.perf_counter()
        label, matched_q, correct_answer = self._find_correct_choice(ocr_texts)
        print(f'  [time] lookup:        {(time.perf_counter()-t0)*1000:5.0f} ms')
        return ocr_texts, label, matched_q, correct_answer

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

            ocr_texts, label, matched_q, correct_answer = self._read_and_answer(screenshot)
            if label is None and not (debug and screenshot_path):
                # Maybe a frame caught mid-animation (half-drawn text): read one fresh frame
                # before giving up. Costs a poll only when the lookup failed.
                time.sleep(TRANSITION_POLL)
                retry = self._take_screenshot()
                if retry is not None:
                    print('  [retry] no answer - reading a fresh frame')
                    screenshot = retry
                    ocr_texts, label, matched_q, correct_answer = self._read_and_answer(screenshot)
            prev_question = ocr_texts['question']

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
                    t0 = time.perf_counter()
                    self._tap_region(label, screenshot)
                    print(f'  [time] tap:           {(time.perf_counter()-t0)*1000:5.0f} ms')
                    screenshot = self._wait_for_new_question(prev_question)

        print('\nDebug run complete.' if debug else '\nQuiz complete.')


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Life Makeover — Vvanna Quiz assistant')
    add_common_args(parser)
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
    cfg, adb, profile = select_device(args, CONFIG_PATH)
    regions = profile_regions(profile)

    if debug and screenshot_path:
        # File-based debug: no device needed
        loader = QuizAnswerLoader(ANSWER_URL, CONFIG_PATH)
        reader = QuizScreenReader(regions)
        assistant = QuizAssistant(adb=None, loader=loader, reader=reader)
        assistant.run(debug=True, screenshot_path=screenshot_path)
        return

    capture = open_capture(cfg, adb, SCRCPY_WINDOW_TITLE, force_adb=args.adb)

    loader = QuizAnswerLoader(ANSWER_URL, CONFIG_PATH)
    reader = QuizScreenReader(regions)
    assistant = QuizAssistant(adb=adb, loader=loader, reader=reader, capture=capture,
                              device_size=adb.get_screen_size())
    # The quiz can be played once, so start only when the first question is showing
    try:
        input('\nOpen the Vvanna Quiz and press Enter when the first question is on screen '
              '(Ctrl+C to exit)...')
    except (KeyboardInterrupt, EOFError):
        print('\nExiting.')
        return
    assistant.run(debug=debug, screenshot_path=screenshot_path)


if __name__ == '__main__':
    main()
