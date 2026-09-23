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
    assert "NoraServerSttClient" in js.text
    assert "streaming_stt_available" in js.text

    stt = client.get("/assets/server_stt.js")
    assert stt.status_code == 200
    assert "NoraServerSttClient" in stt.text
    assert "AudioWorkletNode" in stt.text
    assert 'type: "commit"' in stt.text
    assert 'type: "reconnect"' in stt.text
    assert "reconcileAfterReconnect" in stt.text
    assert "maxReconnectAttempts" in stt.text
    assert "inFlight" in stt.text

    tts = client.get("/assets/server_tts.js")
    assert tts.status_code == 200
    assert "NoraServerTtsPlayer" in tts.text

    assert "/assets/server_stt.js" in home.text
    assert "/assets/server_tts.js" in home.text


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


def test_job_studio_and_assets_are_served():
    client = TestClient(app)

    page = client.get("/studio")
    assert page.status_code == 200
    assert "Job & Rubric Studio" in page.text
    assert "Human approval boundary" in page.text

    css = client.get("/assets/studio.css")
    assert css.status_code == 200
    assert ".studio-grid" in css.text

    js = client.get("/assets/studio.js")
    assert js.status_code == 200
    assert "/v1/rubrics/draft" in js.text
    assert "/v1/rubrics/drafts/" in js.text
    assert "/approve" in js.text
    assert 'jsonFetch("/v1/jobs"' not in js.text
    assert "\\n\\nconst state" not in js.text
