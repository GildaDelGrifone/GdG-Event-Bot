import os
import tempfile
import unittest
import zipfile


class FolderTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")
        self.day = os.path.join(self.data, "2026", "10", "28")
        os.makedirs(self.day)

    def write(self, name, content=b"img", folder=None):
        path = os.path.join(folder or self.day, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def zip(self, members, folder=None):
        path = os.path.join(folder or self.day, "archive.zip")
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        return path
