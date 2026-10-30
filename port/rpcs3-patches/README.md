# KB-RPCS3 patches for RPCS3

These 48 patches turn upstream RPCS3 (revision `46aee28f8`) into the KB-RPCS3 emulator core for the PS5.
They are licensed under the **GPL-2.0-only**, the same as RPCS3 (`../../LICENSES/GPL-2.0.txt`).

Apply them with `../apply-rpcs3-patches.sh`, or by hand:

```bash
git clone https://github.com/RPCS3/rpcs3.git && cd rpcs3
git checkout 46aee28f8 && git submodule update --init --recursive
git am --keep-cr /path/to/port/rpcs3-patches/*.patch
```

`--keep-cr` is required because some RPCS3 files use CRLF line endings.

Patch 0048 supplies the PS5 frontend's directory resolver so installed title IDs
retain their first character when constructing guest boot paths. Its focused
regression check compiles the actual callback with a host C++ compiler:

```bash
python3 port/tests/check-ps5-boot-path.py "$HOME/work/rpcs3"
```
