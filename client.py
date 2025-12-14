# client.py
import argparse, socket, json, sys

def request(host: str, port: int, s: socket, payload: dict) -> dict:
    """
    Send a single JSON-line request and return a single JSON-line response.

    Parameters:
    - host: server host (unused in current code because socket is passed)
    - port: server port (unused)
    - s: a persistent TCP socket
    - payload: dictionary containing the request data

    Returns:
    - dictionary representing server response
    """
    # Convert payload dictionary to JSON string and encode to bytes
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

    # Send the request data over the socket
    s.sendall(data)

    buff = b""  # buffer to accumulate received bytes
    while True:
        chunk = s.recv(4096)  # receive data from socket
        if not chunk:          # connection closed
            break
        buff += chunk
        if b"\n" in buff:     # full JSON line received
            line, _, _ = buff.partition(b"\n")  # split at newline
            return json.loads(line.decode("utf-8"))  # parse JSON and return

    # If no response received, return error dictionary
    return {"ok": False, "error": "No response"}


def main():
    host = "127.0.0.1"
    port = 5554

    # Create a persistent socket connection to the server
    # This allows multiple requests without reconnecting each time
    s = socket.create_connection((host, port))

    # Interactive loop for user input
    while True:
        mode = input("gpt/calc/quit : ")  # ask user for mode

        if mode == "quit":  # exit condition
            print("exiting")
            s.sendall(b'{"mode": "quit"}\n')  # notify server
            s.close()  # close socket
            sys.exit(1)

        cache = input("Allow cache? [y/n]")  # ask if caching is allowed

        if mode == "calc":
            expr = input("Enter expression:")
            if not expr:
                print("Missing --expr", file=sys.stderr)
                sys.exit(2)
            # Build JSON payload for calc mode
            payload = {"mode": "calc", "data": {"expr": expr}, "options": {"cache": cache == "y"}}
        else:
            prompt = input("Enter prompt:")
            if not prompt:
                print("Missing --prompt", file=sys.stderr)
                sys.exit(2)
            # Build JSON payload for gpt mode
            payload = {"mode": "gpt", "data": {"prompt": prompt}, "options": {"cache": cache == "y"}}

        # Send request to server and receive response
        resp = request(host, port, s, payload)

        # Pretty-print the JSON response
        print(json.dumps(resp, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
