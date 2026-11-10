"""Windows current-user DPAPI codec. Sensitive material only travels over stdio."""
import base64
import ctypes
import os
import sys
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_byte))]


def transform(raw,encrypt=True):
    if os.name!='nt':raise RuntimeError('Windows DPAPI is required')
    buffer=ctypes.create_string_buffer(raw)
    source=Blob(len(raw),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte)))
    target=Blob()
    crypt=ctypes.windll.crypt32
    operation=crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    operation.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    operation.restype=wintypes.BOOL
    if not operation(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise RuntimeError('Credential protection unavailable for this Windows account')
    try:return ctypes.string_at(target.pbData,target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.pbData,ctypes.c_void_p))


if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(8*1024*1024+1)
        if len(raw)>8*1024*1024:raise ValueError('size')
        mode=sys.argv[1]
        if mode=='encrypt':sys.stdout.buffer.write(base64.b64encode(transform(raw)))
        elif mode=='decrypt':sys.stdout.buffer.write(transform(base64.b64decode(raw,validate=True),False))
        else:raise ValueError('mode')
    except BaseException:
        sys.stderr.write('Credential codec failed; no plaintext was saved.\n')
        raise SystemExit(1)
