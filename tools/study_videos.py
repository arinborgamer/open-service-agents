"""Download public captions for private study; never commit caption files."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi

IDS = ['MTZwSjiDg30', 'NE-62S4OYCg', 'XmzgbRe9Pkg', 'zE6cfSnVWUs']
ROOT = Path(__file__).resolve().parents[1] / '.local' / 'captions'

def fetch(video_id):
    target = ROOT / (video_id + '.json')
    if not target.exists():
        captions = YouTubeTranscriptApi().fetch(video_id).to_raw_data()
        ROOT.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(captions, ensure_ascii=False), encoding='utf-8')
    return video_id, json.loads(target.read_text(encoding='utf-8'))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--keywords', action='store_true')
    parser.add_argument('--video')
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--end', type=int, default=100000)
    args = parser.parse_args()
    for video_id, captions in ThreadPoolExecutor(4).map(fetch, [args.video] if args.video else IDS):
        print('\nVIDEO', video_id, 'segments', len(captions), 'duration', int(captions[-1]['start']))
        for row in captions:
            if not args.start <= row['start'] < args.end:
                continue
            if args.keywords and not any(word in row['text'].lower() for word in ['agent', 'whop', 'software', 'reception', 'appointment', 'outreach']):
                continue
            print(f"{int(row['start'])}: {row['text']}")
