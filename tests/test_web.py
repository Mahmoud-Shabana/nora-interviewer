from fastapi.testclient import TestClient

from nora_interviewer.api import app


def test_interview_room_and_assets_are_served():
    client = TestClient(app)
    home = client.get("/")
    assert home.status_code == 200
    assert "Nora Interviewer" in home.text
    assert "setupForm" in home.text

    css = client.get("/assets/styles.css")
    assert css.status_code == 200
    assert "--accent" in css.text

    js = client.get("/assets/app.js")
    assert js.status_code == 200
    assert "candidate_text" in js.text
