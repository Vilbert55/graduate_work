import argparse
import json
import statistics
import sys
import time
import urllib.request


BASE_URL = ""
ITERATIONS = 100


def _get(path):
    """GET-запрос и разбор JSON."""
    req = urllib.request.Request(f"{BASE_URL}{path}")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def _post(path, data):
    """POST-запрос с телом JSON."""
    data_bytes = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data_bytes,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def _time_get(path):
    """Возвращает время GET-запроса в секундах."""
    t0 = time.perf_counter()
    _get(path)
    return time.perf_counter() - t0


def _time_post(path, data):
    """Возвращает время POST-запроса в секундах."""
    t0 = time.perf_counter()
    _post(path, data)
    return time.perf_counter() - t0


def _random_id(kind):
    """Случайный идентификатор (user/movie/review)."""
    return _get(f"/random/{kind}")["id"]


def _percentile(sorted_data, p):
    n = len(sorted_data)
    k = (p / 100) * (n - 1)
    f = int(k)
    c = k - f
    if f + 1 < n:
        return sorted_data[f] + c * (sorted_data[f + 1] - sorted_data[f])
    return sorted_data[f]


def _run(test_name, url_func, write_mode=False, data_func=None):
    """Общий измеритель: для GET (write_mode=False) или POST (write_mode=True)."""
    print(f"\n=== {test_name} ===")
    times = []
    for i in range(ITERATIONS):
        if write_mode:
            url = "/film_score"
            data = data_func()
            t = _time_post(url, data)
        else:
            url = url_func()
            t = _time_get(url)
        times.append(t)
        if (i + 1) % 100 == 0:
            print(f"  Progress: {i + 1}/{ITERATIONS}")

    sorted_times = sorted(times)
    avg = statistics.mean(times)
    med = statistics.median(times)
    p95 = _percentile(sorted_times, 95)
    p99 = _percentile(sorted_times, 99)
    print(f"  Average: {avg * 1000:.2f} ms")
    print(f"  Median:  {med * 1000:.2f} ms")
    print(f"  P95:     {p95 * 1000:.2f} ms")
    print(f"  P99:     {p99 * 1000:.2f} ms")
    print(f"  Min:     {sorted_times[0] * 1000:.2f} ms")
    print(f"  Max:     {sorted_times[-1] * 1000:.2f} ms")
    return times


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()

    global BASE_URL, ITERATIONS
    BASE_URL = args.base_url.rstrip("/")
    ITERATIONS = args.iterations

    # Здоровье
    try:
        if _get("/health")["status"] != "ok":
            sys.exit("Service not healthy.")
    except Exception as e:
        sys.exit(f"Health check failed: {e}")

    print(f"Testing {BASE_URL} ({ITERATIONS} iterations each)…")

    # Функции – генераторы URL для тестов чтения
    def user_likes_url():
        return f"/user/{_random_id('user')}/likes"

    def movie_stats_url():
        return f"/movie/{_random_id('movie')}/stats"

    def bookmarks_url():
        return f"/user/{_random_id('user')}/bookmarks"

    # Чтение
    _run("User Likes", user_likes_url)
    _run("Movie Stats", movie_stats_url)
    _run("User Bookmarks", bookmarks_url)

    # Запись (оценка фильма)
    def score_data():
        return {
            "user_id": _random_id("user"),
            "movie_id": _random_id("movie"),
            "score": 7
        }
    _run("Write Film Score", None, write_mode=True, data_func=score_data)

    # Консистентность
    print("\n=== Write-Read Consistency ===")
    uid = _random_id("user")
    mid = _random_id("movie")
    before = _get(f"/movie/{mid}/stats")
    _post("/film_score", {"user_id": uid, "movie_id": mid, "score": 10})
    after = _get(f"/movie/{mid}/stats")
    diff = after["likes"] - before["likes"]
    print(f"  Likes before: {before['likes']}, after: {after['likes']}, change: {diff}")
    if diff == 1:
        print("Сonsistency - OK.")
    else:
        print("Сonsistency ERROR")

    print("\nBenchmark finished.")


if __name__ == "__main__":
    main()
