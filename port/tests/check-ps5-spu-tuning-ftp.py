#!/usr/bin/env python3
"""Test PS5 ftpsrv's nonstandard 226 DELE response and rollback cleanup."""
import ftplib
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "tools/gta4-spu-tuning.py"
spec = importlib.util.spec_from_file_location("gta4_spu_tuning", SCRIPT)
tuning = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tuning)


class FakeFTP:
    def __init__(self, files=None, code="226 File deleted", remove=True):
        self.files = dict(files or {})
        self.code = code
        self.remove = remove

    def retrbinary(self, command, callback):
        assert command.startswith("RETR ")
        name = command[5:]
        if name not in self.files:
            raise ftplib.error_perm("550 No such file or directory")
        callback(self.files[name])
        return "226 Transfer complete"

    def delete(self, path):
        if self.remove:
            self.files.pop(path, None)
        if self.code:
            raise ftplib.error_reply(self.code)
        return "250 File deleted"

    def rename(self, source, destination):
        self.files[destination] = self.files.pop(source)


class DeletionTests(unittest.TestCase):
    def test_226_after_actual_delete(self):
        ftp = FakeFTP({tuning.BACKUP: b"old"})
        tuning.delete_verified(ftp, tuning.BACKUP)
        self.assertNotIn(tuning.BACKUP, ftp.files)

    def test_standard_250_after_delete(self):
        ftp = FakeFTP({tuning.BACKUP: b"old"}, code="")
        tuning.delete_verified(ftp, tuning.BACKUP)
        self.assertNotIn(tuning.BACKUP, ftp.files)

    def test_226_without_delete_must_fail(self):
        ftp = FakeFTP({tuning.BACKUP: b"old"}, remove=False)
        with self.assertRaisesRegex(RuntimeError, "did not remove"):
            tuning.delete_verified(ftp, tuning.BACKUP)

    def test_unexpected_reply_must_fail(self):
        ftp = FakeFTP({tuning.BACKUP: b"old"}, code="421 Server failed", remove=False)
        with self.assertRaises(ftplib.error_reply):
            tuning.delete_verified(ftp, tuning.BACKUP)

    def test_restores_exact_absent_original(self):
        ftp = FakeFTP({tuning.TUNE: b"spu_insert_select 1\n"})
        tuning.put_atomically(ftp, ftp.files[tuning.TUNE], None)
        self.assertFalse(ftp.files)


if __name__ == "__main__":
    unittest.main()
