"""Byte-transparent stdio proxy for the installed server; never emits MCP messages."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def main():
    transcript, stderr, executable = sys.argv[1:]
    lock = threading.Lock()
    with Path(transcript).open('x') as log, Path(stderr).open('x') as err:
        child = subprocess.Popen([executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err)

        def forward(source, destination, direction):
            while True:
                data = os.read(source, 65536)
                if not data:
                    break
                with lock:
                    log.write(json.dumps(dict(direction=direction, bytes=base64.b64encode(data).decode(),
                                              monotonic=time.monotonic()))+'\n')
                    log.flush()
                view = memoryview(data)
                while view:
                    view = view[os.write(destination, view):]
            if direction == 'client':
                child.stdin.close()

        reader = threading.Thread(target=forward, args=(0, child.stdin.fileno(), 'client'), daemon=True)
        reader.start()
        forward(child.stdout.fileno(), 1, 'server')
        sys.exit(child.wait())


if __name__ == '__main__':
    main()
