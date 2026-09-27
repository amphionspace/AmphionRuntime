"""Pin the shipped ITN verbalizer; its optimized form is smaller than 100 KiB."""
from pathlib import Path
import hashlib
import sys
import zipfile

ENTRY = 'assets/amphion-models/itn-zh/v1/zh_itn_verbalizer.fst'
# Built from the filler-preserving ITN rules shipped on both platforms.
EXPECTED_SHA256 = '89d1b765d526fab21b1ba3402221baa28edb4b380e9b799d764042e842cecf98'


def verify(archive: Path, *, expected_sha256: str = EXPECTED_SHA256) -> None:
    with zipfile.ZipFile(archive) as package:
        actual = hashlib.sha256(package.read(ENTRY)).hexdigest()
    if actual != expected_sha256:
        raise ValueError('ITN verbalizer does not match the approved rules')


if __name__ == '__main__':
    verify(Path(sys.argv[1]))
    print('[OK] pinned Android ITN verbalizer SHA-256 verified')
