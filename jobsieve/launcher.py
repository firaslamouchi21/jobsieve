import importlib.util
import os
import subprocess
import sys
import threading
import time
import webbrowser


def missing_extras() -> list[str]:
    needed = {"uvicorn": "api", "fastapi": "api", "streamlit": "ui"}
    return sorted({extra for module, extra in needed.items() if importlib.util.find_spec(module) is None})


def start(api_port: int = 8000, ui_port: int = 8501, open_browser: bool = True) -> int:
    missing = missing_extras()
    if missing:
        print(f"missing pieces: pip install \"jobsieve[{','.join(missing)}]\"", file=sys.stderr)
        return 2
    app_file = importlib.util.find_spec("jobsieve.app").origin
    # Streamlit reads its theme from the working directory.
    theme_dir = os.path.join(os.path.dirname(os.path.abspath(app_file)), "data")

    env = {
        **os.environ,
        "DATA_DIR": os.path.abspath(os.environ.get("DATA_DIR", "./data")),
        "CONFIG_DIR": os.path.abspath(os.environ.get("CONFIG_DIR", "./config")),
        "SCRAPER_URL": f"http://127.0.0.1:{api_port}",
    }
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "jobsieve.api:api", "--host", "127.0.0.1", "--port", str(api_port)], env=env
    )
    ui = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", app_file, "--server.port", str(ui_port), "--server.headless", "true",
         "--server.address", "127.0.0.1"],
        env=env,
        cwd=theme_dir,
    )
    address = f"http://127.0.0.1:{ui_port}"
    print(f"Jobsieve is starting. Open {address} (Ctrl+C to stop)", file=sys.stderr)
    if open_browser:
        threading.Timer(4.0, lambda: webbrowser.open(address)).start()
    try:
        while api.poll() is None and ui.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in (api, ui):
            if process.poll() is None:
                process.terminate()
        for process in (api, ui):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0
