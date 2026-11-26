"""Mensageiro dos atalhos do Hyprland: o compositor executa este script a cada tecla de atalho
(ou clique, quando o efeito de clique não tem acesso a /dev/input) e ele avisa o GCP Capture Studio
pelo socket local. Executado com `python3 -I -S`, sem importar nada além da biblioteca padrão,
para responder em poucos milissegundos.

Uso: hyprsend.py <socket do programa> <mensagem>

Se o programa não estiver mais aberto (fechou de forma inesperada), remove os atalhos que ele
deixou registrados no Hyprland, para a tecla voltar a funcionar normalmente.
"""
import errno
import json
import os
import socket
import sys


def _send(path: str, message: str) -> bool | None:
    """True: entregue. False: o programa não está aberto. None: falha passageira (não limpa nada)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(path)
            s.sendall(message.encode("utf-8") + b"\n")
        return True
    except OSError as exc:
        if exc.errno in (errno.ECONNREFUSED, errno.ENOENT):
            return False
        return None


def _hypr(cmd: str) -> None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    for base in (os.path.join(runtime, "hypr"), "/tmp/hypr"):
        path = os.path.join(base, sig, ".socket.sock")
        if not os.path.exists(path):
            continue
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(path)
                s.sendall(cmd.encode("utf-8"))
                s.recv(4096)
        except OSError:
            pass
        return


def _cleanup() -> None:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or os.path.expanduser("~/.cache")
    for ns in ("keys", "mouse"):
        state = os.path.join(runtime, f"gcp-capture-studio-hyprland-{ns}.json")
        try:
            with open(state, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if data.get("lua"):
            table = data.get("table") or f"gcp_capture_binds_{ns}"
            if table.replace("_", "").isalnum():
                _hypr(f"/eval for _, b in ipairs({table} or {{}}) do pcall(function() b:remove() end) end; {table} = {{}}")
        else:
            for combo in data.get("unbind") or []:
                _hypr(f"/keyword unbind {combo}")
        try:
            os.remove(state)
        except OSError:
            pass


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        return 2
    sent = _send(argv[1], argv[2])
    if sent:
        return 0
    if sent is False:
        _cleanup()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
