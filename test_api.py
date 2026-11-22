import os, sys, tempfile, unittest
os.environ["EDUBRIDGE_NO_AUTOAPP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app

PW = "correct-horse"

class Api(unittest.TestCase):
    def setUp(self):
        self.app = create_app(os.path.join(tempfile.mkdtemp(), "t.db")); self.c = self.app.test_client()

    def call(self, method, url, tok=None, **json):
        r = getattr(self.c, method)(url, json=json or None, headers={"Authorization": f"Bearer {tok}"} if tok else {})
        return r.status_code, r.get_json()

    def signup(self, name, email, role, **extra):
        code, d = self.call("post", "/api/register", name=name, email=email, password=PW, role=role, **extra)
        self.assertEqual(code, 201, d); return d["token"], d["user"]

    def test_frontend_and_health_are_served(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertIn(b"EduBridge", self.c.get("/").data)
        for f in ("app.js", "style.css"): self.assertEqual(self.c.get("/static/" + f).status_code, 200)
        self.assertEqual(self.call("get", "/api/health")[1], {"status": "ok"})

    def test_register_login_logout(self):
        tok, u = self.signup("Asha", "Asha@Example.com", "student")
        self.assertEqual(u["email"], "asha@example.com")
        self.assertEqual(self.call("post", "/api/register", name="X", email="asha@example.com", password=PW, role="student")[0], 409)
        self.assertEqual(self.call("post", "/api/register", name="X", email="x@e.co", password="short", role="student")[0], 400)
        self.assertEqual(self.call("post", "/api/login", email="asha@example.com", password="nope")[0], 401)
        code, d = self.call("post", "/api/login", email="ASHA@example.com", password=PW); self.assertEqual(code, 200)
        self.assertEqual(self.call("get", "/api/me", d["token"])[1]["user"]["name"], "Asha")
        self.call("post", "/api/logout", d["token"])
        self.assertEqual(self.call("get", "/api/me", d["token"])[0], 401)
        self.assertEqual(self.call("get", "/api/me")[0], 401)

    def test_passwords_and_tokens_are_not_stored_in_plain_text(self):
        tok, _ = self.signup("Asha", "a@e.co", "student")
        import sqlite3; c = sqlite3.connect(self.app.config["DB"])
        self.assertNotIn(PW, c.execute("SELECT password FROM users").fetchone()[0])
        self.assertNotEqual(tok, c.execute("SELECT token_hash FROM sessions").fetchone()[0])

    def test_tutor_search_and_profile_update(self):
        s, _ = self.signup("Stu", "s@e.co", "student")
        t, tu = self.signup("Ravi", "r@e.co", "tutor", skills="Python, SQL", city="Hyderabad")
        self.call("put", "/api/me", t, name="Ravi K", skills="Python, Math", bio="Hi", city="Hyderabad", rate="300")
        found = self.call("get", "/api/tutors?q=math", s)[1]["tutors"]
        self.assertEqual([x["name"] for x in found], ["Ravi K"]); self.assertEqual(found[0]["rate"], 300)
        self.assertNotIn("email", found[0])
        self.assertEqual(self.call("get", "/api/tutors?q=zzz", s)[1]["tutors"], [])

    def test_booking_workflow_and_permissions(self):
        s, _ = self.signup("Stu", "s@e.co", "student"); t, tu = self.signup("Ravi", "r@e.co", "tutor"); o, _ = self.signup("Other", "o@e.co", "tutor")
        self.assertEqual(self.call("post", "/api/bookings", t, tutor_id=str(tu["id"]), topic="x")[0], 403)   # tutors can't book
        self.assertEqual(self.call("post", "/api/bookings", s, tutor_id="999", topic="x")[0], 404)
        code, d = self.call("post", "/api/bookings", s, tutor_id=tu["id"], topic="Calculus", slot="Sat 5pm"); self.assertEqual(code, 201)
        bid = d["id"]
        self.assertEqual(self.call("post", f"/api/bookings/{bid}/status", o, status="Accepted")[0], 404)     # not your booking
        self.assertEqual(self.call("post", f"/api/bookings/{bid}/status", s, status="Accepted")[0], 409)    # student can't accept
        self.assertEqual(self.call("post", f"/api/bookings/{bid}/status", t, status="Accepted")[0], 200)
        self.assertEqual(self.call("post", f"/api/bookings/{bid}/status", t, status="Declined")[0], 409)    # already accepted
        self.assertEqual(self.call("post", f"/api/bookings/{bid}/status", t, status="Completed")[0], 200)
        self.assertEqual(self.call("get", "/api/bookings", s)[1]["bookings"][0]["other_name"], "Ravi")
        self.assertEqual(self.call("get", "/api/bookings", t)[1]["bookings"][0]["other_name"], "Stu")
        self.assertEqual(self.call("get", "/api/bookings", o)[1]["bookings"], [])

    def test_doubts_and_replies(self):
        s, _ = self.signup("Stu", "s@e.co", "student"); t, _ = self.signup("Ravi", "r@e.co", "tutor")
        self.assertEqual(self.call("post", "/api/doubts", t, subject="a", question="b")[0], 403)
        did = self.call("post", "/api/doubts", s, subject="Math", question="What is a limit?")[1]["id"]
        self.assertEqual(self.call("post", f"/api/doubts/{did}/replies", t, body="Approaching value")[0], 201)
        self.assertEqual(self.call("post", "/api/doubts/999/replies", t, body="x")[0], 404)
        d = self.call("get", "/api/doubts", s)[1]["doubts"][0]
        self.assertEqual((d["student_name"], d["replies"][0]["name"], d["replies"][0]["role"]), ("Stu", "Ravi", "tutor"))

    def test_html_is_stored_raw_and_json_errors_are_clean(self):
        s, _ = self.signup("<b>S</b>", "s@e.co", "student")
        self.assertEqual(self.call("get", "/api/me", s)[1]["user"]["name"], "<b>S</b>")    # escaping happens in the frontend
        self.assertEqual(self.c.post("/api/login", data="notjson").status_code, 400)
        self.assertEqual(self.c.get("/api/nothing").status_code, 404)

if __name__ == "__main__":
    unittest.main()
