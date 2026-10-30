#!/usr/bin/env python3
"""Exercise the PS5 frontend's real resolver against RPCS3's boot-path slicing."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1]) / 'rpcs3/ps5/ps5_frontend.cpp').read_text()
start = source.index('\tcallbacks.resolve_path = ')
end = source.index('\n\t};', start) + len('\n\t};')
resolver = source[start:end].split('=', 1)[1].strip().removesuffix(';')
program = r'''
#include <cassert>
#include <iostream>
#include <string>
#include <string_view>
int main()
{
    auto resolve = RESOLVER;
    const std::string root = "/app0/rpcs3/dev_hdd0/game/";
    // Reproduce the old callback's failure with the actual System.cpp slice.
    const std::string original = root + "NPUB30702/USRDIR/EBOOT.BIN";
    assert(original.substr((root + '/').size()) == "PUB30702/USRDIR/EBOOT.BIN");
    for (const auto* title : {"NPUB30702", "NPEB00393", "BLES00229"})
    {
        const std::string tail = std::string(title) + "/USRDIR/EBOOT.BIN";
        for (const auto* suffix : {"", "/", "///"})
        {
            const std::string prefix = resolve(root + suffix) + '/';
            const std::string boot = resolve(root + tail).substr(prefix.size());
            assert(boot == tail);
            assert("/dev_hdd0/game/" + boot == "/dev_hdd0/game/" + tail);
        }
    }
    assert(resolve("/") == "/");
    assert(resolve("").empty());
    assert(resolve("/app0/rpcs3/dev_flash/sys/external/liblv2.sprx") ==
           "/app0/rpcs3/dev_flash/sys/external/liblv2.sprx");
    std::cout << "PASS: boot paths preserve full title IDs; root and file paths preserved\n";
}
'''.replace('RESOLVER', resolver)
compiler = shutil.which('clang++-19') or shutil.which('c++')
if not compiler:
    raise SystemExit('A host C++ compiler is required')
with tempfile.TemporaryDirectory() as temporary:
    directory = Path(temporary)
    test = directory / 'boot-path.cpp'
    binary = directory / 'boot-path'
    test.write_text(program)
    subprocess.run([compiler, '-std=c++20', str(test), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
