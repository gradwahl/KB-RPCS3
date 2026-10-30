#!/usr/bin/env python3
"""Reject converted native TLS layouts that lose alignment or initial values."""
import struct
import sys


def read_elf(path):
    with open(path, 'rb') as source:
        data = source.read()
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError(f'{path}: expected little-endian ELF64')
    offset, = struct.unpack_from('<Q', data, 0x20)
    size, count = struct.unpack_from('<HH', data, 0x36)
    headers = [struct.unpack_from('<IIQQQQQQ', data, offset + i * size)
               for i in range(count)]
    tls = [header for header in headers if header[0] == 7]
    if len(tls) != 1 or tls[0][6] == 0:
        raise ValueError(f'{path}: expected one non-empty PT_TLS')
    return data, headers, tls[0]


def check(original, converted):
    source, _, before = read_elf(original)
    output, headers, after = read_elf(converted)
    # p_vaddr, p_filesz, p_memsz, p_align define the loader's TLS template.
    if any(before[i] != after[i] for i in (3, 5, 6, 7)):
        raise ValueError('converter changed the TLS address, size or alignment')
    template = source[before[2]:before[2] + before[5]]
    if output[after[2]:after[2] + after[5]] != template:
        raise ValueError('converter changed the initial TLS template')
    for header in headers:
        kind, flags, offset, address, _, filesz, _, _ = header
        if (kind == 1 and flags & 2 and address <= after[3]
                and after[3] + after[5] <= address + filesz):
            loaded = offset + after[3] - address
            if output[loaded:loaded + after[5]] == template:
                print(f'Native TLS verified: template={after[5]} bytes, '
                      f'memory={after[6]} bytes, alignment={after[7]}')
                return
    raise ValueError('TLS initial values are missing from writable file-backed PT_LOAD')


if __name__ == '__main__':
    try:
        check(*sys.argv[1:])
    except (ValueError, TypeError) as error:
        sys.exit(f'Native TLS validation failed: {error}. '
                 'Check port/ps5-native-tls-converter.patch and rebuild ps5-native-tool.')
