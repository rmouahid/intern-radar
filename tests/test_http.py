import httpx

from intern_radar.http import USER_AGENT, Throttle, make_client


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_throttle_spaces_requests_to_the_same_host():
    clock = FakeClock()
    throttle = Throttle(interval=1.0, clock=clock, sleep=clock.sleep)
    throttle(httpx.Request("GET", "https://a.example/1"))
    clock.now += 0.25
    throttle(httpx.Request("GET", "https://a.example/2"))
    throttle(httpx.Request("GET", "https://b.example/1"))
    assert clock.sleeps == [0.75]


def test_make_client_sets_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200, json={})

    client = make_client(Throttle(interval=0), httpx.MockTransport(handler))
    client.get("https://a.example/")
    assert seen["ua"] == USER_AGENT
