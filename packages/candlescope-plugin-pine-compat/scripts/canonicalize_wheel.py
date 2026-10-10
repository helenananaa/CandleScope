"""Freeze archive metadata without changing wheel contents or RECORD hashes."""

import argparse
import hashlib
from pathlib import Path
import zipfile


def canonicalize(path: Path) -> None:
    with zipfile.ZipFile(path) as source:
        contents = [(name, source.read(name)) for name in sorted(source.namelist())]
    temporary = path.with_suffix('.canonical.tmp')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED) as target:
        for name, data in contents:
            entry = zipfile.ZipInfo(name, date_time=(2020, 2, 2, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            target.writestr(entry, data)
    temporary.replace(path)
    print(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    canonicalize(parser.parse_args().wheel)
