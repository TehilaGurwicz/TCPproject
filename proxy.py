# proxy.py
import argparse, socket, threading, json
from server import LRUCache

# Initialize a local cache using LRU strategy with a capacity of 128 items
cache = LRUCache(capacity=128)

def pipe(src, dst):
    """
    Bi-directional byte piping helper.
    Continuously reads data from `src` and forwards it to `dst`.
    Used for setting up a thread-based data forwarding.
    """
    try:
        while True:
            data = src.recv(4096)  # read up to 4096 bytes
            if not data:
                break
            print("data transfer on proxy server")
            dst.sendall(data)  # forward data to destination
    except Exception:
        pass
    finally:
        # Shutdown writing side of the socket safely
        try: dst.shutdown(socket.SHUT_WR)
        except Exception: pass


def main():
    # Parse command-line arguments
    ap = argparse.ArgumentParser(description="Transparent TCP proxy (optional)")
    ap.add_argument("--listen-host", default="127.0.0.1")
    ap.add_argument("--listen-port", type=int, default=5554)
    ap.add_argument("--server-host", default="127.0.0.1")
    ap.add_argument("--server-port", type=int, default=5555)
    args = ap.parse_args()

    # Create persistent socket connection to backend server
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server_socket.connect((args.server_host, args.server_port))
        print(f"[proxy] Connected to server {args.server_host}:{args.server_port}")
    except Exception as e:
        print(f"[proxy] Error connecting to server: {e}")
        return

    # Create listening socket for clients
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.listen_host, args.listen_port))
        s.listen(16)  # allow up to 16 pending connections
        print(f"[proxy] Listening on {args.listen_host}:{args.listen_port}")

        # Main loop to accept client connections
        while True:
            try:
                c, addr = s.accept()  # accept a new client
                print(f"[proxy] Accepted connection from {addr}")

                # Inner loop to handle multiple requests from the same client
                while True:
                    try:
                        data = c.recv(4096)
                        if not data:
                            break  # client closed connection

                        payload = json.loads(data.decode("utf-8"))  # parse JSON request
                        cache_key = json.dumps(payload, sort_keys=True)  # normalize key
                        hit = cache.get(cache_key)  # check if response exists in cache

                        if hit is not None:
                            # Return cached response to client
                            response = {"ok": True, "result": hit, "meta": {"from_cache": True}}
                            c.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))

                        else:
                            # Forward request to backend server
                            try:
                                server_socket.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

                                buff = b""
                                while True:
                                    chunk = server_socket.recv(4096)
                                    if not chunk:
                                        break
                                    buff += chunk
                                    if b"\n" in buff:
                                        line, _, _ = buff.partition(b"\n")
                                        resp = json.loads(line.decode("utf-8"))
                                        cache.set(cache_key, resp.get("result"))  # cache the result
                                        c.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                                        break
                            except Exception as e:
                                # Error communicating with backend server
                                error_resp = {"ok": False, "error": f"Server communication error: {e}"}
                                c.sendall((json.dumps(error_resp) + "\n").encode("utf-8"))

                    except Exception as e:
                        # Handle any proxy-level errors and notify client
                        try:
                            c.sendall((json.dumps({"ok": False, "error": f"Proxy error: {e}"}) + "\n").encode("utf-8"))
                        except Exception:
                            pass
                        break
            except Exception as e:
                # Error accepting a client connection, continue listening
                print(f"[proxy] Error accepting client connection: {e}")
                continue


def handle(c, s, sh):
    """
    Threaded helper to pipe data between client and server sockets.
    Currently not used in main loop, kept for possible async proxy design.
    """
    try:
        t1 = threading.Thread(target=pipe, args=(c, s), daemon=True)
        t2 = threading.Thread(target=pipe, args=(s, c), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    except Exception as e:
        try: c.sendall((json.dumps({"ok": False, "error": f"Proxy error: {e}"})+"\n").encode("utf-8"))
        except Exception: pass


if __name__ == "__main__":
    main()
