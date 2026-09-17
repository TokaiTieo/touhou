"""Verify the actual PE icon images, not merely the build configuration."""

import hashlib
import struct
import sys
from pathlib import Path

import pefile


def verify(executable, icon):
    ico = Path(icon).read_bytes()
    expected = []
    count = struct.unpack_from("<H", ico, 4)[0]
    for index in range(count):
        size, offset = struct.unpack_from("<II", ico, 6 + index * 16 + 8)
        expected.append(hashlib.sha256(ico[offset:offset + size]).hexdigest())
    with pefile.PE(str(executable)) as pe:
        actual = []
        for resource in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if resource.id != 3:
                continue
            for identity in resource.directory.entries:
                for language in identity.directory.entries:
                    entry = language.data.struct
                    actual.append(hashlib.sha256(pe.get_data(entry.OffsetToData, entry.Size)).hexdigest())
    if sorted(actual) != sorted(expected):
        raise ValueError("Embedded EXE icon does not match the current TouHou ICO")
    print(f"Embedded TouHou icon verified: {count} sizes")


if __name__ == "__main__":
    verify(sys.argv[1], Path(__file__).resolve().parents[1] / "static/touhou.ico")
