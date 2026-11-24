"""Windows 当前用户 DPAPI 编解码器。敏感内容只经 stdio 传输，不落盘、不进日志。

调用契约（Node 侧 credentials.mjs 与 ofm_runtime.verify_credential_codec 都按它工作）：

- ``encrypt``：stdin 读明文，stdout 写 base64 密文；
- ``decrypt``：stdin 读 base64 密文，stdout 写明文；
- ``probe``：不读写业务数据，只做一次当前用户 DPAPI 的加解密往返，成功时 stdout 写 ``ok``。

三种模式都使用 CryptProtectData/CryptUnprotectData 的 current-user 作用域（dwFlags=1，
即 UI_FORBIDDEN、不弹窗），因此只有同一个 Windows 用户能解开密文；探针失败说明账号或
系统环境不可用，此时调用方必须保持旧密文原样，不得把凭据重置为空。
"""
import base64
import ctypes
import os
import sys
from ctypes import wintypes

MAX_INPUT = 8 * 1024 * 1024
PROBE_SIZE = 32


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def transform(raw, encrypt=True):
    """在 current-user DPAPI 作用域内加密或解密一段字节。"""
    if os.name != 'nt':
        raise RuntimeError('需要 Windows DPAPI（当前系统不支持），凭据未保存')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    crypt = ctypes.windll.crypt32
    operation = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError('当前 Windows 账户无法使用凭据保护，旧凭据未被改动')
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


def probe():
    """当前用户 DPAPI 往返自检：只返回布尔值，不输出密钥或明文。"""
    if os.name != 'nt':
        return False
    try:
        sample = os.urandom(PROBE_SIZE)
        return transform(transform(sample, True), False) == sample
    except BaseException:
        return False


def main(argv=None):
    """进程入口：成功返回 0，失败返回 1；错误信息只写 stderr。"""
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        mode = args[0] if args else ''
        if mode == 'probe':
            if not probe():
                raise RuntimeError('当前 Windows 账户无法完成 DPAPI 加解密自检，旧凭据未被改动')
            sys.stdout.write('ok')
            sys.stdout.flush()
            return 0
        if mode not in ('encrypt', 'decrypt'):
            raise ValueError('未知的编解码模式')
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('凭据内容超过大小上限')
        if mode == 'encrypt':
            sys.stdout.buffer.write(base64.b64encode(transform(raw, True)))
        else:
            sys.stdout.buffer.write(transform(base64.b64decode(raw, validate=True), False))
        sys.stdout.buffer.flush()
        return 0
    except BaseException as error:
        message = str(error) or error.__class__.__name__
        sys.stderr.write(f'凭据编解码失败：{message}；未写入任何明文，旧凭据未被改动\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
