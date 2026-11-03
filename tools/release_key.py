"""Developer-only Ed25519 signing key, protected with Windows DPAPI outside the repo."""
import argparse
import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def key_path():
    return Path(os.environ["LOCALAPPDATA"]) / "FileSearchRelease" / "signing-key.dpapi"


def load_key():
    return Ed25519PrivateKey.from_private_bytes(protect(key_path().read_bytes(), decrypt=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()
    path = key_path()
    if args.create and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Ed25519PrivateKey.generate()
        with path.open("xb") as stream:
            stream.write(protect(key.private_bytes_raw()))
    print(base64.b64encode(load_key().public_key().public_bytes_raw()).decode("ascii"))


if __name__ == "__main__":
    main()
