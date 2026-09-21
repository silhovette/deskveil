"""Real two-process capture, producer handover, restart and final release.

Run with DeskVeil/peeker stopped. No frame is displayed or saved.
"""
from pathlib import Path
import multiprocessing as mp
import queue
import sys
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def client(name, namespace, stop, reports):
    from detection.shared_camera import SharedCamera
    camera = SharedCamera(namespace=namespace)
    frames = 0
    last_report = 0
    try:
        while not stop.is_set():
            ok, frame = camera.read()
            if ok and time.monotonic() - camera.timestamp <= .8:
                frames += 1
            if time.monotonic() - last_report > .3:
                reports.put((name, frames, camera.producer))
                last_report = time.monotonic()
            time.sleep(.02)
    finally:
        camera.release()


def main():
    ctx = mp.get_context("spawn")
    reports = ctx.Queue()
    namespace = "DeskVeilTest" + uuid.uuid4().hex
    processes, stops, latest = [], [], {}

    def start(name):
        stop = ctx.Event()
        process = ctx.Process(target=client, args=(name, namespace, stop, reports))
        process.start()
        processes.append(process)
        stops.append(stop)
        return process, stop

    def wait_for(predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                name, frames, producer = reports.get(timeout=.3)
                latest[name] = frames, producer
            except queue.Empty:
                continue
            if predicate():
                return
        raise AssertionError(latest)

    try:
        a, stop_a = start("A")
        wait_for(lambda: latest.get("A", (0,))[0] >= 30)
        b, stop_b = start("B")
        wait_for(lambda: latest.get("B", (0,))[0] >= 80)
        assert latest["A"][1] and not latest["B"][1], latest
        print("Concurrent capture:", latest, flush=True)
        old_frames = latest["B"][0]
        stop_a.set()
        a.join(8)
        assert a.exitcode == 0
        wait_for(lambda: latest["B"][1] and latest["B"][0] >= old_frames + 50)
        print("Producer handover:", latest["B"], flush=True)
        a2, stop_a2 = start("A2")
        wait_for(lambda: latest.get("A2", (0,))[0] >= 60)
        assert not latest["A2"][1], latest
        print("Restart joined existing capture:", latest["A2"], flush=True)
    finally:
        for stop in stops:
            stop.set()
        for process in processes:
            process.join(8)
            if process.is_alive():
                process.terminate()
                process.join()
    assert all(p.exitcode == 0 for p in processes)
    from detection.shared_camera import SharedCamera
    camera = SharedCamera(namespace=namespace)
    try:
        ok, frame = camera.read()
        assert ok and camera.producer
    finally:
        camera.release()
    print("PASS: both clients exited, camera can be acquired again")


if __name__ == "__main__":
    main()
