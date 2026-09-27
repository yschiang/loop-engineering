"""Fake GitHub and runtime adapters with fault injection (test support only)."""

from delivery.outbox import ResponseUnknown


class Crash(BaseException):
    """Simulated controller process death; escapes every except Exception."""


class FakeGitHub:
    def __init__(self, faults=None):
        self.comments = {}  # target -> [body]
        self.faults = list(faults or [])  # per post: "ok" | "lost" (applied, response lost) | "error" (not applied)
        self.lookup_faults = []
        self.posts = 0

    def post_comment(self, target, body):
        self.posts += 1
        fault = self.faults.pop(0) if self.faults else "ok"
        if fault == "error":
            raise ResponseUnknown("503")
        self.comments.setdefault(target, []).append(body)
        if fault == "lost":
            raise ResponseUnknown("connection reset after write")
        if fault == "crash":
            raise Crash()
        return {"id": len(self.comments[target]), "url": f"https://gh/{target}#c{len(self.comments[target])}"}

    def find_comment(self, target, marker):
        if self.lookup_faults and self.lookup_faults.pop(0) == "error":
            raise ResponseUnknown("lookup 502")
        for i, body in enumerate(self.comments.get(target, []), 1):
            if marker in body:
                return {"id": i, "url": f"https://gh/{target}#c{i}"}
        return None


class FakeRuntime:
    def __init__(self, faults=None, consistent=True, stop_confirms=True):
        self.sessions = {}  # id -> {"title": str, "messages": [..]}
        self.faults = dict(faults or {})  # call name -> "lost" | "crash_before" | "crash_after" | "drop"
        self.session_list_consistent = consistent
        self.stop_confirms = stop_confirms
        self.creates = self.sends = self.stops = 0

    def _fault(self, name, phase):
        f = self.faults.get(name)
        if f == f"crash_{phase}":
            del self.faults[name]
            raise Crash()
        if phase == "after" and f == "lost":
            del self.faults[name]
            raise ResponseUnknown(f"{name} response lost")

    def create_session(self, title):
        self._fault("create", "before")
        self.creates += 1
        sid = f"s{len(self.sessions) + 1}"
        self.sessions[sid] = {"title": title, "messages": []}
        self._fault("create", "after")
        return sid

    def find_sessions(self, marker):
        return [sid for sid, s in self.sessions.items() if marker in s["title"]]

    def send_prompt(self, session, text):
        self._fault("send", "before")
        self.sends += 1
        if self.faults.get("send") == "drop":  # request lost before the runtime accepted it
            del self.faults["send"]
            raise ResponseUnknown("prompt timeout")
        mid = f"m{len(self.sessions[session]['messages']) + 1}"
        self.sessions[session]["messages"].append({"id": mid, "role": "user", "text": text})
        self._fault("send", "after")
        return mid

    def list_messages(self, session):
        return list(self.sessions[session]["messages"])

    def stop(self, session):
        self.stops += 1
        return self.stop_confirms
