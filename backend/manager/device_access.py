"""Private-interface access; pairing is optional legacy compatibility.

No forwarded headers are trusted. The default trusts configured private
interfaces without a cookie. Optional legacy sessions are memory-only and
revoked on restart. Public network adapters are never bound.
"""
import hashlib
import ipaddress
import secrets
import socket
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"))
COOKIE = "novel_device"
SESSION_SECONDS = 30 * 24 * 3600


def private_address(value):
    try:
        address = ipaddress.ip_address(value)
        return any(address in network for network in NETWORKS)
    except ValueError:
        return False


def local_addresses():
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        return []
    return sorted(address for address in addresses if private_address(address))[:8]


def listen_sockets(hosts, port):
    sockets = []
    try:
        for host in dict.fromkeys(hosts):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(sock)
            # Windows SO_REUSEADDR permits a second listener to hijack the port.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind((host, port))
            sock.listen(128)
            sock.setblocking(False)
        return sockets
    except BaseException:
        for sock in sockets:
            sock.close()
        raise


class PairInput(BaseModel):
    code: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")
    name: str = Field(default="我的设备", min_length=1, max_length=40)


class DeviceAccess:
    def __init__(self, hosts=(), port=8765, pairing_required=False):
        self.hosts = tuple(hosts)
        self.port = port
        self.pairing_required = pairing_required
        self.sessions = {}
        self.code = ""
        self.code_expires = 0
        # 按 IP 统计配对失败次数：旧的全局计数器允许任意未配对设备
        # 每分钟 10 次坏码把合法设备的配对请求永久 429。
        self.attempts = {}
        self.lock = threading.RLock()

    def local(self, request):
        peer = request.client.host if request.client else ""
        # testclient is an in-process transport, never a real TCP source address.
        if peer == "testclient":
            return True
        try:
            return ipaddress.ip_address(peer).is_loopback
        except ValueError:
            return False

    def require_local(self, request):
        if not self.local(request):
            raise HTTPException(403, "请在运行小说助手的电脑上管理设备")

    def prune(self):
        now = time.time()
        self.sessions = {key: item for key, item in self.sessions.items() if item["expires_at"] > now}
        self.attempts = {
            ip: [stamp for stamp in stamps if stamp > now - 60]
            for ip, stamps in self.attempts.items()
            if any(stamp > now - 60 for stamp in stamps)
        }

    def authenticated(self, request):
        token = request.cookies.get(COOKIE, "")
        if not token or len(token) > 128:
            return False
        with self.lock:
            self.prune()
            record = self.sessions.get(hashlib.sha256(token.encode()).hexdigest())
            if not record:
                return False
            # 会话与配对时的来源 IP 绑定：明文 LAN 下 cookie 被嗅探/重放时
            # 仅凭令牌不足以从其他设备使用（Tailscale/LAN 地址稳定）。
            peer = request.client.host if request.client else ""
            if record.get("ip") and peer and record["ip"] != peer:
                return False
            return True

    def guard(self, request):
        if self.local(request):
            return None
        peer = request.client.host if request.client else ""
        if not self.hosts or not private_address(peer):
            return JSONResponse({"detail": "仅开放给局域网与 Tailscale 设备"}, status_code=403)
        if not self.pairing_required:
            # Explicit author policy: the private network is the trust boundary.
            # TrustedHost and same-origin/custom-header write checks still apply.
            return None
        public = {"/pair", "/api/health", "/api/access/pair", "/static/pair.js", "/static/style.css", "/static/editorial.css"}
        if request.url.path in public or self.authenticated(request):
            return None
        if request.url.path == "/":
            return RedirectResponse("/pair", status_code=303, headers={"Cache-Control": "no-store"})
        return JSONResponse({"detail": "设备尚未配对或登录已失效，请重新配对"}, status_code=401, headers={"Cache-Control": "no-store"})

    def status(self, request):
        with self.lock:
            self.prune()
            local = self.local(request)
            return {"local": local, "enabled": bool(self.hosts),
                    "pairing_required": self.pairing_required,
                    "access_mode": "paired" if self.pairing_required else "private_network",
                    "addresses": [{"url": f"http://{host}:{self.port}", "kind": "Tailscale" if host.startswith("100.") else "局域网"} for host in self.hosts] if local else [],
                    "devices": list(self.sessions.values()) if local else [],
                    "session_days": 30}


def install_routes(app, access, static: Path):
    @app.get("/pair", include_in_schema=False)
    def page():
        if not access.pairing_required:
            return RedirectResponse('/',status_code=303,headers={'Cache-Control':'no-store'})
        return FileResponse(static / "pair.html")

    @app.get("/api/access")
    def status(request: Request):
        return access.status(request)

    @app.post("/api/access/code")
    def create_code(request: Request):
        access.require_local(request)
        if not access.pairing_required:
            raise HTTPException(410, '当前为可信网络免配对访问，无需生成配对码')
        if not access.hosts:
            raise HTTPException(409, "尚未发现局域网或 Tailscale 地址，请连接后重新启动小说助手")
        with access.lock:
            access.code = f"{secrets.randbelow(100000000):08d}"
            access.code_expires = time.time() + 600
            return {"code": access.code, "expires_at": access.code_expires}

    @app.post("/api/access/pair")
    def pair(request: Request, data: PairInput):
        if not access.pairing_required:
            raise HTTPException(410, '当前为可信网络免配对访问，请直接打开首页')
        peer = request.client.host if request.client else ""
        with access.lock:
            access.prune()
            recent = access.attempts.get(peer, [])
            if len(recent) >= 10:
                raise HTTPException(429, "配对尝试过于频繁，请一分钟后再试")
            access.attempts.setdefault(peer, []).append(time.time())
            if time.time() >= access.code_expires or not access.code or not secrets.compare_digest(data.code, access.code):
                raise HTTPException(401, "配对码不正确或已过期，请在电脑上重新生成")
            if len(access.sessions) >= 32:
                raise HTTPException(409, "已连接设备过多，请在电脑上移除旧设备")
            token = secrets.token_urlsafe(32)
            record = {"id": secrets.token_hex(12), "name": data.name.strip() or "我的设备",
                      "ip": peer, "created_at": time.time(), "expires_at": time.time() + SESSION_SECONDS}
            access.sessions[hashlib.sha256(token.encode()).hexdigest()] = record
            access.code = ""
            access.code_expires = 0
        response = JSONResponse({"paired": True})
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https", max_age=SESSION_SECONDS, path="/")
        return response

    @app.delete("/api/access/devices/{identity}")
    def revoke(request: Request, identity: str):
        access.require_local(request)
        if not access.pairing_required:
            raise HTTPException(409, '免配对模式按网络授权；请通过防火墙或Tailscale访问规则限制设备')
        with access.lock:
            access.sessions = {key: item for key, item in access.sessions.items() if item["id"] != identity}
        return {"revoked": True}

    @app.post("/api/access/logout")
    def logout(request: Request):
        if not access.pairing_required:
            return {'logged_out':False,'pairing_required':False,'message':'当前按可信网络授权，无需设备登录'}
        with access.lock:
            access.sessions.pop(hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(), None)
        response = JSONResponse({"logged_out": True})
        response.delete_cookie(COOKIE, path="/")
        return response
