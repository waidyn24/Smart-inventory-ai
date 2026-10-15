"""Start and supervise the colocated FastAPI and Next.js processes."""
import os
import signal
import subprocess
import sys
import time

procs = []
stopping = False

def stop(_sig=None, _frame=None):
    global stopping
    stopping = True
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

api_env = os.environ.copy()
web_env = os.environ.copy()
web_env.setdefault('PORT', '3000')
web_env['HOSTNAME'] = '0.0.0.0'

try:
    procs.append(subprocess.Popen(
        ['uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
        cwd='/app/backend', env=api_env,
    ))
    procs.append(subprocess.Popen(
        ['node', 'server.js'], cwd='/app/web', env=web_env,
    ))
    while not stopping:
        for proc in procs:
            result = proc.poll()
            if result is not None:
                print(f'Child {proc.pid} stopped with code {result}; shutting down.', flush=True)
                raise SystemExit(result if result != 0 else 1)
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    stop()
    for proc in procs:
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
