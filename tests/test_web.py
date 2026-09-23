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


def test_review_console_and_assets_are_served():
    client = TestClient(app)

    page = client.get("/review")
    assert page.status_code == 200
    assert "Evidence Review Console" in page.text
    assert "queue" in page.text

    css = client.get("/assets/review.css")
    assert css.status_code == 200
    assert ".review-grid" in css.text

    js = client.get("/assets/review.js")
    assert js.status_code == 200
    assert "/v1/review/queue" in js.text
    assert "/v1/review/sessions/" in js.text
