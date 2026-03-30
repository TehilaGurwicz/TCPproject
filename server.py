# server.py
'''
Enabling real GPT calls (optional):
1. Install deps: pip install -r requirements.txt.
2. Create a .env file with OPENAI_API_KEY=... .
3. Replace call_gpt() in server.py with the real implementation shown in the comments, or keep the stub.
'''
import argparse, socket, json, time, threading, math, os, ast, operator, collections
from typing import Any, Dict
from google import genai


# ---------------- LRU Cache (simple) ----------------
class LRUCache:
    """Minimal LRU cache based on OrderedDict."""
    def __init__(self, capacity: int = 128):
        self.capacity = capacity
        self._d = collections.OrderedDict()  # maintain order for LRU eviction

    def get(self, key):
        """Return value if exists, and mark as recently used."""
        if key not in self._d:
            return None
        self._d.move_to_end(key)
        return self._d[key]

    def set(self, key, value):
        """Set value and evict oldest if over capacity."""
        self._d[key] = value
        self._d.move_to_end(key)
        if len(self._d) > self.capacity:
            self._d.popitem(last=False)

# ---------------- Safe Math Eval (no eval) ----------------
# Allowed math functions and constants
_ALLOWED_FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "sqrt": math.sqrt,
    "log": math.log, "exp": math.exp, "max": max, "min": min, "abs": abs,
}
_ALLOWED_CONSTS = {"pi": math.pi, "e": math.e}

# Allowed AST operators for safe evaluation
_ALLOWED_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
}

def _eval_node(node):
    """Evaluate a restricted AST node safely, without using eval()."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("illegal constant type")
    if hasattr(ast, "Num") and isinstance(node, ast.Num):  # legacy fallback
        return node.n
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_CONSTS:
            return _ALLOWED_CONSTS[node.id]
        raise ValueError(f"unknown symbol {node.id}")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPS:
        return _ALLOWED_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ValueError("illegal function call")
        args = [_eval_node(a) for a in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)
    raise ValueError("illegal expression")

def safe_eval_expr(expr: str) -> float:
    """Parse and safely evaluate a math expression string."""
    tree = ast.parse(expr, mode="eval")
    return float(_eval_node(tree.body))


def call_gpt(prompt: str) -> str:

    #for good practice we would locate api key inside of .env file to hid it (but we trust you)
    OPENAI_API_KEY = OPENAI_API_KEY = os.environ.get("GEMINI_API_KEY")

    client = genai.Client(api_key=OPENAI_API_KEY)
    response = client.models.generate_content(model="gemini-2.5-flash",contents=prompt)
    return (response.text)


# ---------------- Server core ----------------
def handle_request(msg: Dict[str, Any], cache: LRUCache) -> Dict[str, Any]:
    """
    Process a single client request.
    Supports 'calc' and 'gpt' modes.
    Handles cache lookups and records execution time.
    """
    mode = msg.get("mode")
    data = msg.get("data") or {}
    options = msg.get("options") or {}
    use_cache = bool(options.get("cache", True))

    started = time.time()
    cache_key = json.dumps(msg, sort_keys=True)

    if use_cache:
        hit = cache.get(cache_key)
        if hit is not None:
            return {"ok": True, "result": hit, "meta": {"from_cache": True, "took_ms": int((time.time()-started)*1000)}}

    try:
        if mode == "calc":
            expr = data.get("expr")
            if not expr or not isinstance(expr, str):
                return {"ok": False, "error": "Bad request: 'expr' is required (string)"}
            res = safe_eval_expr(expr)
        elif mode == "gpt":
            prompt = data.get("prompt")
            if not prompt or not isinstance(prompt, str):
                return {"ok": False, "error": "Bad request: 'prompt' is required (string)"}
            res = call_gpt(prompt)
        else:
            return {"ok": False, "error": "Bad request: unknown mode"}

        took = int((time.time()-started)*1000)
        if use_cache:
            cache.set(cache_key, res)
        return {"ok": True, "result": res, "meta": {"from_cache": False, "took_ms": took}}
    except Exception as e:
        return {"ok": False, "error": f"Server error: {e}"}

def serve(host: str, port: int, cache_size: int):
    """Main server loop: listens for connections and spawns threads for each client."""
    cache = LRUCache(cache_size)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(16)
        print(f"[server] listening on {host}:{port} (cache={cache_size})")
        while True:
            conn, addr = s.accept()
            # Spawn a new thread for each client connection
            threading.Thread(target=handle_client, args=(conn, addr, cache), daemon=True).start()

def handle_client(conn: socket.socket, addr, cache: LRUCache):
    """Handles communication with a single client in a thread."""
    try:
        raw = b""
        while True:
            chunk = conn.recv(4096)  # read data from client
            if not chunk:
                break  # client disconnected
            raw += chunk
            while b"\n" in raw:
                line, _, rest = raw.partition(b"\n")
                raw = rest
                msg = json.loads(line.decode("utf-8"))

                # handle client quit request
                if msg.get("mode") == "quit":
                    conn.sendall(b'{"ok": true, "msg": "bye"}\n')
                    return  # close connection

                # process normal request
                resp = handle_request(msg, cache)
                out = (json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8")
                conn.sendall(out)
    except Exception as e:
        # send error response if message malformed
        try:
            conn.sendall((json.dumps({"ok": False, "error": f"Malformed: {e}"}) + "\n").encode("utf-8"))
        except Exception:
            pass

def main():
    # Parse command-line arguments
    ap = argparse.ArgumentParser(description="JSON TCP server (calc/gpt) — student skeleton")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5555)
    ap.add_argument("--cache-size", type=int, default=128)
    args = ap.parse_args()
    serve(args.host, args.port, args.cache_size)

if __name__ == "__main__":
    main()
