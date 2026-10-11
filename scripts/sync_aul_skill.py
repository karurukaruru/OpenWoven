"""Generate or check the dependency-free AUL skill runtime."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'src/openwoven/user_learning.py'
TARGET = ROOT / 'skills/agent-user-learning/scripts/aul.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = SOURCE.read_bytes()
    if args.check:
        if not TARGET.exists() or TARGET.read_bytes() != content:
            raise SystemExit('AUL runtime differs; run python scripts/sync_aul_skill.py')
        print('AUL runtime matches SDK source')
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        TARGET.write_bytes(content)


if __name__ == '__main__':
    main()
